-- ============================================================
-- WattWise Energy Monitoring Platform — MySQL Schema
-- Developer: Mr. Suhas Devmane
-- Version: 1.0.0
-- ============================================================

SET FOREIGN_KEY_CHECKS=0;
CREATE DATABASE IF NOT EXISTS wattwise_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE wattwise_db;

-- ── USERS ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(128) NOT NULL,
    email            VARCHAR(256) NOT NULL UNIQUE,
    password_hash    VARCHAR(256) NOT NULL,
    push_token       VARCHAR(512) DEFAULT NULL,
    notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin         BOOLEAN NOT NULL DEFAULT FALSE,
    reset_token      VARCHAR(256) DEFAULT NULL,
    reset_token_expiry DATETIME DEFAULT NULL,
    daily_energy_goal_kwh  FLOAT DEFAULT NULL,
    weekly_energy_goal_kwh FLOAT DEFAULT NULL,
    monthly_budget_gbp     FLOAT DEFAULT NULL,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at    DATETIME DEFAULT NULL,
    INDEX idx_users_email (email)
) ENGINE=InnoDB;

-- ── HOMES ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS homes (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL,
    home_name        VARCHAR(128) NOT NULL,
    address          VARCHAR(256) DEFAULT NULL,
    location_desc    VARCHAR(256) DEFAULT NULL,
    num_occupants    TINYINT UNSIGNED DEFAULT 1,
    home_type        ENUM('flat','terraced','semi-detached','detached','other') DEFAULT 'other',
    registered_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_homes_user (user_id)
) ENGINE=InnoDB;

-- ── DEVICES (Smart Plugs / Appliances) ───────────────────────
CREATE TABLE IF NOT EXISTS devices (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    home_id          INT UNSIGNED NOT NULL,
    name             VARCHAR(128) NOT NULL,
    appliance_key    VARCHAR(64) NOT NULL,
    location         VARCHAR(128) DEFAULT NULL COMMENT 'Room name',
    entity_id        VARCHAR(128) DEFAULT NULL COMMENT 'HA entity ID',
    power_entity_id  VARCHAR(128) DEFAULT NULL,
    switch_entity_id VARCHAR(128) DEFAULT NULL,
    device_type      ENUM('appliance','sensor','switch') DEFAULT 'appliance',
    rated_wattage    FLOAT DEFAULT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (home_id) REFERENCES homes(id) ON DELETE CASCADE,
    INDEX idx_devices_home (home_id),
    INDEX idx_devices_entity (entity_id)
) ENGINE=InnoDB;

-- ── ROOMS (Environmental Sensors) ────────────────────────────
CREATE TABLE IF NOT EXISTS rooms (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    home_id          INT UNSIGNED NOT NULL,
    name             VARCHAR(128) NOT NULL,
    entity_id        VARCHAR(128) DEFAULT NULL,
    FOREIGN KEY (home_id) REFERENCES homes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ── ENERGY READINGS (Raw from MQTT / HTTP) ───────────────────
-- For high-volume, this acts as a buffer before hourly aggregation.
-- Long-term raw storage remains in InfluxDB.
CREATE TABLE IF NOT EXISTS energy_readings (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    device_id        INT UNSIGNED NOT NULL,
    recorded_at      DATETIME(3) NOT NULL,
    power_watts      FLOAT NOT NULL DEFAULT 0,
    current_amps     FLOAT DEFAULT NULL,
    voltage_volts    FLOAT DEFAULT NULL,
    energy_kwh       FLOAT DEFAULT NULL COMMENT 'Cumulative kWh counter from plug',
    switch_state     ENUM('on','off','unknown') DEFAULT 'unknown',
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    INDEX idx_readings_device_time (device_id, recorded_at)
) ENGINE=InnoDB ROW_FORMAT=COMPRESSED;

-- ── HOURLY SUMMARIES ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hourly_summary (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    device_id        INT UNSIGNED NOT NULL,
    hour_start       DATETIME NOT NULL,
    avg_watts        FLOAT DEFAULT 0,
    max_watts        FLOAT DEFAULT 0,
    min_watts        FLOAT DEFAULT 0,
    total_kwh        FLOAT DEFAULT 0,
    usage_cycles     SMALLINT UNSIGNED DEFAULT 0 COMMENT 'On/off cycles this hour',
    active_minutes   SMALLINT UNSIGNED DEFAULT 0,
    reading_count    SMALLINT UNSIGNED DEFAULT 0,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    UNIQUE KEY uq_hourly (device_id, hour_start),
    INDEX idx_hourly_time (hour_start)
) ENGINE=InnoDB;

-- ── DAILY SUMMARIES ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_summary (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    device_id        INT UNSIGNED NOT NULL,
    home_id          INT UNSIGNED NOT NULL,
    day_date         DATE NOT NULL,
    total_kwh        FLOAT DEFAULT 0,
    avg_watts        FLOAT DEFAULT 0,
    peak_watts       FLOAT DEFAULT 0,
    usage_cycles     SMALLINT UNSIGNED DEFAULT 0,
    active_minutes   SMALLINT UNSIGNED DEFAULT 0,
    estimated_cost_gbp FLOAT DEFAULT 0,
    efficiency_score FLOAT DEFAULT NULL COMMENT '0-100 score',
    goal_kwh         FLOAT DEFAULT NULL COMMENT "User's target kWh for this device",
    goal_met         BOOLEAN DEFAULT NULL,
    reading_count    INT UNSIGNED DEFAULT 0,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    FOREIGN KEY (home_id) REFERENCES homes(id) ON DELETE CASCADE,
    UNIQUE KEY uq_daily (device_id, day_date),
    INDEX idx_daily_home_date (home_id, day_date)
) ENGINE=InnoDB;

-- ── HOME DAILY TOTALS (Across all devices) ───────────────────
CREATE TABLE IF NOT EXISTS home_daily_totals (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    home_id          INT UNSIGNED NOT NULL,
    day_date         DATE NOT NULL,
    total_kwh        FLOAT DEFAULT 0,
    total_cost_gbp   FLOAT DEFAULT 0,
    active_devices   TINYINT UNSIGNED DEFAULT 0,
    peak_watts       FLOAT DEFAULT 0,
    efficiency_score FLOAT DEFAULT NULL,
    FOREIGN KEY (home_id) REFERENCES homes(id) ON DELETE CASCADE,
    UNIQUE KEY uq_home_daily (home_id, day_date),
    INDEX idx_home_daily_date (day_date)
) ENGINE=InnoDB;

-- ── ENERGY GOALS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS energy_goals (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL,
    device_id        INT UNSIGNED DEFAULT NULL COMMENT 'NULL = whole-home goal',
    goal_type        ENUM('daily','weekly','monthly','per_device') NOT NULL,
    target_kwh       FLOAT DEFAULT NULL,
    target_cost_gbp  FLOAT DEFAULT NULL,
    start_date       DATE NOT NULL,
    end_date         DATE DEFAULT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL,
    INDEX idx_goals_user (user_id)
) ENGINE=InnoDB;

-- ── NOTIFICATIONS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL,
    home_id          INT UNSIGNED DEFAULT NULL,
    device_id        INT UNSIGNED DEFAULT NULL,
    notification_type ENUM(
        'ENERGY_ALERT','GOAL_WARNING','GOAL_MET','PEAK_USAGE',
        'HIGH_CONSUMPTION','STANDBY_ALERT','PEAK_TARIFF_REMINDER',
        'DAILY_SUMMARY','WEEKLY_SUMMARY','MONTHLY_SUMMARY',
        'ADMIN_BROADCAST','RECOMMENDATION','ACHIEVEMENT','TEST'
    ) NOT NULL,
    severity         ENUM('INFO','WARNING','ALERT','CRITICAL') NOT NULL DEFAULT 'INFO',
    title            VARCHAR(256) NOT NULL,
    message          TEXT NOT NULL,
    action_hint      VARCHAR(256) DEFAULT NULL COMMENT 'Suggested user action',
    action_button_text VARCHAR(64) DEFAULT NULL,
    requires_user_action BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json    JSON DEFAULT NULL COMMENT 'Extra context data',
    is_read          BOOLEAN NOT NULL DEFAULT FALSE,
    read_at          DATETIME DEFAULT NULL,
    dismissed        BOOLEAN NOT NULL DEFAULT FALSE,
    dismissed_at     DATETIME DEFAULT NULL,
    sent_via_push    BOOLEAN NOT NULL DEFAULT FALSE,
    push_receipt_id  VARCHAR(256) DEFAULT NULL,
    sent_at          DATETIME DEFAULT NULL,
    expires_at       DATETIME DEFAULT NULL,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (home_id) REFERENCES homes(id) ON DELETE SET NULL,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL,
    INDEX idx_notif_user_created (user_id, created_at),
    INDEX idx_notif_unread (user_id, is_read),
    INDEX idx_notif_expires (expires_at)
) ENGINE=InnoDB;

-- ── USER DECISIONS (⭐ Core Research Model) ───────────────────
-- Records what action a user takes after receiving a notification,
-- and the energy impact of that decision.
CREATE TABLE IF NOT EXISTS user_decisions (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL,
    notification_id  BIGINT UNSIGNED NOT NULL,
    device_id        INT UNSIGNED DEFAULT NULL,
    decision_type    ENUM('ACCEPTED','REJECTED','DEFERRED','CUSTOM_ACTION') NOT NULL,
    action_taken     TEXT DEFAULT NULL COMMENT 'Free text describing what user did',
    action_timestamp DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    -- Energy impact measured over a 2-hour window before and after
    measure_window_hours TINYINT UNSIGNED DEFAULT 2,
    energy_before_kwh    FLOAT DEFAULT NULL COMMENT 'kWh used in window before decision',
    energy_after_kwh     FLOAT DEFAULT NULL COMMENT 'kWh used in window after decision',
    energy_saved_kwh     FLOAT DEFAULT NULL COMMENT 'Positive = saved energy',
    cost_saved_gbp       FLOAT DEFAULT NULL,

    -- Response time analysis
    notification_sent_at DATETIME DEFAULT NULL,
    response_time_seconds INT UNSIGNED DEFAULT NULL COMMENT 'Seconds from notification → decision',

    -- Score computed by decision_tracker
    effectiveness_score  FLOAT DEFAULT NULL COMMENT '0-100, auto-calculated after window expires',
    user_feedback_text   TEXT DEFAULT NULL COMMENT 'Optional free-text from user',
    user_satisfaction    TINYINT DEFAULT NULL COMMENT '1-5 star rating',
    impact_calculated_at DATETIME DEFAULT NULL,

    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL,
    INDEX idx_decisions_user (user_id, created_at),
    INDEX idx_decisions_notification (notification_id)
) ENGINE=InnoDB;

-- ── USER INTERACTION LOG ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_interaction_logs (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL,
    interaction_type ENUM(
        'LOGIN','LOGOUT','VIEW_DASHBOARD','VIEW_DEVICE','VIEW_NOTIFICATION',
        'SET_GOAL','UPDATE_GOAL','RECORD_DECISION','VIEW_RANKING',
        'VIEW_REPORT','CHANGE_SETTINGS','APP_OPEN','APP_CLOSE'
    ) NOT NULL,
    screen_name      VARCHAR(128) DEFAULT NULL,
    device_id        INT UNSIGNED DEFAULT NULL,
    notification_id  BIGINT UNSIGNED DEFAULT NULL,
    session_id       VARCHAR(64) DEFAULT NULL,
    metadata_json    JSON DEFAULT NULL,
    created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_interaction_user_time (user_id, created_at)
) ENGINE=InnoDB;

-- ── ADMIN NOTIFICATION TEMPLATES ─────────────────────────────
CREATE TABLE IF NOT EXISTS admin_notification_templates (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(128) NOT NULL,
    title_template   VARCHAR(256) NOT NULL,
    message_template TEXT NOT NULL,
    notification_type ENUM(
        'ENERGY_ALERT','GOAL_WARNING','PEAK_TARIFF_REMINDER',
        'ADMIN_BROADCAST','RECOMMENDATION','ACHIEVEMENT'
    ) NOT NULL DEFAULT 'ADMIN_BROADCAST',
    severity         ENUM('INFO','WARNING','ALERT','CRITICAL') NOT NULL DEFAULT 'INFO',
    action_hint      VARCHAR(256) DEFAULT NULL,
    action_button_text VARCHAR(64) DEFAULT NULL,
    requires_user_action BOOLEAN NOT NULL DEFAULT FALSE,
    target_audience  ENUM('all','active_today','high_usage','goal_breached','custom') DEFAULT 'all',
    schedule_cron    VARCHAR(64) DEFAULT NULL COMMENT 'Cron expression for automated sending',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_by       INT UNSIGNED DEFAULT NULL,
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ── ENERGY RANKINGS ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS energy_rankings (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id          INT UNSIGNED NOT NULL,
    home_id          INT UNSIGNED NOT NULL,
    period_type      ENUM('DAILY','WEEKLY','MONTHLY') NOT NULL,
    period_start     DATE NOT NULL,
    overall_score    FLOAT NOT NULL COMMENT '0-100 composite score',
    rank_position    INT UNSIGNED DEFAULT NULL,
    total_users      INT UNSIGNED DEFAULT NULL,
    percentile       FLOAT DEFAULT NULL COMMENT 'Top X%',
    efficiency_score     FLOAT DEFAULT NULL COMMENT 'Energy efficiency vs peers',
    goal_adherence_score FLOAT DEFAULT NULL COMMENT 'How well user met their goals',
    decision_response_score FLOAT DEFAULT NULL COMMENT 'Responsiveness to notifications',
    improvement_score    FLOAT DEFAULT NULL COMMENT 'Improvement vs previous period',
    total_kwh        FLOAT DEFAULT NULL,
    total_cost_gbp   FLOAT DEFAULT NULL,
    computed_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (home_id) REFERENCES homes(id) ON DELETE CASCADE,
    UNIQUE KEY uq_ranking (user_id, period_type, period_start),
    INDEX idx_ranking_period (period_type, period_start, overall_score)
) ENGINE=InnoDB;

-- ── DEFAULT ADMIN USER ────────────────────────────────────────
-- Password: wattwise_admin (bcrypt hash — change before production)
INSERT IGNORE INTO users (name, email, password_hash, is_admin, notifications_enabled)
VALUES (
    'Suhas Devmane',
    'admin@wattwise.co.uk',
    '$2b$12$S11M7M.wCDn7Be4q9NBkM.M.d8VUl5arXwyWlwf.Pi2sR4pv5B6IW',
    TRUE,
    FALSE
);

SET FOREIGN_KEY_CHECKS=1;
