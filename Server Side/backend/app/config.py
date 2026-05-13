"""WattWise — Application Configuration."""

import logging as _logging

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MySQL (Relational data) — Dynamically constructed for Host/Docker compatibility
    DB_USER: str = "wattwise_app"
    DB_PASS: str = "changeme_app_2026"
    DB_HOST: str = "mysql"
    DB_PORT: int = 3306
    DB_NAME: str = "wattwise_db"

    @property
    def DATABASE_URL(self) -> str:
        # Construct async MySQL URL
        return f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # InfluxDB (Time-series energy telemetry)
    INFLUX_HOST: str = "influxdb"
    INFLUX_PORT: int = 8086
    INFLUX_DB: str = "wattwise_energy"
    INFLUX_USER: str = "wattwise_influx"
    INFLUX_PASS: str = "changeme_influx_2026"
    INFLUX_PROTOCOL: str = "http"

    # MQTT
    MQTT_BROKER_HOST: str = "mosquitto"
    MQTT_BROKER_PORT: int = 1883
    MQTT_TOPIC_PREFIX: str = "wattwise/homes"
    MQTT_USERNAME: str = "wattwise_backend"
    MQTT_PASSWORD: str = "changeme_mqtt_2026"

    # Auth
    SECRET_KEY: str = "changeme-secret-key-wattwise-2026"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    STRICT_SECURITY: bool = False
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 10
    ENABLE_PASSWORD_HASHING: bool = False

    # UK Energy Tariff Rates (£/kWh)
    ENERGY_STANDARD_PRICE_PER_KWH: float = 0.2700
    ENERGY_PEAK_PRICE_PER_KWH: float = 0.3200
    ENERGY_OFFPEAK_PRICE_PER_KWH: float = 0.1300
    ENERGY_PEAK_START_HOUR: int = 16   # 4 PM
    ENERGY_PEAK_END_HOUR: int = 19     # 7 PM

    # Energy Alert Thresholds
    ENERGY_DAILY_WARNING_KWH: float = 15.0
    ENERGY_DAILY_HIGH_KWH: float = 25.0
    ENERGY_DEVICE_STANDBY_WATTS: float = 5.0
    ENERGY_USAGE_SPIKE_MULTIPLIER: float = 2.0  # 2× average = spike

    # Decision impact measurement window (hours)
    DECISION_MEASURE_WINDOW_HOURS: int = 2

    # Expo Push Notifications
    EXPO_PUSH_URL: str = "https://exp.host/--/api/v2/push/send"

    # Admin
    ADMIN_EMAIL: str = "admin@wattwise.co.uk"
    ADMIN_PASSWORD: str = "changeme_admin_2026"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:5000"

    # Email (SMTP) — optional, leave SMTP_USER empty to disable
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "WattWise <noreply@wattwiser.org>"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    def get_current_tariff(self) -> float:
        """Return current UK tariff rate based on time of day."""
        from datetime import datetime
        hour = datetime.now().hour
        if self.ENERGY_PEAK_START_HOUR <= hour < self.ENERGY_PEAK_END_HOUR:
            return self.ENERGY_PEAK_PRICE_PER_KWH
        if 0 <= hour < 7:
            return self.ENERGY_OFFPEAK_PRICE_PER_KWH
        return self.ENERGY_STANDARD_PRICE_PER_KWH

    def is_peak_time(self) -> bool:
        from datetime import datetime
        hour = datetime.now().hour
        return self.ENERGY_PEAK_START_HOUR <= hour < self.ENERGY_PEAK_END_HOUR


def _warn_changeme(settings: "Settings") -> None:
    _logger = _logging.getLogger("wattwise.config")
    fields = {
        "SECRET_KEY": settings.SECRET_KEY,
        "DATABASE_URL": settings.DATABASE_URL,
        "INFLUX_PASS": settings.INFLUX_PASS,
        "MQTT_PASSWORD": settings.MQTT_PASSWORD,
        "ADMIN_PASSWORD": getattr(settings, "ADMIN_PASSWORD", ""),
    }
    for name, val in fields.items():
        if val and "changeme" in str(val).lower():
            _logger.critical(
                "SECURITY: %s contains 'changeme' — change before production!", name
            )


settings = Settings()
_warn_changeme(settings)
