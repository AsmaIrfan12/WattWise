"""
WattWise Appliance Scenarios Engine
=====================================
Ported from old/services/energy-calculator.js (Node.js).

Provides:
- Scenario definitions for 11 appliance types (dryer, kettle, microwave, etc.)
- Environmental correction factors (temperature, humidity, pressure)
- Alert generation based on usage data + environmental conditions
- Optimization payload for each device usage session
- Recommendation generation

Used by:
- smart_notifications.py router (on-demand smart alert generation)
- notification_engine.py (automated scenario-based push notifications)
- scheduler.py (periodic device health check job)
"""

import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("appliance_scenarios")


# ── UK Energy Rate Constants ────────────────────────────────────

UK_ENERGY_RATES = {
    "standard": settings.ENERGY_STANDARD_PRICE_PER_KWH,   # £0.27/kWh
    "peak": settings.ENERGY_PEAK_PRICE_PER_KWH,            # £0.32/kWh
    "off_peak": settings.ENERGY_OFFPEAK_PRICE_PER_KWH,     # £0.13/kWh
}


# ── Appliance Base Energy (kWh per typical cycle/session) ──────

APPLIANCE_BASE_ENERGY: dict[str, float] = {
    "dryer": 3.00,
    "kettle": 0.12,
    "microwave": 0.30,
    "coffeemachine": 0.10,
    "coffee_machine": 0.10,
    "airfryer": 1.20,
    "air_fryer": 1.20,
    "toaster": 0.08,
    "dishwasher": 1.20,
    "washingmachine": 0.90,
    "washing_machine": 0.90,
    "cooker": 0.25,
    "xbox": 0.15,
    "gaming_console": 0.15,
    "waterpurifier": 0.25,
    "water_purifier": 0.25,
}


# ── Scenario Definitions ────────────────────────────────────────
# Each scenario: { level, priority, scenario (str), condition (callable), message (callable) }
# condition(data) -> bool
# message(data)   -> str
# data keys: eaec, dailyEAEC, N, fT, fH, fP, temperature, humidity, pressure,
#            duration, shortUseCount, standbyTime, standbyPower,
#            avgPower, lateNightHours, isPeakTime, keepWarmTime

APPLIANCE_SCENARIOS: dict[str, list[dict]] = {

    # ── DRYER ──────────────────────────────────────────────────
    "dryer": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "High energy per cycle",
            "condition": lambda d: d["N"] > 0 and d["eaec"] > 4.5,
            "message": lambda d: (
                f"⚠️ Your dryer used {d['eaec']:.2f} kWh this cycle — that's higher than normal. "
                f"Try using a shorter or eco cycle to save energy. "
                f"💚 Health tip: Line-drying clothes in fresh air naturally sanitizes them!"
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "Daily consumption high",
            "condition": lambda d: d["N"] > 0 and d["dailyEAEC"] > 7,
            "message": lambda d: (
                f"💡 You've used the dryer {d['dailyEAEC']:.1f} kWh today. "
                f"Consider air drying some items to save money. 🌿 Fresh air drying reduces static!"
            ),
        },
        {
            "level": "🟦", "priority": "notice",
            "scenario": "Humidity spike adjustment",
            "condition": lambda d: d["N"] > 0 and d["fH"] > 1.15,
            "message": lambda d: (
                f"💧 High humidity is making your dryer work {round((d['fH'] - 1) * 100)}% harder. "
                f"Wait for a drier day or use a dehumidifier. 🏠 Lower humidity reduces mold growth!"
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Multiple cycles per day",
            "condition": lambda d: d["N"] > 2,
            "message": lambda d: (
                f"⚡ You've run the dryer {d['N']} times today. "
                f"Try combining your laundry loads to save energy. 🧺 Fewer sessions = less dust circulation."
            ),
        },
    ],

    # ── KETTLE ─────────────────────────────────────────────────
    "kettle": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Excessive daily usage",
            "condition": lambda d: d["N"] > 12,
            "message": lambda d: (
                f"☕ You've boiled the kettle {d['N']} times today — that's a lot! "
                f"Only boil the water you need and consider a flask to keep it hot."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "High cycles — moderate use",
            "condition": lambda d: 8 < d["N"] <= 12,
            "message": lambda d: (
                f"☕ {d['N']} kettle uses today. Overfilling wastes energy — boil only what you need."
            ),
        },
        {
            "level": "🟦", "priority": "notice",
            "scenario": "Cold weather energy increase",
            "condition": lambda d: d["fT"] > 1.1 and d["N"] > 0,
            "message": lambda d: (
                f"🌡️ Cold temperature (≈{d['temperature']:.0f}°C) is making your kettle use "
                f"{round((d['fT'] - 1) * 100)}% more energy per boil. A thermos flask could help!"
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Late night usage",
            "condition": lambda d: d.get("lateNightHours", 0) > 0,
            "message": lambda d: (
                "🌙 Late-night kettle use detected. Caffeine this late can affect sleep quality. "
                "Try herbal tea or warm water instead!"
            ),
        },
    ],

    # ── MICROWAVE ──────────────────────────────────────────────
    "microwave": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Extended continuous use",
            "condition": lambda d: d.get("duration", 0) > 30 and d["N"] > 0,
            "message": lambda d: (
                f"⚠️ Your microwave ran for {d['duration']:.0f} minutes. "
                f"Excessive use can affect food quality and wastes energy. Use oven for large meals."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "High daily energy",
            "condition": lambda d: d["N"] > 0 and d["dailyEAEC"] > 0.8,
            "message": lambda d: (
                f"💡 Your microwave used {d['dailyEAEC']:.2f} kWh today. "
                f"This is quite high — check if it's staying on unnecessarily."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Peak time usage",
            "condition": lambda d: d.get("isPeakTime", False) and d["N"] > 0,
            "message": lambda d: (
                f"⚡ Your microwave is running during peak hours (4–7 PM). "
                f"You're paying {settings.ENERGY_PEAK_PRICE_PER_KWH*100:.0f}p/kWh instead of "
                f"{settings.ENERGY_STANDARD_PRICE_PER_KWH*100:.0f}p/kWh."
            ),
        },
    ],

    # ── WASHING MACHINE ────────────────────────────────────────
    "washingmachine": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "High energy per wash",
            "condition": lambda d: d["N"] > 0 and d["eaec"] > 2.0,
            "message": lambda d: (
                f"🧺 Your washing machine used {d['eaec']:.2f} kWh this wash — much higher than average (0.9 kWh). "
                f"Try washing at 30°C instead of 60°C to save up to 40% energy."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "Multiple washes per day",
            "condition": lambda d: d["N"] > 2,
            "message": lambda d: (
                f"🧺 {d['N']} wash cycles today. Combining loads saves water, energy and extends machine life."
            ),
        },
        {
            "level": "🟦", "priority": "notice",
            "scenario": "High humidity — longer drying needed",
            "condition": lambda d: d["fH"] > 1.1 and d["N"] > 0,
            "message": lambda d: (
                f"💧 High humidity ({d['humidity']:.0f}%) means clothes will take longer to air dry. "
                f"Use a heated rack or ventilated room rather than the dryer."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Peak tariff wash",
            "condition": lambda d: d.get("isPeakTime", False) and d["N"] > 0,
            "message": lambda d: (
                "⏰ Washing during peak hours (4–7 PM) costs 19p/kWh more. "
                "Schedule your wash for after 7 PM or use a delay timer."
            ),
        },
    ],

    # ── DISHWASHER ─────────────────────────────────────────────
    "dishwasher": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Not full — wasteful cycle",
            "condition": lambda d: d["N"] > 0 and d["eaec"] > 2.5,
            "message": lambda d: (
                f"🍽️ Your dishwasher used {d['eaec']:.2f} kWh — above the 1.2 kWh average. "
                f"Always run with a full load and use eco mode."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "Multiple runs per day",
            "condition": lambda d: d["N"] > 1,
            "message": lambda d: (
                f"🍽️ {d['N']} dishwasher runs today. Running once a day with a full load is optimal."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Peak time run",
            "condition": lambda d: d.get("isPeakTime", False) and d["N"] > 0,
            "message": lambda d: (
                f"⏰ Dishwasher running during peak hours. Delay to after 7 PM to save up to "
                f"£{d['eaec'] * (settings.ENERGY_PEAK_PRICE_PER_KWH - settings.ENERGY_STANDARD_PRICE_PER_KWH):.2f} this run."
            ),
        },
    ],

    # ── COFFEE MACHINE ─────────────────────────────────────────
    "coffeemachine": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Standby drain detected",
            "condition": lambda d: d.get("standbyPower", 0) > 8 and d.get("standbyTime", 0) > 60,
            "message": lambda d: (
                f"☕ Your coffee machine has been in standby for {d['standbyTime']:.0f} minutes "
                f"using {d['standbyPower']:.0f}W. Turn it off at the wall to save energy."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "High daily usage",
            "condition": lambda d: d["N"] > 8,
            "message": lambda d: (
                f"☕ {d['N']} coffees brewed today! Your coffee machine used {d['dailyEAEC']:.2f} kWh. "
                f"Consider batch brewing to reduce energy."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Keep-warm mode overuse",
            "condition": lambda d: d.get("keepWarmTime", 0) > 30,
            "message": lambda d: (
                f"☕ Keep-warm mode was on for {d['keepWarmTime']:.0f} minutes today. "
                f"Use a thermal flask instead to save energy."
            ),
        },
    ],

    # ── AIR FRYER ──────────────────────────────────────────────
    "airfryer": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Extended session energy",
            "condition": lambda d: d["N"] > 0 and d["eaec"] > 2.0,
            "message": lambda d: (
                f"🍟 Your air fryer used {d['eaec']:.2f} kWh this session — above the 1.2 kWh average. "
                f"Preheat efficiently and batch cook to reduce usage."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "Multiple sessions",
            "condition": lambda d: d["N"] > 3,
            "message": lambda d: (
                f"🍟 {d['N']} air fryer sessions today. Batch cooking in fewer sessions saves energy."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Peak time cooking",
            "condition": lambda d: d.get("isPeakTime", False) and d["N"] > 0,
            "message": lambda d: (
                "⏰ Air fryer running during peak hours. "
                "Cooking before 4 PM or after 7 PM saves 19p/kWh."
            ),
        },
    ],

    # ── TOASTER ────────────────────────────────────────────────
    "toaster": [
        {
            "level": "🟧", "priority": "warning",
            "scenario": "High daily cycles",
            "condition": lambda d: d["N"] > 10,
            "message": lambda d: (
                f"🍞 Your toaster has run {d['N']} times today — quite a lot! "
                f"Consider toasting multiple slices at once."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Short use pattern",
            "condition": lambda d: d.get("shortUseCount", 0) > 5,
            "message": lambda d: (
                f"🍞 {d['shortUseCount']} very short toasting sessions detected. "
                f"Your toaster may be partially burning food — check the timer setting."
            ),
        },
    ],

    # ── COOKER ─────────────────────────────────────────────────
    "cooker": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Very high energy session",
            "condition": lambda d: d["N"] > 0 and d["eaec"] > 3.0,
            "message": lambda d: (
                f"🍳 Your cooker used {d['eaec']:.2f} kWh this session. "
                f"Using residual heat (turn off 10 mins early) can save 10% energy."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "Extended cook time",
            "condition": lambda d: d.get("duration", 0) > 90 and d["N"] > 0,
            "message": lambda d: (
                f"🍳 Extended cooking session of {d['duration']:.0f} minutes detected. "
                f"A slow cooker uses 75% less energy for long recipes."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Peak time cooking",
            "condition": lambda d: d.get("isPeakTime", False) and d["N"] > 0,
            "message": lambda d: (
                "⏰ Cooking during peak hours. Try meal prepping before 4 PM or after 7 PM."
            ),
        },
    ],

    # ── GAMING CONSOLE (XBOX) ──────────────────────────────────
    "xbox": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Extended gaming session",
            "condition": lambda d: d.get("duration", 0) > 240 and d["N"] > 0,
            "message": lambda d: (
                f"🎮 Your console ran for {d['duration']:.0f} minutes today. "
                f"Extended gaming sessions also affect posture and eye health. Take regular breaks!"
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "High temperature effect",
            "condition": lambda d: d["fT"] > 1.08 and d["N"] > 0,
            "message": lambda d: (
                f"🌡️ High room temperature ({d['temperature']:.0f}°C) is causing your console to run "
                f"hotter and use {round((d['fT'] - 1) * 100)}% more energy for cooling. Improve ventilation!"
            ),
        },
        {
            "level": "🟦", "priority": "notice",
            "scenario": "Standby power",
            "condition": lambda d: d.get("standbyPower", 0) > 5 and d.get("standbyTime", 0) > 120,
            "message": lambda d: (
                f"🎮 Console on standby for {d['standbyTime']:.0f} minutes using {d['standbyPower']:.0f}W. "
                f"Enable power-saving mode or turn off when not in use."
            ),
        },
        {
            "level": "🟨", "priority": "caution",
            "scenario": "Late night gaming",
            "condition": lambda d: d.get("lateNightHours", 0) > 1,
            "message": lambda d: (
                "🌙 Late-night gaming detected. Blue light exposure can disrupt sleep. "
                "Try setting a console shut-off timer."
            ),
        },
    ],

    # ── WATER PURIFIER ─────────────────────────────────────────
    "water_purifier": [
        {
            "level": "🟥", "priority": "critical",
            "scenario": "Abnormally high energy",
            "condition": lambda d: d["N"] > 0 and d["eaec"] > 1.0,
            "message": lambda d: (
                f"💧 Your water purifier used {d['eaec']:.2f} kWh — much higher than normal (0.25 kWh). "
                f"The filter may be clogged and needs replacing."
            ),
        },
        {
            "level": "🟧", "priority": "warning",
            "scenario": "Continuous operation",
            "condition": lambda d: d.get("duration", 0) > 120 and d["N"] > 0,
            "message": lambda d: (
                f"💧 Water purifier running continuously for {d['duration']:.0f} minutes. "
                f"Check for leaks or a stuck valve."
            ),
        },
    ],
}

# ── Aliases ─────────────────────────────────────────────────────
APPLIANCE_SCENARIOS["washing_machine"] = APPLIANCE_SCENARIOS["washingmachine"]
APPLIANCE_SCENARIOS["coffee_machine"] = APPLIANCE_SCENARIOS["coffeemachine"]
APPLIANCE_SCENARIOS["air_fryer"] = APPLIANCE_SCENARIOS["airfryer"]
APPLIANCE_SCENARIOS["gaming_console"] = APPLIANCE_SCENARIOS["xbox"]
APPLIANCE_SCENARIOS["waterpurifier"] = APPLIANCE_SCENARIOS["water_purifier"]


# ── Environmental Factor Functions ──────────────────────────────

def calculate_temperature_factor(temperature: float, appliance_key: str) -> float:
    """
    Return a multiplier for energy usage based on ambient temperature.
    Cold = some appliances work harder. Hot = consoles overheat.
    """
    key = appliance_key.lower().replace("_", "")
    if key == "kettle":
        if temperature < 10:  return 1.15
        if temperature < 15:  return 1.10
        if temperature > 25:  return 0.95
        return 1.0
    elif key == "dryer":
        if temperature < 15:  return 1.08
        if temperature < 18:  return 1.05
        return 1.0
    elif key in ("xbox", "gamingconsole"):
        if temperature > 28:  return 1.10
        if temperature > 25:  return 1.05
        return 1.0
    elif key == "washingmachine":
        if temperature < 10:  return 1.05
        return 1.0
    return 1.0


def calculate_humidity_factor(humidity: float, appliance_key: str) -> float:
    """
    Return a multiplier for energy usage based on relative humidity.
    High humidity = dryer/washer work harder.
    """
    key = appliance_key.lower().replace("_", "")
    if key in ("dryer", "washingmachine"):
        if humidity > 80:  return 1.20
        if humidity > 70:  return 1.10
        if humidity > 60:  return 1.05
        return 1.0
    return 1.0


def calculate_pressure_factor(pressure: float) -> float:
    """
    Return a multiplier for energy usage based on atmospheric pressure.
    Low pressure → slight efficiency drop for heating appliances.
    """
    if pressure < 990:  return 1.03
    if pressure < 1000: return 1.01
    return 1.0


# ── Core Scenario Engine ─────────────────────────────────────────

def generate_alerts(appliance_key: str, data: dict) -> list[dict]:
    """
    Evaluate all scenarios for the given appliance and return triggered alerts.
    data must contain usage statistics (N, eaec, dailyEAEC, fT, fH, fP, etc.)
    """
    scenarios = APPLIANCE_SCENARIOS.get(appliance_key)
    if not scenarios:
        logger.debug(f"No scenarios for appliance: {appliance_key}")
        return []

    alerts = []
    for scenario in scenarios:
        try:
            if scenario["condition"](data):
                msg = scenario["message"]
                alerts.append({
                    "level": scenario["level"],
                    "priority": scenario["priority"],
                    "scenario": scenario["scenario"],
                    "message": msg(data) if callable(msg) else msg,
                })
        except Exception as e:
            logger.warning(f"Scenario eval error [{appliance_key}/{scenario['scenario']}]: {e}")
    return alerts


def calculate_potential_savings(alerts: list[dict], efficiency_loss: float) -> float:
    """Estimate % potential savings from alerts and efficiency loss (capped at 60%)."""
    savings = abs(efficiency_loss)
    for alert in alerts:
        priority = alert.get("priority", "")
        if priority == "critical":   savings += 20
        elif priority == "warning":  savings += 10
        elif priority == "caution":  savings += 5
        elif priority == "notice":   savings += 2
    return min(savings, 60.0)


def generate_recommendations(
    appliance_key: str,
    temperature: float,
    humidity: float,
    alerts: list[dict],
) -> list[str]:
    """Generate actionable text recommendations based on triggered alerts."""
    recs = []
    for alert in alerts:
        priority = alert.get("priority", "")
        if priority in ("critical", "warning"):
            recs.append(f"💡 {alert['message']}")
    if not recs:
        recs.append(f"✅ Your {appliance_key.replace('_', ' ')} usage looks efficient — keep it up!")
    return recs[:5]  # Max 5 recommendations


def calculate_optimization(
    appliance_key: str,
    temperature: float,
    humidity: float,
    pressure: float,
    usage_data: Optional[dict] = None,
) -> dict:
    """
    Full optimization payload for a device usage session.
    Combines environmental factors + scenario evaluation + savings estimate.

    Args:
        appliance_key: normalised appliance key (e.g. "kettle", "washing_machine")
        temperature: ambient temperature in °C
        humidity: relative humidity in %
        pressure: atmospheric pressure in hPa
        usage_data: dict with keys: eaec, dailyEAEC, N, duration, shortUseCount,
                    standbyTime, standbyPower, avgPower, lateNightHours, isPeakTime, keepWarmTime

    Returns:
        Full optimization dict with conditions, factors, alerts, recommendations, savings
    """
    usage_data = usage_data or {}
    base_energy = APPLIANCE_BASE_ENERGY.get(appliance_key, 0.5)

    # Environmental correction factors
    fT = calculate_temperature_factor(temperature, appliance_key)
    fH = calculate_humidity_factor(humidity, appliance_key)
    fP = calculate_pressure_factor(pressure)

    adjusted_energy = base_energy * fT * fH * fP
    efficiency_loss = (1 - base_energy / adjusted_energy) * 100 if adjusted_energy > 0 else 0

    # Normalise data — ensure all scenario condition keys exist
    data = {
        "temperature": temperature,
        "humidity": humidity,
        "pressure": pressure,
        "fT": fT,
        "fH": fH,
        "fP": fP,
        "eaec": usage_data.get("eaec", adjusted_energy),
        "dailyEAEC": usage_data.get("dailyEAEC", 0),
        "N": usage_data.get("N", 0),
        "duration": usage_data.get("duration", 0),
        "shortUseCount": usage_data.get("shortUseCount", 0),
        "standbyTime": usage_data.get("standbyTime", 0),
        "standbyPower": usage_data.get("standbyPower", 0),
        "avgPower": usage_data.get("avgPower", 0),
        "lateNightHours": usage_data.get("lateNightHours", 0),
        "isPeakTime": usage_data.get("isPeakTime", settings.is_peak_time()),
        "keepWarmTime": usage_data.get("keepWarmTime", 0),
        **usage_data,
    }

    alerts = generate_alerts(appliance_key, data)
    potential_savings = calculate_potential_savings(alerts, efficiency_loss)
    recommendations = generate_recommendations(appliance_key, temperature, humidity, alerts)

    return {
        "appliance_key": appliance_key,
        "conditions": {
            "temperature": round(temperature, 1),
            "humidity": round(humidity),
            "pressure": round(pressure),
        },
        "factors": {
            "fT": round(fT, 3),
            "fH": round(fH, 3),
            "fP": round(fP, 3),
        },
        "base_energy_kwh": round(base_energy, 3),
        "adjusted_energy_kwh": round(adjusted_energy, 3),
        "efficiency_loss_pct": round(abs(efficiency_loss), 1),
        "efficiency_score": round(max(0, 100 - abs(efficiency_loss)), 1),
        "alerts": alerts,
        "recommendations": recommendations,
        "potential_savings_pct": round(potential_savings, 1),
        "usage_data": {
            "N": data["N"],
            "eaec": round(data["eaec"], 3),
            "dailyEAEC": round(data["dailyEAEC"], 3),
            "duration_min": round(data["duration"], 1),
            "standby_time_min": round(data["standbyTime"], 1),
            "is_peak_time": data["isPeakTime"],
        },
    }
