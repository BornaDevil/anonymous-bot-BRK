import os
import logging
import sqlite3
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ---------- CONFIGURATION ----------
TOKEN = "8930850659:AAHPa6kZCIctxoqK6B2m6f6B9Xpdz_kPZ4k"
ADMIN_ID = 6747512673

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- DATABASE SETUP ----------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        is_blocked INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER,
        to_admin_id INTEGER,
        message_text TEXT,
        message_type TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# ---------- DATABASE HELPER FUNCTIONS ----------
def add_user(user_id, first_name, username):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
        (user_id, first_name, username)
    )
    conn.commit()

def save_message(from_user_id, to_admin_id, message_text, message_type="text"):
    cursor.execute(
        "INSERT INTO messages (from_user_id, to_admin_id, message_text, message_type) VALUES (?, ?, ?, ?)",
        (from_user_id, to_admin_id, message_text, message_type)
    )
    conn.commit()

def is_user_blocked(user_id):
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result is not None and result[0] == 1

def block_user(user_id):
    cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
    conn.commit()

# ---------- BOT HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.first_name or "", user.username or "")
    await update.message.reply_text(
        "👋 Hello! This is an anonymous messaging bot.\n"
        "Send any message and it will be forwarded to the admin."
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_blocked(user.id):
        await update.message.reply_text("⛔ You have been blocked.")
        return

    add_user(user.id, user.first_name or "", user.username or "")
    save_message(user.id, ADMIN_ID, update.message.text)

    log_message = (
        f"📩 **New message from:**\n"
        f"👤 Name: {user.first_name or 'N/A'}\n"
        f"🆔 ID: `{user.id}`\n"
        f"📛 Username: @{user.username if user.username else 'N/A'}\n\n"
        f"📝 Text:\n{update.message.text}"
    )
    
    keyboard = [
        [InlineKeyboardButton("✉️ Reply", callback_data=f"reply_{user.id}")],
        [InlineKeyboardButton("🚫 Block", callback_data=f"block_{user.id}")]
    ]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=log_message,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✅ Your message has been sent.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ You don't have permission.")
        return

    data = query.data
    
    if data.startswith("reply_"):
        user_id = int(data.split("_")[1])
        context.user_data['reply_to_user'] = user_id
        context.user_data['waiting_for_reply'] = True
        await query.edit_message_text(
            f"✉️ Type your reply for user {user_id}. (Cancel: /cancel)"
        )
    elif data.startswith("block_"):
        user_id = int(data.split("_")[1])
        block_user(user_id)
        await query.edit_message_text(f"✅ User {user_id} has been blocked.")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not context.user_data.get('waiting_for_reply'):
        return
    
    target_id = context.user_data.get('reply_to_user')
    if not target_id:
        await update.message.reply_text("❌ Error: No target user found.")
        context.user_data['waiting_for_reply'] = False
        return
    
    try:
        await context.bot.send_message(
            target_id,
            f"📩 Admin response:\n\n{update.message.text}"
        )
        await update.message.reply_text("✅ Message sent successfully.")
    except Exception as e:
        logger.error(f"Error sending reply: {e}")
        await update.message.reply_text("❌ Failed to send message. User may have blocked the bot.")
    
    context.user_data['waiting_for_reply'] = False
    context.user_data['reply_to_user'] = None

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if context.user_data.get('waiting_for_reply'):
        context.user_data['waiting_for_reply'] = False
        context.user_data['reply_to_user'] = None
        await update.message.reply_text("✅ Reply mode cancelled.")
    else:
        await update.message.reply_text("⚠️ You are not in reply mode.")

# ---------- FLASK WEB SERVER ----------
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ---------- BOT STARTER ----------
def run_bot():
    logger.info("🚀 Starting bot thread...")
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID),
            handle_admin_reply
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_user_message
        )
    )
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# ---------- MAIN ----------
if __name__ == '__main__':
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
