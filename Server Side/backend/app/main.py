import os
import logging
import logging.config
from datetime import datetime
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jose import jwt, JWTError
from sqlalchemy import text

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.mqtt_client import start_mqtt, stop_mqtt, is_mqtt_connected
from app.observability import metrics_store
from app.scheduler import (
    aggregate_hourly, aggregate_daily, check_goals,
    send_peak_reminder, send_daily_report,
    calculate_decision_impacts, compute_rankings,
    cleanup_old_notifications, detect_and_notify_anomalies,
)
from app.email_report import send_weekly_reports
from app.persona_classifier import classify_all_users, seed_default_personas
from app.routers import auth, devices, readings, goals, decisions, notifications, analysis, admin, export, backup
from app.routers import advanced
from app.routers import influx, environment, smart_notifications


def _configure_logging():
    """Configure structured JSON logging for production or human-readable for dev."""
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    if log_format == "json":
        # Structured JSON — compatible with Grafana Loki, Datadog, CloudWatch
        try:
            from pythonjsonlogger import jsonlogger

            class _WattwiseJsonFormatter(jsonlogger.JsonFormatter):
                def add_fields(self, log_record, record, message_dict):
                    super().add_fields(log_record, record, message_dict)
                    log_record["service"] = "wattwise-backend"
                    log_record["level"] = record.levelname
                    log_record["ts"] = datetime.utcnow().isoformat() + "Z"

            handler = logging.StreamHandler()
            handler.setFormatter(_WattwiseJsonFormatter("%(message)s %(name)s %(levelname)s"))
            logging.root.handlers = [handler]
            logging.root.setLevel(log_level)
        except ImportError:
            # pythonjsonlogger not installed — fall back to text
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s %(name)s %(levelname)s %(message)s"
            )
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(name)s %(levelname)s %(message)s"
        )


_configure_logging()
logger = logging.getLogger("main")

scheduler = AsyncIOScheduler()


def _security_warnings() -> list[str]:
    warnings: list[str] = []
    secret = settings.SECRET_KEY or ""
    if len(secret) < 32:
        warnings.append("SECRET_KEY is shorter than 32 characters")
    if "changeme" in secret.lower():
        warnings.append("SECRET_KEY appears to use a default placeholder")
    if settings.ADMIN_PASSWORD and "changeme" in settings.ADMIN_PASSWORD.lower():
        warnings.append("ADMIN_PASSWORD appears to use a default placeholder")
    if any(origin.strip() == "*" for origin in settings.allowed_origins_list):
        warnings.append("ALLOWED_ORIGINS contains wildcard '*' which is unsafe for production")
    return warnings


async def _run_tracked_job(job_name: str, job_fn):
    started_at = datetime.utcnow()
    status = "ok"
    try:
        await job_fn()
    except Exception:
        status = "error"
        logger.exception("Scheduler job failed: %s", job_name)
        raise
    finally:
        metrics_store.record_scheduler_run(job_name, status, started_at, datetime.utcnow())


async def _job_hourly_agg():
    await _run_tracked_job("hourly_agg", aggregate_hourly)


async def _job_daily_agg():
    await _run_tracked_job("daily_agg", aggregate_daily)


async def _job_goal_check():
    await _run_tracked_job("goal_check", check_goals)


async def _job_peak_reminder():
    await _run_tracked_job("peak_reminder", send_peak_reminder)


async def _job_daily_report():
    await _run_tracked_job("daily_report", send_daily_report)


async def _job_decision_impact():
    await _run_tracked_job("decision_impact", calculate_decision_impacts)


async def _job_rankings():
    await _run_tracked_job("rankings", compute_rankings)


async def _job_weekly_email():
    await _run_tracked_job("weekly_email", send_weekly_reports)


async def _job_classify_personas():
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        summary = await classify_all_users(db)
        logger.info("Persona classification: %s", summary)


async def _job_analytics_evaluator():
    from app.scheduler import evaluate_analytics_thresholds
    await _run_tracked_job("analytics_eval", evaluate_analytics_thresholds)


async def _job_smart_device_check():
    """Run smart appliance scenario checks for all users every 2 hours."""
    from app.database import AsyncSessionLocal
    from app.notification_engine import NotificationEngine
    async with AsyncSessionLocal() as db:
        await NotificationEngine.check_device_scenario_notifications(db)


async def _job_notification_cleanup():
    """Daily TTL cleanup — delete notifications older than 90 days."""
    await _run_tracked_job("notification_cleanup", lambda: cleanup_old_notifications(retention_days=90))


async def _job_anomaly_scan():
    """Hourly scan: notify users of any device exceeding 3x its baseline."""
    await _run_tracked_job(
        "anomaly_scan",
        lambda: detect_and_notify_anomalies(threshold_factor=3.0, lookback_hours=2),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("🔋 WattWise Energy Monitoring Server starting...")

    # Initialise database tables
    await init_db()
    logger.info("✅ Database tables ready")

    # Start MQTT subscriber
    start_mqtt()
    logger.info("✅ MQTT subscriber started")

    sec_warnings = _security_warnings()
    if sec_warnings:
        if settings.STRICT_SECURITY:
            raise RuntimeError(
                "STRICT_SECURITY=true and insecure configuration detected: "
                + "; ".join(sec_warnings)
            )
        logger.warning("Security posture warnings detected:")
        for warning in sec_warnings:
            logger.warning("  - %s", warning)
    else:
        logger.info("✅ Security posture baseline checks passed")

    # Seed default personas if not already present
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await seed_default_personas(db)
    logger.info("✅ Default personas seeded")

    # Schedule recurring jobs
    scheduler.add_job(_job_hourly_agg,         "interval",   minutes=30,                  id="hourly_agg")
    scheduler.add_job(_job_daily_agg,          "cron",       hour=0,    minute=15,         id="daily_agg")
    scheduler.add_job(_job_analytics_evaluator,"cron",       hour=0,    minute=30,         id="analytics_eval")
    scheduler.add_job(_job_goal_check,         "interval",   hours=1,                     id="goal_check")
    scheduler.add_job(_job_peak_reminder,      "cron",       hour=15,   minute=45,         id="peak_reminder")
    scheduler.add_job(_job_daily_report,       "cron",       hour=7,    minute=0,          id="daily_report")
    scheduler.add_job(_job_decision_impact,    "interval",   hours=2,                     id="decision_impact")
    scheduler.add_job(_job_rankings,           "cron",       hour=1,    minute=30,         id="rankings")
    scheduler.add_job(_job_weekly_email,       "cron",       day_of_week="mon", hour=8,    minute=0,  id="weekly_email")
    scheduler.add_job(_job_classify_personas,  "cron",       day_of_week="sun", hour=2,    minute=0,  id="classify_personas")
    scheduler.add_job(_job_smart_device_check, "interval",   hours=2,                                  id="smart_device_check")
    scheduler.add_job(_job_notification_cleanup,"cron",       hour=3,    minute=0,          id="notification_cleanup")
    scheduler.add_job(_job_anomaly_scan,        "interval",   hours=1,                     id="anomaly_scan")
    scheduler.start()
    logger.info("✅ Scheduler started with 13 jobs")

    yield

    # Shutdown — wait=True ensures no job is left mid-execution (prevents data corruption)
    scheduler.shutdown(wait=True)
    stop_mqtt()
    logger.info("WattWise server shutdown complete")


app = FastAPI(
    title="WattWise Energy Monitoring API",
    description=(
        "Cloud-hosted energy monitoring platform for WattWise. "
        "Ingests smart plug telemetry, analyses usage patterns, "
        "tracks user decisions, and provides community rankings."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)


# ── JWT Auth Middleware ───────────────────────────────────────
PUBLIC_PATHS = {
    "/", "/health", "/health/dependencies", "/health/slo", "/metrics", "/docs", "/openapi.json", "/redoc",
    "/api/auth/signup", "/api/auth/login", "/api/auth/forgot-password",
    "/api/rankings/leaderboard",
}


@app.middleware("http")
async def request_metrics_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    start_ts = datetime.utcnow()

    try:
        response = await call_next(request)
    except Exception:
        metrics_store.record_request(500)
        logger.exception(
            "request_failed request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        return JSONResponse({"detail": "Internal server error", "request_id": request_id}, status_code=500)

    metrics_store.record_request(response.status_code)
    if request.url.path == "/api/readings/" and request.method == "POST" and response.status_code == 201:
        metrics_store.record_reading_ingested()

    duration_ms = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' wss: ws:; "
        "frame-ancestors 'none';"
    )
    logger.info(
        "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    Validate JWT on every protected route.
    Injects user_id and is_admin into request.state.
    """
    path = request.url.path

    # Skip auth for public paths
    if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        metrics_store.record_auth_failure()
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    token = auth_header.split(" ", 1)[1]

    # Check denylist (tokens invalidated by logout)
    from app.routers.auth import is_token_denied
    if is_token_denied(token):
        metrics_store.record_auth_failure()
        return JSONResponse({"detail": "Token has been invalidated"}, status_code=401)

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload["sub"])
        # Read is_admin from JWT claim — avoids extra DB query per request.
        # The claim is embedded at login time; re-login required to reflect changes.
        is_admin = bool(payload.get("is_admin", False))
    except JWTError:
        metrics_store.record_auth_failure()
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    request.state.user_id = user_id
    request.state.is_admin = is_admin
    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(readings.router)
app.include_router(notifications.router)
app.include_router(goals.router)
app.include_router(decisions.router)
app.include_router(analysis.router)
app.include_router(admin.router)
app.include_router(export.router)
app.include_router(backup.router)
app.include_router(advanced.router)
app.include_router(influx.router)
app.include_router(environment.router)
app.include_router(smart_notifications.router)


# ── Health ────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "WattWise Energy Monitoring API",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


@app.get("/health/dependencies", tags=["Health"])
async def health_dependencies():
    checks = {
        "database": False,
        "mqtt": is_mqtt_connected(),
        "influxdb": False,
    }

    # Check MySQL reachability
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
    except Exception:
        checks["database"] = False

    # Check InfluxDB reachability
    try:
        from influxdb import InfluxDBClient

        influx = InfluxDBClient(
            host=settings.INFLUX_HOST,
            port=settings.INFLUX_PORT,
            username=settings.INFLUX_USER,
            password=settings.INFLUX_PASS,
            database=settings.INFLUX_DB,
            timeout=3,
        )
        checks["influxdb"] = bool(influx.ping())
    except Exception:
        checks["influxdb"] = False

    overall_ok = all(checks.values())
    return {
        "status": "ok" if overall_ok else "degraded",
        "checks": checks,
    }


@app.get("/metrics", tags=["Health"])
async def metrics_snapshot():
    return metrics_store.snapshot()


@app.get("/health/slo", tags=["Health"])
async def health_slo():
    snapshot = metrics_store.snapshot()
    counters = snapshot.get("counters", {})

    total = counters.get("requests_total", 0)
    errors_5xx = counters.get("requests_5xx_total", 0)
    auth_failures = counters.get("auth_failures_total", 0)

    if total == 0:
        error_rate_pct = 0.0
        auth_failure_rate_pct = 0.0
    else:
        error_rate_pct = round((errors_5xx / total) * 100, 3)
        auth_failure_rate_pct = round((auth_failures / total) * 100, 3)

    slo = {
        "availability_target_pct": 99.0,
        "max_5xx_error_rate_pct": 1.0,
        "max_auth_failure_rate_pct": 30.0,
    }

    breaches = {
        "errors": error_rate_pct > slo["max_5xx_error_rate_pct"],
        "auth_failures": auth_failure_rate_pct > slo["max_auth_failure_rate_pct"],
    }

    return {
        "status": "breach" if any(breaches.values()) else "ok",
        "window": "process_lifetime",
        "rates": {
            "request_5xx_error_rate_pct": error_rate_pct,
            "auth_failure_rate_pct": auth_failure_rate_pct,
        },
        "targets": slo,
        "breaches": breaches,
    }
