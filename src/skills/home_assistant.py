import asyncio
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# Maps spoken names → HA entity IDs
DEVICE_ALIASES = {
    "exhaust fan":   "switch.tp_link_power_strip_503c_exhaust_fan",
    "fan":           "switch.tp_link_power_strip_503c_exhaust_fan",
    "workshop light": "switch.workshop_light_1",
    "light one":     "switch.workshop_light_1",
    "light 1":       "switch.workshop_light_1",
    "light two":     "switch.workshop_light_2",
    "light 2":       "switch.workshop_light_2",
    "workshop power": "switch.workshop_power",
    "power":         "switch.workshop_power",
}

# Friendly display names for responses
DEVICE_NAMES = {
    "switch.tp_link_power_strip_503c_exhaust_fan": "exhaust fan",
    "switch.workshop_light_1": "workshop light one",
    "switch.workshop_light_2": "workshop light two",
    "switch.workshop_power": "workshop power",
}


def _get_token() -> str:
    try:
        import config.secrets as _secrets
        return getattr(_secrets, "HA_TOKEN", "")
    except Exception:
        return ""


def _ha_post(path: str, token: str, body: dict = None) -> bool:
    """POST to HA REST API. Returns True on success."""
    from config.settings import HA_URL
    data = json.dumps(body or {}).encode()
    try:
        req = urllib.request.Request(
            f"{HA_URL}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        logger.warning(f"HA POST failed {path}: HTTP {e.code}")
        return False
    except Exception as e:
        logger.warning(f"HA POST failed {path}: {e}")
        return False


def _resolve_device(text: str) -> tuple[str | None, str | None]:
    """Return (entity_id, friendly_name) for the device mentioned in text, or (None, None)."""
    text_lower = text.lower()
    # Longest match first to avoid "fan" matching before "exhaust fan"
    for alias in sorted(DEVICE_ALIASES, key=len, reverse=True):
        if alias in text_lower:
            entity_id = DEVICE_ALIASES[alias]
            return entity_id, DEVICE_NAMES.get(entity_id, alias)
    return None, None


async def control_device(text: str) -> str:
    """
    Parse a 'turn on/off <device>' command and call the HA service.
    Returns a spoken confirmation string.
    """
    text_lower = text.lower()

    if "turn on" in text_lower:
        action = "turn_on"
        action_word = "Turning on"
    elif "turn off" in text_lower:
        action = "turn_off"
        action_word = "Turning off"
    else:
        return "I didn't catch whether to turn something on or off."

    entity_id, friendly_name = _resolve_device(text)
    if entity_id is None:
        return "I'm not sure which device you mean."

    token = _get_token()
    if not token:
        return "Home Assistant token is not configured."

    domain = entity_id.split(".")[0]
    success = await asyncio.to_thread(
        _ha_post, f"/api/services/{domain}/{action}", token, {"entity_id": entity_id}
    )

    if success:
        return f"{action_word} the {friendly_name}."
    else:
        return f"I couldn't reach Home Assistant to control the {friendly_name}."
