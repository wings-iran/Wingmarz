import asyncio
import json
from datetime import datetime
from typing import List, Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import config
from database import db
from marzban_api import marzban_api
from models.schemas import UsageReportModel, LogModel, LimitCheckResult
from utils.notify import notify_limit_warning, notify_limit_exceeded


class MonitoringScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.backup_job_id = "bot_backup_job"

    async def check_admin_limits(self, admin_user_id: int) -> LimitCheckResult:
        admin = await db.get_admin(admin_user_id)
        if not admin:
            return LimitCheckResult(admin_user_id=admin_user_id)
        return await self.check_admin_limits_by_id(admin.id)

    async def check_admin_limits_by_id(self, admin_id: int) -> LimitCheckResult:
        try:
            admin = await db.get_admin_by_id(admin_id)
            if not admin or not admin.is_active:
                return LimitCheckResult(admin_user_id=admin.user_id if admin else 0)

            # Fetch current usage from Marzban (prefer panel username)
            admin_username = admin.marzban_username or admin.username or str(admin.user_id)
            admin_stats = await marzban_api.get_admin_stats(admin_username)

            # زمان سپری‌شده از ساخت ادمین
            created_at = admin.created_at
            now = datetime.utcnow()
            elapsed_seconds = (now - created_at).total_seconds()

            # نسبت استفاده‌ها به‌صورت 0..1 (یکسان‌سازی مقیاس)
            time_percentage = elapsed_seconds / admin.max_total_time if admin.max_total_time > 0 else 0
            # Use historical peak users for limit checks
            try:
                peak_users = max(int(getattr(admin, 'users_historical_peak', 0) or 0), int(admin_stats.total_users or 0))
                if peak_users != (getattr(admin, 'users_historical_peak', 0) or 0):
                    await db.update_admin(admin.id, users_historical_peak=peak_users)
            except Exception:
                peak_users = admin_stats.total_users

            user_percentage = (peak_users / admin.max_users) if admin.max_users > 0 else 0
            traffic_percentage = (admin_stats.total_traffic_used / admin.max_total_traffic) if admin.max_total_traffic > 0 else 0

            limits_exceeded = (
                time_percentage >= 1.0 or
                user_percentage >= 1.0 or
                traffic_percentage >= 1.0
            )
            # Warning if any threshold crossed: 0.6, 0.7, 0.8, 0.9
            warning_levels = [0.6, 0.7, 0.8, 0.9]
            warning_needed = any([
                any(level <= time_percentage < 1.0 for level in warning_levels),
                any(level <= user_percentage < 1.0 for level in warning_levels),
                any(level <= traffic_percentage < 1.0 for level in warning_levels)
            ])

            # گزارش واقعی استفاده
            report = UsageReportModel(
                admin_user_id=admin.user_id,
                check_time=now,
                current_users=admin_stats.total_users,
                current_total_time=int(elapsed_seconds),
                current_total_traffic=int(admin_stats.total_traffic_used),
                users_data=json.dumps([], ensure_ascii=False)
            )
            await db.add_usage_report(report)

            return LimitCheckResult(
                admin_user_id=admin.user_id,
                admin_id=admin.id,
                exceeded=limits_exceeded,
                warning=warning_needed,
                limits_data={
                    "user_percentage": user_percentage,           # ratios 0..1
                    "traffic_percentage": traffic_percentage,     # ratios 0..1
                    "time_percentage": time_percentage,           # ratios 0..1
                    "current_users": admin_stats.total_users,
                    "max_users": admin.max_users,
                    "current_traffic": 0,
                    "max_traffic": admin.max_total_traffic,
                    "current_time": elapsed_seconds,
                    "max_time": admin.max_total_time
                },
                affected_users=[]
            )

        except Exception as e:
            print(f"Error checking limits for admin panel {admin_id}: {e}")
            return LimitCheckResult(admin_user_id=admin.user_id if admin else 0, admin_id=admin_id)

    async def handle_limit_exceeded(self, result: LimitCheckResult):
        try:
            if not result.exceeded:
                return

            from handlers.sudo_handlers import deactivate_admin_panel_by_id, notify_admin_deactivation
            admin = await db.get_admin_by_id(result.admin_id)
            if not admin:
                return

            reasons = []
            if result.limits_data.get("time_percentage", 0) >= 1.0:
                reasons.append("تجاوز از محدودیت زمان اعتبار")
            if result.limits_data.get("user_percentage", 0) >= 1.0:
                 reasons.append("تجاوز از محدودیت تعداد کاربر")
            if result.limits_data.get("traffic_percentage", 0) >= 1.0:
                 reasons.append("تجاوز از محدودیت ترافیک")

            reason = " و ".join(reasons)
            if not reason: # Should not happen if result.exceeded is True, but as a safeguard
                reason = "تجاوز از محدودیت‌ها"

            success = await deactivate_admin_panel_by_id(result.admin_id, reason)
            if success:
                # include admin_id so notifier can include marzban username and new password
                await notify_admin_deactivation(self.bot, result.admin_user_id, reason, admin_id=result.admin_id)
                # notify the affected admin directly
                try:
                    from utils.notify import notify_admin_deactivated
                    await notify_admin_deactivated(self.bot, result.admin_user_id, reason)
                except Exception as _e:
                    print(f"Error notifying deactivated admin {result.admin_user_id}: {_e}")
                log = LogModel(
                    admin_user_id=result.admin_user_id,
                    action="admin_panel_auto_deactivated",
                    details=f"Admin panel {result.admin_id} deactivated due to time limit exceeded.",
                    timestamp=datetime.now()
                )
                await db.add_log(log)
                print(f"Admin panel {result.admin_id} deactivated due to time exceeded.")
                return

        except Exception as e:
            print(f"Error handling limit exceeded for admin {result.admin_user_id}: {e}")

    async def handle_limit_warning(self, result: LimitCheckResult):
        try:
            if not result.warning:
                return

            # Send granular warnings for each resource at 60/70/80/90
            levels = [0.6, 0.7, 0.8, 0.9]
            mapping = [
                ("زمان", result.limits_data.get("time_percentage", 0)),
                ("کاربر", result.limits_data.get("user_percentage", 0)),
                ("حجم مصرفی", result.limits_data.get("traffic_percentage", 0)),
            ]
            for label, value in mapping:
                for level in levels:
                    # If value passed this level (and below 100%)
                    if level <= value < 1.0:
                        await notify_limit_warning(
                            self.bot,
                            result.admin_user_id,
                            f"{label}",
                            value
                        )
                        break  # only highest crossed level per resource per run

        except Exception as e:
            print(f"Error handling limit warning for admin {result.admin_user_id}: {e}")

    async def cleanup_expired_users(self):
        try:
            if not config.AUTO_DELETE_EXPIRED_USERS:
                print("AUTO_DELETE_EXPIRED_USERS is disabled; skipping expired users cleanup")
                return
            print(f"Starting expired users cleanup at {datetime.now()}")
            admins = await db.get_all_admins()
            active_admins = [admin for admin in admins if admin.is_active]
            total_cleaned = 0

            for admin in active_admins:
                try:
                    admin_username = admin.marzban_username or admin.username or str(admin.user_id)
                    expired_users = await marzban_api.get_expired_users(admin_username)
                    if expired_users:
                        for user in expired_users:
                            try:
                                success = await marzban_api.remove_user(user.username)
                                if success:
                                    total_cleaned += 1
                                    print(f"Removed expired user: {user.username} (admin: {admin_username})")
                                await asyncio.sleep(0.1)
                            except Exception as e:
                                print(f"Error removing expired user {user.username}: {e}")
                                continue
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"Error cleaning expired users for admin {admin.user_id}: {e}")
                    continue

            if total_cleaned > 0:
                log = LogModel(
                    admin_user_id=None,
                    action="expired_users_cleanup",
                    details=f"Automatically cleaned up {total_cleaned} expired users",
                    timestamp=datetime.now()
                )
                await db.add_log(log)

            print(f"Expired users cleanup completed. Removed {total_cleaned} users at {datetime.now()}")

        except Exception as e:
            print(f"Error in cleanup_expired_users: {e}")

    async def monitor_all_admins(self):
        try:
            print(f"Starting monitoring check at {datetime.now()}")
            # Only cleanup expired users if enabled
            if config.AUTO_DELETE_EXPIRED_USERS:
                await self.cleanup_expired_users()
            admins = await db.get_all_admins()
            active_admins = [admin for admin in admins if admin.is_active]

            if not active_admins:
                print("No active admins to monitor")
                return

            print(f"Monitoring {len(active_admins)} active admins")

            for admin in active_admins:
                try:
                    result = await self.check_admin_limits_by_id(admin.id)
                    if result.exceeded:
                        await self.handle_limit_exceeded(result)
                    elif result.warning:
                        await self.handle_limit_warning(result)
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"Error monitoring admin panel {admin.id} (user {admin.user_id}): {e}")
                    continue

            print(f"Monitoring check completed at {datetime.now()}")

        except Exception as e:
            print(f"Error in monitor_all_admins: {e}")

    async def start(self):
        if self.is_running:
            print("Scheduler is already running")
            return

        print("Starting monitoring scheduler...")

        self.scheduler.add_job(
            self.monitor_all_admins,
            trigger=IntervalTrigger(seconds=config.MONITORING_INTERVAL),
            id="admin_monitor",
            name="Admin Limit Monitor",
            replace_existing=True,
            max_instances=1
        )

        self.scheduler.start()
        self.is_running = True

        print(f"Monitoring scheduler started. Will check every {config.MONITORING_INTERVAL} seconds.")

        await self.monitor_all_admins()

    async def send_backup(self):
        try:
            from utils.backup import create_backup_zip
            path = await create_backup_zip()
            for sudo_id in config.SUDO_ADMINS:
                try:
                    from pathlib import Path
                    from aiogram.types import FSInputFile
                    p = Path(str(path))
                    if p.exists():
                        await self.bot.send_document(chat_id=sudo_id, document=FSInputFile(str(p)), caption=f"بکاپ خودکار: {p.name}")
                    else:
                        await self.bot.send_document(chat_id=sudo_id, document=str(path), caption=f"بکاپ خودکار: {p.name}")
                except Exception:
                    pass
        except Exception as e:
            print(f"Error creating/sending backup: {e}")

    def schedule_backup_every_hour(self):
        try:
            # Remove existing job if any
            job = self.scheduler.get_job(self.backup_job_id)
            if job:
                self.scheduler.remove_job(self.backup_job_id)
            # Schedule every 60 minutes from now to avoid minute-0 alignment issues
            self.scheduler.add_job(
                self.send_backup,
                trigger=IntervalTrigger(hours=1),
                id=self.backup_job_id,
                name="Hourly Bot Backup",
                replace_existing=True,
                max_instances=1
            )
            return True
        except Exception as e:
            print(f"Error scheduling hourly backup: {e}")
            return False

    def disable_backup_schedule(self):
        try:
            job = self.scheduler.get_job(self.backup_job_id)
            if job:
                self.scheduler.remove_job(self.backup_job_id)
            return True
        except Exception as e:
            print(f"Error disabling backup schedule: {e}")
            return False

    async def stop(self):
        if not self.is_running:
            return
        print("Stopping monitoring scheduler...")
        self.scheduler.shutdown(wait=False)
        self.is_running = False
        print("Monitoring scheduler stopped.")

    def get_status(self) -> Dict:
        return {
            "running": self.is_running,
            "jobs": len(self.scheduler.get_jobs()) if self.is_running else 0,
            "next_run": str(self.scheduler.get_job("admin_monitor").next_run_time) if self.is_running else None
        }


scheduler = None


def init_scheduler(bot):
    global scheduler
    scheduler = MonitoringScheduler(bot)
    return scheduler
