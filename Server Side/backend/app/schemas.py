"""Pydantic schemas for WattWise API request/response validation."""

from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Auth ─────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    name: str
    email: str
    is_admin: bool

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    is_admin: bool
    notifications_enabled: bool
    daily_energy_goal_kwh: Optional[float]
    weekly_energy_goal_kwh: Optional[float]
    monthly_budget_gbp: Optional[float]
    created_at: datetime


# ── Homes ─────────────────────────────────────────────────────

class HomeCreate(BaseModel):
    home_name: str = Field(..., min_length=2, max_length=128)
    address: Optional[str] = None
    location_desc: Optional[str] = None
    num_occupants: Optional[int] = Field(default=1, ge=1, le=20)
    home_type: Optional[str] = "other"

class HomeResponse(BaseModel):
    id: int
    home_name: str
    address: Optional[str]
    location_desc: Optional[str]
    num_occupants: Optional[int]
    home_type: Optional[str]
    registered_at: datetime
    is_active: bool


# ── Devices ──────────────────────────────────────────────────

class DeviceCreate(BaseModel):
    name: str
    appliance_key: str
    location: Optional[str] = None
    entity_id: Optional[str] = None
    power_entity_id: Optional[str] = None
    switch_entity_id: Optional[str] = None
    device_type: Optional[str] = "appliance"
    rated_wattage: Optional[float] = None

class DeviceResponse(BaseModel):
    id: int
    home_id: int
    name: str
    appliance_key: str
    location: Optional[str]
    entity_id: Optional[str]
    power_entity_id: Optional[str]
    device_type: Optional[str]
    rated_wattage: Optional[float]
    is_active: bool


# ── Energy Readings ───────────────────────────────────────────

class EnergyReadingCreate(BaseModel):
    """Used by HTTP ingest endpoint and MQTT handler."""
    device_id: Optional[int] = None   # DB id (if known)
    entity_id: Optional[str] = None   # HA entity_id (if lookup needed)
    home_id: Optional[int] = None
    recorded_at: Optional[datetime] = None
    power_watts: float = Field(..., ge=0, le=50000)  # max 50kW household
    current_amps: Optional[float] = None
    voltage_volts: Optional[float] = None
    energy_kwh: Optional[float] = None
    switch_state: Optional[str] = "unknown"

class EnergyReadingResponse(BaseModel):
    id: int
    device_id: int
    recorded_at: datetime
    power_watts: float
    current_amps: Optional[float]
    energy_kwh: Optional[float]
    switch_state: Optional[str]

class HourlySummaryResponse(BaseModel):
    device_id: int
    hour_start: datetime
    avg_watts: float
    max_watts: float
    total_kwh: float
    usage_cycles: int
    active_minutes: int

class DailySummaryResponse(BaseModel):
    device_id: int
    day_date: date
    total_kwh: float
    avg_watts: float
    peak_watts: float
    usage_cycles: int
    estimated_cost_gbp: float
    efficiency_score: Optional[float]
    goal_kwh: Optional[float]
    goal_met: Optional[bool]


# ── Energy Goals ──────────────────────────────────────────────

class GoalCreate(BaseModel):
    device_id: Optional[int] = None
    goal_type: str = Field(..., pattern="^(daily|weekly|monthly|per_device)$")
    target_kwh: Optional[float] = Field(default=None, ge=0)
    target_cost_gbp: Optional[float] = Field(default=None, ge=0)
    start_date: date
    end_date: Optional[date] = None

class GoalResponse(BaseModel):
    id: int
    user_id: int
    device_id: Optional[int]
    goal_type: str
    target_kwh: Optional[float]
    target_cost_gbp: Optional[float]
    start_date: date
    end_date: Optional[date]
    is_active: bool
    created_at: datetime

class GoalProgressResponse(BaseModel):
    goal: GoalResponse
    current_kwh: float
    current_cost_gbp: float
    percentage_used: float
    days_remaining: Optional[int]
    on_track: bool
    projected_kwh: Optional[float]


# ── Notifications ─────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: int
    user_id: int
    device_id: Optional[int]
    notification_type: str
    severity: str
    title: str
    message: str
    action_hint: Optional[str]
    action_button_text: Optional[str]
    requires_user_action: bool
    metadata_json: Optional[dict]
    is_read: bool
    dismissed: bool
    sent_via_push: bool
    created_at: datetime

class NotificationStatsResponse(BaseModel):
    total: int
    unread: int
    critical: int
    today: int
    requires_action: int


# ── User Decisions ────────────────────────────────────────────

class DecisionCreate(BaseModel):
    notification_id: int
    device_id: Optional[int] = None
    decision_type: str = Field(..., pattern="^(ACCEPTED|REJECTED|DEFERRED|CUSTOM_ACTION)$")
    action_taken: Optional[str] = None
    user_feedback_text: Optional[str] = None
    user_satisfaction: Optional[int] = Field(default=None, ge=1, le=5)

class DecisionResponse(BaseModel):
    id: int
    user_id: int
    notification_id: int
    device_id: Optional[int]
    decision_type: str
    action_taken: Optional[str]
    action_timestamp: datetime
    energy_before_kwh: Optional[float]
    energy_after_kwh: Optional[float]
    energy_saved_kwh: Optional[float]
    cost_saved_gbp: Optional[float]
    response_time_seconds: Optional[int]
    effectiveness_score: Optional[float]
    user_satisfaction: Optional[int]
    impact_calculated_at: Optional[datetime]
    created_at: datetime

class DecisionImpactReport(BaseModel):
    total_decisions: int
    accepted: int
    rejected: int
    deferred: int
    avg_response_time_seconds: Optional[float]
    total_energy_saved_kwh: Optional[float]
    total_cost_saved_gbp: Optional[float]
    avg_effectiveness_score: Optional[float]
    avg_satisfaction: Optional[float]


# ── Rankings ──────────────────────────────────────────────────

class RankingResponse(BaseModel):
    user_id: int
    home_id: int
    home_name: str
    period_type: str
    period_start: date
    overall_score: float
    rank_position: Optional[int]
    total_users: Optional[int]
    percentile: Optional[float]
    efficiency_score: Optional[float]
    goal_adherence_score: Optional[float]
    decision_response_score: Optional[float]
    total_kwh: Optional[float]
    total_cost_gbp: Optional[float]


# ── Admin ─────────────────────────────────────────────────────

class AdminNotificationSend(BaseModel):
    user_ids: Optional[List[int]] = None   # None = broadcast to all
    title: str
    message: str
    notification_type: str = "ADMIN_BROADCAST"
    severity: str = "INFO"
    action_hint: Optional[str] = None
    action_button_text: Optional[str] = None
    requires_user_action: bool = False

class AdminTemplateCreate(BaseModel):
    name: str
    title_template: str
    message_template: str
    notification_type: str = "ADMIN_BROADCAST"
    severity: str = "INFO"
    action_hint: Optional[str] = None
    action_button_text: Optional[str] = None
    requires_user_action: bool = False
    target_audience: str = "all"
    schedule_cron: Optional[str] = None

class AdminDashboardResponse(BaseModel):
    total_users: int
    active_users_today: int
    total_homes: int
    total_devices: int
    energy_today_kwh: float
    cost_today_gbp: float
    notifications_sent_today: int
    decisions_recorded_today: int
    avg_goal_adherence_pct: float

class PushTokenUpdate(BaseModel):
    push_token: str


# ── Environment (Room Sensors) ─────────────────────────────────

class EnvironmentalReading(BaseModel):
    current: Optional[float]
    unit: str
    data_count: int

class RoomEnvironmentResponse(BaseModel):
    room_name: str
    entity_id: Optional[str]
    home_id: Optional[int]
    home_name: Optional[str]
    temperature: EnvironmentalReading
    humidity: EnvironmentalReading
    pressure: EnvironmentalReading

class RoomSummary(BaseModel):
    home_id: int
    home_name: str
    room_name: str
    entity_id: Optional[str]
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    pressure_hpa: Optional[float]
    last_reading_time: Optional[str]
    has_data: bool


# ── Appliance Scenarios / Smart Notifications ─────────────────

class ApplianceAlert(BaseModel):
    level: str                   # e.g. "🟥", "🟧"
    priority: str                # critical, warning, caution, notice
    scenario: str                # human-readable name
    message: str                 # full human-readable alert message

class OptimizationConditions(BaseModel):
    temperature: float
    humidity: float
    pressure: float

class OptimizationFactors(BaseModel):
    fT: float
    fH: float
    fP: float

class OptimizationResult(BaseModel):
    appliance_key: str
    conditions: OptimizationConditions
    factors: OptimizationFactors
    base_energy_kwh: float
    adjusted_energy_kwh: float
    efficiency_loss_pct: float
    efficiency_score: float
    alerts: List[ApplianceAlert]
    recommendations: List[str]
    potential_savings_pct: float

class SmartAlertResponse(BaseModel):
    device_id: int
    device_name: str
    appliance_key: str
    home_id: int
    home_name: str
    location: Optional[str]
    efficiency_score: float
    potential_savings_pct: float
    level: str
    priority: str
    scenario: str
    message: str

class SmartNotificationsResponse(BaseModel):
    message: str
    alert_count: int
    alerts: List[SmartAlertResponse]

class DeviceCheckAdvisory(BaseModel):
    device_name: str
    appliance_key: str
    location: Optional[str]
    home_name: Optional[str]
    is_peak_time: bool
    current_tariff_pence_per_kwh: float
    estimated_cost_this_use_gbp: float
    efficiency_score: float
    alerts: List[ApplianceAlert]
    recommendations: List[str]
    verdict: str
