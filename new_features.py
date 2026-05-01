# Новые функции для добавления в bot.py

# ========== ИЗБРАННОЕ ==========

async def show_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать избранное пользователя."""
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
    else:
        user_id = update.effective_user.id
    
    conn = db()
    favorites = conn.execute("""
        SELECT l.* FROM listings l
        JOIN favorites f ON l.id = f.listing_id
        WHERE f.user_id = ? AND l.active = 1
        ORDER BY f.created_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    
    if not favorites:
        text = "⭐ У вас пока нет избранных объявлений.\n\nДобавляйте объявления в избранное чтобы не потерять их!"
        if query:
            await query.edit_message_text(text, reply_markup=home_ikb())
        else:
            await update.message.reply_text(text, reply_markup=home_ikb())
        return MAIN_MENU
    
    text = f"⭐ *Избранное* ({len(favorites)} объявл.)"
    if query:
        await query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    
    for row in favorites:
        lid = row[0]
        caption = listing_text(row)
        
        # Кнопки: удалить из избранного + карта
        buttons = [
            [InlineKeyboardButton("💔 Удалить из избранного", callback_data=f"unfav_{lid}")],
            [InlineKeyboardButton("🗺 На карте", callback_data=f"map_{lid}")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        
        if row[11]:  # photo_id
            await (query.message if query else update.message).reply_photo(
                row[11], caption=caption, parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            await (query.message if query else update.message).reply_text(
                caption, parse_mode="Markdown", reply_markup=keyboard
            )
    
    return MAIN_MENU


async def toggle_favorite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Добавить/удалить из избранного."""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    action = data_parts[0]  # fav или unfav
    lid = int(data_parts[1])
    user_id = query.from_user.id
    
    conn = db()
    
    if action == "fav":
        # Добавить в избранное
        try:
            conn.execute("INSERT INTO favorites (user_id, listing_id) VALUES (?, ?)", (user_id, lid))
            conn.commit()
            await query.answer("⭐ Добавлено в избранное!", show_alert=True)
        except:
            await query.answer("Уже в избранном", show_alert=True)
    else:
        # Удалить из избранного
        conn.execute("DELETE FROM favorites WHERE user_id=? AND listing_id=?", (user_id, lid))
        conn.commit()
        await query.answer("💔 Удалено из избранного", show_alert=True)
        
        # Удаляем сообщение если просматриваем избранное
        try:
            await query.message.delete()
        except:
            pass
    
    conn.close()
    return MAIN_MENU


# ========== РЕДАКТИРОВАНИЕ ОБЪЯВЛЕНИЙ ==========

async def edit_listing_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Меню редактирования объявления."""
    query = update.callback_query
    await query.answer()
    
    lid = int(query.data.split("_")[1])
    user_id = query.from_user.id
    
    conn = db()
    listing = conn.execute("SELECT * FROM listings WHERE id=? AND owner_id=?", (lid, user_id)).fetchone()
    conn.close()
    
    if not listing:
        await query.answer("Объявление не найдено", show_alert=True)
        return MAIN_MENU
    
    ctx.user_data["edit_listing_id"] = lid
    
    caption = listing_text(listing)
    buttons = [
        [InlineKeyboardButton("✏️ Изменить цену", callback_data=f"editprice_{lid}")],
        [InlineKeyboardButton("✏️ Изменить описание", callback_data=f"editdesc_{lid}")],
        [InlineKeyboardButton("✏️ Изменить фото", callback_data=f"editphoto_{lid}")],
        [InlineKeyboardButton("🏠 На главную", callback_data="go_home")],
    ]
    
    await query.edit_message_text(
        f"*Редактирование объявления:*\n\n{caption}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return MAIN_MENU


# ========== ПОДТВЕРЖДЕНИЕ АКТУАЛЬНОСТИ ==========

async def send_confirmation_requests():
    """Отправка запросов на подтверждение актуальности (вызывается по расписанию)."""
    import datetime
    
    conn = db()
    # Объявления старше 7 дней без подтверждения
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    
    listings = conn.execute("""
        SELECT id, owner_id, owner_name FROM listings
        WHERE active=1 AND confirmed_at < ?
    """, (cutoff,)).fetchall()
    
    for lid, owner_id, owner_name in listings:
        # Отметить что запрос отправлен
        conn.execute("""
            UPDATE listings SET confirmed_at = datetime('now', '+48 hours')
            WHERE id = ?
        """, (lid,))
    
    conn.commit()
    conn.close()
    
    # TODO: Отправка уведомлений владельцам
    # Нужен доступ к bot instance


# ========== АВТОУДАЛЕНИЕ ==========

async def auto_delete_expired():
    """Автоудаление неподтверждённых объявлений (вызывается по расписанию)."""
    import datetime
    
    conn = db()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Удалить объявления где confirmed_at прошёл и не подтверждено
    deleted = conn.execute("""
        DELETE FROM listings
        WHERE active=1 AND confirmed_at < ?
        RETURNING id
    """, (now,))
    
    count = len(deleted.fetchall())
    conn.commit()
    conn.close()
    
    return count


# ========== КОМАНДЫ ==========

async def cmd_my(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /my - мои объявления."""
    ctx.user_data["action"] = "mylistings"
    return await start_action(update, ctx)


async def cmd_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /favorites - избранное."""
    return await show_favorites(update, ctx)


async def cmd_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /subscriptions - подписки."""
    ctx.user_data["action"] = "subscriptions"
    return await start_action(update, ctx)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /help - помощь."""
    help_text = """
*ParkRent Varna — поиск парковок и гаражей*

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
"""
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=home_ikb())
    return MAIN_MENU
