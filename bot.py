import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from database import db
from marzban_api import marzban_api
from handlers.sudo_handlers import sudo_router
from handlers.admin_handlers import admin_router
from handlers.public_handlers import public_router
from scheduler import init_scheduler


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class MarzbanAdminBot:
    def __init__(self):
        self.bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher()
        self.scheduler = None

    async def setup(self):
        """Setup bot components."""
        logger.info("Setting up Marzban Admin Bot...")
        
        # Initialize database
        try:
            await db.init_db()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
        
        # Test Marzban API connection
        try:
            if await marzban_api.test_connection():
                logger.info("Marzban API connection successful")
            else:
                logger.warning("Marzban API connection failed - bot will continue but some features may not work")
        except Exception as e:
            logger.warning(f"Error testing Marzban API: {e}")
        
        # Register forced-join middleware BEFORE routers so it gates everything
        self.dp.message.outer_middleware(ForcedJoinMiddleware(self.bot))
        self.dp.callback_query.outer_middleware(ForcedJoinMiddleware(self.bot))
        
        # Setup routers - IMPORTANT: Register state-specific routers FIRST
        # This ensures FSM state handlers are processed before general handlers
        logger.info("=== ROUTER REGISTRATION ORDER (CRITICAL FOR FSM) ===")
        logger.info("Registering sudo_router (FSM-aware)...")
        self.dp.include_router(sudo_router)
        logger.info("✅ sudo_router registered successfully")
        
        logger.info("Registering admin_router (FSM-aware)...")
        self.dp.include_router(admin_router)
        logger.info("✅ admin_router registered successfully")
        logger.info("Registering public_router ...")
        self.dp.include_router(public_router)
        logger.info("✅ public_router registered successfully")
        
        logger.info("=== GENERAL HANDLERS (AFTER FSM ROUTERS) ===")
        # Add global handlers AFTER state-specific routers
        # Start is handled by routers (admin/public) now
        
        # Register help handler with proper filters to avoid FSM interference
        # Help and general handlers are optional; routers handle most routes.
        logger.info("=== ROUTER REGISTRATION COMPLETE ===")
        logger.info("📋 Handler order: FSM routers → Command handlers → StateFilter(None) handlers")
        
        # Initialize scheduler
        self.scheduler = init_scheduler(self.bot)
        
        logger.info("Bot setup completed")

    async def help_handler(self, message: Message, state: FSMContext = None):
        """Handler for unrecognized commands and help."""
        user_id = message.from_user.id
        current_state = await state.get_state() if state else None
        logger.info(f"Help handler activated for user {user_id}, current state: {current_state}, message: {message.text}")
        if current_state:
            logger.error(f"CRITICAL: Help handler called for user {user_id} in state {current_state} - StateFilter(None) not working properly!")
            return
        if user_id not in config.SUDO_ADMINS and not await db.is_admin_authorized(user_id):
            from handlers.public_handlers import get_public_main_keyboard
            await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
            return
        if user_id in config.SUDO_ADMINS:
            logger.info(f"Providing sudo admin help to user {user_id}")
            help_text = (
                "🤖 دستورات سودو ادمین:\n\n"
                "📝 مدیریت ادمین‌ها:\n"
                "• /add_admin - افزودن ادمین جدید\n"
                "• /show_admins یا /list_admins - نمایش لیست ادمین‌ها\n"
                "• /remove_admin - غیرفعالسازی پنل\n"
                "• /edit_panel - ویرایش محدودیت‌های پنل\n"
                "• /admin_status - وضعیت تفصیلی ادمین‌ها\n"
                "• /activate_admin - فعالسازی ادمین غیرفعال\n\n"
                "📋 یا از دکمه‌های شیشه‌ای استفاده کنید:"
            )
            from handlers.sudo_handlers import get_sudo_keyboard
            await message.answer(help_text, reply_markup=get_sudo_keyboard())
        else:
            logger.info(f"Providing regular admin help to user {user_id}")
            help_text = (
                "🤖 دستورات ادمین معمولی:\n\n"
                "📊 گزارش‌گیری:\n"
                "• /گزارش_من - گزارش لحظه‌ای شما\n"
                "• /کاربران_من - لیست کاربران شما\n\n"
                "📋 یا از دکمه‌های شیشه‌ای استفاده کنید:"
            )
            from handlers.admin_handlers import get_admin_keyboard
            await message.answer(help_text, reply_markup=get_admin_keyboard())
        logger.info(f"Help message sent to user {user_id}")

    async def unauthorized_handler(self, message: Message, state: FSMContext = None):
        """Handler for unauthorized users."""
        user_id = message.from_user.id
        current_state = await state.get_state() if state else None
        logger.info(f"Unauthorized handler activated for user {user_id}, current state: {current_state}, message: {message.text}")
        if current_state:
            logger.warning(f"Unauthorized handler called for user {user_id} in state {current_state} with message: {message.text} - this should not happen")
            return
        if user_id not in config.SUDO_ADMINS:
            chans = await db.get_forced_channels()
            if chans:
                not_joined = []
                for ch in chans:
                    try:
                        member = await self.bot.get_chat_member(chat_id=ch.get('chat_id'), user_id=user_id)
                        status = getattr(member, 'status', None)
                        if str(status).lower() not in ['member', 'administrator', 'creator']:
                            not_joined.append(ch)
                    except Exception:
                        not_joined.append(ch)
                if not_joined:
                    lines = ["برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید:", ""]
                    kb_rows = []
                    for ch in not_joined:
                        title = ch.get('title') or ch.get('chat_id')
                        link = ch.get('invite_link') or (f"https://t.me/{title.lstrip('@')}" if str(ch.get('chat_id')).startswith('@') else None)
                        if link:
                            lines.append(f"• {title}")
                            kb_rows.append([InlineKeyboardButton(text=title, url=link)])
                        else:
                            lines.append(f"• {title}")
                    kb_rows.append([InlineKeyboardButton(text="✅ بررسی مجدد", callback_data="forced_join_refresh")])
                    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
                    return
        if user_id not in config.SUDO_ADMINS and not await db.is_admin_authorized(user_id):
            from handlers.public_handlers import get_public_main_keyboard
            await message.answer(
                "به ربات خوش آمدید!",
                reply_markup=get_public_main_keyboard()
            )
            logger.info(f"Public user {user_id} opened the bot")

    async def general_message_handler(self, message: Message, state: FSMContext = None):
        """General handler for unhandled messages."""
        user_id = message.from_user.id
        current_state = await state.get_state() if state else None
        logger.info(f"General message handler activated for user {user_id}, current state: {current_state}, message: {message.text}")
        if current_state:
            logger.error(f"CRITICAL: General handler called for user {user_id} in state {current_state} with message: {message.text} - StateFilter(None) not working properly!")
            return
        if user_id in config.SUDO_ADMINS:
            logger.info(f"Providing sudo admin help to user {user_id}")
            await message.answer(
                "🔐 شما سودو ادمین هستید.\n\n"
                "📋 دستورات موجود:\n"
                "• /start - منوی اصلی\n"
                "• /add_admin - افزودن ادمین جدید\n"
                "• /show_admins - نمایش لیست ادمین‌ها\n"
                "• /remove_admin - غیرفعالسازی پنل\n"
                "• /edit_panel - ویرایش محدودیت‌های پنل\n"
                "• /admin_status - وضعیت ادمین‌ها\n"
                "• /activate_admin - فعالسازی ادمین غیرفعال\n\n"
                "برای دسترسی به منوی اصلی /start را بزنید."
            )
            logger.info(f"Sudo admin help message sent to user {user_id}")
            return
        if await db.is_admin_authorized(user_id):
            logger.info(f"Providing regular admin help to user {user_id}")
            await message.answer(
                "👋 شما ادمین معمولی هستید.\n\n"
                "📋 دستورات موجود:\n"
                "• /start - منوی اصلی\n"
                "• /گزارش_من - گزارش استفاده\n"
                "• /کاربران_من - لیست کاربران\n"
                "• /اطلاعات_من - اطلاعات حساب\n\n"
                "برای دسترسی به منوی اصلی /start را بزنید."
            )
            logger.info(f"Regular admin help message sent to user {user_id}")
            return
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())

    async def start_polling(self):
        """Start bot polling."""
        logger.info("Starting bot polling...")
        try:
            await self.scheduler.start()
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Error during polling: {e}")
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up bot resources...")
        try:
            if self.scheduler:
                await self.scheduler.stop()
            await db.close()
            await self.bot.session.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def send_startup_message(self):
        """Send startup notification to sudo admins."""
        startup_message = (
            "🚀 ربات مدیریت ادمین‌های مرزبان راه‌اندازی شد!\n\n"
            f"⏰ دوره مانیتورینگ: {config.MONITORING_INTERVAL} ثانیه\n"
            f"📊 آستانه هشدار: {int(config.WARNING_THRESHOLD * 100)}%\n"
            f"🔗 آدرس مرزبان: {config.MARZBAN_URL}"
        )
        for sudo_id in config.SUDO_ADMINS:
            try:
                await self.bot.send_message(sudo_id, startup_message)
            except Exception as e:
                logger.warning(f"Failed to send startup message to sudo {sudo_id}: {e}")


class ForcedJoinMiddleware(BaseMiddleware):
    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    async def __call__(self, handler, event, data):
        try:
            user = getattr(event, 'from_user', None)
            if not user:
                return await handler(event, data)
            user_id = user.id
            if user_id in config.SUDO_ADMINS:
                return await handler(event, data)
            # Allow refresh callback to pass through
            if hasattr(event, 'data') and getattr(event, 'data', '') == 'forced_join_refresh':
                return await handler(event, data)
            chans = await db.get_forced_channels()
            if not chans:
                return await handler(event, data)
            not_joined = []
            for ch in chans:
                try:
                    raw_chat_id = ch.get('chat_id')
                    chat_id = raw_chat_id
                    if isinstance(raw_chat_id, str) and raw_chat_id.isdigit() and not raw_chat_id.startswith('-100'):
                        chat_id = f"-100{raw_chat_id}"
                    # Convert numeric to int
                    chat_id_to_use = int(chat_id) if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit() else chat_id
                    member = await self.bot.get_chat_member(chat_id=chat_id_to_use, user_id=user_id)
                    status = getattr(member, 'status', None)
                    if hasattr(status, 'value'):
                        s = status.value.lower()
                    elif hasattr(status, 'name'):
                        s = status.name.lower()
                    else:
                        s = str(status).lower()
                    if s not in ['member', 'administrator', 'creator']:
                        not_joined.append(ch)
                except Exception:
                    not_joined.append(ch)
            if not not_joined:
                return await handler(event, data)
            lines = ["برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید:", ""]
            kb_rows = []
            for ch in not_joined:
                title = ch.get('title') or ch.get('chat_id')
                link = ch.get('invite_link') or (f"https://t.me/{title.lstrip('@')}" if str(ch.get('chat_id')).startswith('@') else None)
                if link:
                    lines.append(f"• {title}")
                    kb_rows.append([InlineKeyboardButton(text=title, url=link)])
                else:
                    lines.append(f"• {title}")
            kb_rows.append([InlineKeyboardButton(text="✅ بررسی مجدد", callback_data="forced_join_refresh")])
            # Send as reply if message, or answer callback
            if hasattr(event, 'message') and event.message:
                await event.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
            elif hasattr(event, 'message'):
                await event.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
            else:
                # Fallback for callbacks
                try:
                    await self.bot.send_message(chat_id=user_id, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
                except Exception:
                    pass
            return  # Block further handling
        except Exception as e:
            logger.error(f"ForcedJoinMiddleware error: {e}")
            return await handler(event, data)

    async def help_handler(self, message: Message, state: FSMContext = None):
        """Handler for unrecognized commands and help."""
        user_id = message.from_user.id
        
        # Log handler activation with detailed state information
        current_state = await state.get_state() if state else None
        logger.info(f"Help handler activated for user {user_id}, current state: {current_state}, message: {message.text}")
        
        # This should not happen anymore due to StateFilter(None), but keep as safety check
        if current_state:
            logger.error(f"CRITICAL: Help handler called for user {user_id} in state {current_state} - StateFilter(None) not working properly!")
            return  # Don't interfere with FSM flow
        
        # Check if user is authorized
        if user_id not in config.SUDO_ADMINS and not await db.is_admin_authorized(user_id):
            from handlers.public_handlers import get_public_main_keyboard
            await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())
            return
        
        # Different help messages for sudo and regular admins
        if user_id in config.SUDO_ADMINS:
            logger.info(f"Providing sudo admin help to user {user_id}")
            help_text = (
                "🤖 دستورات سودو ادمین:\n\n"
                "📝 مدیریت ادمین‌ها:\n"
                "• /add_admin - افزودن ادمین جدید\n"
                "• /show_admins یا /list_admins - نمایش لیست ادمین‌ها\n"
                "• /remove_admin - غیرفعالسازی پنل\n"
                "• /edit_panel - ویرایش محدودیت‌های پنل\n"
                "• /admin_status - وضعیت تفصیلی ادمین‌ها\n"
                "• /activate_admin - فعالسازی ادمین غیرفعال\n\n"
                "📋 یا از دکمه‌های شیشه‌ای استفاده کنید:"
            )
            from handlers.sudo_handlers import get_sudo_keyboard
            await message.answer(help_text, reply_markup=get_sudo_keyboard())
        else:
            logger.info(f"Providing regular admin help to user {user_id}")
            help_text = (
                "🤖 دستورات ادمین معمولی:\n\n"
                "📊 گزارش‌گیری:\n"
                "• /گزارش_من - گزارش لحظه‌ای شما\n"
                "• /کاربران_من - لیست کاربران شما\n\n"
                "📋 یا از دکمه‌های شیشه‌ای استفاده کنید:"
            )
            from handlers.admin_handlers import get_admin_keyboard
            await message.answer(help_text, reply_markup=get_admin_keyboard())
        
        logger.info(f"Help message sent to user {user_id}")

    async def unauthorized_handler(self, message: Message, state: FSMContext = None):
        """Handler for unauthorized users."""
        user_id = message.from_user.id
        
        # Log handler activation with state information
        current_state = await state.get_state() if state else None
        logger.info(f"Unauthorized handler activated for user {user_id}, current state: {current_state}, message: {message.text}")
        
        # This should not happen with proper StateFilter, but keep as safety check
        if current_state:
            logger.warning(f"Unauthorized handler called for user {user_id} in state {current_state} with message: {message.text} - this should not happen")
            return  # Don't interfere with FSM flow
        
        # Forced join gate for any non-sudo
        if user_id not in config.SUDO_ADMINS:
            chans = await db.get_forced_channels()
            if chans:
                # Check membership in all active channels
                not_joined = []
                for ch in chans:
                    try:
                        member = await self.bot.get_chat_member(chat_id=ch.get('chat_id'), user_id=user_id)
                        status = getattr(member, 'status', None)
                        if str(status).lower() not in ['member', 'administrator', 'creator']:
                            not_joined.append(ch)
                    except Exception:
                        # If check fails, require join via invite link if exists
                        not_joined.append(ch)
                if not_joined:
                    lines = ["برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید:", ""]
                    kb_rows = []
                    for ch in not_joined:
                        title = ch.get('title') or ch.get('chat_id')
                        link = ch.get('invite_link') or (f"https://t.me/{title.lstrip('@')}" if str(ch.get('chat_id')).startswith('@') else None)
                        if link:
                            lines.append(f"• {title}")
                            kb_rows.append([InlineKeyboardButton(text=title, url=link)])
                        else:
                            lines.append(f"• {title}")
                    kb_rows.append([InlineKeyboardButton(text="✅ بررسی مجدد", callback_data="forced_join_refresh")])
                    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
                    return

        # If not sudo and not admin, show public menu
        if user_id not in config.SUDO_ADMINS and not await db.is_admin_authorized(user_id):
            from handlers.public_handlers import get_public_main_keyboard
            await message.answer(
                "به ربات خوش آمدید!",
                reply_markup=get_public_main_keyboard()
            )
            logger.info(f"Public user {user_id} opened the bot")

    async def general_message_handler(self, message: Message, state: FSMContext = None):
        """General handler for unhandled messages."""
        user_id = message.from_user.id
        
        # Log handler activation with detailed state information
        current_state = await state.get_state() if state else None
        logger.info(f"General message handler activated for user {user_id}, current state: {current_state}, message: {message.text}")
        
        # This should not happen with StateFilter(None), but keep as safety check
        if current_state:
            logger.error(f"CRITICAL: General handler called for user {user_id} in state {current_state} with message: {message.text} - StateFilter(None) not working properly!")
            return  # Don't interfere with FSM flow
        
        # Check if user is sudo admin
        if user_id in config.SUDO_ADMINS:
            logger.info(f"Providing sudo admin help to user {user_id}")
            await message.answer(
                "🔐 شما سودو ادمین هستید.\n\n"
                "📋 دستورات موجود:\n"
                "• /start - منوی اصلی\n"
                "• /add_admin - افزودن ادمین جدید\n"
                "• /show_admins - نمایش لیست ادمین‌ها\n"
                "• /remove_admin - غیرفعالسازی پنل\n"
                "• /edit_panel - ویرایش محدودیت‌های پنل\n"
                "• /admin_status - وضعیت ادمین‌ها\n"
                "• /activate_admin - فعالسازی ادمین غیرفعال\n\n"
                "برای دسترسی به منوی اصلی /start را بزنید."
            )
            logger.info(f"Sudo admin help message sent to user {user_id}")
            return
        
        # Check if user is authorized admin
        if await db.is_admin_authorized(user_id):
            logger.info(f"Providing regular admin help to user {user_id}")
            await message.answer(
                "👋 شما ادمین معمولی هستید.\n\n"
                "📋 دستورات موجود:\n"
                "• /start - منوی اصلی\n"
                "• /گزارش_من - گزارش استفاده\n"
                "• /کاربران_من - لیست کاربران\n"
                "• /اطلاعات_من - اطلاعات حساب\n\n"
                "برای دسترسی به منوی اصلی /start را بزنید."
            )
            logger.info(f"Regular admin help message sent to user {user_id}")
            return
        
        # Unauthorized user
        from handlers.public_handlers import get_public_main_keyboard
        await message.answer("به ربات خوش آمدید!", reply_markup=get_public_main_keyboard())

    async def start_polling(self):
        """Start bot polling."""
        logger.info("Starting bot polling...")
        
        try:
            # Start monitoring scheduler
            await self.scheduler.start()
            
            # Start polling
            await self.dp.start_polling(self.bot)
            
        except Exception as e:
            logger.error(f"Error during polling: {e}")
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up bot resources...")
        
        try:
            if self.scheduler:
                await self.scheduler.stop()
            
            await db.close()
            await self.bot.session.close()
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def send_startup_message(self):
        """Send startup notification to sudo admins."""
        startup_message = (
            "🚀 ربات مدیریت ادمین‌های مرزبان راه‌اندازی شد!\n\n"
            f"⏰ دوره مانیتورینگ: {config.MONITORING_INTERVAL} ثانیه\n"
            f"📊 آستانه هشدار: {int(config.WARNING_THRESHOLD * 100)}%\n"
            f"🔗 آدرس مرزبان: {config.MARZBAN_URL}"
        )
        
        for sudo_id in config.SUDO_ADMINS:
            try:
                await self.bot.send_message(sudo_id, startup_message)
            except Exception as e:
                logger.warning(f"Failed to send startup message to sudo {sudo_id}: {e}")


async def main():
    """Main function."""
    try:
        # Validate config
        if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_BOT_TOKEN":
            logger.error("BOT_TOKEN is not set in config!")
            return
        
        if not config.SUDO_ADMINS:
            logger.error("No SUDO_ADMINS configured!")
            return
        
        # Create and setup bot
        bot = MarzbanAdminBot()
        await bot.setup()
        
        # Start polling
        await bot.start_polling()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Application failed: {e}")
        sys.exit(1)