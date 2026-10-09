"""
بات تلگرام FAQ با پنل ادمین (بدون مدل زبانی)

قابلیت‌های ادمین (با دستور /admin):
  - مشاهده، افزودن، ویرایش و حذف سؤال‌ها (بدون دست زدن به کد)
  - ارسال پیام همگانی به همه‌ی کاربران
  - آمار کاربران

نصب:
    pip install "python-telegram-bot>=21"

داده‌ها (سؤال‌ها و لیست کاربران) توی فایل data.json کنار همین فایل ذخیره می‌شن.
"""

import asyncio
import copy
import json
import logging
import os
import re
import uuid
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ----------------------------------------------------------------------
# تنظیمات
# ----------------------------------------------------------------------
TOKEN = '' or "PUT_TELEGRAM_TOKEN_HERE"

# آیدی عددی ادمین‌ها. برای فهمیدن آیدی خودت، به بات /myid بفرست و عدد رو اینجا بذار.
# مثال: ADMIN_IDS = {123456789, 987654321}
ADMIN_IDS = set = {}

# اگه برای وصل شدن به تلگرام پروکسی لازم داری. مثال: "http://127.0.0.1:10809"
PROXY = ""

DATA_FILE = Path(__file__).with_name("data.json")

WELCOME = "سلام! 👋\nبه بات پشتیبانی خوش اومدی. یکی از گزینه‌ها رو انتخاب کن:"
NOT_FOUND = "متأسفانه جوابی برای این سؤال پیدا نکردم 🤔\nاز منوی زیر یکی از گزینه‌ها رو انتخاب کن:"

# سؤال‌های اولیه (فقط بار اول که data.json وجود نداره استفاده می‌شن)
DEFAULT_DATA = {
    "faq": {
        "hours": {
            "title": "🕘 ساعات کاری",
            "answer": "ساعات کاری ما شنبه تا چهارشنبه، ۹ صبح تا ۵ عصره.",
            "keywords": ["ساعت", "کاری", "باز", "تعطیل"],
        },
        "price": {
            "title": "💰 قیمت‌ها",
            "answer": "برای دیدن لیست قیمت‌ها به وب‌سایت ما سر بزن یا با پشتیبانی تماس بگیر.",
            "keywords": ["قیمت", "هزینه", "تعرفه", "چند"],
        },
        "shipping": {
            "title": "🚚 ارسال و تحویل",
            "answer": "سفارش‌ها معمولاً ظرف ۳ تا ۵ روز کاری تحویل داده می‌شن.",
            "keywords": ["ارسال", "تحویل", "پست", "سفارش"],
        },
        "contact": {
            "title": "📞 تماس با ما",
            "answer": "ایمیل: info@example.com\nتلفن: ۰۲۱-۱۲۳۴۵۶۷۸",
            "keywords": ["تماس", "تلفن", "شماره", "ایمیل", "آدرس"],
        },
    },
    "users": [],
}

FIELD_NAMES = {"title": "عنوان دکمه", "answer": "متن جواب", "keywords": "کلمات کلیدی"}


# ----------------------------------------------------------------------
# ذخیره و بارگذاری داده‌ها
# ----------------------------------------------------------------------
def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = DATA_FILE.with_suffix(".json.bak")
            DATA_FILE.replace(backup)
            logging.error("data.json خراب بود؛ نسخه‌ی قبلی در %s نگهداری شد.", backup)
    return copy.deepcopy(DEFAULT_DATA)


DATA = load_data()


def save_data() -> None:
    DATA_FILE.write_text(
        json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ----------------------------------------------------------------------
# توابع کمکی
# ----------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def normalize(text: str) -> str:
    return text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").strip().lower()


def parse_keywords(text: str) -> list:
    return [k.strip() for k in re.split(r"[,،\n]+", text) if k.strip()]


def register_user(update: Update) -> None:
    chat = update.effective_chat
    if chat and chat.type == "private" and chat.id not in DATA["users"]:
        DATA["users"].append(chat.id)
        save_data()


def find_answer(text: str):
    text = normalize(text)
    for item in DATA["faq"].values():
        if any(normalize(k) in text for k in item["keywords"]):
            return item
    return None


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(item["title"], callback_data=f"faq:{key}")]
        for key, item in DATA["faq"].items()
    ]
    return InlineKeyboardMarkup(rows)


def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu")]]
    )


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [btn("📋 مدیریت سؤال‌ها", "adm:list")],
            [btn("➕ افزودن سؤال", "adm:add")],
            [btn("📢 پیام همگانی", "adm:bc")],
            [btn("📊 آمار", "adm:stats")],
        ]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("❌ انصراف", "adm:cancel")]])


ADMIN_TITLE = "🛠 پنل ادمین\nیکی از گزینه‌ها رو انتخاب کن:"


# ----------------------------------------------------------------------
# هندلرهای کاربر عادی
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    await update.message.reply_text(WELCOME, reply_markup=main_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    await update.message.reply_text(
        "با /start منوی اصلی رو ببین، یا سؤالت رو بنویس تا دنبال جواب بگردم.",
        reply_markup=main_menu(),
    )


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"آیدی عددی تو: {update.effective_user.id}")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "menu":
        await query.edit_message_text(WELCOME, reply_markup=main_menu())
        return

    item = DATA["faq"].get(query.data.split(":", 1)[1])
    if item:
        await query.edit_message_text(
            f"{item['title']}\n\n{item['answer']}", reply_markup=back_button()
        )
    else:
        await query.edit_message_text(
            "این گزینه دیگه موجود نیست.", reply_markup=back_button()
        )


# ----------------------------------------------------------------------
# پنل ادمین
# ----------------------------------------------------------------------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ADMIN_IDS:
        await update.message.reply_text(
            "هنوز هیچ ادمینی تنظیم نشده. /myid رو بزن و آیدی‌ات رو توی ADMIN_IDS بذار."
        )
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("دسترسی نداری.")
        return
    context.user_data.pop("pending", None)
    await update.message.reply_text(ADMIN_TITLE, reply_markup=admin_menu())


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.pop("pending", None) and is_admin(update.effective_user.id):
        await update.message.reply_text("لغو شد.", reply_markup=admin_menu())


def item_text(item: dict) -> str:
    return (
        f"عنوان: {item['title']}\n\n"
        f"جواب:\n{item['answer']}\n\n"
        f"کلمات کلیدی: {'، '.join(item['keywords']) or '—'}"
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("دسترسی نداری.", show_alert=True)
        return
    await query.answer()

    parts = query.data.split(":")
    action = parts[1]
    context.user_data.pop("pending", None)
    edit = query.edit_message_text

    if action in ("menu", "cancel"):
        await edit(ADMIN_TITLE, reply_markup=admin_menu())

    elif action == "list":
        rows = [[btn(i["title"], f"adm:item:{k}")] for k, i in DATA["faq"].items()]
        rows.append([btn("🔙 بازگشت", "adm:menu")])
        text = "سؤالی رو برای ویرایش یا حذف انتخاب کن:" if DATA["faq"] else "هنوز سؤالی نداری."
        await edit(text, reply_markup=InlineKeyboardMarkup(rows))

    elif action == "item":
        key = parts[2]
        item = DATA["faq"].get(key)
        if not item:
            await edit("این سؤال پیدا نشد.", reply_markup=admin_menu())
            return
        kb = InlineKeyboardMarkup(
            [
                [btn("✏️ عنوان", f"adm:edit:{key}:title"), btn("✏️ جواب", f"adm:edit:{key}:answer")],
                [btn("✏️ کلمات کلیدی", f"adm:edit:{key}:keywords")],
                [btn("🗑 حذف", f"adm:del:{key}")],
                [btn("🔙 بازگشت", "adm:list")],
            ]
        )
        await edit(item_text(item), reply_markup=kb)

    elif action == "edit":
        key, field = parts[2], parts[3]
        context.user_data["pending"] = {"type": "edit", "key": key, "field": field}
        hint = "\n(کلمات رو با ویرگول جدا کن)" if field == "keywords" else ""
        await edit(f"{FIELD_NAMES[field]} جدید رو بفرست:{hint}", reply_markup=cancel_kb())

    elif action == "del":
        key = parts[2]
        kb = InlineKeyboardMarkup(
            [[btn("✅ بله، حذف کن", f"adm:delok:{key}"), btn("❌ نه", f"adm:item:{key}")]]
        )
        await edit("مطمئنی که می‌خوای این سؤال حذف بشه؟", reply_markup=kb)

    elif action == "delok":
        DATA["faq"].pop(parts[2], None)
        save_data()
        await edit("🗑 حذف شد.", reply_markup=admin_menu())

    elif action == "add":
        context.user_data["pending"] = {"type": "add", "step": "title", "data": {}}
        await edit("عنوان دکمه رو بفرست (مثلاً: 💳 روش‌های پرداخت):", reply_markup=cancel_kb())

    elif action == "bc":
        context.user_data["pending"] = {"type": "broadcast"}
        await edit("متن پیام همگانی رو بفرست:", reply_markup=cancel_kb())

    elif action == "bcok":
        text = context.user_data.pop("bc_text", None)
        if not text:
            await edit("پیامی برای ارسال نیست.", reply_markup=admin_menu())
            return
        await edit("⏳ در حال ارسال... وقتی تموم شد خبرت می‌کنم.")
        context.application.create_task(
            run_broadcast(context, query.message.chat_id, text)
        )

    elif action == "stats":
        kb = InlineKeyboardMarkup([[btn("🔙 بازگشت", "adm:menu")]])
        await edit(
            f"📊 آمار\n\nکاربران: {len(DATA['users'])}\nسؤال‌ها: {len(DATA['faq'])}",
            reply_markup=kb,
        )


async def run_broadcast(context: ContextTypes.DEFAULT_TYPE, admin_chat: int, text: str) -> None:
    sent = failed = 0
    for uid in list(DATA["users"]):
        try:
            await context.bot.send_message(uid, text)
            sent += 1
        except Forbidden:            # کاربر بات رو بلاک کرده
            DATA["users"].remove(uid)
            failed += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(0.05)    # رعایت محدودیت سرعت تلگرام
    save_data()
    await context.bot.send_message(
        admin_chat,
        f"✅ ارسال تموم شد.\nموفق: {sent}\nناموفق: {failed}",
        reply_markup=admin_menu(),
    )


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE, pending: dict) -> None:
    text = update.message.text.strip()
    reply = update.message.reply_text

    if pending["type"] == "add":
        step = pending["step"]
        if step == "title":
            pending["data"]["title"] = text
            pending["step"] = "answer"
            await reply("متن جواب رو بفرست:", reply_markup=cancel_kb())
        elif step == "answer":
            pending["data"]["answer"] = text
            pending["step"] = "keywords"
            await reply(
                "کلمات کلیدی رو با ویرگول جدا کن (برای تشخیص سؤال‌هایی که کاربر تایپ می‌کنه).\n"
                "مثال: پرداخت، خرید، کارت",
                reply_markup=cancel_kb(),
            )
        else:
            data = pending["data"]
            data["keywords"] = parse_keywords(text)
            DATA["faq"][uuid.uuid4().hex[:8]] = data
            save_data()
            context.user_data.pop("pending", None)
            await reply("✅ سؤال اضافه شد.", reply_markup=admin_menu())

    elif pending["type"] == "edit":
        item = DATA["faq"].get(pending["key"])
        context.user_data.pop("pending", None)
        if not item:
            await reply("این سؤال دیگه وجود نداره.", reply_markup=admin_menu())
            return
        field = pending["field"]
        item[field] = parse_keywords(text) if field == "keywords" else text
        save_data()
        await reply("✅ ذخیره شد.\n\n" + item_text(item), reply_markup=admin_menu())

    elif pending["type"] == "broadcast":
        context.user_data.pop("pending", None)
        context.user_data["bc_text"] = text
        kb = InlineKeyboardMarkup(
            [[btn("✅ ارسال", "adm:bcok"), btn("❌ انصراف", "adm:cancel")]]
        )
        await reply(
            f"این پیام برای {len(DATA['users'])} نفر ارسال می‌شه:\n\n{text}", reply_markup=kb
        )


# ----------------------------------------------------------------------
# پیام‌های متنی
# ----------------------------------------------------------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)

    pending = context.user_data.get("pending")
    if pending and is_admin(update.effective_user.id):
        await handle_admin_input(update, context, pending)
        return

    item = find_answer(update.message.text)
    if item:
        await update.message.reply_text(
            f"{item['title']}\n\n{item['answer']}", reply_markup=back_button()
        )
    else:
        await update.message.reply_text(NOT_FOUND, reply_markup=main_menu())


# ----------------------------------------------------------------------
def main() -> None:
    builder = Application.builder().token(TOKEN)
    if PROXY:
        builder = builder.proxy(PROXY).get_updates_proxy(PROXY)
    app = builder.build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(menu|faq:)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logging.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
