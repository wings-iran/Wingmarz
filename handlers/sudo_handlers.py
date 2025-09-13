from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import FSInputFile
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import List
import logging
import asyncio
from pathlib import Path
import config
from database import db
from models.schemas import AdminModel, LogModel
from utils.notify import (
    notify_admin_added, notify_admin_removed, notify_admin_deactivated, format_traffic_size, format_time_duration,
    gb_to_bytes, days_to_seconds, bytes_to_gb, seconds_to_days,
)
from utils.notify import notify_admin_reactivation as notify_admin_reactivation_utils
from marzban_api import marzban_api
from datetime import datetime
from handlers.admin_handlers import show_cleanup_menu, perform_cleanup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)


class AddAdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_admin_name = State()
    waiting_for_marzban_username = State()
    waiting_for_marzban_password = State()
    waiting_for_traffic_volume = State()
    waiting_for_max_users = State()
    waiting_for_validity_period = State()
    waiting_for_confirmation = State()


class ImportAdminStates(StatesGroup):
    waiting_for_admin_name = State()
    waiting_for_target_user_id = State()
    waiting_for_marzban_username = State()
    waiting_for_marzban_password = State()
    waiting_for_traffic_volume = State()
    waiting_for_validity_period = State()
    waiting_for_max_users = State()
    waiting_for_confirmation = State()


class EditPanelStates(StatesGroup):
    waiting_for_traffic_volume = State()
    waiting_for_validity_period = State()
    waiting_for_confirmation = State()

class ManageAdminStates(StatesGroup):
    waiting_for_user_id = State()


class CreatePlanStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_type = State()
    waiting_for_traffic = State()
    waiting_for_time = State()
    waiting_for_max_users = State()
    waiting_for_price = State()
    waiting_for_renew_mode = State()


class CardStates(StatesGroup):
    waiting_for_bank = State()
    waiting_for_card = State()
    waiting_for_holder = State()


class LoginURLStates(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_url = State()


sudo_router = Router()


def get_progress_indicator(current_step: int, total_steps: int = 7) -> str:
    """Generate a visual progress indicator."""
    filled = "🟢"
    current = "🔵" 
    empty = "⚪"
    
    indicators = []
    for i in range(1, total_steps + 1):
        if i < current_step:
            indicators.append(filled)
        elif i == current_step:
            indicators.append(current)
        else:
            indicators.append(empty)
    
    return "".join(indicators) + f" ({current_step}/{total_steps})"


def get_sudo_keyboard() -> InlineKeyboardMarkup:
    """Get sudo admin main keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        # Row 1: Core management submenus
        [
            InlineKeyboardButton(text="🧩 پنل‌ها", callback_data="sudo_menu_panels"),
            InlineKeyboardButton(text="🧹 پاکسازی", callback_data="sudo_menu_cleanup"),
            InlineKeyboardButton(text="💳 فروش/مالی", callback_data="sudo_menu_sales")
        ],
        # Row 2: Settings and reports
        [
            InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="sudo_menu_settings"),
            InlineKeyboardButton(text=config.BUTTONS["backup_menu"], callback_data="sudo_menu_backup"),
            InlineKeyboardButton(text="📊 گزارشات", callback_data="sudo_menu_reports")
        ]
    ])

@sudo_router.callback_query(F.data == "sudo_menu_panels")
async def sudo_menu_panels(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["add_admin"], callback_data="add_admin"), InlineKeyboardButton(text=config.BUTTONS["edit_panel"], callback_data="edit_panel")],
        [InlineKeyboardButton(text=config.BUTTONS["activate_admin"], callback_data="activate_admin"), InlineKeyboardButton(text=config.BUTTONS["manage_admins"], callback_data="sudo_manage_admins")],
        [InlineKeyboardButton(text=config.BUTTONS["import_admin"], callback_data="import_admin")],
        [InlineKeyboardButton(text=config.BUTTONS["remove_admin"], callback_data="remove_admin")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("🧩 مدیریت پنل‌ها:", reply_markup=kb)
    await callback.answer()

@sudo_router.callback_query(F.data == "import_admin")
async def import_admin_entry(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.clear()
    await state.set_state(ImportAdminStates.waiting_for_admin_name)
    await callback.message.edit_text(
        "⬇️ افزودن ادمین قبلی\n\nیک نام نمایشی برای این پنل بفرستید (اختیاری، برای نمایش). اگر نمی‌خواهید، - بفرستید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_menu_panels")]])
    )
    await callback.answer()

@sudo_router.message(ImportAdminStates.waiting_for_admin_name, F.text)
async def import_admin_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(admin_name=None if name == '-' else name)
    await state.set_state(ImportAdminStates.waiting_for_target_user_id)
    await message.answer("آیدی عددی تلگرام ادمین (User ID) را ارسال کنید:")


@sudo_router.message(ImportAdminStates.waiting_for_target_user_id, F.text)
async def import_admin_target_user_id(message: Message, state: FSMContext):
    try:
        target_user_id = int(message.text.strip())
        await state.update_data(target_user_id=target_user_id)
        await state.set_state(ImportAdminStates.waiting_for_marzban_username)
        await message.answer("نام کاربری پنل در مرزبان را ارسال کنید:")
    except Exception:
        await message.answer("آیدی عددی نامعتبر است. یک عدد صحیح ارسال کنید:")

@sudo_router.message(ImportAdminStates.waiting_for_marzban_username, F.text)
async def import_admin_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username:
        await message.answer("نام کاربری معتبر نیست. دوباره بفرستید:")
        return
    await state.update_data(marzban_username=username)
    await state.set_state(ImportAdminStates.waiting_for_marzban_password)
    await message.answer("رمز عبور پنل در مرزبان را ارسال کنید:")

@sudo_router.message(ImportAdminStates.waiting_for_marzban_password, F.text)
async def import_admin_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if not password:
        await message.answer("رمز عبور معتبر نیست. دوباره بفرستید:")
        return
    await state.update_data(marzban_password=password)
    await state.set_state(ImportAdminStates.waiting_for_traffic_volume)
    await message.answer("محدودیت حجم (GB) را وارد کنید (مثلاً 100) یا «نامحدود» بفرستید:")

@sudo_router.message(ImportAdminStates.waiting_for_traffic_volume, F.text)
async def import_admin_traffic(message: Message, state: FSMContext):
    from utils.notify import gb_to_bytes
    try:
        raw = message.text.strip()
        lower = raw.lower()
        # Accept unlimited keywords
        if lower in ["نامحدود", "بدون محدودیت", "unlimited", "∞", "بي نهايت", "بی نهایت", "بی‌نهایت"]:
            await state.update_data(max_total_traffic=0, traffic_unlimited=True)
            await state.set_state(ImportAdminStates.waiting_for_validity_period)
            await message.answer("محدودیت زمان (روز) را وارد کنید (مثلاً 30) یا «نامحدود» بفرستید:")
            return
        gb = float(raw.replace(',', '.'))
        if gb < 0:
            raise ValueError()
        await state.update_data(max_total_traffic=gb_to_bytes(gb))
        await state.set_state(ImportAdminStates.waiting_for_validity_period)
        await message.answer("محدودیت زمان (روز) را وارد کنید (مثلاً 30) یا «نامحدود» بفرستید:")
    except Exception:
        await message.answer("فرمت حجم نامعتبر است. یک عدد مثل 100 وارد کنید:")

@sudo_router.message(ImportAdminStates.waiting_for_validity_period, F.text)
async def import_admin_time(message: Message, state: FSMContext):
    from utils.notify import days_to_seconds
    try:
        raw = message.text.strip()
        lower = raw.lower()
        if lower in ["نامحدود", "بدون محدودیت", "unlimited", "∞", "بي نهايت", "بی نهایت", "بی‌نهایت"]:
            # Use a large sentinel (100 years) for unlimited time
            days = 36500
            await state.update_data(max_total_time=days_to_seconds(days), validity_days=days, time_unlimited=True)
            await state.set_state(ImportAdminStates.waiting_for_max_users)
            await message.answer("حداکثر تعداد کاربران را وارد کنید (مثلاً 100) یا «نامحدود» بفرستید:")
            return
        days = int(raw)
        if days <= 0:
            raise ValueError()
        await state.update_data(max_total_time=days_to_seconds(days), validity_days=days)
        await state.set_state(ImportAdminStates.waiting_for_max_users)
        await message.answer("حداکثر تعداد کاربران را وارد کنید (مثلاً 100) یا «نامحدود» بفرستید:")
    except Exception:
        await message.answer("فرمت زمان نامعتبر است. یک عدد صحیح مثل 30 وارد کنید:")

@sudo_router.message(ImportAdminStates.waiting_for_max_users, F.text)
async def import_admin_max_users(message: Message, state: FSMContext):
    try:
        raw = message.text.strip()
        lower = raw.lower()
        if lower in ["نامحدود", "بدون محدودیت", "unlimited", "∞", "بي نهايت", "بی نهایت", "بی‌نهایت"]:
            max_users = 1000000  # Sentinel for unlimited users
            await state.update_data(max_users=max_users, users_unlimited=True)
        else:
            max_users = int(raw)
        if max_users <= 0:
            raise ValueError()
        if not lower in ["نامحدود", "بدون محدودیت", "unlimited", "∞", "بي نهايت", "بی نهایت", "بی‌نهایت"]:
            await state.update_data(max_users=max_users)
        data = await state.get_data()
        # Build human-readable summary respecting unlimited selections
        traffic_b = data.get('max_total_traffic')
        validity_days = data.get('validity_days')
        traffic_txt = "نامحدود" if data.get('traffic_unlimited') or (traffic_b == 0) else f"{traffic_b} بایت"
        time_txt = "نامحدود" if data.get('time_unlimited') or (validity_days and validity_days >= 36500) else f"{validity_days} روز"
        users_txt = "نامحدود" if data.get('users_unlimited') or (max_users >= 1000000) else f"{max_users}"
        text = (
            "✅ تایید افزودن ادمین قبلی\n\n"
            f"نام: {data.get('admin_name') or '-'}\n"
            f"آیدی کاربر مقصد: {data.get('target_user_id','-')}\n"
            f"نام کاربری مرزبان: {data.get('marzban_username')}\n"
            f"کاربر: {users_txt}\n"
            f"حجم: {traffic_txt}\n"
            f"زمان: {time_txt}\n\n"
            "برای ادامه تایید کنید."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تایید و افزودن", callback_data="confirm_import_admin")],
            [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_menu_panels")]
        ])
        await state.set_state(ImportAdminStates.waiting_for_confirmation)
        await message.answer(text, reply_markup=kb)
    except Exception:
        await message.answer("فرمت تعداد کاربران نامعتبر است. یک عدد صحیح وارد کنید:")

@sudo_router.callback_query(F.data == "confirm_import_admin")
async def confirm_import_admin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    # Target user who will own this imported panel in the bot
    data = await state.get_data()
    user_id = data.get('target_user_id') or callback.from_user.id
    await state.clear()
    # Validate credentials by trying to fetch stats
    try:
        admin_api = await marzban_api.create_admin_api(data.get('marzban_username'), data.get('marzban_password'))
        stats = await admin_api.get_admin_stats()
    except Exception as e:
        logger.error(f"Import admin auth failed: {e}")
        await callback.message.edit_text("❌ اعتبارسنجی ناموفق. لطفاً اطلاعات را بررسی کنید.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_menu_panels")]]))
        await callback.answer()
        return
    # Save admin in DB
    from models.schemas import AdminModel, UsageReportModel
    from datetime import datetime
    admin = AdminModel(
        user_id=user_id,
        admin_name=data.get('admin_name'),
        marzban_username=data.get('marzban_username'),
        marzban_password=data.get('marzban_password'),
        max_users=data.get('max_users', 10),
        max_total_time=data.get('max_total_time', 2592000),
        max_total_traffic=data.get('max_total_traffic', 107374182400),
        validity_days=data.get('validity_days', 30),
        is_active=True,
    )
    ok = await db.add_admin(admin)
    if not ok:
        await callback.message.edit_text("❌ خطا در ذخیره ادمین.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_menu_panels")]]))
        await callback.answer()
        return
    # Store initial usage report from fetched stats
    report = UsageReportModel(
        admin_user_id=user_id,
        check_time=datetime.utcnow(),
        current_users=stats.total_users,
        current_total_time=0,
        current_total_traffic=stats.total_traffic_used,
        users_data=None
    )
    await db.add_usage_report(report)
    await callback.message.edit_text("✅ ادمین قبلی اضافه شد و مصرف فعلی ثبت شد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_menu_panels")]]))
    await callback.answer()

@sudo_router.callback_query(F.data == "sudo_menu_cleanup")
async def sudo_menu_cleanup(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["cleanup_old_expired"], callback_data="sudo_cleanup_old_expired")],
        [InlineKeyboardButton(text=config.BUTTONS["cleanup_small_quota"], callback_data="sudo_cleanup_small_quota")],
        [InlineKeyboardButton(text=config.BUTTONS["reset_usage"], callback_data="sudo_reset_usage")],
        [InlineKeyboardButton(text=config.BUTTONS["non_payer"], callback_data="sudo_non_payer")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("🧹 عملیات پاکسازی:", reply_markup=kb)
    await callback.answer()

@sudo_router.callback_query(F.data == "sudo_menu_sales")
async def sudo_menu_sales(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 مدیریت فروش", callback_data="sales_manage")],
        [InlineKeyboardButton(text=config.BUTTONS["sales_cards"], callback_data="sales_cards"), InlineKeyboardButton(text=config.BUTTONS["set_billing"], callback_data="set_billing")],
        [InlineKeyboardButton(text=config.BUTTONS["set_login_url"], callback_data="set_login_url")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("💳 فروش و مالی:", reply_markup=kb)
    await callback.answer()

@sudo_router.callback_query(F.data == "sudo_menu_settings")
async def sudo_menu_settings(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 کانال‌های اجباری", callback_data="forced_join_manage")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("⚙️ تنظیمات:", reply_markup=kb)
    await callback.answer()

@sudo_router.callback_query(F.data == "sudo_menu_backup")
async def sudo_menu_backup(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["backup_now"], callback_data="backup_now"), InlineKeyboardButton(text=config.BUTTONS["backup_schedule"], callback_data="backup_schedule")],
        [InlineKeyboardButton(text=config.BUTTONS["backup_restore"], callback_data="backup_restore")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("🗄️ مدیریت بکاپ:", reply_markup=kb)
    await callback.answer()

@sudo_router.callback_query(F.data == "backup_now")
async def backup_now(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await callback.answer("در حال ساخت بکاپ...", show_alert=False)
    try:
        from utils.backup import create_backup_zip
        path = await create_backup_zip()
        await callback.message.answer(config.MESSAGES["backup_created"]) 
        try:
            p = Path(str(path))
            await callback.message.answer_document(document=FSInputFile(str(p)), caption=f"بکاپ: {p.name}")
        except Exception as send_err:
            logger.error(f"Failed to send backup file {p}: {send_err}")
            await callback.message.answer("❌ خطا در ارسال فایل بکاپ.")
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        await callback.message.answer(config.MESSAGES["backup_failed"]) 

    # Return to backup menu
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["backup_now"], callback_data="backup_now")],
        [InlineKeyboardButton(text=config.BUTTONS["backup_schedule"], callback_data="backup_schedule")],
        [InlineKeyboardButton(text=config.BUTTONS["backup_restore"], callback_data="backup_restore")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    try:
        await callback.message.answer("🗄️ مدیریت بکاپ:", reply_markup=kb)
    except Exception:
        pass

class BackupRestoreStates(StatesGroup):
    waiting_for_file = State()

@sudo_router.callback_query(F.data == "backup_restore")
async def backup_restore_entry(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.set_state(BackupRestoreStates.waiting_for_file)
    await callback.message.edit_text(
        "♻️ ریستور بکاپ\n\nفایل زیپ بکاپ را همین‌جا ارسال کنید. فقط فایل‌های زیپ ساخته‌شده توسط ربات پشتیبانی می‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_menu_backup")]])
    )
    await callback.answer()

@sudo_router.message(BackupRestoreStates.waiting_for_file)
async def backup_restore_receive(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    if not message.document or not (message.document.file_name or '').lower().endswith('.zip'):
        await message.answer("لطفاً یک فایل ZIP معتبر ارسال کنید.")
        return
    # Download file to /app/data (or CWD fallback)
    try:
        from aiogram.types import FSInputFile
        from pathlib import Path
        import zipfile
        import asyncio
        # Create download path
        target_dir = Path(config.DATABASE_PATH).resolve().parent
        target_dir.mkdir(parents=True, exist_ok=True)
        local_zip = target_dir / f"restore-{message.document.file_name}"

        # Download via bot API (aiogram v3)
        file = await message.bot.get_file(message.document.file_id)
        await message.bot.download(file, destination=str(local_zip))

        # Extract and replace DB
        with zipfile.ZipFile(local_zip, 'r') as zf:
            members = zf.namelist()
            # Prefer exact DB file
            db_rel = Path(config.DATABASE_PATH).name
            db_member = None
            for m in members:
                if m.endswith(db_rel):
                    db_member = m
                    break
            if not db_member:
                # Try common names
                for m in members:
                    if m.endswith('bot_database.db'):
                        db_member = m
                        break
            if not db_member:
                await message.answer("❌ فایل دیتابیس در بکاپ پیدا نشد.")
                await state.clear()
                return
            extract_tmp = target_dir / "_restore_tmp.db"
            with zf.open(db_member, 'r') as src, open(extract_tmp, 'wb') as dst:
                dst.write(src.read())

        # Replace existing DB (backup current)
        db_path = Path(config.DATABASE_PATH).resolve()
        backup_old = db_path.with_suffix('.db.bak') if db_path.suffix else Path(str(db_path) + '.bak')
        try:
            if db_path.exists():
                db_path.replace(backup_old)
        except Exception:
            pass
        extract_tmp.replace(db_path)
        await message.answer("✅ ریستور انجام شد. ربات تا چند لحظه دیگر با داده‌های جدید کار می‌کند.")
        await state.clear()
        # Optional: instruct user to restart container/service if needed
        await message.answer("در صورت اجرای دائمی، برای اطمینان می‌توانید سرویس را ری‌استارت کنید.")
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        await message.answer("❌ خطا در ریستور بکاپ.")
        await state.clear()

class BackupScheduleStates(StatesGroup):
    waiting_input = State()

@sudo_router.callback_query(F.data == "backup_schedule")
async def backup_schedule_entry(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    text = (
        "⏱️ زمان‌بندی بکاپ\n\n"
        "- برای فعال‌سازی بکاپ ساعتی، عدد 1h را بفرستید.\n"
        "- برای غیرفعالسازی، عبارت off را بفرستید.\n"
        "(در حال حاضر فقط هر ساعت پشتیبانی می‌شود)"
    )
    await state.set_state(BackupScheduleStates.waiting_input)
    await callback.message.edit_text(text, reply_markup=None)
    await callback.answer()

@sudo_router.message(BackupScheduleStates.waiting_input, F.text)
async def backup_schedule_set(message: Message, state: FSMContext):
    txt = message.text.strip().lower()
    from scheduler import scheduler
    if txt in ("off", "0", "disable", "stop"):
        ok = scheduler.disable_backup_schedule() if scheduler else False
        if ok:
            await db.set_setting("backup_schedule", "off")
            await message.answer("✅ تنظیم شد.")
        else:
            await message.answer("❌ خطا در غیرفعالسازی زمان‌بندی.")
        await state.clear()
        # Return directly to admin main menu
        await message.answer(config.MESSAGES["welcome_sudo"], reply_markup=get_sudo_keyboard())
        return
    if txt in ("1h", "hour", "hourly"):
        ok = scheduler.schedule_backup_every_hour() if scheduler else False
        if ok:
            await db.set_setting("backup_schedule", "1h")
            await message.answer("✅ تنظیم شد.")
        else:
            await message.answer("❌ خطا در ذخیره زمان‌بندی.")
        await state.clear()
        # Return directly to admin main menu
        await message.answer(config.MESSAGES["welcome_sudo"], reply_markup=get_sudo_keyboard())
        return
    await message.answer("فرمت نامعتبر. فقط '1h' یا 'off' مجاز است.")

@sudo_router.callback_query(F.data == "sudo_menu_reports")
async def sudo_menu_reports(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["list_admins"], callback_data="list_admins"), InlineKeyboardButton(text=config.BUTTONS["admin_status"], callback_data="admin_status")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📊 گزارشات:", reply_markup=kb)
    await callback.answer()
@sudo_router.callback_query(F.data == "forced_join_manage")
async def forced_join_manage(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    channels = await db.get_forced_channels(only_active=False)
    lines = ["📢 کانال‌های جوین اجباری:", ""]
    if not channels:
        lines.append("— لیستی وجود ندارد.")
    else:
        for ch in channels:
            status = "✅" if ch.get("is_active") else "❌"
            lines.append(f"{status} #{ch['id']} • {ch.get('title') or ch.get('chat_id')}\n{ch.get('invite_link') or ''}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن", callback_data="forced_join_add")],
        [InlineKeyboardButton(text="🗑️ حذف", callback_data="forced_join_del")],
        [InlineKeyboardButton(text="🔁 فعال/غیرفعال", callback_data="forced_join_toggle")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


class ForcedJoinStates(StatesGroup):
    waiting_chat_id = State()
    waiting_title = State()
    waiting_link = State()


@sudo_router.callback_query(F.data == "forced_join_add")
async def forced_join_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.set_state(ForcedJoinStates.waiting_chat_id)
    await callback.message.edit_text("Chat ID یا @username کانال را ارسال کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="forced_join_manage")]]))
    await callback.answer()


@sudo_router.message(ForcedJoinStates.waiting_chat_id, F.text)
async def forced_join_add_chat_id(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.text.strip())
    await state.set_state(ForcedJoinStates.waiting_title)
    await message.answer("عنوان نمایشی (اختیاری) را ارسال کنید یا - را بفرستید:")


@sudo_router.message(ForcedJoinStates.waiting_title, F.text)
async def forced_join_add_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(title=None if title == '-' else title)
    await state.set_state(ForcedJoinStates.waiting_link)
    await message.answer("لینک دعوت (اختیاری) را ارسال کنید یا - را بفرستید:")


@sudo_router.message(ForcedJoinStates.waiting_link, F.text)
async def forced_join_add_link(message: Message, state: FSMContext):
    link = message.text.strip()
    data = await state.get_data()
    await state.clear()
    ok = await db.add_forced_channel(chat_id=data.get('chat_id'), title=data.get('title'), invite_link=(None if link == '-' else link), is_active=True)
    if ok:
        await message.answer("✅ کانال اضافه شد.")
    else:
        await message.answer("❌ خطا در افزودن کانال.")


@sudo_router.callback_query(F.data == "forced_join_del")
async def forced_join_del(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    channels = await db.get_forced_channels(only_active=False)
    if not channels:
        await callback.answer("کانالی نیست.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{c['id']} {c.get('title') or c.get('chat_id')}", callback_data=f"forced_join_del_{c['id']}") ] for c in channels] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="forced_join_manage")]])
    await callback.message.edit_text("یک کانال را برای حذف انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("forced_join_del_"))
async def forced_join_del_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    cid = int(callback.data.split("_")[-1])
    ok = await db.delete_forced_channel(cid)
    text = "✅ حذف شد." if ok else "❌ خطا در حذف." 
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="forced_join_manage")]]))
    await callback.answer()


@sudo_router.callback_query(F.data == "forced_join_toggle")
async def forced_join_toggle(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    channels = await db.get_forced_channels(only_active=False)
    if not channels:
        await callback.answer("کانالی نیست.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"#{c['id']} {'فعال' if c.get('is_active') else 'غیرفعال'} - {c.get('title') or c.get('chat_id')}", callback_data=f"forced_join_toggle_{c['id']}") ] for c in channels] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="forced_join_manage")]])
    await callback.message.edit_text("فعال/غیرفعال کردن:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("forced_join_toggle_"))
async def forced_join_toggle_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    cid = int(callback.data.split("_")[-1])
    channels = await db.get_forced_channels(only_active=False)
    ch = next((c for c in channels if c['id'] == cid), None)
    if not ch:
        await callback.answer("یافت نشد.", show_alert=True)
        return
    ok = await db.set_forced_channel_active(cid, not bool(ch.get('is_active')))
    text = "✅ بروزرسانی شد." if ok else "❌ خطا در بروزرسانی." 
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="forced_join_manage")]]))
    await callback.answer()


def get_admin_list_keyboard(admins: List[AdminModel], action: str) -> InlineKeyboardMarkup:
    """Get keyboard with admin list for selection - grouped by user_id for better display."""
    buttons = []
    
    # Group admins by user_id
    user_panels = {}
    for admin in admins:
        if admin.user_id not in user_panels:
            user_panels[admin.user_id] = []
        user_panels[admin.user_id].append(admin)
    
    # Create buttons for each user (showing number of panels)
    for user_id, user_admins in user_panels.items():
        # Get user display info from first admin
        first_admin = user_admins[0]
        display_name = first_admin.username or f"ID: {user_id}"
        
        # Count active/inactive panels
        active_panels = len([a for a in user_admins if a.is_active])
        total_panels = len(user_admins)
        
        # Show status based on whether user has any active panels
        status = "✅" if active_panels > 0 else "❌"
        
        panel_info = f"({active_panels}/{total_panels} پنل)" if total_panels > 1 else ""
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {display_name} {panel_info}",
                callback_data=f"{action}_{user_id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_panel_list_keyboard(admins: List[AdminModel], action: str) -> InlineKeyboardMarkup:
    """Get keyboard with individual panel list for selection."""
    buttons = []
    
    # Create buttons for each individual panel
    for admin in admins:
        # Get display info
        display_name = admin.admin_name or admin.username or f"ID: {admin.user_id}"
        panel_name = admin.marzban_username or f"Panel-{admin.id}"
        
        # Show status
        status = "✅" if admin.is_active else "❌"
        
        # Include traffic and time limits for editing context
        from utils.notify import bytes_to_gb, seconds_to_days
        traffic_gb = bytes_to_gb(admin.max_total_traffic)
        time_days = seconds_to_days(admin.max_total_time)
        
        button_text = f"{status} {display_name} ({panel_name}) - {traffic_gb}GB/{time_days}د"
        
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"{action}_{admin.id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@sudo_router.message(Command("start"))
async def sudo_start(message: Message):
    """Start command for sudo users."""
    if message.from_user.id not in config.SUDO_ADMINS:
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return
    
    await message.answer(
        config.MESSAGES["welcome_sudo"],
        reply_markup=get_sudo_keyboard()
    )


@sudo_router.callback_query(F.data == "sudo_cleanup_old_expired")
async def sudo_cleanup_entry(callback: CallbackQuery):
    """Entry point for sudo cleanup: GLOBAL cleanup without panel selection."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    try:
        from handlers.admin_handlers import show_global_cleanup_menu
        await show_global_cleanup_menu(callback)
    except Exception as e:
        logger.error(f"Error showing global cleanup for sudo: {e}")
        await callback.answer("خطا در نمایش منوی پاکسازی.", show_alert=True)


@sudo_router.callback_query(F.data == "sudo_cleanup_small_quota")
async def sudo_cleanup_small_quota_entry(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    try:
        from handlers.admin_handlers import show_global_small_quota_menu
        await show_global_small_quota_menu(callback)
    except Exception as e:
        logger.error(f"Error showing global small-quota cleanup for sudo: {e}")
        await callback.answer("خطا در نمایش منوی پاکسازی.", show_alert=True)


@sudo_router.callback_query(F.data == "sudo_reset_usage")
async def sudo_reset_usage_entry(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    # سودو پنل را انتخاب کند و سپس منوی ریست پنل نمایش داده شود
    admins = await db.get_all_admins()
    if not admins:
        await callback.answer("هیچ پنلی وجود ندارد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(a.admin_name or a.marzban_username or f"Panel {a.id}"), callback_data=f"sudo_reset_menu_panel_{a.id}")]
        for a in admins
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]])
    await callback.message.edit_text("پنل موردنظر برای ریست مصرف را انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data == "sudo_non_payer")
async def sudo_non_payer_entry(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    # انتخاب پنل برای غیرفعال‌سازی به علت عدم پرداخت
    admins = await db.get_all_admins()
    active_admins = [a for a in admins if a.is_active]
    if not active_admins:
        await callback.answer("هیچ پنل فعالی وجود ندارد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(a.admin_name or a.marzban_username or f"Panel {a.id}"), callback_data=f"sudo_non_payer_panel_{a.id}")]
        for a in active_admins
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]])
    await callback.message.edit_text("پنل عدم پرداخت را انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("sudo_non_payer_panel_"))
async def sudo_non_payer_panel_selected(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    # تاییدیه
    panel_name = admin.admin_name or admin.marzban_username or f"Panel {admin.id}"
    text = (
        f"💸 غیرفعال‌سازی به علت عدم پرداخت\n\n"
        f"پنل: {panel_name}\n"
        f"در صورت تایید، همه کاربران غیرفعال می‌شوند و پسورد تغییر می‌کند.\n"
        f"پسورد جدید برای شما ارسال خواهد شد."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید عدم پرداخت", callback_data=f"sudo_non_payer_confirm_{admin.id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("sudo_non_payer_confirm_"))
async def sudo_non_payer_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    # اجرای غیرفعال‌سازی: ابتدا کاربران را غیرفعال کن، سپس پسورد را رندوم کن
    import secrets
    new_password = secrets.token_hex(5)
    try:
        # 1) غیرفعال‌سازی کاربران پنل
        disabled = 0
        try:
            if admin.marzban_username:
                try:
                    # تلاش با کرندنشیال فعلی پنل
                    admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password or "")
                    users = await admin_api.get_users()
                except Exception as e:
                    # اگر احراز هویت پنل شکست خورد، با اکانت اصلی لیست کاربران را بگیر
                    logger.warning(f"Non-payer: falling back to main API for users of {admin.marzban_username}: {e}")
                    users = await marzban_api.get_admin_users(admin.marzban_username)
                for u in users:
                    status = (u.status or "").lower()
                    if status != "disabled":
                        ok = await marzban_api.modify_user(u.username, {"status": "disabled"})
                        if ok:
                            disabled += 1
                        await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Non-payer: error disabling users for admin {admin.id}: {e}")
        
        # 2) ذخیره پسورد اصلی برای بازیابی (در صورت عدم وجود)
        if not admin.original_password and admin.marzban_password:
            await db.update_admin(admin.id, original_password=admin.marzban_password)
        
        # 3) تغییر پسورد در مرزبان به مقدار رندوم
        pwd_changed = await marzban_api.update_admin_password(admin.marzban_username, new_password, is_sudo=False)
        if pwd_changed:
            await db.update_admin(admin.id, marzban_password=new_password)
        else:
            logger.warning(f"Non-payer: failed to change password for {admin.marzban_username}")
        
        # 4) غیرفعال‌سازی پنل در دیتابیس با دلیل عدم پرداخت
        await db.deactivate_admin(admin.id, "عدم پرداخت")
        
        # 5) گزارش به سودو به همراه پسورد جدید
        await callback.message.edit_text(
            f"✅ پنل غیرفعال شد و {disabled} کاربر غیر فعال شدند.\n\n"
            f"👤 پنل: {admin.marzban_username}\n"
            f"🔐 پسورد جدید: `{new_password}`",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]])
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in non-payer flow for admin {admin.id}: {e}")
        await callback.answer("خطا در اجرای عملیات.", show_alert=True)


@sudo_router.callback_query(F.data.startswith("sudo_reset_menu_panel_"))
async def sudo_reset_menu_panel_selected(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    from handlers.admin_handlers import show_reset_menu
    await show_reset_menu(callback, admin)


@sudo_router.callback_query(F.data == "sudo_global_cleanup_confirm")
async def sudo_global_cleanup_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    try:
        from handlers.admin_handlers import global_cleanup_confirm
        await global_cleanup_confirm(callback)
    except Exception as e:
        logger.error(f"Error performing sudo global cleanup: {e}")
        await callback.answer("خطا در اجرای پاکسازی.", show_alert=True)


@sudo_router.callback_query(F.data == "add_admin")
async def add_admin_callback(callback: CallbackQuery, state: FSMContext):
    """Start adding new admin process."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    # Clear any existing state first
    current_state = await state.get_state()
    logger.info(f"User {callback.from_user.id} clearing previous state before add_admin: {current_state}")
    await state.clear()
    
    logger.info(f"Starting comprehensive add admin process for sudo user {callback.from_user.id}")
    
    await callback.message.edit_text(
        "🆕 **افزودن ادمین جدید**\n\n"
        f"{get_progress_indicator(1)}\n"
        "📝 **مرحله ۱ از ۷: User ID**\n\n"
        "لطفاً User ID (آیدی تلگرام) کاربری که می‌خواهید ادمین کنید را ارسال کنید:\n\n"
        "🔍 **نکته:** User ID باید یک عدد صحیح باشد\n"
        "📋 **مثال:** `123456789`\n\n"
        "💡 **راهنما:** برای یافتن User ID می‌توانید از ربات‌های مخصوص یا دستور /start در ربات‌ها استفاده کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=config.BUTTONS["cancel"], callback_data="back_to_main")]
        ])
    )
    
    # Set initial state for the add admin process
    logger.info(f"User {callback.from_user.id} transitioning to state: AddAdminStates.waiting_for_user_id")
    await state.set_state(AddAdminStates.waiting_for_user_id)
    
    # Log state change
    current_state = await state.get_state()
    logger.info(f"User {callback.from_user.id} state set to: {current_state}")
    
    await callback.answer()


@sudo_router.message(AddAdminStates.waiting_for_user_id, F.text)
async def process_admin_user_id(message: Message, state: FSMContext):
    """Process admin user ID input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_admin_user_id' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        admin_user_id = int(message.text.strip())
        logger.info(f"User {user_id} entered admin user ID: {admin_user_id}")
        
        # Note: We no longer check if *any* admin exists with this user_id here.
        # A user can have multiple admin panels. The uniqueness check will be
        # performed on the Marzban username later in process_marzban_username.
        
        # You could add a check to see if the user is valid or exists on Telegram,
        # but getting their info requires them to start the bot, which is not
        # guaranteed at this stage. For now, we accept the ID and proceed.
        
        # Future improvement: If the user hasn't started the bot, maybe ask them
        # to start it so we can capture their username.

        # Save the user ID to state data
        await state.update_data(user_id=admin_user_id)
        
        # Move to next step
        await message.answer(
            f"✅ **User ID دریافت شد:** `{admin_user_id}`\n\n"
            f"{get_progress_indicator(2)}\n"
            "📝 **مرحله ۲ از ۷: نام ادمین**\n\n"
            "لطفاً نام کامل ادمین را وارد کنید:\n\n"
            "📋 **مثال:** `احمد محمدی` یا `مدیر شعبه شمال`\n\n"
            "💡 **نکته:** این نام برای شناسایی ادمین در پنل استفاده می‌شود."
        )
        
        # Change state to waiting for admin name
        logger.info(f"User {user_id} transitioning from waiting_for_user_id to waiting_for_admin_name")
        await state.set_state(AddAdminStates.waiting_for_admin_name)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except ValueError:
        logger.warning(f"User {user_id} entered invalid user ID: {message.text}")
        await message.answer(
            "❌ **فرمت User ID اشتباه است!**\n\n"
            "🔢 لطفاً یک عدد صحیح وارد کنید.\n"
            "📋 **مثال:** `123456789`"
        )
    except Exception as e:
        logger.error(f"Error processing user ID from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش User ID**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(AddAdminStates.waiting_for_admin_name, F.text)
async def process_admin_name(message: Message, state: FSMContext):
    """Process admin name input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_admin_name' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        admin_name = message.text.strip()
        
        # Validate admin name
        if len(admin_name) < 2:
            await message.answer(
                "❌ **نام خیلی کوتاه است!**\n\n"
                "لطفاً نام کامل ادمین را وارد کنید (حداقل ۲ کاراکتر):"
            )
            return
        
        if len(admin_name) > 100:
            await message.answer(
                "❌ **نام خیلی طولانی است!**\n\n"
                "لطفاً نامی کوتاه‌تر وارد کنید (حداکثر ۱۰۰ کاراکتر):"
            )
            return
        
        # Save admin name to state data
        await state.update_data(admin_name=admin_name)
        
        logger.info(f"User {user_id} entered admin name: {admin_name}")
        
        # Move to next step
        await message.answer(
            f"✅ **نام ادمین دریافت شد:** `{admin_name}`\n\n"
            "📝 **مرحله ۳ از ۷: Username مرزبان**\n\n"
            "لطفاً Username برای پنل مرزبان وارد کنید:\n\n"
            "📋 **مثال:** `admin_ahmad` یا `manager_north`\n\n"
            "⚠️ **نکات مهم:**\n"
            "• فقط از حروف انگلیسی، اعداد و خط تیره استفاده کنید\n"
            "• Username نباید قبلاً در مرزبان وجود داشته باشد\n"
            "• حداقل ۳ کاراکتر باشد"
        )
        
        # Change state to waiting for marzban username
        await state.set_state(AddAdminStates.waiting_for_marzban_username)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except Exception as e:
        logger.error(f"Error processing admin name from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش نام ادمین**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(AddAdminStates.waiting_for_marzban_username, F.text)
async def process_marzban_username(message: Message, state: FSMContext):
    """Process Marzban username input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_marzban_username' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        marzban_username = message.text.strip()
        
        # Validate username format
        import re
        if not re.match(r'^[a-zA-Z0-9_-]{3,50}$', marzban_username):
            await message.answer(
                "❌ **فرمت Username اشتباه است!**\n\n"
                "⚠️ **شرایط Username:**\n"
                "• فقط حروف انگلیسی، اعداد، خط تیره (-) و زیرخط (_)\n"
                "• حداقل ۳ و حداکثر ۵۰ کاراکتر\n"
                "• بدون فاصله\n\n"
                "📋 **مثال صحیح:** `admin_ahmad` یا `manager123`"
            )
            return
        
        # Check if username exists in Marzban
        username_exists = await marzban_api.admin_exists(marzban_username)
        if username_exists:
            await message.answer(
                "❌ **Username تکراری است!**\n\n"
                "این Username قبلاً در پنل مرزبان استفاده شده است.\n\n"
                "💡 لطفاً Username متفاوتی انتخاب کنید:"
            )
            return
        
        # Save marzban username to state data
        await state.update_data(marzban_username=marzban_username)
        
        logger.info(f"User {user_id} entered marzban username: {marzban_username}")
        
        # Move to next step
        await message.answer(
            f"✅ **Username مرزبان دریافت شد:** `{marzban_username}`\n\n"
            "📝 **مرحله ۴ از ۷: Password مرزبان**\n\n"
            "لطفاً Password برای پنل مرزبان وارد کنید:\n\n"
            "🔐 **نکات امنیتی:**\n"
            "• حداقل ۸ کاراکتر\n"
            "• ترکیبی از حروف بزرگ، کوچک، اعداد\n"
            "• استفاده از علائم نگارشی توصیه می‌شود\n\n"
            "📋 **مثال:** `MyPass123!` یا `Secure@2024`"
        )
        
        # Change state to waiting for marzban password
        await state.set_state(AddAdminStates.waiting_for_marzban_password)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except Exception as e:
        logger.error(f"Error processing marzban username from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش Username**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(AddAdminStates.waiting_for_marzban_password, F.text)
async def process_marzban_password(message: Message, state: FSMContext):
    """Process Marzban password input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_marzban_password' activated for user {user_id}, current state: {current_state}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        marzban_password = message.text.strip()
        
        # Validate password strength
        if len(marzban_password) < 8:
            await message.answer(
                "❌ **Password خیلی ضعیف است!**\n\n"
                "Password باید حداقل ۸ کاراکتر باشد.\n\n"
                "💡 لطفاً Password قوی‌تری وارد کنید:"
            )
            return
        
        if len(marzban_password) > 100:
            await message.answer(
                "❌ **Password خیلی طولانی است!**\n\n"
                "Password نباید بیش از ۱۰۰ کاراکتر باشد.\n\n"
                "💡 لطفاً Password کوتاه‌تری وارد کنید:"
            )
            return
        
        # Basic password strength check
        has_upper = any(c.isupper() for c in marzban_password)
        has_lower = any(c.islower() for c in marzban_password)
        has_digit = any(c.isdigit() for c in marzban_password)
        
        if not (has_upper or has_lower or has_digit):
            await message.answer(
                "⚠️ **Password ضعیف است!**\n\n"
                "برای امنیت بیشتر، Password باید شامل:\n"
                "• حروف بزرگ یا کوچک\n"
                "• اعداد\n\n"
                "🤔 آیا می‌خواهید همین Password را استفاده کنید؟\n"
                "💡 برای ادامه همین Password را مجدد ارسال کنید، یا Password جدیدی وارد کنید."
            )
            return
        
        # Save marzban password to state data
        await state.update_data(marzban_password=marzban_password)
        
        logger.info(f"User {user_id} entered marzban password (length: {len(marzban_password)})")
        
        # Move to next step
        await message.answer(
            f"✅ **Password دریافت شد** (طول: {len(marzban_password)} کاراکتر)\n\n"
            "📝 **مرحله ۵ از ۷: حجم ترافیک**\n\n"
            "لطفاً حداکثر حجم ترافیک مجاز را به گیگابایت وارد کنید:\n\n"
            "📋 **مثال‌ها:**\n"
            "• `100` برای ۱۰۰ گیگابایت\n"
            "• `50.5` برای ۵۰.۵ گیگابایت\n"
            "• `1000` برای ۱ ترابایت\n\n"
            "💡 **نکته:** عدد اعشاری هم قابل قبول است"
        )
        
        # Change state to waiting for traffic volume
        await state.set_state(AddAdminStates.waiting_for_traffic_volume)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except Exception as e:
        logger.error(f"Error processing marzban password from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش Password**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(AddAdminStates.waiting_for_traffic_volume, F.text)
async def process_traffic_volume(message: Message, state: FSMContext):
    """Process traffic volume input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_traffic_volume' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        traffic_gb = float(message.text.strip())
        
        # Validate traffic volume
        if traffic_gb <= 0:
            await message.answer(
                "❌ **حجم ترافیک نامعتبر!**\n\n"
                "حجم ترافیک باید عددی مثبت باشد.\n\n"
                "💡 لطفاً عدد صحیحی وارد کنید:"
            )
            return
        
        if traffic_gb > 10000:  # More than 10TB seems unrealistic
            await message.answer(
                "⚠️ **حجم ترافیک خیلی زیاد است!**\n\n"
                f"آیا واقعاً می‌خواهید {traffic_gb} گیگابایت تخصیص دهید؟\n\n"
                "🤔 برای تایید همین مقدار را مجدد ارسال کنید، یا مقدار کمتری وارد کنید."
            )
            return
        
        # Convert GB to bytes
        traffic_bytes = gb_to_bytes(traffic_gb)
        
        # Save traffic to state data
        await state.update_data(traffic_gb=traffic_gb, traffic_bytes=traffic_bytes)
        
        logger.info(f"User {user_id} entered traffic volume: {traffic_gb} GB ({traffic_bytes} bytes)")
        
        # Move to next step
        await message.answer(
            f"✅ **حجم ترافیک دریافت شد:** {traffic_gb} گیگابایت\n\n"
            "📝 **مرحله ۶ از ۷: تعداد کاربر مجاز**\n\n"
            "لطفاً حداکثر تعداد کاربری که این ادمین می‌تواند ایجاد کند را وارد کنید:\n\n"
            "📋 **مثال‌ها:**\n"
            "• `10` برای ۱۰ کاربر\n"
            "• `50` برای ۵۰ کاربر\n"
            "• `100` برای ۱۰۰ کاربر\n\n"
            "💡 **نکته:** عدد صحیح وارد کنید"
        )
        
        # Change state to waiting for max users
        await state.set_state(AddAdminStates.waiting_for_max_users)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except ValueError:
        logger.warning(f"User {user_id} entered invalid traffic volume: {message.text}")
        await message.answer(
            "❌ **فرمت حجم ترافیک اشتباه است!**\n\n"
            "🔢 لطفاً یک عدد صحیح یا اعشاری وارد کنید.\n"
            "📋 **مثال:** `100` یا `50.5`"
        )
    except Exception as e:
        logger.error(f"Error processing traffic volume from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش حجم ترافیک**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(AddAdminStates.waiting_for_max_users, F.text)
async def process_max_users(message: Message, state: FSMContext):
    """Process max users input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_max_users' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        max_users = int(message.text.strip())
        
        # Validate max users
        if max_users <= 0:
            await message.answer(
                "❌ **تعداد کاربر نامعتبر!**\n\n"
                "تعداد کاربر باید عددی مثبت باشد.\n\n"
                "💡 لطفاً عدد صحیحی وارد کنید:"
            )
            return
        
        if max_users > 10000:  # More than 10k users seems unrealistic for one admin
            await message.answer(
                "⚠️ **تعداد کاربر خیلی زیاد است!**\n\n"
                f"آیا واقعاً می‌خواهید {max_users} کاربر تخصیص دهید؟\n\n"
                "🤔 برای تایید همین مقدار را مجدد ارسال کنید، یا عدد کمتری وارد کنید."
            )
            return
        
        # Save max users to state data
        await state.update_data(max_users=max_users)
        
        logger.info(f"User {user_id} entered max users: {max_users}")
        
        # Move to next step
        await message.answer(
            f"✅ **تعداد کاربر مجاز دریافت شد:** {max_users} کاربر\n\n"
            "📝 **مرحله ۷ از ۷: مدت اعتبار**\n\n"
            "لطفاً مدت اعتبار این ادمین را به روز وارد کنید:\n\n"
            "📋 **مثال‌ها:**\n"
            "• `30` برای ۳۰ روز (یک ماه)\n"
            "• `90` برای ۹۰ روز (سه ماه)\n"
            "• `365` برای ۳۶۵ روز (یک سال)\n\n"
            "💡 **نکته:** پس از انقضا، ادمین غیرفعال می‌شود"
        )
        
        # Change state to waiting for validity period
        await state.set_state(AddAdminStates.waiting_for_validity_period)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except ValueError:
        logger.warning(f"User {user_id} entered invalid max users: {message.text}")
        await message.answer(
            "❌ **فرمت تعداد کاربر اشتباه است!**\n\n"
            "🔢 لطفاً یک عدد صحیح وارد کنید.\n"
            "📋 **مثال:** `10` یا `50`"
        )
    except Exception as e:
        logger.error(f"Error processing max users from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش تعداد کاربر**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(AddAdminStates.waiting_for_validity_period, F.text)
async def process_validity_period(message: Message, state: FSMContext):
    """Process validity period input."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_validity_period' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted admin addition")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        validity_days = int(message.text.strip())
        
        # Validate validity period
        if validity_days <= 0:
            await message.answer(
                "❌ **مدت اعتبار نامعتبر!**\n\n"
                "مدت اعتبار باید عددی مثبت باشد.\n\n"
                "💡 لطفاً تعداد روز را وارد کنید:"
            )
            return
        
        if validity_days > 3650:  # More than 10 years seems unrealistic
            await message.answer(
                "⚠️ **مدت اعتبار خیلی طولانی است!**\n\n"
                f"آیا واقعاً می‌خواهید {validity_days} روز ({validity_days//365} سال) تخصیص دهید؟\n\n"
                "🤔 برای تایید همین مقدار را مجدد ارسال کنید، یا عدد کمتری وارد کنید."
            )
            return
        
        # Convert days to seconds
        validity_seconds = days_to_seconds(validity_days)
        
        # Save validity period to state data
        await state.update_data(validity_days=validity_days, validity_seconds=validity_seconds)
        
        logger.info(f"User {user_id} entered validity period: {validity_days} days ({validity_seconds} seconds)")
        
        # Get all collected data for confirmation
        data = await state.get_data()
        admin_user_id = data.get("user_id")
        admin_name = data.get("admin_name")
        marzban_username = data.get("marzban_username")
        traffic_gb = data.get("traffic_gb")
        max_users = data.get("max_users")
        
        # Show confirmation with summary
        confirmation_text = (
            "📋 **خلاصه اطلاعات ادمین جدید**\n\n"
            f"👤 **User ID:** `{admin_user_id}`\n"
            f"📝 **نام ادمین:** {admin_name}\n"
            f"🔐 **Username مرزبان:** {marzban_username}\n"
            f"📊 **حجم ترافیک:** {traffic_gb} گیگابایت\n"
            f"👥 **تعداد کاربر مجاز:** {max_users} کاربر\n"
            f"📅 **مدت اعتبار:** {validity_days} روز\n\n"
            "❓ **آیا اطلاعات صحیح است؟**\n\n"
            "✅ برای **تایید و ایجاد ادمین** دکمه تایید را بزنید\n"
            "❌ برای **لغو** دکمه لغو را بزنید"
        )
        
        # Create confirmation keyboard
        confirmation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تایید و ایجاد", callback_data="confirm_create_admin"),
                InlineKeyboardButton(text="❌ لغو", callback_data="back_to_main")
            ]
        ])
        
        await message.answer(confirmation_text, reply_markup=confirmation_keyboard)
        
        # Change state to waiting for confirmation
        await state.set_state(AddAdminStates.waiting_for_confirmation)
        
        # Log state change
        current_state = await state.get_state()
        logger.info(f"User {user_id} state changed to: {current_state}")
        
    except ValueError:
        logger.warning(f"User {user_id} entered invalid validity period: {message.text}")
        await message.answer(
            "❌ **فرمت مدت اعتبار اشتباه است!**\n\n"
            "🔢 لطفاً تعداد روز را به عدد صحیح وارد کنید.\n"
            "📋 **مثال:** `30` یا `90`"
        )
    except Exception as e:
        logger.error(f"Error processing validity period from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش مدت اعتبار**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.callback_query(F.data == "confirm_create_admin")
async def confirm_create_admin(callback: CallbackQuery, state: FSMContext):
    """Confirm and create the admin."""
    user_id = callback.from_user.id
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    # Verify state
    current_state = await state.get_state()
    if current_state != AddAdminStates.waiting_for_confirmation:
        await callback.answer("جلسه منقضی شده", show_alert=True)
        await state.clear()
        return
    
    try:
        # Get all collected data
        data = await state.get_data()
        admin_user_id = data.get("user_id")
        admin_name = data.get("admin_name")
        marzban_username = data.get("marzban_username")
        marzban_password = data.get("marzban_password")
        traffic_bytes = data.get("traffic_bytes")
        max_users = data.get("max_users")
        validity_seconds = data.get("validity_seconds")
        validity_days = data.get("validity_days")
        
        # Validate required data
        if not all([admin_user_id, admin_name, marzban_username, marzban_password, traffic_bytes, max_users, validity_seconds]):
            logger.error(f"Missing required data in state for user {user_id}")
            await callback.message.edit_text(
                "❌ **خطا: اطلاعات ناقص**\n\n"
                "اطلاعات جلسه ناقص است. لطفاً مجدداً شروع کنید.",
                reply_markup=get_sudo_keyboard()
            )
            await state.clear()
            await callback.answer()
            return
        
        # Update message to show progress
        await callback.message.edit_text(
            "⏳ **در حال ایجاد ادمین...**\n\n"
            "لطفاً صبر کنید..."
        )
        
        logger.info(f"Creating admin: {admin_user_id} with username: {marzban_username}")
        
        # Step 1: Create admin in Marzban panel
        marzban_success = await marzban_api.create_admin(
            username=marzban_username,
            password=marzban_password,
            telegram_id=admin_user_id
        )
        
        if not marzban_success:
            logger.error(f"Failed to create admin in Marzban: {marzban_username}")
            await callback.message.edit_text(
                "❌ **خطا در ایجاد ادمین در پنل مرزبان**\n\n"
                "علت‌های احتمالی:\n"
                "• Username تکراری است\n"
                "• اتصال به مرزبان برقرار نیست\n"
                "• تنظیمات API نادرست است\n"
                "• مشکل در احراز هویت\n\n"
                "⚠️ **هیچ تغییری در سیستم انجام نشد**\n"
                "لطفاً مشکل را بررسی کرده و مجدداً تلاش کنید.",
                reply_markup=get_sudo_keyboard()
            )
            await state.clear()
            await callback.answer()
            return
        
        # Step 2: Create admin in local database
        admin = AdminModel(
            user_id=admin_user_id,
            admin_name=admin_name,
            marzban_username=marzban_username,
            marzban_password=marzban_password,  # Store for management purposes
            max_users=max_users,
            max_total_time=validity_seconds,
            max_total_traffic=traffic_bytes,
            validity_days=validity_days
        )
        
        db_success = await db.add_admin(admin)
        
        if not db_success:
            logger.error(f"Failed to add admin to database: {admin_user_id}")
            # Try to remove from Marzban if database failed
            try:
                await marzban_api.delete_admin(marzban_username)
                logger.info(f"Cleaned up admin {marzban_username} from Marzban after database failure")
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup admin {marzban_username} from Marzban: {cleanup_error}")
            
            await callback.message.edit_text(
                "❌ **خطا در ذخیره اطلاعات در پایگاه داده**\n\n"
                "ادمین در پنل مرزبان ایجاد شد اما در پایگاه داده ربات ذخیره نشد.\n\n"
                "🔄 **اقدام انجام شده:** ادمین از مرزبان نیز حذف شد تا تناقض پیش نیاید.\n\n"
                "⚠️ لطفاً مشکل پایگاه داده را بررسی و مجدداً تلاش کنید.",
                reply_markup=get_sudo_keyboard()
            )
            await state.clear()
            await callback.answer()
            return
        
        # Step 3: Send notifications
        admin_info = {
            "user_id": admin_user_id,
            "admin_name": admin_name,
            "marzban_username": marzban_username,
            "max_users": max_users,
            "max_total_time": validity_seconds,
            "max_total_traffic": traffic_bytes,
            "validity_days": validity_days
        }
        
        await notify_admin_added(callback.bot, admin_user_id, admin_info, user_id)
        
        # Step 4: Show success message
        success_text = (
            "✅ **پنل ادمین با موفقیت ایجاد شد!**\n\n"
            f"👤 **User ID:** {admin_user_id}\n"
            f"📝 **نام ادمین:** {admin_name}\n"
            f"🔐 **Username مرزبان:** {marzban_username}\n"
            f"👥 **حداکثر کاربر:** {max_users}\n"
            f"📊 **حجم ترافیک:** {await format_traffic_size(traffic_bytes)}\n"
            f"📅 **مدت اعتبار:** {validity_days} روز\n\n"
            "🎉 **مراحل انجام شده:**\n"
            "✅ ایجاد در پنل مرزبان\n"
            "✅ ذخیره در پایگاه داده\n"
            "✅ ارسال اطلاع‌رسانی\n\n"
            "🔔 کاربر مربوطه می‌تواند از ربات استفاده کند و به پنل‌های خود دسترسی داشته باشد."
        )
        
        await callback.message.edit_text(success_text, reply_markup=get_sudo_keyboard())
        
        logger.info(f"Admin {admin_user_id} successfully created by {user_id}")
        
        await state.clear() # Clear state after successful creation
        await callback.answer("ادمین با موفقیت ایجاد شد! ✅")
        
    except Exception as e:
        logger.error(f"Error creating admin for {user_id}: {e}")
        await callback.message.edit_text(
            f"❌ **خطا در ایجاد ادمین**\n\n"
            f"خطا: {str(e)}\n\n"
            "لطفاً مجدداً تلاش کنید.",
            reply_markup=get_sudo_keyboard()
        )
        await state.clear()
        await callback.answer()


@sudo_router.message(AddAdminStates.waiting_for_confirmation, F.text)
async def handle_text_in_confirmation_state(message: Message, state: FSMContext):
    """Handle text messages in confirmation state."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} sent text in confirmation state: {message.text}")
    
    await message.answer(
        "⏸️ **در انتظار تایید**\n\n"
        "لطفاً از دکمه‌های زیر استفاده کنید:\n"
        "✅ **تایید و ایجاد** - برای ایجاد ادمین\n"
        "❌ **لغو** - برای لغو عملیات\n\n"
        "📝 **اطلاعات وارد شده قابل ویرایش نیست.** برای تغییر، عملیات را لغو کرده و مجدداً شروع کنید."
    )


# Add help handlers for when users send unrelated commands during FSM flow
@sudo_router.message(AddAdminStates.waiting_for_user_id, ~F.text)
@sudo_router.message(AddAdminStates.waiting_for_admin_name, ~F.text)  
@sudo_router.message(AddAdminStates.waiting_for_marzban_username, ~F.text)
@sudo_router.message(AddAdminStates.waiting_for_marzban_password, ~F.text)
@sudo_router.message(AddAdminStates.waiting_for_traffic_volume, ~F.text)
@sudo_router.message(AddAdminStates.waiting_for_max_users, ~F.text)
@sudo_router.message(AddAdminStates.waiting_for_validity_period, ~F.text)
async def handle_non_text_in_fsm(message: Message, state: FSMContext):
    """Handle non-text messages during FSM flow."""
    current_state = await state.get_state()
    logger.info(f"User {message.from_user.id} sent non-text message in state {current_state}")
    
    state_names = {
        "AddAdminStates:waiting_for_user_id": "User ID",
        "AddAdminStates:waiting_for_admin_name": "نام ادمین",
        "AddAdminStates:waiting_for_marzban_username": "Username مرزبان",
        "AddAdminStates:waiting_for_marzban_password": "Password مرزبان",
        "AddAdminStates:waiting_for_traffic_volume": "حجم ترافیک",
        "AddAdminStates:waiting_for_max_users": "تعداد کاربر مجاز",
        "AddAdminStates:waiting_for_validity_period": "مدت اعتبار"
    }
    
    current_step = state_names.get(current_state, "اطلاعات")
    
    await message.answer(
        f"📝 **در انتظار: {current_step}**\n\n"
        "لطفاً فقط متن ارسال کنید. فایل، عکس، صدا و سایر انواع پیام پذیرفته نمی‌شوند.\n\n"
        "❌ برای لغو عملیات /start را بزنید."
    )


# Add handler for commands during FSM (except /start which should cancel)
@sudo_router.message(F.text.startswith('/') & ~F.text.startswith('/start'))
async def handle_commands_in_fsm(message: Message, state: FSMContext):
    """Handle commands during FSM flow (except /start)."""
    current_state = await state.get_state()
    
    # Only handle if we're in an FSM state
    if not current_state or not current_state.startswith('AddAdminStates:'):
        return
        
    command = message.text
    logger.info(f"User {message.from_user.id} sent command {command} in state {current_state}")
    
    await message.answer(
        f"⚠️ **عملیات در حال انجام**\n\n"
        f"شما در حال افزودن ادمین جدید هستید.\n"
        f"دستور `{command}` در این مرحله قابل اجرا نیست.\n\n"
        "🔄 **گزینه‌های شما:**\n"
        "• ادامه فرآیند افزودن ادمین\n"
        "• ارسال /start برای لغو و بازگشت به منوی اصلی\n\n"
        "💡 پس از تکمیل یا لغو، می‌توانید از دستورات استفاده کنید."
    )


@sudo_router.callback_query(F.data == "remove_admin")
async def remove_admin_callback(callback: CallbackQuery):
    """Show panel list for complete deletion."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    # Get only active admins for deletion
    all_admins = await db.get_all_admins()
    active_admins = [admin for admin in all_admins if admin.is_active]
    
    if not active_admins:
        await callback.message.edit_text(
            "❌ هیچ پنل فعالی برای حذف یافت نشد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "🗑️ انتخاب پنل برای حذف کامل (پنل و تمام کاربرانش):",
        reply_markup=get_panel_list_keyboard(active_admins, "confirm_deactivate")
    )
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("confirm_deactivate_"))
async def confirm_deactivate_panel(callback: CallbackQuery):
    """Confirm panel deactivation."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    
    if not admin:
        await callback.answer("پنل یافت نشد", show_alert=True)
        return
    
    # Completely delete the panel and all users for manual deactivation
    success, err = await delete_admin_panel_completely(admin_id, "غیرفعالسازی دستی توسط سودو")
    
    if success:
        panel_name = admin.admin_name or admin.marzban_username or f"Panel-{admin.id}"
        await callback.message.edit_text(
            f"✅ پنل {panel_name} با موفقیت حذف شد.\n\n"
            f"👤 کاربر: {admin.username or admin.user_id}\n"
            f"🏷️ نام پنل: {panel_name}\n"
            f"🔐 نام کاربری مرزبان: {admin.marzban_username}\n\n"
            "🗑️ پنل و تمام کاربران آن به طور کامل حذف شدند.",
            reply_markup=get_sudo_keyboard()
        )
    else:
        await callback.message.edit_text(
            ("❌ خطا در حذف پنل." + (f"\n\nجزئیات: {err}" if err else "")),
            reply_markup=get_sudo_keyboard()
        )
    
    await callback.answer()


@sudo_router.callback_query(F.data == "edit_panel")
async def edit_panel_callback(callback: CallbackQuery):
    """Show panel list for editing."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    # Get all admins for editing
    admins = await db.get_all_admins()
    
    if not admins:
        await callback.message.edit_text(
            "❌ هیچ پنلی برای ویرایش یافت نشد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        config.MESSAGES["select_panel_to_edit"],
        reply_markup=get_panel_list_keyboard(admins, "start_edit")
    )
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("start_edit_"))
async def start_edit_panel(callback: CallbackQuery, state: FSMContext):
    """Start editing a specific panel."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    
    if not admin:
        await callback.answer("پنل یافت نشد", show_alert=True)
        return
    
    # Store admin_id in state
    await state.update_data(admin_id=admin_id)
    
    # Show current limits and ask for new traffic
    from utils.notify import bytes_to_gb, seconds_to_days
    current_traffic = bytes_to_gb(admin.max_total_traffic)
    current_time = seconds_to_days(admin.max_total_time)
    
    panel_name = admin.admin_name or admin.marzban_username or f"Panel-{admin.id}"
    
    await callback.message.edit_text(
        f"✏️ **ویرایش پنل {panel_name}**\n\n"
        f"👤 کاربر: {admin.username or admin.user_id}\n"
        f"🔐 نام کاربری مرزبان: {admin.marzban_username}\n\n"
        f"📊 **محدودیت‌های فعلی:**\n"
        f"📡 ترافیک: {current_traffic} گیگابایت\n"
        f"⏰ مدت زمان: {current_time} روز\n\n"
        f"📝 **مرحله ۱ از ۳: ترافیک جدید**\n\n"
        "لطفاً مقدار ترافیک جدید را به گیگابایت وارد کنید:\n\n"
        "📋 **مثال:** `500` برای ۵۰۰ گیگابایت\n"
        "💡 **نکته:** عدد صحیح وارد کنید",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=config.BUTTONS["cancel"], callback_data="back_to_main")]
        ])
    )
    
    await state.set_state(EditPanelStates.waiting_for_traffic_volume)
    await callback.answer()


@sudo_router.message(EditPanelStates.waiting_for_traffic_volume, F.text)
async def process_edit_traffic(message: Message, state: FSMContext):
    """Process new traffic volume for editing."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_edit_traffic' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted panel editing")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        traffic_gb = int(message.text.strip())
        
        if traffic_gb <= 0:
            await message.answer(
                "❌ **مقدار ترافیک نامعتبر!**\n\n"
                "لطفاً عددی بزرگتر از صفر وارد کنید:"
            )
            return
        
        if traffic_gb > 10000:  # Reasonable upper limit
            await message.answer(
                "❌ **مقدار ترافیک خیلی زیاد!**\n\n"
                "لطفاً مقداری کمتر از ۱۰۰۰۰ گیگابایت وارد کنید:"
            )
            return
        
        # Save traffic to state
        await state.update_data(traffic_gb=traffic_gb)
        
        # Get admin info for display
        data = await state.get_data()
        admin_id = data.get('admin_id')
        admin = await db.get_admin_by_id(admin_id)
        
        from utils.notify import seconds_to_days
        current_time = seconds_to_days(admin.max_total_time)
        
        await message.answer(
            f"✅ **ترافیک جدید:** {traffic_gb} گیگابایت\n\n"
            f"📝 **مرحله ۲ از ۳: مدت زمان جدید**\n\n"
            f"⏰ **مدت زمان فعلی:** {current_time} روز\n\n"
            "لطفاً مدت زمان جدید را به روز وارد کنید:\n\n"
            "📋 **مثال:** `30` برای ۳۰ روز\n"
            "💡 **نکته:** عدد صحیح وارد کنید"
        )
        
        await state.set_state(EditPanelStates.waiting_for_validity_period)
        
    except ValueError:
        await message.answer(
            "❌ **فرمت ترافیک اشتباه است!**\n\n"
            "🔢 لطفاً یک عدد صحیح وارد کنید.\n"
            "📋 **مثال:** `500`"
        )
    except Exception as e:
        logger.error(f"Error processing traffic from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش ترافیک**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.message(EditPanelStates.waiting_for_validity_period, F.text)
async def process_edit_time(message: Message, state: FSMContext):
    """Process new validity period for editing."""
    user_id = message.from_user.id
    current_state = await state.get_state()
    logger.info(f"FSM handler 'process_edit_time' activated for user {user_id}, current state: {current_state}, message: {message.text}")
    
    # Verify user is sudo admin
    if user_id not in config.SUDO_ADMINS:
        logger.warning(f"Non-sudo user {user_id} attempted panel editing")
        await message.answer("⛔ شما مجاز به انجام این عمل نیستید.")
        await state.clear()
        return
    
    try:
        validity_days = int(message.text.strip())
        
        if validity_days <= 0:
            await message.answer(
                "❌ **مدت زمان نامعتبر!**\n\n"
                "لطفاً عددی بزرگتر از صفر وارد کنید:"
            )
            return
        
        if validity_days > 3650:  # Max 10 years
            await message.answer(
                "❌ **مدت زمان خیلی زیاد!**\n\n"
                "لطفاً مقداری کمتر از ۳۶۵۰ روز وارد کنید:"
            )
            return
        
        # Save time to state
        await state.update_data(validity_days=validity_days)
        
        # Get all data for confirmation
        data = await state.get_data()
        admin_id = data.get('admin_id')
        traffic_gb = data.get('traffic_gb')
        admin = await db.get_admin_by_id(admin_id)
        
        from utils.notify import bytes_to_gb, seconds_to_days
        old_traffic = bytes_to_gb(admin.max_total_traffic)
        old_time = seconds_to_days(admin.max_total_time)
        
        panel_name = admin.admin_name or admin.marzban_username or f"Panel-{admin.id}"
        
        # Show confirmation
        confirmation_text = (
            f"📋 **تأیید نهایی ویرایش پنل**\n\n"
            f"🏷️ **پنل:** {panel_name}\n"
            f"👤 **کاربر:** {admin.username or admin.user_id}\n"
            f"🔐 **نام کاربری مرزبان:** {admin.marzban_username}\n\n"
            f"📊 **تغییرات:**\n"
            f"📡 ترافیک: {old_traffic} GB ← {traffic_gb} GB\n"
            f"⏰ مدت زمان: {old_time} روز ← {validity_days} روز\n\n"
            "❓ آیا از انجام این تغییرات اطمینان دارید؟"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید", callback_data="confirm_edit_panel"),
                InlineKeyboardButton(text="❌ لغو", callback_data="back_to_main")
            ]
        ])
        
        await message.answer(confirmation_text, reply_markup=keyboard)
        await state.set_state(EditPanelStates.waiting_for_confirmation)
        
    except ValueError:
        await message.answer(
            "❌ **فرمت مدت زمان اشتباه است!**\n\n"
            "🔢 لطفاً یک عدد صحیح وارد کنید.\n"
            "📋 **مثال:** `30`"
        )
    except Exception as e:
        logger.error(f"Error processing time from {user_id}: {e}")
        await message.answer(
            "❌ **خطا در پردازش مدت زمان**\n\n"
            "لطفاً مجدداً تلاش کنید یا /start را بزنید."
        )
        await state.clear()


@sudo_router.callback_query(F.data == "confirm_edit_panel")
async def confirm_edit_panel(callback: CallbackQuery, state: FSMContext):
    """Confirm panel editing."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        await state.clear()
        return
    
    try:
        # Get data from state
        data = await state.get_data()
        admin_id = data.get('admin_id')
        traffic_gb = data.get('traffic_gb')
        validity_days = data.get('validity_days')
        
        if not all([admin_id, traffic_gb, validity_days]):
            await callback.answer("داده‌های ناکافی", show_alert=True)
            await state.clear()
            return
        
        # Convert to database format
        from utils.notify import gb_to_bytes, days_to_seconds
        max_total_traffic = gb_to_bytes(traffic_gb)
        max_total_time = days_to_seconds(validity_days)
        
        # Update in database
        success = await db.update_admin(
            admin_id, 
            max_total_traffic=max_total_traffic,
            max_total_time=max_total_time
        )
        
        if success:
            admin = await db.get_admin_by_id(admin_id)
            panel_name = admin.admin_name or admin.marzban_username or f"Panel-{admin.id}"
            
            await callback.message.edit_text(
                f"✅ پنل {panel_name} با موفقیت ویرایش شد!\n\n"
                f"📊 **محدودیت‌های جدید:**\n"
                f"📡 ترافیک: {traffic_gb} گیگابایت\n"
                f"⏰ مدت زمان: {validity_days} روز\n\n"
                f"👤 کاربر: {admin.username or admin.user_id}\n"
                f"🔐 نام کاربری مرزبان: {admin.marzban_username}",
                reply_markup=get_sudo_keyboard()
            )
            
            # Log the change
            from models.schemas import LogModel
            log = LogModel(
                admin_user_id=admin.user_id,
                action="panel_limits_edited",
                details=f"Panel {admin_id} limits updated: Traffic={traffic_gb}GB, Time={validity_days}days"
            )
            await db.add_log(log)
            
        else:
            await callback.message.edit_text(
                "❌ خطا در ویرایش پنل.",
                reply_markup=get_sudo_keyboard()
            )
        
        await state.clear()
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error confirming panel edit: {e}")
        await callback.message.edit_text(
            "❌ خطا در ویرایش پنل.",
            reply_markup=get_sudo_keyboard()
        )
        await state.clear()
        await callback.answer()


async def get_admin_list_text() -> str:
    """Get admin list text. Shared logic for both callback and command handlers."""
    admins = await db.get_all_admins()
    
    if not admins:
        return "❌ هیچ ادمینی یافت نشد."
    
    text = "📋 لیست همه ادمین‌ها:\n\n"
    
    # Group admins by user_id to show multiple panels per user
    user_panels = {}
    for admin in admins:
        if admin.user_id not in user_panels:
            user_panels[admin.user_id] = []
        user_panels[admin.user_id].append(admin)
    
    counter = 1
    for user_id, user_admins in user_panels.items():
        text += f"{counter}. 👨‍💼 کاربر ID: {user_id}\n"
        
        for i, admin in enumerate(user_admins, 1):
            status = "✅ فعال" if admin.is_active else "❌ غیرفعال"
            panel_name = admin.admin_name or f"پنل {i}"
            
            text += f"   🔹 {panel_name} {status}\n"
            text += f"      🆔 پنل ID: {admin.id}\n"
            text += f"      👤 نام کاربری مرزبان: {admin.marzban_username or 'نامشخص'}\n"
            text += f"      🏷️ نام تلگرام: {admin.username or 'نامشخص'}\n"
            text += f"      👥 حداکثر کاربر: {admin.max_users}\n"
            text += f"      📅 تاریخ ایجاد: {admin.created_at.strftime('%Y-%m-%d %H:%M') if admin.created_at else 'نامشخص'}\n"
            
            if not admin.is_active and admin.deactivated_reason:
                text += f"      ❌ دلیل غیرفعالی: {admin.deactivated_reason}\n"
            
            text += "\n"
        
        counter += 1
        text += "\n"
    
    return text


async def get_admin_status_text() -> str:
    """Get admin status text. Shared logic for both callback and command handlers."""
    admins = await db.get_all_admins()
    
    if not admins:
        return "❌ هیچ ادمینی یافت نشد."
    
    text = "📊 وضعیت تفصیلی ادمین‌ها:\n\n"
    
    # Group admins by user_id to show multiple panels per user
    user_panels = {}
    for admin in admins:
        if admin.user_id not in user_panels:
            user_panels[admin.user_id] = []
        user_panels[admin.user_id].append(admin)
    
    for user_id, user_admins in user_panels.items():
        text += f"👨‍💼 کاربر ID: {user_id}\n"
        
        for i, admin in enumerate(user_admins, 1):
            status = "✅ فعال" if admin.is_active else "❌ غیرفعال"
            panel_name = admin.admin_name or f"پنل {i}"
            
            text += f"   🔹 {panel_name} ({admin.marzban_username}) {status}\n"
            
            # Get admin stats using their own credentials
            try:
                if admin.is_active and admin.marzban_username and admin.marzban_password:
                    admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
                    admin_stats = await admin_api.get_admin_stats()
                    
                    # Update and use historical peak users to prevent deletion from reducing stats
                    try:
                        peak_users = max(int(getattr(admin, 'users_historical_peak', 0) or 0), int(admin_stats.total_users or 0))
                        if peak_users != (getattr(admin, 'users_historical_peak', 0) or 0):
                            await db.update_admin(admin.id, users_historical_peak=peak_users)
                    except Exception:
                        peak_users = admin_stats.total_users

                    # Calculate usage percentages (time based on real elapsed since panel creation)
                    user_percentage = (peak_users / admin.max_users * 100) if admin.max_users > 0 else 0
                    traffic_percentage = (admin_stats.total_traffic_used / admin.max_total_traffic * 100) if admin.max_total_traffic > 0 else 0
                    from datetime import datetime as _dt
                    created_at = admin.created_at or _dt.utcnow()
                    elapsed_seconds = max(0, (_dt.utcnow() - created_at).total_seconds())
                    time_percentage = (elapsed_seconds / admin.max_total_time * 100) if admin.max_total_time > 0 else 0
                    
                    max_traffic_txt = "نامحدود" if (admin.max_total_traffic or 0) == 0 else await format_traffic_size(admin.max_total_traffic)
                    max_time_txt = "نامحدود" if (admin.max_total_time or 0) == 0 else await format_time_duration(admin.max_total_time)
                    max_users_txt = "نامحدود" if ((admin.max_users or 0) >= 1000000) else f"{admin.max_users}"
                    text += f"      👥 کاربران: {admin_stats.total_users}/{max_users_txt} ({user_percentage:.1f}%)\n"
                    try:
                        expired_c = (admin_stats.counts_extra or {}).get("expired", 0)
                        quota_full_c = (admin_stats.counts_extra or {}).get("quota_full", 0)
                        disabled_c = (admin_stats.counts_extra or {}).get("disabled", 0)
                        active_c = (admin_stats.counts_by_status or {}).get("active", 0)
                        text += f"      ├ فعلی: {admin_stats.total_users} (فعال: {active_c}, منقضی: {expired_c}, پرحجم: {quota_full_c}, غیرفعال: {disabled_c})\n"
                        text += f"      └ اوج تاریخی: {peak_users}\n"
                    except Exception:
                        pass
                    text += f"      📊 ترافیک: {await format_traffic_size(admin_stats.total_traffic_used)}/{max_traffic_txt} ({traffic_percentage:.1f}%)\n"
                    text += f"      ⏱️ زمان: {await format_time_duration(int(elapsed_seconds))}/{max_time_txt} ({time_percentage:.1f}%)\n"
                    
                    # Show warning if approaching limits
                    if any(p >= 80 for p in [user_percentage, traffic_percentage, time_percentage]):
                        text += f"      ⚠️ نزدیک به محدودیت!\n"
                        
                elif not admin.is_active:
                    text += f"      ❌ غیرفعال"
                    if admin.deactivated_reason:
                        text += f" - {admin.deactivated_reason}"
                    text += "\n"
                else:
                    text += f"      ❌ اطلاعات احراز هویت ناکامل\n"
                    
            except Exception as e:
                text += f"      ❌ خطا در دریافت آمار: {str(e)[:50]}...\n"
            
            text += "\n"
        
        text += "\n"
    
    return text


@sudo_router.callback_query(F.data == "list_admins")
async def list_admins_callback(callback: CallbackQuery):
    """Show list of all admins."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    text = await get_admin_list_text()
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
        ])
    )
    await callback.answer()


@sudo_router.callback_query(F.data == "admin_status")
async def admin_status_callback(callback: CallbackQuery):
    """Show detailed status of all admins."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await show_admin_status_page(callback, 1)
    await callback.answer()


async def show_admin_status_page(message_or_callback: Message | CallbackQuery, page: int = 1):
    if isinstance(message_or_callback, CallbackQuery):
        chat = message_or_callback.message
    else:
        chat = message_or_callback
    admins = await db.get_all_admins()
    if not admins:
        await chat.edit_text(
            "❌ هیچ ادمینی یافت نشد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]])
        )
        return
    per_page = 30
    total = len(admins)
    max_page = (total + per_page - 1) // per_page
    page = max(1, min(page, max_page))
    start = (page - 1) * per_page
    end = min(start + per_page, total)
    page_admins = admins[start:end]

    rows = []
    for a in page_admins:
        panel_name = a.admin_name or a.marzban_username or f"Panel {a.id}"
        # Use last recorded traffic from usage_reports (per user_id)
        try:
            report = await db.get_latest_usage_report(a.user_id)
            used_bytes = int(getattr(report, 'current_total_traffic', 0) or 0) if report else 0
        except Exception:
            used_bytes = 0
        used_txt = await format_traffic_size(used_bytes)
        btn_text = f"{panel_name} — {used_txt}"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_status_detail_{a.id}_p{page}")])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"admin_status_page_{page-1}"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"admin_status_page_{page+1}"))
    rows.append(nav_row or [InlineKeyboardButton(text=str(page), callback_data=f"admin_status_page_{page}")])
    rows.append([InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")])

    header = f"📊 لیست ادمین‌ها (صفحه {page}/{max_page})\n\nبرای مشاهده جزئیات، یکی را انتخاب کنید:"
    try:
        await chat.edit_text(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        # Fallback to send new message if edit fails
        await chat.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@sudo_router.callback_query(F.data.startswith("admin_status_page_"))
async def admin_status_page_nav(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    try:
        page = int(callback.data.split("_")[-1])
    except Exception:
        page = 1
    await show_admin_status_page(callback, page)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("admin_status_detail_"))
async def admin_status_detail(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    parts = callback.data.split("_")
    try:
        admin_id_part = parts[-2]
        page_part = parts[-1]
        admin_id = int(admin_id_part)
        page = int(page_part[1:]) if page_part.startswith('p') else 1
    except Exception:
        await callback.answer("درک دستور نامعتبر است", show_alert=True)
        return
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    panel_name = admin.admin_name or admin.marzban_username or f"Panel {admin.id}"
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        admin_stats = await admin_api.get_admin_stats()
        from datetime import datetime as _dt
        created_at = admin.created_at or _dt.utcnow()
        elapsed_seconds = max(0, (_dt.utcnow() - created_at).total_seconds())
        # Percentages (respect unlimited sentinels)
        user_percentage = (max(int(getattr(admin, 'users_historical_peak', 0) or 0), int(admin_stats.total_users or 0)) / admin.max_users * 100) if admin.max_users > 0 else 0
        traffic_percentage = (admin_stats.total_traffic_used / admin.max_total_traffic * 100) if admin.max_total_traffic > 0 else 0
        time_percentage = (elapsed_seconds / admin.max_total_time * 100) if admin.max_total_time > 0 else 0
        # Display helpers
        max_users_txt = "نامحدود" if ((admin.max_users or 0) >= 1000000 or (admin.max_users or 0) == 0) else f"{admin.max_users}"
        max_traffic_txt = "نامحدود" if (admin.max_total_traffic or 0) == 0 else await format_traffic_size(admin.max_total_traffic)
        max_time_txt = "نامحدود" if (admin.max_total_time or 0) == 0 or (admin.max_total_time or 0) >= (36500 * 24 * 60 * 60) else await format_time_duration(admin.max_total_time)
        # Breakdown
        try:
            expired_c = (admin_stats.counts_extra or {}).get("expired", 0)
            quota_full_c = (admin_stats.counts_extra or {}).get("quota_full", 0)
            disabled_c = (admin_stats.counts_extra or {}).get("disabled", 0)
            active_c = (admin_stats.counts_by_status or {}).get("active", 0)
            users_breakdown = f"(فعال: {active_c}, منقضی: {expired_c}, پرحجم: {quota_full_c}, غیرفعال: {disabled_c})"
        except Exception:
            users_breakdown = ""
        detail_text = (
            f"👤 **اطلاعات پنل: {panel_name}**\n\n"
            f"- **نام کاربری مرزبان:** `{admin.marzban_username}`\n"
            f"- **وضعیت:** {'✅ فعال' if admin.is_active else '❌ غیرفعال'}\n"
            f"- **تاریخ ایجاد:** {created_at.strftime('%Y-%m-%d')}\n\n"
            f"📊 **محدودیت‌ها و استفاده:**\n"
            f"- **کاربران:** {getattr(admin_stats, 'consumed_users', 0)}/{max_users_txt} ({user_percentage:.1f}%)\n"
            f"  ├ فعلی: {admin_stats.total_users} {users_breakdown}\n"
            f"- **ترافیک:** {await format_traffic_size(admin_stats.total_traffic_used)} / {max_traffic_txt} ({traffic_percentage:.1f}%)\n"
            f"- **اعتبار زمانی:** {await format_time_duration(int(elapsed_seconds))} سپری‌شده ({time_percentage:.1f}%)\n"
            f"  └ سقف: {max_time_txt}"
        )
    except Exception as e:
        detail_text = f"❌ خطا در دریافت اطلاعات پنل: {e}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data=f"admin_status_page_{page}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await callback.message.edit_text(detail_text, reply_markup=kb)
    await callback.answer()


@sudo_router.message(Command("add_admin"))
async def add_admin_command(message: Message, state: FSMContext):
    """Handle /add_admin text command."""
    if message.from_user.id not in config.SUDO_ADMINS:
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return
    
    # Clear any existing state first
    await state.clear()
    
    logger.info(f"Starting comprehensive add admin process via command for sudo user {message.from_user.id}")
    
    await message.answer(
        "🆕 **افزودن ادمین جدید**\n\n"
        "📝 **مرحله ۱ از ۷: User ID**\n\n"
        "لطفاً User ID (آیدی تلگرام) کاربری که می‌خواهید ادمین کنید را ارسال کنید:\n\n"
        "🔍 **نکته:** User ID باید یک عدد صحیح باشد\n"
        "📋 **مثال:** `123456789`\n\n"
        "💡 **راهنما:** برای یافتن User ID می‌توانید از ربات‌های مخصوص یا دستور /start در ربات‌ها استفاده کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=config.BUTTONS["cancel"], callback_data="back_to_main")]
        ])
    )
    
    await state.set_state(AddAdminStates.waiting_for_user_id)
    
    # Log state change
    current_state = await state.get_state()
    logger.info(f"User {message.from_user.id} state set to: {current_state}")


@sudo_router.message(Command("show_admins", "list_admins"))
async def show_admins_command(message: Message):
    """Handle /show_admins or /list_admins text command."""
    if message.from_user.id not in config.SUDO_ADMINS:
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return
    
    text = await get_admin_list_text()
    await message.answer(text, reply_markup=get_sudo_keyboard())


@sudo_router.message(Command("remove_admin"))
async def remove_admin_command(message: Message):
    """Handle /remove_admin text command."""
    if message.from_user.id not in config.SUDO_ADMINS:
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return
    
    # Get only active admins for deactivation
    all_admins = await db.get_all_admins()
    active_admins = [admin for admin in all_admins if admin.is_active]
    
    if not active_admins:
        await message.answer(
            "❌ هیچ پنل فعالی برای غیرفعالسازی یافت نشد.",
            reply_markup=get_sudo_keyboard()
        )
        return
    
    await message.answer(
        config.MESSAGES["select_panel_to_deactivate"],
        reply_markup=get_panel_list_keyboard(active_admins, "confirm_deactivate")
    )


@sudo_router.message(Command("edit_panel"))
async def edit_panel_command(message: Message):
    """Handle /edit_panel text command."""
    if message.from_user.id not in config.SUDO_ADMINS:
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return
    
    # Get all admins for editing
    admins = await db.get_all_admins()
    
    if not admins:
        await message.answer(
            "❌ هیچ پنلی برای ویرایش یافت نشد.",
            reply_markup=get_sudo_keyboard()
        )
        return
    
    await message.answer(
        config.MESSAGES["select_panel_to_edit"],
        reply_markup=get_panel_list_keyboard(admins, "start_edit")
    )


@sudo_router.message(Command("admin_status"))
async def admin_status_command(message: Message):
    """Handle /admin_status text command."""
    if message.from_user.id not in config.SUDO_ADMINS:
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return
    await show_admin_status_page(message, 1)


@sudo_router.callback_query(F.data == "activate_admin")
async def activate_admin_callback(callback: CallbackQuery):
    """Step 1: choose a user (owner) who has deactivated panels."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    deactivated_admins = await db.get_deactivated_admins()
    if not deactivated_admins:
        await callback.message.edit_text(
            config.MESSAGES["no_deactivated_admins"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
            ])
        )
        await callback.answer()
        return
    
    # Build user selection keyboard
    user_ids = sorted(set(a.user_id for a in deactivated_admins))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"کاربر {uid}", callback_data=f"activate_choose_user_{uid}")]
        for uid in user_ids
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]])
    await callback.message.edit_text("کاربر موردنظر برای فعالسازی پنل را انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("activate_choose_user_"))
async def confirm_activate_admin(callback: CallbackQuery):
    """Step 2: show deactivated panels for selected user and let sudo pick one."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[-1])
    deactivated_admins = await db.get_deactivated_admins()
    user_deactivated_admins = [admin for admin in deactivated_admins if admin.user_id == user_id]
    if not user_deactivated_admins:
        await callback.answer("هیچ پنل غیرفعال برای این کاربر یافت نشد", show_alert=True)
        return
    await callback.message.edit_text(
        "یکی از پنل‌های غیرفعال این کاربر را برای فعالسازی انتخاب کنید:",
        reply_markup=get_panel_list_keyboard(user_deactivated_admins, "activate_panel")
    )
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("activate_panel_"))
async def activate_panel_selected(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin or admin.is_active:
        await callback.answer("پنل یافت نشد یا فعال است.", show_alert=True)
        return
    user_id = admin.user_id
    try:
        db_success = await db.reactivate_admin(admin.id)
        password_restored = False
        if db_success and admin.original_password:
            password_restored = await restore_admin_password_and_update_db(admin.id, admin.original_password)
            # Give Marzban a brief moment to apply password change
            try:
                await asyncio.sleep(0.5)
            except Exception:
                pass
        users_reactivated = 0
        try:
            users_reactivated = await reactivate_admin_panel_users(admin.id)
        except Exception as e:
            logger.warning(f"Failed to reactivate users for panel {admin.id}: {e}")
        panel_name = admin.admin_name or admin.marzban_username or f"Panel {admin.id}"
        text = (
            f"✅ پنل فعال شد: {panel_name}\n"
            f"🔑 {'پسورد بازیابی شد' if password_restored else 'پسورد قبلی در دسترس نبود'}\n"
            f"👥 کاربران فعال‌شده: {users_reactivated}"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]]))
        await callback.answer()
        try:
            # notify affected admin user about reactivation
            await notify_admin_reactivation_utils(callback.bot, user_id, callback.from_user.id)
        except Exception as e:
            logger.error(f"Error sending reactivation notification: {e}")
    except Exception as e:
        logger.error(f"Error activating panel {admin_id}: {e}")
        await callback.answer("خطا در فعالسازی پنل.", show_alert=True)


@sudo_router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Return to main menu."""
    await state.clear()
    
    if callback.from_user.id in config.SUDO_ADMINS:
        await callback.message.edit_text(
            config.MESSAGES["welcome_sudo"],
            reply_markup=get_sudo_keyboard()
        )
    else:
        await callback.answer("غیرمجاز", show_alert=True)
    
    await callback.answer()


@sudo_router.message(StateFilter(None), F.text & ~F.text.startswith('/'))
async def sudo_unhandled_text(message: Message, state: FSMContext):
    """Handle unhandled text messages for sudo users when NOT in FSM state."""
    if message.from_user.id not in config.SUDO_ADMINS:
        return  # Let other handlers handle this
    
    # This handler should only be called when user is NOT in any FSM state
    current_state = await state.get_state()
    if current_state:
        logger.error(f"sudo_unhandled_text called for user {message.from_user.id} in state {current_state} - this should not happen with StateFilter(None)")
        return
    
    logger.info(f"Sudo user {message.from_user.id} sent unhandled text: {message.text}")
    
    # Show sudo menu with a helpful message
    await message.answer(
        "🔐 شما سودو ادمین هستید.\n\n"
        "📋 دستورات موجود:\n"
        "• /add_admin - افزودن ادمین جدید\n"
        "• /show_admins - نمایش لیست ادمین‌ها\n"
        "• /remove_admin - غیرفعالسازی پنل\n"
        "• /edit_panel - ویرایش محدودیت‌های پنل\n"
        "• /admin_status - وضعیت ادمین‌ها\n"
        "• /start - منوی اصلی\n\n"
        "یا از دکمه‌های زیر استفاده کنید:",
        reply_markup=get_sudo_keyboard()
    )


async def restore_admin_password(admin_user_id: int, original_password: str) -> bool:
    """Restore admin's original password in Marzban (legacy function for backward compatibility)."""
    try:
        if not original_password:
            logger.warning(f"No original password found for admin {admin_user_id}")
            return False
            
        # Get admin info
        admin = await db.get_admin(admin_user_id)
        if not admin or not admin.marzban_username:
            logger.warning(f"No marzban username found for admin {admin_user_id}")
            return False
        
        # Try to restore password via Marzban API with new format
        success = await marzban_api.update_admin_password(admin.marzban_username, original_password, is_sudo=False)
        
        if success:
            logger.info(f"Password restored for admin {admin_user_id}")
        else:
            logger.warning(f"Failed to restore password for admin {admin_user_id}")
            
        return success
        
    except Exception as e:
        logger.error(f"Error restoring password for admin {admin_user_id}: {e}")
        return False


async def restore_admin_password_and_update_db(admin_id: int, original_password: str) -> bool:
    """Restore admin's original password in Marzban and update database."""
    try:
        if not original_password:
            logger.warning(f"No original password found for admin panel {admin_id}")
            return False
            
        # Get admin info by ID
        admin = await db.get_admin_by_id(admin_id)
        if not admin or not admin.marzban_username:
            logger.warning(f"No marzban username found for admin panel {admin_id}")
            return False
        
        # Try to restore password via Marzban API with new format
        marzban_success = await marzban_api.update_admin_password(admin.marzban_username, original_password, is_sudo=False)
        
        if marzban_success:
            # Update password in database
            db_success = await db.update_admin(admin_id, marzban_password=original_password)
            if db_success:
                logger.info(f"Password restored and database updated for admin panel {admin_id}")
                return True
            else:
                logger.warning(f"Password restored in Marzban but failed to update database for admin panel {admin_id}")
                return False
        else:
            logger.warning(f"Failed to restore password in Marzban for admin panel {admin_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error restoring password for admin panel {admin_id}: {e}")
        return False


async def reactivate_admin_users(admin_user_id: int) -> bool:
    """Reactivate all users belonging to an admin (legacy function for backward compatibility)."""
    try:
        admin = await db.get_admin(admin_user_id)
        if not admin or not admin.marzban_username:
            return False
        
        # Get admin's users from Marzban using admin's credentials
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        users = await admin_api.get_users()
        
        reactivated_count = 0
        for user in users:
            # Reactivate any user that is not already active (e.g., disabled/limited)
            status_value = (user.status or "").lower()
            if status_value != "active":
                success = await marzban_api.modify_user(user.username, {"status": "active"})
                if success:
                    reactivated_count += 1
        
        logger.info(f"Reactivated {reactivated_count} users for admin {admin_user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error reactivating users for admin {admin_user_id}: {e}")
        return False


async def reactivate_admin_panel_users(admin_id: int) -> int:
    """Reactivate all users belonging to a specific admin panel and return count."""
    try:
        admin = await db.get_admin_by_id(admin_id)
        if not admin or not admin.marzban_username:
            logger.warning(f"No marzban username found for admin panel {admin_id}")
            return 0
        
        users = []
        # Try via admin API first (uses panel credentials)
        try:
            admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
            users = await admin_api.get_users()
        except Exception as e:
            logger.warning(f"reactivate_admin_panel_users: admin API path failed for {admin.marzban_username}: {e}")
            # Fallback: use main API to get users of this admin
            try:
                users = await marzban_api.get_admin_users(admin.marzban_username)
            except Exception as e2:
                logger.error(f"reactivate_admin_panel_users: main API fallback failed for {admin.marzban_username}: {e2}")
                users = []
        
        reactivated_count = 0
        for user in users:
            status_value = (user.status or "").lower()
            if status_value != "active":
                try:
                    success = await marzban_api.modify_user(user.username, {"status": "active"})
                    if success:
                        reactivated_count += 1
                    await asyncio.sleep(0.1)  # Rate limiting
                except Exception as e:
                    logger.warning(f"Failed to reactivate user {user.username}: {e}")
        
        logger.info(f"Reactivated {reactivated_count} users for admin panel {admin_id}")
        return reactivated_count
        
    except Exception as e:
        logger.error(f"Error reactivating users for admin panel {admin_id}: {e}")
        return 0


async def deactivate_admin_and_users(admin_user_id: int, reason: str = "Limit exceeded") -> bool:
    """Deactivate admin and all their users."""
    try:
        admin = await db.get_admin(admin_user_id)
        if not admin:
            return False
        
        # Store original password before deactivation
        if admin.marzban_username and not admin.original_password:
            # Store original password for recovery
            await db.update_admin(admin.id, original_password=admin.marzban_password)
            
            # Use the specified password for automatic deactivation
            fixed_password = "ce8fb29b0e"
            
            # Update admin password in Marzban panel using new API format
            success = await marzban_api.update_admin_password(admin.marzban_username, fixed_password, is_sudo=False)
            if success:
                # Update password in database too
                await db.update_admin(admin.id, marzban_password=fixed_password)
            else:
                logger.warning(f"Failed to update password for admin {admin.marzban_username}")
        
        # Deactivate admin in database
        await db.deactivate_admin(admin.id, reason)
        
        # Disable all admin's users using admin's own credentials
        disabled_count = 0
        if admin.marzban_username and admin.marzban_password:
            try:
                # Create admin API with current credentials
                admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
                users = await admin_api.get_users()
                
                for user in users:
                    if user.status == "active":
                        # Use modifyUser API to disable user
                        success = await marzban_api.modify_user(user.username, {"status": "disabled"})
                        if success:
                            disabled_count += 1
                        await asyncio.sleep(0.1)  # Rate limiting
                        
            except Exception as e:
                print(f"Error disabling users for admin {admin.marzban_username}: {e}")
                # Fallback: try using main admin credentials
                users = await marzban_api.get_admin_users(admin.marzban_username)
                for user in users:
                    if user.status == "active":
                        success = await marzban_api.disable_user(user.username)
                        if success:
                            disabled_count += 1
                        await asyncio.sleep(0.1)
            
            logger.info(f"Disabled {disabled_count} users for deactivated admin {admin.id} ({admin.marzban_username})")
        
        # Log the action
        log = LogModel(
            admin_user_id=admin_user_id,
            action="admin_deactivated",
            details=f"Admin panel {admin.id} ({admin.marzban_username}) deactivated. Reason: {reason}. Users disabled: {disabled_count}."
        )
        await db.add_log(log)
        
        return True
        
    except Exception as e:
        logger.error(f"Error deactivating admin {admin_user_id}: {e}")
        return False


async def delete_admin_panel_completely(admin_id: int, reason: str = "غیرفعالسازی دستی توسط سودو"):
    """Completely delete admin panel and all their users from both Marzban and database (atomic with retry).

    Returns:
        (success: bool, error_message: str | None)
    """
    try:
        admin = await db.get_admin_by_id(admin_id)
        if not admin:
            return False, "پنل در دیتابیس یافت نشد."
        
        # Store details for logging
        admin_username = admin.marzban_username
        user_count = 0
        last_error: str | None = None
        
        # Step 1: Completely delete admin and all users from Marzban panel
        marzban_success = True if not admin.marzban_username else False
        if admin.marzban_username:
            # Try fetching user count (best-effort)
            try:
                if admin.marzban_password:
                    admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
                    users = await admin_api.get_users()
                    user_count = len(users)
            except Exception:
                pass

            # Retry deletion up to 3 times
            attempts = 3
            for attempt in range(1, attempts + 1):
                try:
                    marzban_success = await marzban_api.delete_admin_completely(admin.marzban_username)
                    if marzban_success:
                        logger.info(f"Admin {admin.marzban_username} and {user_count} users deleted from Marzban (attempt {attempt})")
                        last_error = None
                        break
                    else:
                        last_error = f"API returned failure on attempt {attempt}"
                        logger.warning(f"Failed to delete admin {admin.marzban_username} from Marzban (attempt {attempt})")
                except Exception as e:
                    last_error = f"Exception on attempt {attempt}: {type(e).__name__}: {e}"
                    logger.error(f"Error deleting admin {admin.marzban_username} from Marzban: {e}")
                # Small backoff between attempts
                try:
                    await asyncio.sleep(0.7 * attempt)
                except Exception:
                    pass

        # If Marzban deletion failed, do not remove from DB
        if not marzban_success:
            message = "حذف ادمین در مرزبان ناموفق بود. دیتابیس تغییری نکرد." + (f"\nجزئیات: {last_error}" if last_error else "")
            return False, message
        
        # Step 2 (atomic): Remove admin from database completely only if Marzban deletion succeeded
        db_success = await db.remove_admin_by_id(admin_id)
        
        if db_success:
            # If user has no more panels, they should not be treated as regular admin anymore
            remaining = await db.get_admins_for_user(admin.user_id)
            if not remaining:
                logger.info(f"User {admin.user_id} has no remaining panels; they will no longer be considered a regular admin.")
            # Log the action
            log = LogModel(
                admin_user_id=admin.user_id,
                action="admin_panel_completely_deleted",
                details=f"Admin panel {admin_id} ({admin_username}) and {user_count} users completely deleted. Reason: {reason}. Deleted from both Marzban and database."
            )
            await db.add_log(log)
            
            logger.info(f"Admin panel {admin_id} ({admin_username}) completely deleted from both Marzban and database")
            return True, None
        else:
            logger.error(f"Failed to delete admin panel {admin_id} from database")
            return False, "حذف رکورد پنل در دیتابیس ناموفق بود."
        
    except Exception as e:
        logger.error(f"Error completely deleting admin panel {admin_id}: {e}")
        return False, f"خطای غیرمنتظره: {type(e).__name__}: {e}"


async def deactivate_admin_panel_by_id(admin_id: int, reason: str = "Limit exceeded") -> bool:
    """Deactivate specific admin panel by ID and all their users."""
    try:
        admin = await db.get_admin_by_id(admin_id)
        if not admin:
            return False
        
        # Store original password before deactivation
        new_password = None
        password_updated = False
        if admin.marzban_username:
            # Store original password for recovery (only once)
            if not admin.original_password:
                await db.update_admin(admin.id, original_password=admin.marzban_password)
            
            # Generate a random password for automatic deactivation (always randomize on deactivation)
            import secrets
            new_password = secrets.token_hex(5)
            
            # Update admin password in Marzban panel using new API format
            password_updated = await marzban_api.update_admin_password(admin.marzban_username, new_password, is_sudo=False)
            if password_updated:
                # Update password in database too
                await db.update_admin(admin.id, marzban_password=new_password)
            else:
                logger.warning(f"Failed to update password for admin {admin.marzban_username}")
        
        # Deactivate admin in database
        await db.deactivate_admin(admin.id, reason)
        
        # Disable all admin's users using admin's credentials (prefer the updated password)
        disabled_count = 0
        if admin.marzban_username and admin.marzban_password:
            try:
                # Choose the correct password to use
                admin_password_to_use = new_password if password_updated and new_password else admin.marzban_password
                # Create admin API with current credentials
                admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin_password_to_use)
                users = await admin_api.get_users()
                
                for user in users:
                    if user.status == "active":
                        # Use modifyUser API to disable user
                        success = await marzban_api.modify_user(user.username, {"status": "disabled"})
                        if success:
                            disabled_count += 1
                        await asyncio.sleep(0.1)  # Rate limiting
                        
            except Exception as e:
                print(f"Error disabling users for admin {admin.marzban_username}: {e}")
                # Fallback: try using main admin credentials
                users = await marzban_api.get_admin_users(admin.marzban_username)
                for user in users:
                    if user.status == "active":
                        success = await marzban_api.disable_user(user.username)
                        if success:
                            disabled_count += 1
                        await asyncio.sleep(0.1)
            
            logger.info(f"Disabled {disabled_count} users for deactivated admin panel {admin.id} ({admin.marzban_username})")
        
        # Log the action
        log = LogModel(
            admin_user_id=admin.user_id,
            action="admin_panel_deactivated",
            details=f"Admin panel {admin.id} ({admin.marzban_username}) deactivated. Reason: {reason}. Users disabled: {disabled_count}."
        )
        await db.add_log(log)
        
        return True
        
    except Exception as e:
        logger.error(f"Error deactivating admin panel {admin_id}: {e}")
        return False


async def notify_admin_deactivation(bot, admin_user_id: int, reason: str, admin_id: int | None = None):
    """Notify sudo admins about admin deactivation, including new password if available."""
    try:
        admin = None
        if admin_id is not None:
            admin = await db.get_admin_by_id(admin_id)
        if not admin:
            admin = await db.get_admin(admin_user_id)
        admin_name = (admin.username or admin.marzban_username or f"ID: {admin_user_id}") if admin else f"ID: {admin_user_id}"
        marzban_username = admin.marzban_username if admin else "—"
        current_password = admin.marzban_password if admin else None

        lines = [
            "🔒 **هشدار غیرفعالسازی ادمین**",
            "",
            f"👤 ادمین: {admin_name}",
            f"🧩 نام‌کاربری پنل: {marzban_username}",
            f"📝 دلیل: {reason}",
            f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if current_password:
            lines.append(f"🔐 پسورد جدید: `{current_password}`")
        lines.append("برای فعالسازی مجدد از دکمه 'فعالسازی ادمین' استفاده کنید.")

        message = "\n".join(lines)

        for sudo_id in config.SUDO_ADMINS:
            try:
                await bot.send_message(sudo_id, message)
            except Exception as e:
                logger.warning(f"Failed to notify sudo admin {sudo_id}: {e}")
                
    except Exception as e:
        logger.error(f"Error notifying about admin deactivation: {e}")


async def notify_admin_reactivation(bot, admin_user_id: int, reactivated_by: int):
    """Notify admin about their reactivation."""
    try:
        admin = await db.get_admin(admin_user_id)
        if not admin:
            return
            
        message = (
            f"✅ **اطلاع فعالسازی مجدد**\n\n"
            f"🎉 حساب شما مجدداً فعال شد!\n"
            f"🔐 پسورد شما بازگردانده شد.\n"
            f"👥 کاربران شما فعال شدند.\n\n"
            f"می‌توانید مجدداً از ربات استفاده کنید."
        )
        
        try:
            await bot.send_message(admin_user_id, message)
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_user_id} about reactivation: {e}")
            
    except Exception as e:
        logger.error(f"Error notifying admin about reactivation: {e}")


@sudo_router.callback_query(F.data == "sudo_manage_admins")
async def sudo_manage_admins_entry(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    text = (
        "🛠️ مدیریت ادمین‌ها\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید یا آیدی عددی کاربر را برای جستجو ارسال کنید."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 لیست همه ادمین‌ها", callback_data="manage_list_all")],
        [InlineKeyboardButton(text="🛒 مدیریت فروش", callback_data="sales_manage")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])
    await state.set_state(ManageAdminStates.waiting_for_user_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data == "manage_list_all")
async def manage_list_all(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.clear()
    admins = await db.get_all_admins()
    if not admins:
        await callback.answer("ادمینی یافت نشد.", show_alert=True)
        return
    kb = get_admin_list_keyboard(admins, "manage_user")
    await callback.message.edit_text("یک کاربر را برای مدیریت پنل‌ها انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_user_"))
async def manage_user_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.clear()
    user_id = int(callback.data.split("_")[-1])
    panels = await db.get_admins_for_user(user_id)
    if not panels:
        await callback.answer("برای این کاربر پنلی وجود ندارد.", show_alert=True)
        return
    kb = get_panel_list_keyboard(panels, "manage_panel")
    await callback.message.edit_text(f"مدیریت پنل‌های کاربر {user_id}:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_panel_"))
async def manage_panel_selected(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.message.edit_text("❌ پنل یافت نشد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_manage_admins")]]))
        await callback.answer()
        return
    panel_name = admin.admin_name or admin.marzban_username or f"Panel {admin.id}"
    info = (
        f"👤 کاربر: {admin.user_id}\n"
        f"🏷️ پنل: {panel_name}\n"
        f"🔐 مرزبان: {admin.marzban_username or '-'}\n"
        f"✅ وضعیت: {'فعال' if admin.is_active else 'غیرفعال'}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ اطلاعات", callback_data=f"manage_action_info_{admin.id}")],
        [InlineKeyboardButton(text="🔄 فعالسازی", callback_data=f"manage_action_activate_{admin.id}"), InlineKeyboardButton(text="⛔ غیرفعالسازی", callback_data=f"manage_action_deactivate_{admin.id}")],
        [InlineKeyboardButton(text=config.BUTTONS["remove_admin"], callback_data=f"manage_action_delete_{admin.id}")],
        [InlineKeyboardButton(text="♻️ ریست زمان", callback_data=f"manage_action_reset_time_{admin.id}"), InlineKeyboardButton(text="♻️ ریست حجم", callback_data=f"manage_action_reset_traffic_{admin.id}")],
        [InlineKeyboardButton(text="👥 تعداد کاربر", callback_data=f"manage_action_users_{admin.id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_manage_admins")]
    ])
    await callback.message.edit_text(info, reply_markup=kb)
    await callback.answer()


@sudo_router.message(ManageAdminStates.waiting_for_user_id, F.text)
async def manage_search_user(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("آیدی عددی نامعتبر است.")
        return
    user_id = int(text)
    panels = await db.get_admins_for_user(user_id)
    if not panels:
        await message.answer("برای این کاربر پنلی یافت نشد.")
        return
    kb = get_panel_list_keyboard(panels, "manage_panel")
    await message.answer(f"مدیریت پنل‌های کاربر {user_id}:", reply_markup=kb)
    await state.clear()


# ===== Helpers for Manage Admins UI =====

def _manage_back_keyboard(admin_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data=f"manage_panel_{admin_id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_manage_admins")]
    ])


@sudo_router.callback_query(F.data.startswith("manage_action_info_"))
async def manage_action_info(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    try:
        text = f"ℹ️ اطلاعات پنل {admin.admin_name or admin.marzban_username or admin.id}\n\n"
        if admin.marzban_username and admin.marzban_password:
            admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
            stats = await admin_api.get_admin_stats()
            max_traffic_txt = "نامحدود" if (admin.max_total_traffic or 0) == 0 else await format_traffic_size(admin.max_total_traffic)
            text += (
                f"👥 کاربران فعال/کل: {stats.active_users}/{stats.total_users}\n"
                f"📊 ترافیک مصرفی: {await format_traffic_size(stats.total_traffic_used)} / {max_traffic_txt}\n"
            )
        else:
            text += "اطلاعات مرزبان کامل نیست.\n"
    except Exception as e:
        text = f"❌ خطا در دریافت اطلاعات: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_activate_"))
async def manage_action_activate(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    try:
        db_success = await db.reactivate_admin(admin.id)
        password_restored = False
        if db_success and admin.original_password:
            password_restored = await restore_admin_password_and_update_db(admin.id, admin.original_password)
            # Give Marzban a brief moment to apply password change
            try:
                await asyncio.sleep(0.5)
            except Exception:
                pass
        users_reactivated = 0
        try:
            users_reactivated = await reactivate_admin_panel_users(admin.id)
        except Exception as e:
            logger.warning(f"manage activate: reactivate users failed for {admin.id}: {e}")
        text = (
            f"✅ پنل فعال شد\n"
            f"🔑 {'پسورد بازیابی شد' if password_restored else 'پسورد قبلی در دسترس نبود'}\n"
            f"👥 کاربران فعال‌شده: {users_reactivated}"
        )
        try:
            # Notify affected admin about reactivation (was missing in manage flow)
            await notify_admin_reactivation_utils(callback.bot, admin.user_id, callback.from_user.id)
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin.user_id} about reactivation: {e}")
    except Exception as e:
        text = f"❌ خطا در فعالسازی: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_deactivate_"))
async def manage_action_deactivate(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    try:
        # قبل از غیرفعالسازی، پسورد را رندوم کن و برای سودو نمایش بده
        admin = await db.get_admin_by_id(admin_id)
        import secrets
        new_password = secrets.token_hex(5)
        # ذخیره پسورد اصلی اگر نبود
        if admin and not admin.original_password and admin.marzban_password:
            await db.update_admin(admin.id, original_password=admin.marzban_password)
        # تغییر پسورد در مرزبان
        pwd_changed = False
        if admin and admin.marzban_username:
            pwd_changed = await marzban_api.update_admin_password(admin.marzban_username, new_password, is_sudo=False)
            if pwd_changed:
                await db.update_admin(admin.id, marzban_password=new_password)
        # غیرفعالسازی پنل (کاربران هم طبق منطق deactivate_admin_panel_by_id غیرفعال می‌شوند)
        success = await deactivate_admin_panel_by_id(admin_id, "غیرفعالسازی دستی توسط سودو")
        if success:
            pwd_text = f"\n🔐 پسورد جدید: `{new_password}`" if pwd_changed else "\n⚠️ تغییر پسورد انجام نشد."
            text = f"✅ پنل غیرفعال شد.{pwd_text}"
            try:
                # notify affected admin user
                await notify_admin_deactivated(callback.bot, admin.user_id, "غیرفعالسازی دستی توسط سودو")
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin.user_id} about manual deactivation: {e}")
        else:
            text = "❌ خطا در غیرفعالسازی پنل."
    except Exception as e:
        text = f"❌ خطا در غیرفعالسازی: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_delete_"))
async def manage_action_delete(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    try:
        success, err = await delete_admin_panel_completely(admin_id, "حذف دستی توسط سودو")
        text = "✅ پنل حذف شد." if success else ("❌ خطا در حذف پنل." + (f"\n\nجزئیات: {err}" if err else ""))
    except Exception as e:
        text = f"❌ خطا در حذف پنل: {e}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_manage_admins")]]))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_reset_time_"))
async def manage_action_reset_time(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    from datetime import datetime as _dt
    try:
        await db.update_admin(admin.id, created_at=_dt.utcnow())
        text = "✅ زمان مصرف‌شده پنل ریست شد."
    except Exception as e:
        text = f"❌ خطا در ریست زمان: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_reset_traffic_"))
async def manage_action_reset_traffic(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    try:
        reset = 0
        failed = 0
        if admin.marzban_username and admin.marzban_password:
            admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
            users = await admin_api.get_users()
            for u in users:
                ok = await admin_api.reset_user_data_usage(u.username)
                if ok:
                    reset += 1
                else:
                    failed += 1
        text = (
            "✅ ریست ترافیک انجام شد\n\n"
            f"ریست‌شده: {reset}\n"
            f"ناموفق: {failed}"
        )
    except Exception as e:
        text = f"❌ خطا در ریست ترافیک: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_users_"))
async def manage_action_users(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    try:
        total = 0
        active = 0
        if admin.marzban_username and admin.marzban_password:
            admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
            users = await admin_api.get_users()
            total = len(users)
            active = len([u for u in users if (u.status or '').lower() == 'active'])
        text = f"👥 تعداد کاربران: {total} (فعال: {active})"
    except Exception as e:
        text = f"❌ خطا در دریافت کاربران: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_quota_"))
async def manage_action_quota(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ +1GB", callback_data=f"manage_action_quota_add_{admin_id}_1")],
        [InlineKeyboardButton(text="➕ +5GB", callback_data=f"manage_action_quota_add_{admin_id}_5")],
        [InlineKeyboardButton(text="➕ +10GB", callback_data=f"manage_action_quota_add_{admin_id}_10")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"manage_panel_{admin_id}")]
    ])
    await callback.message.edit_text("مقدار افزایش حجم را انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("manage_action_quota_add_"))
async def manage_action_quota_add(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin = await db.get_admin_by_id(admin_id)
    try:
        if not admin:
            await callback.message.edit_text("❌ پنل یافت نشد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_manage_admins")]]))
            await callback.answer()
            return
        add_bytes = gb_to_bytes(gb)
        new_total = (admin.max_total_traffic or 0) + add_bytes
        await db.update_admin(admin_id, max_total_traffic=new_total)
        text = f"✅ حجم پنل {gb}GB افزایش یافت. ظرفیت جدید: {await format_traffic_size(new_total)}"
    except Exception as e:
        text = f"❌ خطا در افزایش حجم: {e}"
    await callback.message.edit_text(text, reply_markup=_manage_back_keyboard(admin_id))
    await callback.answer()


def _sales_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن پلن", callback_data="sales_add")],
        [InlineKeyboardButton(text="🗑️ حذف پلن", callback_data="sales_delete")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sudo_manage_admins")]
    ])


@sudo_router.callback_query(F.data == "sales_manage")
async def sales_manage_entry(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    plans = await db.get_plans()
    if not plans:
        text = "🛒 مدیریت فروش\n\nهنوز هیچ پلنی ثبت نشده."
    else:
        from utils.notify import seconds_to_days
        lines = ["🛒 مدیریت فروش", ""]
        for p in plans:
            traffic_txt = "نامحدود" if p.traffic_limit_bytes is None else f"{await format_traffic_size(p.traffic_limit_bytes)}"
            time_txt = "نامحدود" if p.time_limit_seconds is None else f"{seconds_to_days(p.time_limit_seconds)} روز"
            users_txt = "نامحدود" if p.max_users is None else f"{p.max_users} کاربر"
            type_txt = "حجمی" if (getattr(p, 'plan_type', 'volume') == 'volume') else "پکیجی"
            price_txt = f"{p.price:,}"
            lines.append(f"#{p.id} • {p.name}")
            lines.append(f"🧩 نوع: {type_txt}")
            lines.append(f"📦 ترافیک: {traffic_txt}")
            lines.append(f"⏱️ زمان: {time_txt}")
            lines.append(f"👥 کاربر: {users_txt}")
            lines.append(f"💰 قیمت: {price_txt} تومان")
            lines.append("—")
        text = "\n".join(lines).rstrip("—")
    await callback.message.edit_text(text, reply_markup=_sales_menu_keyboard())
    await callback.answer()


def _cards_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["add_card"], callback_data="card_add")],
        [InlineKeyboardButton(text=config.BUTTONS["delete_card"], callback_data="card_delete")],
        [InlineKeyboardButton(text=config.BUTTONS["toggle_card"], callback_data="card_toggle")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]
    ])


@sudo_router.callback_query(F.data == "sales_cards")
async def sales_cards_entry(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    cards = await db.get_cards()
    lines = ["💳 کارت‌های ثبت‌شده:", ""]
    if not cards:
        lines.append("— هیچ کارتی ثبت نشده است.")
    else:
        for c in cards:
            status = "✅" if c.get("is_active") else "❌"
            lines.append(f"{status} #{c['id']} • {c.get('bank_name','بانک')} | {c.get('card_number','----')} | {c.get('holder_name','')}")
    await callback.message.edit_text("\n".join(lines), reply_markup=_cards_menu_keyboard())
    await callback.answer()


# Orders menu removed per request


@sudo_router.callback_query(F.data == "set_login_url")
async def set_login_url_entry(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    current = await db.get_setting("global_login_url")
    text = "🌐 تنظیم آدرس ورود برای پیام صدور\n\n"
    if current:
        text += f"آدرس فعلی: {current}\n\n"
    text += "لطفاً URL عمومی ورود برای پیام کاربران را ارسال کنید."
    await state.set_state(LoginURLStates.waiting_for_url)
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]]))
    await callback.answer()


@sudo_router.callback_query(F.data == "set_billing")
async def set_billing_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.set_state(BillingStates.waiting_per_gb)
    await callback.message.edit_text("مبلغ هر 1GB را وارد کنید (تومان):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]]))
    await callback.answer()


@sudo_router.message(StateFilter(None), F.text.startswith("/"))
async def ignore_commands(message: Message):
    return


class BillingStates(StatesGroup):
    waiting_per_gb = State()
    waiting_per_30d = State()
    waiting_per_user = State()


@sudo_router.callback_query(F.data == "set_billing")
async def set_billing_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.set_state(BillingStates.waiting_per_gb)
    await callback.message.edit_text("مبلغ هر 1GB را وارد کنید (تومان):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]]))
    await callback.answer()


@sudo_router.message(BillingStates.waiting_per_gb, F.text)
async def billing_per_gb(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    await state.update_data(per_gb=val)
    await state.set_state(BillingStates.waiting_per_30d)
    await message.answer("مبلغ هر 30 روز را وارد کنید (تومان):")


@sudo_router.message(BillingStates.waiting_per_30d, F.text)
async def billing_per_30d(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    await state.update_data(per_30d=val)
    await state.set_state(BillingStates.waiting_per_user)
    await message.answer("مبلغ هر 1 کاربر اضافی را وارد کنید (تومان):")


@sudo_router.message(BillingStates.waiting_per_user, F.text)
async def billing_per_user(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    data = await state.get_data()
    await db.set_setting("price_per_gb_toman", str(data.get('per_gb', 0)))
    await db.set_setting("price_per_30days_toman", str(data.get('per_30d', 0)))
    await db.set_setting("price_per_user_toman", str(val))
    await state.clear()
    await message.answer("✅ تعرفه‌ها ذخیره شد.", reply_markup=get_sudo_keyboard())


@sudo_router.callback_query(F.data.startswith("set_login_url_"))
async def set_login_url_choose(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    await state.update_data(admin_id=admin_id)
    await state.set_state(LoginURLStates.waiting_for_url)
    await callback.message.edit_text("آدرس ورود (URL) پنل را ارسال کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_main")]]))
    await callback.answer()


@sudo_router.message(LoginURLStates.waiting_for_url, F.text)
async def set_login_url_save(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    url = message.text.strip()
    # Basic validation
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("URL معتبر نیست. با http(s) شروع کنید.")
        return
    await db.set_setting("global_login_url", url)
    await state.clear()
    await message.answer(config.MESSAGES["login_url_updated"], reply_markup=get_sudo_keyboard())


# Orders list UI removed per request


# Orders filter UI removed per request


# Order open UI removed per request


@sudo_router.callback_query(F.data.startswith("order_approve_"))
async def order_approve(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    oid = int(callback.data.split("_")[-1])
    o = await db.get_order_by_id(oid)
    if not o:
        await callback.answer("سفارش یافت نشد.", show_alert=True)
        return
    # Prevent double-approval
    if (o.get("status") or "").lower() == "approved":
        await callback.answer("این سفارش قبلاً تایید شده است.", show_alert=True)
        return

    order_type = (o.get("order_type") or "").lower()
    if order_type == "renew":
        # Apply renewal on target admin
        target_admin_id = o.get("target_admin_id")
        admin = await db.get_admin_by_id(int(target_admin_id)) if target_admin_id else None
        if not admin:
            await callback.answer("پنل مقصد تمدید یافت نشد.", show_alert=True)
            return
        delta_traffic = int(o.get("delta_traffic_bytes") or 0)
        delta_time = int(o.get("delta_time_seconds") or 0)
        delta_users = int(o.get("delta_users") or 0)
        new_fields = {}
        if delta_traffic:
            new_fields["max_total_traffic"] = (admin.max_total_traffic or 0) + delta_traffic
        if delta_time:
            new_fields["max_total_time"] = (admin.max_total_time or 0) + delta_time
        if delta_users:
            new_fields["max_users"] = (admin.max_users or 0) + delta_users
        if not new_fields:
            await callback.answer("مقادیر تمدید نامعتبر است.", show_alert=True)
            return
        ok_update = await db.update_admin(admin.id, **new_fields)
        if not ok_update:
            await callback.answer("خطا در اعمال تمدید.", show_alert=True)
            return
        await db.update_order(oid, status="approved", approved_by=callback.from_user.id)
        # Notify user
        try:
            from utils.notify import format_traffic_size, format_time_duration
            bot = callback.bot
            lines = ["✅ تمدید اعمال شد.", ""]
            if delta_traffic:
                lines.append(f"📦 افزایش ترافیک: +{await format_traffic_size(delta_traffic)}")
            if delta_time:
                lines.append(f"⏱️ افزایش زمان: +{await format_time_duration(delta_time)}")
            if delta_users:
                lines.append(f"👥 افزایش کاربر: +{delta_users}")
            await bot.send_message(chat_id=o['user_id'], text="\n".join(lines))
        except Exception as e:
            logger.error(f"Failed to notify user {o['user_id']} after renewal approve: {e}")
        await callback.message.edit_text("✅ سفارش تایید و تمدید اعمال شد.")
        await callback.answer()
        return

    # New panel purchase flow
    plan = await db.get_plan_by_id(int(o.get("plan_id"))) if o.get("plan_id") else None
    if not plan:
        await callback.answer("پلن مربوطه یافت نشد.", show_alert=True)
        return
    import secrets
    # Username pattern: panel{user_id}, if exists then panel{user_id}-1, -2, ...
    base_username = f"panel{o['user_id']}"
    # Find an available username deterministically
    candidate = base_username
    try:
        exists = await marzban_api.admin_exists(candidate)
    except Exception:
        exists = False
    suffix = 0
    if exists:
        suffix = 1
        while suffix < 500:
            candidate = f"{base_username}-{suffix}"
            try:
                exists = await marzban_api.admin_exists(candidate)
            except Exception:
                exists = False
            if not exists:
                break
            suffix += 1
    new_username = candidate
    new_password = secrets.token_hex(5)
    # Try create; if still fails (race), try next few suffixes
    created = await marzban_api.create_admin(new_username, new_password, telegram_id=o['user_id'], is_sudo=False)
    if not created:
        attempts = 0
        while attempts < 5 and not created:
            suffix = (suffix + 1) if suffix else 1
            new_username = f"{base_username}-{suffix}"
            created = await marzban_api.create_admin(new_username, new_password, telegram_id=o['user_id'], is_sudo=False)
            attempts += 1
        if not created:
            await callback.answer("خطا در صدور پنل در مرزبان.", show_alert=True)
            return
    from models.schemas import AdminModel
    admin_model = AdminModel(
        user_id=o['user_id'],
        admin_name=(plan.name or f"Reseller #{oid}"),
        marzban_username=new_username,
        marzban_password=new_password,
        max_users=(plan.max_users if plan.max_users is not None else 1000000),
        max_total_time=(plan.time_limit_seconds if plan.time_limit_seconds is not None else days_to_seconds(36500)),
        max_total_traffic=plan.traffic_limit_bytes or 0,
        validity_days=(plan.time_limit_seconds // 86400) if plan.time_limit_seconds else 36500,
        is_active=True,
        origin_plan_id=plan.id
    )
    ok = await db.add_admin(admin_model)
    issued_admin = None
    if ok:
        admins = await db.get_admins_for_user(o['user_id'])
        issued_admin = next((a for a in admins if a.marzban_username == new_username), None)
    await db.update_order(oid, status="approved", approved_by=callback.from_user.id, issued_admin_id=(issued_admin.id if issued_admin else None))
    try:
        bot = callback.bot
        # Prefer global setting for login URL; fallback to per-admin or MARZBAN_URL
        login_url = await db.get_setting("global_login_url")
        if not login_url:
            login_url = issued_admin.login_url if issued_admin and issued_admin.login_url else config.MARZBAN_URL
        plan_name_display = plan.name if plan and getattr(plan, 'name', None) else (o.get('plan_name_snapshot') or f"پلن #{o.get('plan_id')}")
        msg = config.MESSAGES["order_approved_user"].format(username=new_username, password=new_password, login_url=login_url)
        msg += f"\n📦 پلن: {plan_name_display}"
        await bot.send_message(chat_id=o['user_id'], text=msg)
    except Exception as e:
        logger.error(f"Failed to notify user {o['user_id']} for order {oid}: {e}")
    await callback.message.edit_text("✅ سفارش تأیید و پنل صادر شد.")
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("order_reject_"))
async def order_reject(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    oid = int(callback.data.split("_")[-1])
    o = await db.get_order_by_id(oid)
    if not o:
        await callback.answer("سفارش یافت نشد.", show_alert=True)
        return
    await db.update_order(oid, status="rejected", approved_by=callback.from_user.id)
    # Notify end user about rejection
    try:
        await callback.bot.send_message(chat_id=o['user_id'], text=config.MESSAGES["order_rejected_user"])
    except Exception as e:
        logger.error(f"Failed to notify user {o['user_id']} about order rejection {oid}: {e}")
    await callback.message.edit_text("⛔ سفارش رد شد.")
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("order_retry_"))
async def order_retry(callback: CallbackQuery):
    # Retry is the same as approve, just attempt again
    await order_approve(callback)


@sudo_router.callback_query(F.data == "card_add")
async def card_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.set_state(CardStates.waiting_for_bank)
    await callback.message.edit_text("نام بانک را وارد کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_cards")]]))
    await callback.answer()


@sudo_router.message(CardStates.waiting_for_bank, F.text)
async def card_add_bank(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    await state.update_data(bank=message.text.strip())
    await state.set_state(CardStates.waiting_for_card)
    await message.answer("شماره کارت را وارد کنید (xxxx xxxx xxxx xxxx):")


@sudo_router.message(CardStates.waiting_for_card, F.text)
async def card_add_number(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    await state.update_data(card=message.text.strip())
    await state.set_state(CardStates.waiting_for_holder)
    await message.answer("به نام چه کسی است؟")


@sudo_router.message(CardStates.waiting_for_holder, F.text)
async def card_add_holder(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    data = await state.get_data()
    bank = data.get("bank")
    card = data.get("card")
    holder = message.text.strip()
    ok = await db.add_card(bank, card, holder, True)
    await state.clear()
    if ok:
        await message.answer("✅ کارت ثبت شد.")
    else:
        await message.answer("❌ خطا در افزودن کارت.")
    # Show list again
    cards = await db.get_cards()
    lines = ["💳 کارت‌های ثبت‌شده:", ""]
    if not cards:
        lines.append("— هیچ کارتی ثبت نشده است.")
    else:
        for c in cards:
            status = "✅" if c.get("is_active") else "❌"
            lines.append(f"{status} #{c['id']} • {c.get('bank_name','بانک')} | {c.get('card_number','----')} | {c.get('holder_name','')}")
    await message.answer("\n".join(lines), reply_markup=_cards_menu_keyboard())


@sudo_router.callback_query(F.data == "card_delete")
async def card_delete(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    cards = await db.get_cards()
    if not cards:
        await callback.answer("کارتی وجود ندارد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{c['id']} {c.get('bank_name','بانک')} {c.get('card_number','----')}", callback_data=f"card_delete_{c['id']}")]
        for c in cards
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_cards")]])
    await callback.message.edit_text("یک کارت را برای حذف انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("card_delete_"))
async def card_delete_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    card_id = int(callback.data.split("_")[-1])
    ok = await db.delete_card(card_id)
    text = "✅ حذف شد." if ok else "❌ خطا در حذف کارت."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_cards")]]))
    await callback.answer()


@sudo_router.callback_query(F.data == "card_toggle")
async def card_toggle(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    cards = await db.get_cards()
    if not cards:
        await callback.answer("کارتی وجود ندارد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{c['id']} {'فعال' if c.get('is_active') else 'غیرفعال'} - {c.get('bank_name','بانک')} {c.get('card_number','----')}", callback_data=f"card_toggle_{c['id']}")]
        for c in cards
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_cards")]])
    await callback.message.edit_text("انتخاب کنید برای فعال/غیرفعال:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("card_toggle_"))
async def card_toggle_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    card_id = int(callback.data.split("_")[-1])
    card = await db.get_card_by_id(card_id)
    if not card:
        await callback.answer("کارت یافت نشد.", show_alert=True)
        return
    ok = await db.set_card_active(card_id, not bool(card.get("is_active")))
    text = "✅ وضعیت کارت بروزرسانی شد." if ok else "❌ خطا در بروزرسانی."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_cards")]]))
    await callback.answer()


@sudo_router.callback_query(F.data == "sales_add")
async def sales_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    await state.set_state(CreatePlanStates.waiting_for_name)
    await callback.message.edit_text(
        "🆕 افزودن پلن جدید\n\nنام پلن را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_manage")]])
    )
    await callback.answer()


@sudo_router.message(CreatePlanStates.waiting_for_name, F.text)
async def sales_plan_name(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(CreatePlanStates.waiting_for_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="پلن حجمی", callback_data="sales_type_volume")],
        [InlineKeyboardButton(text="پلن پکیجی (زمانی)", callback_data="sales_type_time")]
    ])
    await message.answer("نوع پلن را انتخاب کنید:", reply_markup=kb)


@sudo_router.callback_query(F.data.startswith("sales_type_"))
async def sales_type_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    t = callback.data.split("_")[-1]
    await state.update_data(plan_type=t)
    # همیشه هر سه محدودیت را می‌گیریم (اجازه نامحدود هم هست)
    await state.set_state(CreatePlanStates.waiting_for_traffic)
    await callback.message.edit_text(
        "حجم را وارد کنید (به GB) یا بنویسید 'نامحدود':",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_manage")]])
    )
    await callback.answer()


@sudo_router.message(CreatePlanStates.waiting_for_traffic, F.text)
async def sales_enter_traffic(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    v = message.text.strip()
    from utils.notify import gb_to_bytes
    if v == "نامحدود":
        await state.update_data(traffic_limit_bytes=None)
    else:
        try:
            gb = float(v.replace(",", "."))
            await state.update_data(traffic_limit_bytes=gb_to_bytes(gb))
        except Exception:
            await message.answer("فرمت حجم نامعتبر است. دوباره وارد کنید (مثال: 10 یا نامحدود)")
            return
    await state.set_state(CreatePlanStates.waiting_for_time)
    await message.answer("مدت زمان را وارد کنید (به روز) یا بنویسید 'نامحدود':")


@sudo_router.message(CreatePlanStates.waiting_for_time, F.text)
async def sales_enter_time(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    v = message.text.strip()
    from utils.notify import days_to_seconds
    if v == "نامحدود":
        await state.update_data(time_limit_seconds=None)
    else:
        try:
            days = int(v)
            await state.update_data(time_limit_seconds=days_to_seconds(days))
        except Exception:
            await message.answer("فرمت زمان نامعتبر است. دوباره وارد کنید (مثال: 30 یا نامحدود)")
            return
    await state.set_state(CreatePlanStates.waiting_for_max_users)
    await message.answer("حداکثر تعداد کاربر را وارد کنید یا بنویسید 'نامحدود':")


@sudo_router.message(CreatePlanStates.waiting_for_max_users, F.text)
async def sales_enter_max_users(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    v = message.text.strip()
    if v == "نامحدود":
        await state.update_data(max_users=None)
    else:
        try:
            mu = int(v)
            if mu <= 0:
                raise ValueError()
            await state.update_data(max_users=mu)
        except Exception:
            await message.answer("فرمت تعداد کاربر نامعتبر است. یک عدد مثبت یا 'نامحدود' وارد کنید.")
            return
    await state.set_state(CreatePlanStates.waiting_for_price)
    await message.answer("قیمت را وارد کنید (عدد):")


@sudo_router.message(CreatePlanStates.waiting_for_price, F.text)
async def sales_enter_price(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    try:
        price = int(message.text.strip())
    except Exception:
        await message.answer("فرمت قیمت نامعتبر است. یک عدد وارد کنید.")
        return
    data = await state.get_data()
    name = data.get("name")
    plan_type = data.get("plan_type")
    traffic_limit_bytes = data.get("traffic_limit_bytes") if plan_type != "time" else data.get("traffic_limit_bytes", None)
    time_limit_seconds = data.get("time_limit_seconds") if plan_type != "volume" else data.get("time_limit_seconds", None)
    max_users = data.get("max_users")
    await state.update_data(price=price, name=name, traffic_limit_bytes=traffic_limit_bytes, time_limit_seconds=time_limit_seconds, max_users=max_users)
    await state.set_state(CreatePlanStates.waiting_for_renew_mode)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تمدید تدریجی مجاز است", callback_data="sales_renew_mode_incremental")],
        [InlineKeyboardButton(text="❌ فقط تمدید کامل", callback_data="sales_renew_mode_full")]
    ])
    await message.answer("حالت تمدید این پلن را انتخاب کنید:", reply_markup=kb)


@sudo_router.callback_query(F.data.startswith("sales_renew_mode_"))
async def sales_renew_mode_selected(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    mode = callback.data.split("_")[-1]
    allow_incremental = True if mode == "incremental" else False
    data = await state.get_data()
    from models.schemas import PlanModel
    plan = PlanModel(
        name=data.get("name"),
        traffic_limit_bytes=data.get("traffic_limit_bytes"),
        time_limit_seconds=data.get("time_limit_seconds"),
        max_users=data.get("max_users"),
        price=data.get("price"),
        is_active=True,
        allow_incremental_renewal=allow_incremental
    )
    ok = await db.add_plan(plan)
    await state.clear()
    if ok:
        await callback.message.edit_text("✅ پلن با موفقیت اضافه شد.")
    else:
        await callback.message.edit_text("❌ خطا در افزودن پلن.")
    await callback.answer()


@sudo_router.callback_query(F.data == "sales_delete")
async def sales_delete(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    plans = await db.get_plans()
    if not plans:
        await callback.answer("پلنی وجود ندارد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{p.id} {p.name}", callback_data=f"sales_delete_{p.id}")]
        for p in plans
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="sales_manage")]])
    await callback.message.edit_text("یک پلن را برای حذف انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@sudo_router.callback_query(F.data.startswith("sales_delete_"))
async def sales_delete_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("غیرمجاز", show_alert=True)
        return
    plan_id = int(callback.data.split("_")[-1])
    ok = await db.delete_plan(plan_id)
    await callback.message.edit_text("✅ حذف شد" if ok else "❌ خطا در حذف", reply_markup=_sales_menu_keyboard())
    await callback.answer()


@sudo_router.message(CreatePlanStates.waiting_for_max_users, F.text)
async def sales_enter_max_users(message: Message, state: FSMContext):
    if message.from_user.id not in config.SUDO_ADMINS:
        return
    v = message.text.strip()
    if v == "نامحدود":
        await state.update_data(max_users=None)
    else:
        try:
            mu = int(v)
            if mu <= 0:
                raise ValueError()
            await state.update_data(max_users=mu)
        except Exception:
            await message.answer("فرمت تعداد کاربر نامعتبر است. یک عدد مثبت یا 'نامحدود' وارد کنید.")
            return
    await state.set_state(CreatePlanStates.waiting_for_price)
    await message.answer("قیمت را وارد کنید (عدد):")