"""
ParkRent Bot — покупка, продажа, аренда парковок и гаражей в Варне
"""
import os
import logging
import sqlite3
import math
import urllib.request
import urllib.parse
import json
import re
import datetime
import asyncio
from contextlib import contextmanager

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

from messages import t, get_user_lang, set_user_lang, detect_telegram_lang

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID   = 5053888378

# ── Paths configuration (Railway Volumes) ─────────────────
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_FILE = os.path.join(DATA_DIR, "parking.db")
PERSISTENCE_FILE = os.path.join(DATA_DIR, "bot_persistence.pkl")

PAGE_SIZE  = 10
MAX_LISTINGS_PER_USER = 15  # Лимит объявлений для обычных пользователей (админ - безлимит)
PHONE_RE   = re.compile(r'^\+?[0-9]{7,15}$')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── Состояния ─────────────────────────────────────────────────
(
    MAIN_MENU,
    AD_TYPE, AD_LOCATION_CHOICE, AD_ADDRESS_TEXT, AD_ADDRESS_CONFIRM, AD_LOCATION_GEO,
    AD_PHONE, AD_PRICE, AD_DESCRIPTION, AD_PHOTO, AD_CONFIRM,
    SEARCH_TYPE, SEARCH_LOCATION_CHOICE, SEARCH_ADDRESS_TEXT, SEARCH_GEO, SEARCH_RADIUS,
    CONTACT_MSG,
    ADMIN_MENU, ADMIN_BROADCAST,
    EDIT_FIELD,
) = range(20)

# ── БД ────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # Доступ по именам: row["price"]
    conn.execute("PRAGMA journal_mode=WAL")  # Лучшая конкурентность
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def get_db():
    """Context manager — соединение закрывается автоматически."""
    conn = db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, owner_name TEXT,
            action TEXT, type TEXT, address TEXT, phone TEXT, lat REAL, lon REAL,
            price REAL, description TEXT, photo_id TEXT, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')), confirmed_at TEXT DEFAULT (datetime('now', '+7 days')),
            views INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER, from_id INTEGER,
            from_name TEXT, text TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS contact_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, listing_id INTEGER,
            price REAL, purchased_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS search_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, search_type TEXT,
            action TEXT, lat REAL, lon REAL, radius INTEGER, max_price REAL,
            active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')), expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL, created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, listing_id)
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT 'bg',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    
    # 🔴 ИНДЕКСЫ для производительности (критично при 1000+ объявлений)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_listings_owner ON listings(owner_id);
        CREATE INDEX IF NOT EXISTS idx_listings_active_action ON listings(active, action);
        CREATE INDEX IF NOT EXISTS idx_listings_coords ON listings(lat, lon);
        CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
        CREATE INDEX IF NOT EXISTS idx_favorites_listing ON favorites(listing_id);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON search_subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON search_subscriptions(active);
    """)
    
    # Миграция для существующих БД
    migrations = [
        "ALTER TABLE listings ADD COLUMN views INTEGER DEFAULT 0",
        "ALTER TABLE listings ADD COLUMN confirmed_at TEXT DEFAULT (datetime('now', '+7 days'))",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except Exception:
            pass  # Колонка уже существует
    conn.commit()
    conn.close()

# ── Геокодинг ─────────────────────────────────────────────────
_geocode_cache: dict = {}
_geocode_lock = asyncio.Lock() if False else None  # инициализируем в runtime

async def geocode(address: str):
    """Асинхронный геокодинг с кэшем."""
    if address in _geocode_cache:
        return _geocode_cache[address]

    query = f"{address}, Варна, България"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1, "countrycodes": "bg",
    })
    try:
        loop = asyncio.get_event_loop()
        req = urllib.request.Request(url, headers={"User-Agent": "ParkPlaceVarnaBot/1.0"})
        def _fetch():
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read())
        data = await loop.run_in_executor(None, _fetch)
        if data:
            result = float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"]
            _geocode_cache[address] = result
            return result
    except Exception as e:
        logger.error(f"Geocode error: {e}")
    return None

async def reverse_geocode(lat: float, lon: float):
    """Асинхронный обратный геокодинг."""
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode({
        "lat": lat, "lon": lon, "format": "json", "accept-language": "bg,en",
        "zoom": 18,
    })
    try:
        loop = asyncio.get_event_loop()
        req = urllib.request.Request(url, headers={"User-Agent": "ParkPlaceVarnaBot/1.0"})
        def _fetch():
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read())
        data = await loop.run_in_executor(None, _fetch)
        addr = data.get("address", {})
        parts = []
        road = addr.get("road") or addr.get("pedestrian") or addr.get("residential")
        if road:
            house = addr.get("house_number")
            parts.append(f"{road} {house}" if house else road)
        suburb = addr.get("suburb") or addr.get("neighbourhood") or addr.get("city_district")
        if suburb:
            parts.append(suburb)
        if parts:
            return ", ".join(parts)
        return data.get("display_name", "").split(",")[0]
    except Exception as e:
        logger.error(f"Reverse geocode error: {e}")
    return None

# ── Haversine ─────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 2*R*math.asin(math.sqrt(a))

def fmt_dist(m, lang='bg'):
    from_you = {"bg": "от вас", "ru": "от вас"}
    m_unit = {"bg": "м", "ru": "м"}
    km_unit = {"bg": "км", "ru": "км"}
    
    if m < 1000: 
        return f"{round(m/10)*10:.0f} {m_unit[lang]} {from_you[lang]}"
    elif m < 10000: 
        return f"{m/1000:.1f} {km_unit[lang]} {from_you[lang]}"
    else: 
        return f"{m/1000:.0f} {km_unit[lang]} {from_you[lang]}"

# ── Лейблы ────────────────────────────────────────────────────
# Функции локализации
def get_action_label(action, lang='bg'):
    labels = {'bg': {'buy': '🛒 Купува', 'sell': '💰 Продава', 'rent': '🔑 Наем', 'lease': '📋 Под наем'},
              'ru': {'buy': '🛒 Купить', 'sell': '💰 Продать', 'rent': '🔑 Аренда', 'lease': '📋 Сдать'}}
    return labels.get(lang, labels['bg']).get(action, action)

def get_type_label(ltype, lang='bg'):
    labels = {'bg': {'parking': '🅿️ Паркомясто', 'garage': '🚘 Гараж', 'all': '📋 Всичко'},
              'ru': {'parking': '🅿️ Парковочное место', 'garage': '🚘 Гараж', 'all': '📋 Всё'}}
    return labels.get(lang, labels['bg']).get(ltype, ltype)



def has_purchased_contacts(buyer_id: int, listing_id: int) -> bool:
    """Проверяет купил ли пользователь доступ к контактам этого обявиения."""
    conn = db()
    result = conn.execute(
        "SELECT id FROM contact_purchases WHERE buyer_id=? AND listing_id=?",
        (buyer_id, listing_id)
    ).fetchone()
    conn.close()
    return result is not None

def listing_text(row, distance_m=None, lang="bg"):
    """Формирует текст обявиения (все контакты видны всем)."""
    lid, owner_id, owner_name, action, ltype, address, phone, lat, lon, price, desc, photo, active, created, confirmed_at, views = row
    lines = [f"{get_action_label(action, lang)} · {get_type_label(ltype, lang)}"]
    
    if distance_m is not None:
        lines.append(f"📏 *{fmt_dist(distance_m, lang)}*")
    
    lines.append(f"📍 {address}")
    
    if phone:
        lines.append(f"📞 {phone}")
    
    lines.append(f"💰 {price:,.0f} €")
    
    if desc:
        lines.append(f"📝 {desc}")
    
    lines.append(f"🆔 #{lid}")
    return "\n".join(lines)


def get_photos(row) -> list:
    """Возвращает список photo_id из строки БД."""
    photo = row[11]
    if not photo:
        return []
    # Новый формат: JSON список
    if photo.startswith("["):
        try:
            return json.loads(photo)
        except Exception:
            return []
    # Старый формат: одна строка
    return [photo]


async def send_listing(message, caption: str, row, keyboard):
    """Отправить объявление: фото → текст с кнопками."""
    from telegram import InputMediaPhoto
    photos = get_photos(row)

    if photos:
        # Сначала фото медиагруппой БЕЗ текста
        if len(photos) == 1:
            await message.reply_photo(photos[0])
        else:
            media = [InputMediaPhoto(media=p) for p in photos[:5]]
            await message.reply_media_group(media)
    
    # Затем текст С КНОПКАМИ
    await message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)

# ── Клавиатуры ────────────────────────────────────────────────
def main_keyboard():
    """Пустая клавиатура - убираем ReplyKeyboard."""
    from telegram import ReplyKeyboardRemove
    return ReplyKeyboardRemove()

def home_ikb(lang="bg"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")]])

def back_and_home_ikb(back_action="go_home", lang="bg"):
    """Кнопки Назад + На главную."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_back", lang), callback_data=back_action)],
        [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")],
    ])

def action_keyboard(lang="bg"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_buy", lang),  callback_data="start_buy"),
         InlineKeyboardButton(t("btn_sell", lang), callback_data="start_sell")],
        [InlineKeyboardButton(t("btn_rent", lang),  callback_data="start_rent"),
         InlineKeyboardButton(t("btn_lease", lang), callback_data="start_lease")],
        [InlineKeyboardButton(t("btn_my_listings", lang), callback_data="start_mylistings"),
         InlineKeyboardButton(t("btn_favorites", lang),    callback_data="start_favorites")],
        [InlineKeyboardButton(t("btn_subscriptions", lang), callback_data="start_subscriptions")],
        [InlineKeyboardButton(t("btn_language", lang), callback_data="language")],
    ])

def type_keyboard(prefix, include_all=False, lang="bg"):
    rows = [
        [InlineKeyboardButton(t("btn_type_parking", lang), callback_data=f"{prefix}_parking")],
        [InlineKeyboardButton(t("btn_type_garage", lang),  callback_data=f"{prefix}_garage")],
    ]
    if include_all:
        rows.append([InlineKeyboardButton(t("btn_type_all", lang), callback_data=f"{prefix}_all")])
    rows.append([InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")])
    return InlineKeyboardMarkup(rows)

def location_choice_keyboard(prefix, lang="bg"):
    """Выбор способа указания местоположения."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_enter_address", lang),    callback_data=f"{prefix}_text")],
        [InlineKeyboardButton(t("btn_send_location", lang),    callback_data=f"{prefix}_geo")],
        [InlineKeyboardButton(t("btn_home", lang),             callback_data="go_home")],
    ])

def geo_ad_keyboard(lang="bg"):
    return ReplyKeyboardMarkup([
        [KeyboardButton(t("btn_send_location_object", lang), request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def geo_search_keyboard(lang="bg"):
    return ReplyKeyboardMarkup([
        [KeyboardButton(t("btn_send_my_location", lang), request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def phone_keyboard(lang="bg"):
    """Клавиатура с бутон за автоматично изпращане на вашия номер."""
    return ReplyKeyboardMarkup([
        [KeyboardButton(t("btn_send_phone", lang), request_contact=True)],
        [KeyboardButton(t("btn_skip", lang))],
    ], resize_keyboard=True, one_time_keyboard=True)

def radius_keyboard(lang="bg"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("500 м", callback_data="radius_500"),
         InlineKeyboardButton("1 км",  callback_data="radius_1000")],
        [InlineKeyboardButton("2 км",  callback_data="radius_2000"),
         InlineKeyboardButton("5 км",  callback_data="radius_5000")],
        [InlineKeyboardButton(t("radius_all", lang), callback_data="radius_all")],
        [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")],
    ])

def admin_keyboard(lang="bg"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_adm_listings", lang),   callback_data="adm_listings_0"),
         InlineKeyboardButton(t("btn_adm_users", lang),      callback_data="adm_users")],
        [InlineKeyboardButton(t("btn_adm_stats", lang),      callback_data="adm_stats"),
         InlineKeyboardButton(t("btn_adm_broadcast", lang),  callback_data="adm_broadcast")],
        [InlineKeyboardButton(t("btn_home", lang),           callback_data="go_home")],
    ])

# ── /start ────────────────────────────────────────────────────
async def cmd_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /language."""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    ctx.user_data["lang"] = lang
    
    keyboard = [
        [InlineKeyboardButton(t("language_bg", lang), callback_data="lang_bg")],
        [InlineKeyboardButton(t("language_ru", lang), callback_data="lang_ru")],
        [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")]
    ]
    await update.message.reply_text(t("language_choose", lang), reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_language_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка выбора языка."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    ctx.user_data["lang"] = lang
    
    keyboard = [
        [InlineKeyboardButton(t("language_bg", lang), callback_data="lang_bg")],
        [InlineKeyboardButton(t("language_ru", lang), callback_data="lang_ru")],
        [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")]
    ]
    await query.edit_message_text(t("language_choose", lang), reply_markup=InlineKeyboardMarkup(keyboard))

async def set_language_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора языка."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    new_lang = query.data.replace("lang_", "")
    set_user_lang(user_id, new_lang, ctx)
    ctx.user_data["lang"] = new_lang
    
    await query.edit_message_text(
        t("language_changed", new_lang) + "\n\n" + t("welcome_line", new_lang),
        parse_mode="Markdown",
        reply_markup=action_keyboard(new_lang)
    )

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from telegram import ReplyKeyboardRemove
    ctx.user_data.clear()
    
    user_id = update.effective_user.id
    
    # Проверяем, есть ли пользователь в базе данных
    with get_db() as conn:
        user_exists = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    
    # Если пользователя нет в базе - это первый запуск, определяем язык автоматически
    if not user_exists:
        lang = detect_telegram_lang(update)
        set_user_lang(user_id, lang, ctx)
        logger.info(f"New user {user_id} with auto-detected language: {lang}")
    else:
        # Пользователь существует - берем его сохраненный язык
        lang = get_user_lang(user_id, ctx)
    
    ctx.user_data["lang"] = lang
    
    if update.message:
        await update.message.reply_text(
            t("welcome_full", lang),
            parse_mode="Markdown", 
            reply_markup=action_keyboard(lang)
        )
    else:
        await update.callback_query.message.reply_text(
            t("welcome_full", lang),
            parse_mode="Markdown",
            reply_markup=action_keyboard(lang)
        )
    return MAIN_MENU

async def go_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    # КРИТИЧНО: Сохранить язык перед очисткой
    saved_lang = ctx.user_data.get("lang")
    ctx.user_data.clear()
    if saved_lang:
        ctx.user_data["lang"] = saved_lang
    
    # Получить и кэшировать язык
    lang = get_user_lang(user_id, ctx)
    ctx.user_data["lang"] = lang
    
    # Редактируем существующее сообщение
    try:
        await query.edit_message_text(
            t("welcome_line", lang),
            parse_mode="Markdown",
            reply_markup=action_keyboard(lang)
        )
    except Exception:
        # Если не можем отредактировать (например, медиагруппа), отправляем новое
        await query.message.reply_text(
            t("welcome_line", lang),
            parse_mode="Markdown",
            reply_markup=action_keyboard(lang)
        )
    
    return MAIN_MENU

# ── Текстовое меню ────────────────────────────────────────────
async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from telegram import ReplyKeyboardRemove
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    text = update.message.text
    if text == t("btn_home", lang) or text == "🏠 Начало" or text == "🏠 Главная":
        ctx.user_data.clear()
        ctx.user_data["lang"] = lang
        await update.message.reply_text(
            t("welcome_short", lang),
            parse_mode="Markdown", 
            reply_markup=action_keyboard(lang)
        )
        return MAIN_MENU
    elif text == t("btn_my_listings", lang) or text == "📁 Моите обяви" or text == "📁 Мои объявления":
        return await show_my_listings(update, ctx)
    elif text == "ℹ️ Помощ" or text == "ℹ️ Помощь":
        await update.message.reply_text(
            t("help_text", lang),
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return MAIN_MENU
    await update.message.reply_text(t("choose_action", lang), reply_markup=action_keyboard(lang))
    return MAIN_MENU

# ── Выбор действия ────────────────────────────────────────────

async def home_button_pressed(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка Reply-кнопки 'На главную' из любого состояния."""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    ctx.user_data.clear()
    ctx.user_data["lang"] = lang
    
    await update.message.reply_text(
        t("welcome_short", lang),
        parse_mode="Markdown", 
        reply_markup=action_keyboard(lang)
    )
    return MAIN_MENU

async def start_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    ctx.user_data["lang"] = lang
    
    action = query.data.replace("start_", "")

    # Любими
    if action == "favorites":
        return await show_favorites(update, ctx)

    # Мои обявиения
    if action == "mylistings":
        conn = db()
        rows = conn.execute("SELECT * FROM listings WHERE owner_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        conn.close()
        
        if not rows:
            await query.edit_message_text(t("my_no_listings", lang), reply_markup=home_ikb())
            return MAIN_MENU
        
        # Сохраняем для пагинации
        ctx.user_data["my_listings"] = rows
        
        my_listings_text = {"bg": "📁 *Вашите обяви*", "ru": "📁 *Ваши объявления*"}
        await query.edit_message_text(f"{my_listings_text.get(lang, my_listings_text['bg'])} ({len(rows)})", parse_mode="Markdown", reply_markup=home_ikb())
        
        # Показываем первую страницу
        await show_my_listings_page(query.message, ctx, page=0)
        
        return MAIN_MENU

    # Мои подписки
    if action == "subscriptions":
        conn = db()
        rows = conn.execute(
            "SELECT id, search_type, action, lat, lon, radius, created_at, expires_at, active "
            "FROM search_subscriptions WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        conn.close()
        
        if not rows:
            sub_no_active_text = {"bg": "🔔 Нямате активни абонаменти.\n\nАбонаментите позволяват получаване на известия за нови обяви.",
                                  "ru": "🔔 У вас нет активных подписок.\n\nПодписки позволяют получать уведомления о новых объявлениях."}
            await query.edit_message_text(
                sub_no_active_text.get(lang, sub_no_active_text["bg"]),
                reply_markup=home_ikb()
            )
            return MAIN_MENU
        
        sub_title_text = {"bg": "🔔 Вашите абонаменти", "ru": "🔔 Ваши подписки"}
        await query.edit_message_text(f"{sub_title_text.get(lang, sub_title_text['bg'])} ({len(rows)}):", reply_markup=home_ikb())
        
        for sub_id, stype, act, lat, lon, radius, created, expires, active in rows:
            import datetime
            
            km_text = {"bg": "км", "ru": "км"}
            m_text = {"bg": "м", "ru": "м"}
            radius_text = f"{radius//1000} {km_text[lang]}" if radius >= 1000 else f"{radius} {m_text[lang]}"
            type_text = get_type_label(stype, lang)
            action_text = get_action_label(act, lang)
            
            status_active = {"bg": "✅ Активна", "ru": "✅ Активна"}
            status_paused = {"bg": "⏸ Изключен", "ru": "⏸ Приостановлена"}
            status_expired = {"bg": "⏰ Изтекъл", "ru": "⏰ Истекла"}
            
            status = status_active[lang] if active else status_paused[lang]
            
            # Проверяем не истекла ли подписка
            if expires:
                exp_date = datetime.datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
                if exp_date < datetime.datetime.now():
                    status = status_expired[lang]
            
            sub_text_template = {"bg": "🔔 *Абонамент #{sub_id}*\n• {action_text}\n• {type_text}\n• Радиус: {radius_text}\n📅 Създаден: {created}\n⏰ Изтича: {expires}\n{status}",
                                "ru": "🔔 *Подписка #{sub_id}*\n• {action_text}\n• {type_text}\n• Радиус: {radius_text}\n📅 Создана: {created}\n⏰ Истекает: {expires}\n{status}"}
            
            text = sub_text_template[lang].format(
                sub_id=sub_id,
                action_text=action_text,
                type_text=type_text,
                radius_text=radius_text,
                created=created[:10],
                expires=expires[:10] if expires else '—',
                status=status
            )
            
            btns = []
            if active:
                btns.append(InlineKeyboardButton(t("btn_pause", lang), callback_data=f"unsub_{sub_id}"))
            else:
                btns.append(InlineKeyboardButton(t("btn_resume", lang), callback_data=f"resub_{sub_id}"))
            btns.append(InlineKeyboardButton(t("btn_delete", lang), callback_data=f"delsub_{sub_id}"))
            
            await query.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([btns])
            )
        
        return MAIN_MENU

    ctx.user_data["action"] = action

    if action in ("buy", "rent"):
        ctx.user_data["search_action"] = action
        await query.edit_message_text(
            t("ad_choose_type", lang, action=get_action_label(action, lang)),
            parse_mode="Markdown",
            reply_markup=type_keyboard("stype", include_all=True, lang=lang)
        )
        return SEARCH_TYPE
    else:
        # Проверяем лимит объявлений (админ - безлимит)
        
        # Админ может создавать сколько угодно
        if user_id != ADMIN_ID:
            MAX_LISTINGS = 15
            conn = db()
            count = conn.execute(
                "SELECT COUNT(*) FROM listings WHERE owner_id=? AND active=1", 
                (user_id,)
            ).fetchone()[0]
            conn.close()
            
            if count >= MAX_LISTINGS:
                await query.edit_message_text(
                    t("ad_limit", lang, max=MAX_LISTINGS),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t("btn_my_listings", lang), callback_data="start_mylistings")],
                        [InlineKeyboardButton(t("btn_home", lang),         callback_data="go_home")],
                    ])
                )
                return MAIN_MENU

        ctx.user_data["ad"] = {"action": action}
        ctx.user_data["published"] = False
        await query.edit_message_text(
            t("ad_choose_type", lang, action=get_action_label(action, lang)),
            parse_mode="Markdown",
            reply_markup=type_keyboard("adtype", include_all=False, lang=lang)
        )
        return AD_TYPE

# ═══════════════════════════════════════════════════════════════
# ПОДАЧА ОБЪЯВЛЕНИЯ
# ═══════════════════════════════════════════════════════════════
async def ad_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    ctx.user_data["ad"]["type"] = query.data.replace("adtype_", "")
    await query.edit_message_text(
        t("ad_location_how", lang),
        reply_markup=location_choice_keyboard("adloc", lang)
    )
    return AD_LOCATION_CHOICE

# Выбор способа — текст или геолокация
async def ad_location_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)

    if query.data == "adloc_text":
        await query.edit_message_text(
            t("ad_enter_address", lang),
            parse_mode="Markdown"
        )
        return AD_ADDRESS_TEXT

    elif query.data == "adloc_geo":
        await query.edit_message_text(
            t("ad_send_geo", lang),
            parse_mode="Markdown"
        )
        await query.message.reply_text(
            t("ad_press_button", lang), reply_markup=geo_ad_keyboard(lang)
        )
        return AD_LOCATION_GEO

# Адрес текстом → геокодинг
async def ad_address_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    address = update.message.text.strip()
    await update.message.reply_text(t("ad_searching", lang))
    result = await geocode(address)
    if not result:
        await update.message.reply_text(
            t("ad_not_found", lang),
            parse_mode="Markdown"
        )
        return AD_ADDRESS_TEXT

    lat, lon, display = result
    ctx.user_data["ad"]["lat"]     = lat
    ctx.user_data["ad"]["lon"]     = lon
    ctx.user_data["ad"]["address"] = address

    await update.message.reply_location(latitude=lat, longitude=lon)
    await update.message.reply_text(
        t("ad_confirm_address", lang, display=display[:120]),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("btn_yes_correct", lang), callback_data="addrconfirm_ok")],
            [InlineKeyboardButton(t("btn_no_retry", lang),    callback_data="addrconfirm_retry")],
            [InlineKeyboardButton(t("btn_clarify_geo", lang), callback_data="addrconfirm_geo")],
        ])
    )
    return AD_ADDRESS_CONFIRM

async def ad_address_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)

    if query.data == "addrconfirm_retry":
        await query.edit_message_text(t("ad_retry_address", lang))
        return AD_ADDRESS_TEXT

    elif query.data == "addrconfirm_geo":
        await query.edit_message_text(t("ad_retry_geo", lang))
        await query.message.reply_text(t("ad_press_button", lang), reply_markup=geo_ad_keyboard(lang))
        return AD_LOCATION_GEO

    # ok — подтверждено
    # Если редактируем — возвращаемся в превью
    if ctx.user_data.get("editing_mode"):
        ctx.user_data["editing_mode"] = False
        await query.edit_message_text(t("ad_address_updated", lang))
        return await _show_ad_preview(update, ctx)
    
    # Иначе переходим к телефону
    await query.edit_message_text(t("ad_address_confirmed", lang))
    await query.message.reply_text(
        t("ad_phone_prompt", lang),
        parse_mode="Markdown",
        reply_markup=phone_keyboard(lang)
    )
    return AD_PHONE

# Геолокация чрез скрепку
async def ad_location_geo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from telegram import ReplyKeyboardRemove
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    loc = update.message.location
    
    # 🔴 ПРОВЕРКА: объявление должно быть в пределах 50км от центра Варны
    VARNA_CENTER_LAT = 43.2141
    VARNA_CENTER_LON = 27.9147
    MAX_DISTANCE_FROM_VARNA = 50000  # 50 км в метрах
    
    distance_from_varna = haversine(VARNA_CENTER_LAT, VARNA_CENTER_LON, loc.latitude, loc.longitude)
    
    if distance_from_varna > MAX_DISTANCE_FROM_VARNA:
        await update.message.reply_text(
            t("ad_too_far_details", lang, 
              dist=f"{distance_from_varna/1000:.1f}",
              max_dist=f"{MAX_DISTANCE_FROM_VARNA/1000:.0f}"),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        # Возвращаем в состояние выбора способа указания локации
        await update.message.reply_text(
            t("ad_location_object", lang),
            parse_mode="Markdown",
            reply_markup=location_choice_keyboard("ad")
        )
        return AD_LOCATION_CHOICE
    
    ctx.user_data["ad"]["lat"] = loc.latitude
    ctx.user_data["ad"]["lon"] = loc.longitude

    # Если адрес ещё не задан — пробуем определить его по координатам
    if not ctx.user_data["ad"].get("address"):
        await update.message.reply_text(
            t("ad_detecting_address", lang),
            reply_markup=ReplyKeyboardRemove()  # Убираем кнопку
        )
        addr = await reverse_geocode(loc.latitude, loc.longitude)
        if addr:
            ctx.user_data["ad"]["address"] = addr if isinstance(addr, str) else ", ".join(addr)
            msg = t("ad_geo_saved", lang) + f"\n📍 *{ctx.user_data['ad']['address']}*\n\n"
        else:
            ctx.user_data["ad"]["address"] = f"{loc.latitude:.5f}, {loc.longitude:.5f}"
            msg = t("ad_geo_saved_no_addr", lang) + "\n\n"
    else:
        msg = t("ad_geo_saved", lang) + "\n\n"

    await update.message.reply_text(
        msg + t("ad_phone_prompt", lang),
        parse_mode="Markdown", reply_markup=phone_keyboard(lang)
    )
    return AD_PHONE

async def ad_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    # Если пришёл контакт через кнопку
    if update.message.contact:
        ctx.user_data["ad"]["phone"] = update.message.contact.phone_number
    else:
        text = update.message.text.strip()
        skip_texts = ["⏩ Пропускане", "⏩ Пропустить", "-"]
        if text in skip_texts:
            ctx.user_data["ad"]["phone"] = None
        else:
            # Валидация телефона
            import re
            phone_clean = re.sub(r'[\s\-\(\)]', '', text)
            if not re.match(r'^\+?[0-9]{7,15}$', phone_clean):
                await update.message.reply_text(
                    t("ad_phone_invalid", lang),
                    parse_mode="Markdown"
                )
                return AD_PHONE
            ctx.user_data["ad"]["phone"] = text

    # Если редактируем — возвращаемся в превью
    if ctx.user_data.get("editing_mode"):
        ctx.user_data["editing_mode"] = False
        from telegram import ReplyKeyboardRemove
        phone_updated_text = {"bg": "✅ Телефонът е обновен!", "ru": "✅ Телефон обновлён!"}
        await update.message.reply_text(phone_updated_text.get(lang, phone_updated_text["bg"]), reply_markup=ReplyKeyboardRemove())
        return await _show_ad_preview(update, ctx)

    from telegram import ReplyKeyboardRemove
    await update.message.reply_text(
        t("ad_price_prompt", lang),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return AD_PRICE

async def ad_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    try:
        price = float(update.message.text.strip().replace(" ", "").replace(",", "."))
        ctx.user_data["ad"]["price"] = price
    except ValueError:
        await update.message.reply_text(t("ad_price_invalid", lang))
        return AD_PRICE
    
    # Если редактируем — возвращаемся в превью
    if ctx.user_data.get("editing_mode"):
        ctx.user_data["editing_mode"] = False
        price_updated_text = {"bg": "✅ Цената е обновена!", "ru": "✅ Цена обновлена!"}
        await update.message.reply_text(price_updated_text.get(lang, price_updated_text["bg"]))
        return await _show_ad_preview(update, ctx)
    
    await update.message.reply_text(
        t("ad_desc_prompt", lang), 
        parse_mode="Markdown"
    )
    return AD_DESCRIPTION

async def ad_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    text = update.message.text.strip()
    ctx.user_data["ad"]["description"] = None if text == "-" else text
    
    # Если редактируем — возвращаемся в превью
    if ctx.user_data.get("editing_mode"):
        ctx.user_data["editing_mode"] = False
        desc_updated_text = {"bg": "✅ Описанието е обновено!", "ru": "✅ Описание обновлено!"}
        await update.message.reply_text(desc_updated_text.get(lang, desc_updated_text["bg"]))
        return await _show_ad_preview(update, ctx)
    
    ctx.user_data["ad"]["photos"] = []
    await update.message.reply_text(
        t("ad_photos_prompt", lang),
        parse_mode="Markdown"
    )
    return AD_PHOTO


async def ad_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    # Нажали "Готово"
    if update.callback_query:
        await update.callback_query.answer()
        photos = ctx.user_data["ad"].get("photos", [])
        if not photos:
            ctx.user_data["ad"]["photos"] = []
        return await _show_ad_preview(update, ctx)

    # Пропустить через текст "-"
    if update.message and update.message.text and update.message.text.strip() == "-":
        ctx.user_data["ad"]["photos"] = []
        return await _show_ad_preview(update, ctx)

    # Получаем фото — собираем МОЛЧА, не отвечаем на каждое
    if update.message and update.message.photo:
        photos = ctx.user_data["ad"].setdefault("photos", [])
        file_id = update.message.photo[-1].file_id

        if file_id not in photos and len(photos) < 5:
            photos.append(file_id)

        count = len(photos)

        # Редактируем или отправляем одну кнопку "Готово"
        # Используем job_queue чтобы дать время собрать всю медиагруппу
        # Удаляем старый джоб если есть
        jobs = ctx.job_queue.get_jobs_by_name(f"photo_done_{update.effective_user.id}")
        for job in jobs:
            job.schedule_removal()

        # Ставим джоб через 1.5 секунды — если за это время придут ещё фото, он перезапустится
        async def send_photo_prompt(context):
            cnt = len(context.job.data["photos"])
            user_lang = context.job.data["lang"]
            await context.job.data["message"].reply_text(
                t("photos_received", user_lang, cnt=cnt),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("photos_done_btn", user_lang, cnt=cnt), callback_data="photos_done")],
                    [InlineKeyboardButton(t("btn_skip", user_lang), callback_data="photos_done")],
                ])
            )

        ctx.job_queue.run_once(
            send_photo_prompt,
            when=1.5,
            name=f"photo_done_{update.effective_user.id}",
            data={"photos": photos, "message": update.message, "lang": lang}
        )
        return AD_PHOTO

    # Что-то другое
    await update.message.reply_text(
        t("photos_send_or_skip", lang),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("btn_skip", lang), callback_data="photos_done")],
        ])
    )
    return AD_PHOTO


async def _show_ad_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать превью объявления перед публикацией."""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    ad = ctx.user_data["ad"]
    
    geo_line_text = {"bg": "🗺 Геолокация ✅", "ru": "🗺 Геолокация ✅"}
    no_geo_text = {"bg": "🗺 Без геолокация", "ru": "🗺 Без геолокации"}
    phone_text = {"bg": "📞 Без телефон", "ru": "📞 Без телефона"}
    
    geo_line   = geo_line_text[lang] if ad.get("lat") else no_geo_text[lang]
    phone_line = f"📞 {ad['phone']}" if ad.get("phone") else phone_text[lang]
    photos     = ad.get("photos", [])
    photo_line = t("photo_line_with", lang, cnt=len(photos)) if photos else t("photo_line_without", lang)

    preview = (
        t("ad_review", lang) +
        f"{get_action_label(ad.get('action',''), lang)} · {get_type_label(ad.get('type',''), lang)}\n"
        f"📍 {ad.get('address', '—')}\n"
        f"{phone_line}\n"
        f"{geo_line}\n"
        f"💰 {ad.get('price', 0):,.0f} €\n"
    )
    if ad.get("description"):
        preview += f"📝 {ad['description']}\n"
    preview += photo_line

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_publish", lang), callback_data="ad_publish")],
        [InlineKeyboardButton(t("btn_edit_address2", lang),  callback_data="ad_edit_address"),
         InlineKeyboardButton(t("btn_edit_phone2", lang),    callback_data="ad_edit_phone")],
        [InlineKeyboardButton(t("btn_edit_price2", lang),    callback_data="ad_edit_price"),
         InlineKeyboardButton(t("btn_edit_desc2", lang),     callback_data="ad_edit_desc")],
        [InlineKeyboardButton(t("btn_edit_photos2", lang),   callback_data="ad_edit_photo")],
        [InlineKeyboardButton(t("btn_cancel", lang),         callback_data="ad_cancel")],
    ])

    chat_id = update.effective_chat.id

    # Три отдельных сообщения: фото → текст с кнопками
    if photos:
        # Сначала фото
        if len(photos) == 1:
            await update.effective_message.reply_photo(photos[0])
        else:
            from telegram import InputMediaPhoto
            media = [InputMediaPhoto(media=p) for p in photos[:5]]
            await update.effective_message.reply_media_group(media)
    
    # Затем текст С КНОПКАМИ (не отдельно!)
    await update.effective_message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)

    return AD_CONFIRM

async def ad_edit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок редактирования в финальном просмотре."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    # Устанавливаем флаг редактирования
    ctx.user_data["editing_mode"] = True
    
    if query.data == "ad_edit_address":
        await query.message.reply_text(
            t("ad_new_location", lang),
            reply_markup=location_choice_keyboard("adloc", lang)
        )
        return AD_LOCATION_CHOICE
    
    elif query.data == "ad_edit_phone":
        await query.message.reply_text(
            t("ad_new_phone", lang),
            reply_markup=phone_keyboard(lang)
        )
        return AD_PHONE
    
    elif query.data == "ad_edit_price":
        await query.message.reply_text(t("ad_new_price", lang), parse_mode="Markdown")
        return AD_PRICE
    
    elif query.data == "ad_edit_desc":
        await query.message.reply_text(
            t("ad_new_desc", lang),
            parse_mode="Markdown"
        )
        return AD_DESCRIPTION
    
    elif query.data == "ad_edit_photo":
        # ВАЖНО: Очищаем старые фото перед добавлением новых
        ctx.user_data["ad"]["photos"] = []
        await query.message.reply_text(
            t("ad_new_photos", lang),
            parse_mode="Markdown"
        )
        return AD_PHOTO
    
    return AD_CONFIRM


async def notify_favorites_changes(bot, listing_id: int, field: str, old_value, new_value):
    """Уведомляет пользователей, у которых объявление в избранном, об изменениях."""
    logger.info(f"notify_favorites_changes called: listing_id={listing_id}, field={field}")
    
    conn = db()
    
    # Находим всех пользователей, у которых это объявление в избранном + их языки
    favorites_users = conn.execute(
        """SELECT f.user_id, COALESCE(u.language, 'bg') as lang
           FROM favorites f
           LEFT JOIN users u ON f.user_id = u.user_id
           WHERE f.listing_id=?""",
        (listing_id,)
    ).fetchall()
    
    logger.info(f"Found {len(favorites_users)} users with this listing in favorites")
    
    # Получаем информацию об объявлении
    listing = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    
    if not listing or not favorites_users:
        logger.info(f"No listing or no favorites_users, returning. listing={listing is not None}, users={len(favorites_users)}")
        conn.close()
        return
    
    # Отправляем уведомления с полным объявлением
    photos = get_photos(listing)
    
    for (user_id, lang) in favorites_users:
        try:
            logger.info(f"Sending notification to user {user_id} in {lang}")
            
            # Формируем сообщение об изменении на языке пользователя
            if field == "price":
                notification_text = t("notify_price_changed", lang, old=f"{old_value:,.0f}", new=f"{new_value:,.0f}")
            elif field == "address":
                notification_text = t("notify_address_changed", lang, old=old_value or '—', new=new_value or '—')
            elif field == "phone":
                if old_value is None:
                    notification_text = t("notify_phone_added", lang)
                elif new_value:
                    notification_text = t("notify_phone_changed", lang)
                else:
                    notification_text = t("notify_phone_removed", lang)
            elif field == "description":
                if old_value is None:
                    notification_text = t("notify_desc_added", lang)
                elif new_value:
                    notification_text = t("notify_desc_changed", lang)
                else:
                    notification_text = t("notify_desc_removed", lang)
            elif field == "photo":
                if new_value != 'removed':
                    notification_text = t("notify_photos_updated", lang, count=new_value)
                else:
                    notification_text = t("notify_photos_removed", lang)
            else:
                notification_text = t("notify_listing_updated", lang, lid=listing_id)
            
            caption = listing_text(listing, lang=lang)
            full_message = f"{t('notify_fav_updated', lang)}\n\n{notification_text}\n\n{'─'*30}\n\n{caption}"
            
            buttons = [
                [InlineKeyboardButton(t("btn_remove_fav", lang), callback_data=f"unfav_{listing_id}")],
                [InlineKeyboardButton(t("btn_on_map", lang), callback_data=f"map_{listing_id}")],
            ]
            
            if photos and len(photos) > 1:
                # Несколько фото - отправляем media group + текст с кнопками отдельно
                from telegram import InputMediaPhoto
                media_group = [InputMediaPhoto(media=photo) for photo in photos]
                await bot.send_media_group(user_id, media=media_group)
                await bot.send_message(
                    user_id,
                    full_message,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            elif photos:
                # Одно фото - отправляем с caption
                await bot.send_photo(
                    user_id,
                    photo=photos[0],
                    caption=full_message,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                # Без фото
                await bot.send_message(
                    user_id,
                    full_message,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            
            # Rate limiting
            await asyncio.sleep(0.05)
            logger.info(f"Successfully sent notification to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to notify favorites user {user_id}: {e}", exc_info=True)
    
    conn.close()


async def notify_favorites_deleted(bot, listing_id: int):
    """Уведомляет пользователей об удалении объявления из избранного."""
    conn = db()
    
    # Находим всех пользователей, у которых это объявление в избранном + их языки
    favorites_users = conn.execute(
        """SELECT f.user_id, COALESCE(u.language, 'bg') as lang
           FROM favorites f
           LEFT JOIN users u ON f.user_id = u.user_id
           WHERE f.listing_id=?""",
        (listing_id,)
    ).fetchall()
    
    # Получаем информацию об объявлении перед удалением
    listing = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    
    # Удаляем из избранного
    conn.execute("DELETE FROM favorites WHERE listing_id=?", (listing_id,))
    conn.commit()
    
    if not listing or not favorites_users:
        conn.close()
        return
    
    # Отправляем уведомления на языке каждого пользователя
    for (user_id, lang) in favorites_users:
        try:
            await bot.send_message(
                user_id,
                t("notify_listing_deleted", lang, lid=listing_id, address=listing[5] or '—'),
                parse_mode="Markdown"
            )
            # Rate limiting
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to notify favorites deletion to user {user_id}: {e}", exc_info=True)
    
    conn.close()


async def notify_subscribers(ctx, listing_id: int, action: str, ltype: str, lat: float, lon: float, price: float):
    """Отправляет уведомления подписчикам о новом обявиении."""
    if not lat or not lon:
        return  # Нет координат — не можем проверить радиус
    
    # Находим подходящие подписки
    conn = db()
    # Ищем подписки где action совпадает (buy ищет sell, rent ищет lease)
    search_action = "buy" if action == "sell" else ("rent" if action == "lease" else None)
    if not search_action:
        conn.close()
        return
    
    subscriptions = conn.execute(
        "SELECT user_id, search_type, lat, lon, radius, max_price FROM search_subscriptions "
        "WHERE active=1 AND action=? AND (search_type=? OR search_type='all') AND (expires_at IS NULL OR expires_at > datetime('now'))",
        (search_action, ltype)
    ).fetchall()
    
    # Получаем само обявиение для показа
    listing = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    conn.close()
    
    if not listing:
        return
    
    notified = 0
    for user_id, stype, sub_lat, sub_lon, radius, max_price in subscriptions:
        # Проверяем радиус
        dist = haversine(sub_lat, sub_lon, lat, lon)
        if dist > radius:
            continue
        
        # Проверяем цену если указана
        if max_price and price > max_price:
            continue
        
        # Отправляем уведомление
        try:
            owner_id = listing[1]
            photo_id = listing[11]
            caption = listing_text(listing, distance_m=dist)
            notification = f"🔔 *Новое обявиение по вашей подписке!*\n\n{caption}"
            
            # Простая кнопка "На карте"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗺 На картата", callback_data=f"map_{listing_id}")],
            ])
            
            # Отправляем с фото если есть (новый формат JSON)
            photos = get_photos(listing)
            if photos:
                await ctx.bot.send_photo(
                    user_id,
                    photo=photos[0],
                    caption=notification,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                await ctx.bot.send_message(
                    user_id,
                    notification,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            
            # 🔴 FIX #2: Rate limiting - 20 сообщений/сек (безопасно для Telegram)
            await asyncio.sleep(0.05)
            
            notified += 1
        except Exception as e:
            err_str = str(e)
            if "Forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                # Пользователь заблокировал бота — деактивируем его подписки
                try:
                    c = db()
                    c.execute("UPDATE search_subscriptions SET active=0 WHERE user_id=?", (user_id,))
                    c.commit(); c.close()
                    logger.info(f"Deactivated subscriptions for blocked user {user_id}")
                except Exception as e2:
                    logger.error(f"Failed to deactivate subscriptions for user {user_id}: {e2}", exc_info=True)
            else:
                logger.error(f"Failed to notify user {user_id}: {e}")
    
    if notified > 0:
        logger.info(f"Notified {notified} subscribers about listing #{listing_id}")

async def ad_publish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    if query.data == "ad_cancel":
        try:
            await query.edit_message_text(t("ad_cancelled", lang), reply_markup=home_ikb(lang))
        except Exception as e:
            logger.warning(f"Could not edit message, sending new one: {e}")
            await query.message.reply_text(t("ad_cancelled", lang), reply_markup=home_ikb(lang))
        return MAIN_MENU

    ad   = ctx.user_data.get("ad", {})
    user = query.from_user

    # Сохраняем фото как JSON-список
    photos = ad.get("photos", [])
    photo_id = json.dumps(photos) if photos else None

    conn = db()
    cursor = conn.execute(
        "INSERT INTO listings (owner_id,owner_name,action,type,address,phone,lat,lon,price,description,photo_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user.id, user.full_name, ad.get("action"), ad.get("type"),
         ad.get("address"), ad.get("phone"), ad.get("lat"), ad.get("lon"),
         ad.get("price"), ad.get("description"), photo_id)
    )
    listing_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await notify_subscribers(
        ctx, listing_id, ad.get("action"), ad.get("type"),
        ad.get("lat"), ad.get("lon"), ad.get("price")
    )

    try:
        await query.edit_message_text(t("ad_published", lang), reply_markup=home_ikb(lang))
    except Exception:
        await query.message.reply_text(t("ad_published", lang), reply_markup=home_ikb(lang))
    return MAIN_MENU

# ═══════════════════════════════════════════════════════════════
# ПОИСК
# ═══════════════════════════════════════════════════════════════
async def search_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    ctx.user_data["search_type"] = query.data.replace("stype_", "")
    await query.edit_message_text(
        t("search_location_how", lang),
        reply_markup=location_choice_keyboard("sloc", lang)
    )
    return SEARCH_LOCATION_CHOICE

async def search_location_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)

    if query.data == "sloc_text":
        await query.edit_message_text(
            t("search_enter_address", lang),
            parse_mode="Markdown"
        )
        return SEARCH_ADDRESS_TEXT

    elif query.data == "sloc_geo":
        await query.edit_message_text(
            t("search_send_geo", lang)
        )
        await query.message.reply_text(t("search_choose_method", lang), reply_markup=geo_search_keyboard(lang))
        return SEARCH_GEO

async def search_address_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    address = update.message.text.strip()
    await update.message.reply_text(t("search_searching", lang))
    result = await geocode(address)
    if not result:
        await update.message.reply_text(
            t("search_not_found", lang)
        )
        return SEARCH_ADDRESS_TEXT
    lat, lon, display = result
    ctx.user_data["search_lat"] = lat
    ctx.user_data["search_lon"] = lon
    await update.message.reply_location(latitude=lat, longitude=lon)
    
    found_text = {"bg": f"📍 _{display[:100]}_\n\n📏 Изберете *радиус поиска*:",
                  "ru": f"📍 _{display[:100]}_\n\n📏 Выберите *радиус поиска*:"}
    await update.message.reply_text(
        found_text.get(lang, found_text["bg"]),
        parse_mode="Markdown", reply_markup=radius_keyboard(lang)
    )
    return SEARCH_RADIUS

async def search_geo_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from telegram import ReplyKeyboardRemove
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    loc = update.message.location
    ctx.user_data["search_lat"] = loc.latitude
    ctx.user_data["search_lon"] = loc.longitude
    
    # Убираем кнопку геолокации
    await update.message.reply_text(
        "​",  # Невидимый символ
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Показываем выбор радиуса
    await update.message.reply_text(
        t("choose_radius", lang),
        parse_mode="Markdown", 
        reply_markup=radius_keyboard(lang)
    )
    return SEARCH_RADIUS

async def search_radius_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    radius_str = query.data.replace("radius_", "")
    radius   = None if radius_str == "all" else int(radius_str)
    user_lat = ctx.user_data.get("search_lat")
    user_lon = ctx.user_data.get("search_lon")
    ltype    = ctx.user_data.get("search_type", "all")
    s_action = ctx.user_data.get("search_action", "rent")
    db_action = "sell" if s_action == "buy" else "lease"

    conn = db()
    params = [db_action]
    sql = "SELECT * FROM listings WHERE active=1 AND action=?"
    if ltype != "all":
        sql += " AND type=?"
        params.append(ltype)
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    no_geo  = []
    
    # 🔴 КОНСТАНТЫ для фильтрации по городу Варна
    VARNA_CENTER_LAT = 43.2141
    VARNA_CENTER_LON = 27.9147
    MAX_DISTANCE_FROM_VARNA = 50000  # 50 км в метрах
    
    for row in rows:
        lat, lon = row[7], row[8]
        
        # Проверяем что объявление в пределах Варны (50км от центра)
        if lat is not None and lon is not None:
            dist_from_varna = haversine(VARNA_CENTER_LAT, VARNA_CENTER_LON, lat, lon)
            
            # Пропускаем объявления слишком далеко от Варны
            if dist_from_varna > MAX_DISTANCE_FROM_VARNA:
                continue
        
        if user_lat and lat is not None:
            dist = haversine(user_lat, user_lon, lat, lon)
            if radius is None or dist <= radius:
                results.append((dist, row))
        elif radius is None:
            no_geo.append(row)

    results.sort(key=lambda x: x[0])
    total = len(results) + len(no_geo)

    if total == 0:
        user_id = query.from_user.id
        lang = get_user_lang(user_id, ctx)
        
        km_text = {"bg": "км", "ru": "км"}
        m_text = {"bg": "м", "ru": "м"}
        all_varna = {"bg": "вся Варна", "ru": "вся Варна"}
        
        rl = f"{radius//1000} {km_text[lang]}" if radius and radius >= 1000 else f"{radius} {m_text[lang]}" if radius else all_varna[lang]
        
        # Сохраняем параметры поиска для подписки
        ctx.user_data["subscribe_params"] = {
            "search_type": ltype,
            "action": s_action,
            "lat": user_lat,
            "lon": user_lon,
            "radius": radius or 50000,
        }
        
        await query.edit_message_text(
            t("search_no_results", lang, radius=rl),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("btn_subscribe_notif", lang), callback_data="subscribe")],
                [InlineKeyboardButton(t("btn_change_radius", lang), callback_data="change_radius")],
                [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")],
            ])
        )
        from telegram import ReplyKeyboardRemove
        await query.message.reply_text("​", reply_markup=ReplyKeyboardRemove())
        return MAIN_MENU

    rl = (f"{radius//1000} км" if radius >= 1000 else f"{radius} м") if radius else "вся Варна"

    logger.info(f"Search results: {len(results)} with geo, {len(no_geo)} without geo")
    
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    # Сохраняем результаты поиска для пагинации
    ctx.user_data["search_results"] = results
    ctx.user_data["search_no_geo"] = no_geo
    ctx.user_data["search_radius_label"] = rl
    
    from telegram import ReplyKeyboardRemove
    await query.edit_message_text(
        t("search_found", lang, count=total, radius=rl),
        parse_mode="Markdown"
    )

    # Убираем кнопку геолокации БЕЗ лишнего сообщения
    try:
        await query.message.reply_text("​", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"ReplyKeyboardRemove error: {e}")
    
    # Показываем первую страницу (первые 5 объявлений)
    await show_search_page(query.message, ctx, page=0)
    
    return MAIN_MENU


async def show_search_page(message, ctx, page=0):
    """Показывает страницу результатов поиска (5 объявлений)."""
    user_id = message.chat.id
    lang = get_user_lang(user_id, ctx)
    
    ITEMS_PER_PAGE = 5
    
    results = ctx.user_data.get("search_results", [])
    no_geo = ctx.user_data.get("search_no_geo", [])
    all_listings = results + [(None, row) for row in no_geo]
    
    total = len(all_listings)
    total_pages = math.ceil(total / ITEMS_PER_PAGE) if total > 0 else 1
    
    # Ограничиваем страницу
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_listings = all_listings[start:end]
    
    viewer_id = message.chat.id
    
    # Отправляем объявления на текущей странице
    for item in page_listings:
        dist, row = item if item[0] is not None else (None, item[1])
        lid = row[0]
        caption = listing_text(row, distance_m=dist)
        logger.info(f"Sending listing {lid} to user {viewer_id}")

        conn = db()
        in_fav = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND listing_id=?",
            (viewer_id, lid)
        ).fetchone()
        conn.close()

        fav_text = t("btn_remove_from_fav", lang) if in_fav else t("btn_add_to_fav", lang)
        fav_action = f"unfav_{lid}" if in_fav else f"fav_{lid}"
        
        if dist is not None:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(t("btn_on_map", lang), callback_data=f"map_{lid}"),
                 InlineKeyboardButton(fav_text, callback_data=fav_action)],
            ])
        else:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(fav_text, callback_data=fav_action)]])

        try:
            await send_listing(message, caption, row, keyboard)
            await asyncio.sleep(0.05)  # Rate limiting
            logger.info(f"Listing {lid} sent successfully")
        except Exception as e:
            logger.error(f"Error listing {lid}: {e}", exc_info=True)
            try:
                await message.reply_text(caption, reply_markup=keyboard, parse_mode="Markdown")
            except Exception as e2:
                logger.error(f"Error listing {lid} no md: {e2}")
    
    # Кнопки навигации
    nav_buttons = []
    
    # Кнопка "Вперед" если не последняя страница
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(t("btn_next_page", lang), callback_data=f"search_page_{page+1}"))
    
    # Кнопка "На главную" всегда
    home_button = [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")]
    
    # Формируем клавиатуру
    keyboard_rows = []
    if nav_buttons:
        keyboard_rows.append(nav_buttons)
    keyboard_rows.append(home_button)
    
    # Отправляем сообщение с навигацией
    await message.reply_text(
        t("page_info", lang, page=page+1, total_pages=total_pages, total_listings=total),
        reply_markup=InlineKeyboardMarkup(keyboard_rows)
    )


async def search_page_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик переключения страниц поиска."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.replace("search_page_", ""))
    
    # Удаляем старое сообщение с навигацией
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete pagination message: {e}")
    
    # Показываем новую страницу
    await show_search_page(query.message, ctx, page=page)
    
    return MAIN_MENU


async def change_radius(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    await query.edit_message_text(t("choose_radius", lang), reply_markup=radius_keyboard(lang))
    return SEARCH_RADIUS

# ── Карта ─────────────────────────────────────────────────────
async def show_map(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lid = int(query.data.split("_")[1])
    
    conn = db()
    row = conn.execute("SELECT lat, lon, address FROM listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    
    if row and row[0]:
        await query.message.reply_location(latitude=row[0], longitude=row[1])
        await query.message.reply_text(f"📍 {row[2]}")
    else:
        await query.answer("Геолокацията не е указана", show_alert=True)
    
    return MAIN_MENU

# ── Связь ─────────────────────────────────────────────────────
async def reveal_contacts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Показать контакты' - запуск оплаты чрез Telegram Stars."""
    query = update.callback_query
    await query.answer()
    lid = int(query.data.split("_")[1])
    buyer_id = query.from_user.id
    
    # Проверяем не купил ли уже
    if has_purchased_contacts(buyer_id, lid):
        await query.answer("Вече сте закупили достъп до тези контакти!", show_alert=True)
        return MAIN_MENU
    
    # Получаем информацию об обявиении
    conn = db()
    row = conn.execute("SELECT type, address FROM listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    
    if not row:
        await query.answer("Обявата не е намерена", show_alert=True)
        return MAIN_MENU
    
    ltype, address = row
    type_label = get_type_label(ltype, lang)
    
    # Формируем инвойс для Telegram Stars
    title = f"Доступ к контактам"
    description = f"{type_label}, {address[:50]}"
    payload = f"contacts_{lid}_{buyer_id}"
    
    # Цена в Telegram Stars (примерно 100 Stars ≈ 2€)
    stars_price = 100
    
    # Отправляем инвойс (для Stars не нужен provider_token)
    try:
        await query.message.reply_invoice(
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Пустой для Telegram Stars
            currency="XTR",  # XTR = Telegram Stars
            prices=[{"label": "Контакты", "amount": stars_price}],
            start_parameter=f"contacts_{lid}",
        )
        await query.answer("⭐ Платете чрез Telegram Stars")
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await query.answer("❌ Грешка создания платежа. Попробуйте позже.", show_alert=True)
    
    return MAIN_MENU


async def precheckout_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка pre-checkout запроса перед оплатой."""
    query = update.pre_checkout_query
    # Всегда подтверждаем (можно добавить дополнительные проверки)
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка успешной оплаты чрез Telegram Stars."""
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    
    # Парсим payload: "contacts_LISTING_ID_BUYER_ID"
    try:
        parts = payload.split("_")
        if parts[0] == "contacts":
            lid = int(parts[1])
            buyer_id = int(parts[2])
            
            # Сохраняем покупку в БД
            # total_amount для Stars уже в правильных единицах (не центы)
            price_stars = payment.total_amount
            
            conn = db()
            conn.execute(
                "INSERT INTO contact_purchases (buyer_id, listing_id, price) VALUES (?, ?, ?)",
                (buyer_id, lid, price_stars)  # Сохраняем количество Stars
            )
            conn.commit()
            
            # Получаем обявиение с контактами
            row = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
            conn.close()
            
            if row:
                user_id = update.effective_user.id
                lang = get_user_lang(user_id, ctx)
                
                caption = listing_text(row, lang=lang)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("btn_on_map", lang), callback_data=f"map_{lid}")],
                ])
                
                payment_success_text = {"bg": "✅ *Плащането е успешно!* (⭐ {stars} Stars)\n\n{caption}",
                                       "ru": "✅ *Оплата прошла успешно!* (⭐ {stars} Stars)\n\n{caption}"}
                
                await update.message.reply_text(
                    payment_success_text[lang].format(stars=price_stars, caption=caption),
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                user_id = update.effective_user.id
                lang = get_user_lang(user_id, ctx)
                
                payment_success_no_listing = {"bg": "✅ Оплата прошла, но обявиение не е намерено.",
                                              "ru": "✅ Оплата прошла, но объявление не найдено."}
                await update.message.reply_text(payment_success_no_listing[lang])
        
        elif parts[0] == "subscription":
            # Обработка оплаты подписки
            await update.message.reply_text("✅ Подписка оплачена!")
    
    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        await update.message.reply_text("❌ Грешка обработки платежа. Свяжитесь с поддержкой.")

async def subscribe_to_notifications(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка подписки на уведомления с оплатой Stars."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    params = ctx.user_data.get("subscribe_params")

    if not params:
        await query.message.reply_text(
            t("search_params_lost", lang),
            reply_markup=home_ikb(lang)
        )
        return MAIN_MENU

    conn = db()
    existing = conn.execute(
        "SELECT id FROM search_subscriptions WHERE user_id=? AND active=1 "
        "AND search_type=? AND action=? AND radius=?",
        (user_id, params["search_type"], params["action"], params["radius"])
    ).fetchone()
    conn.close()

    if existing:
        await query.message.reply_text(
            t("subscription_exists", lang),
            reply_markup=home_ikb(lang)
        )
        return MAIN_MENU

    # 🔴 АДМИН = БЕСПЛАТНО
    if user_id == ADMIN_ID:
        # Создаём подписку сразу без оплаты
        import datetime
        expires_at = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        
        conn = db()
        conn.execute(
            "INSERT INTO search_subscriptions (user_id, search_type, action, lat, lon, radius, active, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (user_id, params["search_type"], params["action"], 
             params.get("lat"), params.get("lon"), params["radius"], expires_at)
        )
        conn.commit()
        conn.close()
        
        await query.message.reply_text(
            t("subscription_activated_admin", lang, expires=expires_at[:10]),
            parse_mode="Markdown",
            reply_markup=home_ikb(lang)
        )
        return MAIN_MENU

    # Сохраняем параметры для оплаты
    ctx.user_data["pending_subscription"] = params

    km_text = {"bg": "км", "ru": "км"}
    m_text = {"bg": "м", "ru": "м"}
    radius_text = f"{params['radius']//1000} {km_text[lang]}" if params['radius'] >= 1000 else f"{params['radius']} {m_text[lang]}"
    type_text   = get_type_label(params["search_type"], lang)
    action_text = get_action_label(params["action"], lang)

    # Отправляем инвойс Telegram Stars
    from telegram import LabeledPrice
    try:
        await ctx.bot.send_invoice(
            chat_id=user_id,
            title=t("subscription_invoice_title", lang),
            description=t("subscription_invoice_desc", lang, action=action_text, type=type_text, radius=radius_text),
            payload=f"subscription_{user_id}_{params['search_type']}_{params['action']}",
            provider_token="",  # Empty for Stars
            currency="XTR",  # Telegram Stars
            prices=[LabeledPrice(label=t("subscription_invoice_label", lang), amount=100)],  # 100 Stars
        )
        await query.message.reply_text(
            "💳 *Изпратено е известие за плащане.*\n\n"
            "Натиснете за да платите с Telegram Stars.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Invoice send error: {e}")
        await query.message.reply_text(
            "❌ Грешка при създаване на плащане. Моля опитайте отново.",
            reply_markup=home_ikb()
        )

    return MAIN_MENU


async def handle_successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка успешной оплаты Stars."""
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    
    # Определение и сохранение языка
    lang = get_user_lang(user_id, ctx)
    if not lang or lang == "bg":
        detected = detect_telegram_lang(update)
        if detected != lang:
            set_user_lang(user_id, detected, ctx)
            lang = detected
    ctx.user_data["lang"] = lang

    
    logger.info(f"Payment successful: {payment.telegram_payment_charge_id} from user {user_id}")
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    
    params = ctx.user_data.get("pending_subscription")
    if not params:
        await update.message.reply_text(t("error_params_lost", lang))
        return

    # Создаём подписку
    import datetime
    expires = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO search_subscriptions (user_id, search_type, action, lat, lon, radius, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, params["search_type"], params["action"],
             params.get("lat"), params.get("lon"), params["radius"], expires)
        )

    radius_text = f"{params['radius']//1000} км" if params['radius'] >= 1000 else f"{params['radius']} м"
    type_text   = TYPE_LABEL.get(params["search_type"], params["search_type"])
    action_text = ACTION_LABEL.get(params["action"], params["action"])

    await update.message.reply_text(
        f"✅ *Плащането е успешно!*\n\n"
        f"🔔 *Абонаментът е активиран:*\n"
        f"• {action_text} · {type_text}\n"
        f"• Радиус: {radius_text}\n"
        f"• Валиден: 30 дни\n\n"
        f"Ще получавате известия за нови обяви!",
        parse_mode="Markdown",
        reply_markup=home_ikb()
    )
    
    # Очищаем временные данные
    ctx.user_data.pop("pending_subscription", None)


async def handle_precheckout_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Подтверждение предоплаты с валидацией."""
    query = update.pre_checkout_query
    
    # 🔴 ВАЛИДАЦИЯ платежа (защита от подделки)
    try:
        # Проверяем что цена корректна (100 Stars = подписка)
        if query.total_amount != 100:
            await query.answer(
                ok=False, 
                error_message="❌ Невалидна сума за плащане. Опитайте отново."
            )
            return
        
        # Проверяем что currency правильный
        if query.currency != "XTR":  # Telegram Stars
            await query.answer(
                ok=False,
                error_message="❌ Невалидна валута. Използвайте Telegram Stars."
            )
            return
        
        # Всё ОК - подтверждаем
        await query.answer(ok=True)
        
    except Exception as e:
        logger.error(f"Precheckout validation error: {e}", exc_info=True)
        await query.answer(
            ok=False,
            error_message="❌ Грешка при обработка на плащането. Опитайте отново."
        )

async def contact_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts    = query.data.split("_")
    lid      = int(parts[1])
    owner_id = int(parts[2])
    ctx.user_data["contact_listing"] = lid
    ctx.user_data["contact_owner"]   = owner_id
    if query.from_user.id == owner_id:
        await query.answer("Это ваше обявиение!", show_alert=True)
        return MAIN_MENU
    await query.message.reply_text("✉️ Напишите сообщение владельцу:", reply_markup=main_keyboard())
    return CONTACT_MSG

async def contact_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    lid      = ctx.user_data.get("contact_listing")
    owner_id = ctx.user_data.get("contact_owner")
    user     = update.effective_user
    text     = update.message.text
    conn = db()
    conn.execute("INSERT INTO messages (listing_id,from_id,from_name,text) VALUES (?,?,?,?)",
        (lid, user.id, user.full_name, text))
    conn.commit()
    conn.close()
    try:
        uinfo = f"@{user.username}" if user.username else f"ID: {user.id}"
        msg_text = {"bg": f"📩 *Съобщение* по обявление #{lid}\nОт: {user.full_name} ({uinfo})\n\n{text}",
                    "ru": f"📩 *Сообщение* по объявлению #{lid}\nОт: {user.full_name} ({uinfo})\n\n{text}"}
        await ctx.bot.send_message(owner_id,
            msg_text.get(lang, msg_text["bg"]),
            parse_mode="Markdown")
        await update.message.reply_text(t("message_sent", lang), reply_markup=home_ikb(lang))
    except Exception as e:
        logger.error(f"Failed to send message to owner {owner_id} for listing {lid}: {e}", exc_info=True)
        await update.message.reply_text(t("message_saved", lang), reply_markup=home_ikb(lang))
    return MAIN_MENU

# ── Мои обявиения ────────────────────────────────────────────
async def show_my_listings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    conn    = db()
    rows    = conn.execute("SELECT * FROM listings WHERE owner_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text(t("my_no_listings", lang), reply_markup=home_ikb(lang))
        return MAIN_MENU
    
    my_header = {"bg": f"📁 Вашите обяви ({len(rows)}):", "ru": f"📁 Ваши объявления ({len(rows)}):"}
    await update.message.reply_text(my_header[lang], reply_markup=home_ikb(lang))
    
    for row in rows:
        lid, active = row[0], row[12]
        status  = t("listing_status_active", lang) if active else t("listing_status_inactive", lang)
        caption = listing_text(row, lang=lang) + f"\n{status}"
        btns = [
            [InlineKeyboardButton(t("btn_edit", lang), callback_data=f"edit_{lid}"),
             InlineKeyboardButton(t("btn_delete", lang), callback_data=f"delete_{lid}")],
        ]
        kb = InlineKeyboardMarkup(btns)
        await send_listing(update.message, caption, row, kb)
    return MAIN_MENU

async def manage_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    parts   = query.data.split("_")
    action  = parts[0]
    lid     = int(parts[1])
    conn    = db()
    row     = conn.execute("SELECT owner_id FROM listings WHERE id=?", (lid,)).fetchone()
    
    no_access_text = {"bg": "Няма достъп", "ru": "Нет доступа"}
    if not row or row[0] != user_id:
        await query.answer(no_access_text[lang], show_alert=True)
        conn.close()
        return MAIN_MENU

    if action == "edit":
        conn.close()
        # Показываем меню редактирования
        await query.message.reply_text(
            t("my_edit_title", lang, lid=lid),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("btn_edit_address2", lang), callback_data=f"editfield_address_{lid}"),
                 InlineKeyboardButton(t("btn_edit_phone2", lang),   callback_data=f"editfield_phone_{lid}")],
                [InlineKeyboardButton(t("btn_edit_price2", lang),   callback_data=f"editfield_price_{lid}"),
                 InlineKeyboardButton(t("btn_edit_desc2", lang),    callback_data=f"editfield_desc_{lid}")],
                [InlineKeyboardButton(t("btn_edit_photos2", lang),  callback_data=f"editfield_photo_{lid}")],
                [InlineKeyboardButton(t("btn_delete_listing", lang), callback_data=f"delete_{lid}")],
                [InlineKeyboardButton(t("btn_home", lang),          callback_data="go_home")],
            ])
        )
        return MAIN_MENU

    elif action == "delete":
        # Уведомляем подписчиков избранного перед удалением
        await notify_favorites_deleted(ctx.bot, lid)
        
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit()
        conn.close()
        await query.answer("🗑 Изтрито", show_alert=True)
        try:
            await query.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete message after listing deletion: {e}")
        return MAIN_MENU

    conn.close()
    try:
        await query.edit_message_reply_markup(None)
    except Exception:
        pass
    return MAIN_MENU

async def editfield_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Редактирование конкретного поля объявления."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)
    
    parts  = query.data.split("_")  # editfield_address_15
    field  = parts[1]
    lid    = int(parts[2])

    # Проверяем владельца
    conn = db()
    row = conn.execute("SELECT owner_id FROM listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    
    no_access_text = {"bg": "Няма достъп", "ru": "Нет доступа"}
    if not row or row[0] != user_id:
        await query.answer(no_access_text[lang], show_alert=True)
        return MAIN_MENU

    ctx.user_data["editfield_lid"] = lid
    ctx.user_data["editfield_field"] = field

    prompts = {
        "address": t("edit_prompt_address", lang),
        "phone":   t("edit_prompt_phone", lang),
        "price":   t("edit_prompt_price", lang),
        "desc":    t("edit_prompt_desc", lang),
        "photo":   t("edit_prompt_photo", lang),
    }
    await query.message.reply_text(
        prompts.get(field, t("edit_prompt_default", lang)),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(t("btn_cancel2", lang), callback_data="go_home")
        ]])
    )
    return EDIT_FIELD


async def editfield_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Сохранение отредактированного поля."""
    # Проверяем откуда пришло - от обычного пользователя или админа
    is_admin_edit = "adm_editfield_lid" in ctx.user_data
    
    if is_admin_edit:
        lid = ctx.user_data.get("adm_editfield_lid")
        field = ctx.user_data.get("adm_editfield_field")
    else:
        lid = ctx.user_data.get("editfield_lid")
        field = ctx.user_data.get("editfield_field")

    if not lid or not field:
        return MAIN_MENU

    conn = db()
    
    # Получаем старые значения для уведомления об изменениях
    old_listing = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    if not old_listing:
        conn.close()
        await update.message.reply_text("❌ Обява не е намерена!", reply_markup=home_ikb())
        return MAIN_MENU
    
    old_address = old_listing[5]
    old_phone = old_listing[6]
    old_price = old_listing[9]
    old_desc = old_listing[10]
    old_photo = old_listing[11]

    if field == "photo":
        if update.message.photo:
            photos = ctx.user_data.setdefault("editfield_photos" if not is_admin_edit else "adm_editfield_photos", [])
            file_id = update.message.photo[-1].file_id
            if file_id not in photos and len(photos) < 5:
                photos.append(file_id)

            # Ждём остальные фото через job_queue
            jobs = ctx.job_queue.get_jobs_by_name(f"editphoto_{update.effective_user.id}")
            for job in jobs:
                job.schedule_removal()

            async def save_photos(context):
                photos_list = context.job.data["photos"]
                lid_ = context.job.data["lid"]
                photo_json = json.dumps(photos_list) if photos_list else None
                c = db()
                c.execute("UPDATE listings SET photo_id=? WHERE id=?", (photo_json, lid_))
                c.commit(); c.close()
                await context.job.data["message"].reply_text(
                    f"✅ Снимките са обновени ({len(photos_list)} бр.)!",
                    reply_markup=home_ikb()
                )
                
                # Уведомляем подписчиков избранного
                await notify_favorites_changes(context.bot, lid_, "photo", None, len(photos_list))
                
                key = "editfield_photos" if not context.job.data.get("is_admin") else "adm_editfield_photos"
                context.job.data["user_data"].pop(key, None)

            ctx.job_queue.run_once(
                save_photos, when=1.5,
                name=f"editphoto_{update.effective_user.id}",
                data={"photos": photos, "lid": lid, "message": update.message, "user_data": ctx.user_data, "is_admin": is_admin_edit}
            )
            conn.close()
            return EDIT_FIELD

        elif update.message.text and update.message.text.strip() == "-":
            conn.execute("UPDATE listings SET photo_id=NULL WHERE id=?", (lid,))
            conn.commit(); conn.close()
            ctx.user_data.pop("editfield_photos" if not is_admin_edit else "adm_editfield_photos", None)
            await update.message.reply_text("✅ Снимките са премахнати!", reply_markup=home_ikb())
            
            # Уведомляем подписчиков избранного
            await notify_favorites_changes(ctx.bot, lid, "photo", "removed", None)
            
            return MAIN_MENU

        else:
            conn.close()
            return EDIT_FIELD

    text = update.message.text.strip()
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)

    if field == "address":
        result = await geocode(text)
        if result:
            lat, lon, display = result
            conn.execute("UPDATE listings SET address=?, lat=?, lon=? WHERE id=?", (display, lat, lon, lid))
            conn.commit(); conn.close()
            await update.message.reply_text(t("address_updated", lang, address=display), reply_markup=home_ikb(lang))
            
            # Уведомляем подписчиков избранного
            await notify_favorites_changes(ctx.bot, lid, "address", old_address, display)
        else:
            conn.close()
            await update.message.reply_text(t("address_not_found", lang))
            return EDIT_FIELD

    elif field == "phone":
        val = None if text == "-" else text
        conn.execute("UPDATE listings SET phone=? WHERE id=?", (val, lid))
        conn.commit(); conn.close()
        await update.message.reply_text(t("phone_updated", lang), reply_markup=home_ikb(lang))
        
        # Уведомляем подписчиков избранного
        await notify_favorites_changes(ctx.bot, lid, "phone", old_phone, val)

    elif field == "price":
        try:
            price = float(text.replace(",", ".").replace(" ", ""))
            conn.execute("UPDATE listings SET price=? WHERE id=?", (price, lid))
            conn.commit(); conn.close()
            await update.message.reply_text(t("price_updated", lang, price=f"{price:,.0f}"), reply_markup=home_ikb(lang))
            
            # Уведомляем подписчиков избранного
            await notify_favorites_changes(ctx.bot, lid, "price", old_price, price)
        except ValueError:
            conn.close()
            await update.message.reply_text(t("price_invalid", lang))
            return EDIT_FIELD

    elif field == "desc":
        val = None if text == "-" else text
        conn.execute("UPDATE listings SET description=? WHERE id=?", (val, lid))
        conn.commit(); conn.close()
        await update.message.reply_text("✅ Описанието е обновено!", reply_markup=home_ikb())
        
        # Уведомляем подписчиков избранного
        await notify_favorites_changes(ctx.bot, lid, "description", old_desc, val)

    # Очищаем user_data
    if is_admin_edit:
        ctx.user_data.pop("adm_editfield_lid", None)
        ctx.user_data.pop("adm_editfield_field", None)
    else:
        ctx.user_data.pop("editfield_lid", None)
        ctx.user_data.pop("editfield_field", None)

    return MAIN_MENU
    """Управление подписками: отключить, включить, удалить."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[0]
    sub_id = int(parts[1])
    user_id = query.from_user.id
    
    conn = db()
    row = conn.execute("SELECT user_id FROM search_subscriptions WHERE id=?", (sub_id,)).fetchone()
    if not row or row[0] != user_id:
        await query.answer("Няма достъп", show_alert=True)
        conn.close()
        return MAIN_MENU
    
    if action == "unsub":
        conn.execute("UPDATE search_subscriptions SET active=0 WHERE id=?", (sub_id,))
        conn.commit()
        await query.answer("⏸ Абонаментът е изключен")
    elif action == "resub":
        conn.execute("UPDATE search_subscriptions SET active=1 WHERE id=?", (sub_id,))
        conn.commit()
        await query.answer("✅ Абонаментът е включен")
    elif action == "delsub":
        conn.execute("DELETE FROM search_subscriptions WHERE id=?", (sub_id,))
        conn.commit()
        await query.answer("🗑 Абонаментът е изтрит")
        await query.message.reply_text(f"🗑 Абонамент #{sub_id} удалена.")
    
    conn.close()
    await query.edit_message_reply_markup(None)
    return MAIN_MENU


async def manage_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Управление подписками: отключить, включить, удалить, редактировать."""
    query = update.callback_query
    await query.answer()
    parts  = query.data.split("_")
    action = parts[0]
    sub_id = int(parts[1])
    user_id = query.from_user.id

    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM search_subscriptions WHERE id=?", (sub_id,)).fetchone()
        if not row or row[0] != user_id:
            await query.answer("Няма достъп", show_alert=True)
            return MAIN_MENU
        
        if action == "editsub":
            # Меню редактирования подписки
            await query.message.reply_text(
                f"✏️ *Редактиране на абонамент #{sub_id}*\n\nИзберете какво да промените:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📏 Радиус", callback_data=f"editsub_radius_{sub_id}")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="go_home")],
                ])
            )
            return MAIN_MENU
        
        elif action == "unsub":
            conn.execute("UPDATE search_subscriptions SET active=0 WHERE id=?", (sub_id,))
            await query.answer("⏸ Абонаментът е изключен", show_alert=True)
        elif action == "resub":
            conn.execute("UPDATE search_subscriptions SET active=1 WHERE id=?", (sub_id,))
            await query.answer("✅ Абонаментът е включен", show_alert=True)
        elif action == "delsub":
            conn.execute("DELETE FROM search_subscriptions WHERE id=?", (sub_id,))
            await query.answer("🗑 Абонаментът е изтрит", show_alert=True)

    try:
        await query.message.delete()
    except Exception:
        pass
    return MAIN_MENU


async def confirm_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Подтверждение актуальности объявления владельцем."""
    query = update.callback_query
    await query.answer()
    lid = int(query.data.split("_")[2])
    user_id = query.from_user.id

    with get_db() as conn:
        row = conn.execute("SELECT owner_id FROM listings WHERE id=?", (lid,)).fetchone()
        if not row or row[0] != user_id:
            await query.answer("Няма достъп", show_alert=True)
            return MAIN_MENU
        # Продлеваем на 7 дней от сейчас
        conn.execute(
            "UPDATE listings SET confirmed_at=datetime('now', '+7 days') WHERE id=?",
            (lid,)
        )

    await query.edit_message_text(
        f"✅ Обява *#{lid}* е потвърдена! Ще бъде активна още 7 дни.",
        parse_mode="Markdown",
        reply_markup=home_ikb()
    )
    return MAIN_MENU


async def show_map(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать геолокацию объявления на карте."""
    query = update.callback_query
    await query.answer()
    lid = int(query.data.split("_")[1])

    with get_db() as conn:
        row = conn.execute("SELECT lat, lon, address FROM listings WHERE id=?", (lid,)).fetchone()
        # Увеличиваем счётчик просмотров
        conn.execute("UPDATE listings SET views = COALESCE(views, 0) + 1 WHERE id=?", (lid,))

    if not row or not row[0]:
        await query.answer("Геолокацията не е налична", show_alert=True)
        return MAIN_MENU

    lat, lon, address = row
    await query.message.reply_location(latitude=lat, longitude=lon)
    await query.message.reply_text(f"📍 {address}")
    return MAIN_MENU
async def fix_addresses_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Админская команда: переопределяет адрес для всех обявиений где address выглядит как координаты."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Няма достъп.")
        return MAIN_MENU
    await update.message.reply_text("🔄 Обновляю адреса по координатам...")
    conn = db()
    rows = conn.execute("SELECT id, lat, lon, address FROM listings WHERE lat IS NOT NULL").fetchall()
    fixed = 0
    for lid, lat, lon, addr in rows:
        # Определяем что адрес "похож на координаты": содержит запятую и числа
        looks_like_coords = bool(re.match(r'^-?\d+\.\d+,\s*-?\d+\.\d+$', addr or ''))
        if looks_like_coords:
            new_addr = await reverse_geocode(lat, lon)
            if new_addr:
                new_addr_str = new_addr if isinstance(new_addr, str) else ", ".join(new_addr)
                conn.execute("UPDATE listings SET address=? WHERE id=?", (new_addr_str, lid))
                fixed += 1
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Готово! Обновлено обявиений: {fixed}")
    return MAIN_MENU

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    if user_id != ADMIN_ID:
        no_access_text = {"bg": "❌ Няма достъп.", "ru": "❌ Нет доступа."}
        await update.message.reply_text(no_access_text.get(lang, no_access_text["bg"]))
        return MAIN_MENU
    conn    = db()
    total   = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    active  = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
    users   = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
    msgs    = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    
    admin_panel_text = {
        "bg": f"🔧 *Админ-панель ParkPlace Varna*\n\n📋 Обяви: *{total}* (активни: {active})\n👥 Потребители: *{users}* · ✉️ Съобщения: *{msgs}*",
        "ru": f"🔧 *Админ-панель ParkPlace Varna*\n\n📋 Объявления: *{total}* (активных: {active})\n👥 Пользователи: *{users}* · ✉️ Сообщений: *{msgs}*"
    }
    
    await update.message.reply_text(
        admin_panel_text.get(lang, admin_panel_text["bg"]),
        parse_mode="Markdown", reply_markup=admin_keyboard(lang)
    )
    return ADMIN_MENU

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Няма достъп", show_alert=True)
        return ADMIN_MENU
    data = query.data

    if data.startswith("adm_listings_"):
        page  = int(data.replace("adm_listings_", ""))
        ctx.user_data["adm_page"] = page
        conn  = db()
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        rows  = conn.execute(
            "SELECT id,owner_name,action,type,address,price,active FROM listings ORDER BY id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, page * PAGE_SIZE)
        ).fetchall()
        conn.close()

        pages = math.ceil(total / PAGE_SIZE) or 1
        text  = f"📋 *Объявления* (стр. {page+1}/{pages} · всего {total}):\n\n"
        for lid, oname, action, ltype, addr, price, act in rows:
            s = "✅" if act else "⏸"
            text += f"{s} *#{lid}* · {ACTION_LABEL.get(action,action)} · {TYPE_LABEL.get(ltype,ltype)}\n"
            text += f"   📍 {addr or '—'} · 💰 {price:,.0f}€ · 👤 {oname or '—'}\n\n"

        btns = []
        for lid, _, _, _, _, _, act in rows:
            btns.append([
                InlineKeyboardButton(f"✏️ #{lid}", callback_data=f"adm_edit_{lid}_{page}"),
                InlineKeyboardButton(f"🗑 #{lid}", callback_data=f"adm_del_{lid}_{page}"),
            ])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"adm_listings_{page-1}"))
        if (page+1)*PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"adm_listings_{page+1}"))
        if nav: btns.append(nav)
        btns.append([InlineKeyboardButton("↩️ В меню", callback_data="adm_menu")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))
        return ADMIN_MENU

    elif data == "adm_menu":
        user_id = query.from_user.id
        lang = get_user_lang(user_id, ctx)
        
        conn   = db()
        total  = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
        users  = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
        msgs   = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        
        admin_menu_text = {
            "bg": f"🔧 *Админ-панель*\n\n📋 Обяви: {total} (активни: {active})\n👥 Потребители: {users} · ✉️ Съобщения: {msgs}",
            "ru": f"🔧 *Админ-панель*\n\n📋 Объявления: {total} (активных: {active})\n👥 Пользователи: {users} · ✉️ Сообщений: {msgs}"
        }
        
        await query.edit_message_text(
            admin_menu_text.get(lang, admin_menu_text["bg"]),
            parse_mode="Markdown", reply_markup=admin_keyboard(lang)
        )
        return ADMIN_MENU

    elif data == "adm_users":
        conn = db()
        rows = conn.execute(
            "SELECT owner_id,owner_name,COUNT(*) FROM listings GROUP BY owner_id ORDER BY 3 DESC LIMIT 20"
        ).fetchall()
        conn.close()
        text = "👥 *Пользователи:*\n\n"
        for uid, name, cnt in rows:
            text += f"• {name or '—'} · `{uid}` · {cnt} обяви\n"
        await query.edit_message_text(text or "Нет пользователей.", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ В меню", callback_data="adm_menu")]]))
        return ADMIN_MENU

    elif data == "adm_stats":
        user_id = query.from_user.id
        lang = get_user_lang(user_id, ctx)
        
        conn    = db()
        total   = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        active  = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
        sell    = conn.execute("SELECT COUNT(*) FROM listings WHERE action='sell'").fetchone()[0]
        lease   = conn.execute("SELECT COUNT(*) FROM listings WHERE action='lease'").fetchone()[0]
        parking = conn.execute("SELECT COUNT(*) FROM listings WHERE type='parking'").fetchone()[0]
        garage  = conn.execute("SELECT COUNT(*) FROM listings WHERE type='garage'").fetchone()[0]
        geo     = conn.execute("SELECT COUNT(*) FROM listings WHERE lat IS NOT NULL").fetchone()[0]
        users   = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
        msgs    = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        await query.edit_message_text(
            t("admin_stats", lang, total=total, active=active, sell=sell, lease=lease, 
              parking=parking, garage=garage, geo=geo, users=users, msgs=msgs),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_back_menu", lang), callback_data="adm_menu")]]))
        return ADMIN_MENU

    elif data == "adm_broadcast":
        user_id = query.from_user.id
        lang = get_user_lang(user_id, ctx)
        
        await query.edit_message_text(t("admin_broadcast_prompt", lang))
        return ADMIN_BROADCAST

    elif data.startswith("adm_edit_"):
        logger.info(f"Admin edit triggered: {data}")
        parts = data.split("_")
        lid, page = int(parts[2]), int(parts[3])
        logger.info(f"Editing listing {lid}, page {page}")
        
        await query.answer()
        
        # Сохраняем в user_data для возврата на правильную страницу
        ctx.user_data["adm_edit_page"] = page
        ctx.user_data["adm_edit_lid"] = lid
        
        # Показываем объявление с кнопками редактирования
        conn = db()
        listing = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
        conn.close()
        
        if not listing:
            logger.warning(f"Listing {lid} not found")
            await query.answer("Обява не е намерена", show_alert=True)
            return ADMIN_MENU
        
        logger.info(f"Listing found: {listing[0]}")
        
        # Отправляем фото и текст
        photos = get_photos(listing)
        caption = listing_text(listing)
        
        logger.info(f"Photos: {len(photos) if photos else 0}")
        
        # Кнопки редактирования
        edit_btns = [
            [InlineKeyboardButton("✏️ Адрес",    callback_data=f"adm_editfield_address_{lid}")],
            [InlineKeyboardButton("✏️ Телефон",  callback_data=f"adm_editfield_phone_{lid}")],
            [InlineKeyboardButton("✏️ Цена",     callback_data=f"adm_editfield_price_{lid}")],
            [InlineKeyboardButton("✏️ Описание", callback_data=f"adm_editfield_desc_{lid}")],
            [InlineKeyboardButton("✏️ Снимки",   callback_data=f"adm_editfield_photo_{lid}")],
            [InlineKeyboardButton("↩️ Назад",    callback_data=f"adm_listings_{page}")],
        ]
        
        chat_id = query.message.chat_id
        logger.info(f"Sending to chat_id: {chat_id}")
        
        # Удаляем старое сообщение
        try:
            await query.message.delete()
            logger.info("Old message deleted")
        except Exception as e:
            logger.warning(f"Could not delete admin listings message: {e}")
        
        # Отправляем новое через ctx.bot
        try:
            if photos:
                media_group = [InputMediaPhoto(media=photo) for photo in photos]
                await ctx.bot.send_media_group(chat_id=chat_id, media=media_group)
                logger.info("Media group sent")
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(edit_btns)
                )
                logger.info("Caption with buttons sent")
            else:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(edit_btns)
                )
                logger.info("Message with buttons sent (no photos)")
        except Exception as e:
            logger.error(f"Error sending edit message: {e}", exc_info=True)
        
        return ADMIN_MENU

    elif data.startswith("adm_del_"):
        parts = data.split("_")
        lid, page = int(parts[2]), int(parts[3])
        
        # Уведомляем подписчиков избранного перед удалением
        await notify_favorites_deleted(ctx.bot, lid)
        
        conn = db()
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit()
        conn.close()
        await query.answer(f"🗑 #{lid} удалено")
        
        # Показываем обновленный список (вместо изменения query.data)
        ctx.user_data["adm_page"] = page
        conn  = db()
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        rows  = conn.execute(
            "SELECT id,owner_name,action,type,address,price,active FROM listings ORDER BY id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, page * PAGE_SIZE)
        ).fetchall()
        conn.close()

        pages = math.ceil(total / PAGE_SIZE) or 1
        text  = f"📋 *Объявления* (стр. {page+1}/{pages} · всего {total}):\n\n"
        for lid, oname, action, ltype, addr, price, act in rows:
            s = "✅" if act else "⏸"
            text += f"{s} *#{lid}* · {ACTION_LABEL.get(action,action)} · {TYPE_LABEL.get(ltype,ltype)}\n"
            text += f"   📍 {addr or '—'} · 💰 {price:,.0f}€ · 👤 {oname or '—'}\n\n"

        btns = []
        for lid, _, _, _, _, _, act in rows:
            btns.append([
                InlineKeyboardButton(f"✏️ #{lid}", callback_data=f"adm_edit_{lid}_{page}"),
                InlineKeyboardButton(f"🗑 #{lid}", callback_data=f"adm_del_{lid}_{page}"),
            ])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"adm_listings_{page-1}"))
        if (page+1)*PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"adm_listings_{page+1}"))
        if nav: btns.append(nav)
        btns.append([InlineKeyboardButton("↩️ В меню", callback_data="adm_menu")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))
        return ADMIN_MENU

    elif data.startswith("adm_editfield_"):
        # Админ редактирует поле объявления (без проверки owner_id)
        parts = data.split("_")  # adm_editfield_address_15
        field = parts[2]
        lid = int(parts[3])
        
        # Сохраняем контекст для возврата
        ctx.user_data["adm_editfield_lid"] = lid
        ctx.user_data["adm_editfield_field"] = field
        
        prompts = {
            "address": "📍 Въведете нов *адрес*:",
            "phone":   "📞 Въведете нов *телефон* (или «-» за да премахнете):",
            "price":   "💰 Въведете нова *цена* (число, €):",
            "desc":    "📝 Въведете ново *описание* (или «-» за да премахнете):",
            "photo":   "📸 Изпратете нови *снимки* (до 5, или «-» за да премахнете всички):",
        }
        await query.message.reply_text(
            prompts.get(field, "Въведете нова стойност:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отказ", callback_data="go_home")
            ]])
        )
        return EDIT_FIELD

    return ADMIN_MENU

async def admin_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return MAIN_MENU
    text = update.message.text.strip()
    if text.lower() == "отмена":
        await update.message.reply_text("❌ Отменено.", reply_markup=admin_keyboard())
        return ADMIN_MENU
    conn = db()
    uids = set(
        [r[0] for r in conn.execute("SELECT DISTINCT owner_id FROM listings").fetchall()] +
        [r[0] for r in conn.execute("SELECT DISTINCT from_id FROM messages").fetchall()]
    )
    conn.close()
    sent = failed = 0
    for uid in uids:
        try:
            await ctx.bot.send_message(uid,
                f"📢 *Сообщение от администратора:*\n\n{text}", parse_mode="Markdown")
            # 🔴 FIX #2: Rate limiting - 20 сообщений/сек (безопасно для Telegram)
            await asyncio.sleep(0.05)
            sent += 1
        except Exception as e:
            # 🔴 FIX #3: Proper error logging
            logger.error(f"Broadcast error for user {uid}: {e}", exc_info=True)
            failed += 1
    await update.message.reply_text(
        f"✅ Готово! Отправлено: {sent} / Не доставлено: {failed}",
        reply_markup=admin_keyboard()
    )
    return ADMIN_MENU

# ═══════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# КОМАНДИ
# ══════════════════════════════════════════════════════════════

async def cmd_my(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /my — моите обяви."""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    conn = db()
    rows = conn.execute(
        "SELECT * FROM listings WHERE owner_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(t("my_no_listings", lang), reply_markup=home_ikb(lang))
        return MAIN_MENU

    # Сохраняем в user_data для пагинации
    ctx.user_data["my_listings"] = rows
    
    my_header = {"bg": f"📁 *Вашите обяви* ({len(rows)})", "ru": f"📁 *Ваши объявления* ({len(rows)})"}
    await update.message.reply_text(my_header[lang], parse_mode="Markdown")
    
    # Показываем первую страницу
    await show_my_listings_page(update.message, ctx, page=0)
    
    return MAIN_MENU


async def show_my_listings_page(message, ctx, page=0):
    """Показывает страницу своих объявлений (5 штук)."""
    user_id = message.chat.id
    lang = get_user_lang(user_id, ctx)
    
    ITEMS_PER_PAGE = 5
    
    rows = ctx.user_data.get("my_listings", [])
    total = len(rows)
    total_pages = math.ceil(total / ITEMS_PER_PAGE) if total > 0 else 1
    
    # Ограничиваем страницу
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_listings = rows[start:end]
    
    # Отправляем объявления
    for row in page_listings:
        lid, active = row[0], row[12]
        caption = listing_text(row, lang=lang)
        status = t("listing_status_active", lang) if active else t("listing_status_inactive", lang)
        buttons = [
            [InlineKeyboardButton(t("btn_edit", lang), callback_data=f"edit_{lid}"),
             InlineKeyboardButton(t("btn_delete", lang), callback_data=f"delete_{lid}")],
        ]
        kb2 = InlineKeyboardMarkup(buttons)
        await send_listing(message, f"{caption}\n\n{status}", row, kb2)
        await asyncio.sleep(0.05)  # Rate limiting
    
    # Кнопки навигации
    nav_buttons = []
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(t("btn_next_page", lang), callback_data=f"my_page_{page+1}"))
    
    home_button = [InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")]
    
    keyboard_rows = []
    if nav_buttons:
        keyboard_rows.append(nav_buttons)
    keyboard_rows.append(home_button)
    
    await message.reply_text(
        t("page_info", lang, page=page+1, total_pages=total_pages, total_listings=total),
        reply_markup=InlineKeyboardMarkup(keyboard_rows)
    )


async def my_listings_page_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик переключения страниц своих объявлений."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.replace("my_page_", ""))
    
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete my listings pagination message: {e}")
    
    await show_my_listings_page(query.message, ctx, page=page)
    
    return MAIN_MENU


async def cmd_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /favorites — любими."""
    return await show_favorites(update, ctx)


async def cmd_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /subscriptions — абонаменти."""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    conn = db()
    rows = conn.execute(
        "SELECT id, search_type, action, radius, created_at, expires_at, active "
        "FROM search_subscriptions WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(t("sub_no_listings", lang), reply_markup=home_ikb(lang))
        return MAIN_MENU

    sub_header = {"bg": f"🔔 *Вашите абонаменти* ({len(rows)})", "ru": f"🔔 *Ваши подписки* ({len(rows)})"}
    await update.message.reply_text(sub_header[lang], parse_mode="Markdown")
    
    import datetime
    for sub_id, stype, act, radius, created, expires, active in rows:
        km_text = {"bg": "км", "ru": "км"}
        m_text = {"bg": "м", "ru": "м"}
        radius_text = f"{radius//1000} {km_text[lang]}" if radius >= 1000 else f"{radius} {m_text[lang]}"
        type_text   = get_type_label(stype, lang)
        action_text = get_action_label(act, lang)
        
        status_active = {"bg": "✅ Активен", "ru": "✅ Активна"}
        status_paused = {"bg": "⏸ Изключен", "ru": "⏸ Приостановлена"}
        status_expired = {"bg": "⏰ Изтекъл", "ru": "⏰ Истекла"}
        
        status = status_active[lang] if active else status_paused[lang]
        if expires:
            try:
                exp = datetime.datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
                if exp < datetime.datetime.now():
                    status = status_expired[lang]
            except Exception:
                pass

        sub_text_template = {
            "bg": f"🔔 *Абонамент #{sub_id}*\n• {action_text} · {type_text}\n• Радиус: {radius_text}\n📅 {created[:10]} → {expires[:10] if expires else '—'}\n{status}",
            "ru": f"🔔 *Подписка #{sub_id}*\n• {action_text} · {type_text}\n• Радиус: {radius_text}\n📅 {created[:10]} → {expires[:10] if expires else '—'}\n{status}"
        }
        
        text = sub_text_template[lang]
        
        btns = [
            [InlineKeyboardButton(t("btn_edit", lang), callback_data=f"editsub_{sub_id}")],
        ]
        if active:
            btns.append([InlineKeyboardButton(t("btn_pause", lang), callback_data=f"unsub_{sub_id}"),
                         InlineKeyboardButton(t("btn_delete", lang), callback_data=f"delsub_{sub_id}")])
        else:
            btns.append([InlineKeyboardButton(t("btn_resume", lang), callback_data=f"resub_{sub_id}"),
                         InlineKeyboardButton(t("btn_delete", lang), callback_data=f"delsub_{sub_id}")])
        
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns)
        )
    return MAIN_MENU


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /help — помощ."""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)
    
    await update.message.reply_text(t("help_text", lang), parse_mode="Markdown", reply_markup=home_ikb(lang))
    return MAIN_MENU


# ══════════════════════════════════════════════════════════════
# ЛЮБИМИ (ИЗБРАННОЕ)
# ══════════════════════════════════════════════════════════════

async def show_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать избранное пользователя."""
    query = update.callback_query if update.callback_query else None
    user_id = update.effective_user.id
    lang = get_user_lang(user_id, ctx)

    if query:
        await query.answer()

    conn = db()
    favorites = conn.execute("""
        SELECT l.* FROM listings l
        JOIN favorites f ON l.id = f.listing_id
        WHERE f.user_id = ? AND l.active = 1
        ORDER BY f.created_at DESC
    """, (user_id,)).fetchall()
    conn.close()

    if not favorites:
        if query:
            await query.edit_message_text(t("fav_empty", lang), reply_markup=home_ikb(lang))
        else:
            await update.message.reply_text(t("fav_empty", lang), reply_markup=home_ikb(lang))
        return MAIN_MENU

    # Сохраняем для пагинации
    ctx.user_data["favorites_listings"] = favorites

    fav_header = {"bg": f"⭐ *Любими* ({len(favorites)} обяви)", "ru": f"⭐ *Избранное* ({len(favorites)} объявлений)"}
    if query:
        await query.edit_message_text(fav_header[lang], parse_mode="Markdown")
    else:
        await update.message.reply_text(fav_header[lang], parse_mode="Markdown")

    # Показываем первую страницу
    msg_target = query.message if query else update.message
    await show_favorites_page(msg_target, ctx, page=0)

    return MAIN_MENU


async def show_favorites_page(message, ctx, page=0):
    """Показывает страницу избранного (5 объявлений)."""
    user_id = message.chat.id
    lang = get_user_lang(user_id, ctx)
    
    ITEMS_PER_PAGE = 5
    
    favorites = ctx.user_data.get("favorites_listings", [])
    total = len(favorites)
    total_pages = math.ceil(total / ITEMS_PER_PAGE) if total > 0 else 1
    
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_listings = favorites[start:end]
    
    for row in page_listings:
        lid = row[0]
        caption = listing_text(row, lang=lang)
        buttons = [
            [InlineKeyboardButton(t("btn_remove_fav", lang), callback_data=f"unfav_{lid}")],
            [InlineKeyboardButton(t("btn_on_map", lang), callback_data=f"map_{lid}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        try:
            await send_listing(message, caption, row, keyboard)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Error showing favorite {lid}: {e}")
            await message.reply_text(caption, reply_markup=keyboard, parse_mode="Markdown")
    
    # Навигация
    nav_buttons = []
    # Навигация
    nav_buttons = []
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(t("btn_next_page", lang), callback_data=f"fav_page_{page+1}"))
    
    keyboard_rows = []
    if nav_buttons:
        keyboard_rows.append(nav_buttons)
    keyboard_rows.append([InlineKeyboardButton(t("btn_home", lang), callback_data="go_home")])
    
    await message.reply_text(
        t("page_info", lang, page=page+1, total_pages=total_pages, total_listings=total),
        reply_markup=InlineKeyboardMarkup(keyboard_rows)
    )


async def favorites_page_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик переключения страниц избранного."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.replace("fav_page_", ""))
    
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete favorites pagination message: {e}")
    
    await show_favorites_page(query.message, ctx, page=page)
    
    return MAIN_MENU


async def toggle_favorite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Добавить/удалить из избранного."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    lang = get_user_lang(user_id, ctx)

    parts = query.data.split("_")
    action = parts[0]   # fav или unfav
    lid = int(parts[1])

    conn = db()
    if action == "fav":
        try:
            conn.execute("INSERT INTO favorites (user_id, listing_id) VALUES (?, ?)", (user_id, lid))
            conn.commit()
            await query.answer(t("fav_added", lang), show_alert=True)
        except Exception:
            await query.answer(t("fav_already", lang), show_alert=True)
    else:
        conn.execute("DELETE FROM favorites WHERE user_id=? AND listing_id=?", (user_id, lid))
        conn.commit()
        await query.answer(t("fav_removed", lang), show_alert=True)
    conn.close()

    return MAIN_MENU


def main():
    # Создаём директорию для данных если не существует (для Railway Volume)
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Database file: {DB_FILE}")
    
    init_db()
    
    # 🔴 FIX #1: Добавляем Persistence (предотвращает потерю данных платежей)
    from telegram.ext import PicklePersistence
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    # ── Global error handler ───────────────────────────────────
    async def error_handler(update, context):
        logger.error("Exception:", exc_info=context.error)
        
        # Игнорируем Conflict при деплое (два инстанса бота)
        err_text = str(context.error)
        if "Conflict" in err_text and "getUpdates" in err_text:
            return
        
        # Уведомляем администратора
        try:
            upd_info = f"Update: {update}" if update else "No update"
            await context.bot.send_message(
                ADMIN_ID,
                f"🚨 *Ошибка бота:*\n`{err_text[:200]}`\n\n_{upd_info[:100]}_",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    app.add_error_handler(error_handler)

    # ── Rate limiting ──────────────────────────────────────────
    _user_last_action: dict = {}
    RATE_LIMIT_SECONDS = 1  # Минимум 1 сек между запросами

    async def rate_limit_middleware(update, context, next_handler):
        if update.effective_user:
            uid = update.effective_user.id
            now = datetime.datetime.now().timestamp()
            last = _user_last_action.get(uid, 0)
            if now - last < RATE_LIMIT_SECONDS:
                return  # Игнорируем слишком частые запросы
            _user_last_action[uid] = now
        return await next_handler(update, context)

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",         start),
            CommandHandler("cancel",        start),
            CommandHandler("my",            cmd_my),
            CommandHandler("favorites",     cmd_favorites),
            CommandHandler("subscriptions", cmd_subscriptions),
            CommandHandler("help",          cmd_help),
            CommandHandler("admin",         admin_cmd),
            CommandHandler("fixaddresses",  fix_addresses_cmd),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(go_home,              pattern="^go_home$"),
                CallbackQueryHandler(search_page_handler,  pattern="^search_page_"),
                CallbackQueryHandler(my_listings_page_handler, pattern="^my_page_"),
                CallbackQueryHandler(favorites_page_handler, pattern="^fav_page_"),
                CallbackQueryHandler(change_radius,        pattern="^change_radius$"),
                CallbackQueryHandler(subscribe_to_notifications, pattern="^subscribe$"),
                CallbackQueryHandler(toggle_favorite,      pattern="^(fav|unfav)_"),
                CallbackQueryHandler(show_map,             pattern="^map_"),
                CallbackQueryHandler(manage_listing,       pattern="^(edit|delete)_"),
                CallbackQueryHandler(editfield_callback,   pattern="^editfield_"),
                CallbackQueryHandler(manage_subscription,  pattern="^(unsub|resub|delsub|editsub)_"),
                CallbackQueryHandler(confirm_listing,      pattern="^confirm_listing_"),
                CallbackQueryHandler(start_action,         pattern="^start_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu),
            ],
            # Подача обявиения
            AD_TYPE: [
                CallbackQueryHandler(ad_type_chosen, pattern="^adtype_"),
                CallbackQueryHandler(go_home,        pattern="^go_home$"),
            ],
            AD_LOCATION_CHOICE: [
                CallbackQueryHandler(ad_location_choice, pattern="^adloc_"),
                CallbackQueryHandler(go_home,            pattern="^go_home$"),
            ],
            AD_ADDRESS_TEXT: [
                CallbackQueryHandler(go_home, pattern="^go_home$"),
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_address_text),
            ],
            AD_ADDRESS_CONFIRM: [
                CallbackQueryHandler(ad_address_confirm, pattern="^addrconfirm_"),
                CallbackQueryHandler(go_home,            pattern="^go_home$"),
            ],
            AD_LOCATION_GEO: [
                CallbackQueryHandler(go_home, pattern="^go_home$"),
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.LOCATION, ad_location_geo),
            ],
            AD_PHONE: [
                CallbackQueryHandler(go_home, pattern="^go_home$"),
                MessageHandler(filters.CONTACT, ad_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_phone),
            ],
            AD_PRICE: [
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_price),
            ],
            AD_DESCRIPTION: [
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_description),
            ],
            AD_PHOTO: [
                CallbackQueryHandler(go_home, pattern="^go_home$"),
                CallbackQueryHandler(ad_photo, pattern="^photos_done$"),
                MessageHandler(filters.PHOTO, ad_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_photo),
            ],
            AD_CONFIRM: [
                CallbackQueryHandler(ad_edit_callback, pattern="^ad_edit_"),
                CallbackQueryHandler(ad_publish, pattern="^ad_(publish|cancel)$"),
                CallbackQueryHandler(go_home,    pattern="^go_home$"),
            ],
            # Поиск
            SEARCH_TYPE: [
                CallbackQueryHandler(search_type_chosen, pattern="^stype_"),
                CallbackQueryHandler(go_home,            pattern="^go_home$"),
            ],
            SEARCH_LOCATION_CHOICE: [
                CallbackQueryHandler(search_location_choice, pattern="^sloc_"),
                CallbackQueryHandler(go_home,                pattern="^go_home$"),
            ],
            SEARCH_ADDRESS_TEXT: [
                CallbackQueryHandler(go_home, pattern="^go_home$"),
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_address_text),
            ],
            SEARCH_GEO: [
                CallbackQueryHandler(go_home, pattern="^go_home$"),
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.LOCATION, search_geo_input),
            ],
            SEARCH_RADIUS: [
                CallbackQueryHandler(search_radius_chosen,        pattern="^radius_"),
                CallbackQueryHandler(search_page_handler,         pattern="^search_page_"),
                CallbackQueryHandler(subscribe_to_notifications,  pattern="^subscribe$"),
                CallbackQueryHandler(toggle_favorite,             pattern="^(fav|unfav)_"),
                CallbackQueryHandler(show_map,                    pattern="^map_"),
                CallbackQueryHandler(change_radius,               pattern="^change_radius$"),
                CallbackQueryHandler(go_home,                     pattern="^go_home$"),
            ],
            # Админ
            ADMIN_MENU: [
                CallbackQueryHandler(go_home,        pattern="^go_home$"),
                CallbackQueryHandler(admin_callback, pattern="^adm_"),
            ],
            ADMIN_BROADCAST: [
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send),
            ],
            EDIT_FIELD: [
                CallbackQueryHandler(go_home,           pattern="^go_home$"),
                CallbackQueryHandler(editfield_callback, pattern="^editfield_"),
                MessageHandler(filters.PHOTO, editfield_save),
                MessageHandler(filters.TEXT & ~filters.COMMAND, editfield_save),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
            CommandHandler("fixaddresses", fix_addresses_cmd),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cmd_language_button, pattern="^language$"))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CallbackQueryHandler(set_language_callback, pattern="^lang_"))
    
    # Payment handlers (outside ConversationHandler)
    from telegram.ext import PreCheckoutQueryHandler
    app.add_handler(PreCheckoutQueryHandler(handle_precheckout_query))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, handle_successful_payment))
    
    # Глобальные handlers для команд - работают даже если ConversationHandler потерял состояние
    app.add_handler(CommandHandler("my", cmd_my))
    app.add_handler(CommandHandler("favorites", cmd_favorites))
    app.add_handler(CommandHandler("subscriptions", cmd_subscriptions))
    app.add_handler(CommandHandler("help", cmd_help))
    
    # Глобальные callback handlers для кнопок главного меню - работают после редеплоя
    async def global_callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Перехватывает кнопки главного меню если ConversationHandler потерял состояние."""
        query = update.callback_query
        await query.answer()
        
        # Перенаправляем на start_action который обработает callback
        return await start_action(update, ctx)
    
    # Регистрируем для всех кнопок главного меню
    app.add_handler(CallbackQueryHandler(global_callback_router, pattern="^start_(buy|sell|rent|lease|mylistings|favorites|subscriptions)$"))
    
    # Глобальный handler для кнопки "🏠 Начало" - работает даже если ConversationHandler потерял состояние
    async def global_home_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Сбрасывает состояние и возвращает в главное меню."""
        user_id = update.effective_user.id
        lang = get_user_lang(user_id, ctx)
        
        ctx.user_data.clear()
        ctx.user_data["lang"] = lang
        
        await update.message.reply_text(
            t("welcome_short", lang),
            parse_mode="Markdown", 
            reply_markup=action_keyboard(lang)
        )
    
    app.add_handler(MessageHandler(filters.Regex("^🏠 (Начало|Главная)$"), global_home_button))
    
    # Устанавливаем команды для меню бота
    async def post_init(application):
        from telegram import BotCommand, BotCommandScopeDefault
        await application.bot.delete_my_commands(scope=BotCommandScopeDefault())
        commands = [
            BotCommand("start",         "🏠 Главно меню"),
            BotCommand("my",            "📁 Моите обяви"),
            BotCommand("favorites",     "⭐ Любими"),
            BotCommand("subscriptions", "🔔 Абонаменти"),
            BotCommand("help",          "ℹ️ Помощ"),
        ]
        await application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("✅ Команды установлены: %s", [c.command for c in commands])

    app.post_init = post_init

    # ── Планировщик задач ──────────────────────────────────────
    jq = app.job_queue

    async def job_confirm_listings(context):
        """Каждые 6 часов: просим подтвердить объявления старше 7 дней."""
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            rows = conn.execute(
                """SELECT l.id, l.owner_id, COALESCE(u.language, 'bg') as lang
                   FROM listings l
                   LEFT JOIN users u ON l.owner_id = u.user_id
                   WHERE l.active=1 AND l.confirmed_at < ?""",
                (cutoff,)
            ).fetchall()
            for lid, owner_id, lang in rows:
                try:
                    await context.bot.send_message(
                        owner_id,
                        t("confirm_listing_prompt", lang, lid=lid),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(t("btn_confirm_active", lang), callback_data=f"confirm_listing_{lid}")],
                            [InlineKeyboardButton(t("btn_delete_it", lang), callback_data=f"delete_{lid}")],
                        ])
                    )
                    # Обновляем confirmed_at чтобы не слать повторно
                    conn.execute(
                        "UPDATE listings SET confirmed_at=datetime('now', '+48 hours') WHERE id=?",
                        (lid,)
                    )
                except Exception as e:
                    logger.error(f"Confirm notify error for {owner_id}: {e}")

    async def job_auto_delete(context):
        """Раз в день: удаляем неподтверждённые объявления."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, owner_id FROM listings WHERE active=1 AND confirmed_at < ?",
                (now,)
            ).fetchall()
            for lid, owner_id in rows:
                # Уведомляем подписчиков избранного перед удалением
                await notify_favorites_deleted(context.bot, lid)
                
                conn.execute("DELETE FROM listings WHERE id=?", (lid,))
                try:
                    await context.bot.send_message(
                        owner_id,
                        f"🗑 Обява *#{lid}* е изтрита автоматично, тъй като не беше потвърдена навреме.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            if rows:
                logger.info(f"Auto-deleted {len(rows)} listings")

    async def job_cleanup_subscriptions(context):
        """Раз в день: деактивируем истёкшие подписки."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            result = conn.execute(
                "UPDATE search_subscriptions SET active=0 WHERE active=1 AND expires_at < ?",
                (now,)
            )
            if result.rowcount > 0:
                logger.info(f"Deactivated {result.rowcount} expired subscriptions")

    async def job_backup_db(context):
        """Раз в день: бэкап SQLite."""
        import shutil
        import glob
        try:
            backup_name = os.path.join(DATA_DIR, f"parking_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.db")
            shutil.copy(DB_FILE, backup_name)
            # Оставляем только последние 3 бэкапа
            backups = sorted(glob.glob(os.path.join(DATA_DIR, "parking_backup_*.db")))
            for old in backups[:-3]:
                os.remove(old)
            logger.info(f"✅ Backup created: {backup_name}")
        except Exception as e:
            logger.error(f"Backup failed: {e}")

    # Запускаем задачи
    jq.run_repeating(job_confirm_listings,      interval=6*3600,  first=60)
    jq.run_repeating(job_auto_delete,           interval=24*3600, first=120)
    jq.run_repeating(job_cleanup_subscriptions, interval=24*3600, first=180)
    jq.run_repeating(job_backup_db,             interval=24*3600, first=3600)

    logger.info("🤖 ParkPlace Varna запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
