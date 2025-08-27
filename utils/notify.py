from typing import List, Optional
from aiogram import Bot
from aiogram.types import Message
import config
from database import db
from models.schemas import LogModel
from datetime import datetime


async def notify_sudo_admins(bot: Bot, message: str, exclude_user_id: Optional[int] = None):
    """Send notification to all sudo admins."""
    for sudo_id in config.SUDO_ADMINS:
        if exclude_user_id and sudo_id == exclude_user_id:
            continue
        try:
            await bot.send_message(chat_id=sudo_id, text=message)
        except Exception as e:
            print(f"Failed to notify sudo admin {sudo_id}: {e}")


async def notify_admin(bot: Bot, user_id: int, message: str):
    """Send notification to specific admin."""
    try:
        await bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        print(f"Failed to notify admin {user_id}: {e}")


async def notify_limit_warning(bot: Bot, admin_user_id: int, limit_type: str, percentage: float):
    """Send limit warning notification."""
    message = config.MESSAGES["limit_warning"].format(percent=int(percentage * 100))
    message += f"\n\n📊 نوع محدودیت: {limit_type}"
    
    await notify_admin(bot, admin_user_id, message)
    
    # Log the warning
    log = LogModel(
        admin_user_id=admin_user_id,
        action="limit_warning",
        details=f"Warning sent for {limit_type} at {percentage:.1%}",
        timestamp=datetime.now()
    )
    await db.add_log(log)


async def notify_limit_exceeded(bot: Bot, admin_user_id: int, affected_users: List[str]):
    """Send limit exceeded notification."""
    message = config.MESSAGES["limit_exceeded"]
    if affected_users:
        message += f"\n\n🚫 کاربران غیرفعال شده ({len(affected_users)}):\n"
        message += "\n".join([f"• {user}" for user in affected_users[:10]])
        if len(affected_users) > 10:
            message += f"\n... و {len(affected_users) - 10} کاربر دیگر"
    
    # Notify the admin
    await notify_admin(bot, admin_user_id, message)
    
    # Notify sudo admins
    sudo_message = f"🚨 محدودیت ادمین تجاوز شد!\n\n"
    sudo_message += f"👤 ادمین: {admin_user_id}\n"
    sudo_message += f"🚫 کاربران غیرفعال شده: {len(affected_users)}"
    
    await notify_sudo_admins(bot, sudo_message)
    
    # Log the event
    log = LogModel(
        admin_user_id=admin_user_id,
        action="limit_exceeded",
        details=f"Users disabled: {', '.join(affected_users)}",
        timestamp=datetime.now()
    )
    await db.add_log(log)


async def notify_admin_deactivated(bot: Bot, admin_user_id: int, reason: str):
    """Notify the admin (owner) that their panel was deactivated due to limits or other reasons."""
    try:
        message = (
            "🔒 پنل شما غیرفعال شد\n\n"
            f"📝 دلیل: {reason}\n"
            "🔐 به‌دلایل امنیتی، پسورد پنل تغییر کرده و کاربران شما موقتاً غیرفعال شدند.\n\n"
            "در صورت نیاز با پشتیبانی تماس بگیرید یا پس از رفع محدودیت، از گزینه فعالسازی استفاده کنید."
        )
        await notify_admin(bot, admin_user_id, message)
        log = LogModel(
            admin_user_id=admin_user_id,
            action="admin_notified_deactivated",
            details=f"Deactivation notice sent. Reason: {reason}",
            timestamp=datetime.now()
        )
        await db.add_log(log)
    except Exception as e:
        print(f"Failed to notify deactivated admin {admin_user_id}: {e}")


async def notify_users_reactivated(bot: Bot, admin_user_id: int, reactivated_users: List[str], by_sudo: bool = False):
    """Send notification when users are reactivated."""
    message = config.MESSAGES["users_reactivated"]
    message += f"\n\n✅ کاربران فعال شده ({len(reactivated_users)}):\n"
    message += "\n".join([f"• {user}" for user in reactivated_users[:10]])
    if len(reactivated_users) > 10:
        message += f"\n... و {len(reactivated_users) - 10} کاربر دیگر"
    
    # Notify the admin
    await notify_admin(bot, admin_user_id, message)
    
    # If reactivated by sudo, notify sudo admins
    if by_sudo:
        sudo_message = f"🔄 کاربران توسط سودو فعال شدند\n\n"
        sudo_message += f"👤 ادمین: {admin_user_id}\n"
        sudo_message += f"✅ کاربران فعال شده: {len(reactivated_users)}"
        
        await notify_sudo_admins(bot, sudo_message, exclude_user_id=admin_user_id)
    
    # Log the event
    log = LogModel(
        admin_user_id=admin_user_id,
        action="users_reactivated",
        details=f"Users reactivated by {'sudo' if by_sudo else 'admin'}: {', '.join(reactivated_users)}",
        timestamp=datetime.now()
    )
    await db.add_log(log)


async def notify_admin_added(bot: Bot, new_admin_user_id: int, admin_info: dict, by_sudo_id: int):
    """Send notification when new admin is added."""
    # Notify the new admin
    welcome_message = config.MESSAGES["welcome_admin"]
    await notify_admin(bot, new_admin_user_id, welcome_message)
    
    # Notify sudo admins
    sudo_message = f"➕ ادمین جدید اضافه شد:\n\n"
    sudo_message += f"👤 ID: {new_admin_user_id}\n"
    sudo_message += f"📝 نام کاربری: {admin_info.get('username', 'نامشخص')}\n"
    sudo_message += f"👥 حداکثر کاربر: {admin_info.get('max_users', 0)}\n"
    sudo_message += f"⏱️ حداکثر زمان: {admin_info.get('max_total_time', 0)} ثانیه\n"
    sudo_message += f"📊 حداکثر ترافیک: {admin_info.get('max_total_traffic', 0)} بایت"
    
    await notify_sudo_admins(bot, sudo_message, exclude_user_id=by_sudo_id)
    
    # Log the event
    log = LogModel(
        admin_user_id=new_admin_user_id,
        action="admin_added",
        details=f"Added by sudo {by_sudo_id}",
        timestamp=datetime.now()
    )
    await db.add_log(log)


async def notify_admin_removed(bot: Bot, removed_admin_user_id: int, by_sudo_id: int):
    """Send notification when admin is removed."""
    # Notify sudo admins
    sudo_message = f"🗑️ ادمین حذف شد:\n\n"
    sudo_message += f"👤 ID: {removed_admin_user_id}"
    
    await notify_sudo_admins(bot, sudo_message, exclude_user_id=by_sudo_id)
    
    # Log the event
    log = LogModel(
        admin_user_id=removed_admin_user_id,
        action="admin_removed",
        details=f"Removed by sudo {by_sudo_id}",
        timestamp=datetime.now()
    )
    await db.add_log(log)


async def notify_admin_reactivation(bot: Bot, reactivated_admin_user_id: int, by_sudo_id: int):
    """Send notification when admin is reactivated."""
    # Notify the reactivated admin
    reactivation_message = (
        "🎉 **حساب شما مجدداً فعال شد!**\n\n"
        "✅ همه پنل‌های شما دوباره فعال شدند\n"
        "🔑 پسورد اصلی بازگردانی شد\n"
        "👥 کاربران پنل فعال شدند\n\n"
        "🎊 می‌توانید مجدداً از ربات استفاده کنید!"
    )
    await notify_admin(bot, reactivated_admin_user_id, reactivation_message)
    
    # Notify sudo admins
    sudo_message = f"🔄 ادمین مجدداً فعال شد:\n\n"
    sudo_message += f"👤 ID: {reactivated_admin_user_id}\n"
    sudo_message += f"🔧 توسط سودو: {by_sudo_id}"
    
    await notify_sudo_admins(bot, sudo_message, exclude_user_id=by_sudo_id)
    
    # Log the event
    log = LogModel(
        admin_user_id=reactivated_admin_user_id,
        action="admin_reactivated",
        details=f"Reactivated by sudo {by_sudo_id}",
        timestamp=datetime.now()
    )
    await db.add_log(log)


async def format_traffic_size(bytes_size: int) -> str:
    """Format bytes to human readable format."""
    if bytes_size == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_size)
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return f"{size:.2f} {units[unit_index]}"


async def format_time_duration(seconds: int) -> str:
    """Format seconds to human readable duration."""
    if seconds == 0:
        return "0 ثانیه"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if days > 0:
        parts.append(f"{days} روز")
    if hours > 0:
        parts.append(f"{hours} ساعت")
    if minutes > 0:
        parts.append(f"{minutes} دقیقه")
    if secs > 0 and not parts:  # Only show seconds if no larger units
        parts.append(f"{secs} ثانیه")
    
    return " و ".join(parts) if parts else "0 ثانیه"


def gb_to_bytes(gb: float) -> int:
    """Convert gigabytes to bytes."""
    return int(gb * 1024 * 1024 * 1024)


def days_to_seconds(days: int) -> int:
    """Convert days to seconds."""
    return days * 24 * 60 * 60


def bytes_to_gb(bytes_size: int) -> float:
    """Convert bytes to gigabytes."""
    return bytes_size / (1024 * 1024 * 1024)


def seconds_to_days(seconds: int) -> int:
    """Convert seconds to days."""
    return seconds // (24 * 60 * 60)