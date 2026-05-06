# messages.py - Минимальная локализация

import sqlite3
import os

DATA_DIR = os.environ.get("DATA_DIR", "./data")
DB_FILE = os.path.join(DATA_DIR, "parking.db")

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

LANG = {
    "bg": {
        "welcome": "🚗 *ParkPlace Varna*\nКакво искате да направите?",
        "btn_home": "🏠 Начало",
    },
    "ru": {
        "welcome": "🚗 *ParkPlace Varna*\nЧто вы хотите сделать?",
        "btn_home": "🏠 Главная",
    }
}

def t(key, lang='bg', **kwargs):
    text = LANG.get(lang, LANG['bg']).get(key, key)
    return text.format(**kwargs) if kwargs else text

def get_user_lang(user_id, ctx=None):
    if ctx and "lang" in ctx.user_data:
        return ctx.user_data["lang"]
    try:
        conn = db()
        result = conn.execute("SELECT language FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        if result:
            lang = result["language"]
            if ctx:
                ctx.user_data["lang"] = lang
            return lang
    except:
        pass
    return "bg"

def set_user_lang(user_id, lang, ctx=None):
    try:
        conn = db()
        conn.execute("INSERT INTO users (user_id, language) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET language=?", (user_id, lang, lang))
        conn.commit()
        conn.close()
        if ctx:
            ctx.user_data["lang"] = lang
    except Exception as e:
        print(f"Error: {e}")

def detect_telegram_lang(update):
    try:
        if hasattr(update.effective_user, 'language_code'):
            if update.effective_user.language_code.lower().startswith('ru'):
                return 'ru'
    except:
        pass
    return 'bg'
