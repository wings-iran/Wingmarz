from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AdminModel(BaseModel):
    id: Optional[int] = None
    user_id: int
    admin_name: Optional[str] = None  # Full name of admin
    marzban_username: Optional[str] = None  # Username for Marzban panel
    marzban_password: Optional[str] = None  # Password for Marzban panel
    login_url: Optional[str] = None  # Panel login URL
    username: Optional[str] = None  # Telegram username (for compatibility)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    max_users: int = Field(default=10, ge=1)
    max_total_time: int = Field(default=2592000, ge=0)  # 30 days in seconds
    max_total_traffic: int = Field(default=107374182400, ge=0)  # 100GB in bytes
    validity_days: int = Field(default=30, ge=1)  # Validity period in days
    is_active: bool = Field(default=True)
    original_password: Optional[str] = None  # Store original password for reactivation
    deactivated_at: Optional[datetime] = None  # When admin was deactivated
    deactivated_reason: Optional[str] = None  # Reason for deactivation
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UsageReportModel(BaseModel):
    id: Optional[int] = None
    admin_user_id: int
    check_time: datetime
    current_users: int = 0
    current_total_time: int = 0  # in seconds
    current_total_traffic: int = 0  # in bytes
    users_data: Optional[str] = None  # JSON string of users info
    

class LogModel(BaseModel):
    id: Optional[int] = None
    admin_user_id: Optional[int] = None
    action: str
    details: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class MarzbanUserModel(BaseModel):
    username: str
    status: str
    used_traffic: int = 0
    lifetime_used_traffic: int = 0
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    admin: Optional[str] = None


class AdminStatsModel(BaseModel):
    total_users: int = 0
    active_users: int = 0
    total_traffic_used: int = 0
    total_time_used: int = 0
    usage_percentage: Dict[str, float] = Field(default_factory=dict)


class LimitCheckResult(BaseModel):
    admin_user_id: int
    admin_id: Optional[int] = None  # For tracking individual admin panels
    exceeded: bool = False
    warning: bool = False
    limits_data: Dict[str, Any] = Field(default_factory=dict)
    affected_users: List[str] = Field(default_factory=list)


class PlanModel(BaseModel):
    id: Optional[int] = None
    name: str
    plan_type: str = Field(default="volume")  # one of: volume, time
    # If None -> unlimited
    traffic_limit_bytes: Optional[int] = None
    # If None -> unlimited
    time_limit_seconds: Optional[int] = None
    # If None -> unlimited
    max_users: Optional[int] = None
    price: int = 0  # in Toman
    is_active: bool = Field(default=True)