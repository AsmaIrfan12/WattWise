"""
WattWise Energy Analysis Engine
================================
Core analytical service for:
- Device usage pattern detection (on/off cycles, active time)
- Anomaly detection (spikes, standby waste, appliance left on)
- UK tariff-aware cost calculations
- Environmental factor adjustments (temperature, humidity)
- Efficiency scoring (0-100)
- Goal progress evaluation
- Recommendation generation
"""

import logging
from datetime import datetime, date
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import EnergyReading

logger = logging.getLogger("energy_analysis")

# ── Appliance Baseline Profiles ───────────────────────────────
# Expected kWh per usage cycle (from energy-calculator.js)
APPLIANCE_BASE_ENERGY = {
    "kettle": 0.12,
    "microwave": 0.30,
    "dishwasher": 1.20,
    "washing_machine": 0.90,
    "washingmachine": 0.90,
    "dryer": 3.00,
    "toaster": 0.08,
    "coffeemachine": 0.10,
    "airfryer": 1.20,
    "cooker": 0.25,
    "xbox": 0.15,
    "gaming_console": 0.15,
    "water_purifier": 0.25,
}

# Standby detection threshold (Watts)
STANDBY_THRESHOLD_W = settings.ENERGY_DEVICE_STANDBY_WATTS

# "Active" threshold — above this = device is ON
ACTIVE_THRESHOLD_W = 10.0


class EnergyAnalysisEngine:
    """Stateless analysis engine — all methods are static."""

    # ── Usage Pattern Analysis ────────────────────────────────

    @staticmethod
    def detect_usage_cycles(readings: list[dict]) -> dict:
        """
        Analyse a sequence of power readings to detect on/off cycles.
        Returns usage statistics including cycle count, active minutes,
        peak power, and estimated energy consumed.
        """
        if not readings:
            return {"cycles": 0, "active_minutes": 0, "peak_watts": 0,
                    "avg_watts": 0, "total_kwh": 0, "standby_kwh": 0}

        was_active = False
        cycles = 0
        active_minutes = 0
        standby_wh = 0
        total_wh = 0
        peak_watts = 0

        for i in range(1, len(readings)):
            prev = readings[i - 1]
            curr = readings[i]

            power = curr.get("power_watts", 0)
            prev_power = prev.get("power_watts", 0)

            # Time delta in hours
            dt_hours = (curr["recorded_at"] - prev["recorded_at"]).total_seconds() / 3600
            if dt_hours > 1.0:
                was_active = False
                continue  # Skip gaps > 1 hour

            avg_power = (power + prev_power) / 2
            wh = avg_power * dt_hours
            total_wh += wh

            if avg_power >= ACTIVE_THRESHOLD_W:
                active_minutes += dt_hours * 60
                peak_watts = max(peak_watts, power)
                if not was_active:
                    cycles += 1
                    was_active = True
            elif avg_power >= STANDBY_THRESHOLD_W:
                standby_wh += wh
                was_active = False
            else:
                was_active = False

        total_kwh = total_wh / 1000.0
        standby_kwh = standby_wh / 1000.0
        avg_watts = (sum(r.get("power_watts", 0) for r in readings) / len(readings)) if readings else 0

        return {
            "cycles": cycles,
            "active_minutes": round(active_minutes),
            "peak_watts": round(peak_watts, 1),
            "avg_watts": round(avg_watts, 1),
            "total_kwh": round(total_kwh, 4),
            "standby_kwh": round(standby_kwh, 4),
        }

    @staticmethod
    def detect_anomalies(
        current_usage: dict,
        historical_avg: dict,
        appliance_key: str,
        conditions: Optional[dict] = None
    ) -> list[dict]:
        """
        Detect unusual energy consumption patterns.
        Returns list of anomaly dicts with level, type, and message.
        """
        anomalies = []
        base_energy = APPLIANCE_BASE_ENERGY.get(appliance_key, 0.5)

        # Spike detection: current > 2× historical average
        if historical_avg.get("avg_kwh_per_cycle", 0) > 0:
            spike_ratio = current_usage.get("total_kwh", 0) / historical_avg["avg_kwh_per_cycle"]
            if spike_ratio > settings.ENERGY_USAGE_SPIKE_MULTIPLIER * 1.5:
                anomalies.append({
                    "level": "CRITICAL",
                    "type": "CONSUMPTION_SPIKE",
                    "message": f"⚠️ {appliance_key} energy usage is {spike_ratio:.1f}× higher than your normal. Check the device!",
                    "value": spike_ratio
                })
            elif spike_ratio > settings.ENERGY_USAGE_SPIKE_MULTIPLIER:
                anomalies.append({
                    "level": "WARNING",
                    "type": "HIGH_USAGE",
                    "message": f"💡 Your {appliance_key} used {current_usage.get('total_kwh', 0):.3f} kWh — above your average.",
                    "value": spike_ratio
                })

        # Left on standby too long
        if current_usage.get("standby_kwh", 0) > 0.05:
            anomalies.append({
                "level": "INFO",
                "type": "STANDBY_WASTE",
                "message": f"🔌 Your {appliance_key} has been in standby mode and has used {current_usage['standby_kwh']:.3f} kWh. Turn it off completely to save money.",
                "value": current_usage["standby_kwh"]
            })

        # Excessive cycles per day
        daily_cycles = current_usage.get("cycles", 0)
        if appliance_key == "kettle" and daily_cycles > 8:
            anomalies.append({
                "level": "INFO",
                "type": "EXCESSIVE_CYCLES",
                "message": f"☕ You've boiled the kettle {daily_cycles} times today. Only boil the water you need!",
                "value": daily_cycles
            })

        # Peak time usage
        if conditions and conditions.get("is_peak_time") and current_usage.get("total_kwh", 0) > 0.1:
            anomalies.append({
                "level": "WARNING",
                "type": "PEAK_TARIFF",
                "message": f"⚡ Your {appliance_key} is running during peak hours (4–7 PM) when electricity is 19p/kWh more expensive. Can it wait?",
                "value": settings.ENERGY_PEAK_PRICE_PER_KWH
            })

        return anomalies

    # ── Cost Calculations ─────────────────────────────────────

    @staticmethod
    def calculate_cost(kwh: float, tariff: Optional[float] = None) -> float:
        """Calculate cost in GBP for given kWh at current or specified tariff."""
        rate = tariff or settings.get_current_tariff()
        return round(kwh * rate, 4)

    @staticmethod
    def calculate_daily_cost(daily_kwh: float) -> float:
        """Estimate daily cost using blended tariff (weighted average UK)."""
        # Peak hours: 4–7 PM = 3 hours (12.5% of day)
        # Off-peak: midnight–7 AM = 7 hours (29.2% of day)
        # Standard: remaining 58.3%
        blended = (
            settings.ENERGY_PEAK_PRICE_PER_KWH * 0.125 +
            settings.ENERGY_OFFPEAK_PRICE_PER_KWH * 0.292 +
            settings.ENERGY_STANDARD_PRICE_PER_KWH * 0.583
        )
        return round(daily_kwh * blended, 4)

    # ── Efficiency Scoring ────────────────────────────────────

    @staticmethod
    def calculate_efficiency_score(
        appliance_key: str,
        total_kwh: float,
        cycles: int,
        active_minutes: int,
        goal_kwh: Optional[float] = None,
        temperature: float = 20.0,
        humidity: float = 50.0,
    ) -> float:
        """
        Calculate device efficiency score (0-100).
        Higher = more efficient usage.
        """
        base_energy = APPLIANCE_BASE_ENERGY.get(appliance_key, 0.5)
        score = 100.0

        # Penalty: Energy used vs baseline per cycle
        if cycles > 0:
            kwh_per_cycle = total_kwh / cycles
            if kwh_per_cycle > base_energy * 1.5:
                score -= min(30, (kwh_per_cycle / base_energy - 1) * 30)

        # Penalty: Not meeting goal
        if goal_kwh and total_kwh > 0:
            goal_ratio = total_kwh / goal_kwh
            if goal_ratio > 1.0:
                score -= min(30, (goal_ratio - 1) * 40)

        # Bonus: Short, efficient cycles (< 5 min average for kettle/toaster)
        short_appliances = ["kettle", "toaster", "microwave"]
        if appliance_key in short_appliances and cycles > 0:
            avg_min_per_cycle = active_minutes / cycles
            if avg_min_per_cycle < 3:
                score += 5

        # Temperature factor (cold weather = more energy needed)
        if temperature < 15:
            score = min(100, score + 3)  # Give slight benefit of doubt in cold

        return max(0.0, min(100.0, round(score, 1)))

    # ── Goal Progress ─────────────────────────────────────────

    @staticmethod
    def evaluate_goal_progress(
        goal_type: str,
        target_kwh: float,
        current_kwh: float,
        start_date: date,
        end_date: Optional[date] = None,
        today: Optional[date] = None
    ) -> dict:
        """Calculate progress against an energy goal."""
        today = today or date.today()
        pct = (current_kwh / target_kwh * 100) if target_kwh > 0 else 0

        # Days remaining
        if end_date:
            days_remaining = (end_date - today).days
        elif goal_type == "daily":
            days_remaining = 0
        elif goal_type == "weekly":
            days_remaining = 6 - (today - start_date).days
        elif goal_type == "monthly":
            import calendar
            _, last_day = calendar.monthrange(today.year, today.month)
            days_remaining = last_day - today.day
        else:
            days_remaining = None

        # Project if will breach goal
        days_elapsed = (today - start_date).days + 1
        daily_avg = current_kwh / days_elapsed if days_elapsed > 0 else 0
        projected = None
        if goal_type in ("weekly", "monthly") and days_remaining is not None:
            projected = current_kwh + daily_avg * days_remaining

        on_track = pct <= 100 and (projected is None or projected <= target_kwh)

        return {
            "target_kwh": target_kwh,
            "current_kwh": round(current_kwh, 3),
            "percentage_used": round(pct, 1),
            "days_remaining": days_remaining,
            "on_track": on_track,
            "projected_kwh": round(projected, 3) if projected else None,
            "current_cost_gbp": EnergyAnalysisEngine.calculate_daily_cost(current_kwh),
        }

    # ── Recommendations ───────────────────────────────────────

    @staticmethod
    def generate_recommendations(
        appliance_key: str,
        anomalies: list[dict],
        usage_stats: dict,
        conditions: Optional[dict] = None
    ) -> list[dict]:
        """Generate human-readable energy-saving recommendations."""
        recs = []

        if anomalies:
            for a in anomalies[:3]:  # Top 3 anomalies
                if a["type"] == "STANDBY_WASTE":
                    recs.append({
                        "priority": "medium",
                        "title": "Eliminate Standby Waste",
                        "message": f"Turning off {appliance_key} fully (not standby) could save ~£{a['value'] * 0.27 * 365:.2f}/year.",
                        "potential_saving_gbp_year": round(a["value"] * 0.27 * 365, 2)
                    })
                elif a["type"] == "PEAK_TARIFF":
                    recs.append({
                        "priority": "high",
                        "title": "Shift Usage Away from Peak Hours",
                        "message": f"Running {appliance_key} after 7 PM instead of 4–7 PM saves ~19p/kWh.",
                        "potential_saving_gbp_year": None
                    })
                elif a["type"] == "HIGH_USAGE":
                    recs.append({
                        "priority": "high",
                        "title": "Review Usage Habits",
                        "message": f"Your {appliance_key} is consuming more than usual. Check if it needs maintenance.",
                        "potential_saving_gbp_year": None
                    })

        if not recs:
            recs.append({
                "priority": "low",
                "title": "Keep It Up!",
                "message": f"Your {appliance_key} usage looks efficient. Keep monitoring to stay on track.",
                "potential_saving_gbp_year": None
            })

        return recs

    # ── DB Helpers ────────────────────────────────────────────

    @staticmethod
    async def get_device_readings_today(db: AsyncSession, device_id: int) -> list:
        """Fetch today's raw readings from MySQL."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(EnergyReading)
            .where(EnergyReading.device_id == device_id, EnergyReading.recorded_at >= today_start)
            .order_by(EnergyReading.recorded_at.asc())
        )
        rows = result.scalars().all()
        return [{"recorded_at": r.recorded_at, "power_watts": r.power_watts, "energy_kwh": r.energy_kwh} for r in rows]

    @staticmethod
    async def get_device_readings_range(db: AsyncSession, device_id: int, start: datetime, end: datetime) -> list:
        """Fetch readings for a specific time range."""
        result = await db.execute(
            select(EnergyReading)
            .where(EnergyReading.device_id == device_id, EnergyReading.recorded_at.between(start, end))
            .order_by(EnergyReading.recorded_at.asc())
        )
        rows = result.scalars().all()
        return [{"recorded_at": r.recorded_at, "power_watts": r.power_watts, "energy_kwh": r.energy_kwh} for r in rows]
