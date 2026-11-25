"""Pydantic schemas for WattWise API request/response validation."""

from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_admin: bool
    notifications_enabled: bool
    daily_energy_goal_kwh: Optional[float]
    weekly_energy_goal_kwh: Optional[float]
    monthly_budget_gbp: Optional[float]
    created_at: datetime
    persona_id: Optional[int] = None
    persona_name: Optional[str] = None
    last_login_at: Optional[datetime] = None
    is_synthetic: bool = False


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
    model_config = ConfigDict(from_attributes=True)

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
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    current_kwh: float
    current_cost_gbp: float
    percentage_used: float
    days_remaining: Optional[int]
    on_track: bool
    projected_kwh: Optional[float]


# ── Notifications ─────────────────────────────────────────────

class DecisionBrief(BaseModel):
    """The user's response to an alert, embedded in the alert itself."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_type: str
    action_taken: Optional[str] = None
    user_feedback_text: Optional[str] = None
    user_satisfaction: Optional[int] = None
    action_timestamp: Optional[datetime] = None
    remind_at: Optional[datetime] = None
    energy_saved_kwh: Optional[float] = None
    cost_saved_gbp: Optional[float] = None
    effectiveness_score: Optional[float] = None
    impact_scope: Optional[str] = None
    impact_calculated_at: Optional[datetime] = None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    home_id: Optional[int] = None
    device_id: Optional[int]
    device_name: Optional[str] = None
    appliance_key: Optional[str] = None
    notification_type: str
    severity: str
    source: str = "AUTOMATED"
    title: str
    message: str
    action_hint: Optional[str]
    action_button_text: Optional[str]
    requires_user_action: bool
    metadata_json: Optional[dict]
    # `message` is the whole notification, ending with its health tip. These two are the
    # same text in parts (from metadata_json), so a client can lay them out separately.
    health_tip: Optional[str] = None
    energy_message: Optional[str] = None
    is_read: bool
    read_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    dismissed: bool
    sent_via_push: bool
    expires_at: Optional[datetime] = None
    is_expired: bool = False
    created_at: datetime
    decision: Optional[DecisionBrief] = None

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
    action_taken: Optional[str] = Field(default=None, max_length=500)
    user_feedback_text: Optional[str] = Field(default=None, max_length=2000)
    user_satisfaction: Optional[int] = Field(default=None, ge=1, le=5)
    # DEFERRED only: re-surface the alert after this many minutes (default 120).
    remind_in_minutes: Optional[int] = Field(default=None, ge=5, le=7 * 24 * 60)


class DecisionUpdate(BaseModel):
    """Change a recorded decision: complete a deferred alert, or add what was done / feedback."""
    decision_type: Optional[str] = Field(default=None, pattern="^(ACCEPTED|REJECTED|DEFERRED|CUSTOM_ACTION)$")
    action_taken: Optional[str] = Field(default=None, max_length=500)
    user_feedback_text: Optional[str] = Field(default=None, max_length=2000)
    user_satisfaction: Optional[int] = Field(default=None, ge=1, le=5)
    remind_in_minutes: Optional[int] = Field(default=None, ge=5, le=7 * 24 * 60)


class InteractionCreate(BaseModel):
    """A client-side event (app open, screen view…) for behavioural analytics."""
    interaction_type: str = Field(
        ...,
        pattern="^(APP_OPEN|APP_CLOSE|LOGOUT|VIEW_DASHBOARD|VIEW_DEVICE|VIEW_RANKING|VIEW_REPORT|CHANGE_SETTINGS)$",
    )
    screen_name: Optional[str] = Field(default=None, max_length=128)
    device_id: Optional[int] = None
    notification_id: Optional[int] = None
    session_id: Optional[str] = Field(default=None, max_length=64)
    metadata: Optional[dict] = None

class DecisionResponse(BaseModel):
    id: int
    user_id: int
    notification_id: Optional[int] = None  # NULL once the alert itself has been pruned
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
    user_feedback_text: Optional[str] = None
    impact_calculated_at: Optional[datetime]
    impact_scope: Optional[str] = None
    remind_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    # Filled by the list endpoint so history can show what the decision was about.
    notification_title: Optional[str] = None
    notification_type: Optional[str] = None
    device_name: Optional[str] = None

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
    # Targeting precedence: user_ids > home_ids > target_persona_id > everyone in `cohort`.
    user_ids: Optional[List[int]] = None
    home_ids: Optional[List[int]] = None
    target_persona_id: Optional[int] = None
    cohort: str = Field(default="all", pattern="^(real|synthetic|all)$")
    title: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=4000)
    notification_type: str = Field(
        default="ADMIN_BROADCAST",
        pattern="^(ADMIN_BROADCAST|ENERGY_ALERT|GOAL_WARNING|PEAK_TARIFF_REMINDER|RECOMMENDATION|ACHIEVEMENT)$",
    )
    severity: str = Field(default="INFO", pattern="^(INFO|WARNING|ALERT|CRITICAL)$")
    action_hint: Optional[str] = Field(default=None, max_length=256)
    action_button_text: Optional[str] = Field(default=None, max_length=64)
    requires_user_action: bool = False
    # Attach the alert to one device of each targeted home (by appliance), so the
    # energy impact of the user's response can be measured on that device.
    appliance_key: Optional[str] = Field(default=None, max_length=64)
    # Leave empty to send now; a future time schedules the campaign.
    send_at: Optional[datetime] = None

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

class ProfileUpdateRequest(BaseModel):
    monthly_budget_gbp: Optional[float] = Field(default=None, ge=0)
    daily_energy_goal_kwh: Optional[float] = Field(default=None, ge=0)
    notifications_enabled: Optional[bool] = None


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
