#!/usr/bin/env python3
"""
Health Check Script for Marzban Admin Bot
تست سلامت ربات مدیریت مرزبان

This script performs comprehensive health checks on:
1. Database connectivity and operations
2. Marzban API connectivity
3. Provides clear error reporting and solutions

Usage: python health_check.py
"""

import asyncio
import sys
import os
from datetime import datetime
from typing import Optional

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Health check messages in Persian
HEALTH_MESSAGES = {
    "title": "🔍 تست سلامت ربات مدیریت مرزبان",
    "starting": "🚀 شروع تست‌های سلامت...",
    "db_test": "💾 تست اتصال به دیتابیس",
    "db_init": "📦 تست مقداردهی اولیه دیتابیس",
    "db_operations": "🔄 تست عملیات دیتابیس (افزودن/خواندن/حذف)",
    "api_test": "🌐 تست اتصال به پنل مرزبان",
    "test_passed": "✅ موفق",
    "test_failed": "❌ ناموفق",
    "cleanup": "🧹 پاکسازی داده‌های تستی",
    "summary": "📊 خلاصه نتایج تست",
    "all_passed": "🎉 همه تست‌ها موفق! ربات آماده به کار است.",
    "some_failed": "⚠️ برخی تست‌ها ناموفق. لطفاً تنظیمات را بررسی کنید.",
    "critical_error": "💥 خطای حیاتی در حین تست:",
    
    # Error messages and solutions
    "db_init_error": "❌ خطا در مقداردهی اولیه دیتابیس:",
    "db_init_solution": "💡 راه‌حل‌های پیشنهادی:\n   • بررسی مجوزهای پوشه برای ایجاد فایل دیتابیس\n   • اطمینان از وجود فضای کافی در دیسک\n   • بررسی مسیر DATABASE_PATH در فایل تنظیمات",
    
    "db_operations_error": "❌ خطا در عملیات دیتابیس:",
    "db_operations_solution": "💡 راه‌حل‌های پیشنهادی:\n   • بررسی سلامت فایل دیتابیس\n   • اجرای مجدد اسکریپت init_db\n   • بررسی مجوزهای خواندن/نوشتن فایل دیتابیس",
    
    "api_connection_error": "❌ خطا در اتصال به پنل مرزبان:",
    "api_connection_solution": "💡 راه‌حل‌های پیشنهادی:\n   • بررسی صحت آدرس پنل (MARZBAN_URL)\n   • بررسی نام کاربری و رمز عبور (MARZBAN_USERNAME/PASSWORD)\n   • اطمینان از در دسترس بودن پنل مرزبان\n   • بررسی اتصال اینترنت\n   • بررسی تنظیمات فایروال",
    
    "config_error": "❌ خطا در تنظیمات:",
    "config_solution": "💡 راه‌حل‌های پیشنهادی:\n   • بررسی وجود فایل .env\n   • کپی .env.example به .env و تنظیم مقادیر صحیح\n   • بررسی فرمت متغیرهای محیطی"
}

# Test admin data - using a specific test ID to avoid conflicts
TEST_ADMIN_ID = 999999999
TEST_ADMIN_DATA = {
    "user_id": TEST_ADMIN_ID,
    "username": "health_check_test_admin",
    "first_name": "Health",
    "last_name": "Check Test",
    "max_users": 1,
    "max_total_time": 3600,  # 1 hour
    "max_total_traffic": 1073741824,  # 1GB
    "is_active": True
}


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def print_test_result(test_name: str, success: bool, details: str = ""):
    """Print test result with formatting."""
    status = HEALTH_MESSAGES["test_passed"] if success else HEALTH_MESSAGES["test_failed"]
    print(f"{test_name}: {status}")
    if details:
        print(f"   {details}")


def print_error_with_solution(error_key: str, solution_key: str, error_details: str = ""):
    """Print error message with suggested solution."""
    print(f"\n{HEALTH_MESSAGES[error_key]}")
    if error_details:
        print(f"   {error_details}")
    print(f"\n{HEALTH_MESSAGES[solution_key]}")


async def test_database_init() -> tuple[bool, str]:
    """Test database initialization."""
    try:
        from database import db
        await db.init_db()
        return True, "دیتابیس با موفقیت مقداردهی شد"
    except Exception as e:
        return False, f"خطا: {str(e)}"


async def test_database_operations() -> tuple[bool, str]:
    """Test basic database operations with a test admin."""
    try:
        from database import db
        from models.schemas import AdminModel
        
        # Create test admin
        test_admin = AdminModel(**TEST_ADMIN_DATA)
        
        # Test 1: Add admin
        add_result = await db.add_admin(test_admin)
        if not add_result:
            return False, "خطا در افزودن ادمین تستی"
        
        # Test 2: Get admin
        retrieved_admin = await db.get_admin(TEST_ADMIN_ID)
        if not retrieved_admin:
            return False, "خطا در خواندن ادمین تستی"
        
        # Test 3: Verify data integrity
        if retrieved_admin.username != TEST_ADMIN_DATA["username"]:
            return False, "خطا در یکپارچگی داده‌ها"
        
        # Test 4: Remove admin
        remove_result = await db.remove_admin(TEST_ADMIN_ID)
        if not remove_result:
            return False, "خطا در حذف ادمین تستی"
        
        # Test 5: Verify removal
        removed_admin = await db.get_admin(TEST_ADMIN_ID)
        if removed_admin:
            return False, "ادمین تستی پس از حذف هنوز موجود است"
        
        return True, "تمام عملیات دیتابیس موفق"
        
    except Exception as e:
        return False, f"خطا در عملیات دیتابیس: {str(e)}"


async def test_marzban_api() -> tuple[bool, str]:
    """Test Marzban API connectivity."""
    try:
        from marzban_api import marzban_api
        
        # Test connection
        connection_result = await marzban_api.test_connection()
        
        if connection_result:
            return True, "اتصال به پنل مرزبان موفق"
        else:
            return False, "اتصال به پنل مرزبان ناموفق"
            
    except Exception as e:
        return False, f"خطا در اتصال به API: {str(e)}"


async def cleanup_test_data():
    """Clean up any remaining test data."""
    try:
        from database import db
        
        # Ensure test admin is removed
        existing_admin = await db.get_admin(TEST_ADMIN_ID)
        if existing_admin:
            await db.remove_admin(TEST_ADMIN_ID)
            print(f"🧹 ادمین تستی باقیمانده پاک شد (ID: {TEST_ADMIN_ID})")
            
    except Exception as e:
        print(f"⚠️ خطا در پاکسازی: {str(e)}")


async def main():
    """Run all health checks."""
    print(HEALTH_MESSAGES["title"])
    print(HEALTH_MESSAGES["starting"])
    
    results = []
    
    # Test 1: Database Initialization
    print_header(HEALTH_MESSAGES["db_init"])
    db_init_success, db_init_details = await test_database_init()
    print_test_result(HEALTH_MESSAGES["db_init"], db_init_success, db_init_details)
    results.append(("Database Init", db_init_success))
    
    if not db_init_success:
        print_error_with_solution("db_init_error", "db_init_solution", db_init_details)
    
    # Test 2: Database Operations (only if init succeeded)
    if db_init_success:
        print_header(HEALTH_MESSAGES["db_operations"])
        try:
            db_ops_success, db_ops_details = await test_database_operations()
            print_test_result(HEALTH_MESSAGES["db_operations"], db_ops_success, db_ops_details)
            results.append(("Database Operations", db_ops_success))
            
            if not db_ops_success:
                print_error_with_solution("db_operations_error", "db_operations_solution", db_ops_details)
                
        except Exception as e:
            print_test_result(HEALTH_MESSAGES["db_operations"], False, f"خطای غیرمنتظره: {str(e)}")
            print_error_with_solution("db_operations_error", "db_operations_solution", str(e))
            results.append(("Database Operations", False))
        finally:
            # Always clean up test data
            await cleanup_test_data()
    else:
        results.append(("Database Operations", False))
        print("⏭️ تست عملیات دیتابیس به دلیل ناموفق بودن مقداردهی اولیه رد شد")
    
    # Test 3: Marzban API Connection
    print_header(HEALTH_MESSAGES["api_test"])
    try:
        api_success, api_details = await test_marzban_api()
        print_test_result(HEALTH_MESSAGES["api_test"], api_success, api_details)
        results.append(("Marzban API", api_success))
        
        if not api_success:
            print_error_with_solution("api_connection_error", "api_connection_solution", api_details)
            
    except Exception as e:
        print_test_result(HEALTH_MESSAGES["api_test"], False, f"خطای غیرمنتظره: {str(e)}")
        print_error_with_solution("api_connection_error", "api_connection_solution", str(e))
        results.append(("Marzban API", False))
    
    # Summary
    print_header(HEALTH_MESSAGES["summary"])
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = HEALTH_MESSAGES["test_passed"] if success else HEALTH_MESSAGES["test_failed"]
        print(f"{test_name}: {status}")
        if success:
            passed += 1
    
    print(f"\nنتیجه نهایی: {passed}/{total} تست موفق")
    
    if passed == total:
        print(f"\n{HEALTH_MESSAGES['all_passed']}")
        return 0
    else:
        print(f"\n{HEALTH_MESSAGES['some_failed']}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n🛑 تست توسط کاربر متوقف شد")
        sys.exit(1)
    except Exception as e:
        print(f"\n{HEALTH_MESSAGES['critical_error']} {e}")
        sys.exit(1)