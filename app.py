import os
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ---------- تنظیمات ----------
TOKEN = "8930850659:AAHPa6kZCIctxoqK6B2m6f6B9Xpdz_kPZ4k"
ADMIN_IDS = [6747512673]  # لیست آیدی ادمین‌ها (می‌تونی بیشتر هم اضافه کنی)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- دیتابیس ----------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        role TEXT DEFAULT 'user',
        is_blocked INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER,
        to_user_id INTEGER,
        message_text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# ---------- توابع کمکی دیتابیس ----------
def add_user(user_id, first_name, username, role='user'):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, first_name, username, role) VALUES (?, ?, ?, ?)",
        (user_id, first_name, username, role)
    )
    conn.commit()

def get_user_role(user_id):
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 'user'

def is_user_blocked(user_id):
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row is not None and row[0] == 1

def block_user(user_id):
    cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def save_message(from_user_id, to_user_id, text):
    cursor.execute(
        "INSERT INTO messages (from_user_id, to_user_id, message_text) VALUES (?, ?, ?)",
        (from_user_id, to_user_id, text)
    )
    conn.commit()

def get_recent_messages(limit=20):
    cursor.execute(
        "SELECT from_user_id, to_user_id, message_text, created_at FROM messages ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    return cursor.fetchall()

def get_user_info(user_id):
    cursor.execute("SELECT first_name, username FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        return row[0], row[1]
    return "نامشخص", "ندارد"

# ---------- هندلر استارت ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or ""
    username = user.username or ""

    # تعیین نقش (ادمین یا کاربر عادی)
    role = 'admin' if user_id in ADMIN_IDS else 'user'
    add_user(user_id, first_name, username, role)

    # بررسی پارامتر start (لینک اختصاصی)
    args = context.args
    if args:
        try:
            target_id = int(args[0])
            if target_id != user_id:  # جلوگیری از ارسال به خود
                context.user_data['target_user_id'] = target_id
                await update.message.reply_text(
                    f"🔹 شما در حال ارسال پیام ناشناس به کاربری با آیدی `{target_id}` هستید.\n"
                    "📝 پیام خود را بفرستید."
                )
                return
        except ValueError:
            pass  # اگر پارامتر عدد نبود، نادیده بگیر

    # اگر کاربر ادمین است، پنل مدیریت رو نشون بده
    if role == 'admin':
        keyboard = [
            [InlineKeyboardButton("📋 مشاهده لاگ پیام‌ها", callback_data="view_log")],
            [InlineKeyboardButton("📊 آمار کاربران", callback_data="stats")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👋 **سلام ادمین! به پنل مدیریت خوش آمدی.**\n\n"
            "از دکمه‌های زیر استفاده کن:",
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )
    else:
        # کاربر عادی
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user_id}"
        await update.message.reply_text(
            f"👋 سلام {first_name}!\n\n"
            f"🔗 **لینک اختصاصی شما:**\n{link}\n\n"
            "با ارسال این لینک به دیگران، آن‌ها می‌توانند **به شما** پیام ناشناس بفرستند.\n"
            "برای ارسال پیام به ادمین، همین‌طور مستقیم پیام خود را بفرستید.",
            parse_mode="MarkdownV2"
        )

# ---------- هندلر دریافت پیام از کاربران ----------
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text

    if is_user_blocked(user_id):
        await update.message.reply_text("⛔ شما بلاک شده‌اید.")
        return

    # اگر کاربر در حالت ارسال به یک target خاص است (از طریق لینک اختصاصی)
    target_id = context.user_data.get('target_user_id')
    if target_id:
        # ذخیره پیام در دیتابیس
        save_message(user_id, target_id, text)
        try:
            # ارسال پیام به کاربر هدف
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📩 **پیام ناشناس از طرف یک کاربر:**\n\n{text}",
                parse_mode="MarkdownV2"
            )
            await update.message.reply_text("✅ پیام شما با موفقیت ارسال شد.")
        except Exception as e:
            logger.error(f"Error sending to {target_id}: {e}")
            await update.message.reply_text("❌ خطا در ارسال پیام. ممکن است کاربر ربات را بلاک کرده باشد.")
        # پاک کردن target بعد از ارسال
        context.user_data.pop('target_user_id', None)
        return

    # در غیر این صورت، پیام به ادمین اصلی فرستاده می‌شود
    admin_id = ADMIN_IDS[0]  # اولین ادمین در لیست
    save_message(user_id, admin_id, text)

    # گرفتن اطلاعات کاربر فرستنده
    first_name = user.first_name or "ندارد"
    username = user.username or "ندارد"
    
    log_msg = (
        f"📩 **پیام جدید از طرف کاربر:**\n"
        f"👤 نام: {first_name}\n"
        f"🆔 آیدی: `{user_id}`\n"
        f"📛 یوزرنیم: @{username}\n\n"
        f"📝 متن:\n{text}"
    )
    
    keyboard = [
        [InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{user_id}")],
        [InlineKeyboardButton("🚫 بلاک", callback_data=f"block_{user_id}")]
    ]
    
    await context.bot.send_message(
        chat_id=admin_id,
        text=log_msg,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✅ پیام شما برای ادمین ارسال شد.")

# ---------- هندلر دکمه‌های اینلاین ----------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ شما دسترسی به این بخش را ندارید.")
        return

    data = query.data

    if data == "view_log":
        messages = get_recent_messages(20)
        if not messages:
            await query.edit_message_text("📭 هیچ پیامی یافت نشد.")
            return
        
        text = "📋 **لاگ پیام‌های اخیر:**\n\n"
        for from_id, to_id, msg, created in messages:
            from_name, _ = get_user_info(from_id)
            to_name, _ = get_user_info(to_id)
            text += f"🆔 **از** {from_name} (`{from_id}`) **به** {to_name} (`{to_id}`):\n\"{msg[:40]}{'...' if len(msg)>40 else ''}\"\n\n"
        
        await query.edit_message_text(text, parse_mode="MarkdownV2")

    elif data == "stats":
        cursor.execute("SELECT COUNT(*) FROM users WHERE role='user'")
        users_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages")
        messages_count = cursor.fetchone()[0]
        await query.edit_message_text(
            f"📊 **آمار کلی:**\n\n"
            f"👥 تعداد کاربران عادی: {users_count}\n"
            f"💬 تعداد کل پیام‌ها: {messages_count}",
            parse_mode="MarkdownV2"
        )

    elif data.startswith("reply_"):
        target_id = int(data.split("_")[1])
        context.user_data['reply_to_user'] = target_id
        context.user_data['waiting_for_reply'] = True
        await query.edit_message_text(
            f"✉️ پاسخ خود را برای کاربر با آیدی `{target_id}` تایپ کنید.\n(برای لغو، دستور /cancel را بفرستید.)",
            parse_mode="MarkdownV2"
        )

    elif data.startswith("block_"):
        target_id = int(data.split("_")[1])
        block_user(target_id)
        await query.edit_message_text(f"✅ کاربر با آیدی `{target_id}` با موفقیت بلاک شد.", parse_mode="MarkdownV2")

# ---------- هندلر پاسخ ادمین ----------
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    if not context.user_data.get('waiting_for_reply'):
        return
    
    target_id = context.user_data.get('reply_to_user')
    if not target_id:
        await update.message.reply_text("❌ خطا: کاربر مقصد یافت نشد.")
        context.user_data['waiting_for_reply'] = False
        return
    
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"📩 **پاسخ ادمین:**\n\n{update.message.text}",
            parse_mode="MarkdownV2"
        )
        await update.message.reply_text("✅ پیام شما با موفقیت ارسال شد.")
    except Exception as e:
        logger.error(f"Error sending reply: {e}")
        await update.message.reply_text("❌ خطا در ارسال پیام. ممکن است کاربر ربات را بلاک کرده باشد.")
    
    context.user_data['waiting_for_reply'] = False
    context.user_data['reply_to_user'] = None

# ---------- هندلر لغو پاسخ ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    if context.user_data.get('waiting_for_reply'):
        context.user_data['waiting_for_reply'] = False
        context.user_data['reply_to_user'] = None
        await update.message.reply_text("✅ حالت پاسخگویی لغو شد.")
    else:
        await update.message.reply_text("⚠️ شما در حالت پاسخگویی نیستید.")

# ---------- تابع اصلی ----------
def main():
    logger.info("🚀 ربات در حال اجراست...")
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_IDS[0]), handle_admin_reply))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
