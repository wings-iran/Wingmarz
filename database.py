import aiosqlite
import os
from pathlib import Path
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from models.schemas import AdminModel, UsageReportModel, LogModel
import config
from models.schemas import PlanModel


class Database:
    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Initialize database and create tables if they don't exist."""
        # Ensure parent directory exists (if a directory is specified)
        try:
            db_path_str = str(self.db_path)
            parent = Path(db_path_str).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        except Exception as _e:
            print(f"Warning: could not ensure database directory exists for {self.db_path}: {_e}")

        async with aiosqlite.connect(self.db_path) as db:
            # Check if we need to migrate the old schema
            try:
                # Check if the old UNIQUE constraint exists
                async with db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='admins'") as cursor:
                    row = await cursor.fetchone()
                    if row and "user_id INTEGER UNIQUE NOT NULL" in row[0]:
                        print("Migrating database schema to support multiple admin panels per user...")
                        await self._migrate_admin_table(db)
                        await db.commit()
                        print("Database migration completed successfully!")
            except Exception as e:
                print(f"Error checking schema: {e}")
            
            # Create admins table - removed UNIQUE constraint on user_id to allow multiple panels per user
            await db.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    admin_name TEXT,
                    marzban_username TEXT UNIQUE,
                    marzban_password TEXT,
                    login_url TEXT,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    max_users INTEGER DEFAULT 10,
                    max_total_time INTEGER DEFAULT 2592000,
                    max_total_traffic INTEGER DEFAULT 107374182400,
                    validity_days INTEGER DEFAULT 30,
                    is_active BOOLEAN DEFAULT 1,
                    original_password TEXT,
                    deactivated_at TIMESTAMP,
                    deactivated_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Add new columns if they don't exist (for migration)
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN admin_name TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists
                
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN marzban_username TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists
                
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN marzban_password TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists

            try:
                await db.execute("ALTER TABLE admins ADD COLUMN login_url TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists
                
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN validity_days INTEGER DEFAULT 30")
            except aiosqlite.OperationalError:
                pass  # Column already exists
            
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN original_password TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists
            
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN deactivated_at TIMESTAMP")
            except aiosqlite.OperationalError:
                pass  # Column already exists
                
            try:
                await db.execute("ALTER TABLE admins ADD COLUMN deactivated_reason TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists

            # Create usage_reports table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS usage_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_user_id INTEGER NOT NULL,
                    check_time TIMESTAMP NOT NULL,
                    current_users INTEGER DEFAULT 0,
                    current_total_time INTEGER DEFAULT 0,
                    current_total_traffic INTEGER DEFAULT 0,
                    users_data TEXT,
                    FOREIGN KEY (admin_user_id) REFERENCES admins(user_id)
                )
            """)

            # Create logs table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (admin_user_id) REFERENCES admins(user_id)
                )
            """)

            # Create plans table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    plan_type TEXT DEFAULT 'both',
                    traffic_limit_bytes INTEGER,
                    time_limit_seconds INTEGER,
                    max_users INTEGER,
                    price INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1
                )
            """)

            # Create settings table (key-value store)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create forced join channels table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS forced_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    title TEXT,
                    invite_link TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migrate existing plans table to add missing columns
            try:
                await db.execute("ALTER TABLE plans ADD COLUMN max_users INTEGER")
            except aiosqlite.OperationalError:
                pass  # Column already exists or table was just created
            try:
                await db.execute("ALTER TABLE plans ADD COLUMN plan_type TEXT DEFAULT 'both'")
            except aiosqlite.OperationalError:
                pass

            # Create orders table (for reseller purchases)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    order_type TEXT,
                    target_admin_id INTEGER,
                    delta_traffic_bytes INTEGER,
                    delta_time_seconds INTEGER,
                    delta_users INTEGER,
                    price_snapshot INTEGER,
                    plan_name_snapshot TEXT,
                    payment_note TEXT,
                    receipt_file_id TEXT,
                    approved_by INTEGER,
                    issued_admin_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add missing order columns if table exists
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN payment_note TEXT")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN approved_by INTEGER")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN issued_admin_id INTEGER")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN receipt_file_id TEXT")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN order_type TEXT")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN target_admin_id INTEGER")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN delta_traffic_bytes INTEGER")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN delta_time_seconds INTEGER")
            except aiosqlite.OperationalError:
                pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN delta_users INTEGER")
            except aiosqlite.OperationalError:
                pass

            # Create cards table (manual payment destinations)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bank_name TEXT,
                    card_number TEXT,
                    holder_name TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()

    async def _migrate_admin_table(self, db):
        """Migrate the admins table to remove UNIQUE constraint on user_id."""
        # Create new table without UNIQUE constraint
        await db.execute("""
            CREATE TABLE admins_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                admin_name TEXT,
                marzban_username TEXT UNIQUE,
                marzban_password TEXT,
                login_url TEXT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                max_users INTEGER DEFAULT 10,
                max_total_time INTEGER DEFAULT 2592000,
                max_total_traffic INTEGER DEFAULT 107374182400,
                validity_days INTEGER DEFAULT 30,
                is_active BOOLEAN DEFAULT 1,
                original_password TEXT,
                deactivated_at TIMESTAMP,
                deactivated_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Copy data from old table to new table
        await db.execute("""
            INSERT INTO admins_new (id, user_id, admin_name, marzban_username, marzban_password, login_url,
                                  username, first_name, last_name, max_users, max_total_time, 
                                  max_total_traffic, validity_days, is_active, original_password, 
                                  deactivated_at, deactivated_reason, created_at, updated_at)
            SELECT id, user_id, admin_name, marzban_username, marzban_password, NULL,
                   username, first_name, last_name, max_users, max_total_time, 
                   max_total_traffic, validity_days, is_active, original_password, 
                   deactivated_at, deactivated_reason, created_at, updated_at
            FROM admins
        """)
        
        # Drop old table and rename new table
        await db.execute("DROP TABLE admins")
        await db.execute("ALTER TABLE admins_new RENAME TO admins")

    async def add_admin(self, admin: AdminModel) -> bool:
        """Add a new admin to the database."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO admins (user_id, admin_name, marzban_username, marzban_password,
                                      login_url, username, first_name, last_name, 
                                      max_users, max_total_time, max_total_traffic, validity_days,
                                      is_active, original_password, deactivated_at, deactivated_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (admin.user_id, admin.admin_name, admin.marzban_username, admin.marzban_password,
                      admin.login_url, admin.username, admin.first_name, admin.last_name,
                      admin.max_users, admin.max_total_time, admin.max_total_traffic, admin.validity_days,
                      admin.is_active, admin.original_password, admin.deactivated_at, admin.deactivated_reason))
                await db.commit()
                return True
        except aiosqlite.IntegrityError as e:
            print(f"Admin already exists (marzban_username must be unique): {e}")
            return False
        except Exception as e:
            print(f"Error adding admin: {e}")
            return False

    async def get_admin(self, user_id: int) -> Optional[AdminModel]:
        """Get first admin by user_id for backward compatibility."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admins WHERE user_id = ? ORDER BY created_at ASC LIMIT 1", (user_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return AdminModel(**dict(row))
                    return None
        except Exception as e:
            print(f"Error getting admin: {e}")
            return None

    async def get_admins_for_user(self, user_id: int) -> List[AdminModel]:
        """Get all admins for a specific user_id."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admins WHERE user_id = ? ORDER BY created_at DESC", (user_id,)) as cursor:
                    rows = await cursor.fetchall()
                    return [AdminModel(**dict(row)) for row in rows]
        except Exception as e:
            print(f"Error getting admins for user: {e}")
            return []

    async def get_admin_by_marzban_username(self, marzban_username: str) -> Optional[AdminModel]:
        """Get admin by marzban username."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admins WHERE marzban_username = ?", (marzban_username,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return AdminModel(**dict(row))
                    return None
        except Exception as e:
            print(f"Error getting admin by marzban username: {e}")
            return None

    async def get_admin_by_id(self, admin_id: int) -> Optional[AdminModel]:
        """Get admin by admin ID."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return AdminModel(**dict(row))
                    return None
        except Exception as e:
            print(f"Error getting admin by ID: {e}")
            return None

    async def get_all_admins(self) -> List[AdminModel]:
        """Get all admins."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admins ORDER BY created_at DESC") as cursor:
                    rows = await cursor.fetchall()
                    return [AdminModel(**dict(row)) for row in rows]
        except Exception as e:
            print(f"Error getting all admins: {e}")
            return []

    async def update_admin(self, admin_id: int, **kwargs) -> bool:
        """Update admin data by admin ID."""
        try:
            if not kwargs:
                return False
            
            set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
            values = list(kwargs.values()) + [admin_id]
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(f"""
                    UPDATE admins SET {set_clause}, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, values)
                await db.commit()
                return True
        except Exception as e:
            print(f"Error updating admin: {e}")
            return False

    async def update_admin_by_user_id(self, user_id: int, **kwargs) -> bool:
        """Update admin data by user_id (for backward compatibility)."""
        try:
            if not kwargs:
                return False
            
            set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
            values = list(kwargs.values()) + [user_id]
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(f"""
                    UPDATE admins SET {set_clause}, updated_at = CURRENT_TIMESTAMP 
                    WHERE user_id = ? 
                    ORDER BY created_at ASC LIMIT 1
                """, values)
                await db.commit()
                return True
        except Exception as e:
            print(f"Error updating admin by user_id: {e}")
            return False

    async def remove_admin(self, user_id: int) -> bool:
        """Remove first admin from database by user_id (for backward compatibility)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM admins WHERE user_id = ? ORDER BY created_at ASC LIMIT 1", (user_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error removing admin: {e}")
            return False

    async def remove_admin_by_id(self, admin_id: int) -> bool:
        """Remove admin from database by admin ID."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error removing admin by ID: {e}")
            return False

    async def add_usage_report(self, report: UsageReportModel) -> bool:
        """Add usage report."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO usage_reports (admin_user_id, check_time, current_users, 
                                             current_total_time, current_total_traffic, users_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (report.admin_user_id, report.check_time, report.current_users,
                      report.current_total_time, report.current_total_traffic, report.users_data))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error adding usage report: {e}")
            return False

    async def get_latest_usage_report(self, admin_user_id: int) -> Optional[UsageReportModel]:
        """Get latest usage report for admin."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT * FROM usage_reports WHERE admin_user_id = ? 
                    ORDER BY check_time DESC LIMIT 1
                """, (admin_user_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return UsageReportModel(**dict(row))
                    return None
        except Exception as e:
            print(f"Error getting latest usage report: {e}")
            return None

    async def add_log(self, log: LogModel) -> bool:
        """Add log entry."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO logs (admin_user_id, action, details, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (log.admin_user_id, log.action, log.details, log.timestamp))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error adding log: {e}")
            return False

    async def get_logs(self, admin_user_id: Optional[int] = None, limit: int = 100) -> List[LogModel]:
        """Get logs, optionally filtered by admin."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                if admin_user_id:
                    query = "SELECT * FROM logs WHERE admin_user_id = ? ORDER BY timestamp DESC LIMIT ?"
                    params = (admin_user_id, limit)
                else:
                    query = "SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?"
                    params = (limit,)
                
                async with db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()
                    return [LogModel(**dict(row)) for row in rows]
        except Exception as e:
            print(f"Error getting logs: {e}")
            return []

    async def is_admin_authorized(self, user_id: int) -> bool:
        """Check if user is authorized admin (has at least one active admin panel)."""
        if user_id in config.SUDO_ADMINS:
            return True
        
        admins = await self.get_admins_for_user(user_id)
        return any(admin.is_active for admin in admins)

    async def deactivate_admin(self, admin_id: int, reason: str = "Limit exceeded") -> bool:
        """Deactivate admin by admin ID and store original password."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE admins SET 
                        is_active = 0, 
                        deactivated_at = CURRENT_TIMESTAMP,
                        deactivated_reason = ?,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (reason, admin_id))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error deactivating admin: {e}")
            return False

    async def deactivate_admin_by_user_id(self, user_id: int, reason: str = "Limit exceeded") -> bool:
        """Deactivate admin by user_id (for backward compatibility)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE admins SET 
                        is_active = 0, 
                        deactivated_at = CURRENT_TIMESTAMP,
                        deactivated_reason = ?,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE user_id = ?
                """, (reason, user_id))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error deactivating admin: {e}")
            return False

    async def reactivate_admin(self, admin_id: int) -> bool:
        """Reactivate admin by admin ID and restore original password."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE admins SET 
                        is_active = 1, 
                        deactivated_at = NULL,
                        deactivated_reason = NULL,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (admin_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error reactivating admin: {e}")
            return False

    async def reactivate_admin_by_user_id(self, user_id: int) -> bool:
        """Reactivate admin by user_id (for backward compatibility)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE admins SET 
                        is_active = 1, 
                        deactivated_at = NULL,
                        deactivated_reason = NULL,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE user_id = ?
                """, (user_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error reactivating admin: {e}")
            return False

    async def get_deactivated_admins(self) -> List[AdminModel]:
        """Get all deactivated admins."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admins WHERE is_active = 0 ORDER BY deactivated_at DESC") as cursor:
                    rows = await cursor.fetchall()
                    return [AdminModel(**dict(row)) for row in rows]
        except Exception as e:
            print(f"Error getting deactivated admins: {e}")
            return []

    async def close(self):
        """Close database connection (placeholder for future connection pooling)."""
        pass

    # ===== Plans CRUD =====
    async def add_plan(self, plan: PlanModel) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO plans (name, traffic_limit_bytes, time_limit_seconds, max_users, price, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (plan.name, plan.traffic_limit_bytes, plan.time_limit_seconds, plan.max_users, plan.price, plan.is_active))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error adding plan: {e}")
            return False

    async def get_plans(self, only_active: bool = False) -> List[PlanModel]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                query = "SELECT * FROM plans"
                if only_active:
                    query += " WHERE is_active = 1"
                async with db.execute(query) as cursor:
                    rows = await cursor.fetchall()
                    return [PlanModel(**dict(row)) for row in rows]
        except Exception as e:
            print(f"Error getting plans: {e}")
            return []

    async def get_plan_by_id(self, plan_id: int) -> Optional[PlanModel]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)) as cursor:
                    row = await cursor.fetchone()
                    return PlanModel(**dict(row)) if row else None
        except Exception as e:
            print(f"Error getting plan by id: {e}")
            return None

    async def delete_plan(self, plan_id: int) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error deleting plan: {e}")
            return False

    async def update_plan(self, plan_id: int, **kwargs) -> bool:
        try:
            if not kwargs:
                return False
            set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            values = list(kwargs.values()) + [plan_id]
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(f"UPDATE plans SET {set_clause} WHERE id = ?", values)
                await db.commit()
                return True
        except Exception as e:
            print(f"Error updating plan: {e}")
            return False

    # ===== Orders CRUD =====
    async def add_order(self, user_id: int, plan_id: int, price_snapshot: int, plan_name_snapshot: str) -> Optional[int]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO orders (user_id, plan_id, status, price_snapshot, plan_name_snapshot)
                    VALUES (?, ?, 'pending', ?, ?)
                    """,
                    (user_id, plan_id, price_snapshot, plan_name_snapshot)
                )
                await db.commit()
                async with db.execute("SELECT last_insert_rowid()") as cur:
                    row = await cur.fetchone()
                    return int(row[0]) if row else None
        except Exception as e:
            print(f"Error adding order: {e}")
            return None

    async def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                if status:
                    async with db.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC", (status,)) as cur:
                        rows = await cur.fetchall()
                else:
                    async with db.execute("SELECT * FROM orders ORDER BY created_at DESC") as cur:
                        rows = await cur.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error getting orders: {e}")
            return []

    async def get_order_by_id(self, order_id: int) -> Optional[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            print(f"Error getting order: {e}")
            return None

    async def update_order(self, order_id: int, **kwargs) -> bool:
        try:
            if not kwargs:
                return False
            set_clause = ", ".join([f"{k} = ?" for k in kwargs])
            values = list(kwargs.values()) + [order_id]
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(f"UPDATE orders SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
                await db.commit()
                return True
        except Exception as e:
            print(f"Error updating order: {e}")
            return False

    # ===== Cards CRUD =====
    async def add_card(self, bank_name: str, card_number: str, holder_name: str, is_active: bool = True) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO cards (bank_name, card_number, holder_name, is_active)
                    VALUES (?, ?, ?, ?)
                    """,
                    (bank_name, card_number, holder_name, 1 if is_active else 0)
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Error adding card: {e}")
            return False

    async def get_cards(self, only_active: bool = False) -> List[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                query = "SELECT * FROM cards"
                params: tuple = ()
                if only_active:
                    query += " WHERE is_active = 1"
                query += " ORDER BY created_at DESC"
                async with db.execute(query, params) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error getting cards: {e}")
            return []

    async def get_card_by_id(self, card_id: int) -> Optional[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            print(f"Error getting card by id: {e}")
            return None

    async def delete_card(self, card_id: int) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error deleting card: {e}")
            return False

    async def set_card_active(self, card_id: int, is_active: bool) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE cards SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (1 if is_active else 0, card_id)
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Error updating card status: {e}")
            return False

    # ===== Settings (key-value) =====
    async def set_setting(self, key: str, value: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                    """,
                    (key, value)
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Error setting setting {key}: {e}")
            return False

    async def get_setting(self, key: str) -> Optional[str]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
                    row = await cur.fetchone()
                    return row["value"] if row else None
        except Exception as e:
            print(f"Error getting setting {key}: {e}")
            return None

    # Convenience getters for billing
    async def get_billing_rates(self) -> Dict[str, int]:
        """Return per-unit prices: per_gb_toman, per_30days_toman, per_user_toman."""
        def _to_int(val: Optional[str], default: int) -> int:
            try:
                return int(val) if val is not None else default
            except Exception:
                return default
        per_gb = _to_int(await self.get_setting("price_per_gb_toman"), 0)
        per_30d = _to_int(await self.get_setting("price_per_30days_toman"), 0)
        per_user = _to_int(await self.get_setting("price_per_user_toman"), 0)
        return {"per_gb_toman": per_gb, "per_30days_toman": per_30d, "per_user_toman": per_user}

    # ===== Forced Join Channels CRUD =====
    async def add_forced_channel(self, chat_id: str, title: Optional[str] = None, invite_link: Optional[str] = None, is_active: bool = True) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO forced_channels (chat_id, title, invite_link, is_active) VALUES (?, ?, ?, ?)",
                    (chat_id, title, invite_link, 1 if is_active else 0)
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Error adding forced channel: {e}")
            return False

    async def get_forced_channels(self, only_active: bool = True) -> List[Dict[str, Any]]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                query = "SELECT * FROM forced_channels"
                if only_active:
                    query += " WHERE is_active = 1"
                query += " ORDER BY created_at DESC"
                async with db.execute(query) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            print(f"Error getting forced channels: {e}")
            return []

    async def delete_forced_channel(self, channel_id: int) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM forced_channels WHERE id = ?", (channel_id,))
                await db.commit()
                return True
        except Exception as e:
            print(f"Error deleting forced channel: {e}")
            return False

    async def set_forced_channel_active(self, channel_id: int, is_active: bool) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE forced_channels SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (1 if is_active else 0, channel_id)
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Error updating forced channel status: {e}")
            return False


# Global database instance
db = Database()