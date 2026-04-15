"""
WattWise Test Configuration
=============================
Sets up environment variables before any app module is imported,
so settings validation doesn't fail during test runs.
"""

import os

# Provide all required settings so pydantic-settings doesn't raise on import
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_unit_tests_only_x_padding_here")
os.environ.setdefault("DATABASE_URL", "mysql+aiomysql://test:test@localhost:3306/test")
os.environ.setdefault("INFLUX_HOST", "localhost")
os.environ.setdefault("INFLUX_PORT", "8086")
os.environ.setdefault("INFLUX_USER", "test")
os.environ.setdefault("INFLUX_PASS", "test")
os.environ.setdefault("INFLUX_DB", "test")
os.environ.setdefault("MQTT_BROKER_HOST", "localhost")
os.environ.setdefault("MQTT_BROKER_PORT", "1883")
os.environ.setdefault("MQTT_USERNAME", "test")
os.environ.setdefault("MQTT_PASSWORD", "test")
os.environ.setdefault("MQTT_TOPIC_PREFIX", "wattwise/homes")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_pass_long_enough")
os.environ.setdefault("STRICT_SECURITY", "false")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
