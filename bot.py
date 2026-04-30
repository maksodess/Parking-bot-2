import os
"""
ParkRent Bot — покупка, продажа, аренда парковок и гаражей в Варне
"""

import logging
import sqlite3
import math
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

# ── Настройки ────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = 5053888378
DB_FILE = "parking.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Районы Варны ──────────────────────────────────────────────
DISTRICTS = [
    # Официальные районы
    "Приморски",
    "Одесос / Центр",
    "Младост",
    "Владиславово",
    "Аспарухово",
    # Кварталы Приморски
    "Бриз",
    "Чайка",
    "Левски",
    "Изгрев",
    "Виница",
    "Евксиноград",
    "Траката",
    "Золотые Пески",
    "Св. Константин и Елена",
    # Прочее
    "Другой район",
]

# ── Состояния диалога ─────────────────────────────────────────
(
    MAIN_MENU,
    AD_ACTION, AD_TYPE, AD_DISTRICT, AD_ADDRESS, AD_LOCATION,
    AD_PRICE, AD_DESCRIPTION, AD_PHOTO, AD_CONFIRM,
    SEARCH_ACTION, SEARCH_TYPE, SEARCH_DISTRICT, SEARCH_LOCATION,
    CONTACT_MSG,
    ADMIN_MENU, ADMIN_BROADCAST,
) = range(17)

# ── База данных ───────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id    INTEGER NOT NULL,
            owner_name  TEXT,
            action      TEXT NOT NULL,
            type        TEXT NOT NULL,
            district    TEXT NOT NULL,
            address     TEXT,
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

# ── Haversine ─────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((math.radians(lat2-lat1))/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin((math.radians(lon2-lon1))/2)**2
    return 2*R*math.asin(math.sqrt(a))

def fmt_dist(m):
    if m < 1000: return f"{round(m/10)*10:.0f} м от вас"
    elif m < 10000: return f"{m/1000:.1f} км от вас"
    else: return f"{m/1000:.0f} км от вас"

# ── Лейблы ────────────────────────────────────────────────────
ACTION_LABEL = {
    "buy": "🛒 Купить",
    "sell": "💰 Продать",
    "rent": "🔑 Арендовать",
    "lease": "📋 Сдать в аренду",
}
TYPE_LABEL = {
    "parking": "🅿️ Паркоместо",
    "garage": "🏠 Гараж",
}

def listing_text(row, distance_m=None):
    lid, owner_id, owner_name, action, ltype, district, address, lat, lon, price, desc, photo, active, created = row
    lines = [
        f"{ACTION_LABEL.get(action, action)} · {TYPE_LABEL.get(ltype, ltype)}",
    ]
    if distance_m is not None:
        lines.append(f"📏 *{fmt_dist(distance_m)}*")
    lines.append(f"📍 Варна, {district}")
    if address:
        lines.append(f"🏢 {address}")
    lines.append(f"💰 {price:,.0f} €")
    if desc:
        lines.append(f"📝 {desc}")
    lines.append(f"🆔 #{lid}")
    return "\n".join(lines)

# ── Клавиатуры ────────────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📁 Мои объявления", "ℹ️ Помощь"],
    ], resize_keyboard=True)

def action_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Купить", callback_data=f"{prefix}_buy"),
         InlineKeyboardButton("💰 Продать", callback_data=f"{prefix}_sell")],
        [InlineKeyboardButton("🔑 Арендовать", callback_data=f"{prefix}_rent"),
         InlineKeyboardButton("📋 Сдать в аренду", callback_data=f"{prefix}_lease")],
    ])

def type_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🅿️ Паркоместо", callback_data=f"{prefix}_parking")],
        [InlineKeyboardButton("🏠 Гараж", callback_data=f"{prefix}_garage")],
    ])

def district_keyboard(prefix):
    buttons = []
    row = []
    for i, d in enumerate(DISTRICTS):
        row.append(InlineKeyboardButton(d, callback_data=f"{prefix}_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def geo_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📍 Отправить геолокацию объекта", request_location=True)],
        [KeyboardButton("⏩ Пропустить")],
    ], resize_keyboard=True, one_time_keyboard=True)

def search_geo_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📍 Отправить мою геолокацию", request_location=True)],
        [KeyboardButton("🗂 Искать по всем районам")],
    ], resize_keyboard=True, one_time_keyboard=True)

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все объявления", callback_data="adm_listings")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="adm_users")],
        [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast")],
    ])

# ── /start ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 *ParkRent Varna* — паркоместа и гаражи в Варне\n\n"
        "Что вы хотите сделать?",
        parse_mode="Markdown",
        reply_markup=action_keyboard("start")
    )
    return MAIN_MENU

# ── Главное меню (стартовые кнопки) ──────────────────────────
async def start_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("start_", "")
    ctx.user_data["action"] = action

    if action in ("buy", "rent"):
        # Поиск
        ctx.user_data["search_action"] = action
        await query.edit_message_text(
            f"*{ACTION_LABEL[action]}* — выберите тип объекта:",
            parse_mode="Markdown"
        )
        await query.message.reply_text("Выберите:", reply_markup=type_keyboard("stype"))
        return SEARCH_TYPE
    else:
        # Подача объявления
        ctx.user_data["ad"] = {"action": action}
        await query.edit_message_text(
            f"*{ACTION_LABEL[action]}* — выберите тип объекта:",
            parse_mode="Markdown"
        )
        await query.message.reply_text("Выберите:", reply_markup=type_keyboard("adtype"))
        return AD_TYPE

# ── Текстовое меню ────────────────────────────────────────────
async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📁 Мои объявления":
        return await show_my_listings(update, ctx)

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "*Как пользоваться ботом:*\n\n"
            "На главном экране выберите действие:\n"
            "🛒 *Купить* — найти паркоместо или гараж для покупки\n"
            "💰 *Продать* — разместить объявление о продаже\n"
            "🔑 *Арендовать* — найти место для аренды\n"
            "📋 *Сдать в аренду* — разместить объявление об аренде\n\n"
            "🗺 *Как указать геолокацию:*\n"
            "Не нужно быть рядом с объектом!\n"
            "1️⃣ Нажмите скрепку 📎 → *Геолокация*\n"
            "2️⃣ Введите адрес в поиске\n"
            "3️⃣ Подвиньте метку и нажмите *Отправить*\n\n"
            "💡 Все объявления только по городу *Варна*, Болгария.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    # Если пользователь пишет что-то — показываем стартовое меню
    await update.message.reply_text(
        "Что вы хотите сделать?",
        reply_markup=action_keyboard("start")
    )
    return MAIN_MENU

# ═══════════════════════════════════════════════════════════════
# ПОДАЧА ОБЪЯВЛЕНИЯ
# ═══════════════════════════════════════════════════════════════
async def ad_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["ad"]["type"] = query.data.replace("adtype_", "")
    await query.edit_message_text(
        "📍 Выберите *район Варны*:",
        parse_mode="Markdown",
        reply_markup=district_keyboard("addistrict")
    )
    return AD_DISTRICT

async def ad_district_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.replace("addistrict_", ""))
    ctx.user_data["ad"]["district"] = DISTRICTS[idx]
    await query.edit_message_text(
        "🏢 Введите *адрес* (улица, дом, ориентир)\n"
        "Или «-» чтобы пропустить:",
        parse_mode="Markdown"
    )
    return AD_ADDRESS

async def ad_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["ad"]["address"] = None if text == "-" else text
    await update.message.reply_text(
        "🗺 Укажите *точное местоположение* объекта на карте.\n\n"
        "Не нужно быть рядом — выберите любое место:\n"
        "1️⃣ Нажмите скрепку 📎 → *Геолокация*\n"
        "2️⃣ Введите адрес в поиске\n"
        "3️⃣ Подвиньте метку и нажмите *Отправить*\n\n"
        "Или нажмите «Пропустить».",
        parse_mode="Markdown",
        reply_markup=geo_keyboard()
    )
    return AD_LOCATION

async def ad_location_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    ctx.user_data["ad"]["lat"] = loc.latitude
    ctx.user_data["ad"]["lon"] = loc.longitude
    await update.message.reply_text(
        "✅ Геолокация сохранена!\n\n💰 Введите *цену* (число, €):",
        parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
    return AD_PRICE

async def ad_location_skipped(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ad"]["lat"] = None
    ctx.user_data["ad"]["lon"] = None
    await update.message.reply_text(
        "⏩ Геолокация пропущена.\n\n💰 Введите *цену* (число, €):",
        parse_mode="Markdown", reply_markup=main_menu_keyboard()
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
    action = ad.get("action", "")
    ltype = ad.get("type", "")
    geo_line = "🗺 Геолокация указана ✅" if ad.get("lat") else "🗺 Без геолокации"

    preview = (
        f"*Проверьте объявление:*\n\n"
        f"{ACTION_LABEL.get(action, '')} · {TYPE_LABEL.get(ltype, '')}\n"
        f"📍 Варна, {ad.get('district', '')}\n"
    )
    if ad.get("address"):
        preview += f"🏢 {ad['address']}\n"
    preview += f"{geo_line}\n💰 {ad.get('price', 0):,.0f} €\n"
    if ad.get("description"):
        preview += f"📝 {ad['description']}\n"
    if ad.get("photo_id"):
        preview += "🖼 Фото прикреплено\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Опубликовать", callback_data="ad_publish")],
        [InlineKeyboardButton("❌ Отмена", callback_data="ad_cancel")],
    ])
    await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)
    return AD_CONFIRM

async def ad_publish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ad_cancel":
        await query.edit_message_text("❌ Объявление отменено.")
        return MAIN_MENU

    ad = ctx.user_data.get("ad", {})
    user = query.from_user
    conn = db()
    conn.execute(
        "INSERT INTO listings (owner_id, owner_name, action, type, district, address, lat, lon, price, description, photo_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user.id, user.full_name, ad.get("action"), ad.get("type"),
         ad.get("district"), ad.get("address"), ad.get("lat"), ad.get("lon"),
         ad.get("price"), ad.get("description"), ad.get("photo_id"))
    )
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ Объявление опубликовано!")
    return MAIN_MENU

# ═══════════════════════════════════════════════════════════════
# ПОИСК
# ═══════════════════════════════════════════════════════════════
async def search_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["search_type"] = query.data.replace("stype_", "")
    await query.edit_message_text(
        "📍 Выберите *район Варны* для поиска\nили найдите по всем сразу:",
        parse_mode="Markdown",
        reply_markup=district_keyboard("sdistrict")
    )
    # Добавляем кнопку "Все районы"
    return SEARCH_DISTRICT

async def search_district_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.replace("sdistrict_", ""))
    ctx.user_data["search_district"] = DISTRICTS[idx]
    await query.edit_message_text(
        f"🔍 Ищем в районе *{DISTRICTS[idx]}*\n\n"
        "📍 Отправьте геолокацию — бот покажет расстояние до каждого объекта.\n"
        "Или нажмите «Искать по всем районам».",
        parse_mode="Markdown"
    )
    await query.message.reply_text("Выберите:", reply_markup=search_geo_keyboard())
    return SEARCH_LOCATION

async def search_with_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    user_lat, user_lon = loc.latitude, loc.longitude
    return await do_search(update, ctx, user_lat=user_lat, user_lon=user_lon)

async def search_all_districts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["search_district"] = None
    return await do_search(update, ctx)

async def do_search(update, ctx, user_lat=None, user_lon=None):
    ltype = ctx.user_data.get("search_type", "all")
    district = ctx.user_data.get("search_district")
    search_action = ctx.user_data.get("search_action", "rent")
    # buy→sell, rent→lease (ищем тех кто продаёт/сдаёт)
    db_action = "sell" if search_action == "buy" else "lease"

    conn = db()
    query_parts = ["active=1", f"action='{db_action}'"]
    params = []
    if ltype != "all":
        query_parts.append("type=?")
        params.append(ltype)
    if district:
        query_parts.append("district=?")
        params.append(district)

    sql = f"SELECT * FROM listings WHERE {' AND '.join(query_parts)} ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        label = f"в районе *{district}*" if district else "в Варне"
        await update.message.reply_text(
            f"😕 Объявлений {label} пока нет.",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    with_geo, without_geo = [], []
    for row in rows:
        lat, lon = row[7], row[8]
        if user_lat and lat is not None:
            dist = haversine(user_lat, user_lon, lat, lon)
            with_geo.append((dist, row))
        else:
            without_geo.append(row)

    if user_lat:
        with_geo.sort(key=lambda x: x[0])

    total = len(with_geo) + len(without_geo)
    district_label = f"в районе {district}" if district else "по всей Варне"
    sort_label = " — отсортированы по расстоянию 📏" if user_lat else ""
    await update.message.reply_text(
        f"🔍 Найдено {total} объявл. {district_label}{sort_label}",
        reply_markup=main_menu_keyboard()
    )

    for dist, row in with_geo:
        lid, owner_id = row[0], row[1]
        caption = listing_text(row, distance_m=dist)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗺 Открыть на карте", callback_data=f"map_{lid}")],
            [InlineKeyboardButton("✉️ Написать владельцу", callback_data=f"contact_{lid}_{owner_id}")],
        ])
        if row[11]:
            await update.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)

    for row in without_geo:
        lid, owner_id = row[0], row[1]
        caption = listing_text(row)
        buttons = [[InlineKeyboardButton("✉️ Написать владельцу", callback_data=f"contact_{lid}_{owner_id}")]]
        if row[7] is not None:
            buttons.insert(0, [InlineKeyboardButton("🗺 Открыть на карте", callback_data=f"map_{lid}")])
        keyboard = InlineKeyboardMarkup(buttons)
        if row[11]:
            await update.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)

    return MAIN_MENU

# ── Карта ─────────────────────────────────────────────────────
async def show_map(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lid = int(query.data.split("_")[1])
    conn = db()
    row = conn.execute("SELECT lat, lon, district, address FROM listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if row and row[0]:
        await query.message.reply_location(latitude=row[0], longitude=row[1])
        addr = f"📍 Варна, {row[2]}" + (f", {row[3]}" if row[3] else "")
        await query.message.reply_text(addr)
    else:
        await query.answer("Геолокация не указана", show_alert=True)
    return MAIN_MENU

# ── Связь ─────────────────────────────────────────────────────
async def contact_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    lid, owner_id = int(parts[1]), int(parts[2])
    ctx.user_data["contact_listing"] = lid
    ctx.user_data["contact_owner"] = owner_id
    if query.from_user.id == owner_id:
        await query.answer("Это ваше объявление!", show_alert=True)
        return MAIN_MENU
    await query.message.reply_text("✉️ Напишите сообщение владельцу:", reply_markup=main_menu_keyboard())
    return CONTACT_MSG

async def contact_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lid = ctx.user_data.get("contact_listing")
    owner_id = ctx.user_data.get("contact_owner")
    user = update.effective_user
    text = update.message.text
    conn = db()
    conn.execute("INSERT INTO messages (listing_id, from_id, from_name, text) VALUES (?,?,?,?)",
        (lid, user.id, user.full_name, text))
    conn.commit()
    conn.close()
    try:
        uinfo = f"@{user.username}" if user.username else f"ID: {user.id}"
        await ctx.bot.send_message(owner_id,
            f"📩 *Сообщение* по объявлению #{lid}\nОт: {user.full_name} ({uinfo})\n\n{text}",
            parse_mode="Markdown")
        await update.message.reply_text("✅ Сообщение отправлено!", reply_markup=main_menu_keyboard())
    except Exception:
        await update.message.reply_text("✅ Сообщение сохранено.", reply_markup=main_menu_keyboard())
    return MAIN_MENU

# ── Мои объявления ────────────────────────────────────────────
async def show_my_listings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = db()
    rows = conn.execute("SELECT * FROM listings WHERE owner_id=? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("У вас нет объявлений.", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    await update.message.reply_text(f"📁 Ваши объявления ({len(rows)}):")
    for row in rows:
        lid, active = row[0], row[12]
        status = "✅" if active else "⏸"
        geo = "🗺" if row[7] else "📌"
        caption = listing_text(row) + f"\n{status} {'Активно' if active else 'Снято'} · {geo}"
        buttons = []
        if active:
            buttons.append(InlineKeyboardButton("⏸ Снять", callback_data=f"deactivate_{lid}"))
        else:
            buttons.append(InlineKeyboardButton("▶️ Активировать", callback_data=f"activate_{lid}"))
        buttons.append(InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{lid}"))
        keyboard = InlineKeyboardMarkup([buttons])
        if row[11]:
            await update.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)
    return MAIN_MENU

async def manage_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action, lid = parts[0], int(parts[1])
    user_id = query.from_user.id
    conn = db()
    row = conn.execute("SELECT owner_id FROM listings WHERE id=?", (lid,)).fetchone()
    if not row or row[0] != user_id:
        await query.answer("Нет доступа", show_alert=True)
        conn.close()
        return MAIN_MENU
    if action == "deactivate":
        conn.execute("UPDATE listings SET active=0 WHERE id=?", (lid,))
        conn.commit()
        await query.answer("⏸ Снято")
    elif action == "activate":
        conn.execute("UPDATE listings SET active=1 WHERE id=?", (lid,))
        conn.commit()
        await query.answer("✅ Активировано")
    elif action == "delete":
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit()
        await query.answer("🗑 Удалено")
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
    conn = db()
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
    users = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
    msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"🔧 *Админ-панель ParkRent Varna*\n\n"
        f"📋 Объявлений: {total} (активных: {active})\n"
        f"👥 Пользователей: {users}\n"
        f"✉️ Сообщений: {msgs}",
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

    if data == "adm_listings":
        conn = db()
        rows = conn.execute("SELECT * FROM listings ORDER BY id DESC LIMIT 20").fetchall()
        conn.close()
        if not rows:
            await query.message.reply_text("Объявлений пока нет.")
            return ADMIN_MENU
        await query.message.reply_text(f"📋 Последние {len(rows)} объявлений:")
        for row in rows:
            lid, active = row[0], row[12]
            owner_name = row[2] or "—"
            status = "✅" if active else "⏸"
            caption = f"{status} {listing_text(row)}\n👤 {owner_name}"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("⏸ Снять" if active else "▶️ Активировать", callback_data=f"adm_toggle_{lid}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"adm_delete_{lid}"),
            ]])
            if row[11]:
                await query.message.reply_photo(row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await query.message.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)
        return ADMIN_MENU

    elif data == "adm_users":
        conn = db()
        rows = conn.execute(
            "SELECT owner_id, owner_name, COUNT(*) FROM listings GROUP BY owner_id ORDER BY 3 DESC"
        ).fetchall()
        conn.close()
        if not rows:
            await query.message.reply_text("Пользователей пока нет.")
            return ADMIN_MENU
        text = "👥 *Пользователи:*\n\n"
        for uid, name, cnt in rows:
            text += f"• {name or '—'} (ID: `{uid}`) — {cnt} объявл.\n"
        await query.message.reply_text(text, parse_mode="Markdown")
        return ADMIN_MENU

    elif data == "adm_stats":
        conn = db()
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
        sell = conn.execute("SELECT COUNT(*) FROM listings WHERE action='sell'").fetchone()[0]
        lease = conn.execute("SELECT COUNT(*) FROM listings WHERE action='lease'").fetchone()[0]
        parking = conn.execute("SELECT COUNT(*) FROM listings WHERE type='parking'").fetchone()[0]
        garage = conn.execute("SELECT COUNT(*) FROM listings WHERE type='garage'").fetchone()[0]
        with_geo = conn.execute("SELECT COUNT(*) FROM listings WHERE lat IS NOT NULL").fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT owner_id) FROM listings").fetchone()[0]
        msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        # По районам
        conn = db()
        districts_stat = conn.execute(
            "SELECT district, COUNT(*) FROM listings GROUP BY district ORDER BY 2 DESC LIMIT 5"
        ).fetchall()
        conn.close()
        dist_text = "\n".join([f"  • {d}: {c}" for d, c in districts_stat])
        await query.message.reply_text(
            f"📊 *Статистика ParkRent Varna:*\n\n"
            f"📋 Всего объявлений: {total}\n"
            f"  ✅ Активных: {active} / ⏸ Снятых: {total-active}\n"
            f"  💰 На продажу: {sell} / 📋 В аренду: {lease}\n"
            f"  🅿️ Парковок: {parking} / 🏠 Гаражей: {garage}\n"
            f"  🗺 С геолокацией: {with_geo}\n\n"
            f"📍 Топ районов:\n{dist_text}\n\n"
            f"👥 Пользователей: {users}\n"
            f"✉️ Сообщений: {msgs}",
            parse_mode="Markdown", reply_markup=admin_keyboard()
        )
        return ADMIN_MENU

    elif data == "adm_broadcast":
        await query.message.reply_text(
            "📢 Введите текст рассылки всем пользователям:\n(или «отмена»)"
        )
        return ADMIN_BROADCAST

    elif data.startswith("adm_toggle_"):
        lid = int(data.split("_")[2])
        conn = db()
        cur = conn.execute("SELECT active FROM listings WHERE id=?", (lid,)).fetchone()
        if cur:
            new = 0 if cur[0] else 1
            conn.execute("UPDATE listings SET active=? WHERE id=?", (new, lid))
            conn.commit()
            await query.answer("✅ Активировано" if new else "⏸ Снято")
            await query.edit_message_reply_markup(None)
        conn.close()
        return ADMIN_MENU

    elif data.startswith("adm_delete_"):
        lid = int(data.split("_")[2])
        conn = db()
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
        conn.commit()
        conn.close()
        await query.answer(f"🗑 #{lid} удалено")
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(f"🗑 Объявление #{lid} удалено.")
        return ADMIN_MENU

    return ADMIN_MENU

async def admin_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return MAIN_MENU
    text = update.message.text.strip()
    if text.lower() == "отмена":
        await update.message.reply_text("❌ Рассылка отменена.", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    conn = db()
    uids = set(
        [r[0] for r in conn.execute("SELECT DISTINCT owner_id FROM listings").fetchall()] +
        [r[0] for r in conn.execute("SELECT DISTINCT from_id FROM messages").fetchall()]
    )
    conn.close()
    sent = failed = 0
    for uid in uids:
        try:
            await ctx.bot.send_message(uid, f"📢 *Сообщение от администратора:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"✅ Рассылка завершена!\nОтправлено: {sent} / Не доставлено: {failed}",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

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
                CallbackQueryHandler(start_action, pattern="^start_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu),
                CallbackQueryHandler(manage_listing, pattern="^(deactivate|activate|delete)_"),
                CallbackQueryHandler(contact_start, pattern="^contact_"),
                CallbackQueryHandler(show_map, pattern="^map_"),
            ],
            # Подача объявления
            AD_TYPE: [CallbackQueryHandler(ad_type_chosen, pattern="^adtype_")],
            AD_DISTRICT: [CallbackQueryHandler(ad_district_chosen, pattern="^addistrict_")],
            AD_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_address)],
            AD_LOCATION: [
                MessageHandler(filters.LOCATION, ad_location_received),
                MessageHandler(filters.Regex("^⏩"), ad_location_skipped),
            ],
            AD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_price)],
            AD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ad_description)],
            AD_PHOTO: [
                MessageHandler(filters.PHOTO, ad_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ad_photo),
            ],
            AD_CONFIRM: [CallbackQueryHandler(ad_publish, pattern="^ad_(publish|cancel)$")],
            # Поиск
            SEARCH_TYPE: [CallbackQueryHandler(search_type_chosen, pattern="^stype_")],
            SEARCH_DISTRICT: [CallbackQueryHandler(search_district_chosen, pattern="^sdistrict_")],
            SEARCH_LOCATION: [
                MessageHandler(filters.LOCATION, search_with_location),
                MessageHandler(filters.Regex("^🗂"), search_all_districts),
            ],
            # Связь
            CONTACT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_send)],
            # Админ
            ADMIN_MENU: [CallbackQueryHandler(admin_callback, pattern="^adm_")],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    print("🤖 ParkRent Varna Bot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
