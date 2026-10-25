"""Validated Home Assistant automation actions."""

from __future__ import annotations

import math

try:
    from homeassistant.core import probatio as vol
except ImportError:  # Home Assistant 2026.7 uses voluptuous.
    import voluptuous as vol  # type: ignore[no-redef]

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PRESETS
from .models import RECIPIENT, validate_config


def finite(value):
    try:
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError
        return float(value)
    except (TypeError, ValueError) as error:
        raise vol.Invalid("Expected a finite number") from error


def recipient(value):
    if not isinstance(value, str) or not RECIPIENT.fullmatch(value):
        raise vol.Invalid("Expected notify.mobile_app_* action")
    return value


def validated(value):
    try:
        return validate_config(value)
    except (ValueError, TypeError) as error:
        raise vol.Invalid(str(error)) from error


FIELDS = {
    vol.Required("activity_id"): vol.All(cv.string, vol.Length(min=1, max=256)),
    vol.Optional("title"): vol.All(cv.string, vol.Length(max=200)),
    vol.Optional("message"): vol.All(cv.string, vol.Length(max=1000)),
    vol.Optional("preset"): vol.In(PRESETS),
    vol.Optional("recipients"): vol.All(cv.ensure_list, [recipient], vol.Length(min=1)),
    vol.Optional("progress"): finite,
    vol.Optional("progress_min"): finite,
    vol.Optional("progress_max"): finite,
    vol.Optional("step_total"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10000)),
    vol.Optional("remaining_seconds"): vol.All(finite, vol.Range(min=0, max=86400 * 30)),
    vol.Optional("when"): vol.All(finite, vol.Range(min=1)),
    vol.Optional("critical_text"): vol.All(cv.string, vol.Length(max=100)),
    vol.Optional("silent"): cv.boolean,
    vol.Optional("alert_once"): cv.boolean,
    vol.Optional("icon"): cv.string,
    vol.Optional("accent_color"): cv.string,
    vol.Optional("text_color"): cv.string,
    vol.Optional("background_color"): cv.string,
    vol.Optional("progress_color"): cv.string,
    vol.Optional("progress_bar_direction"): vol.In(("increasing", "decreasing")),
    vol.Optional("severity"): vol.In(("info", "warning", "critical")),
    vol.Optional("relevance_score"): vol.All(finite, vol.Range(min=0, max=1)),
    vol.Optional("url"): cv.string,
    vol.Optional("min_update_interval"): vol.All(finite, vol.Range(min=0, max=86400)),
    vol.Optional("debounce_seconds"): vol.All(finite, vol.Range(min=0, max=60)),
    vol.Optional("change_threshold"): vol.All(finite, vol.Range(min=0, max=100)),
    vol.Optional("completion_delay"): vol.All(finite, vol.Range(min=0, max=14400)),
    vol.Optional("completion_behavior"): vol.In(("dismiss", "keep")),
    vol.Optional("finish_at_eta"): cv.boolean,
    vol.Optional("thresholds"): [dict],
}
START_SCHEMA = vol.All(vol.Schema(FIELDS), validated)
UPDATE_SCHEMA = vol.Schema(FIELDS)  # Validate cross-field ranges after merging the running settings.
TEST_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("activity_id", default="home_island_test"): FIELDS[vol.Required("activity_id")],
            **{key: value for key, value in FIELDS.items() if key != vol.Required("activity_id")},
        }
    ),
    validated,
)
END_SCHEMA = vol.Schema(
    {
        vol.Required("activity_id"): vol.All(cv.string, vol.Length(min=1, max=256)),
        vol.Optional("immediate", default=True): cv.boolean,
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register singleton actions once, routing to its live manager."""
    if hass.services.has_service(DOMAIN, "start"):
        return

    async def handle(call: ServiceCall) -> None:
        managers = hass.data.get(DOMAIN, {})
        if not managers:
            raise ServiceValidationError("Configure Home Island first")
        await next(iter(managers.values())).async_manual(call.service, dict(call.data))

    for action, schema in (
        ("start", START_SCHEMA),
        ("update", UPDATE_SCHEMA),
        ("end", END_SCHEMA),
        ("test", TEST_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, action, handle, schema=schema)
