# translations.py - Переводы для мультиязычности

TRANSLATIONS = {
    "ru": {
        # Главное меню
        "buy": "🛒 Купить",
        "sell": "💰 Продать",
        "rent": "🔑 Арендовать",
        "lease": "📋 Сдать в аренду",
        "my_listings": "📁 Мои объявления",
        "favorites": "⭐ Избранное",
        "subscriptions": "🔔 Мои подписки",
        "home": "🏠 На главную",
        "back": "◀️ Назад",
        "cancel": "❌ Отмена",
        
        # Типы
        "parking": "🅿️ Паркоместо",
        "garage": "🏠 Гараж",
        "all": "📋 Всё",
        
        # Поиск
        "choose_type": "Выберите тип:",
        "choose_radius": "Выберите радиус поика:",
        "all_varna": "📋 Вся Варна",
        "no_results": "😕 В радиусе {} объявлений не найдено.",
        "results_found": "🔍 Найдено *{}* объявл. · радиус: {}",
        
        # Подписка
        "subscribe_btn": "🔔 Подписаться на уведомления (⭐100 ≈ 2€)",
        "subscribe_question": "💡 Хотите получать уведомления когда появится подходящее объявление?",
        "subscribe_success": """✅ *Подписка активирована!*

📌 *Параметры:*
• {}
• {}
• Радиус: {}

🔔 Вы получите уведомление когда появится подходящее объявление.

⏰ Подписка действует: 30 дней""",
        
        # Команды
        "help": """*ParkRent Varna — поиск парковок и гаражей*

🛒 *Купить/Арендовать*
Найдите парковку или гараж в нужном районе

💰 *Продать/Сдать*
Разместите объявление бесплатно

📁 *Мои объявления*
Управление вашими объявлениями

⭐ *Избранное*
Сохранённые объявления

🔔 *Подписки*
Уведомления о новых объявлениях

*Команды:*
/start — Главное меню
/my — Мои объявления  
/favorites — Избранное
/subscriptions — Подписки
/help — Эта справка

_Объявления автоматически удаляются если не подтверждены в течение 7 дней_""",
    },
    
    "bg": {
        # Главное меню
        "buy": "🛒 Купува",
        "sell": "💰 Продава",
        "rent": "🔑 Наем",
        "lease": "📋 Под наем",
        "my_listings": "📁 Моите обяви",
        "favorites": "⭐ Любими",
        "subscriptions": "🔔 Абонаменти",
        "home": "🏠 Начало",
        "back": "◀️ Назад",
        "cancel": "❌ Отказ",
        
        # Типы
        "parking": "🅿️ Паркомясто",
        "garage": "🏠 Гараж",
        "all": "📋 Всичко",
        
        # Поиск
        "choose_type": "Изберете тип:",
        "choose_radius": "Изберете радиус на търсене:",
        "all_varna": "📋 Цяла Варна",
        "no_results": "😕 В радиус {} няма намерени обяви.",
        "results_found": "🔍 Намерени *{}* обяви · радиус: {}",
        
        # Подписка
        "subscribe_btn": "🔔 Абонамент за известия (⭐100 ≈ 2€)",
        "subscribe_question": "💡 Искате ли да получавате известия когато се появи подходяща обява?",
        "subscribe_success": """✅ *Абонаментът е активиран!*

📌 *Параметри:*
• {}
• {}
• Радиус: {}

🔔 Ще получите известие когато се появи подходяща обява.

⏰ Абонаментът е валиден: 30 дни""",
        
        # Команды
        "help": """*ParkRent Varna — търсене на паркинги и гаражи*

🛒 *Купува/Наем*
Намерете паркомясто или гараж в нужния район

💰 *Продава/Под наем*
Публикувайте обява безплатно

📁 *Моите обяви*
Управление на вашите обяви

⭐ *Любими*
Запазени обяви

🔔 *Абонаменти*
Известия за нови обяви

*Команди:*
/start — Главно меню
/my — Моите обяви  
/favorites — Любими
/subscriptions — Абонаменти
/help — Помощ

_Обявите се изтриват автоматично ако не са потвърдени в рамките на 7 дни_""",
    },
    
    "en": {
        # Главное меню
        "buy": "🛒 Buy",
        "sell": "💰 Sell",
        "rent": "🔑 Rent",
        "lease": "📋 For Rent",
        "my_listings": "📁 My Listings",
        "favorites": "⭐ Favorites",
        "subscriptions": "🔔 Subscriptions",
        "home": "🏠 Home",
        "back": "◀️ Back",
        "cancel": "❌ Cancel",
        
        # Типы
        "parking": "🅿️ Parking Space",
        "garage": "🏠 Garage",
        "all": "📋 All",
        
        # Поиск
        "choose_type": "Choose type:",
        "choose_radius": "Choose search radius:",
        "all_varna": "📋 All Varna",
        "no_results": "😕 No listings found within {} radius.",
        "results_found": "🔍 Found *{}* listings · radius: {}",
        
        # Подписка
        "subscribe_btn": "🔔 Subscribe to notifications (⭐100 ≈ €2)",
        "subscribe_question": "💡 Would you like to receive notifications when a suitable listing appears?",
        "subscribe_success": """✅ *Subscription activated!*

📌 *Parameters:*
• {}
• {}
• Radius: {}

🔔 You will receive a notification when a suitable listing appears.

⏰ Subscription valid for: 30 days""",
        
        # Команды
        "help": """*ParkRent Varna — parking and garage search*

🛒 *Buy/Rent*
Find a parking space or garage in your area

💰 *Sell/For Rent*
Post a listing for free

📁 *My Listings*
Manage your listings

⭐ *Favorites*
Saved listings

🔔 *Subscriptions*
Notifications about new listings

*Commands:*
/start — Main menu
/my — My listings  
/favorites — Favorites
/subscriptions — Subscriptions
/help — Help

_Listings are automatically deleted if not confirmed within 7 days_""",
    }
}

# Функция для получения перевода
def t(key, lang="ru"):
    """Получить перевод для ключа."""
    return TRANSLATIONS.get(lang, TRANSLATIONS["ru"]).get(key, TRANSLATIONS["ru"].get(key, key))

# Функция для получения языка пользователя
def get_user_language(user_id, conn=None):
    """Получить язык пользователя из БД."""
    if conn is None:
        import sqlite3
        conn = sqlite3.connect("parking.db")
        should_close = True
    else:
        should_close = False
    
    try:
        result = conn.execute("SELECT language FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
        lang = result[0] if result else "ru"
    except:
        lang = "ru"
    finally:
        if should_close:
            conn.close()
    
    return lang

# Функция для установки языка
def set_user_language(user_id, language, conn=None):
    """Установить язык пользователя."""
    if conn is None:
        import sqlite3
        conn = sqlite3.connect("parking.db")
        should_close = True
    else:
        should_close = False
    
    try:
        conn.execute("""
            INSERT OR REPLACE INTO user_settings (user_id, language) 
            VALUES (?, ?)
        """, (user_id, language))
        conn.commit()
    finally:
        if should_close:
            conn.close()
