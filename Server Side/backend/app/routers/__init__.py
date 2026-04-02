"""WattWise API routers package."""
from app.routers import auth, devices, readings, notifications, goals, decisions, analysis, admin

__all__ = ["auth", "devices", "readings", "notifications", "goals", "decisions", "analysis", "admin"]
