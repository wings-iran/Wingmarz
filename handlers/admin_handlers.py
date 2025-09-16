from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import List
import json
import logging
import config
from database import db
from models.schemas import AdminModel, UsageReportModel
from utils.notify import format_traffic_size, format_time_duration
from marzban_api import marzban_api
from datetime import datetime
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


admin_router = Router()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Get admin main keyboard."""
    buttons = [
        [
            InlineKeyboardButton(text=config.BUTTONS["my_info"], callback_data="my_info"),
            InlineKeyboardButton(text=config.BUTTONS["my_report"], callback_data="my_report")
        ],
        [
            InlineKeyboardButton(text=config.BUTTONS["my_users"], callback_data="my_users"),
            InlineKeyboardButton(text=config.BUTTONS["reactivate_users"], callback_data="reactivate_users")
        ],
        [
            InlineKeyboardButton(text="🛒 خرید پنل نمایندگی", callback_data="admin_buy_reseller")
        ],
        [
            InlineKeyboardButton(text=config.BUTTONS["renew"], callback_data="admin_renew")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_panel_selection_keyboard(admins: List[AdminModel], action_type: str) -> InlineKeyboardMarkup:
    """Get keyboard for selecting between multiple admin panels."""
    buttons = []
    for admin in admins:
        panel_name = admin.admin_name or admin.marzban_username or f"Panel {admin.id}"
        status = "✅" if admin.is_active else "❌"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {panel_name}",
                callback_data=f"{action_type}_panel_{admin.id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def show_panel_selection_or_execute(message_or_callback: Message | CallbackQuery, action_type: str):
    """Show panel selection if user has multiple panels, otherwise execute action for the single panel."""
    user_id = message_or_callback.from_user.id
    admins = await db.get_admins_for_user(user_id)
    active_admins = [admin for admin in admins if admin.is_active]

    if not active_admins:
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("شما هیچ پنل فعالی ندارید.", show_alert=True)
        else:
            await message_or_callback.answer("شما هیچ پنل فعالی ندارید.")
        return

    actions = {
        'info': show_admin_info,
        'report': show_admin_report,
        'users': show_admin_users,
        'reactivate': show_admin_reactivate,
        'cleanup': show_cleanup_menu,
        'cleanup_small': None,  # placeholder, will be assigned after function definition
    }

    if len(active_admins) == 1:
        admin = active_admins[0]
        await actions[action_type](message_or_callback, admin)
    else:
        text = f"🔹 شما {len(active_admins)} پنل فعال دارید. لطفاً یکی را برای ادامه انتخاب کنید:"
        keyboard = get_panel_selection_keyboard(active_admins, action_type)
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=keyboard)
            await message_or_callback.answer()
        else:
            await message_or_callback.answer(text, reply_markup=keyboard)


@admin_router.message(Command("start"))
async def admin_start(message: Message):
    """Start command for regular admins."""
    if message.from_user.id in config.SUDO_ADMINS:
        return

    if not await db.is_admin_authorized(message.from_user.id):
        # Show public menu instead of unauthorized for normal users
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
        return

    admins = await db.get_admins_for_user(message.from_user.id)
    active_admins = [admin for admin in admins if admin.is_active]
    
    welcome_message = config.MESSAGES["welcome_admin"]
    if len(active_admins) > 1:
        welcome_message += f"\n\n🔹 شما {len(active_admins)} پنل فعال دارید."
    
    await message.answer(welcome_message, reply_markup=get_admin_keyboard())


async def show_admin_info(message_or_callback: Message | CallbackQuery, admin: AdminModel):
    """Show information for a specific admin panel."""
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        admin_stats = await admin_api.get_admin_stats()
        
        # Use historical peak users when assessing percentage
        try:
            peak_users = max(int(getattr(admin, 'users_historical_peak', 0) or 0), int(admin_stats.total_users or 0))
            if peak_users != (getattr(admin, 'users_historical_peak', 0) or 0):
                await db.update_admin(admin.id, users_historical_peak=peak_users)
        except Exception:
            peak_users = admin_stats.total_users

        # Adjust percentage to reflect consumed users (active, not expired, not quota-full)
        user_percentage = (getattr(admin_stats, 'consumed_users', 0) / admin.max_users) * 100 if admin.max_users > 0 else 0
        traffic_percentage = (admin_stats.total_traffic_used / admin.max_total_traffic) * 100 if admin.max_total_traffic > 0 else 0
        
        now = datetime.utcnow()
        created_at = admin.created_at or now
        elapsed_seconds = max(0, (now - created_at).total_seconds())
        total_validity_period = admin.max_total_time
        remaining_time_seconds = max(0, total_validity_period - elapsed_seconds)
        time_percentage = (elapsed_seconds / total_validity_period) * 100 if total_validity_period > 0 else 0
        
        panel_name = admin.admin_name or admin.marzban_username
        
        # Compose detailed users breakdown
        try:
            expired_c = (admin_stats.counts_extra or {}).get("expired", 0)
            quota_full_c = (admin_stats.counts_extra or {}).get("quota_full", 0)
            disabled_c = (admin_stats.counts_extra or {}).get("disabled", 0)
            active_c = (admin_stats.counts_by_status or {}).get("active", 0)
            # Use consumed_users as active for consistency with header count if it differs by one
            # but keep detailed categories as-is, with 'اتمام حجم' wording per request
            users_breakdown = f"(فعال: {getattr(admin_stats, 'consumed_users', active_c)}, منقضی: {expired_c}, اتمام حجم: {quota_full_c}, غیرفعال: {disabled_c})"
        except Exception:
            users_breakdown = ""

        # Handle display for unlimited values (traffic 0 => unlimited, time 0 => unlimited, users 0 => unlimited)
        max_users_txt = "نامحدود" if ((admin.max_users or 0) == 0 or (admin.max_users or 0) >= 1000000) else f"{admin.max_users}"
        max_traffic_txt = "نامحدود" if (admin.max_total_traffic or 0) == 0 else await format_traffic_size(admin.max_total_traffic)
        max_time_seconds = admin.max_total_time or 0
        # Treat very large durations (>=100 years) as unlimited for display
        max_time_txt = "نامحدود" if max_time_seconds == 0 or max_time_seconds >= (36500 * 24 * 60 * 60) else await format_time_duration(max_time_seconds)
        text = (
            f"👤 <b>اطلاعات پنل: {panel_name}</b>\n\n"
            f"- <b>نام کاربری مرزبان:</b> <code>{admin.marzban_username}</code>\n"
            f"- <b>وضعیت:</b> {'✅ فعال' if admin.is_active else '❌ غیرفعال'}\n"
            f"- <b>تاریخ ایجاد:</b> {admin.created_at.strftime('%Y-%m-%d')}\n\n"
            f"📊 <b>محدودیت‌ها و استفاده:</b>\n"
            f"- <b>کاربران:</b> {getattr(admin_stats, 'consumed_users', 0)}/{max_users_txt} ({user_percentage:.1f}%)\n"
            f"  ├ کل: {admin_stats.total_users} {users_breakdown}\n"
            f"  └ اوج تاریخی: {peak_users}\n"
            f"- <b>ترافیک:</b> {await format_traffic_size(admin_stats.total_traffic_used)} / {max_traffic_txt} ({traffic_percentage:.1f}%)\n"
            f"- <b>اعتبار زمانی:</b> {await format_time_duration(remaining_time_seconds)} مانده ({time_percentage:.1f}%)\n"
            f"  └ سقف: {max_time_txt}"
        )

    except Exception as e:
        logger.error(f"Error getting info for admin panel {admin.id}: {e}")
        text = f"❌ خطا در دریافت اطلاعات پنل {admin.admin_name or admin.marzban_username}."

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=get_admin_keyboard())


async def show_admin_report(message_or_callback: Message | CallbackQuery, admin: AdminModel):
    """Show usage report for a specific admin panel."""
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        users = await admin_api.get_users()
        # Use sudo-based admin usage cumulative
        try:
            from marzban_api import marzban_api as _sudo_api
            total_traffic = await _sudo_api.get_admin_usage_cumulative(admin.marzban_username or admin.username or "")
        except Exception:
            total_traffic = sum(u.used_traffic for u in users)
        active_users = len([u for u in users if u.status == 'active'])
        
        panel_name = admin.admin_name or admin.marzban_username
        
        text = (
            f"📈 **گزارش لحظه‌ای پنل: {panel_name}**\n\n"
            f"- **تعداد کل کاربران:** {len(users)}\n"
            f"- **کاربران فعال:** {active_users}\n"
            f"- **مجموع ترافیک مصرفی:** {await format_traffic_size(total_traffic)}"
        )
    except Exception as e:
        logger.error(f"Error getting report for admin panel {admin.id}: {e}")
        text = f"❌ خطا در دریافت گزارش پنل {admin.admin_name or admin.marzban_username}."

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=get_admin_keyboard())


async def show_admin_users(message_or_callback: Message | CallbackQuery, admin: AdminModel):
    """Show user list for a specific admin panel."""
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        users = await admin_api.get_users()
        
        panel_name = admin.admin_name or admin.marzban_username
        
        if not users:
            text = f"👥 **لیست کاربران پنل: {panel_name}**\n\n- هیچ کاربری یافت نشد."
        else:
            user_lines = []
            for user in users[:20]: # Limit to 20 users
                status = "✅" if user.status == 'active' else "❌"
                used = await format_traffic_size(user.used_traffic)
                limit = f"/ {await format_traffic_size(user.data_limit)}" if user.data_limit else ""
                user_lines.append(f"- `{user.username}` {status} ({used}{limit})")
            
            text = f"👥 **لیست کاربران پنل: {panel_name}**\n\n" + "\n".join(user_lines)
            if len(users) > 20:
                text += f"\n\n... و {len(users) - 20} کاربر دیگر."
            # Add panel-scoped actions
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")],
                [InlineKeyboardButton(text=config.BUTTONS["cleanup_old_expired"], callback_data=f"cleanup_menu_panel_{admin.id}")],
                [InlineKeyboardButton(text=config.BUTTONS["cleanup_small_quota"], callback_data=f"cleanup_small_menu_panel_{admin.id}")],
                [InlineKeyboardButton(text=config.BUTTONS["reset_usage"], callback_data=f"reset_panel_{admin.id}")]
            ])

    except Exception as e:
        logger.error(f"Error getting users for admin panel {admin.id}: {e}")
        text = f"❌ خطا در دریافت لیست کاربران پنل {admin.admin_name or admin.marzban_username}."

    if isinstance(message_or_callback, CallbackQuery):
        # If keyboard for users view was created, use it; else default to back only
        try:
            await message_or_callback.message.edit_text(text, reply_markup=keyboard)
        except NameError:
            await message_or_callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=get_admin_keyboard())


async def show_admin_reactivate(message_or_callback: Message | CallbackQuery, admin: AdminModel):
    """Placeholder for reactivating users of a specific panel."""
    panel_name = admin.admin_name or admin.marzban_username
    text = f"🔄 **فعالسازی کاربران پنل: {panel_name}**\n\nاین قابلیت به زودی اضافه خواهد شد."

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=get_admin_keyboard())


# ===== Admin - Buy Reseller Panel Flow =====

class AdminPaymentStates(StatesGroup):
    waiting_for_receipt = State()


class AdminRenewStates(StatesGroup):
    in_flow = State()


@admin_router.callback_query(F.data == "admin_buy_reseller")
async def admin_buy_reseller(callback: CallbackQuery):
    if callback.from_user.id in config.SUDO_ADMINS:
        # Sudo can use own menu; but allow listing anyway
        pass
    plans = await db.get_plans(only_active=True)
    if not plans:
        await callback.message.edit_text(
            "در حال حاضر پلنی برای خرید موجود نیست.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]])
        )
        await callback.answer()
        return
    from utils.notify import seconds_to_days
    lines = ["🛒 پلن‌های نمایندگی:", ""]
    for p in plans:
        traffic_txt = "نامحدود" if p.traffic_limit_bytes is None else f"{await format_traffic_size(p.traffic_limit_bytes)}"
        time_txt = "نامحدود" if p.time_limit_seconds is None else f"{seconds_to_days(p.time_limit_seconds)} روز"
        users_txt = "نامحدود" if p.max_users is None else f"{p.max_users} کاربر"
        type_txt = "حجمی" if (getattr(p, 'plan_type', 'volume') == 'volume') else "پکیجی"
        price_txt = f"{p.price:,}"
        lines.append(f"• {p.name} ({type_txt})")
        lines.append(f"  📦 ترافیک: {traffic_txt}")
        lines.append(f"  ⏱️ زمان: {time_txt}")
        lines.append(f"  👥 کاربر: {users_txt}")
        lines.append(f"  💰 قیمت: {price_txt} تومان")
        lines.append(f"   ➤ برای ثبت سفارش روی دکمه زیر بزنید: #ID {p.id}")
        lines.append("—")
    text = "\n".join(lines).rstrip("—")
    kb_rows = []
    for p in plans:
        kb_rows.append([InlineKeyboardButton(text=f"سفارش #{p.id} - {p.name}", callback_data=f"admin_order_{p.id}")])
    kb_rows.append([InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_order_"))
async def admin_order(callback: CallbackQuery):
    plan_id = int(callback.data.split("_")[-1])
    plans = await db.get_plans(only_active=True)
    plan = next((p for p in plans if p.id == plan_id), None)
    if not plan:
        await callback.answer("پلن یافت نشد.", show_alert=True)
        return
    order_id = await db.add_order(callback.from_user.id, plan_id, plan.price, plan.name)
    if not order_id:
        await callback.answer("خطا در ثبت سفارش.", show_alert=True)
        return
    price_txt = f"{plan.price:,}"
    # Show manual payment cards
    cards = await db.get_cards(only_active=True)
    lines = [
        f"✅ سفارش ثبت شد.\n\nشناسه سفارش: {order_id}\nپلن: {plan.name}\nقیمت: {price_txt} تومان\n",
        config.MESSAGES["public_payment_instructions"],
        "",
        "کارت‌های فعال:",
    ]
    if not cards:
        lines.append("— فعلاً کارتی ثبت نشده. لطفاً با پشتیبانی تماس بگیرید.")
    else:
        for c in cards:
            lines.append(f"• {c.get('bank_name','بانک')} | {c.get('card_number','---- ---- ---- ----')} | {c.get('holder_name','')} ")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["mark_paid"], callback_data=f"admin_mark_paid_{order_id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_mark_paid_"))
async def admin_mark_paid(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[-1])
    order = await db.get_order_by_id(order_id)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("سفارش یافت نشد.", show_alert=True)
        return
    await state.update_data(order_id=order_id)
    await state.set_state(AdminPaymentStates.waiting_for_receipt)
    await callback.message.edit_text(config.MESSAGES["public_send_receipt"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
    await callback.answer()


@admin_router.message(AdminPaymentStates.waiting_for_receipt)
async def admin_receive_payment_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await state.clear()
        return
    if not message.photo:
        await message.answer(config.MESSAGES["public_send_receipt"])
        return
    file_id = message.photo[-1].file_id
    await db.update_order(order_id, receipt_file_id=file_id, status="submitted")
    # Notify sudo admins
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    order = await db.get_order_by_id(order_id)
    plan = await db.get_plan_by_id(order.get("plan_id")) if order else None
    text = (
        f"🧾 سفارش جدید #{order_id}\n\n"
        f"کاربر: {message.from_user.id}\n"
        f"پلن: {plan.name if plan else order.get('plan_name_snapshot','')}\n"
        f"قیمت: {order.get('price_snapshot',0):,} تومان\n\n"
        f"عکس رسید در پیام بعدی ارسال می‌شود."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید و صدور", callback_data=f"order_approve_{order_id}")],
        [InlineKeyboardButton(text="❌ رد", callback_data=f"order_reject_{order_id}")],
        [InlineKeyboardButton(text="🔁 تلاش دوباره صدور", callback_data=f"order_retry_{order_id}")]
    ])
    try:
        for sudo_id in config.SUDO_ADMINS:
            await message.bot.send_message(chat_id=sudo_id, text=text, reply_markup=kb)
            await message.bot.send_photo(chat_id=sudo_id, photo=file_id, caption=f"رسید سفارش #{order_id}")
    except Exception:
        pass
    await state.clear()
    await message.answer(config.MESSAGES["order_submitted_to_admin"], reply_markup=get_admin_keyboard())


# ===== Admin Renew/Extend Flow =====

@admin_router.callback_query(F.data == "admin_renew")
async def admin_renew_entry(callback: CallbackQuery):
    # Choose panel for this admin (if multiple)
    admins = await db.get_admins_for_user(callback.from_user.id)
    active_admins = [a for a in admins if a.is_active]
    if not active_admins:
        await callback.answer("پنل فعالی ندارید.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=(a.admin_name or a.marzban_username or f"Panel {a.id}"), callback_data=f"admin_renew_panel_{a.id}")]
        for a in active_admins
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]])
    await callback.message.edit_text("پنل موردنظر برای تمدید را انتخاب کنید:", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_panel_"))
async def admin_renew_panel(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin or admin.user_id != callback.from_user.id:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    # Persist chosen admin_id in state for downstream steps
    await state.update_data(current_admin_id=admin_id)
    
    rates = await db.get_billing_rates()
    # Determine renewability mode: admin override takes precedence, else plan setting
    try:
        override = getattr(admin, 'allow_incremental_renewal', None)
        if override is not None:
            allow_incremental = bool(override)
        else:
            plan = await db.get_plan_by_id(getattr(admin, 'origin_plan_id', 0) or 0)
            allow_incremental = bool(getattr(plan, 'allow_incremental_renewal', True)) if plan else True
    except Exception:
        allow_incremental = True

    if allow_incremental:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"➕ حجم (1GB = {rates['per_gb_toman']:,} ت)", callback_data=f"admin_renew_traffic_{admin_id}")],
            [InlineKeyboardButton(text=f"➕ زمان (30 روز = {rates['per_30days_toman']:,} ت)", callback_data=f"admin_renew_time_{admin_id}")],
            [InlineKeyboardButton(text=f"➕ کاربر (1 کاربر = {rates['per_user_toman']:,} ت)", callback_data=f"admin_renew_users_{admin_id}")],
            [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="admin_renew")]
        ])
        intro = config.MESSAGES.get("renew_intro", "🔄 تمدید/افزایش محدودیت‌ها (تدریجی مجاز)")
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 تمدید کامل پلن (انتخاب پلن)", callback_data=f"admin_full_renew_{admin_id}")],
            [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="admin_renew")]
        ])
        intro = "🔄 تمدید کامل پلن (پرداخت کل هزینه پلن)"
    await callback.message.edit_text(intro, reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_full_renew_"))
async def admin_full_renew(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin or admin.user_id != callback.from_user.id:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    # Safeguard: only allow for full-renew-only cases
    try:
        override = getattr(admin, 'allow_incremental_renewal', None)
        if override is not None and override:
            await callback.answer("تمدید کامل اجباری نیست؛ می‌توانید از افزایش تدریجی استفاده کنید.", show_alert=True)
            return
        origin_plan = await db.get_plan_by_id(getattr(admin, 'origin_plan_id', 0) or 0)
        plan_allows_incremental = bool(getattr(origin_plan, 'allow_incremental_renewal', True)) if origin_plan else True
        if plan_allows_incremental and override is None:
            await callback.answer("این پنل محدود به تمدید کامل نیست.", show_alert=True)
            return
    except Exception:
        pass
    # Show all active plans for selection (full-renew-only flow)
    plans = await db.get_plans(only_active=True)
    if not plans:
        await callback.answer("هیچ پلن فعالی برای تمدید موجود نیست.", show_alert=True)
        return
    from utils.notify import seconds_to_days
    lines = ["🔁 تمدید کامل: یک پلن را برای تمدید انتخاب کنید:", ""]
    for p in plans:
        traffic_txt = "نامحدود" if p.traffic_limit_bytes is None else f"{await format_traffic_size(p.traffic_limit_bytes)}"
        time_txt = "نامحدود" if p.time_limit_seconds is None else f"{seconds_to_days(p.time_limit_seconds)} روز"
        users_txt = "نامحدود" if p.max_users is None else f"{p.max_users} کاربر"
        price_txt = f"{p.price:,}"
        lines.append(f"• {p.name}")
        lines.append(f"  📦 ترافیک: {traffic_txt}")
        lines.append(f"  ⏱️ زمان: {time_txt}")
        lines.append(f"  👥 کاربر: {users_txt}")
        lines.append(f"  💰 قیمت: {price_txt} تومان")
        lines.append(f"   ➤ برای تمدید با این پلن بزنید: #ID {p.id}")
        lines.append("—")
    text = "\n".join(lines).rstrip("—")
    kb_rows = [
        [InlineKeyboardButton(text=f"تمدید با #{p.id} - {p.name}", callback_data=f"admin_full_renew_plan_{admin_id}_{p.id}")]
        for p in plans
    ]
    kb_rows.append([InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_full_renew_plan_"))
async def admin_full_renew_plan_selected(callback: CallbackQuery):
    parts = callback.data.split("_")
    try:
        admin_id = int(parts[-2])
        plan_id = int(parts[-1])
    except Exception:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    admin = await db.get_admin_by_id(admin_id)
    if not admin or admin.user_id != callback.from_user.id:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    plan = await db.get_plan_by_id(plan_id)
    if not plan:
        await callback.answer("پلن انتخابی یافت نشد.", show_alert=True)
        return
    # Create renew order flagged as reset (apply_as_reset)
    order_id = await db.add_order(callback.from_user.id, plan_id=plan.id, price_snapshot=plan.price, plan_name_snapshot=f"تمدید کامل - {plan.name}")
    if not order_id:
        await callback.answer("خطا در ثبت سفارش تمدید.", show_alert=True)
        return
    await db.update_order(order_id, order_type="renew", target_admin_id=admin_id, apply_as_reset=1)
    # Show payment instructions
    cards = await db.get_cards(only_active=True)
    lines = [
        f"✅ سفارش تمدید کامل ثبت شد.\n\nشناسه سفارش: {order_id}\nپلن انتخابی: {plan.name}\nقیمت: {plan.price:,} تومان\n",
        config.MESSAGES["public_payment_instructions"],
        "",
        "کارت‌های فعال:",
    ]
    if not cards:
        lines.append("— فعلاً کارتی ثبت نشده. لطفاً با پشتیبانی تماس بگیرید.")
    else:
        for c in cards:
            lines.append(f"• {c.get('bank_name','بانک')} | {c.get('card_number','---- ---- ---- ----')} | {c.get('holder_name','')} ")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["mark_paid"], callback_data=f"admin_mark_paid_{order_id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_traffic_") & (~F.data.startswith("admin_renew_traffic_amount_")))
async def admin_renew_traffic(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split("_")[-1])
    await state.update_data(current_admin_id=admin_id)
    rates = await db.get_billing_rates()
    # پیشنهاد گزینه‌ها تا 2 ترابایت
    options_gb = [10, 50, 100, 200, 500, 1024, 2048]  # GB
    rows = []
    for gb in options_gb:
        price = gb * rates['per_gb_toman']
        label_size = ("1TB" if gb == 1024 else ("2TB" if gb == 2048 else f"{gb}GB"))
        rows.append([InlineKeyboardButton(text=f"+{label_size} - {price:,} ت", callback_data=f"admin_renew_traffic_amount_{admin_id}_{gb}")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]])
    try:
        await callback.message.edit_text("مقدار افزایش حجم را انتخاب کنید:", reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await callback.answer()
        else:
            raise
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_traffic_amount_"))
async def admin_renew_traffic_amount(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    try:
        admin_id = int(parts[-2])
    except Exception:
        data = await state.get_data()
        admin_id = int(data.get("current_admin_id"))
    gb = int(parts[-1])
    rates = await db.get_billing_rates()
    price = gb * rates['per_gb_toman']
    # ایجاد سفارش تمدید
    delta_bytes = gb * 1024 * 1024 * 1024
    order_id = await db.add_order(callback.from_user.id, plan_id=0, price_snapshot=price, plan_name_snapshot=f"تمدید حجم +{gb}GB")
    await db.update_order(order_id, order_type="renew", target_admin_id=admin_id, delta_traffic_bytes=delta_bytes)
    # نمایش کارت‌ها و دریافت رسید
    cards = await db.get_cards(only_active=True)
    lines = [
        f"✅ سفارش تمدید ثبت شد.\n\nشناسه سفارش: {order_id}\nافزایش حجم: +{gb}GB\nقیمت: {price:,} تومان\n",
        config.MESSAGES["public_payment_instructions"],
        "",
        "کارت‌های فعال:",
    ]
    if not cards:
        lines.append("— فعلاً کارتی ثبت نشده. لطفاً با پشتیبانی تماس بگیرید.")
    else:
        for c in cards:
            lines.append(f"• {c.get('bank_name','بانک')} | {c.get('card_number','---- ---- ---- ----')} | {c.get('holder_name','')} ")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["mark_paid"], callback_data=f"admin_mark_paid_{order_id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_time_") & (~F.data.startswith("admin_renew_time_amount_")))
async def admin_renew_time(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split("_")[-1])
    await state.update_data(current_admin_id=admin_id)
    rates = await db.get_billing_rates()
    options = [30, 90, 180, 360]  # days
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"+{d} روز - {((d // 30) * rates['per_30days_toman']):,} ت", callback_data=f"admin_renew_time_amount_{admin_id}_{d}")]
        for d in options
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]])
    try:
        await callback.message.edit_text("افزایش زمان را انتخاب کنید:", reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await callback.answer()
        else:
            raise
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_time_amount_"))
async def admin_renew_time_amount(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    try:
        admin_id = int(parts[-2])
    except Exception:
        data = await state.get_data()
        admin_id = int(data.get("current_admin_id"))
    days = int(parts[-1])
    rates = await db.get_billing_rates()
    price = (days // 30) * rates['per_30days_toman']
    delta_seconds = days * 24 * 60 * 60
    order_id = await db.add_order(callback.from_user.id, plan_id=0, price_snapshot=price, plan_name_snapshot=f"تمدید زمان +{days} روز")
    await db.update_order(order_id, order_type="renew", target_admin_id=admin_id, delta_time_seconds=delta_seconds)
    cards = await db.get_cards(only_active=True)
    lines = [
        f"✅ سفارش تمدید ثبت شد.\n\nشناسه سفارش: {order_id}\nافزایش زمان: +{days} روز\nقیمت: {price:,} تومان\n",
        config.MESSAGES["public_payment_instructions"],
        "",
        "کارت‌های فعال:",
    ]
    if not cards:
        lines.append("— فعلاً کارتی ثبت نشده. لطفاً با پشتیبانی تماس بگیرید.")
    else:
        for c in cards:
            lines.append(f"• {c.get('bank_name','بانک')} | {c.get('card_number','---- ---- ---- ----')} | {c.get('holder_name','')} ")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["mark_paid"], callback_data=f"admin_mark_paid_{order_id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_users_") & (~F.data.startswith("admin_renew_users_amount_")))
async def admin_renew_users(callback: CallbackQuery, state: FSMContext):
    admin_id = int(callback.data.split("_")[-1])
    await state.update_data(current_admin_id=admin_id)
    rates = await db.get_billing_rates()
    options = [10, 50, 100, 200]  # users
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"+{u} کاربر - {u * rates['per_user_toman']:,} ت", callback_data=f"admin_renew_users_amount_{admin_id}_{u}")]
        for u in options
    ] + [[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]])
    try:
        await callback.message.edit_text("افزایش تعداد کاربر را انتخاب کنید:", reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await callback.answer()
        else:
            raise
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_renew_users_amount_"))
async def admin_renew_users_amount(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    try:
        admin_id = int(parts[-2])
    except Exception:
        data = await state.get_data()
        admin_id = int(data.get("current_admin_id"))
    users = int(parts[-1])
    rates = await db.get_billing_rates()
    price = users * rates['per_user_toman']
    order_id = await db.add_order(callback.from_user.id, plan_id=0, price_snapshot=price, plan_name_snapshot=f"افزایش کاربر +{users}")
    await db.update_order(order_id, order_type="renew", target_admin_id=admin_id, delta_users=users)
    cards = await db.get_cards(only_active=True)
    lines = [
        f"✅ سفارش تمدید ثبت شد.\n\nشناسه سفارش: {order_id}\nافزایش کاربر: +{users}\nقیمت: {price:,} تومان\n",
        config.MESSAGES["public_payment_instructions"],
        "",
        "کارت‌های فعال:",
    ]
    if not cards:
        lines.append("— فعلاً کارتی ثبت نشده. لطفاً با پشتیبانی تماس بگیرید.")
    else:
        for c in cards:
            lines.append(f"• {c.get('bank_name','بانک')} | {c.get('card_number','---- ---- ---- ----')} | {c.get('holder_name','')} ")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=config.BUTTONS["mark_paid"], callback_data=f"admin_mark_paid_{order_id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=f"admin_renew_panel_{admin_id}")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


async def show_cleanup_menu(callback: CallbackQuery, admin: AdminModel):
    """Show cleanup confirmation for users expired over 10 days (panel-scoped)."""
    # Allow owner admin or sudo
    if callback.from_user.id not in (config.SUDO_ADMINS + [admin.user_id]):
        await callback.answer("غیرمجاز", show_alert=True)
        return
    panel_name = admin.admin_name or admin.marzban_username
    # Compute count for this panel only
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        old_expired = await admin_api.get_users_expired_over_days(10)
        count = len(old_expired)
    except Exception as e:
        logger.error(f"Error fetching old expired users for admin {admin.id}: {e}")
        count = 0
    text = (
        f"🧹 حذف کاربران منقضی‌شده بیش از ۱۰ روز (همین پنل)\n\n"
        f"پنل: {panel_name}\n"
        f"تعداد شناسایی‌شده: {count} کاربر\n\n"
        f"آیا مایل به حذف آن‌ها هستید؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"cleanup_confirm_panel_{admin.id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


async def perform_cleanup(callback: CallbackQuery, admin: AdminModel):
    """Delete users expired more than 10 days for this panel only."""
    if callback.from_user.id not in (config.SUDO_ADMINS + [admin.user_id]):
        await callback.answer("غیرمجاز", show_alert=True)
        return
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        old_expired = await admin_api.get_users_expired_over_days(10)
        candidate_count = len(old_expired)
        # Progress feedback
        try:
            progress_msg = await callback.message.answer(
                f"⏳ در حال پاکسازی لطفا صبر کنید\nمنقضی‌های ۱۰+ روز...\nکاندید: {candidate_count}\nحذف‌شده: 0"
            )
        except Exception:
            progress_msg = None
        deleted = 0
        processed = 0
        for u in old_expired:
            ok = await marzban_api.remove_user(u.username)
            processed += 1
            if ok:
                deleted += 1
            # Update progress every 25 items or on last
            if progress_msg and (processed % 25 == 0 or processed == candidate_count):
                try:
                    await progress_msg.edit_text(
                        f"⏳ در حال پاکسازی لطفا صبر کنید\nمنقضی‌های ۱۰+ روز...\nکاندید: {candidate_count}\nپردازش‌شده: {processed}\nحذف‌شده: {deleted}"
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        pass
                    else:
                        raise
        msg = f"✅ {deleted} کاربر قدیمی در همین پنل حذف شد."
    except Exception as e:
        logger.error(f"Error performing cleanup for admin {admin.id}: {e}")
        msg = "❌ خطا در حذف کاربران قدیمی پنل."
    is_sudo = callback.from_user.id in config.SUDO_ADMINS
    back_cb = "back_to_main" if is_sudo else "back_to_admin_main"
    # Cleanup progress message if exists
    try:
        if progress_msg:
            await progress_msg.delete()
    except Exception:
        pass
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data=back_cb)]]))
    await callback.answer()


async def show_cleanup_small_menu(callback: CallbackQuery, admin: AdminModel):
    """Show confirmation for panel-scoped cleanup of <=1GB finished/time-expired users."""
    if callback.from_user.id not in (config.SUDO_ADMINS + [admin.user_id]):
        await callback.answer("غیرمجاز", show_alert=True)
        return
    panel_name = admin.admin_name or admin.marzban_username
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        to_delete = await admin_api.get_small_quota_finished_users(1073741824)
        count = len(to_delete)
    except Exception as e:
        logger.error(f"Error fetching small-quota finished users for admin {admin.id}: {e}")
        count = 0
    text = (
        f"🧹 حذف کاربران ≤۱GB تمام‌شده/منقضی (پنل)\n\n"
        f"پنل: {panel_name}\n"
        f"تعداد شناسایی‌شده: {count} کاربر\n\n"
        f"آیا مایل به حذف آن‌ها هستید؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"cleanup_small_confirm_panel_{admin.id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("cleanup_small_confirm_panel_"))
async def cleanup_small_confirm_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await perform_cleanup_small(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)


async def perform_cleanup_small(callback: CallbackQuery, admin: AdminModel):
    """Delete small-quota finished/time-expired users for this panel only."""
    if callback.from_user.id not in (config.SUDO_ADMINS + [admin.user_id]):
        await callback.answer("غیرمجاز", show_alert=True)
        return
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        to_delete = await admin_api.get_small_quota_finished_users(1073741824)
        candidate_count = len(to_delete)
        # Progress feedback
        try:
            progress_msg = await callback.message.answer(
                f"⏳ در حال پاکسازی لطفا صبر کنید\nساب‌های ≤۱GB...\nکاندید: {candidate_count}\nحذف‌شده: 0\nناموفق: 0"
            )
        except Exception:
            progress_msg = None
        deleted = 0
        failed = 0
        processed = 0
        for u in to_delete:
            ok = await marzban_api.remove_user(u.username)
            processed += 1
            if ok:
                deleted += 1
            else:
                failed += 1
            if progress_msg and (processed % 25 == 0 or processed == candidate_count):
                try:
                    await progress_msg.edit_text(
                        f"⏳ در حال پاکسازی لطفا صبر کنید\nساب‌های ≤۱GB...\nکاندید: {candidate_count}\nپردازش‌شده: {processed}\nحذف‌شده: {deleted}\nناموفق: {failed}"
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        pass
                    else:
                        raise
        msg = (
            "✅ پاکسازی ساب‌های ≤۱GB تمام‌شده/منقضی در همین پنل انجام شد\n\n"
            f"کاندید: {candidate_count}\n"
            f"حذف‌شده: {deleted}\n"
            f"ناموفق: {failed}"
        )
    except Exception as e:
        logger.error(f"Error performing small cleanup for admin {admin.id}: {e}")
        msg = "❌ خطا در حذف کاربران سهمیه کم پنل."
    try:
        if progress_msg:
            await progress_msg.delete()
    except Exception:
        pass
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
    await callback.answer()


async def show_reset_menu(callback: CallbackQuery, admin: AdminModel):
    """Show reset options for this panel: traffic (users' data) or time (panel)."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("این قابلیت فقط برای سودو فعال است.", show_alert=True)
        return
    panel_name = admin.admin_name or admin.marzban_username
    text = (
        f"♻️ ریست مصرف پنل: {panel_name}\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📡 ریست ترافیک کاربران پنل", callback_data=f"reset_traffic_panel_{admin.id}")],
        [InlineKeyboardButton(text="⏱️ ریست زمان مصرف‌شده پنل", callback_data=f"reset_time_panel_{admin.id}")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data.startswith("reset_traffic_panel_"))
async def reset_traffic_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    try:
        logger.info(f"reset_traffic_panel_selected by {callback.from_user.id} (sudo={callback.from_user.id in config.SUDO_ADMINS}), admin_id={admin_id}, exists={bool(admin)}")
    except Exception:
        pass
    if admin and (admin.user_id == callback.from_user.id or callback.from_user.id in config.SUDO_ADMINS):
        await perform_reset_traffic(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)


@admin_router.callback_query(F.data.startswith("reset_time_panel_"))
async def reset_time_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    try:
        logger.info(f"reset_time_panel_selected by {callback.from_user.id} (sudo={callback.from_user.id in config.SUDO_ADMINS}), admin_id={admin_id}, exists={bool(admin)}")
    except Exception:
        pass
    if admin and (admin.user_id == callback.from_user.id or callback.from_user.id in config.SUDO_ADMINS):
        await perform_reset_time(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)


async def perform_reset_traffic(callback: CallbackQuery, admin: AdminModel):
    """Reset data usage for all users of this panel (panel-scoped)."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("این قابلیت فقط برای سودو فعال است.", show_alert=True)
        return
    try:
        admin_api = await marzban_api.create_admin_api(admin.marzban_username, admin.marzban_password)
        users = await admin_api.get_users()
        reset = 0
        failed = 0
        for u in users:
            ok = await admin_api.reset_user_data_usage(u.username)
            if ok:
                reset += 1
            else:
                failed += 1
        msg = (
            "✅ ریست ترافیک کاربران پنل انجام شد\n\n"
            f"ریست‌شده: {reset}\n"
            f"ناموفق: {failed}"
        )
    except Exception as e:
        logger.error(f"Error resetting traffic for admin {admin.id}: {e}")
        msg = "❌ خطا در ریست ترافیک کاربران پنل."
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
    await callback.answer()


async def perform_reset_time(callback: CallbackQuery, admin: AdminModel):
    """Reset time usage for this panel by resetting created_at to now (affects remaining/percentage)."""
    if callback.from_user.id not in config.SUDO_ADMINS:
        await callback.answer("این قابلیت فقط برای سودو فعال است.", show_alert=True)
        return
    try:
        # Database-level reset: set created_at = now
        from datetime import datetime as _dt
        now = _dt.utcnow()
        await db.update_admin(admin.id, created_at=now)
        msg = "✅ زمان مصرف‌شده پنل ریست شد (از الان محاسبه می‌شود)."
    except Exception as e:
        logger.error(f"Error resetting time for admin {admin.id}: {e}")
        msg = "❌ خطا در ریست زمان پنل."
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
    await callback.answer()


# Main callback handlers that trigger panel selection
@admin_router.callback_query(F.data == "my_info")
async def my_info_callback(callback: CallbackQuery):
    await show_panel_selection_or_execute(callback, "info")

@admin_router.callback_query(F.data == "my_report")
async def my_report_callback(callback: CallbackQuery):
    await show_panel_selection_or_execute(callback, "report")

@admin_router.callback_query(F.data == "my_users")
async def my_users_callback(callback: CallbackQuery):
    await show_panel_selection_or_execute(callback, "users")

@admin_router.callback_query(F.data == "reactivate_users")
async def reactivate_users_callback(callback: CallbackQuery):
    await show_panel_selection_or_execute(callback, "reactivate")


@admin_router.callback_query(F.data == "cleanup_old_expired")
async def cleanup_old_expired_entry(callback: CallbackQuery):
    await callback.answer("این قابلیت فقط برای سودو فعال است.", show_alert=True)


@admin_router.callback_query(F.data == "cleanup_small_quota")
async def cleanup_small_quota_entry(callback: CallbackQuery):
    await callback.answer("این قابلیت فقط برای سودو فعال است.", show_alert=True)


@admin_router.callback_query(F.data == "reset_usage")
async def reset_usage_entry(callback: CallbackQuery):
    await callback.answer("این قابلیت فقط برای سودو فعال است.", show_alert=True)


# Handlers that are called after a panel is selected
@admin_router.callback_query(F.data.startswith("info_panel_"))
async def info_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await show_admin_info(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)

@admin_router.callback_query(F.data.startswith("report_panel_"))
async def report_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await show_admin_report(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)

@admin_router.callback_query(F.data.startswith("users_panel_"))
async def users_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await show_admin_users(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)

@admin_router.callback_query(F.data.startswith("cleanup_menu_panel_"))
async def cleanup_menu_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await show_cleanup_menu(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)


@admin_router.callback_query(F.data.startswith("cleanup_small_menu_panel_"))
async def cleanup_small_menu_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if not admin:
        await callback.answer("پنل یافت نشد.", show_alert=True)
        return
    # Allow owner admin or sudo to access
    if callback.from_user.id == admin.user_id or callback.from_user.id in config.SUDO_ADMINS:
        await show_cleanup_small_menu(callback, admin)
    else:
        await callback.answer("غیرمجاز", show_alert=True)


@admin_router.callback_query(F.data.startswith("reset_panel_"))
async def reset_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await show_reset_menu(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)

@admin_router.callback_query(F.data.startswith("cleanup_confirm_panel_"))
async def cleanup_confirm_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await perform_cleanup(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)

@admin_router.callback_query(F.data.startswith("reactivate_panel_"))
async def reactivate_panel_selected(callback: CallbackQuery):
    admin_id = int(callback.data.split("_")[-1])
    admin = await db.get_admin_by_id(admin_id)
    if admin and admin.user_id == callback.from_user.id:
        await show_admin_reactivate(callback, admin)
    else:
        await callback.answer("پنل یافت نشد.", show_alert=True)


# Back to main menu
@admin_router.callback_query(F.data == "back_to_admin_main")
async def back_to_admin_main(callback: CallbackQuery):
    """Return to admin main menu."""
    await callback.message.edit_text(config.MESSAGES["welcome_admin"], reply_markup=get_admin_keyboard())
    await callback.answer()


async def show_global_cleanup_menu(callback: CallbackQuery):
    """Show confirmation for GLOBAL cleanup (expired >10 days across whole panel)."""
    try:
        old_expired = await marzban_api.get_users_expired_over_days(None, 10)
        count = len(old_expired)
    except Exception as e:
        logger.error(f"Error fetching global old expired users: {e}")
        count = 0
    text = (
        "🧹 حذف کاربران منقضی‌شده بیش از ۱۰ روز (سراسری)\n\n"
        f"تعداد شناسایی‌شده: {count} کاربر\n\n"
        "آیا مایل به حذف آن‌ها هستید؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، حذف کن", callback_data="global_cleanup_confirm")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


async def show_global_small_quota_menu(callback: CallbackQuery):
    """(Not used for regular admins anymore) Show confirmation for GLOBAL cleanup."""
    try:
        to_delete = await marzban_api.get_small_quota_finished_users(1073741824, None)
        count = len(to_delete)
    except Exception as e:
        logger.error(f"Error fetching global small-quota finished users: {e}")
        count = 0
    text = (
        "🧹 حذف کاربران با سهمیه ≤۱GB تمام‌شده یا زمان‌انقضا گذشته (سراسری)\n\n"
        f"تعداد شناسایی‌شده: {count} کاربر\n\n"
        "آیا مایل به حذف آن‌ها هستید؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، حذف کن", callback_data="global_small_quota_cleanup_confirm")],
        [InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data == "global_cleanup_confirm")
async def global_cleanup_confirm(callback: CallbackQuery):
    """Perform GLOBAL cleanup (expired >10 days across whole panel)."""
    try:
        candidates = await marzban_api.get_users_expired_over_days(None, 10)
        candidate_count = len(candidates)
        deleted = 0
        failed = 0
        for u in candidates:
            ok = await marzban_api.remove_user(u.username)
            if ok:
                deleted += 1
            else:
                failed += 1
        msg = (
            "✅ پاکسازی منقضی‌های ۱۰+ روز (سراسری) انجام شد\n\n"
            f"کاندید: {candidate_count}\n"
            f"حذف‌شده: {deleted}\n"
            f"ناموفق: {failed}"
        )
    except Exception as e:
        logger.error(f"Error performing global cleanup: {e}")
        msg = "❌ خطا در حذف کاربران قدیمی (سراسری)."
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
    await callback.answer()


@admin_router.callback_query(F.data == "global_small_quota_cleanup_confirm")
async def global_small_quota_cleanup_confirm(callback: CallbackQuery):
    """(Not used for regular admins anymore) Perform GLOBAL small-quota cleanup (<=1GB)."""
    try:
        to_delete = await marzban_api.get_small_quota_finished_users(1073741824, None)
        candidate_count = len(to_delete)
        # دسته‌بندی: بر اساس زمان یا سهمیه کوچک
        from time import time as _now
        now_ts = _now()
        time_expired_count = 0
        small_quota_finished_count = 0
        for u in to_delete:
            time_expired = (u.expire is not None and u.expire <= now_ts)
            if time_expired:
                time_expired_count += 1
            else:
                small_quota_finished_count += 1
        deleted = 0
        failed = 0
        for u in to_delete:
            ok = await marzban_api.remove_user(u.username)
            if ok:
                deleted += 1
            else:
                failed += 1
        msg = (
            "✅ پاکسازی سراسری ساب‌های ≤۱GB تمام‌شده/منقضی انجام شد\n\n"
            f"کاندید: {candidate_count}\n"
            f"— بر اساس زمان‌انقضا: {time_expired_count}\n"
            f"— بر اساس سهمیه کوچک: {small_quota_finished_count}\n"
            f"حذف‌شده: {deleted}\n"
            f"ناموفق: {failed}"
        )
    except Exception as e:
        logger.error(f"Error performing global small-quota cleanup: {e}")
        msg = "❌ خطا در حذف کاربران سهمیه کم (سراسری)."
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=config.BUTTONS["back"], callback_data="back_to_admin_main")]]))
    await callback.answer()

# Text command handlers
@admin_router.message(Command("my_info", "اطلاعات_من"))
async def my_info_command(message: Message):
    await show_panel_selection_or_execute(message, "info")

@admin_router.message(Command("my_report", "گزارش_من"))
async def my_report_command(message: Message):
    await show_panel_selection_or_execute(message, "report")

@admin_router.message(Command("my_users", "کاربران_من"))
async def my_users_command(message: Message):
    await show_panel_selection_or_execute(message, "users")

@admin_router.message(StateFilter(None), F.text & ~F.text.startswith('/'))
async def admin_unhandled_text(message: Message):
    """Handle unhandled text for regular admin users when not in a state."""
    if message.from_user.id in config.SUDO_ADMINS or not await db.is_admin_authorized(message.from_user.id):
        return

    await message.answer(
        "دستور نا مشخص است. لطفاً از دکمه‌های زیر یا دستورات موجود استفاده کنید.",
        reply_markup=get_admin_keyboard()
    )
