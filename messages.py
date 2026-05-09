# messages.py — Полная локализация ParkPlace Varna Bot (БГ/РУ)
import sqlite3, os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_FILE = os.path.join(DATA_DIR, "parking.db")

def _db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

BG = {
    "welcome_full": "🚗 *Добре дошли в ParkPlace Varna!*\n\nПазар за паркоместа и гаражи във Варна.\n\nИзберете действие от менюто:",
    "welcome_short": "🚗 *ParkPlace Varna*\n\nКакво искате да направите?",
    "welcome_line": "🚗 *ParkPlace Varna*\nКакво искате да направите?",
    "btn_buy": "🛒 Купува", "btn_sell": "💰 Продава", "btn_rent": "🔑 Наем", "btn_lease": "📋 Под наем",
    "btn_my_listings": "📁 Моите обяви", "btn_favorites": "⭐ Любими", "btn_subscriptions": "🔔 Абонаменти",
    "btn_home": "🏠 Начало", "btn_back": "◀️ Назад", "btn_back2": "🔙 Назад",
    "btn_to_menu": "↩️ В меню", "btn_to_menu_back": "↩️ Назад", "btn_language": "🇧🇬/🇷🇺 Език",
    "btn_type_parking": "🅿️ Паркомясто", "btn_type_garage": "🚘 Гараж", "btn_type_all": "📋 Всичко наведнъж",
    "btn_enter_address": "✏️ Въвеждане на адрес", "btn_send_location": "📍 Изпращане на геолокация",
    "btn_send_location_object": "📍 Изпращане на геолокация на обекта",
    "btn_send_my_location": "📍 Изпращане на моята геолокация",
    "btn_send_phone": "📱 Изпращане на моя номер", "btn_skip": "⏩ Пропускане",
    "btn_skip_no_photos": "⏩ Пропускане (без снимки)",
    "btn_yes_correct": "✅ Да, правилно", "btn_no_retry": "❌ Не, въведи отново",
    "btn_clarify_geo": "📍 Уточни с геолокация", "radius_all": "📋 Цяла Варна",
    "btn_publish": "✅ Публикуване", "btn_cancel": "❌ Отмена", "btn_cancel2": "❌ Отказ",
    "btn_edit_address": "✏️ Адрес", "btn_edit_phone": "✏️ Телефон", "btn_edit_phone2": "📞 Телефон",
    "btn_edit_price": "✏️ Цена", "btn_edit_price2": "💰 Цена",
    "btn_edit_desc": "✏️ Описание", "btn_edit_desc2": "📝 Описание",
    "btn_edit_photos": "✏️ Снимки", "btn_edit_photos2": "📸 Снимки", "btn_edit_address2": "📍 Адрес",
    "btn_edit": "✏️ Редактиране", "btn_delete": "🗑 Изтрий", "btn_delete_listing": "🗑 Изтрий обявата",
    "btn_next": "Напред ▶️", "btn_remove_fav": "💔 Премахни от любими", "btn_add_fav": "⭐ В любими",
    "btn_on_map": "🗺 На картата",
    "btn_subscribe": "🔔 Абонамент за известия (⭐100 ≈ 2€)", "btn_change_radius": "🔄 Промяна на радиус",
    "btn_pause": "⏸ Изключване", "btn_resume": "▶️ Включване", "btn_radius": "📏 Радиус",
    "btn_yes_actual": "✅ Да, актуална е", "btn_delete_it": "🗑 Изтрий я",
    "btn_adm_listings": "📋 Обяви", "btn_adm_users": "👥 Потребители",
    "btn_adm_stats": "📊 Статистика", "btn_adm_broadcast": "📢 Изпращане",
    "language_choose": "🌍 Изберете език:", "language_bg": "🇧🇬 Български",
    "language_ru": "🇷🇺 Русский", "language_changed": "✅ Езикът е променен!",
    "cmd_home": "🏠 Главно меню", "cmd_my": "📁 Моите обяви",
    "cmd_favorites": "⭐ Любими", "cmd_subscriptions": "🔔 Абонаменти", "cmd_help": "ℹ️ Помощ",
}

RU = {
    "welcome_full": "🚗 *Добро пожаловать в ParkPlace Varna!*\n\nМаркетплейс парковочных мест и гаражей в Варне.\n\nВыберите действие:",
    "welcome_short": "🚗 *ParkPlace Varna*\n\nЧто вы хотите сделать?",
    "welcome_line": "🚗 *ParkPlace Varna*\nЧто вы хотите сделать?",
    "btn_buy": "🛒 Купить", "btn_sell": "💰 Продать", "btn_rent": "🔑 Аренда", "btn_lease": "📋 Сдать",
    "btn_my_listings": "📁 Мои объявления", "btn_favorites": "⭐ Избранное", "btn_subscriptions": "🔔 Подписки",
    "btn_home": "🏠 Главная", "btn_back": "◀️ Назад", "btn_back2": "🔙 Назад",
    "btn_to_menu": "↩️ В меню", "btn_to_menu_back": "↩️ Назад", "btn_language": "🇧🇬/🇷🇺 Язык",
    "btn_type_parking": "🅿️ Парковочное место", "btn_type_garage": "🚘 Гараж", "btn_type_all": "📋 Всё сразу",
    "btn_enter_address": "✏️ Ввести адрес", "btn_send_location": "📍 Отправить геолокацию",
    "btn_send_location_object": "📍 Отправить геолокацию объекта",
    "btn_send_my_location": "📍 Отправить мою геолокацию",
    "btn_send_phone": "📱 Отправить мой номер", "btn_skip": "⏩ Пропустить",
    "btn_skip_no_photos": "⏩ Пропустить (без фото)",
    "btn_yes_correct": "✅ Да, правильно", "btn_no_retry": "❌ Нет, ввести заново",
    "btn_clarify_geo": "📍 Уточнить геолокацией", "radius_all": "📋 Вся Варна",
    "btn_publish": "✅ Опубликовать", "btn_cancel": "❌ Отмена", "btn_cancel2": "❌ Отказ",
    "btn_edit_address": "✏️ Адрес", "btn_edit_phone": "✏️ Телефон", "btn_edit_phone2": "📞 Телефон",
    "btn_edit_price": "✏️ Цена", "btn_edit_price2": "💰 Цена",
    "btn_edit_desc": "✏️ Описание", "btn_edit_desc2": "📝 Описание",
    "btn_edit_photos": "✏️ Фото", "btn_edit_photos2": "📸 Фото", "btn_edit_address2": "📍 Адрес",
    "btn_edit": "✏️ Редактировать", "btn_delete": "🗑 Удалить", "btn_delete_listing": "🗑 Удалить объявление",
    "btn_next": "Вперёд ▶️", "btn_remove_fav": "💔 Убрать из избранного", "btn_add_fav": "⭐ В избранное",
    "btn_on_map": "🗺 На карте",
    "btn_subscribe": "🔔 Подписка на уведомления (⭐100 ≈ 2€)", "btn_change_radius": "🔄 Изменить радиус",
    "btn_pause": "⏸ Приостановить", "btn_resume": "▶️ Возобновить", "btn_radius": "📏 Радиус",
    "btn_yes_actual": "✅ Да, актуально", "btn_delete_it": "🗑 Удалить",
    "btn_adm_listings": "📋 Объявления", "btn_adm_users": "👥 Пользователи",
    "btn_adm_stats": "📊 Статистика", "btn_adm_broadcast": "📢 Рассылка",
    "language_choose": "🌍 Выберите язык:", "language_bg": "🇧🇬 Болгарский",
    "language_ru": "🇷🇺 Русский", "language_changed": "✅ Язык изменён!",
    "cmd_home": "🏠 Главное меню", "cmd_my": "📁 Мои объявления",
    "cmd_favorites": "⭐ Избранное", "cmd_subscriptions": "🔔 Подписки", "cmd_help": "ℹ️ Помощь",
}

LANG = {"bg": BG, "ru": RU}

def t(key, lang='bg', **kwargs):
    text = LANG.get(lang, BG).get(key, BG.get(key, key))
    try:
        return text.format(**kwargs) if kwargs else text
    except:
        return text

def get_user_lang(user_id, ctx=None):
    if ctx and "lang" in ctx.user_data:
        return ctx.user_data["lang"]
    try:
        conn = _db()
        row = conn.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        if row:
            lang = row["language"]
            if ctx: ctx.user_data["lang"] = lang
            return lang
    except: pass
    if ctx: ctx.user_data["lang"] = "bg"
    return "bg"

def set_user_lang(user_id, lang, ctx=None):
    try:
        conn = _db()
        conn.execute("INSERT INTO users (user_id,language) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET language=?", (user_id, lang, lang))
        conn.commit(); conn.close()
        if ctx: ctx.user_data["lang"] = lang
    except Exception as e: print(f"set_user_lang error: {e}")

def detect_telegram_lang(update):
    """Определяет язык пользователя по настройкам Telegram.
    
    Приоритет:
    1. language_code пользователя (ru -> русский, bg -> болгарский)
    2. Если не ru и не bg - возвращаем болгарский как язык по умолчанию
    """
    try:
        code = update.effective_user.language_code or ""
        code_lower = code.lower()
        
        # Если язык русский - возвращаем ru
        if code_lower.startswith("ru"):
            return "ru"
        
        # Если язык болгарский - возвращаем bg
        if code_lower.startswith("bg"):
            return "bg"
        
    except Exception as e:
        print(f"detect_telegram_lang error: {e}")
    
    # По умолчанию - болгарский (так как бот для Варны, Болгария)
    return "bg"



# Дополнительные переводы
BG.update({
    "ad_choose_type": "*{action}* — изберете тип:",
    "ad_limit": "⚠️ Достигнали сте лимита от *{max} активни обяви*.\nИзтрийте стари обяви за да добавите нови.",
    "ad_location_how": "📍 Как да посочите местоположението на обекта?",
    "ad_enter_address": "✏️ Въведете *адрес на обекта*:\n\nНапример: _ул. Цар Симеон I 15_ или _бул. Приморски 42_\n\nБотът ще намери това място на картата.",
    "ad_send_geo": "📍 Изпратете геолокация на обекта чрез бутона по-долу.\n\nНе е нужно да сте наблизо:\n📎 → Геолокация → намерете адрес → преместете маркера → Изпращане",
    "ad_press_button": "Натиснете бутона:",
    "ad_searching": "🔍 Търся на картата...",
    "ad_not_found": "❌ Адресът не е намерен. Опитайте по-точно:\n_ул. Цар Симеон I 15_ или _бул. Владислав Варненчик 42_",
    "ad_confirm_address": "📍 Намерих: _{display}_\n\nТова ли е правилното място?",
    "ad_retry_address": "✏️ Въведете адрес отново:",
    "ad_retry_geo": "📍 Изпратете точна геолокацию чрез 📎 → Геолокация:",
    "ad_phone_prompt": "📞 *Телефонен номер* за връзка\n\nНатиснете бутона, за да изпратите вашия номер автоматично,\nили въведете номер ръчно, или натиснете «Пропускане».",
    "ad_too_far": "❌ *Обявата е твърде далеч от Варна!*",
    "ad_detecting_address": "🔍 Определям адрес по геолокация...",
    "ad_phone_invalid": "❌ Некоректен формат на телефон.\nПример: *+359888123456* или *0888123456*\nИли натиснете «⏩ Пропускане»",
    "ad_price_prompt": "💰 Въведете *цена* (число, €):",
    "ad_price_invalid": "❌ Въведете число, например: 5000",
    "ad_desc_prompt": "📝 Добавете *описание* (площ, особености, достъп)\nИли «-» за да пропуснете:",
    "ad_photos_prompt": "📸 Изпратете до 5 снимки *наведнъж* (незадължително)\n\nИзберете всички снимки в галерията и изпратете с едно съобщение.\nИли «-» за да пропуснете:",
    "ad_review": "*Проверете обявата:*\n\n",
    "ad_cancelled": "❌ Обявата е отменена.",
    "ad_published": "✅ Обявата е публикувана!",
    "ad_new_location": "📍 Как да посочите ново местоположение?",
    "ad_new_phone": "📞 Натиснете бутона или въведете ръчно:",
    "ad_new_price": "💰 Въведете нова *цена* (число, €):",
    "ad_new_desc": "📝 Въведете ново *описание*\nИли «-» за да премахнете:",
    "ad_new_photos": "📸 Изпратете нови снимки (до 5)\nИли «-» за да премахнете:",
    "my_no_listings": "Все още нямате обяви.",
    "my_edit_title": "✏️ *Редактиране на обява #{lid}*\nИзберете какво да промените:",
    "my_enter_value": "Въведете нова стойност:",
    "edit_address": "📍 Въведете нов *адрес*:",
    "edit_phone": "📞 Въведете нов *телефон* (или «-» за да премахнете):",
    "edit_price": "💰 Въведете нова *цена* (число, €):",
    "edit_desc": "📝 Въведете ново *описание* (или «-» за да премахнете):",
    "edit_photos": "📸 Изпратете нови *снимки* (до 5, или «-» за да премахнете всички):",
    "search_location_how": "📍 Как да посочите вашето местоположение за търсене?",
    "search_enter_address": "✏️ Въведете *вашия адрес*:\n\nНапример: _ул. Цар Симеон I 15_\n\nБотът ще го намери на картата и ще предложи радиус за търсене.",
    "search_send_geo": "📍 Изпратете вашата геолокация:\n\n• Натиснете бутона «Изпращане на моята геолокация» по-долу\n• Или чрез кламер 📎 → Геолокация",
    "search_choose_method": "Изберете начин:",
    "search_searching": "🔍 Търся на картата...",
    "search_not_found": "❌ Адресът не е намерен. Опитайте по-точно:",
    "help_text": "*ParkPlace Varna — паркоместа и гаражи*\n\n🛒 *Купува / Наем* — търсене на обект\n💰 *Продава / Под наем* — публикуване на обява\n⭐ *Любими* — запазени обяви\n🔔 *Абонаменти* — известия за нови обяви\n\n*Команди:*\n/start — Главно меню\n/my — Моите обяви\n/favorites — Любими\n/subscriptions — Абонаменти\n/help — Помощ\n\n_Обявите се изтриват автоматично ако не са потвърдени в рамките на 7 дни_",
    "fav_empty": "⭐ Все още нямате любими обяви.\n\nДобавяйте обяви в любими, за да не ги загубите!",
    "sub_no_active": "🔔 Нямате активни абонаменти.",
    "sub_no_listings": "🔔 Нямате абонаменти.",
    "search_choose_method": "Изберете начин:",
    "choose_radius": "📏 Изберете радиус:",
    "ad_address_updated": "✅ Адресът е обновен!",
    "ad_address_confirmed": "✅ Адресът е потвърден!",
    "ad_too_far_details": "❌ *Обявата е твърде далеч от Варна!*\n\nРазстояние: {dist} км (макс. {max_dist} км)",
    "ad_geo_saved": "✅ Геолокацията е запазена!",
    "ad_geo_saved_no_addr": "✅ Геолокацията е запазена (адресът не е намерен автоматично)!",
    "photos_received": "✅ Получени *{cnt}* снимки.\nНатиснете *Готово* за да продължите:",
    "photos_done_btn": "✅ Готово ({cnt} снимки)",
    "photos_send_or_skip": "📸 Изпратете снимки или натиснете *Пропускане*:",
    "photo_line_with": "🖼 {cnt} снимки",
    "photo_line_without": "🖼 Без снимка",
    "listing_status_active": "✅ Активна",
    "listing_status_inactive": "⏸ Неактивна",
    "page_info": "📄 Страница {page} от {total_pages} (общо {total_listings} обяви)",
    "btn_next_page": "Напред ▶️",
    "btn_edit": "✏️ Редактиране",
    "fav_added": "⭐ Добавено в любими!",
    "fav_already": "Вече в любими",
    "fav_removed": "💔 Премахнато от любими",
    "listing_not_found": "❌ Обява не е намерена!",
    "message_sent": "✅ Отправлено!",
    "message_saved": "✅ Запазено.",
    "photos_removed": "✅ Снимките са премахнати!",
    "search_no_results": "😕 В радиус {radius} няма намерени обяви.\n\n💡 Искате ли да получавате известия когато се появи подходяща обява?",
    "search_params_lost": "❌ Параметрите на търсенето са загубени, повторете търсенето.",
    "subscription_exists": "ℹ️ Вече имате активен абонамент с тези параметри!",
    "subscription_activated_admin": "✅ *Абонаментът е активиран!* (безплатно за администратор)\n\nЩе получавате известия за нови обяви, които отговарят на вашите критерии.\nВалиден до: {expires}",
    "subscription_invoice_title": "🔔 Абонамент за известия",
    "subscription_invoice_desc": "{action} · {type}\nРадиус: {radius}\nВалиден: 30 дни",
    "subscription_invoice_label": "Абонамент 30 дни",
    "notify_fav_updated": "⭐ *Обявата от вашите любими е обновена!*",
    "notify_price_changed": "💰 *Цената е променена*\nБеше: {old} €\nСега: {new} €",
    "notify_address_changed": "📍 *Адресът е променен*\nБеше: {old}\nСега: {new}",
    "notify_phone_added": "📞 *Телефонът е добавен*",
    "notify_phone_changed": "📞 *Телефонът е променен*",
    "notify_phone_removed": "📞 *Телефонът е премахнат*",
    "notify_desc_added": "📝 *Описанието е добавено*",
    "notify_desc_changed": "📝 *Описанието е променено*",
    "notify_desc_removed": "📝 *Описанието е премахнато*",
    "notify_photos_updated": "📸 *Снимките са обновени*\n{count} снимки",
    "notify_photos_removed": "📸 *Снимките са премахнати*",
    "notify_listing_updated": "✏️ Обявата #{lid} е обновена",
    "notify_listing_deleted": "❌ *Обявата е изтрита*\n\n#{lid} · {address}\n\nОбявата беше премахната от вашите любими, тъй като беше изтрита.",
    "edit_prompt_address": "📍 Въведете нов *адрес*:",
    "edit_prompt_phone": "📞 Въведете нов *телефон* (или «-» за да премахнете):",
    "edit_prompt_price": "💰 Въведете нова *цена* (число, €):",
    "edit_prompt_desc": "📝 Въведете ново *описание* (или «-» за да премахнете):",
    "edit_prompt_photo": "📸 Изпратете нови *снимки* (до 5, или «-» за да премахнете всички):",
    "edit_prompt_default": "Въведете нова стойност:",
    "edit_field_updated": "✅ Полето е обновено!",
    "listing_deleted": "🗑 Обявата е изтрита.",
    "address_updated": "✅ Адресът е обновен: {address}",
    "address_not_found": "❌ Адресът не е намерен. Опитайте отново:",
    "phone_updated": "✅ Телефонът е обновен!",
    "price_updated": "✅ Цената е обновена: {price} €",
    "price_invalid": "❌ Въведете число, например: 5000",
    "desc_updated": "✅ Описанието е обновено!",
    "photos_updated": "✅ Снимките са обновени!",
    "btn_subscribe_notif": "🔔 Абонамент за известия (⭐100 ≈ 2€)",
    "btn_change_radius": "🔄 Промяна на радиус",
    "error_params_lost": "❌ Грешка: параметри не са намерени.",
    "btn_prev_page": "◀️ Назад",
    "btn_add_to_fav": "⭐ В любими",
    "btn_remove_from_fav": "💔 Премахни от любими",
    "my_edit_title": "✏️ *Редактиране на обява #{lid}*\nИзберете какво да промените:",
    "btn_delete_listing": "🗑 Изтрий обявата",
    "sub_edit_title": "✏️ *Редактиране на абонамент #{sub_id}*\n\nИзберете какво да промените:",
    "btn_delete_it": "🗑 Изтрий я",
    "confirm_listing_prompt": "⏰ *Обява #{lid}* е публикувана преди повече от 7 дни.\n\nВсе още ли е актуална? Потвърдете в рамките на 48 часа, иначе ще бъде изтрита автоматично.",
    "btn_confirm_active": "✅ Да, актуална е",
    "search_found": "🔍 Намерени *{count}* обяви · радиус: {radius}",
    "admin_stats": "📊 *Статистика:*\n\n📋 Всего: {total} · Активни: {active}\n💰 Продажа: {sell} · 📋 Аренда: {lease}\n🅿️ Парковок: {parking} · 🚘 Гаражей: {garage}\n🗺 С геолокацией: {geo}\n\n👥 Потребители: {users} · ✉️ Съобщения: {msgs}",
    "btn_back_menu": "↩️ В меню",
    "admin_broadcast_prompt": "📢 Въведете текст на рассилката (или «отмена»):",
    "choose_action": "Какво искате да направите?",
})

RU.update({
    "ad_choose_type": "*{action}* — выберите тип:",
    "ad_limit": "⚠️ Вы достигли лимита *{max} активных объявлений*.\nУдалите старые, чтобы добавить новые.",
    "ad_location_how": "📍 Как указать местоположение объекта?",
    "ad_enter_address": "✏️ Введите *адрес объекта*:\n\nНапример: _ул. Цар Симеон I 15_ или _бул. Приморски 42_\n\nБот найдёт это место на карте.",
    "ad_send_geo": "📍 Отправьте геолокацию объекта через кнопку ниже.\n\nНе нужно быть рядом:\n📎 → Геолокация → найдите адрес → переместите маркер → Отправить",
    "ad_press_button": "Нажмите кнопку:",
    "ad_searching": "🔍 Ищу на карте...",
    "ad_not_found": "❌ Адрес не найден. Попробуйте точнее:\n_ул. Цар Симеон I 15_ или _бул. Владислав Варненчик 42_",
    "ad_confirm_address": "📍 Найдено: _{display}_\n\nЭто правильное место?",
    "ad_retry_address": "✏️ Введите адрес заново:",
    "ad_retry_geo": "📍 Отправьте точную геолокацию через 📎 → Геолокация:",
    "ad_phone_prompt": "📞 *Номер телефона* для связи\n\nНажмите кнопку для автоматической отправки,\nили введите вручную, или нажмите «Пропустить».",
    "ad_too_far": "❌ *Объявление слишком далеко от Варны!*",
    "ad_detecting_address": "🔍 Определяю адрес по геолокации...",
    "ad_phone_invalid": "❌ Неверный формат телефона.\nПример: *+359888123456* или *0888123456*\nИли нажмите «⏩ Пропустить»",
    "ad_price_prompt": "💰 Введите *цену* (число, €):",
    "ad_price_invalid": "❌ Введите число, например: 5000",
    "ad_desc_prompt": "📝 Добавьте *описание* (площадь, особенности, доступ)\nИли «-» чтобы пропустить:",
    "ad_photos_prompt": "📸 Отправьте до 5 фото *одним сообщением* (необязательно)\n\nВыберите все фото в галерее и отправьте одним сообщением.\nИли «-» чтобы пропустить:",
    "ad_review": "*Проверьте объявление:*\n\n",
    "ad_cancelled": "❌ Объявление отменено.",
    "ad_published": "✅ Объявление опубликовано!",
    "ad_new_location": "📍 Как указать новое местоположение?",
    "ad_new_phone": "📞 Нажмите кнопку или введите вручную:",
    "ad_new_price": "💰 Введите новую *цену* (число, €):",
    "ad_new_desc": "📝 Введите новое *описание*\nИли «-» чтобы удалить:",
    "ad_new_photos": "📸 Отправьте новые фото (до 5)\nИли «-» чтобы удалить:",
    "my_no_listings": "У вас пока нет объявлений.",
    "my_edit_title": "✏️ *Редактирование объявления #{lid}*\nВыберите что изменить:",
    "my_enter_value": "Введите новое значение:",
    "edit_address": "📍 Введите новый *адрес*:",
    "edit_phone": "📞 Введите новый *телефон* (или «-» чтобы удалить):",
    "edit_price": "💰 Введите новую *цену* (число, €):",
    "edit_desc": "📝 Введите новое *описание* (или «-» чтобы удалить):",
    "edit_photos": "📸 Отправьте новые *фото* (до 5, или «-» чтобы удалить все):",
    "search_location_how": "📍 Как указать ваше местоположение для поиска?",
    "search_enter_address": "✏️ Введите *ваш адрес*:\n\nНапример: _ул. Цар Симеон I 15_\n\nБот найдёт его на карте и предложит радиус поиска.",
    "search_send_geo": "📍 Отправьте вашу геолокацию:\n\n• Нажмите кнопку «Отправить мою геолокацию» ниже\n• Или через скрепку 📎 → Геолокация",
    "search_choose_method": "Выберите способ:",
    "search_searching": "🔍 Ищу на карте...",
    "search_not_found": "❌ Адрес не найден. Попробуйте точнее:",
    "help_text": "*ParkPlace Varna — парковки и гаражи*\n\n🛒 *Купить / Аренда* — поиск объекта\n💰 *Продать / Сдать* — публикация объявления\n⭐ *Избранное* — сохранённые объявления\n🔔 *Подписки* — уведомления о новых объявлениях\n\n*Команды:*\n/start — Главное меню\n/my — Мои объявления\n/favorites — Избранное\n/subscriptions — Подписки\n/help — Помощь\n\n_Объявления удаляются автоматически если не подтверждены в течение 7 дней_",
    "fav_empty": "⭐ У вас пока нет избранных объявлений.\n\nДобавляйте в избранное, чтобы не потерять!",
    "sub_no_active": "🔔 У вас нет активных подписок.",
    "sub_no_listings": "🔔 У вас нет подписок.",
    "search_choose_method": "Выберите способ:",
    "choose_radius": "📏 Выберите радиус:",
    "ad_address_updated": "✅ Адрес обновлён!",
    "ad_address_confirmed": "✅ Адрес подтверждён!",
    "ad_too_far_details": "❌ *Объявление слишком далеко от Варны!*\n\nРасстояние: {dist} км (макс. {max_dist} км)",
    "ad_geo_saved": "✅ Геолокация сохранена!",
    "ad_geo_saved_no_addr": "✅ Геолокация сохранена (адрес не найден автоматически)!",
    "photos_received": "✅ Получено *{cnt}* фото.\nНажмите *Готово* чтобы продолжить:",
    "photos_done_btn": "✅ Готово ({cnt} фото)",
    "photos_send_or_skip": "📸 Отправьте фото или нажмите *Пропустить*:",
    "photo_line_with": "🖼 {cnt} фото",
    "photo_line_without": "🖼 Без фото",
    "listing_status_active": "✅ Активно",
    "listing_status_inactive": "⏸ Неактивно",
    "page_info": "📄 Страница {page} из {total_pages} (всего {total_listings} объявлений)",
    "btn_next_page": "Вперёд ▶️",
    "btn_edit": "✏️ Редактировать",
    "fav_added": "⭐ Добавлено в избранное!",
    "fav_already": "Уже в избранном",
    "fav_removed": "💔 Удалено из избранного",
    "listing_not_found": "❌ Объявление не найдено!",
    "message_sent": "✅ Отправлено!",
    "message_saved": "✅ Сохранено.",
    "photos_removed": "✅ Фото удалены!",
    "search_no_results": "😕 В радиусе {radius} не найдено объявлений.\n\n💡 Хотите получать уведомления когда появится подходящее объявление?",
    "search_params_lost": "❌ Параметры поиска потеряны, повторите поиск.",
    "subscription_exists": "ℹ️ У вас уже есть активная подписка с этими параметрами!",
    "subscription_activated_admin": "✅ *Подписка активирована!* (бесплатно для администратора)\n\nВы будете получать уведомления о новых объявлениях, соответствующих вашим критериям.\nДействительна до: {expires}",
    "subscription_invoice_title": "🔔 Подписка на уведомления",
    "subscription_invoice_desc": "{action} · {type}\nРадиус: {radius}\nДействительна: 30 дней",
    "subscription_invoice_label": "Подписка 30 дней",
    "notify_fav_updated": "⭐ *Объявление из вашего избранного обновлено!*",
    "notify_price_changed": "💰 *Цена изменена*\nБыло: {old} €\nСтало: {new} €",
    "notify_address_changed": "📍 *Адрес изменён*\nБыло: {old}\nСтало: {new}",
    "notify_phone_added": "📞 *Телефон добавлен*",
    "notify_phone_changed": "📞 *Телефон изменён*",
    "notify_phone_removed": "📞 *Телефон удалён*",
    "notify_desc_added": "📝 *Описание добавлено*",
    "notify_desc_changed": "📝 *Описание изменено*",
    "notify_desc_removed": "📝 *Описание удалено*",
    "notify_photos_updated": "📸 *Фото обновлены*\n{count} фото",
    "notify_photos_removed": "📸 *Фото удалены*",
    "notify_listing_updated": "✏️ Объявление #{lid} обновлено",
    "notify_listing_deleted": "❌ *Объявление удалено*\n\n#{lid} · {address}\n\nОбъявление было удалено из вашего избранного, так как было удалено.",
    "edit_prompt_address": "📍 Введите новый *адрес*:",
    "edit_prompt_phone": "📞 Введите новый *телефон* (или «-» чтобы удалить):",
    "edit_prompt_price": "💰 Введите новую *цену* (число, €):",
    "edit_prompt_desc": "📝 Введите новое *описание* (или «-» чтобы удалить):",
    "edit_prompt_photo": "📸 Отправьте новые *фото* (до 5, или «-» чтобы удалить все):",
    "edit_prompt_default": "Введите новое значение:",
    "edit_field_updated": "✅ Поле обновлено!",
    "listing_deleted": "🗑 Объявление удалено.",
    "address_updated": "✅ Адрес обновлён: {address}",
    "address_not_found": "❌ Адрес не найден. Попробуйте снова:",
    "phone_updated": "✅ Телефон обновлён!",
    "price_updated": "✅ Цена обновлена: {price} €",
    "price_invalid": "❌ Введите число, например: 5000",
    "desc_updated": "✅ Описание обновлено!",
    "photos_updated": "✅ Фото обновлены!",
    "btn_subscribe_notif": "🔔 Подписка на уведомления (⭐100 ≈ 2€)",
    "btn_change_radius": "🔄 Изменить радиус",
    "error_params_lost": "❌ Ошибка: параметры не найдены.",
    "btn_prev_page": "◀️ Назад",
    "btn_add_to_fav": "⭐ В избранное",
    "btn_remove_from_fav": "💔 Удалить из избранного",
    "my_edit_title": "✏️ *Редактирование объявления #{lid}*\nВыберите что изменить:",
    "btn_delete_listing": "🗑 Удалить объявление",
    "sub_edit_title": "✏️ *Редактирование подписки #{sub_id}*\n\nВыберите что изменить:",
    "btn_delete_it": "🗑 Удалить её",
    "confirm_listing_prompt": "⏰ *Объявление #{lid}* опубликовано более 7 дней назад.\n\nОно всё ещё актуально? Подтвердите в течение 48 часов, иначе оно будет удалено автоматически.",
    "btn_confirm_active": "✅ Да, актуально",
    "search_found": "🔍 Найдено *{count}* объявлений · радиус: {radius}",
    "admin_stats": "📊 *Статистика:*\n\n📋 Всего: {total} · Активных: {active}\n💰 Продажа: {sell} · 📋 Аренда: {lease}\n🅿️ Парковок: {parking} · 🚘 Гаражей: {garage}\n🗺 С геолокацией: {geo}\n\n👥 Пользователей: {users} · ✉️ Сообщений: {msgs}",
    "btn_back_menu": "↩️ В меню",
    "admin_broadcast_prompt": "📢 Введите текст рассылки (или «отмена»):",
    "choose_action": "Что вы хотите сделать?",
})
