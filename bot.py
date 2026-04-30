import os
"""
ParkRent Bot — покупка, продажа, аренда парковок и гаражей в Варне
"""

import logging
import sqlite3
import math
import urllib.request
import urllib.parse
import json
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID  = 5053888378
DB_FILE   = "parking.db"
PAGE_SIZE = 10

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Состояния ─────────────────────────────────────────────────
(
    MAIN_MENU,
    AD_TYPE, AD_LOCATION_CHOICE, AD_ADDRESS_TEXT, AD_ADDRESS_CONFIRM, AD_LOCATION_GEO,
    AD_PHONE, AD_PRICE, AD_DESCRIPTION, AD_PHOTO, AD_CONFIRM,
    SEARCH_TYPE, SEARCH_LOCATION_CHOICE, SEARCH_ADDRESS_TEXT, SEARCH_GEO, SEARCH_RADIUS,
    CONTACT_MSG,
    ADMIN_MENU, ADMIN_BROADCAST,
) = range(19)

# ── БД ────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id    INTEGER NOT NULL,
            owner_name  TEXT,
            action      TEXT NOT NULL,
            type        TEXT NOT NULL,
            address     TEXT NOT NULL,
            phone       TEXT,
            lat         REAL,
            lon         REAL,
            price       REAL NOT NULL,
            description TEXT,
            photo_id    TEXT,
            active      INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id  INTEGER NOT NULL,
            from_id     INTEGER NOT NULL,
            from_name   TEXT,
            text        TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

def db():
    return sqlite3.connect(DB_FILE)

# ── Геокодинг ─────────────────────────────────────────────────
def geocode(address: str):
    query = f"{address}, Варна, България"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1, "countrycodes": "bg",
    })
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ParkRentVarnaBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"]
    except Exception as e:
        logger.error(f"Geocode error: {e}")
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
    "buy":   "🛒 Купить",
    "sell":  "💰 Продать",
    "rent":  "🔑 Арендовать",
    "lease": "📋 Сдать в аренду",
}
TYPE_LABEL = {
    "parking": "🅿️ Паркоместо",
    "garage":  "🏠 Гараж",
    "all":     "📋 Всё",
}

def listing_text(row, distance_m=None):
    lid, owner_id, owner_name, action, ltype, address, phone, lat, lon, price, desc, photo, active, created = row
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

# ── Клавиатуры ────────────────────────────────────────────────
def main_keyboard():
    return ReplyKeyboardMarkup([["📁 Мои объявления", "ℹ️ Помощь"]], resize_keyboard=True)

def home_ikb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 На главную", callback_data="go_home")]])

def action_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Купить",         callback_data="start_buy"),
         InlineKeyboardButton("💰 Продать",        callback_data="start_sell")],
        [InlineKeyboardButton("🔑 Арендовать",     callback_data="start_rent"),
         InlineKeyboardButton("📋 Сдать в аренду", callback_data="start_lease")],
    ])

def type_keyboard(prefix, include_all=False):
    rows = [
        [InlineKeyboardButton("🅿️ Паркоместо", callback_data=f"{prefix}_parking")],
        [InlineKeyboardButton("🏠 Гараж",       callback_data=f"{prefix}_garage")],
    ]
    if include_all:
        rows.append([InlineKeyboardButton("📋 Всё сразу", callback_data=f"{prefix}_all")])
    rows.append([InlineKeyboardButton("🏠 На главную", callback_data="go_home")])
    return InlineKeyboardMarkup(rows)

def location_choice_keyboard(prefix):
    """Выбор способа указания местоположения."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Ввести адрес",       callback_data=f"{prefix}_text")],
        [InlineKeyboardButton("📍 Отправить геолокацию", callback_data=f"{prefix}_geo")],
        [InlineKeyboardButton("🏠 На главную",           callback_data="go_home")],
    ])

def geo_ad_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📍 Отправить геолокацию объекта", request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def geo_search_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📍 Отправить мою геолокацию", request_location=True)],
    ], resize_keyboard=True, one_time_keyboard=True)

def radius_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("500 м", callback_data="radius_500"),
         InlineKeyboardButton("1 км",  callback_data="radius_1000")],
        [InlineKeyboardButton("2 км",  callback_data="radius_2000"),
         InlineKeyboardButton("5 км",  callback_data="radius_5000")],
        [InlineKeyboardButton("📋 Вся Варна", callback_data="radius_all")],
        [InlineKeyboardButton("🏠 На главную", callback_data="go_home")],
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Объявления",   callback_data="adm_listings_0"),
         InlineKeyboardButton("👥 Пользователи", callback_data="adm_users")],
        [InlineKeyboardButton("📊 Статистика",   callback_data="adm_stats"),
         InlineKeyboardButton("📢 Рассылка",     callback_data="adm_broadcast")],
        [InlineKeyboardButton("🏠 На главную",   callback_data="go_home")],
    ])

# ── /start ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    send = update.message.reply_text if update.message else update.callback_query.message.reply_text
    await send(
        "🚗 *ParkRent Varna*\nПаркоместа и гаражи — купить, продать, арендовать\n\nЧто вы хотите сделать?",
        parse_mode="Markdown", reply_markup=action_keyboard()
    )
    return MAIN_MENU

async def go_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        "🚗 *ParkRent Varna*\nЧто вы хотите сделать?",
        parse_mode="Markdown", reply_markup=action_keyboard()
    )
    return MAIN_MENU

# ── Текстовое меню ────────────────────────────────────────────
async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📁 Мои объявления":
        return await show_my_listings(update, ctx)
    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "*Как пользоваться:*\n\n"
            "🛒 *Купить / Арендовать* — найти объект\n"
            "💰 *Продать / Сдать* — разместить объявление\n\n"
            "📍 *Местоположение объекта:*\n"
            "Можно ввести адрес текстом — бот найдёт его на карте.\n"
            "Или отправить геолокацию через 📎 → Геолокация.\n\n"
            "🔍 *Поиск по радиусу* — укажите своё местоположение\n"
            "и выберите радиус: 500м / 1км / 2км / 5км / вся Варна.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return MAIN_MENU
    await update.message.reply_text("Что вы хотите сделать?", reply_markup=action_keyboard())
    return MAIN_MENU

# ── Выбор действия ────────────────────────────────────────────
async def start_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("start_", "")
    ctx.user_data["action"] = action

    if action in ("buy", "rent"):
        ctx.user_data["search_action"] = action
        await query.edit_message_text(
            f"*{ACTION_LABEL[action]}* — выберите тип:",
            parse_mode="Markdown",
            reply_markup=type_keyboard("stype", include_all=True)
        )
        return SEARCH_TYPE
    else:
        ctx.user_data["ad"] = {"action": action}
        await query.edit_message_text(
            f"*{ACTION_LABEL[action]}* — выберите тип:",
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
        "📍 Как указать местоположение объекта?",
        reply_markup=location_choice_keyboard("adloc")
    )
    return AD_LOCATION_CHOICE

# Выбор способа — текст или геолокация
async def ad_location_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "adloc_text":
        await query.edit_message_text(
            "✏️ Введите *адрес объекта*:\n\n"
            "Например: _ул. Цар Симеон I 15_ или _бул. Приморски 42_\n\n"
            "Бот найдёт это место на карте.",
            parse_mode="Markdown"
        )
        return AD_ADDRESS_TEXT

    elif query.data == "adloc_geo":
        await query.edit_message_text(
            "📍 Отправьте геолокацию объекта через кнопку ниже.\n\n"
            "Не нужно находиться рядом:\n"
            "📎 → Геолокация → найдите адрес → двигайте метку → Отправить",
            parse_mode="Markdown"
        )
        await query.message.reply_text(
            "Нажмите кнопку:", reply_markup=geo_ad_keyboard()
        )
        return AD_LOCATION_GEO

# Адрес текстом → геокодинг
async def ad_address_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    await update.message.reply_text("🔍 Ищу на карте...")
    result = geocode(address)
    if not result:
        await update.message.reply_text(
            "❌ Адрес не найден. Попробуйте точнее:\n"
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
        f"📍 Нашёл: _{display[:120]}_\n\nЭто правильное место?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, верно",          callback_data="addrconfirm_ok")],
            [InlineKeyboardButton("❌ Нет, ввести снова",  callback_data="addrconfirm_retry")],
            [InlineKeyboardButton("📍 Уточнить геолокацией", callback_data="addrconfirm_geo")],
        ])
    )
    return AD_ADDRESS_CONFIRM

async def ad_address_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "addrconfirm_retry":
        await query.edit_message_text("✏️ Введите адрес снова:")
        return AD_ADDRESS_TEXT

    elif query.data == "addrconfirm_geo":
        await query.edit_message_text(
            "📍 Отправьте точную геолокацию через 📎 → Геолокация:"
        )
        await query.message.reply_text("Нажмите кнопку:", reply_markup=geo_ad_keyboard())
        return AD_LOCATION_GEO

    # ok — подтверждено, переходим к телефону
    await query.edit_message_text(
        "✅ Адрес подтверждён!\n\n"
        "📞 Введите *номер телефона* для связи\n"
        "Или «-» чтобы пропустить:",
        parse_mode="Markdown"
    )
    return AD_PHONE

# Геолокация через скрепку
async def ad_location_geo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    ctx.user_data["ad"]["lat"] = loc.latitude
    ctx.user_data["ad"]["lon"] = loc.longitude
    # Если адрес ещё не задан — ставим координаты как адрес
    if not ctx.user_data["ad"].get("address"):
        ctx.user_data["ad"]["address"] = f"{loc.latitude:.5f}, {loc.longitude:.5f}"
    await update.message.reply_text(
        "✅ Геолокация сохранена!\n\n"
        "📞 Введите *номер телефона* для связи\n"
        "Или «-» чтобы пропустить:",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )
    return AD_PHONE

async def ad_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["ad"]["phone"] = None if text == "-" else text
    await update.message.reply_text(
        "💰 Введите *цену* (число, €):", parse_mode="Markdown"
    )
    return AD_PRICE

async def ad_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip().replace(" ", "").replace(",", "."))
        ctx.user_data["ad"]["price"] = price
    except ValueError:
        await update.message.reply_text("❌ Введите число, например: 5000")
        return AD_PRICE
    await update.message.reply_text(
        "📝 Добавьте *описание* (площадь, особенности, доступ)\n"
        "Или «-» чтобы пропустить:", parse_mode="Markdown"
    )
    return AD_DESCRIPTION

async def ad_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["ad"]["description"] = None if text == "-" else text
    await update.message.reply_text(
        "📸 Отправьте *фото* (необязательно)\nИли «-» чтобы пропустить:",
        parse_mode="Markdown"
    )
    return AD_PHOTO

async def ad_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        ctx.user_data["ad"]["photo_id"] = update.message.photo[-1].file_id
    else:
        ctx.user_data["ad"]["photo_id"] = None

    ad = ctx.user_data["ad"]
    geo_line   = "🗺 Геолокация ✅" if ad.get("lat") else "🗺 Без геолокации"
    phone_line = f"📞 {ad['phone']}" if ad.get("phone") else "📞 Без телефона"

    preview = (
        f"*Проверьте объявление:*\n\n"
        f"{ACTION_LABEL.get(ad.get('action',''))} · {TYPE_LABEL.get(ad.get('type',''))}\n"
        f"📍 {ad.get('address', '—')}\n"
        f"{phone_line}\n"
        f"{geo_line}\n"
        f"💰 {ad.get('price', 0):,.0f} €\n"
    )
    if ad.get("description"):
        preview += f"📝 {ad['description']}\n"
    if ad.get("photo_id"):
        preview += "🖼 Фото прикреплено\n"

    await update.message.reply_text(
        preview, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Опубликовать", callback_data="ad_publish")],
            [InlineKeyboardButton("❌ Отмена",       callback_data="ad_cancel")],
            [InlineKeyboardButton("🏠 На главную",   callback_data="go_home")],
        ])
    )
    return AD_CONFIRM

async def ad_publish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ad_cancel":
        await query.edit_message_text("❌ Объявление отменено.", reply_markup=home_ikb())
        return MAIN_MENU
    ad   = ctx.user_data.get("ad", {})
    user = query.from_user
    conn = db()
    conn.execute(
        "INSERT INTO listings (owner_id,owner_name,action,type,address,phone,lat,lon,price,description,photo_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user.id, user.full_name, ad.get("action"), ad.get("type"),
         ad.get("address"), ad.get("phone"), ad.get("lat"), ad.get("lon"),
         ad.get("price"), ad.get("description"), ad.get("photo_id"))
    )
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ Объявление опубликовано!", reply_markup=home_ikb())
    return MAIN_MENU

# ═══════════════════════════════════════════════════════════════
# ПОИСК
# ═══════════════════════════════════════════════════════════════
async def search_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["search_type"] = query.data.replace("stype_", "")
    await query.edit_message_text(
        "📍 Как указать ваше местоположение для поиска?",
        reply_markup=location_choice_keyboard("sloc")
    )
    return SEARCH_LOCATION_CHOICE

async def search_location_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "sloc_text":
        await query.edit_message_text(
            "✏️ Введите *ваш адрес*:\n\n"
            "Например: _ул. Цар Симеон I 15_\n\n"
            "Бот найдёт его на карте и предложит радиус поиска.",
            parse_mode="Markdown"
        )
        return SEARCH_ADDRESS_TEXT

    elif query.data == "sloc_geo":
        await query.edit_message_text(
            "📍 Отправьте вашу геолокацию:"
        )
        await query.message.reply_text("Нажмите кнопку:", reply_markup=geo_search_keyboard())
        return SEARCH_GEO

async def search_address_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    await update.message.reply_text("🔍 Ищу на карте...")
    result = geocode(address)
    if not result:
        await update.message.reply_text(
            "❌ Адрес не найден. Попробуйте точнее:"
        )
        return SEARCH_ADDRESS_TEXT
    lat, lon, display = result
    ctx.user_data["search_lat"] = lat
    ctx.user_data["search_lon"] = lon
    await update.message.reply_location(latitude=lat, longitude=lon)
    await update.message.reply_text(
        f"📍 _{display[:100]}_\n\n📏 Выберите *радиус поиска*:",
        parse_mode="Markdown", reply_markup=radius_keyboard()
    )
    return SEARCH_RADIUS

async def search_geo_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    ctx.user_data["search_lat"] = loc.latitude
    ctx.user_data["search_lon"] = loc.longitude
    await update.message.reply_text(
        "📏 Выберите *радиус поиска*:",
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
        await query.edit_message_text(
            f"😕 В радиусе {rl} объявлений не найдено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Изменить радиус", callback_data="change_radius")],
                [InlineKeyboardButton("🏠 На главную",      callback_data="go_home")],
            ])
        )
        return MAIN_MENU

    rl = (f"{radius//1000} км" if radius >= 1000 else f"{radius} м") if radius else "вся Варна"
    await query.edit_message_text(
        f"🔍 Найдено *{total}* объявл. · радиус: {rl}",
        parse_mode="Markdown"
    )

    for dist, row in results:
        lid, owner_id = row[0], row[1]
        caption  = listing_text(row, distance_m=dist)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗺 На карте",   callback_data=f"map_{lid}"),
             InlineKeyboardButton("✉️ Написать",  callback_data=f"contact_{lid}_{owner_id}")],
        ])
        if row[11]:
            await query.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await query.message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)

    for row in no_geo:
        lid, owner_id = row[0], row[1]
        caption  = listing_text(row)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✉️ Написать", callback_data=f"contact_{lid}_{owner_id}")]
        ])
        if row[11]:
            await query.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await query.message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)

    await query.message.reply_text("✅ Все результаты показаны.", reply_markup=home_ikb())
    return MAIN_MENU

async def change_radius(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📏 Выберите радиус:", reply_markup=radius_keyboard())
    return SEARCH_RADIUS

# ── Карта ─────────────────────────────────────────────────────
async def show_map(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lid = int(query.data.split("_")[1])
    conn = db()
    row  = conn.execute("SELECT lat, lon, address FROM listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if row and row[0]:
        await query.message.reply_location(latitude=row[0], longitude=row[1])
        await query.message.reply_text(f"📍 {row[2]}")
    else:
        await query.answer("Геолокация не указана", show_alert=True)
    return MAIN_MENU

# ── Связь ─────────────────────────────────────────────────────
async def contact_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts    = query.data.split("_")
    lid      = int(parts[1])
    owner_id = int(parts[2])
    ctx.user_data["contact_listing"] = lid
    ctx.user_data["contact_owner"]   = owner_id
    if query.from_user.id == owner_id:
        await query.answer("Это ваше объявление!", show_alert=True)
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
            f"📩 *Сообщение* по объявлению #{lid}\nОт: {user.full_name} ({uinfo})\n\n{text}",
            parse_mode="Markdown")
        await update.message.reply_text("✅ Отправлено!", reply_markup=home_ikb())
    except Exception:
        await update.message.reply_text("✅ Сохранено.", reply_markup=home_ikb())
    return MAIN_MENU

# ── Мои объявления ────────────────────────────────────────────
async def show_my_listings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn    = db()
    rows    = conn.execute("SELECT * FROM listings WHERE owner_id=? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("У вас нет объявлений.", reply_markup=home_ikb())
        return MAIN_MENU
    await update.message.reply_text(f"📁 Ваши объявления ({len(rows)}):", reply_markup=home_ikb())
    for row in rows:
        lid, active = row[0], row[12]
        status  = "✅ Активно" if active else "⏸ Снято"
        caption = listing_text(row) + f"\n{status}"
        btns    = []
        if active:
            btns.append(InlineKeyboardButton("⏸ Снять",        callback_data=f"deactivate_{lid}"))
        else:
            btns.append(InlineKeyboardButton("▶️ Активировать", callback_data=f"activate_{lid}"))
        btns.append(InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{lid}"))
        kb = InlineKeyboardMarkup([btns])
        if row[11]:
            await update.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=kb)
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
        await query.answer("Нет доступа", show_alert=True)
        conn.close()
        return MAIN_MENU
    if action == "deactivate":
        conn.execute("UPDATE listings SET active=0 WHERE id=?", (lid,))
        conn.commit(); await query.answer("⏸ Снято")
    elif action == "activate":
        conn.execute("UPDATE listings SET active=1 WHERE id=?", (lid,))
        conn.commit(); await query.answer("✅ Активировано")
    elif action == "delete":
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit(); await query.answer("🗑 Удалено")
        await query.message.reply_text(f"🗑 Объявление #{lid} удалено.")
    conn.close()
    await query.edit_message_reply_markup(None)
    return MAIN_MENU

# ═══════════════════════════════════════════════════════════════
# АДМИН
# ═══════════════════════════════════════════════════════════════
async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Нет доступа.")
        return MAIN_MENU
    conn    = db()
    total   = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    active  = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
    users   = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
    msgs    = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"🔧 *Админ-панель ParkRent Varna*\n\n"
        f"📋 Объявлений: *{total}* (активных: {active})\n"
        f"👥 Пользователей: *{users}* · ✉️ Сообщений: *{msgs}*",
        parse_mode="Markdown", reply_markup=admin_keyboard()
    )
    return ADMIN_MENU

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Нет доступа", show_alert=True)
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
            f"📋 Объявлений: {total} (активных: {active})\n"
            f"👥 Пользователей: {users} · ✉️ Сообщений: {msgs}",
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
            text += f"• {name or '—'} · `{uid}` · {cnt} объявл.\n"
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
            f"📋 Всего: {total} · Активных: {active}\n"
            f"💰 Продажа: {sell} · 📋 Аренда: {lease}\n"
            f"🅿️ Парковок: {parking} · 🏠 Гаражей: {garage}\n"
            f"🗺 С геолокацией: {geo}\n\n"
            f"👥 Пользователей: {users} · ✉️ Сообщений: {msgs}",
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
            await query.answer("✅ Активировано" if new else "⏸ Снято")
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
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(go_home,        pattern="^go_home$"),
                CallbackQueryHandler(start_action,   pattern="^start_"),
                CallbackQueryHandler(manage_listing, pattern="^(deactivate|activate|delete)_"),
                CallbackQueryHandler(contact_start,  pattern="^contact_"),
                CallbackQueryHandler(show_map,       pattern="^map_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu),
            ],
            # Подача объявления
            AD_TYPE:            [CallbackQueryHandler(ad_type_chosen,    pattern="^adtype_")],
            AD_LOCATION_CHOICE: [CallbackQueryHandler(ad_location_choice, pattern="^adloc_")],
            AD_ADDRESS_TEXT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_address_text)],
            AD_ADDRESS_CONFIRM: [CallbackQueryHandler(ad_address_confirm, pattern="^addrconfirm_")],
            AD_LOCATION_GEO:    [MessageHandler(filters.LOCATION, ad_location_geo)],
            AD_PHONE:           [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_phone)],
            AD_PRICE:           [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_price)],
            AD_DESCRIPTION:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_description)],
            AD_PHOTO: [
                MessageHandler(filters.PHOTO, ad_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_photo),
            ],
            AD_CONFIRM: [
                CallbackQueryHandler(ad_publish, pattern="^ad_(publish|cancel)$"),
                CallbackQueryHandler(go_home,    pattern="^go_home$"),
            ],
            # Поиск
            SEARCH_TYPE: [
                CallbackQueryHandler(search_type_chosen, pattern="^stype_"),
                CallbackQueryHandler(go_home,            pattern="^go_home$"),
            ],
            SEARCH_LOCATION_CHOICE: [CallbackQueryHandler(search_location_choice, pattern="^sloc_")],
            SEARCH_ADDRESS_TEXT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, search_address_text)],
            SEARCH_GEO:             [MessageHandler(filters.LOCATION, search_geo_input)],
            SEARCH_RADIUS: [
                CallbackQueryHandler(search_radius_chosen, pattern="^radius_"),
                CallbackQueryHandler(change_radius,        pattern="^change_radius$"),
                CallbackQueryHandler(go_home,              pattern="^go_home$"),
            ],
            # Связь
            CONTACT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_send)],
            # Админ
            ADMIN_MENU: [
                CallbackQueryHandler(go_home,        pattern="^go_home$"),
                CallbackQueryHandler(admin_callback, pattern="^adm_"),
            ],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    print("🤖 ParkRent Varna запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
