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
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID   = 5053888378
DB_FILE    = "parking.db"
PAGE_SIZE  = 10
MAX_LISTINGS_PER_USER = 10
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

def fmt_dist(m):
    if m < 1000: return f"{round(m/10)*10:.0f} м от вас"
    elif m < 10000: return f"{m/1000:.1f} км от вас"
    else: return f"{m/1000:.0f} км от вас"

# ── Лейблы ────────────────────────────────────────────────────
ACTION_LABEL = {
    "buy":   "🛒 Купува",
    "sell":  "💰 Продава",
    "rent":  "🔑 Наем",
    "lease": "📋 Под наем",
}
TYPE_LABEL = {
    "parking": "🅿️ Паркомясто",
    "garage":  "🚘 Гараж",
    "all":     "📋 Всичко",
}


def has_purchased_contacts(buyer_id: int, listing_id: int) -> bool:
    """Проверяет купил ли пользователь доступ к контактам этого обявиения."""
    conn = db()
    result = conn.execute(
        "SELECT id FROM contact_purchases WHERE buyer_id=? AND listing_id=?",
        (buyer_id, listing_id)
    ).fetchone()
    conn.close()
    return result is not None

def listing_text(row, distance_m=None):
    """Формирует текст обявиения (все контакты видны всем)."""
    lid, owner_id, owner_name, action, ltype, address, phone, lat, lon, price, desc, photo, active, created, confirmed_at, views = row
    lines = [f"{ACTION_LABEL.get(action, action)} · {TYPE_LABEL.get(ltype, ltype)}"]
    
    if distance_m is not None:
        lines.append(f"📏 *{fmt_dist(distance_m)}*")
    
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
    """Отправить объявление — все фото в одной медиагруппе."""
    from telegram import InputMediaPhoto
    photos = get_photos(row)

    if not photos:
        # Нет фото — просто текст
        await message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)
    elif len(photos) == 1:
        # Одно фото — стандартно с кнопками
        await message.reply_photo(photos[0], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
    else:
        # 2-5 фото — медиагруппа с текстом на первом
        media = [InputMediaPhoto(media=photos[0], caption=caption, parse_mode="Markdown")]
        for p in photos[1:5]:
            media.append(InputMediaPhoto(media=p))
        await message.reply_media_group(media)
        # Кнопки сразу после (невидимый символ)
        await message.reply_text("​", reply_markup=keyboard)

# ── Клавиатуры ────────────────────────────────────────────────
def main_keyboard():
    """Пустая клавиатура - убираем ReplyKeyboard."""
    from telegram import ReplyKeyboardRemove
    return ReplyKeyboardRemove()

def home_ikb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Начало", callback_data="go_home")]])

def back_and_home_ikb(back_action="go_home"):
    """Кнопки Назад + На главную."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data=back_action)],
        [InlineKeyboardButton("🏠 Начало", callback_data="go_home")],
    ])

def action_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Купува",         callback_data="start_buy"),
         InlineKeyboardButton("💰 Продава",        callback_data="start_sell")],
        [InlineKeyboardButton("🔑 Наем",           callback_data="start_rent"),
         InlineKeyboardButton("📋 Под наем",       callback_data="start_lease")],
        [InlineKeyboardButton("📁 Моите обяви", callback_data="start_mylistings"),
         InlineKeyboardButton("⭐ Любими",       callback_data="start_favorites")],
        [InlineKeyboardButton("🔔 Абонаменти",   callback_data="start_subscriptions")],
    ])

def type_keyboard(prefix, include_all=False):
    rows = [
        [InlineKeyboardButton("🅿️ Паркомясто", callback_data=f"{prefix}_parking")],
        [InlineKeyboardButton("🚘 Гараж",       callback_data=f"{prefix}_garage")],
    ]
    if include_all:
        rows.append([InlineKeyboardButton("📋 Всичко наведнъж", callback_data=f"{prefix}_all")])
    rows.append([InlineKeyboardButton("🏠 Начало", callback_data="go_home")])
    return InlineKeyboardMarkup(rows)

def location_choice_keyboard(prefix):
    """Выбор способа указания местоположения."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Въвеждане на адрес",       callback_data=f"{prefix}_text")],
        [InlineKeyboardButton("📍 Изпращане на геолокация", callback_data=f"{prefix}_geo")],
        [InlineKeyboardButton("🏠 Начало",           callback_data="go_home")],
    ])

def geo_ad_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📍 Изпращане на геолокация на обекта", request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def geo_search_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📍 Изпращане на моята геолокация", request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def phone_keyboard():
    """Клавиатура с бутон за автоматично изпращане на вашия номер."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📱 Изпращане на моя номер", request_contact=True)],
        [KeyboardButton("⏩ Пропускане")],
    ], resize_keyboard=True, one_time_keyboard=True)

def radius_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("500 м", callback_data="radius_500"),
         InlineKeyboardButton("1 км",  callback_data="radius_1000")],
        [InlineKeyboardButton("2 км",  callback_data="radius_2000"),
         InlineKeyboardButton("5 км",  callback_data="radius_5000")],
        [InlineKeyboardButton("📋 Цяла Варна", callback_data="radius_all")],
        [InlineKeyboardButton("🏠 Начало", callback_data="go_home")],
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Обяви",   callback_data="adm_listings_0"),
         InlineKeyboardButton("👥 Потребители", callback_data="adm_users")],
        [InlineKeyboardButton("📊 Статистика",   callback_data="adm_stats"),
         InlineKeyboardButton("📢 Изпращане",     callback_data="adm_broadcast")],
        [InlineKeyboardButton("🏠 Начало",   callback_data="go_home")],
    ])

# ── /start ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    send = update.message.reply_text if update.message else update.callback_query.message.reply_text
    await send(
        "🚗 *Добре дошли в ParkPlace Varna!*\n\n"
        "Пазар за паркоместа и гаражи във Варна.\n\n"
        "Изберете действие от менюто:",
        parse_mode="Markdown", reply_markup=action_keyboard()
    )
    return MAIN_MENU

async def go_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        "🚗 *ParkPlace Varna*\nКакво искате да направите?",
        parse_mode="Markdown", reply_markup=action_keyboard()
    )
    return MAIN_MENU

# ── Текстовое меню ────────────────────────────────────────────
async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Начало":
        ctx.user_data.clear()
        await update.message.reply_text(
            "🚗 *ParkPlace Varna*\nКакво искате да направите?",
            parse_mode="Markdown", reply_markup=action_keyboard()
        )
        return MAIN_MENU
    elif text == "📁 Моите обяви":
        return await show_my_listings(update, ctx)
    elif text == "ℹ️ Помощ":
        await update.message.reply_text(
            "*Как да използвате:*\n\n"
            "🛒 *Купува / Наем* — намиране на обект\n"
            "💰 *Продава / Под наем* — публикуване на обява\n\n"
            "📍 *Местоположение на обекта:*\n"
            "Можете да въведете адрес като текст — ботът ще го намери на картата.\n"
            "Или изпратете геолокация чрез 📎 → Геолокация.\n\n"
            "🔍 *Търсене по радиус* — посочете вашето местоположение\n"
            "и изберете радиус: 500м / 1км / 2км / 5км / Цяла Варна.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return MAIN_MENU
    await update.message.reply_text("Какво искате да направите?", reply_markup=action_keyboard())
    return MAIN_MENU

# ── Выбор действия ────────────────────────────────────────────

async def home_button_pressed(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка Reply-кнопки 'На главную' из любого состояния."""
    ctx.user_data.clear()
    await update.message.reply_text(
        "🚗 *ParkPlace Varna*\nКакво искате да направите?",
        parse_mode="Markdown", reply_markup=action_keyboard()
    )
    return MAIN_MENU

async def start_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("start_", "")

    # Любими
    if action == "favorites":
        return await show_favorites(update, ctx)

    # Мои обявиения
    if action == "mylistings":
        user_id = query.from_user.id
        conn = db()
        rows = conn.execute("SELECT * FROM listings WHERE owner_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("Все още нямате обяви.", reply_markup=home_ikb())
            return MAIN_MENU
        await query.edit_message_text(f"📁 Вашите обяви ({len(rows)}):", reply_markup=home_ikb())
        for row in rows:
            lid, active = row[0], row[12]
            status  = "✅ Активна" if active else "⏸ Неактивна"
            caption = listing_text(row) + f"\n{status}"
            btns = [
                [InlineKeyboardButton("✏️ Редактиране", callback_data=f"edit_{lid}"),
                 InlineKeyboardButton("🗑 Изтрий",      callback_data=f"delete_{lid}")],
            ]
            kb = InlineKeyboardMarkup(btns)
            await send_listing(query.message, caption, row, kb)
        return MAIN_MENU

    # Мои подписки
    if action == "subscriptions":
        user_id = query.from_user.id
        conn = db()
        rows = conn.execute(
            "SELECT id, search_type, action, lat, lon, radius, created_at, expires_at, active "
            "FROM search_subscriptions WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        conn.close()
        
        if not rows:
            await query.edit_message_text(
                "🔔 Нямате активни абонаменти.\n\n"
                "Абонаментите позволяват получаване на известия о новых обявиениях.",
                reply_markup=home_ikb()
            )
            return MAIN_MENU
        
        await query.edit_message_text(f"🔔 Вашите абонаменти ({len(rows)}):", reply_markup=home_ikb())
        
        for sub_id, stype, act, lat, lon, radius, created, expires, active in rows:
            import datetime
            
            radius_text = f"{radius//1000} км" if radius >= 1000 else f"{radius} м"
            type_text = TYPE_LABEL.get(stype, stype)
            action_text = ACTION_LABEL.get(act, act)
            status = "✅ Активна" if active else "⏸ Изключен"
            
            # Проверяем не истекла ли подписка
            if expires:
                exp_date = datetime.datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
                if exp_date < datetime.datetime.now():
                    status = "⏰ Изтекъл"
            
            text = (
                f"🔔 *Абонамент #{sub_id}*\n"
                f"• {action_text}\n"
                f"• {type_text}\n"
                f"• Радиус: {radius_text}\n"
                f"📅 Създаден: {created[:10]}\n"
                f"⏰ Изтича: {expires[:10] if expires else '—'}\n"
                f"{status}"
            )
            
            btns = []
            if active:
                btns.append(InlineKeyboardButton("⏸ Изключване", callback_data=f"unsub_{sub_id}"))
            else:
                btns.append(InlineKeyboardButton("▶️ Включване", callback_data=f"resub_{sub_id}"))
            btns.append(InlineKeyboardButton("🗑 Изтрий", callback_data=f"delsub_{sub_id}"))
            
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
            f"*{ACTION_LABEL[action]}* — изберете тип:",
            parse_mode="Markdown",
            reply_markup=type_keyboard("stype", include_all=True)
        )
        return SEARCH_TYPE
    else:
        # Проверяем лимит объявлений
        MAX_LISTINGS = 10
        conn = db()
        count = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE owner_id=? AND active=1", 
            (query.from_user.id,)
        ).fetchone()[0]
        conn.close()
        
        if count >= MAX_LISTINGS:
            await query.edit_message_text(
                f"⚠️ Достигнали сте лимита от *{MAX_LISTINGS} активни обяви*.\n\n"
                f"Изтрийте стари обяви за да добавите нови.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📁 Моите обяви", callback_data="start_mylistings")],
                    [InlineKeyboardButton("🏠 Начало",      callback_data="go_home")],
                ])
            )
            return MAIN_MENU

        ctx.user_data["ad"] = {"action": action}
        ctx.user_data["preview_shown"] = False
        ctx.user_data["published"] = False
        await query.edit_message_text(
            f"*{ACTION_LABEL[action]}* — изберете тип:",
            parse_mode="Markdown",
            reply_markup=type_keyboard("adtype", include_all=False)
        )
        return AD_TYPE

# ═══════════════════════════════════════════════════════════════
# ПОДАЧА ОБЪЯВЛЕНИЯ
# ═══════════════════════════════════════════════════════════════
async def ad_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["ad"]["type"] = query.data.replace("adtype_", "")
    await query.edit_message_text(
        "📍 Как да посочите местоположението на обекта?",
        reply_markup=location_choice_keyboard("adloc")
    )
    return AD_LOCATION_CHOICE

# Выбор способа — текст или геолокация
async def ad_location_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "adloc_text":
        await query.edit_message_text(
            "✏️ Въведете *адрес на обекта*:\n\n"
            "Например: _ул. Цар Симеон I 15_ или _бул. Приморски 42_\n\n"
            "Ботът ще намери това място на картата.",
            parse_mode="Markdown"
        )
        return AD_ADDRESS_TEXT

    elif query.data == "adloc_geo":
        await query.edit_message_text(
            "📍 Изпратете геолокация на обекта чрез бутона по-долу.\n\n"
            "Не е нужно да сте наблизо:\n"
            "📎 → Геолокация → намерете адрес → преместете маркера → Изпращане",
            parse_mode="Markdown"
        )
        await query.message.reply_text(
            "Натиснете бутона:", reply_markup=geo_ad_keyboard()
        )
        return AD_LOCATION_GEO

# Адрес текстом → геокодинг
async def ad_address_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    await update.message.reply_text("🔍 Търся на картата...")
    result = await geocode(address)
    if not result:
        await update.message.reply_text(
            "❌ Адресът не е намерен. Опитайте по-точно:\n"
            "_ул. Цар Симеон I 15_ или _бул. Владислав Варненчик 42_",
            parse_mode="Markdown"
        )
        return AD_ADDRESS_TEXT

    lat, lon, display = result
    ctx.user_data["ad"]["lat"]     = lat
    ctx.user_data["ad"]["lon"]     = lon
    ctx.user_data["ad"]["address"] = address

    await update.message.reply_location(latitude=lat, longitude=lon)
    await update.message.reply_text(
        f"📍 Намерих: _{display[:120]}_\n\nТова ли е правилното място?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, правилно",          callback_data="addrconfirm_ok")],
            [InlineKeyboardButton("❌ Не, въведи отново",  callback_data="addrconfirm_retry")],
            [InlineKeyboardButton("📍 Уточни с геолокация", callback_data="addrconfirm_geo")],
        ])
    )
    return AD_ADDRESS_CONFIRM

async def ad_address_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "addrconfirm_retry":
        await query.edit_message_text("✏️ Въведете адрес отново:")
        return AD_ADDRESS_TEXT

    elif query.data == "addrconfirm_geo":
        await query.edit_message_text(
            "📍 Изпратете точна геолокацию чрез 📎 → Геолокация:"
        )
        await query.message.reply_text("Натиснете бутона:", reply_markup=geo_ad_keyboard())
        return AD_LOCATION_GEO

    # ok — подтверждено, переходим к телефону
    await query.edit_message_text(
        "✅ Адрес подтверждён!",
    )
    await query.message.reply_text(
        "📞 *Телефонен номер* за връзка\n\n"
        "Натиснете бутона, за да изпратите вашия номер автоматично,\n"
        "или въведете номер ръчно, или натиснете «Пропускане».",
        parse_mode="Markdown",
        reply_markup=phone_keyboard()
    )
    return AD_PHONE

# Геолокация чрез скрепку
async def ad_location_geo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    ctx.user_data["ad"]["lat"] = loc.latitude
    ctx.user_data["ad"]["lon"] = loc.longitude

    # Если адрес ещё не задан — пробуем определить его по координатам
    if not ctx.user_data["ad"].get("address"):
        await update.message.reply_text("🔍 Определям адрес по геолокация...")
        addr = await reverse_geocode(loc.latitude, loc.longitude)
        if addr:
            ctx.user_data["ad"]["address"] = addr if isinstance(addr, str) else ", ".join(addr)
            msg = f"✅ Геолокацията е запазена!\n📍 *{ctx.user_data['ad']['address']}*\n\n"
        else:
            ctx.user_data["ad"]["address"] = f"{loc.latitude:.5f}, {loc.longitude:.5f}"
            msg = "✅ Геолокацията е запазена! (адресът не можа да бъде определен)\n\n"
    else:
        msg = "✅ Геолокацията е запазена!\n\n"

    await update.message.reply_text(
        msg + "📞 *Телефонен номер* за връзка\n\n"
        "Натиснете бутона, за да изпратите вашия номер автоматично,\n"
        "или въведете номер ръчно, или натиснете «Пропускане».",
        parse_mode="Markdown", reply_markup=phone_keyboard()
    )
    return AD_PHONE

async def ad_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Если пришёл контакт через кнопку
    if update.message.contact:
        ctx.user_data["ad"]["phone"] = update.message.contact.phone_number
    else:
        text = update.message.text.strip()
        if text == "⏩ Пропускане" or text == "-":
            ctx.user_data["ad"]["phone"] = None
        else:
            # Валидация телефона
            import re
            phone_clean = re.sub(r'[\s\-\(\)]', '', text)
            if not re.match(r'^\+?[0-9]{7,15}$', phone_clean):
                await update.message.reply_text(
                    "❌ Некоректен формат на телефон.\n"
                    "Пример: *+359888123456* или *0888123456*\n"
                    "Или натиснете «⏩ Пропускане»",
                    parse_mode="Markdown"
                )
                return AD_PHONE
            ctx.user_data["ad"]["phone"] = text

    from telegram import ReplyKeyboardRemove
    await update.message.reply_text(
        "💰 Въведете *цена* (число, €):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return AD_PRICE

async def ad_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip().replace(" ", "").replace(",", "."))
        ctx.user_data["ad"]["price"] = price
    except ValueError:
        await update.message.reply_text("❌ Въведете число, например: 5000")
        return AD_PRICE
    await update.message.reply_text(
        "📝 Добавете *описание* (площ, особености, достъп)\n"
        "Или «-» за да пропуснете:", parse_mode="Markdown"
    )
    return AD_DESCRIPTION

async def ad_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["ad"]["description"] = None if text == "-" else text
    ctx.user_data["ad"]["photos"] = []
    await update.message.reply_text(
        "📸 Изпратете до 5 снимки *наведнъж* (незадължително)\n\n"
        "Изберете всички снимки в галерията и изпратете с едно съобщение.\n"
        "Или «-» за да пропуснете:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏩ Пропускане (без снимки)", callback_data="photos_done")],
        ])
    )
    return AD_PHOTO

async def ad_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
            await context.job.data["message"].reply_text(
                f"✅ Получени *{cnt}* снимки.\nНатиснете *Готово* за да продължите:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"✅ Готово ({cnt} снимки)", callback_data="photos_done")],
                    [InlineKeyboardButton("⏩ Пропускане", callback_data="photos_done")],
                ])
            )

        ctx.job_queue.run_once(
            send_photo_prompt,
            when=1.5,
            name=f"photo_done_{update.effective_user.id}",
            data={"photos": photos, "message": update.message}
        )
        return AD_PHOTO

    # Что-то другое
    await update.message.reply_text(
        "📸 Изпратете снимки или натиснете *Пропускане*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏩ Пропускане", callback_data="photos_done")],
        ])
    )
    return AD_PHOTO


async def _show_ad_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать превью объявления перед публикацией."""
    # Защита от повторного вызова
    if ctx.user_data.get("preview_shown"):
        return AD_CONFIRM
    ctx.user_data["preview_shown"] = True

    ad = ctx.user_data["ad"]
    geo_line   = "🗺 Геолокация ✅" if ad.get("lat") else "🗺 Без геолокация"
    phone_line = f"📞 {ad['phone']}" if ad.get("phone") else "📞 Без телефон"
    photos     = ad.get("photos", [])
    photo_line = f"🖼 {len(photos)} снимки" if photos else "🖼 Без снимка"

    preview = (
        f"*Проверете обявата:*\n\n"
        f"{ACTION_LABEL.get(ad.get('action',''))} · {TYPE_LABEL.get(ad.get('type',''))}\n"
        f"📍 {ad.get('address', '—')}\n"
        f"{phone_line}\n"
        f"{geo_line}\n"
        f"💰 {ad.get('price', 0):,.0f} €\n"
    )
    if ad.get("description"):
        preview += f"📝 {ad['description']}\n"
    preview += photo_line

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Публикуване", callback_data="ad_publish")],
        [InlineKeyboardButton("✏️ Адрес",    callback_data="ad_edit_address"),
         InlineKeyboardButton("✏️ Телефон",  callback_data="ad_edit_phone")],
        [InlineKeyboardButton("✏️ Цена",     callback_data="ad_edit_price"),
         InlineKeyboardButton("✏️ Описание", callback_data="ad_edit_desc")],
        [InlineKeyboardButton("✏️ Снимки",   callback_data="ad_edit_photo")],
        [InlineKeyboardButton("❌ Отмена",   callback_data="ad_cancel")],
    ])

    msg = update.message if update.message else update.callback_query.message

    # Первое фото с текстом, остальные отдельно
    if len(photos) >= 1:
        from telegram import InputMediaPhoto
        # Первое фото с подписью и кнопками
        await msg.reply_photo(photos[0], caption=preview, parse_mode="Markdown", reply_markup=keyboard)
        # Остальные фото без текста
        if len(photos) > 1:
            media = [InputMediaPhoto(media=p) for p in photos[1:5]]
            await msg.reply_media_group(media)
    else:
        await msg.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)

    return AD_CONFIRM

async def ad_edit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок редактирования в финальном просмотре."""
    query = update.callback_query
    await query.answer()
    
    # Сбрасываем флаг preview_shown чтобы можно было показать превью снова
    ctx.user_data["preview_shown"] = False
    
    if query.data == "ad_edit_address":
        await query.message.reply_text(
            "📍 Как да посочите ново местоположение?",
            reply_markup=location_choice_keyboard("adloc")
        )
        return AD_LOCATION_CHOICE
    
    elif query.data == "ad_edit_phone":
        await query.message.reply_text(
            "📞 Натиснете бутона или въведете ръчно:",
            reply_markup=phone_keyboard()
        )
        return AD_PHONE
    
    elif query.data == "ad_edit_price":
        await query.message.reply_text("💰 Въведете нова *цена* (число, €):", parse_mode="Markdown")
        return AD_PRICE
    
    elif query.data == "ad_edit_desc":
        await query.message.reply_text(
            "📝 Въведете ново *описание*\nИли «-» за да премахнете:",
            parse_mode="Markdown"
        )
        return AD_DESCRIPTION
    
    elif query.data == "ad_edit_photo":
        await query.message.reply_text(
            "📸 Изпратете нови снимки (до 5)\nИли «-» за да премахнете:",
            parse_mode="Markdown"
        )
        return AD_PHOTO
    
    return AD_CONFIRM


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
                except Exception:
                    pass
            else:
                logger.error(f"Failed to notify user {user_id}: {e}")
    
    if notified > 0:
        logger.info(f"Notified {notified} subscribers about listing #{listing_id}")

async def ad_publish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ad_cancel":
        ctx.user_data["preview_shown"] = False
        await query.edit_message_text("❌ Обявата е отменена.", reply_markup=home_ikb())
        return MAIN_MENU

    # Защита от двойной публикации
    if ctx.user_data.get("published"):
        return MAIN_MENU
    ctx.user_data["published"] = True

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
        await query.edit_message_text("✅ Обявата е публикувана!", reply_markup=home_ikb())
    except Exception:
        await query.message.reply_text("✅ Обявата е публикувана!", reply_markup=home_ikb())
    return MAIN_MENU

# ═══════════════════════════════════════════════════════════════
# ПОИСК
# ═══════════════════════════════════════════════════════════════
async def search_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["search_type"] = query.data.replace("stype_", "")
    await query.edit_message_text(
        "📍 Как да посочите вашето местоположение за търсене?",
        reply_markup=location_choice_keyboard("sloc")
    )
    return SEARCH_LOCATION_CHOICE

async def search_location_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "sloc_text":
        await query.edit_message_text(
            "✏️ Въведете *вашия адрес*:\n\n"
            "Например: _ул. Цар Симеон I 15_\n\n"
            "Ботът ще го намери на картата и ще предложи радиус за търсене.",
            parse_mode="Markdown"
        )
        return SEARCH_ADDRESS_TEXT

    elif query.data == "sloc_geo":
        await query.edit_message_text(
            "📍 Изпратете вашата геолокация:\n\n"
            "• Натиснете бутона «Изпращане на моята геолокация» по-долу\n"
            "• Или чрез кламер 📎 → Геолокация → намерете място на картата → Изпращане"
        )
        await query.message.reply_text("Изберете начин:", reply_markup=geo_search_keyboard())
        return SEARCH_GEO

async def search_address_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    await update.message.reply_text("🔍 Търся на картата...")
    result = await geocode(address)
    if not result:
        await update.message.reply_text(
            "❌ Адресът не е намерен. Опитайте по-точно:"
        )
        return SEARCH_ADDRESS_TEXT
    lat, lon, display = result
    ctx.user_data["search_lat"] = lat
    ctx.user_data["search_lon"] = lon
    await update.message.reply_location(latitude=lat, longitude=lon)
    await update.message.reply_text(
        f"📍 _{display[:100]}_\n\n📏 Изберете *радиус поиска*:",
        parse_mode="Markdown", reply_markup=radius_keyboard()
    )
    return SEARCH_RADIUS

async def search_geo_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    ctx.user_data["search_lat"] = loc.latitude
    ctx.user_data["search_lon"] = loc.longitude
    await update.message.reply_text(
        "📏 Изберете *радиус поиска*:",
        parse_mode="Markdown", reply_markup=radius_keyboard()
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
    for row in rows:
        lat, lon = row[7], row[8]
        if user_lat and lat is not None:
            dist = haversine(user_lat, user_lon, lat, lon)
            if radius is None or dist <= radius:
                results.append((dist, row))
        elif radius is None:
            no_geo.append(row)

    results.sort(key=lambda x: x[0])
    total = len(results) + len(no_geo)

    if total == 0:
        rl = f"{radius//1000} км" if radius and radius >= 1000 else f"{radius} м" if radius else "вся Варна"
        
        # Сохраняем параметры поиска для подписки
        ctx.user_data["subscribe_params"] = {
            "search_type": ltype,
            "action": s_action,
            "lat": user_lat,
            "lon": user_lon,
            "radius": radius or 50000,
        }
        
        await query.edit_message_text(
            f"😕 В радиус {rl} няма намерени обяви.\n\n"
            f"💡 Искате ли да получавате известия когато се появи подходяща обява?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Абонамент за известия (⭐100 ≈ 2€)", callback_data="subscribe")],
                [InlineKeyboardButton("🔄 Промяна на радиус", callback_data="change_radius")],
                [InlineKeyboardButton("🏠 Начало",      callback_data="go_home")],
            ])
        )
        from telegram import ReplyKeyboardRemove
        await query.message.reply_text("​", reply_markup=ReplyKeyboardRemove())
        return MAIN_MENU

    rl = (f"{radius//1000} км" if radius >= 1000 else f"{radius} м") if radius else "вся Варна"

    logger.info(f"Search results: {len(results)} with geo, {len(no_geo)} without geo")

    from telegram import ReplyKeyboardRemove
    await query.edit_message_text(
        f"🔍 Намерени *{total}* обяви · радиус: {rl}",
        parse_mode="Markdown"
    )

    # Убираем кнопку геолокации БЕЗ лишнего сообщения
    # (отправляем невидимый символ чтобы просто убрать клавиатуру)
    try:
        await query.message.reply_text("​", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"ReplyKeyboardRemove error: {e}")

    for dist, row in results:
        lid = row[0]
        viewer_id = query.from_user.id
        caption = listing_text(row, distance_m=dist)
        logger.info(f"Sending listing {lid} to user {viewer_id}")

        conn = db()
        in_fav = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND listing_id=?",
            (viewer_id, lid)
        ).fetchone()
        conn.close()

        fav_text   = "💔 Премахни от любими" if in_fav else "⭐ В любими"
        fav_action = f"unfav_{lid}" if in_fav else f"fav_{lid}"
        keyboard   = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗺 На картата", callback_data=f"map_{lid}"),
             InlineKeyboardButton(fav_text, callback_data=fav_action)],
        ])

        try:
            await send_listing(query.message, caption, row, keyboard)
            logger.info(f"Listing {lid} sent successfully")
        except Exception as e:
            logger.error(f"Error listing {lid}: {e}", exc_info=True)
            try:
                await query.message.reply_text(caption, reply_markup=keyboard)
            except Exception as e2:
                logger.error(f"Error listing {lid} no md: {e2}")

    for row in no_geo:
        lid = row[0]
        viewer_id = query.from_user.id
        caption = listing_text(row)

        conn = db()
        in_favorites = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND listing_id=?",
            (viewer_id, lid)
        ).fetchone()
        conn.close()

        fav_text   = "💔 Премахни от любими" if in_favorites else "⭐ В любими"
        fav_action = f"unfav_{lid}" if in_favorites else f"fav_{lid}"
        keyboard   = InlineKeyboardMarkup([[InlineKeyboardButton(fav_text, callback_data=fav_action)]])

        try:
            await send_listing(query.message, caption, row, keyboard)
        except Exception as e:
            logger.error(f"Error no_geo listing {lid}: {e}")
            try:
                await query.message.reply_text(caption, reply_markup=keyboard)
            except Exception as e2:
                logger.error(f"Error no_geo listing {lid} no md: {e2}")

    # Финальное сообщение убирает ReplyKeyboard и показывает Начало
    await query.message.reply_text(
        "✅ Всички резултати са показани.",
        reply_markup=home_ikb()
    )
    return MAIN_MENU

async def change_radius(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📏 Изберете радиус:", reply_markup=radius_keyboard())
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
    type_label = TYPE_LABEL.get(ltype, ltype)
    
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
                caption = listing_text(row)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗺 На картата", callback_data=f"map_{lid}")],
                ])
                
                await update.message.reply_text(
                    f"✅ *Плащането е успешно!* (⭐ {price_stars} Stars)\n\n{caption}",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                await update.message.reply_text("✅ Оплата прошла, но обявиение не е намерено.")
        
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
    params = ctx.user_data.get("subscribe_params")

    if not params:
        await query.message.reply_text(
            "❌ Параметрите на търсенето са загубени, повторете търсенето.",
            reply_markup=home_ikb()
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
            "ℹ️ Вече имате активен абонамент с тези параметри!",
            reply_markup=home_ikb()
        )
        return MAIN_MENU

    # Сохраняем параметры для оплаты
    ctx.user_data["pending_subscription"] = params

    radius_text = f"{params['radius']//1000} км" if params['radius'] >= 1000 else f"{params['radius']} м"
    type_text   = TYPE_LABEL.get(params["search_type"], params["search_type"])
    action_text = ACTION_LABEL.get(params["action"], params["action"])

    # Отправляем инвойс Telegram Stars
    from telegram import LabeledPrice
    try:
        await ctx.bot.send_invoice(
            chat_id=user_id,
            title="🔔 Абонамент за известия",
            description=f"{action_text} · {type_text}\nРадиус: {radius_text}\nВалиден: 30 дни",
            payload=f"subscription_{user_id}_{params['search_type']}_{params['action']}",
            provider_token="",  # Empty for Stars
            currency="XTR",  # Telegram Stars
            prices=[LabeledPrice(label="Абонамент 30 дни", amount=100)],  # 100 Stars
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
    
    logger.info(f"Payment successful: {payment.telegram_payment_charge_id} from user {user_id}")
    
    params = ctx.user_data.get("pending_subscription")
    if not params:
        await update.message.reply_text("❌ Грешка: параметри не са намерени.")
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
    """Подтверждение предоплаты."""
    query = update.pre_checkout_query
    await query.answer(ok=True)

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
        await ctx.bot.send_message(owner_id,
            f"📩 *Сообщение* по обявиению #{lid}\nОт: {user.full_name} ({uinfo})\n\n{text}",
            parse_mode="Markdown")
        await update.message.reply_text("✅ Отправлено!", reply_markup=home_ikb())
    except Exception:
        await update.message.reply_text("✅ Запазено.", reply_markup=home_ikb())
    return MAIN_MENU

# ── Мои обявиения ────────────────────────────────────────────
async def show_my_listings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn    = db()
    rows    = conn.execute("SELECT * FROM listings WHERE owner_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Все още нямате обяви.", reply_markup=home_ikb())
        return MAIN_MENU
    await update.message.reply_text(f"📁 Вашите обяви ({len(rows)}):", reply_markup=home_ikb())
    for row in rows:
        lid, active = row[0], row[12]
        status  = "✅ Активна" if active else "⏸ Неактивна"
        caption = listing_text(row) + f"\n{status}"
        btns = [
            [InlineKeyboardButton("✏️ Редактиране", callback_data=f"edit_{lid}"),
             InlineKeyboardButton("🗑 Изтрий",      callback_data=f"delete_{lid}")],
        ]
        kb = InlineKeyboardMarkup(btns)
        await send_listing(update.message, caption, row, kb)
    return MAIN_MENU

async def manage_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    parts   = query.data.split("_")
    action  = parts[0]
    lid     = int(parts[1])
    user_id = query.from_user.id
    conn    = db()
    row     = conn.execute("SELECT owner_id FROM listings WHERE id=?", (lid,)).fetchone()
    if not row or row[0] != user_id:
        await query.answer("Няма достъп", show_alert=True)
        conn.close()
        return MAIN_MENU

    if action == "edit":
        conn.close()
        # Показываем меню редактирования
        await query.message.reply_text(
            f"✏️ *Редактиране на обява #{lid}*\nИзберете какво да промените:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Адрес",    callback_data=f"editfield_address_{lid}"),
                 InlineKeyboardButton("📞 Телефон",  callback_data=f"editfield_phone_{lid}")],
                [InlineKeyboardButton("💰 Цена",     callback_data=f"editfield_price_{lid}"),
                 InlineKeyboardButton("📝 Описание", callback_data=f"editfield_desc_{lid}")],
                [InlineKeyboardButton("📸 Снимки",   callback_data=f"editfield_photo_{lid}")],
                [InlineKeyboardButton("🗑 Изтрий обявата", callback_data=f"delete_{lid}")],
                [InlineKeyboardButton("🏠 Начало",   callback_data="go_home")],
            ])
        )
        return MAIN_MENU

    elif action == "delete":
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit()
        conn.close()
        await query.answer("🗑 Изтрито", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
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
    parts  = query.data.split("_")  # editfield_address_15
    field  = parts[1]
    lid    = int(parts[2])
    user_id = query.from_user.id

    # Проверяем владельца
    conn = db()
    row = conn.execute("SELECT owner_id FROM listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if not row or row[0] != user_id:
        await query.answer("Няма достъп", show_alert=True)
        return MAIN_MENU

    ctx.user_data["editfield_lid"] = lid
    ctx.user_data["editfield_field"] = field

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


async def editfield_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Сохранение отредактированного поля."""
    lid   = ctx.user_data.get("editfield_lid")
    field = ctx.user_data.get("editfield_field")

    if not lid or not field:
        return MAIN_MENU

    conn = db()

    if field == "photo":
        if update.message.photo:
            photos = ctx.user_data.setdefault("editfield_photos", [])
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
                context.job.data["user_data"].pop("editfield_photos", None)

            ctx.job_queue.run_once(
                save_photos, when=1.5,
                name=f"editphoto_{update.effective_user.id}",
                data={"photos": photos, "lid": lid, "message": update.message, "user_data": ctx.user_data}
            )
            conn.close()
            return EDIT_FIELD

        elif update.message.text and update.message.text.strip() == "-":
            conn.execute("UPDATE listings SET photo_id=NULL WHERE id=?", (lid,))
            conn.commit(); conn.close()
            ctx.user_data.pop("editfield_photos", None)
            await update.message.reply_text("✅ Снимките са премахнати!", reply_markup=home_ikb())
            return MAIN_MENU

        else:
            conn.close()
            return EDIT_FIELD

    text = update.message.text.strip()

    if field == "address":
        result = await geocode(text)
        if result:
            lat, lon, display = result
            conn.execute("UPDATE listings SET address=?, lat=?, lon=? WHERE id=?", (display, lat, lon, lid))
            conn.commit(); conn.close()
            await update.message.reply_text(f"✅ Адресът е обновен: {display}", reply_markup=home_ikb())
        else:
            conn.close()
            await update.message.reply_text("❌ Адресът не е намерен. Опитайте отново:")
            return EDIT_FIELD

    elif field == "phone":
        val = None if text == "-" else text
        conn.execute("UPDATE listings SET phone=? WHERE id=?", (val, lid))
        conn.commit(); conn.close()
        await update.message.reply_text("✅ Телефонът е обновен!", reply_markup=home_ikb())

    elif field == "price":
        try:
            price = float(text.replace(",", ".").replace(" ", ""))
            conn.execute("UPDATE listings SET price=? WHERE id=?", (price, lid))
            conn.commit(); conn.close()
            await update.message.reply_text(f"✅ Цената е обновена: {price:,.0f} €", reply_markup=home_ikb())
        except ValueError:
            conn.close()
            await update.message.reply_text("❌ Въведете число, например: 5000")
            return EDIT_FIELD

    elif field == "desc":
        val = None if text == "-" else text
        conn.execute("UPDATE listings SET description=? WHERE id=?", (val, lid))
        conn.commit(); conn.close()
        await update.message.reply_text("✅ Описанието е обновено!", reply_markup=home_ikb())

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
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Няма достъп.")
        return MAIN_MENU
    conn    = db()
    total   = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    active  = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
    users   = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
    msgs    = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"🔧 *Админ-панель ParkPlace Varna*\n\n"
        f"📋 Обяви: *{total}* (активных: {active})\n"
        f"👥 Потребители: *{users}* · ✉️ Сообщений: *{msgs}*",
        parse_mode="Markdown", reply_markup=admin_keyboard()
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
                InlineKeyboardButton(f"{'⏸' if act else '▶️'} #{lid}", callback_data=f"adm_toggle_{lid}_{page}"),
                InlineKeyboardButton(f"🗑 #{lid}",                       callback_data=f"adm_del_{lid}_{page}"),
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
        conn   = db()
        total  = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
        users  = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
        msgs   = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        await query.edit_message_text(
            f"🔧 *Админ-панель*\n\n"
            f"📋 Обяви: {total} (активных: {active})\n"
            f"👥 Потребители: {users} · ✉️ Сообщений: {msgs}",
            parse_mode="Markdown", reply_markup=admin_keyboard()
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
            f"📊 *Статистика:*\n\n"
            f"📋 Всего: {total} · Активни: {active}\n"
            f"💰 Продажа: {sell} · 📋 Аренда: {lease}\n"
            f"🅿️ Парковок: {parking} · 🚘 Гаражей: {garage}\n"
            f"🗺 С геолокацией: {geo}\n\n"
            f"👥 Потребители: {users} · ✉️ Сообщений: {msgs}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ В меню", callback_data="adm_menu")]]))
        return ADMIN_MENU

    elif data == "adm_broadcast":
        await query.edit_message_text("📢 Введите текст рассылки (или «отмена»):")
        return ADMIN_BROADCAST

    elif data.startswith("adm_toggle_"):
        parts = data.split("_")
        lid, page = int(parts[2]), int(parts[3])
        conn = db()
        cur  = conn.execute("SELECT active FROM listings WHERE id=?", (lid,)).fetchone()
        if cur:
            new = 0 if cur[0] else 1
            conn.execute("UPDATE listings SET active=? WHERE id=?", (new, lid))
            conn.commit()
            await query.answer("✅ Активирано" if new else "⏸ Неактивна")
        conn.close()
        query.data = f"adm_listings_{page}"
        return await admin_callback(update, ctx)

    elif data.startswith("adm_del_"):
        parts = data.split("_")
        lid, page = int(parts[2]), int(parts[3])
        conn = db()
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit()
        conn.close()
        await query.answer(f"🗑 #{lid} удалено")
        query.data = f"adm_listings_{page}"
        return await admin_callback(update, ctx)

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
            sent += 1
        except Exception:
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
    conn = db()
    rows = conn.execute(
        "SELECT * FROM listings WHERE owner_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Все още нямате обяви.", reply_markup=home_ikb())
        return MAIN_MENU

    await update.message.reply_text(f"📁 *Вашите обяви* ({len(rows)})", parse_mode="Markdown")
    for row in rows:
        lid, active = row[0], row[12]
        caption = listing_text(row)
        status = "✅ Активна" if active else "⏸ Неактивна"
        buttons = []
        if active:
            buttons.append([InlineKeyboardButton("⏸ Деактивиране", callback_data=f"deactivate_{lid}")])
        else:
            buttons.append([InlineKeyboardButton("▶️ Активиране",   callback_data=f"activate_{lid}")])
        buttons.append([InlineKeyboardButton("🗑 Изтрий", callback_data=f"delete_{lid}")])
        try:
            kb2 = InlineKeyboardMarkup(buttons)
            # Временно меняем текст для статуса
            row_with_status = row
            await send_listing(update.message, f"{caption}\n\n{status}", row_with_status, kb2)
        except Exception as e:
            logger.error(f"cmd_my error listing {lid}: {e}")
            await update.message.reply_text(
                f"{caption}\n\n{status}", reply_markup=InlineKeyboardMarkup(buttons)
            )
    return MAIN_MENU


async def cmd_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /favorites — любими."""
    return await show_favorites(update, ctx)


async def cmd_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /subscriptions — абонаменти."""
    user_id = update.effective_user.id
    conn = db()
    rows = conn.execute(
        "SELECT id, search_type, action, radius, created_at, expires_at, active "
        "FROM search_subscriptions WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("🔔 Нямате абонаменти.", reply_markup=home_ikb())
        return MAIN_MENU

    await update.message.reply_text(f"🔔 *Вашите абонаменти* ({len(rows)})", parse_mode="Markdown")
    import datetime
    for sub_id, stype, act, radius, created, expires, active in rows:
        radius_text = f"{radius//1000} км" if radius >= 1000 else f"{radius} м"
        type_text   = TYPE_LABEL.get(stype, stype)
        action_text = ACTION_LABEL.get(act, act)
        status = "✅ Активен" if active else "⏸ Изключен"
        if expires:
            try:
                exp = datetime.datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
                if exp < datetime.datetime.now():
                    status = "⏰ Изтекъл"
            except Exception:
                pass

        text = (
            f"🔔 *Абонамент #{sub_id}*\n"
            f"• {action_text} · {type_text}\n"
            f"• Радиус: {radius_text}\n"
            f"📅 {created[:10]} → {expires[:10] if expires else '—'}\n"
            f"{status}"
        )
        btns = [
            [InlineKeyboardButton("✏️ Редактиране", callback_data=f"editsub_{sub_id}")],
        ]
        if active:
            btns.append([InlineKeyboardButton("⏸ Изключване", callback_data=f"unsub_{sub_id}"),
                         InlineKeyboardButton("🗑 Изтрий", callback_data=f"delsub_{sub_id}")])
        else:
            btns.append([InlineKeyboardButton("▶️ Включване", callback_data=f"resub_{sub_id}"),
                         InlineKeyboardButton("🗑 Изтрий", callback_data=f"delsub_{sub_id}")])
        
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns)
        )
    return MAIN_MENU


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /help — помощ."""
    text = (
        "*ParkPlace Varna — паркоместа и гаражи*\n\n"
        "🛒 *Купува / Наем* — търсене на обект\n"
        "💰 *Продава / Под наем* — публикуване на обява\n"
        "⭐ *Любими* — запазени обяви\n"
        "🔔 *Абонаменти* — известия за нови обяви (⭐100 ≈ 2€)\n\n"
        "*Команди:*\n"
        "/start — Главно меню\n"
        "/my — Моите обяви\n"
        "/favorites — Любими\n"
        "/subscriptions — Абонаменти\n"
        "/help — Помощ\n\n"
        "_Обявите се изтриват автоматично ако не са потвърдени в рамките на 7 дни_"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=home_ikb())
    return MAIN_MENU


# ══════════════════════════════════════════════════════════════
# ЛЮБИМИ (ИЗБРАННОЕ)
# ══════════════════════════════════════════════════════════════

async def show_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать избранное пользователя."""
    query = update.callback_query if update.callback_query else None
    user_id = update.effective_user.id

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
        text = "⭐ Все още нямате любими обяви.\n\nДобавяйте обяви в любими, за да не ги загубите!"
        if query:
            await query.edit_message_text(text, reply_markup=home_ikb())
        else:
            await update.message.reply_text(text, reply_markup=home_ikb())
        return MAIN_MENU

    header = f"⭐ *Любими* ({len(favorites)} обяви)"
    if query:
        await query.edit_message_text(header, parse_mode="Markdown")
    else:
        await update.message.reply_text(header, parse_mode="Markdown")

    for row in favorites:
        lid = row[0]
        caption = listing_text(row)
        buttons = [
            [InlineKeyboardButton("💔 Премахни от любими", callback_data=f"unfav_{lid}")],
            [InlineKeyboardButton("🗺 На картата", callback_data=f"map_{lid}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        msg_target = query.message if query else update.message
        try:
            await send_listing(msg_target, caption, row, keyboard)
        except Exception as e:
            logger.error(f"Error showing favorite {lid}: {e}")
            await msg_target.reply_text(caption, reply_markup=keyboard)

    return MAIN_MENU


async def toggle_favorite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Добавить/удалить из избранного."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[0]   # fav или unfav
    lid = int(parts[1])
    user_id = query.from_user.id

    conn = db()
    if action == "fav":
        try:
            conn.execute("INSERT INTO favorites (user_id, listing_id) VALUES (?, ?)", (user_id, lid))
            conn.commit()
            await query.answer("⭐ Добавено в любими!", show_alert=True)
        except Exception:
            await query.answer("Вече в любими", show_alert=True)
    else:
        conn.execute("DELETE FROM favorites WHERE user_id=? AND listing_id=?", (user_id, lid))
        conn.commit()
        await query.answer("💔 Премахнато от любими", show_alert=True)
    conn.close()

    return MAIN_MENU


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Global error handler ───────────────────────────────────
    async def error_handler(update, context):
        logger.error("Exception:", exc_info=context.error)
        # Уведомляем администратора
        try:
            err_text = str(context.error)[:200]
            upd_info = f"Update: {update}" if update else "No update"
            await context.bot.send_message(
                ADMIN_ID,
                f"🚨 *Ошибка бота:*\n`{err_text}`\n\n_{upd_info[:100]}_",
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
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_address_text),
            ],
            AD_ADDRESS_CONFIRM: [
                CallbackQueryHandler(ad_address_confirm, pattern="^addrconfirm_"),
                CallbackQueryHandler(go_home,            pattern="^go_home$"),
            ],
            AD_LOCATION_GEO: [
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.LOCATION, ad_location_geo),
            ],
            AD_PHONE: [
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
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_address_text),
            ],
            SEARCH_GEO: [
                MessageHandler(filters.Regex("^🏠 Начало$"), home_button_pressed),
                MessageHandler(filters.LOCATION, search_geo_input),
            ],
            SEARCH_RADIUS: [
                CallbackQueryHandler(search_radius_chosen,        pattern="^radius_"),
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
    
    # Payment handlers (outside ConversationHandler)
    from telegram.ext import PreCheckoutQueryHandler
    app.add_handler(PreCheckoutQueryHandler(handle_precheckout_query))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, handle_successful_payment))
    
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
                "SELECT id, owner_id FROM listings WHERE active=1 AND confirmed_at < ?",
                (cutoff,)
            ).fetchall()
            for lid, owner_id in rows:
                try:
                    await context.bot.send_message(
                        owner_id,
                        f"⏰ *Обява #{lid}* е публикувана преди повече от 7 дни.\n\n"
                        f"Все още ли е актуална? Потвърдете в рамките на 48 часа, иначе ще бъде изтрита автоматично.",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Да, актуална е", callback_data=f"confirm_listing_{lid}")],
                            [InlineKeyboardButton("🗑 Изтрий я",       callback_data=f"delete_{lid}")],
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
        try:
            backup_name = f"parking_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.db"
            shutil.copy(DB_FILE, backup_name)
            # Оставляем только последние 3 бэкапа
            import glob
            backups = sorted(glob.glob("parking_backup_*.db"))
            for old in backups[:-3]:
                import os
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
