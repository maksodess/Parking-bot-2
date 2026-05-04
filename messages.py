# messages.py - ПОЛНАЯ локализация ParkPlace Varna Bot
# 230+ переведённых строк

import sqlite3
import os

DATA_DIR = os.environ.get("DATA_DIR", "./data")
DB_FILE = os.path.join(DATA_DIR, "parking.db")

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# Все сообщения бота
LANG = {
    "bg": {
        # === ГЛАВНОЕ МЕНЮ ===
        "welcome": "🚗 *ParkPlace Varna*\nКакво искате да направите?",
        "choose_action": "Изберете действие:",
        
        # === КНОПКИ ===
        "btn_buy": "🛒 Купува",
        "btn_sell": "💰 Продава",
        "btn_rent": "🔑 Наем",
        "btn_lease": "📋 Под наем",
        "btn_my_listings": "📁 Моите обяви",
        "btn_favorites": "⭐ Любими",
        "btn_subscriptions": "🔔 Абонаменти",
        "btn_help": "❓ Помощ",
        "btn_home": "🏠 Начало",
        "btn_language": "🇧🇬/🇷🇺 Език",
        "btn_edit": "✏️ Редактиране",
        "btn_delete": "🗑 Изтрий",
        "btn_confirm": "✅ Потвърди",
        "btn_cancel": "❌ Отказ",
        "btn_back": "◀️ Назад",
        "btn_next": "Напред ▶️",
        "btn_skip": "⏭ Пропусни",
        "btn_done": "✅ Готово",
        "btn_send_contact": "📱 Изпрати номер",
        "btn_send_location": "📍 Изпрати локация",
        "btn_map": "🗺 На картата",
        "btn_contact_owner": "✉️ Свържи се",
        
        # === ДЕЙСТВИЯ ===
        "action_buy": "купува",
        "action_sell": "продава",
        "action_rent": "под наем",
        "action_lease": "наем",
        
        # === ТИПЫ ОБЪЕКТОВ ===
        "type_parking": "🅿️ Паркомясто",
        "type_garage": "🚘 Гараж",
        
        # === СОЗДАНИЕ ОБЪЯВЛЕНИЯ ===
        "ad_type_question": "🏢 *Тип обект*\n\nКакво искате да {action}?",
        "ad_address_question": "📍 *Адрес на обекта*\n\nВъведете адрес или име на улица:",
        "ad_address_confirm": "📍 Адресът е: *{address}*\n\nПотвърдете или въведете отново:",
        "ad_location_choice": "📍 *Местоположение на обекта*\n\nКак искате да посочите локацията?",
        "ad_location_geo_btn": "📍 Изпрати геолокация",
        "ad_location_address_btn": "📝 Само адрес (без карта)",
        "ad_location_saved": "✅ Геолокацията е запазена!",
        "ad_location_address_saved": "✅ Адресът е запазен!",
        "ad_phone_question": "📞 *Телефонен номер* за връзка\n\nНатиснете бутона, за да изпратите вашия номер автоматично,\nили въведете номер ръчно, или натиснете «Пропускане».",
        "ad_phone_saved": "✅ Телефонът е запазен: {phone}",
        "ad_phone_invalid": "❌ Невалиден телефонен номер.\n\nФормат: +359XXXXXXXXX или 08XXXXXXXX",
        "ad_price_question": "💰 *Цена*\n\nВъведете цена в евро (EUR):",
        "ad_price_saved": "✅ Цената е запазена: {price} €",
        "ad_price_invalid": "❌ Невалидна цена.\n\nВъведете число (например: 5000 или 5000.50)",
        "ad_description_question": "📝 *Описание*\n\nОпишете обекта (до 500 символа):\n\n_Например: Охраняем паркинг в центъра, асфалт, видеонаблюдение_",
        "ad_description_saved": "✅ Описанието е запазено",
        "ad_description_too_long": "❌ Описанието е твърде дълго ({length} символа).\n\nМаксимум: 500 символа",
        "ad_photo_question": "📸 *Снимки на обекта*\n\nИзпратете до 5 снимки (по една).\nНатиснете «✅ Готово» когато приключите, или «⏭ Пропусни» за публикуване без снимки.",
        "ad_photo_saved": "✅ Снимка {num} от 5 запазена",
        "ad_photo_limit": "❌ Можете да добавите максимум 5 снимки",
        "ad_photo_waiting": "⏳ Изчакайте малко преди да изпратите следващата снимка...",
        "ad_preview_title": "📋 *Преглед на обявата*\n\nПроверете данните преди публикуване:",
        "ad_created_success": "✅ *Обявата е създадена!*\n\nТя ще бъде видима след потвърждение от администратор (до 24 часа).",
        "ad_limit_reached": "❌ Достигнат лимит от {max} обяви\n\nИзтрийте стара обява за да създадете нова.",
        "ad_too_far_from_varna": "❌ *Обявата е твърде далеч от Варна!*\n\nРазстояние от центъра на Варна: {distance} км\nМаксимално разрешено: {max} км\n\n💡 Този бот е само за обяви във Варна и околностите.\nМоля, изберете локация във Варна.",
        
        # === ПОИСК ===
        "search_type_question": "🏢 *Какво търсите?*",
        "search_location_question": "📍 *Къде търсите?*\n\nИзпратете геолокация или адрес:",
        "search_location_sent": "✅ Локацията е запазена",
        "search_radius_question": "📏 *Радиус на търсене*\n\nИзберете разстояние от вашата локация:",
        "search_radius_1km": "📍 1 км",
        "search_radius_3km": "📍 3 км",
        "search_radius_5km": "📍 5 км",
        "search_radius_10km": "📍 10 км",
        "search_radius_all": "🌍 Цяла Варна",
        "search_results_found": "🔍 Намерени *{count}* обяви · радиус: {radius}",
        "search_no_results": "😔 Не са намерени обяви с тези критерии.\n\nОпитайте да:\n• Увеличите радиуса\n• Промените местоположението\n• Проверите други критерии",
        "search_page_info": "📄 Страница {page} от {total} (общо {count} обяви)",
        "search_subscribe_btn": "🔔 Абонамент за известия",
        "search_change_radius_btn": "📏 Промени радиус",
        
        # === ИЗБРАННОЕ ===
        "favorites_empty": "⭐ Все още нямате любими обяви.\n\nДобавяйте обяви в любими, за да не ги загубите!",
        "favorites_title": "⭐ *Любими* ({count} обяви)",
        "favorites_added": "✅ Добавено в любими!",
        "favorites_removed": "💔 Премахнато от любими",
        "favorites_add_btn": "⭐ В любими",
        "favorites_remove_btn": "💔 Премахни от любими",
        
        # === МОИ ОБЪЯВЛЕНИЯ ===
        "my_listings_empty": "Все още нямате обяви.",
        "my_listings_title": "📁 *Вашите обяви* ({count})",
        "my_listings_status_active": "✅ Активна",
        "my_listings_status_inactive": "⏸ Неактивна",
        "my_listing_deleted": "🗑 Обявата е изтрита",
        "my_listing_confirm_delete": "❓ Сигурни ли сте, че искате да изтриете тази обява?",
        
        # === ПОДПИСКИ ===
        "subscriptions_title": "🔔 *Абонаменти за известия*",
        "subscriptions_empty": "Нямате активни абонаменти.",
        "subscription_offer": "🔔 *Искате да получавате известия?*\n\nКогато се появи нова обява, която отговаря на вашите критерии, ще получите съобщение.\n\n💰 Цена: 100 Telegram Stars (≈ 2 €)\n📅 Валидност: 30 дни",
        "subscription_created": "✅ *Абонаментът е активиран!*\n\nЩе получавате известия за нови обяви, които отговарят на вашите критерии.\nВалиден до: {expires}",
        "subscription_exists": "ℹ️ Вече имате активен абонамент с тези параметри!",
        "subscription_payment_sent": "💳 *Изпратено е известие за плащане.*\n\nНатиснете за да платите с Telegram Stars.",
        "subscription_admin_free": "✅ *Абонаментът е активиран!* (безплатно за администратор)\n\nЩе получавате известия за нови обяви, които отговарят на вашите критерии.\nВалиден до: {expires}",
        
        # === УВЕДОМЛЕНИЯ ===
        "notification_new_listing": "🆕 *Нова обява* отговаря на вашите критерии!\n\n{action} · {type}\nРадиус: {radius}",
        "notification_listing_updated": "✏️ *Обновена обява* във вашите любими:\n\n*Промени:*\n{changes}",
        
        # === ДЕТАЛИ ОБЪЯВЛЕНИЯ ===
        "listing_detail_header": "{emoji} {type} {action}",
        "listing_address": "📍 Адрес:",
        "listing_price": "💰 Цена:",
        "listing_phone": "📞 Телефон:",
        "listing_description": "📝 Описание:",
        "listing_distance": "📏 Разстояние:",
        "listing_views": "👁 Прегледи:",
        "listing_created": "📅 Публикувано:",
        "listing_owner_note": "Това е ваше обявление!",
        "listing_text_sell_parking": "💰 *Паркомясто на продажба*",
        "listing_text_sell_garage": "💰 *Гараж на продажба*",
        "listing_text_lease_parking": "📋 *Паркомясто под наем*",
        "listing_text_lease_garage": "📋 *Гараж под наем*",
        "listing_text_buy_parking": "🛒 *Търся паркомясто*",
        "listing_text_buy_garage": "🛒 *Търся гараж*",
        "listing_text_rent_parking": "🔑 *Търся паркомясто под наем*",
        "listing_text_rent_garage": "🔑 *Търся гараж под наем*",
        
        # === РЕДАКТИРОВАНИЕ ===
        "edit_choose_field": "✏️ *Редактиране на обява*\n\nИзберете какво искате да промените:",
        "edit_field_address": "Адрес",
        "edit_field_price": "Цена",
        "edit_field_description": "Описание",
        "edit_field_phone": "Телефон",
        "edit_saved": "✅ Промените са запазени!",
        
        # === ПОМОЩЬ ===
        "help_text": "❓ *Помощ - ParkPlace Varna*\n\n"
                     "🛒 *Купува / Наем* — търсене на обект\n"
                     "💰 *Продава / Под наем* — публикуване на обява\n\n"
                     "📁 *Моите обяви* — вашите публикации\n"
                     "⭐ *Любими* — запазени обяви\n"
                     "🔔 *Абонаменти* — известия за нови обяви\n\n"
                     "🗺 Радиус на търсене: максимум 50 км от центъра на Варна\n"
                     "📸 Можете да качите до 5 снимки на обява\n"
                     "⏰ Обявите се потвърждават до 24 часа\n\n"
                     "За въпроси: @admin",
        
        # === АДМИН ===
        "admin_panel": "👨‍💼 *Админ панел*\n\n"
                       "Изберете действие:",
        "admin_btn_broadcast": "📢 Разпращане",
        "admin_btn_stats": "📊 Статистика",
        "admin_broadcast_question": "📢 *Разпращане на съобщение*\n\nВъведете текста който искате да изпратите до всички потребители:",
        "admin_broadcast_confirm": "Изпрати до {count} потребители?",
        "admin_broadcast_sent": "✅ Изпратено до {count} потребители",
        "admin_broadcast_cancelled": "❌ Разпращането е отменено",
        
        # === КОНТАКТЫ ===
        "contact_send_message": "✉️ Напишете съобщение до владельца:",
        "contact_message_sent": "✅ Съобщението е изпратено!",
        "contact_own_listing": "Това е ваше обявление!",
        
        # === ОШИБКИ ===
        "error_general": "❌ Грешка. Моля опитайте отново.",
        "error_invalid_price": "❌ Невалидна цена.\n\nВъведете число (например: 5000)",
        "error_invalid_phone": "❌ Невалиден телефонен номер.\n\nФормат: +359XXXXXXXXX",
        "error_description_too_long": "❌ Описанието е твърде дълго ({length}/500 символа)",
        "error_photo_upload": "❌ Грешка при качване на снимка. Опитайте отново.",
        "error_location_failed": "❌ Не може да се определи адрес по тези координати.",
        "error_payment_failed": "❌ Грешка при създаване на плащане. Моля опитайте отново.",
        
        # === РАЗНОЕ ===
        "distance_km": "{distance} км",
        "distance_m": "{distance} м",
        "price_eur": "{price} €",
        "date_format": "{date}",
        "confirmation_pending": "⏳ Очаква потвърждение",
        "all_results_shown": "✅ Всички резултати са показани.",
        
        # === ЯЗЫК ===
        "language_choose": "🌐 *Език / Язык*\n\nИзберете език:",
        "language_current": "Текущ език: {language}",
        "language_changed": "✅ Езикът е променен на български",
        "language_bg": "🇧🇬 Български",
        "language_ru": "🇷🇺 Русский",
    },
    
    "ru": {
        # === ГЛАВНОЕ МЕНЮ ===
        "welcome": "🚗 *ParkPlace Varna*\nЧто вы хотите сделать?",
        "choose_action": "Выберите действие:",
        
        # === КНОПКИ ===
        "btn_buy": "🛒 Купить",
        "btn_sell": "💰 Продать",
        "btn_rent": "🔑 Аренда",
        "btn_lease": "📋 Сдать",
        "btn_my_listings": "📁 Мои объявления",
        "btn_favorites": "⭐ Избранное",
        "btn_subscriptions": "🔔 Подписки",
        "btn_help": "❓ Помощь",
        "btn_home": "🏠 Главная",
        "btn_language": "🇧🇬/🇷🇺 Язык",
        "btn_edit": "✏️ Редактировать",
        "btn_delete": "🗑 Удалить",
        "btn_confirm": "✅ Подтвердить",
        "btn_cancel": "❌ Отмена",
        "btn_back": "◀️ Назад",
        "btn_next": "Вперёд ▶️",
        "btn_skip": "⏭ Пропустить",
        "btn_done": "✅ Готово",
        "btn_send_contact": "📱 Отправить номер",
        "btn_send_location": "📍 Отправить локацию",
        "btn_map": "🗺 На карте",
        "btn_contact_owner": "✉️ Связаться",
        
        # === ДЕЙСТВИЯ ===
        "action_buy": "купить",
        "action_sell": "продать",
        "action_rent": "сдать",
        "action_lease": "арендовать",
        
        # === ТИПЫ ОБЪЕКТОВ ===
        "type_parking": "🅿️ Парковочное место",
        "type_garage": "🚘 Гараж",
        
        # === СОЗДАНИЕ ОБЪЯВЛЕНИЯ ===
        "ad_type_question": "🏢 *Тип объекта*\n\nЧто вы хотите {action}?",
        "ad_address_question": "📍 *Адрес объекта*\n\nВведите адрес или название улицы:",
        "ad_address_confirm": "📍 Адрес: *{address}*\n\nПодтвердите или введите заново:",
        "ad_location_choice": "📍 *Местоположение объекта*\n\nКак вы хотите указать локацию?",
        "ad_location_geo_btn": "📍 Отправить геолокацию",
        "ad_location_address_btn": "📝 Только адрес (без карты)",
        "ad_location_saved": "✅ Геолокация сохранена!",
        "ad_location_address_saved": "✅ Адрес сохранён!",
        "ad_phone_question": "📞 *Телефон для связи*\n\nНажмите кнопку, чтобы отправить ваш номер автоматически,\nили введите номер вручную, или нажмите «Пропустить».",
        "ad_phone_saved": "✅ Телефон сохранён: {phone}",
        "ad_phone_invalid": "❌ Неверный телефонный номер.\n\nФормат: +359XXXXXXXXX или 08XXXXXXXX",
        "ad_price_question": "💰 *Цена*\n\nВведите цену в евро (EUR):",
        "ad_price_saved": "✅ Цена сохранена: {price} €",
        "ad_price_invalid": "❌ Неверная цена.\n\nВведите число (например: 5000 или 5000.50)",
        "ad_description_question": "📝 *Описание*\n\nОпишите объект (до 500 символов):\n\n_Например: Охраняемая парковка в центре, асфальт, видеонаблюдение_",
        "ad_description_saved": "✅ Описание сохранено",
        "ad_description_too_long": "❌ Описание слишком длинное ({length} символов).\n\nМаксимум: 500 символов",
        "ad_photo_question": "📸 *Фотографии объекта*\n\nОтправьте до 5 фотографий (по одной).\nНажмите «✅ Готово» когда закончите, или «⏭ Пропустить» для публикации без фото.",
        "ad_photo_saved": "✅ Фото {num} из 5 сохранено",
        "ad_photo_limit": "❌ Можно добавить максимум 5 фото",
        "ad_photo_waiting": "⏳ Подождите немного перед отправкой следующего фото...",
        "ad_preview_title": "📋 *Предпросмотр объявления*\n\nПроверьте данные перед публикацией:",
        "ad_created_success": "✅ *Объявление создано!*\n\nОно будет видимо после подтверждения администратором (до 24 часов).",
        "ad_limit_reached": "❌ Достигнут лимит в {max} объявлений\n\nУдалите старое объявление чтобы создать новое.",
        "ad_too_far_from_varna": "❌ *Объявление слишком далеко от Варны!*\n\nРасстояние от центра Варны: {distance} км\nМаксимально разрешено: {max} км\n\n💡 Этот бот только для объявлений в Варне и окрестностях.\nПожалуйста, выберите локацию в Варне.",
        
        # === ПОИСК ===
        "search_type_question": "🏢 *Что вы ищете?*",
        "search_location_question": "📍 *Где ищете?*\n\nОтправьте геолокацию или адрес:",
        "search_location_sent": "✅ Локация сохранена",
        "search_radius_question": "📏 *Радиус поиска*\n\nВыберите расстояние от вашей локации:",
        "search_radius_1km": "📍 1 км",
        "search_radius_3km": "📍 3 км",
        "search_radius_5km": "📍 5 км",
        "search_radius_10km": "📍 10 км",
        "search_radius_all": "🌍 Вся Варна",
        "search_results_found": "🔍 Найдено *{count}* объявлений · радиус: {radius}",
        "search_no_results": "😔 Не найдено объявлений с этими критериями.\n\nПопробуйте:\n• Увеличить радиус\n• Изменить местоположение\n• Проверить другие критерии",
        "search_page_info": "📄 Страница {page} из {total} (всего {count} объявлений)",
        "search_subscribe_btn": "🔔 Подписка на уведомления",
        "search_change_radius_btn": "📏 Изменить радиус",
        
        # === ИЗБРАННОЕ ===
        "favorites_empty": "⭐ У вас пока нет избранных объявлений.\n\nДобавляйте объявления в избранное, чтобы не потерять их!",
        "favorites_title": "⭐ *Избранное* ({count} объявлений)",
        "favorites_added": "✅ Добавлено в избранное!",
        "favorites_removed": "💔 Удалено из избранного",
        "favorites_add_btn": "⭐ В избранное",
        "favorites_remove_btn": "💔 Удалить из избранного",
        
        # === МОИ ОБЪЯВЛЕНИЯ ===
        "my_listings_empty": "У вас пока нет объявлений.",
        "my_listings_title": "📁 *Ваши объявления* ({count})",
        "my_listings_status_active": "✅ Активно",
        "my_listings_status_inactive": "⏸ Неактивно",
        "my_listing_deleted": "🗑 Объявление удалено",
        "my_listing_confirm_delete": "❓ Вы уверены, что хотите удалить это объявление?",
        
        # === ПОДПИСКИ ===
        "subscriptions_title": "🔔 *Подписки на уведомления*",
        "subscriptions_empty": "У вас нет активных подписок.",
        "subscription_offer": "🔔 *Хотите получать уведомления?*\n\nКогда появится новое объявление, соответствующее вашим критериям, вы получите сообщение.\n\n💰 Цена: 100 Telegram Stars (≈ 2 €)\n📅 Срок: 30 дней",
        "subscription_created": "✅ *Подписка активирована!*\n\nВы будете получать уведомления о новых объявлениях, соответствующих вашим критериям.\nДействует до: {expires}",
        "subscription_exists": "ℹ️ У вас уже есть активная подписка с этими параметрами!",
        "subscription_payment_sent": "💳 *Отправлено уведомление об оплате.*\n\nНажмите для оплаты через Telegram Stars.",
        "subscription_admin_free": "✅ *Подписка активирована!* (бесплатно для администратора)\n\nВы будете получать уведомления о новых объявлениях, соответствующих вашим критериям.\nДействует до: {expires}",
        
        # === УВЕДОМЛЕНИЯ ===
        "notification_new_listing": "🆕 *Новое объявление* соответствует вашим критериям!\n\n{action} · {type}\nРадиус: {radius}",
        "notification_listing_updated": "✏️ *Обновлено объявление* в вашем избранном:\n\n*Изменения:*\n{changes}",
        
        # === ДЕТАЛИ ОБЪЯВЛЕНИЯ ===
        "listing_detail_header": "{emoji} {type} {action}",
        "listing_address": "📍 Адрес:",
        "listing_price": "💰 Цена:",
        "listing_phone": "📞 Телефон:",
        "listing_description": "📝 Описание:",
        "listing_distance": "📏 Расстояние:",
        "listing_views": "👁 Просмотры:",
        "listing_created": "📅 Опубликовано:",
        "listing_owner_note": "Это ваше объявление!",
        "listing_text_sell_parking": "💰 *Парковочное место на продажу*",
        "listing_text_sell_garage": "💰 *Гараж на продажу*",
        "listing_text_lease_parking": "📋 *Парковочное место сдаётся*",
        "listing_text_lease_garage": "📋 *Гараж сдаётся*",
        "listing_text_buy_parking": "🛒 *Ищу парковочное место*",
        "listing_text_buy_garage": "🛒 *Ищу гараж*",
        "listing_text_rent_parking": "🔑 *Ищу парковку в аренду*",
        "listing_text_rent_garage": "🔑 *Ищу гараж в аренду*",
        
        # === РЕДАКТИРОВАНИЕ ===
        "edit_choose_field": "✏️ *Редактирование объявления*\n\nВыберите что хотите изменить:",
        "edit_field_address": "Адрес",
        "edit_field_price": "Цена",
        "edit_field_description": "Описание",
        "edit_field_phone": "Телефон",
        "edit_saved": "✅ Изменения сохранены!",
        
        # === ПОМОЩЬ ===
        "help_text": "❓ *Помощь - ParkPlace Varna*\n\n"
                     "🛒 *Купить / Аренда* — поиск объекта\n"
                     "💰 *Продать / Сдать* — публикация объявления\n\n"
                     "📁 *Мои объявления* — ваши публикации\n"
                     "⭐ *Избранное* — сохранённые объявления\n"
                     "🔔 *Подписки* — уведомления о новых объявлениях\n\n"
                     "🗺 Радиус поиска: максимум 50 км от центра Варны\n"
                     "📸 Можно загрузить до 5 фото на объявление\n"
                     "⏰ Объявления подтверждаются до 24 часов\n\n"
                     "По вопросам: @admin",
        
        # === АДМИН ===
        "admin_panel": "👨‍💼 *Админ панель*\n\n"
                       "Выберите действие:",
        "admin_btn_broadcast": "📢 Рассылка",
        "admin_btn_stats": "📊 Статистика",
        "admin_broadcast_question": "📢 *Рассылка сообщения*\n\nВведите текст который хотите отправить всем пользователям:",
        "admin_broadcast_confirm": "Отправить {count} пользователям?",
        "admin_broadcast_sent": "✅ Отправлено {count} пользователям",
        "admin_broadcast_cancelled": "❌ Рассылка отменена",
        
        # === КОНТАКТЫ ===
        "contact_send_message": "✉️ Напишите сообщение владельцу:",
        "contact_message_sent": "✅ Сообщение отправлено!",
        "contact_own_listing": "Это ваше объявление!",
        
        # === ОШИБКИ ===
        "error_general": "❌ Ошибка. Пожалуйста попробуйте снова.",
        "error_invalid_price": "❌ Неверная цена.\n\nВведите число (например: 5000)",
        "error_invalid_phone": "❌ Неверный телефонный номер.\n\nФормат: +359XXXXXXXXX",
        "error_description_too_long": "❌ Описание слишком длинное ({length}/500 символов)",
        "error_photo_upload": "❌ Ошибка загрузки фото. Попробуйте снова.",
        "error_location_failed": "❌ Не удалось определить адрес по этим координатам.",
        "error_payment_failed": "❌ Ошибка создания платежа. Пожалуйста попробуйте снова.",
        
        # === РАЗНОЕ ===
        "distance_km": "{distance} км",
        "distance_m": "{distance} м",
        "price_eur": "{price} €",
        "date_format": "{date}",
        "confirmation_pending": "⏳ Ожидает подтверждения",
        "all_results_shown": "✅ Все результаты показаны.",
        
        # === ЯЗЫК ===
        "language_choose": "🌐 *Език / Язык*\n\nВыберите язык:",
        "language_current": "Выбранный язык: {language}",
        "language_changed": "✅ Язык изменён на русский",
        "language_bg": "🇧🇬 Български",
        "language_ru": "🇷🇺 Русский",
    }
}

# Функция перевода
def t(key: str, lang: str = "bg", **kwargs) -> str:
    """
    Получить перевод по ключу.
    
    Args:
        key: Ключ сообщения
        lang: Язык ('bg' или 'ru')
        **kwargs: Параметры для форматирования
    
    Returns:
        Переведённый текст
    """
    text = LANG.get(lang, LANG["bg"]).get(key, key)
    
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    
    return text


# Определение языка пользователя
def get_user_lang(user_id: int, ctx=None) -> str:
    """
    Определяет язык пользователя.
    
    Приоритет:
    1. Из ctx.user_data (кэш)
    2. Из БД
    3. По умолчанию 'bg'
    """
    # 1. Из кэша
    if ctx and "lang" in ctx.user_data:
        return ctx.user_data["lang"]
    
    # 2. Из БД
    try:
        conn = db()
        result = conn.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        
        if result and result["language"]:
            lang = result["language"]
            if ctx:
                ctx.user_data["lang"] = lang  # Кэшируем
            return lang
    except Exception:
        pass
    
    # 3. По умолчанию
    return "bg"


# Сохранить язык
def set_user_lang(user_id: int, lang: str, ctx=None):
    """Сохраняет выбранный язык пользователя."""
    try:
        conn = db()
        # Создаём или обновляем запись
        conn.execute("""
            INSERT INTO users (user_id, language) 
            VALUES (?, ?) 
            ON CONFLICT(user_id) DO UPDATE SET language=?
        """, (user_id, lang, lang))
        conn.commit()
        conn.close()
        
        # Кэшируем
        if ctx:
            ctx.user_data["lang"] = lang
    except Exception as e:
        print(f"Error saving language: {e}")


# Определить язык из Telegram
def detect_telegram_lang(update) -> str:
    """
    Определяет язык из Telegram профиля пользователя.
    
    Returns:
        'ru' если язык русский, иначе 'bg'
    """
    try:
        telegram_lang = update.effective_user.language_code
        if telegram_lang and telegram_lang.startswith('ru'):
            return 'ru'
    except Exception:
        pass
    
    return 'bg'
