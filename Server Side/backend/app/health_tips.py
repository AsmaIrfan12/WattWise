"""
WattWise health suggestions
===========================
Every energy alert in WattWise is paired with a short health or wellbeing suggestion
for the appliance it is about. This is a signature feature of the original single-home
app (old/services/energy-calculator.js), where each notification is an energy message
that ends with a health tip. That file spells out the dryer's four notifications and
says the other appliances "follow the same structure"; the dryer's four are used here
word for word, and the other appliances are written in the same structure, based on
mainstream UK public-health guidance (NHS, Food Standards Agency).

Two kinds of tip:

  SCENARIO_HEALTH_TIPS  one tip per alert scenario (appliance + scenario name), shown
                        with that alert.
  GENERAL_HEALTH_TIPS   a few tips per appliance, shown on the device's panel and used
                        for alerts that do not come from a scenario (for example the
                        "unusual usage" alert).

The tips are wellbeing suggestions, not medical advice.
"""
from typing import Iterable, Optional

# Appliance keys that mean the same thing. The right-hand side is the canonical key.
_ALIASES = {
    "washing_machine": "washingmachine",
    "washer": "washingmachine",
    "coffee_machine": "coffeemachine",
    "air_fryer": "airfryer",
    "gaming_console": "xbox",
    "console": "xbox",
    "waterpurifier": "water_purifier",
    "tumble_dryer": "dryer",
    "television": "tv",
    "oven": "cooker",
    "hob": "cooker",
}


def canonical_appliance(appliance_key: Optional[str]) -> str:
    """The key the tip tables use for this appliance ("" when unknown)."""
    key = (appliance_key or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(key, key)


# ── Tips tied to an alert scenario ───────────────────────────────────────────
# Keys: canonical appliance -> scenario name (exactly as in appliance_scenarios.py).
SCENARIO_HEALTH_TIPS: dict[str, dict[str, str]] = {
    "dryer": {   # restored from the original app
        "High energy per cycle":
            "Line-drying clothes in fresh air naturally sanitizes them and is better for sensitive skin!",
        "Daily consumption high":
            "Fresh air drying reduces static and chemical exposure from dryer sheets.",
        "Humidity spike adjustment":
            "Lower humidity also reduces mold growth and improves respiratory health!",
        "Multiple cycles per day":
            "Fewer laundry sessions means less dust circulation in your home.",
    },
    "kettle": {
        "Excessive daily usage":
            "Aim for 6 to 8 cups of fluid a day, and try swapping some teas and coffees for water or caffeine-free drinks.",
        "High cycles — moderate use":
            "Staying hydrated helps your concentration and energy levels. Water and herbal teas count too.",
        "Cold weather energy increase":
            "A warm drink helps in cold weather. Keeping the rooms you use at 18°C or above protects your health in winter.",
        "Late night usage":
            "Caffeine late in the evening can disturb your sleep. Try a caffeine-free drink such as herbal tea before bed.",
    },
    "microwave": {
        "Extended continuous use":
            "When reheating, stir halfway through and check the food is steaming hot all the way through before eating.",
        "High daily energy":
            "Steaming vegetables in the microwave with a splash of water keeps more of their vitamins than boiling them.",
        "Peak time usage":
            "Let food stand for a minute after microwaving. It finishes heating evenly and avoids burns from hot spots.",
    },
    "washingmachine": {
        "High energy per wash":
            "A 30°C wash is fine for everyday clothes. Keep 60°C for towels and bedding, where it helps remove germs and dust mites.",
        "Multiple washes per day":
            "Leave the door and detergent drawer open between washes so mould does not build up inside the machine.",
        "High humidity — longer drying needed":
            "Drying washing indoors adds moisture to the air, which encourages damp and mould. Open a window or dry outside when you can.",
        "Peak tariff wash":
            "Hang washing out soon after the cycle ends. Damp laundry left in the drum starts to smell and can grow mildew.",
    },
    "dishwasher": {
        "Not full — wasteful cycle":
            "A dishwasher's hot cycle cleans more hygienically than washing up by hand, so waiting for a full load costs nothing in cleanliness.",
        "Multiple runs per day":
            "Clean the filter regularly and leave the door ajar after a cycle so the inside dries out and stays free of mould.",
        "Peak time run":
            "Put chopping boards and utensils used for raw meat through a hot cycle to help prevent food poisoning.",
    },
    "coffeemachine": {
        "Standby drain detected":
            "Empty the drip tray and used grounds every day. A warm, damp coffee machine is a common place for mould to grow.",
        "High daily usage":
            "Up to about 400 mg of caffeine a day, roughly four cups of coffee, is considered safe for most adults (200 mg in pregnancy).",
        "Keep-warm mode overuse":
            "Coffee kept on a hot plate turns bitter. Brew fresh or use a flask, and have your last coffee about six hours before bed.",
    },
    "airfryer": {
        "Extended session energy":
            "Air frying uses far less oil than deep frying, which cuts fat and calories. Shake the basket so food cooks evenly.",
        "Multiple sessions":
            "Cook chips and other starchy foods to a golden yellow, not dark brown. Lighter cooking produces less acrylamide.",
        "Peak time cooking":
            "Air-fried vegetables count towards your 5 A Day. Try carrots, peppers or broccoli alongside the main dish.",
    },
    "toaster": {
        "High daily cycles":
            "Toast bread to a golden yellow rather than dark brown. Lighter toast contains less acrylamide.",
        "Short use pattern":
            "Wholemeal or seeded bread has more fibre than white bread and keeps you fuller for longer.",
    },
    "cooker": {
        "Very high energy session":
            "Use the extractor fan or open a window while cooking. It clears steam and cooking fumes and keeps indoor air healthier.",
        "Extended cook time":
            "Batch cooking? Cool leftovers within one to two hours, keep them in the fridge and eat them within two days.",
        "Peak time cooking":
            "Lids on pans cook food faster and keep moisture out of the air, which helps prevent condensation and mould.",
    },
    "xbox": {
        "Extended gaming session":
            "Long sessions affect posture and eyes. Every 20 minutes look at something far away for 20 seconds, and stand up and stretch each hour.",
        "High temperature effect":
            "A hot, stuffy room is tiring. Open a window or take a break to cool down and have a drink of water.",
        "Standby power":
            "Switching the console off fully at night also removes the lights and alerts that can disturb your sleep.",
        "Late night gaming":
            "Screens late at night make it harder to fall asleep. Try to stop gaming about an hour before bed.",
    },
    "water_purifier": {
        "Abnormally high energy":
            "Change the filter on schedule. An overdue filter stops removing impurities properly and can harbour bacteria.",
        "Continuous operation":
            "Fresh filtered water makes it easier to drink enough. Aim for 6 to 8 cups of fluid a day.",
    },
}

# ── General tips per appliance ───────────────────────────────────────────────
GENERAL_HEALTH_TIPS: dict[str, list[str]] = {
    "dryer": [
        "Line-drying clothes in fresh air naturally sanitizes them and is better for sensitive skin!",
        "Fresh air drying reduces static and chemical exposure from dryer sheets.",
        "Clean the lint filter after every load. It keeps the dryer safe and reduces dust in your home.",
    ],
    "kettle": [
        "Aim for 6 to 8 cups of fluid a day. Water, lower-fat milk, tea and coffee all count.",
        "Let very hot drinks cool for a few minutes before drinking them.",
        "Swap caffeinated drinks for water or herbal tea in the evening to protect your sleep.",
    ],
    "microwave": [
        "When reheating, stir halfway through and check the food is steaming hot all the way through.",
        "Steaming vegetables in the microwave with a splash of water keeps more of their vitamins than boiling them.",
        "Only use containers marked microwave-safe, and loosen lids so steam can escape.",
    ],
    "washingmachine": [
        "A 30°C wash is fine for everyday clothes. Keep 60°C for towels and bedding, where it helps remove germs and dust mites.",
        "Leave the door and detergent drawer open between washes so mould does not build up inside the machine.",
        "Drying washing indoors adds moisture to the air. Open a window or dry outside when you can to avoid damp and mould.",
    ],
    "dishwasher": [
        "A dishwasher's hot cycle cleans more hygienically than washing up by hand.",
        "Clean the filter regularly and leave the door ajar after a cycle so the inside dries out and stays free of mould.",
        "Put chopping boards and utensils used for raw meat through a hot cycle to help prevent food poisoning.",
    ],
    "coffeemachine": [
        "Up to about 400 mg of caffeine a day, roughly four cups of coffee, is considered safe for most adults (200 mg in pregnancy).",
        "Empty the drip tray and used grounds every day so mould does not grow in the machine.",
        "Have your last coffee about six hours before bed for better sleep.",
    ],
    "airfryer": [
        "Air frying uses far less oil than deep frying, which cuts fat and calories.",
        "Cook chips and other starchy foods to a golden yellow, not dark brown. Lighter cooking produces less acrylamide.",
        "Air-fried vegetables count towards your 5 A Day.",
    ],
    "toaster": [
        "Toast bread to a golden yellow rather than dark brown. Lighter toast contains less acrylamide.",
        "Wholemeal or seeded bread has more fibre than white bread and keeps you fuller for longer.",
        "Empty the crumb tray regularly. Burnt crumbs make smoke and are a fire risk.",
    ],
    "cooker": [
        "Use the extractor fan or open a window while cooking to clear steam and cooking fumes.",
        "Cool leftovers within one to two hours, keep them in the fridge and eat them within two days.",
        "Lids on pans keep moisture out of the air, which helps prevent condensation and mould.",
    ],
    "xbox": [
        "Every 20 minutes look at something far away for 20 seconds, and stand up and stretch each hour.",
        "Screens late at night make it harder to fall asleep. Try to stop gaming about an hour before bed.",
        "Keep the room aired and have water to hand during long sessions.",
    ],
    "water_purifier": [
        "Aim for 6 to 8 cups of fluid a day. Fresh filtered water makes that easier.",
        "Change the filter on schedule so it keeps removing impurities properly.",
    ],
    "tv": [
        "Take a short break from the screen every hour to rest your eyes and move around.",
        "Turning the TV off about an hour before bed helps you wind down and sleep better.",
        "Sit at a comfortable distance with the room softly lit to reduce eye strain.",
    ],
}

# Used for appliance types with no tips of their own ("other", a new device type).
DEFAULT_HEALTH_TIPS: list[str] = [
    "Air your home for a few minutes each day. Fresh air reduces damp, mould and indoor pollutants.",
    "Keeping the rooms you use at 18°C or above in winter protects your health.",
    "Switch appliances off at the wall when you are not using them. It saves energy and lowers fire risk.",
]


# ── How a tip is written into the notification text ──────────────────────────
# In the original app the health tip is the last sentence of the notification itself:
#   "<energy advice> 💚 Health tip: <tip>"
# The dryer's other three notifications introduce the tip with their own emoji; those
# lead-ins are kept so the four original notifications read exactly as they did.
HEALTH_TIP_LABEL = "💚 Health tip:"
_SCENARIO_TIP_LEADS: dict[str, dict[str, str]] = {
    "dryer": {
        "Daily consumption high": "🌿",
        "Humidity spike adjustment": "🏠",
        "Multiple cycles per day": "🧺",
    },
}


def with_health_tip(energy_message: str, tip: Optional[str], lead: str = HEALTH_TIP_LABEL) -> str:
    """The full notification text: the energy advice followed by its health tip."""
    if not tip:
        return energy_message
    return f"{energy_message.rstrip()} {lead} {tip}"


def scenario_tip_lead(appliance_key: Optional[str], scenario: Optional[str]) -> str:
    return _SCENARIO_TIP_LEADS.get(canonical_appliance(appliance_key), {}).get(scenario or "", HEALTH_TIP_LABEL)


def scenario_health_tip(appliance_key: Optional[str], scenario: Optional[str]) -> Optional[str]:
    """The tip that belongs to one alert scenario, or None if there is none."""
    return SCENARIO_HEALTH_TIPS.get(canonical_appliance(appliance_key), {}).get(scenario or "")


def general_health_tips(appliance_key: Optional[str]) -> list[str]:
    """General tips for an appliance. Never empty: unknown types get the home tips."""
    return list(GENERAL_HEALTH_TIPS.get(canonical_appliance(appliance_key)) or DEFAULT_HEALTH_TIPS)


def pick_health_tip(appliance_key: Optional[str], seed: int = 0) -> str:
    """One general tip, rotated by `seed` (for example day of year + device id)."""
    tips = general_health_tips(appliance_key)
    return tips[seed % len(tips)]


def health_tips_for(appliance_key: Optional[str], alerts: Optional[Iterable[dict]] = None) -> list[str]:
    """
    Tips to show for a device: those of its triggered alerts first (most relevant now),
    then the general ones, without repeats.
    """
    ordered: list[str] = []
    for alert in alerts or []:
        tip = alert.get("health_tip") or scenario_health_tip(appliance_key, alert.get("scenario"))
        if tip and tip not in ordered:
            ordered.append(tip)
    for tip in general_health_tips(appliance_key):
        if tip not in ordered:
            ordered.append(tip)
    return ordered
