"""SQLAlchemy ORM models for WattWise Energy Monitoring Platform."""

from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, BigInteger, SmallInteger,
    String, Float, Boolean, DateTime, Date, Enum, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── PERSONAS ───────────────────────────────────────────────
class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    criteria = Column(JSON, nullable=	True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    users = relationship("User", back_populates="persona")


# ── USERS ────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    email = Column(String(256), nullable=False, unique=True)
    password_hash = Column(String(256), nullable=False)
    push_token = Column(String(512), nullable=True)
    notifications_enabled = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    reset_token = Column(String(256), nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    daily_energy_goal_kwh = Column(Float, nullable=True)
    weekly_energy_goal_kwh = Column(Float, nullable=True)
    monthly_budget_gbp = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    homes = relationship("Home", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    decisions = relationship("UserDecision", back_populates="user", cascade="all, delete-orphan")
    persona = relationship("Persona", back_populates="users", uselist=False)
    goals = relationship("EnergyGoal", back_populates="user", cascade="all, delete-orphan")
    rankings = relationship("EnergyRanking", back_populates="user", cascade="all, delete-orphan")


# ── HOMES ────────────────────────────────────────────────────
class Home(Base):
    __tablename__ = "homes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    home_name = Column(String(128), nullable=False)
    address = Column(String(256), nullable=True)
    location_desc = Column(String(256), nullable=True)
    num_occupants = Column(SmallInteger, default=1)
    home_type = Column(
        Enum("flat", "terraced", "semi-detached", "detached", "other"),
        default="other"
    )
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="homes")
    devices = relationship("Device", back_populates="home", cascade="all, delete-orphan")
    rooms = relationship("Room", back_populates="home", cascade="all, delete-orphan")
    daily_totals = relationship("HomeDailyTotal", back_populates="home", cascade="all, delete-orphan")
    rankings = relationship("EnergyRanking", back_populates="home", cascade="all, delete-orphan")


# ── DEVICES ──────────────────────────────────────────────────
class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    home_id = Column(Integer, ForeignKey("homes.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    appliance_key = Column(String(64), nullable=False)
    location = Column(String(128), nullable=True)
    entity_id = Column(String(128), nullable=True)
    power_entity_id = Column(String(128), nullable=True)
    switch_entity_id = Column(String(128), nullable=True)
    device_type = Column(Enum("appliance", "sensor", "switch"), default="appliance")
    rated_wattage = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    home = relationship("Home", back_populates="devices")
    readings = relationship("EnergyReading", back_populates="device", cascade="all, delete-orphan")
    hourly_summaries = relationship("HourlySummary", back_populates="device", cascade="all, delete-orphan")
    daily_summaries = relationship("DailySummary", back_populates="device", cascade="all, delete-orphan")


# ── ROOMS ────────────────────────────────────────────────────
class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    home_id = Column(Integer, ForeignKey("homes.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    entity_id = Column(String(128), nullable=True)

    home = relationship("Home", back_populates="rooms")


# ── ENERGY READINGS ──────────────────────────────────────────
class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    recorded_at = Column(DateTime, nullable=False)
    power_watts = Column(Float, nullable=False, default=0)
    current_amps = Column(Float, nullable=True)
    voltage_volts = Column(Float, nullable=True)
    energy_kwh = Column(Float, nullable=True)
    switch_state = Column(Enum("on", "off", "unknown"), default="unknown")

    device = relationship("Device", back_populates="readings")

    __table_args__ = (
        Index("idx_readings_device_time", "device_id", "recorded_at"),
        # Prevent duplicate readings for same device at same timestamp
        UniqueConstraint("device_id", "recorded_at", name="uq_reading_device_time"),
        # Data quality: power cannot be negative
        CheckConstraint("power_watts >= 0", name="chk_power_non_negative"),
    )


# ── HOURLY SUMMARY ───────────────────────────────────────────
class HourlySummary(Base):
    __tablename__ = "hourly_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    hour_start = Column(DateTime, nullable=False)
    avg_watts = Column(Float, default=0)
    max_watts = Column(Float, default=0)
    min_watts = Column(Float, default=0)
    total_kwh = Column(Float, default=0)
    usage_cycles = Column(SmallInteger, default=0)
    active_minutes = Column(SmallInteger, default=0)
    reading_count = Column(SmallInteger, default=0)

    device = relationship("Device", back_populates="hourly_summaries")

    __table_args__ = (
        UniqueConstraint("device_id", "hour_start", name="uq_hourly"),
        Index("idx_hourly_time", "hour_start"),
    )


# ── DAILY SUMMARY ─────────────────────────────────────────────
class DailySummary(Base):
    __tablename__ = "daily_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    home_id = Column(Integer, ForeignKey("homes.id", ondelete="CASCADE"), nullable=False)
    day_date = Column(Date, nullable=False)
    total_kwh = Column(Float, default=0)
    avg_watts = Column(Float, default=0)
    peak_watts = Column(Float, default=0)
    usage_cycles = Column(SmallInteger, default=0)
    active_minutes = Column(SmallInteger, default=0)
    estimated_cost_gbp = Column(Float, default=0)
    efficiency_score = Column(Float, nullable=True)
    goal_kwh = Column(Float, nullable=True)
    goal_met = Column(Boolean, nullable=True)
    reading_count = Column(Integer, default=0)

    device = relationship("Device", back_populates="daily_summaries")

    __table_args__ = (
        UniqueConstraint("device_id", "day_date", name="uq_daily"),
        Index("idx_daily_home_date", "home_id", "day_date"),
    )


# ── HOME DAILY TOTALS ─────────────────────────────────────────
class HomeDailyTotal(Base):
    __tablename__ = "home_daily_totals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    home_id = Column(Integer, ForeignKey("homes.id", ondelete="CASCADE"), nullable=False)
    day_date = Column(Date, nullable=False)
    total_kwh = Column(Float, default=0)
    total_cost_gbp = Column(Float, default=0)
    active_devices = Column(SmallInteger, default=0)
    peak_watts = Column(Float, default=0)
    efficiency_score = Column(Float, nullable=True)

    home = relationship("Home", back_populates="daily_totals")

    __table_args__ = (
        UniqueConstraint("home_id", "day_date", name="uq_home_daily"),
        Index("idx_home_daily_date", "day_date"),
    )


# ── ENERGY GOALS ─────────────────────────────────────────────
class EnergyGoal(Base):
    __tablename__ = "energy_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    goal_type = Column(Enum("daily", "weekly", "monthly", "per_device"), nullable=False)
    target_kwh = Column(Float, nullable=True)
    target_cost_gbp = Column(Float, nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="goals")


# ── NOTIFICATIONS ─────────────────────────────────────────────
class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    home_id = Column(Integer, ForeignKey("homes.id", ondelete="SET NULL"), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    notification_type = Column(
        Enum(
            "ENERGY_ALERT", "GOAL_WARNING", "GOAL_MET", "PEAK_USAGE",
            "HIGH_CONSUMPTION", "STANDBY_ALERT", "PEAK_TARIFF_REMINDER",
            "DAILY_SUMMARY", "WEEKLY_SUMMARY", "MONTHLY_SUMMARY",
            "ADMIN_BROADCAST", "RECOMMENDATION", "ACHIEVEMENT", "TEST"
        ),
        nullable=False
    )
    severity = Column(Enum("INFO", "WARNING", "ALERT", "CRITICAL"), default="INFO", nullable=False)
    title = Column(String(256), nullable=False)
    message = Column(Text, nullable=False)
    action_hint = Column(String(256), nullable=True)
    action_button_text = Column(String(64), nullable=True)
    requires_user_action = Column(Boolean, default=False, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime, nullable=True)
    dismissed = Column(Boolean, default=False, nullable=False)
    dismissed_at = Column(DateTime, nullable=True)
    sent_via_push = Column(Boolean, default=False, nullable=False)
    push_receipt_id = Column(String(256), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")
    decision = relationship("UserDecision", back_populates="notification", uselist=False)

    __table_args__ = (
        Index("idx_notif_user_created", "user_id", "created_at"),
        Index("idx_notif_unread", "user_id", "is_read"),
    )


# ── USER DECISIONS (Research Core) ───────────────────────────
class UserDecision(Base):
    __tablename__ = "user_decisions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_id = Column(BigInteger, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    decision_type = Column(
        Enum("ACCEPTED", "REJECTED", "DEFERRED", "CUSTOM_ACTION"),
        nullable=False
    )
    action_taken = Column(Text, nullable=True)
    action_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    measure_window_hours = Column(SmallInteger, default=2)
    energy_before_kwh = Column(Float, nullable=True)
    energy_after_kwh = Column(Float, nullable=True)
    energy_saved_kwh = Column(Float, nullable=True)
    cost_saved_gbp = Column(Float, nullable=True)
    notification_sent_at = Column(DateTime, nullable=True)
    response_time_seconds = Column(Integer, nullable=True)
    effectiveness_score = Column(Float, nullable=True)
    user_feedback_text = Column(Text, nullable=True)
    user_satisfaction = Column(SmallInteger, nullable=True)
    impact_calculated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="decisions")
    notification = relationship("Notification", back_populates="decision")

    __table_args__ = (
        Index("idx_decisions_user", "user_id", "created_at"),
    )


# ── USER INTERACTION LOG ──────────────────────────────────────
class UserInteractionLog(Base):
    __tablename__ = "user_interaction_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    interaction_type = Column(
        Enum(
            "LOGIN", "LOGOUT", "VIEW_DASHBOARD", "VIEW_DEVICE", "VIEW_NOTIFICATION",
            "SET_GOAL", "UPDATE_GOAL", "RECORD_DECISION", "VIEW_RANKING",
            "VIEW_REPORT", "CHANGE_SETTINGS", "APP_OPEN", "APP_CLOSE"
        ),
        nullable=False
    )
    screen_name = Column(String(128), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    notification_id = Column(BigInteger, ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(64), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_interaction_user_time", "user_id", "created_at"),
    )


# ── ADMIN NOTIFICATION TEMPLATES ──────────────────────────────
class AdminNotificationTemplate(Base):
    __tablename__ = "admin_notification_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    title_template = Column(String(256), nullable=False)
    message_template = Column(Text, nullable=False)
    notification_type = Column(
        Enum(
            "ENERGY_ALERT", "GOAL_WARNING", "PEAK_TARIFF_REMINDER",
            "ADMIN_BROADCAST", "RECOMMENDATION", "ACHIEVEMENT"
        ),
        default="ADMIN_BROADCAST",
        nullable=False
    )
    severity = Column(Enum("INFO", "WARNING", "ALERT", "CRITICAL"), default="INFO", nullable=False)
    action_hint = Column(String(256), nullable=True)
    action_button_text = Column(String(64), nullable=True)
    requires_user_action = Column(Boolean, default=False, nullable=False)
    target_audience = Column(
        Enum("all", "active_today", "high_usage", "goal_breached", "custom"),
        default="all"
    )
    schedule_cron = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ── ENERGY RANKINGS ───────────────────────────────────────────
class EnergyRanking(Base):
    __tablename__ = "energy_rankings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    home_id = Column(Integer, ForeignKey("homes.id", ondelete="CASCADE"), nullable=False)
    period_type = Column(Enum("DAILY", "WEEKLY", "MONTHLY"), nullable=False)
    period_start = Column(Date, nullable=False)
    overall_score = Column(Float, nullable=False)
    rank_position = Column(Integer, nullable=True)
    total_users = Column(Integer, nullable=True)
    percentile = Column(Float, nullable=True)
    efficiency_score = Column(Float, nullable=True)
    goal_adherence_score = Column(Float, nullable=True)
    decision_response_score = Column(Float, nullable=True)
    improvement_score = Column(Float, nullable=True)
    total_kwh = Column(Float, nullable=True)
    total_cost_gbp = Column(Float, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="rankings")
    home = relationship("Home", back_populates="rankings")

    __table_args__ = (
        UniqueConstraint("user_id", "period_type", "period_start", name="uq_ranking"),
        Index("idx_ranking_period", "period_type", "period_start", "overall_score"),
    )


# ── ADMIN AUDIT LOG ───────────────────────────────────────────
class AdminAuditLog(Base):
    """Records every significant admin action for accountability and research auditing."""
    __tablename__ = "admin_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action_type = Column(
        Enum(
            "SEND_NOTIFICATION", "ASSIGN_PERSONA", "TOGGLE_NOTIFICATIONS",
            "RESET_PASSWORD", "BULK_OPERATION", "EDIT_USER",
            "RUN_CLASSIFIER", "EXPORT_DATA", "BACKUP_TRIGGERED", "LOGIN",
        ),
        nullable=False,
    )
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    details_json = Column(JSON, nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_audit_admin_time", "admin_user_id", "created_at"),
        Index("idx_audit_action", "action_type", "created_at"),
    )
