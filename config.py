import os
from typing import List
try:
    from dotenv import load_dotenv
except Exception:  # make optional for environments without python-dotenv
    def load_dotenv(*args, **kwargs):
        return False

# Load .env file automatically at import time
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

# Marzban Configuration
MARZBAN_URL = os.getenv("MARZBAN_URL", "https://your-marzban-panel.com")
MARZBAN_USERNAME = os.getenv("MARZBAN_USERNAME", "admin")
MARZBAN_PASSWORD = os.getenv("MARZBAN_PASSWORD", "admin_password")

# Sudo Admins (User IDs)
SUDO_ADMINS: List[int] = [
    int(x) for x in os.getenv("SUDO_ADMINS", "123456789").split(",") if x.strip()
]

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")
BACKUP_DIR = os.getenv("BACKUP_DIR", "").strip()

# Monitoring Configuration
MONITORING_INTERVAL = int(os.getenv("MONITORING_INTERVAL", "600"))  # 10 minutes in seconds
WARNING_THRESHOLD = float(os.getenv("WARNING_THRESHOLD", "0.8"))  # 80% threshold
AUTO_DELETE_EXPIRED_USERS = os.getenv("AUTO_DELETE_EXPIRED_USERS", "false").lower() in ["1", "true", "yes"]

# API Configuration
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Messages in Persian
MESSAGES = {
    "welcome_sudo": "🔐 سلام! شما به عنوان سودو ادمین وارد شده‌اید.\n\nکلیدهای دستور:",
    "welcome_admin": "👋 سلام! شما به عنوان ادمین معمولی وارد شده‌اید.\n\nکلیدهای دستور:",
    "unauthorized": "⛔ شما مجاز به استفاده از این ربات نیستید.",
    "admin_added": "✅ ادمین جدید با موفقیت اضافه شد:",
    "admin_removed": "❌ پنل با موفقیت غیرفعال شد.",
    "admin_activated": "✅ ادمین فعال شد.",
    "admin_deactivated": "❌ ادمین غیرفعال شد.",
    "admin_not_found": "❌ ادمین مورد نظر یافت نشد.",
    "panel_not_found": "❌ پنل مورد نظر یافت نشد.",
    "invalid_format": "❌ فرمت ورودی اشتباه است.",
    "api_error": "⚠️ خطا در اتصال به API مرزبان.",
    "database_error": "⚠️ خطا در پایگاه داده.",
    "limit_warning": "⚠️ هشدار: شما به {percent}% از محدودیت خود رسیده‌اید!",
    "limit_exceeded": "🚫 محدودیت شما اشباع شده و کاربران غیرفعال شدند.",
    "users_reactivated": "✅ کاربران مجدداً فعال شدند.",
    "admin_deactivated": "🔒 ادمین {admin_id} به دلیل {reason} غیرفعال شد.",
    "admin_reactivated": "✅ ادمین {admin_id} مجدداً فعال شد.",
    "admin_users_deactivated": "👥 تمام کاربران ادمین {admin_id} غیرفعال شدند.",
    "admin_password_randomized": "🔐 پسورد ادمین {admin_id} تصادفی شد.",
    "no_deactivated_admins": "✅ همه ادمین‌ها فعال هستند.",
    "select_admin_to_reactivate": "🔄 انتخاب ادمین برای فعالسازی مجدد:",
    "select_panel_to_deactivate": "❌ انتخاب پنل برای غیرفعالسازی:",
    "select_panel_to_edit": "✏️ انتخاب پنل برای ویرایش:",
    "panel_limits_updated": "✅ محدودیت‌های پنل با موفقیت به‌روزرسانی شد.",
    # Public sales / payments
    "public_payment_instructions": (
        "💳 اطلاعات پرداخت دستی\n\n"
        "مبلغ را دقیقاً به یکی از کارت‌های زیر واریز کنید، سپس روی 'پرداخت کردم' بزنید و رسید پرداخت را به صورت عکس ارسال کنید."
    ),
    "public_order_registered": "✅ سفارش شما ثبت شد. برای پرداخت، کارت‌ها را می‌بینید.",
    "public_send_payment_note": "✍️ اطلاعات پرداخت را ارسال کنید (۴ رقم آخر کارت شما، شماره تراکنش، زمان واریز).",
    "public_send_receipt": "🧾 لطفاً فقط عکس رسید پرداخت را ارسال کنید.",
    "order_submitted_to_admin": "✅ پرداخت شما ثبت شد. پس از بررسی و صدور پنل به شما اطلاع می‌دهیم.",
    "order_approved_user": (
        "🎉 پنل شما صادر شد!\n\n"
        "```\n"
        "نام کاربری: {username}\n"
        "رمز عبور: {password}\n"
        "```\n"
        "🌐 آدرس ورود: {login_url}\n\n"
        "از طریق لینک فوق وارد پنل شوید."
    ),
    "order_rejected_user": (
        "⛔ سفارش شما رد شد.\n\n"
        "در صورت نیاز می‌توانید دوباره اقدام کنید یا با پشتیبانی در ارتباط باشید."
    ),
    "login_url_updated": "✅ آدرس ورود پنل ذخیره شد.",
    # Backup
    "backup_created": "✅ بکاپ آماده شد و ارسال می‌شود.",
    "backup_failed": "❌ خطا در ایجاد بکاپ.",
    "backup_schedule_saved": "✅ زمان‌بندی بکاپ ذخیره شد.",
    "backup_schedule_disabled": "✅ زمان‌بندی بکاپ غیرفعال شد."
}

# Button Labels
BUTTONS = {
    "add_admin": "➕ افزودن ادمین",
    "remove_admin": "🗑️ حذف کامل پنل", 
    "edit_panel": "✏️ ویرایش پنل",
    "list_admins": "📋 لیست ادمین‌ها",
    "admin_status": "📊 وضعیت ادمین‌ها",
    "activate_admin": "🔄 فعالسازی پنل",
    "import_admin": "⬇️ افزودن ادمین قبلی",
    "my_info": "👤 اطلاعات من",
    "my_users": "👥 کاربران من",
    "my_report": "📈 گزارش من",
    "reactivate_users": "🔄 فعالسازی کاربران",
    "cleanup_old_expired": "🧹 حذف منقضی‌های ۱۰+ روز",
    "cleanup_small_quota": "🧹 حذف ساب‌های سهمیه ≤۱GB تمام‌شده",
    "reset_usage": "♻️ ریست مصرف",
    "non_payer": "💸 پول نداد",
    "manage_admins": "🛠️ مدیریت ادمین‌ها",
    "back": "🔙 بازگشت",
    "cancel": "❌ لغو",
    # Sales
    "sales_cards": "💳 مدیریت کارت‌ها",
    "sales_orders": "🧾 سفارش‌ها",
    "add_card": "➕ افزودن کارت",
    "delete_card": "🗑️ حذف کارت",
    "toggle_card": "🔁 فعال/غیرفعال",
    "mark_paid": "✅ پرداخت کردم",
    "set_login_url": "🌐 تنظیم آدرس ورود",
    "renew": "🔄 تمدید/افزایش",
    "set_billing": "💰 تنظیم تعرفه تمدید",
    # Backup
    "backup_menu": "🗄️ بکاپ",
    "backup_now": "📦 بکاپ الان",
    "backup_schedule": "⏱️ زمان‌بندی بکاپ",
    "backup_restore": "♻️ ریستور بکاپ",
    # Broadcast
    "broadcast_menu": "📣 پیام‌رسانی",
    "broadcast_all": "📣 ارسال به همه ادمین‌ها",
    "broadcast_active": "✅ ارسال به ادمین‌های فعال"
}