"""
ParkPlace Bot — покупка, продажа, аренда парковок и гаражей в Варне
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


# ════════════════════════════════════════════════════════════════
#                        ГЛОБАЛЬНЫЕ УТИЛИТЫ
# ════════════════════════════════════════════════════════════════

def main_menu_keyboard():
    """Основное меню снизу."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Създай обява")],
        [KeyboardButton("🔍 Търси"), KeyboardButton("📁 Моите обяви")],
        [KeyboardButton("⭐ Любими"), KeyboardButton("🔔 Абонаменти")],
        [KeyboardButton("💬 Съобщения"), KeyboardButton("ℹ️ Помощ")],
    ], resize_keyboard=True)

def back_button_keyboard():
    """Кнопка 'Начало' для возврата."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("🏠 Начало")]
    ], resize_keyboard=True)

async def safe_send(context, chat_id, text, **kw):
    """
    Безопасная отправка, избегаем повтора.
    Если последнее сообщение от бота == text, не шлём.
    """
    # Примитивная реализация, можно хранить last_msg в user_data
    try:
        await context.bot.send_message(chat_id, text, **kw)
    except Exception as e:
        logger.error(f"safe_send error: {e}")


# ════════════════════════════════════════════════════════════════
#                           START / HOME
# ════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало / Главное меню."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username or user.first_name}) started bot")
    
    text = (
        f"👋 *Добре дошли в ParkPlace Varna!*\n\n"
        f"🅿️ Пазар за паркоместа и гаражи във Варна\n\n"
        f"Изберете действие от менюто:"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def home_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажата кнопка 'Начало'."""
    context.user_data.clear()
    text = (
        f"🏠 *Главно меню*\n\n"
        f"Изберете действие от менюто:"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback 'go_home' — возврат в главное меню."""
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    text = (
        f"🏠 *Главно меню*\n\n"
        f"Изберете действие от менюто:"
    )
    await q.edit_message_text(
        text,
        parse_mode="Markdown"
    )
    await q.message.reply_text(
        "Изберете действие от менюто:",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                       ГЛАВНОЕ МЕНЮ (обработка)
# ════════════════════════════════════════════════════════════════

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Роутинг главного меню."""
    text = update.message.text
    user = update.effective_user
    
    if text == "➕ Създай обява":
        return await new_ad_start(update, context)
    elif text == "🔍 Търси":
        return await search_start(update, context)
    elif text == "📁 Моите обяви":
        return await my_listings(update, context)
    elif text == "⭐ Любими":
        return await show_favorites(update, context)
    elif text == "🔔 Абонаменти":
        return await show_subscriptions(update, context)
    elif text == "💬 Съобщения":
        return await show_messages(update, context)
    elif text == "ℹ️ Помощ":
        return await show_help(update, context)
    else:
        await update.message.reply_text(
            "❓ Неразпозната команда. Изберете от менюто.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                    СОЗДАНИЕ ОБЪЯВЛЕНИЯ
# ════════════════════════════════════════════════════════════════

async def new_ad_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: выбор действия (продава/купува/наем/под наем)."""
    user = update.effective_user
    
    # Проверка лимита
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE owner_id=? AND active=1",
            (user.id,)
        ).fetchone()[0]
    if count >= MAX_LISTINGS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнахте лимита от {MAX_LISTINGS_PER_USER} активни обяви.\n"
            f"Изтрийте някоя стара обява, за да добавите нова.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    context.user_data.clear()
    context.user_data["ad_draft"] = {}
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Продава", callback_data="adact_sell")],
        [InlineKeyboardButton("🛒 Купува", callback_data="adact_buy")],
        [InlineKeyboardButton("🔑 Под наем", callback_data="adact_lease")],
        [InlineKeyboardButton("📋 Търси наем", callback_data="adact_rent")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await update.message.reply_text(
        "📝 *Създаване на обява*\n\nКакво искате да направите?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return AD_TYPE

async def ad_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: действие выбрано → тип (паркомясто/гараж)."""
    q = update.callback_query
    await q.answer()
    
    action = q.data.split("_")[1]
    context.user_data["ad_draft"]["action"] = action
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🅿️ Паркомясто", callback_data="adtype_parking")],
        [InlineKeyboardButton("🚘 Гараж",      callback_data="adtype_garage")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await q.edit_message_text(
        f"*{ACTION_LABEL[action]}* — какво точно?\n\nИзберете тип:",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return AD_TYPE

async def ad_object_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: тип выбран → адрес."""
    q = update.callback_query
    await q.answer()
    
    obj_type = q.data.split("_")[1]
    context.user_data["ad_draft"]["type"] = obj_type
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Споделете локация", callback_data="adloc_geo")],
        [InlineKeyboardButton("✍️ Въведете адрес", callback_data="adloc_text")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await q.edit_message_text(
        f"*{TYPE_LABEL[obj_type]}* — отлично!\n\n"
        f"Къде се намира?\n\n"
        f"Можете да споделите локация или да въведете адрес (например: 'ул. Цар Освободител 15').",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return AD_LOCATION_CHOICE

async def ad_location_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора способа указания адреса."""
    q = update.callback_query
    await q.answer()
    
    choice = q.data.split("_")[1]
    
    if choice == "text":
        await q.edit_message_text(
            "✍️ Въведете адрес (например: 'ул. Шипка 10, Варна'):",
            parse_mode="Markdown"
        )
        await q.message.reply_text(
            "Напишете адреса:",
            reply_markup=back_button_keyboard()
        )
        return AD_ADDRESS_TEXT
    
    elif choice == "geo":
        await q.edit_message_text(
            "📍 Споделете локация чрез бутона 📎 → 'Location'.\n\n"
            "Или се върнете назад и изберете ръчно въвеждане на адрес.",
            parse_mode="Markdown"
        )
        await q.message.reply_text(
            "Споделете локация:",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("📍 Локация", request_location=True)],
                [KeyboardButton("🏠 Начало")]
            ], resize_keyboard=True)
        )
        return AD_LOCATION_GEO

async def ad_address_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь ввёл адрес текстом."""
    address = update.message.text.strip()
    
    await update.message.reply_text(
        "⏳ Проверявам адреса...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    result = await geocode(address)
    if not result:
        await update.message.reply_text(
            "❌ Не мога да намеря този адрес. Опитайте пак:",
            reply_markup=back_button_keyboard()
        )
        return AD_ADDRESS_TEXT
    
    lat, lon, display = result
    context.user_data["ad_draft"]["address"] = address
    context.user_data["ad_draft"]["lat"] = lat
    context.user_data["ad_draft"]["lon"] = lon
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Потвърждавам", callback_data=f"addrconfirm_yes")],
        [InlineKeyboardButton("🔄 Въведете отново", callback_data=f"addrconfirm_no")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await update.message.reply_text(
        f"📍 *Адрес:* {display}\n\n"
        f"Правилно ли е?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return AD_ADDRESS_CONFIRM

async def ad_address_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение адреса."""
    q = update.callback_query
    await q.answer()
    
    ans = q.data.split("_")[1]
    if ans == "no":
        await q.edit_message_text("✍️ Въведете адрес отново:")
        await q.message.reply_text(
            "Напишете адреса:",
            reply_markup=back_button_keyboard()
        )
        return AD_ADDRESS_TEXT
    
    # Адрес OK → телефон
    await q.edit_message_text(
        f"✅ Адресът е потвърден!",
        parse_mode="Markdown"
    )
    await q.message.reply_text(
        "📞 *Телефон за контакт*\n\n"
        "Въведете телефонен номер или споделете контакт:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("📱 Споделете телефон", request_contact=True)],
            [KeyboardButton("🏠 Начало")]
        ], resize_keyboard=True)
    )
    return AD_PHONE

async def ad_location_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь отправил геолокацию."""
    loc = update.message.location
    lat, lon = loc.latitude, loc.longitude
    
    await update.message.reply_text(
        "⏳ Проверявам локацията...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    address = await reverse_geocode(lat, lon)
    if not address:
        address = f"GPS: {lat:.5f}, {lon:.5f}"
    
    context.user_data["ad_draft"]["address"] = address
    context.user_data["ad_draft"]["lat"] = lat
    context.user_data["ad_draft"]["lon"] = lon
    
    await update.message.reply_text(
        f"✅ Локация получена: {address}",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        "📞 *Телефон за контакт*\n\n"
        "Въведете телефонен номер или споделете контакт:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("📱 Споделете телефон", request_contact=True)],
            [KeyboardButton("🏠 Начало")]
        ], resize_keyboard=True)
    )
    return AD_PHONE

async def ad_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод телефона."""
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    
    if not PHONE_RE.match(phone):
        await update.message.reply_text(
            "❌ Невалиден телефонен номер. Опитайте пак:",
            reply_markup=back_button_keyboard()
        )
        return AD_PHONE
    
    context.user_data["ad_draft"]["phone"] = phone
    
    await update.message.reply_text(
        "💵 *Цена*\n\n"
        "Въведете цена в лева (BGN), например: 150",
        parse_mode="Markdown",
        reply_markup=back_button_keyboard()
    )
    return AD_PRICE

async def ad_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод цены."""
    try:
        price = float(update.message.text.strip().replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Невалидна цена. Въведете число (например: 150):",
            reply_markup=back_button_keyboard()
        )
        return AD_PRICE
    
    context.user_data["ad_draft"]["price"] = price
    
    await update.message.reply_text(
        "📝 *Описание*\n\n"
        "Въведете описание на обявата (до 500 символа):",
        parse_mode="Markdown",
        reply_markup=back_button_keyboard()
    )
    return AD_DESCRIPTION

async def ad_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод описания."""
    desc = update.message.text.strip()
    if len(desc) > 500:
        await update.message.reply_text(
            f"❌ Описанието е твърде дълго ({len(desc)} символа). Максимум 500 символа.",
            reply_markup=back_button_keyboard()
        )
        return AD_DESCRIPTION
    
    context.user_data["ad_draft"]["description"] = desc
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Готово, без снимки", callback_data="photos_done")],
    ])
    await update.message.reply_text(
        "📷 *Снимки* (опционално)\n\n"
        "Изпратете до 5 снимки или натиснете 'Готово':",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return AD_PHOTO

async def ad_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загрузка фото."""
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        # Готово
        draft = context.user_data["ad_draft"]
        return await show_ad_preview(q.message, context, draft)
    
    if update.message.photo:
        photo = update.message.photo[-1]
        draft = context.user_data["ad_draft"]
        photos = draft.get("photos", [])
        if len(photos) >= 5:
            await update.message.reply_text("❌ Максимум 5 снимки.")
            return AD_PHOTO
        photos.append(photo.file_id)
        draft["photos"] = photos
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data="photos_done")],
        ])
        await update.message.reply_text(
            f"✅ Снимка {len(photos)}/5 добавена. Изпратете още или натиснете 'Готово':",
            reply_markup=kb
        )
        return AD_PHOTO
    
    # Текст вместо фото — пропускаем
    draft = context.user_data["ad_draft"]
    return await show_ad_preview(update.message, context, draft)

async def show_ad_preview(message, context, draft):
    """Показ превью объявления."""
    action_txt = ACTION_LABEL.get(draft["action"], "")
    type_txt = TYPE_LABEL.get(draft["type"], "")
    
    text = (
        f"📋 *Преглед на обявата*\n\n"
        f"{action_txt} {type_txt}\n"
        f"📍 *Адрес:* {draft['address']}\n"
        f"📞 *Телефон:* {draft['phone']}\n"
        f"💵 *Цена:* {draft['price']:.2f} лв\n"
        f"📝 *Описание:* {draft['description']}\n"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Редактирай адрес",  callback_data="ad_edit_address")],
        [InlineKeyboardButton("📞 Редактирай телефон", callback_data="ad_edit_phone")],
        [InlineKeyboardButton("💵 Редактирай цена",   callback_data="ad_edit_price")],
        [InlineKeyboardButton("📝 Редактирай описание", callback_data="ad_edit_description")],
        [InlineKeyboardButton("📷 Редактирай снимки",  callback_data="ad_edit_photos")],
        [InlineKeyboardButton("✅ Публикувай",         callback_data="ad_publish")],
        [InlineKeyboardButton("🗑 Отказ",              callback_data="ad_cancel")],
    ])
    
    photos = draft.get("photos", [])
    if photos:
        await message.reply_photo(
            photo=photos[0],
            caption=text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        await message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    
    return AD_CONFIRM

async def ad_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование поля объявления."""
    q = update.callback_query
    await q.answer()
    
    field = q.data.split("_")[2]
    context.user_data["edit_field"] = field
    
    if field == "address":
        await q.edit_message_caption(caption="✍️ Въведете нов адрес:")
        await q.message.reply_text(
            "Напишете адреса:",
            reply_markup=back_button_keyboard()
        )
    elif field == "phone":
        await q.edit_message_caption(caption="📞 Въведете нов телефон:")
        await q.message.reply_text(
            "Напишете телефона:",
            reply_markup=back_button_keyboard()
        )
    elif field == "price":
        await q.edit_message_caption(caption="💵 Въведете нова цена:")
        await q.message.reply_text(
            "Напишете цената:",
            reply_markup=back_button_keyboard()
        )
    elif field == "description":
        await q.edit_message_caption(caption="📝 Въведете ново описание:")
        await q.message.reply_text(
            "Напишете описанието:",
            reply_markup=back_button_keyboard()
        )
    elif field == "photos":
        context.user_data["ad_draft"]["photos"] = []
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data="photos_done")],
        ])
        await q.edit_message_caption(caption="📷 Изпратете нови снимки (до 5):")
        await q.message.reply_text(
            "Изпратете снимки:",
            reply_markup=kb
        )
        return AD_PHOTO
    
    return AD_CONFIRM

async def ad_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Публикация объявления."""
    q = update.callback_query
    await q.answer()
    
    if q.data == "ad_cancel":
        context.user_data.clear()
        await q.edit_message_caption(caption="❌ Обявата е отменена.")
        await q.message.reply_text(
            "Върнахте се в главното меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    draft = context.user_data["ad_draft"]
    user = update.effective_user
    
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO listings (owner_id, owner_name, action, type, address, phone, lat, lon, price, description, photo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user.id,
            user.first_name or user.username or "User",
            draft["action"],
            draft["type"],
            draft["address"],
            draft["phone"],
            draft["lat"],
            draft["lon"],
            draft["price"],
            draft["description"],
            ",".join(draft.get("photos", []))
        ))
        listing_id = cursor.lastrowid
    
    context.user_data.clear()
    
    await q.edit_message_caption(
        caption=f"✅ *Обявата е публикувана!*\n\nНомер: #{listing_id}",
        parse_mode="Markdown"
    )
    await q.message.reply_text(
        "Можете да я видите в 'Моите обяви'.",
        reply_markup=main_menu_keyboard()
    )
    
    # Уведомление подписчиков
    await notify_subscribers(context, listing_id)
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                      ПОИСК ОБЪЯВЛЕНИЙ
# ════════════════════════════════════════════════════════════════

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска: выбор типа."""
    context.user_data.clear()
    context.user_data["search"] = {}
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🅿️ Паркомясто", callback_data="stype_parking")],
        [InlineKeyboardButton("🚘 Гараж",      callback_data="stype_garage")],
        [InlineKeyboardButton("📋 Всичко",     callback_data="stype_all")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await update.message.reply_text(
        "🔍 *Търсене*\n\nКакво търсите?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return SEARCH_TYPE

async def search_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тип выбран → способ указания локации."""
    q = update.callback_query
    await q.answer()
    
    stype = q.data.split("_")[1]
    context.user_data["search"]["type"] = stype
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Споделете локация", callback_data="sloc_geo")],
        [InlineKeyboardButton("✍️ Въведете адрес", callback_data="sloc_text")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await q.edit_message_text(
        f"*{TYPE_LABEL[stype]}* — как да посочите локацията?\n\n"
        f"Можете да споделите текущата си локация или да въведете адрес.",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return SEARCH_LOCATION_CHOICE

async def search_location_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор способа указания локации для поиска."""
    q = update.callback_query
    await q.answer()
    
    choice = q.data.split("_")[1]
    
    if choice == "text":
        await q.edit_message_text("✍️ Въведете адрес:")
        await q.message.reply_text(
            "Напишете адреса:",
            reply_markup=back_button_keyboard()
        )
        return SEARCH_ADDRESS_TEXT
    
    elif choice == "geo":
        await q.edit_message_text("📍 Споделете локация:")
        await q.message.reply_text(
            "Споделете локация:",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("📍 Локация", request_location=True)],
                [KeyboardButton("🏠 Начало")]
            ], resize_keyboard=True)
        )
        return SEARCH_GEO

async def search_address_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Адрес для поиска введён текстом."""
    address = update.message.text.strip()
    
    await update.message.reply_text(
        "⏳ Проверявам адреса...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    result = await geocode(address)
    if not result:
        await update.message.reply_text(
            "❌ Не мога да намеря този адрес. Опитайте пак:",
            reply_markup=back_button_keyboard()
        )
        return SEARCH_ADDRESS_TEXT
    
    lat, lon, display = result
    context.user_data["search"]["lat"] = lat
    context.user_data["search"]["lon"] = lon
    context.user_data["search"]["address"] = address
    
    return await ask_radius(update.message, context)

async def search_geo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Геолокация для поиска."""
    loc = update.message.location
    lat, lon = loc.latitude, loc.longitude
    
    context.user_data["search"]["lat"] = lat
    context.user_data["search"]["lon"] = lon
    
    address = await reverse_geocode(lat, lon)
    context.user_data["search"]["address"] = address or f"GPS: {lat:.5f}, {lon:.5f}"
    
    return await ask_radius(update.message, context)

async def ask_radius(message, context):
    """Запрос радиуса поиска."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("500 м",  callback_data="radius_500")],
        [InlineKeyboardButton("1 км",   callback_data="radius_1000")],
        [InlineKeyboardButton("2 км",   callback_data="radius_2000")],
        [InlineKeyboardButton("5 км",   callback_data="radius_5000")],
        [InlineKeyboardButton("10 км",  callback_data="radius_10000")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    await message.reply_text(
        "📏 *Радиус на търсене*\n\nИзберете радиус около посочената локация:",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return SEARCH_RADIUS

async def search_radius_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Радиус выбран → выполняем поиск."""
    q = update.callback_query
    await q.answer()
    
    radius = int(q.data.split("_")[1])
    context.user_data["search"]["radius"] = radius
    
    await q.edit_message_text("⏳ Търся обяви...")
    
    search = context.user_data["search"]
    stype = search["type"]
    lat, lon = search["lat"], search["lon"]
    
    with get_db() as conn:
        if stype == "all":
            rows = conn.execute(
                "SELECT id, action, type, address, lat, lon, price, description, photo_id FROM listings WHERE active=1"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, action, type, address, lat, lon, price, description, photo_id FROM listings WHERE active=1 AND type=?",
                (stype,)
            ).fetchall()
    
    # Фильтруем по радиусу
    results = []
    for row in rows:
        lid, action, otype, addr, olat, olon, price, desc, photo_id = row
        dist = haversine(lat, lon, olat, olon)
        if dist <= radius:
            results.append((lid, action, otype, addr, olat, olon, price, desc, photo_id, dist))
    
    results.sort(key=lambda x: x[9])  # Сортировка по расстоянию
    
    if not results:
        await q.message.reply_text(
            "❌ Няма намерени обяви в избрания радиус.\n\n"
            "Опитайте да увеличите радиуса или да промените локацията.",
            reply_markup=main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
    
    context.user_data["search_results"] = results
    context.user_data["search_page"] = 0
    
    # Показываем первое объявление
    await show_search_result(q.message, context, 0)
    
    return SEARCH_RADIUS

async def show_search_result(message, context, idx):
    """Показ результата поиска с навигацией."""
    results = context.user_data["search_results"]
    if idx < 0 or idx >= len(results):
        return
    
    lid, action, otype, addr, olat, olon, price, desc, photo_id, dist = results[idx]
    
    # Увеличиваем счётчик просмотров
    with get_db() as conn:
        conn.execute("UPDATE listings SET views = views + 1 WHERE id=?", (lid,))
    
    # Проверяем, в избранном ли
    user = message.chat.id
    with get_db() as conn:
        fav = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND listing_id=?",
            (user, lid)
        ).fetchone()
    
    is_fav = bool(fav)
    
    text = (
        f"📋 *Обява #{lid}*\n\n"
        f"{ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
        f"📍 *Адрес:* {addr}\n"
        f"💵 *Цена:* {price:.2f} лв\n"
        f"📏 {fmt_dist(dist)}\n\n"
        f"📝 {desc}"
    )
    
    kb = [
        [
            InlineKeyboardButton("⭐ Любими" if not is_fav else "💛 В любими", 
                                 callback_data=f"fav_{lid}" if not is_fav else f"unfav_{lid}"),
            InlineKeyboardButton("🗺 Карта", callback_data=f"map_{lid}")
        ],
    ]
    
    # Навигация
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("◀️ Предишна", callback_data=f"nav_prev"))
    nav.append(InlineKeyboardButton(f"{idx+1}/{len(results)}", callback_data="nav_noop"))
    if idx < len(results) - 1:
        nav.append(InlineKeyboardButton("Следваща ▶️", callback_data=f"nav_next"))
    kb.append(nav)
    
    kb.append([InlineKeyboardButton("🔔 Абонирайте се за нови обяви", callback_data="subscribe")])
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    # ИСПРАВЛЕНИЕ #1: Проверяем наличие photo_id и его содержимое
    photos = []
    if photo_id and photo_id.strip():
        photos = photo_id.split(",")
    
    try:
        if photos and photos[0]:  # ИСПРАВЛЕНИЕ: дополнительная проверка
            await message.reply_photo(
                photo=photos[0],
                caption=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
    except Exception as e:
        logger.error(f"Error showing listing {lid}: {e}")
        # Если не получилось показать фото, показываем текст
        await message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    
    context.user_data["search_page"] = idx

async def change_radius(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменение радиуса поиска."""
    q = update.callback_query
    await q.answer()
    
    await q.edit_message_caption(caption="📏 Изберете нов радиус:")
    
    return await ask_radius(q.message, context)


# ════════════════════════════════════════════════════════════════
#                    НАВИГАЦИЯ ПО РЕЗУЛЬТАТАМ
# ════════════════════════════════════════════════════════════════

async def navigate_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по результатам поиска."""
    q = update.callback_query
    await q.answer()
    
    direction = q.data.split("_")[1]
    
    current = context.user_data.get("search_page", 0)
    results = context.user_data.get("search_results", [])
    
    if direction == "prev":
        new_idx = max(0, current - 1)
    elif direction == "next":
        new_idx = min(len(results) - 1, current + 1)
    else:
        return SEARCH_RADIUS
    
    await q.delete_message()
    await show_search_result(q.message, context, new_idx)
    
    return SEARCH_RADIUS


# ════════════════════════════════════════════════════════════════
#                       МОИ ОБЪЯВЛЕНИЯ
# ════════════════════════════════════════════════════════════════

async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка моих объявлений."""
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, action, type, address, price, active FROM listings WHERE owner_id=? ORDER BY created_at DESC",
            (user.id,)
        ).fetchall()
    
    if not rows:
        await update.message.reply_text(
            "📁 Нямате активни обяви.\n\n"
            "Създайте нова обява чрез менюто.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    text = "📁 *Моите обяви:*\n\n"
    kb = []
    
    for lid, action, otype, addr, price, active in rows:
        status = "✅" if active else "❌"
        short_addr = addr[:30] + "..." if len(addr) > 30 else addr
        kb.append([InlineKeyboardButton(
            f"{status} #{lid} | {ACTION_LABEL[action]} {TYPE_LABEL[otype]} | {short_addr}",
            callback_data=f"viewmy_{lid}"
        )])
    
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return MAIN_MENU

async def view_my_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр своего объявления."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    user = update.effective_user
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT action, type, address, phone, price, description, photo_id, active, views FROM listings WHERE id=? AND owner_id=?",
            (lid, user.id)
        ).fetchone()
    
    if not row:
        await q.edit_message_text("❌ Обявата не е намерена.")
        return MAIN_MENU
    
    action, otype, addr, phone, price, desc, photo_id, active, views = row
    
    status = "✅ Активна" if active else "❌ Деактивирана"
    
    text = (
        f"📋 *Обява #{lid}*\n\n"
        f"*Статус:* {status}\n"
        f"👁 *Прегледи:* {views}\n\n"
        f"{ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
        f"📍 *Адрес:* {addr}\n"
        f"📞 *Телефон:* {phone}\n"
        f"💵 *Цена:* {price:.2f} лв\n\n"
        f"📝 {desc}"
    )
    
    kb = [
        [InlineKeyboardButton("✏️ Редактирай", callback_data=f"edit_{lid}")],
        [InlineKeyboardButton("🗑 Изтрий", callback_data=f"delete_{lid}")],
    ]
    
    if active:
        kb.insert(1, [InlineKeyboardButton("🔕 Деактивирай", callback_data=f"deactivate_{lid}")])
    else:
        kb.insert(1, [InlineKeyboardButton("🔔 Активирай", callback_data=f"activate_{lid}")])
    
    kb.append([InlineKeyboardButton("« Назад", callback_data="back_to_mylist")])
    
    # ИСПРАВЛЕНИЕ #2: Аналогичная проверка для моих объявлений
    photos = []
    if photo_id and photo_id.strip():
        photos = photo_id.split(",")
    
    try:
        if photos and photos[0]:
            await q.message.reply_photo(
                photo=photos[0],
                caption=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await q.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.delete_message()
    except Exception as e:
        logger.error(f"Error showing my listing {lid}: {e}")
        # Fallback к тексту
        await q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    
    return MAIN_MENU

async def back_to_mylist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к списку моих объявлений."""
    q = update.callback_query
    await q.answer()
    
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, action, type, address, price, active FROM listings WHERE owner_id=? ORDER BY created_at DESC",
            (user.id,)
        ).fetchall()
    
    text = "📁 *Моите обяви:*\n\n"
    kb = []
    
    for lid, action, otype, addr, price, active in rows:
        status = "✅" if active else "❌"
        short_addr = addr[:30] + "..." if len(addr) > 30 else addr
        kb.append([InlineKeyboardButton(
            f"{status} #{lid} | {ACTION_LABEL[action]} {TYPE_LABEL[otype]} | {short_addr}",
            callback_data=f"viewmy_{lid}"
        )])
    
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                   РЕДАКТИРОВАНИЕ ОБЪЯВЛЕНИЯ
# ════════════════════════════════════════════════════════════════

async def edit_listing_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования объявления."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    context.user_data["editing_listing_id"] = lid
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Адрес",       callback_data=f"editfield_address_{lid}")],
        [InlineKeyboardButton("📞 Телефон",     callback_data=f"editfield_phone_{lid}")],
        [InlineKeyboardButton("💵 Цена",        callback_data=f"editfield_price_{lid}")],
        [InlineKeyboardButton("📝 Описание",    callback_data=f"editfield_description_{lid}")],
        [InlineKeyboardButton("📷 Снимки",      callback_data=f"editfield_photos_{lid}")],
        [InlineKeyboardButton("« Назад",        callback_data=f"viewmy_{lid}")],
    ])
    
    await q.edit_message_caption(
        caption=f"✏️ *Редактиране на обява #{lid}*\n\nИзберете какво да редактирате:",
        parse_mode="Markdown",
        reply_markup=kb
    )
    
    return EDIT_FIELD

async def editfield_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора поля для редактирования."""
    q = update.callback_query
    await q.answer()
    
    parts = q.data.split("_")
    field = parts[1]
    lid = int(parts[2])
    
    context.user_data["editing_listing_id"] = lid
    context.user_data["editing_field"] = field
    
    prompts = {
        "address":     "📍 Въведете нов адрес:",
        "phone":       "📞 Въведете нов телефон:",
        "price":       "💵 Въведете нова цена:",
        "description": "📝 Въведете ново описание:",
        "photos":      "📷 Изпратете нови снимки (до 5) или натиснете 'Готово':",
    }
    
    await q.edit_message_caption(caption=prompts[field])
    await q.message.reply_text(
        f"Въведете нова стойност за *{field}*:",
        parse_mode="Markdown",
        reply_markup=back_button_keyboard()
    )
    
    if field == "photos":
        context.user_data["new_photos"] = []
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data=f"editphotos_done_{lid}")],
        ])
        await q.message.reply_text(
            "Изпратете снимки:",
            reply_markup=kb
        )
    
    return EDIT_FIELD

async def editfield_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение отредактированного поля."""
    lid = context.user_data.get("editing_listing_id")
    field = context.user_data.get("editing_field")
    
    if not lid or not field:
        await update.message.reply_text("❌ Грешка.")
        return MAIN_MENU
    
    if update.message.photo:
        # Обработка фото
        photos = context.user_data.get("new_photos", [])
        if len(photos) >= 5:
            await update.message.reply_text("❌ Максимум 5 снимки.")
            return EDIT_FIELD
        photos.append(update.message.photo[-1].file_id)
        context.user_data["new_photos"] = photos
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Готово", callback_data=f"editphotos_done_{lid}")],
        ])
        await update.message.reply_text(
            f"✅ Снимка {len(photos)}/5 добавена.",
            reply_markup=kb
        )
        return EDIT_FIELD
    
    new_value = update.message.text.strip()
    
    # Валидация
    if field == "phone" and not PHONE_RE.match(new_value):
        await update.message.reply_text(
            "❌ Невалиден телефон. Опитайте пак:",
            reply_markup=back_button_keyboard()
        )
        return EDIT_FIELD
    
    if field == "price":
        try:
            new_value = float(new_value.replace(",", "."))
            if new_value <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Невалидна цена. Опитайте пак:",
                reply_markup=back_button_keyboard()
            )
            return EDIT_FIELD
    
    if field == "description" and len(new_value) > 500:
        await update.message.reply_text(
            f"❌ Описанието е твърде дълго ({len(new_value)} символа). Максимум 500.",
            reply_markup=back_button_keyboard()
        )
        return EDIT_FIELD
    
    # Сохранение в БД
    with get_db() as conn:
        if field == "address":
            result = await geocode(new_value)
            if not result:
                await update.message.reply_text(
                    "❌ Не мога да намеря този адрес. Опитайте пак:",
                    reply_markup=back_button_keyboard()
                )
                return EDIT_FIELD
            lat, lon, _ = result
            conn.execute(
                "UPDATE listings SET address=?, lat=?, lon=? WHERE id=?",
                (new_value, lat, lon, lid)
            )
        else:
            conn.execute(
                f"UPDATE listings SET {field}=? WHERE id=?",
                (new_value, lid)
            )
    
    await update.message.reply_text(
        f"✅ *{field.capitalize()}* е обновен!",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # ИСПРАВЛЕНИЕ #3: После редактирования возвращаемся к превью объявления
    # Загружаем обновленные данные
    with get_db() as conn:
        row = conn.execute(
            "SELECT action, type, address, phone, price, description, photo_id, active FROM listings WHERE id=?",
            (lid,)
        ).fetchone()
    
    if row:
        action, otype, addr, phone, price, desc, photo_id, active = row
        
        text = (
            f"📋 *Обява #{lid}* (Редактирана)\n\n"
            f"{ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
            f"📍 *Адрес:* {addr}\n"
            f"📞 *Телефон:* {phone}\n"
            f"💵 *Цена:* {price:.2f} лв\n\n"
            f"📝 {desc}"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Още редакции", callback_data=f"edit_{lid}")],
            [InlineKeyboardButton("✅ Готово", callback_data=f"viewmy_{lid}")],
        ])
        
        photos = []
        if photo_id and photo_id.strip():
            photos = photo_id.split(",")
        
        if photos and photos[0]:
            await update.message.reply_photo(
                photo=photos[0],
                caption=text,
                parse_mode="Markdown",
                reply_markup=kb
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=kb
            )
    
    # Очищаем контекст редактирования
    context.user_data.pop("editing_field", None)
    
    return MAIN_MENU

async def editphotos_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение редактирования фото."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[2])
    photos = context.user_data.get("new_photos", [])
    
    photo_str = ",".join(photos) if photos else ""
    
    with get_db() as conn:
        conn.execute("UPDATE listings SET photo_id=? WHERE id=?", (photo_str, lid))
    
    await q.edit_message_text(f"✅ Снимките са обновени!")
    
    context.user_data.pop("new_photos", None)
    context.user_data.pop("editing_field", None)
    
    # Показываем обновленное объявление
    user = update.effective_user
    with get_db() as conn:
        row = conn.execute(
            "SELECT action, type, address, phone, price, description, photo_id, active FROM listings WHERE id=? AND owner_id=?",
            (lid, user.id)
        ).fetchone()
    
    if row:
        action, otype, addr, phone, price, desc, photo_id, active = row
        
        text = (
            f"📋 *Обява #{lid}*\n\n"
            f"{ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
            f"📍 *Адрес:* {addr}\n"
            f"📞 *Телефон:* {phone}\n"
            f"💵 *Цена:* {price:.2f} лв\n\n"
            f"📝 {desc}"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Още редакции", callback_data=f"edit_{lid}")],
            [InlineKeyboardButton("✅ Готово", callback_data=f"viewmy_{lid}")],
        ])
        
        photos_list = []
        if photo_id and photo_id.strip():
            photos_list = photo_id.split(",")
        
        if photos_list and photos_list[0]:
            await q.message.reply_photo(
                photo=photos_list[0],
                caption=text,
                parse_mode="Markdown",
                reply_markup=kb
            )
        else:
            await q.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=kb
            )
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#              АКТИВАЦИЯ / ДЕАКТИВАЦИЯ / УДАЛЕНИЕ
# ════════════════════════════════════════════════════════════════

async def deactivate_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Деактивация объявления."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    
    with get_db() as conn:
        conn.execute("UPDATE listings SET active=0 WHERE id=?", (lid,))
    
    await q.edit_message_caption(
        caption=f"🔕 Обява #{lid} е деактивирана.",
        parse_mode="Markdown"
    )
    
    # Возврат к просмотру
    await view_my_listing_after_action(q.message, context, lid)
    
    return MAIN_MENU

async def activate_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активация объявления."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    
    with get_db() as conn:
        conn.execute("UPDATE listings SET active=1 WHERE id=?", (lid,))
    
    await q.edit_message_caption(
        caption=f"🔔 Обява #{lid} е активирана.",
        parse_mode="Markdown"
    )
    
    # Возврат к просмотру
    await view_my_listing_after_action(q.message, context, lid)
    
    return MAIN_MENU

async def delete_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление объявления."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    
    with get_db() as conn:
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
    
    await q.edit_message_caption(
        caption=f"🗑 Обява #{lid} е изтрита.",
        parse_mode="Markdown"
    )
    
    await q.message.reply_text(
        "Обявата е премахната.",
        reply_markup=main_menu_keyboard()
    )
    
    return MAIN_MENU

async def view_my_listing_after_action(message, context, lid):
    """Повторный показ объявления после действия."""
    user = message.chat.id
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT action, type, address, phone, price, description, photo_id, active, views FROM listings WHERE id=?",
            (lid,)
        ).fetchone()
    
    if not row:
        return
    
    action, otype, addr, phone, price, desc, photo_id, active, views = row
    
    status = "✅ Активна" if active else "❌ Деактивирана"
    
    text = (
        f"📋 *Обява #{lid}*\n\n"
        f"*Статус:* {status}\n"
        f"👁 *Прегледи:* {views}\n\n"
        f"{ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
        f"📍 *Адрес:* {addr}\n"
        f"📞 *Телефон:* {phone}\n"
        f"💵 *Цена:* {price:.2f} лв\n\n"
        f"📝 {desc}"
    )
    
    kb = [
        [InlineKeyboardButton("✏️ Редактирай", callback_data=f"edit_{lid}")],
        [InlineKeyboardButton("🗑 Изтрий", callback_data=f"delete_{lid}")],
    ]
    
    if active:
        kb.insert(1, [InlineKeyboardButton("🔕 Деактивирай", callback_data=f"deactivate_{lid}")])
    else:
        kb.insert(1, [InlineKeyboardButton("🔔 Активирай", callback_data=f"activate_{lid}")])
    
    kb.append([InlineKeyboardButton("« Назад", callback_data="back_to_mylist")])
    
    photos = []
    if photo_id and photo_id.strip():
        photos = photo_id.split(",")
    
    if photos and photos[0]:
        await message.reply_photo(
            photo=photos[0],
            caption=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )


# ════════════════════════════════════════════════════════════════
#                          ИЗБРАННОЕ
# ════════════════════════════════════════════════════════════════

async def toggle_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление/удаление из избранного."""
    q = update.callback_query
    await q.answer()
    
    action, lid = q.data.split("_")
    lid = int(lid)
    user = update.effective_user
    
    with get_db() as conn:
        if action == "fav":
            try:
                conn.execute(
                    "INSERT INTO favorites (user_id, listing_id) VALUES (?, ?)",
                    (user.id, lid)
                )
                await q.answer("⭐ Добавено в любими!")
            except sqlite3.IntegrityError:
                await q.answer("❌ Вече е в любими!")
        elif action == "unfav":
            conn.execute(
                "DELETE FROM favorites WHERE user_id=? AND listing_id=?",
                (user.id, lid)
            )
            await q.answer("💔 Премахнато от любими!")
    
    # Обновляем кнопки
    idx = context.user_data.get("search_page", 0)
    await q.delete_message()
    await show_search_result(q.message, context, idx)
    
    return SEARCH_RADIUS

async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ избранных объявлений."""
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute("""
            SELECT l.id, l.action, l.type, l.address, l.price, l.active
            FROM favorites f
            JOIN listings l ON f.listing_id = l.id
            WHERE f.user_id=?
            ORDER BY f.created_at DESC
        """, (user.id,)).fetchall()
    
    if not rows:
        await update.message.reply_text(
            "⭐ Нямате любими обяви.\n\n"
            "Добавете обяви в любими, за да ги виждате тук.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    text = "⭐ *Любими обяви:*\n\n"
    kb = []
    
    for lid, action, otype, addr, price, active in rows:
        status = "✅" if active else "❌"
        short_addr = addr[:30] + "..." if len(addr) > 30 else addr
        kb.append([InlineKeyboardButton(
            f"{status} #{lid} | {ACTION_LABEL[action]} {TYPE_LABEL[otype]} | {short_addr}",
            callback_data=f"viewfav_{lid}"
        )])
    
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return MAIN_MENU

async def view_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр избранного объявления."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT action, type, address, phone, price, description, photo_id, active FROM listings WHERE id=?",
            (lid,)
        ).fetchone()
    
    if not row:
        await q.edit_message_text("❌ Обявата не е намерена.")
        return MAIN_MENU
    
    action, otype, addr, phone, price, desc, photo_id, active = row
    
    status = "✅ Активна" if active else "❌ Деактивирана"
    
    text = (
        f"📋 *Обява #{lid}*\n\n"
        f"*Статус:* {status}\n\n"
        f"{ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
        f"📍 *Адрес:* {addr}\n"
        f"📞 *Телефон:* {phone}\n"
        f"💵 *Цена:* {price:.2f} лв\n\n"
        f"📝 {desc}"
    )
    
    kb = [
        [InlineKeyboardButton("💔 Премахни от любими", callback_data=f"unfav_from_list_{lid}")],
        [InlineKeyboardButton("« Назад", callback_data="back_to_favorites")],
    ]
    
    photos = []
    if photo_id and photo_id.strip():
        photos = photo_id.split(",")
    
    try:
        if photos and photos[0]:
            await q.message.reply_photo(
                photo=photos[0],
                caption=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await q.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        await q.delete_message()
    except Exception:
        await q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    
    return MAIN_MENU

async def unfav_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление из избранного из просмотра."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[3])
    user = update.effective_user
    
    with get_db() as conn:
        conn.execute(
            "DELETE FROM favorites WHERE user_id=? AND listing_id=?",
            (user.id, lid)
        )
    
    await q.edit_message_caption(caption="💔 Премахнато от любими!")
    
    # Возврат к списку
    await back_to_favorites(update, context)
    
    return MAIN_MENU

async def back_to_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к списку избранного."""
    q = update.callback_query
    if q:
        await q.answer()
    
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute("""
            SELECT l.id, l.action, l.type, l.address, l.price, l.active
            FROM favorites f
            JOIN listings l ON f.listing_id = l.id
            WHERE f.user_id=?
            ORDER BY f.created_at DESC
        """, (user.id,)).fetchall()
    
    text = "⭐ *Любими обяви:*\n\n"
    kb = []
    
    for lid, action, otype, addr, price, active in rows:
        status = "✅" if active else "❌"
        short_addr = addr[:30] + "..." if len(addr) > 30 else addr
        kb.append([InlineKeyboardButton(
            f"{status} #{lid} | {ACTION_LABEL[action]} {TYPE_LABEL[otype]} | {short_addr}",
            callback_data=f"viewfav_{lid}"
        )])
    
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    if q:
        await q.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                       ПОДПИСКИ НА УВЕДОМЛЕНИЯ
# ════════════════════════════════════════════════════════════════

async def subscribe_to_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка на уведомления о новых объявлениях."""
    q = update.callback_query
    await q.answer()
    
    user = update.effective_user
    search = context.user_data.get("search", {})
    
    lat = search.get("lat")
    lon = search.get("lon")
    radius = search.get("radius", 5000)
    stype = search.get("type", "all")
    
    if not lat or not lon:
        await q.answer("❌ Няма зададена локация за търсене.")
        return SEARCH_RADIUS
    
    expires = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    
    with get_db() as conn:
        conn.execute("""
            INSERT INTO search_subscriptions (user_id, search_type, action, lat, lon, radius, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user.id, stype, "all", lat, lon, radius, expires))
    
    await q.answer("🔔 Абонирани сте! Ще получавате уведомления за нови обяви.")
    
    return SEARCH_RADIUS

async def show_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ активных подписок."""
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, search_type, lat, lon, radius, expires_at, active
            FROM search_subscriptions
            WHERE user_id=?
            ORDER BY created_at DESC
        """, (user.id,)).fetchall()
    
    if not rows:
        await update.message.reply_text(
            "🔔 Нямате активни абонаменти.\n\n"
            "Създайте абонамент при търсене на обяви.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    text = "🔔 *Вашите абонаменти:*\n\n"
    kb = []
    
    for sid, stype, lat, lon, radius, expires, active in rows:
        status = "✅" if active else "❌"
        kb.append([InlineKeyboardButton(
            f"{status} {TYPE_LABEL.get(stype, stype)} | {radius}м | До {expires[:10]}",
            callback_data=f"viewsub_{sid}"
        )])
    
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return MAIN_MENU

async def view_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр подписки."""
    q = update.callback_query
    await q.answer()
    
    sid = int(q.data.split("_")[1])
    user = update.effective_user
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT search_type, lat, lon, radius, expires_at, active FROM search_subscriptions WHERE id=? AND user_id=?",
            (sid, user.id)
        ).fetchone()
    
    if not row:
        await q.edit_message_text("❌ Абонаментът не е намерен.")
        return MAIN_MENU
    
    stype, lat, lon, radius, expires, active = row
    
    status = "✅ Активен" if active else "❌ Деактивиран"
    
    text = (
        f"🔔 *Абонамент #{sid}*\n\n"
        f"*Статус:* {status}\n"
        f"*Тип:* {TYPE_LABEL.get(stype, stype)}\n"
        f"*Радиус:* {radius} м\n"
        f"*Изтича на:* {expires[:10]}\n"
    )
    
    kb = [
        [InlineKeyboardButton("🗑 Изтрий", callback_data=f"delsub_{sid}")],
        [InlineKeyboardButton("« Назад", callback_data="back_to_subs")],
    ]
    
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return MAIN_MENU

async def delete_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление подписки."""
    q = update.callback_query
    await q.answer()
    
    sid = int(q.data.split("_")[1])
    user = update.effective_user
    
    with get_db() as conn:
        conn.execute("DELETE FROM search_subscriptions WHERE id=? AND user_id=?", (sid, user.id))
    
    await q.edit_message_text("🗑 Абонаментът е изтрит.")
    
    await back_to_subs(update, context)
    
    return MAIN_MENU

async def back_to_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к списку подписок."""
    q = update.callback_query
    await q.answer()
    
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, search_type, lat, lon, radius, expires_at, active
            FROM search_subscriptions
            WHERE user_id=?
            ORDER BY created_at DESC
        """, (user.id,)).fetchall()
    
    text = "🔔 *Вашите абонаменти:*\n\n"
    kb = []
    
    for sid, stype, lat, lon, radius, expires, active in rows:
        status = "✅" if active else "❌"
        kb.append([InlineKeyboardButton(
            f"{status} {TYPE_LABEL.get(stype, stype)} | {radius}м | До {expires[:10]}",
            callback_data=f"viewsub_{sid}"
        )])
    
    kb.append([InlineKeyboardButton("🏠 Главно меню", callback_data="go_home")])
    
    await q.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                    УВЕДОМЛЕНИЯ ПОДПИСЧИКОВ
# ════════════════════════════════════════════════════════════════

async def notify_subscribers(context, listing_id):
    """Уведомление подписчиков о новом объявлении."""
    with get_db() as conn:
        listing = conn.execute(
            "SELECT action, type, lat, lon, price FROM listings WHERE id=?",
            (listing_id,)
        ).fetchone()
        
        if not listing:
            return
        
        action, otype, lat, lon, price = listing
        
        # Находим подписчиков
        subs = conn.execute("""
            SELECT user_id, lat, lon, radius
            FROM search_subscriptions
            WHERE active=1 AND (search_type=? OR search_type='all')
        """, (otype,)).fetchall()
    
    for user_id, sub_lat, sub_lon, radius in subs:
        dist = haversine(sub_lat, sub_lon, lat, lon)
        if dist <= radius:
            try:
                await context.bot.send_message(
                    user_id,
                    f"🔔 *Ново обявление в района ви!*\n\n"
                    f"#{listing_id} | {ACTION_LABEL[action]} {TYPE_LABEL[otype]}\n"
                    f"💵 {price:.2f} лв\n"
                    f"📏 {fmt_dist(dist)}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Notify subscriber {user_id} error: {e}")


# ════════════════════════════════════════════════════════════════
#                          СООБЩЕНИЯ
# ════════════════════════════════════════════════════════════════

async def show_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ входящих сообщений."""
    user = update.effective_user
    
    with get_db() as conn:
        rows = conn.execute("""
            SELECT m.id, m.listing_id, m.from_name, m.text, m.created_at
            FROM messages m
            JOIN listings l ON m.listing_id = l.id
            WHERE l.owner_id=?
            ORDER BY m.created_at DESC
            LIMIT 20
        """, (user.id,)).fetchall()
    
    if not rows:
        await update.message.reply_text(
            "💬 Няма съобщения.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    text = "💬 *Съобщения:*\n\n"
    for mid, lid, from_name, msg_text, created in rows:
        text += f"От {from_name} за #{lid}:\n{msg_text[:50]}...\n{created[:16]}\n\n"
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                       КАРТА
# ════════════════════════════════════════════════════════════════

async def show_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ на карте."""
    q = update.callback_query
    await q.answer()
    
    lid = int(q.data.split("_")[1])
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT lat, lon, address FROM listings WHERE id=?",
            (lid,)
        ).fetchone()
    
    if not row:
        await q.answer("❌ Обявата не е намерена.")
        return SEARCH_RADIUS
    
    lat, lon, addr = row
    
    await q.message.reply_location(
        latitude=lat,
        longitude=lon
    )
    await q.answer(f"📍 {addr}")
    
    return SEARCH_RADIUS


# ════════════════════════════════════════════════════════════════
#                          ПОМОЩ
# ════════════════════════════════════════════════════════════════

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка."""
    text = (
        "ℹ️ *ParkPlace Varna — Помощ*\n\n"
        "🅿️ *Пазар за паркоместа и гаражи във Варна*\n\n"
        "**Основни функции:**\n"
        "• ➕ Създавайте обяви за продажба, покупка или наем\n"
        "• 🔍 Търсете по локация и радиус\n"
        "• ⭐ Добавяйте в любими\n"
        "• 🔔 Абонирайте се за нови обяви\n"
        "• 💬 Общувайте с продавачи\n\n"
        "**Команди:**\n"
        "/start — Главно меню\n"
        "/my — Моите обяви\n"
        "/favorites — Любими\n"
        "/subscriptions — Абонаменти\n"
        "/help — Помощ\n\n"
        "За въпроси: @support"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                          АДМИН
# ════════════════════════════════════════════════════════════════

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нямате достъп.")
        return MAIN_MENU
    
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
        total_listings = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
    
    text = (
        f"👨‍💼 *Админ панел*\n\n"
        f"👥 Потребители: {total_users}\n"
        f"📋 Активни обяви: {total_listings}\n"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Изпрати съобщение до всички", callback_data="adm_broadcast")],
        [InlineKeyboardButton("« Назад", callback_data="go_home")],
    ])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=kb
    )
    
    return ADMIN_MENU

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка админ кнопок."""
    q = update.callback_query
    await q.answer()
    
    action = q.data.split("_")[1]
    
    if action == "broadcast":
        await q.edit_message_text("📢 Въведете текст на съобщението:")
        await q.message.reply_text(
            "Въведете текста:",
            reply_markup=back_button_keyboard()
        )
        return ADMIN_BROADCAST
    
    return ADMIN_MENU

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассылка от админа."""
    text = update.message.text.strip()
    
    with get_db() as conn:
        user_ids = conn.execute("SELECT DISTINCT owner_id FROM listings").fetchall()
    
    sent = 0
    for (uid,) in user_ids:
        try:
            await context.bot.send_message(uid, f"📢 *Съобщение от администрацията:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast to {uid} error: {e}")
    
    await update.message.reply_text(
        f"✅ Изпратено до {sent} потребители.",
        reply_markup=main_menu_keyboard()
    )
    
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                  УТИЛИТЫ ДЛЯ МИГРАЦИИ
# ════════════════════════════════════════════════════════════════

async def fix_addresses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для исправления адресов (миграция)."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нямате достъп.")
        return MAIN_MENU
    
    await update.message.reply_text("🔄 Обновявам адресите...")
    
    with get_db() as conn:
        rows = conn.execute("SELECT id, lat, lon FROM listings WHERE address IS NULL OR address=''").fetchall()
        for lid, lat, lon in rows:
            addr = await reverse_geocode(lat, lon)
            if addr:
                conn.execute("UPDATE listings SET address=? WHERE id=?", (addr, lid))
    
    await update.message.reply_text(f"✅ Обновени {len(rows)} адреса.")
    return MAIN_MENU


# ════════════════════════════════════════════════════════════════
#                          ГЛАВНАЯ ФУНКЦИЯ
# ════════════════════════════════════════════════════════════════

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handler
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("my", my_listings),
            CommandHandler("favorites", show_favorites),
            CommandHandler("subscriptions", show_subscriptions),
            CommandHandler("help", show_help),
        ],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
                CallbackQueryHandler(view_my_listing,    pattern="^viewmy_"),
                CallbackQueryHandler(view_favorite,      pattern="^viewfav_"),
                CallbackQueryHandler(view_subscription,  pattern="^viewsub_"),
                CallbackQueryHandler(back_to_mylist,     pattern="^back_to_mylist$"),
                CallbackQueryHandler(back_to_favorites,  pattern="^back_to_favorites$"),
                CallbackQueryHandler(back_to_subs,       pattern="^back_to_subs$"),
                CallbackQueryHandler(edit_listing_start, pattern="^edit_"),
                CallbackQueryHandler(deactivate_listing, pattern="^deactivate_"),
                CallbackQueryHandler(activate_listing,   pattern="^activate_"),
                CallbackQueryHandler(delete_listing,     pattern="^delete_"),
                CallbackQueryHandler(unfav_from_list,    pattern="^unfav_from_list_"),
                CallbackQueryHandler(delete_subscription, pattern="^delsub_"),
                CallbackQueryHandler(navigate_results,   pattern="^nav_"),
                CallbackQueryHandler(editphotos_done,    pattern="^editphotos_done_"),
                CallbackQueryHandler(go_home,            pattern="^go_home$"),
            ],
            # Создание объявления
            AD_TYPE: [
                CallbackQueryHandler(ad_type_chosen,         pattern="^adact_"),
                CallbackQueryHandler(ad_object_type_chosen,  pattern="^adtype_"),
                CallbackQueryHandler(go_home,                pattern="^go_home$"),
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
                CallbackQueryHandler(navigate_results,            pattern="^nav_"),
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
                CallbackQueryHandler(editphotos_done,   pattern="^editphotos_done_"),
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
