"""Home Island setup and activity editing through Home Assistant's UI."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

try:
    from homeassistant.core import probatio as vol
except ImportError:  # Home Assistant 2026.7–2026.9
    import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import DOMAIN
from .models import number, validate_config

PRESETS = ["generic", "countdown", "gauge", "alert", "steps"]
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
RECIPIENT_RE = re.compile(r"^notify\.mobile_app_[a-z0-9_]+$")

DOMAIN_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "binary_sensor": ("on", "off", "mdi:toggle-switch"),
    "switch": ("on", "off", "mdi:toggle-switch"),
    "vacuum": ("cleaning", "docked,idle", "mdi:robot-vacuum"),
    "timer": ("active", "idle", "mdi:timer-outline"),
    "climate": ("heat,cool", "off", "mdi:thermostat"),
    "media_player": ("playing", "idle,off", "mdi:play-circle"),
    "cover": ("opening,closing", "open,closed", "mdi:window-shutter"),
    "lock": ("unlocked", "locked", "mdi:lock"),
}


def recipient_options(hass: HomeAssistant, saved: list[str] | None = None) -> list[dict[str, str]]:
    """List actual mobile notify actions, identifying registered iOS devices.

    A service can be renamed independently of its registration. Unmatched mobile
    actions therefore remain selectable with an explicit unverified label.
    Known Android registrations are excluded.
    """
    known: dict[str, tuple[str, bool]] = {}
    for entry in hass.config_entries.async_entries("mobile_app"):
        os_name = str(entry.data.get("os_name", "")).lower()
        device_name = str(entry.data.get("device_name", entry.title))
        if os_name:
            known[f"notify.mobile_app_{slugify(device_name)}"] = (
                device_name,
                os_name in {"ios", "ipados", "iphone os"},
            )
    available = {
        f"notify.{name}"
        for name in hass.services.async_services().get("notify", {})
        if name.startswith("mobile_app_")
    }
    result = []
    for service in sorted(available | set(saved or [])):
        device = known.get(service)
        if device and not device[1]:
            continue
        if service not in available:
            label = f"{service} (currently unavailable)"
        elif device:
            label = f"{device[0]} — {service}"
        else:
            label = f"{service} (verify this is your iOS device)"
        result.append({"value": service, "label": label})
    return result


def _recipient_schema(hass: HomeAssistant, selected: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("recipients", default=selected): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=recipient_options(hass, selected),
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _valid_recipients(hass: HomeAssistant, values: Any) -> bool:
    allowed = {item["value"] for item in recipient_options(hass)}
    return (
        bool(values)
        and isinstance(values, list)
        and all(
            isinstance(value, str)
            and RECIPIENT_RE.fullmatch(value)
            and value in allowed
            and hass.services.has_service("notify", value.removeprefix("notify."))
            for value in values
        )
    )


def _text(*, multiline: bool = False) -> selector.TextSelector:
    return selector.TextSelector(selector.TextSelectorConfig(multiline=multiline))


def _number(minimum: float, maximum: float, step: float = 1) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
        )
    )


def _states(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


class HomeIslandConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a single Home Island manager."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        self._async_abort_entries_match()
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            if _valid_recipients(self.hass, user_input.get("recipients")):
                return self.async_create_entry(
                    title="Home Island",
                    data={"recipients": list(dict.fromkeys(user_input["recipients"]))},
                )
            errors["base"] = "invalid_recipients"
        elif not recipient_options(self.hass):
            errors["base"] = "no_mobile_devices"
        return self.async_show_form(
            step_id="user", data_schema=_recipient_schema(self.hass, []), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HomeIslandOptionsFlow()


class HomeIslandOptionsFlow(config_entries.OptionsFlow):
    """Edit recipients and a persisted list of tracked activities."""

    def __init__(self) -> None:
        self._options: dict[str, Any] | None = None
        self._activity: dict[str, Any] = {}
        self._operation = "edit"

    def _init_options(self) -> dict[str, Any]:
        if self._options is None:
            self._options = deepcopy(dict(self.config_entry.options))
            self._options.setdefault("recipients", list(self.config_entry.data.get("recipients", [])))
            self._options.setdefault("activities", [])
        return self._options

    def _save(self):
        return self.async_create_entry(title="", data=self._init_options())

    async def async_step_init(self, user_input=None):
        options = self._init_options()
        menu = ["recipients", "add"]
        if options["activities"]:
            menu.extend(["edit", "toggle", "remove", "test"])
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_recipients(self, user_input=None):
        options = self._init_options()
        errors = {}
        if user_input is not None:
            if _valid_recipients(self.hass, user_input.get("recipients")):
                options["recipients"] = list(dict.fromkeys(user_input["recipients"]))
                return self._save()
            errors["base"] = "invalid_recipients"
        return self.async_show_form(
            step_id="recipients",
            data_schema=_recipient_schema(self.hass, options["recipients"]),
            errors=errors,
        )

    async def async_step_add(self, user_input=None):
        self._activity = {"id": uuid4().hex}
        return await self.async_step_basic()

    async def async_step_edit(self, user_input=None):
        self._operation = "edit"
        return await self._select_activity(user_input)

    async def async_step_toggle(self, user_input=None):
        self._operation = "toggle"
        return await self._select_activity(user_input)

    async def async_step_remove(self, user_input=None):
        self._operation = "remove"
        return await self._select_activity(user_input)

    async def async_step_test(self, user_input=None):
        self._operation = "test"
        return await self._select_activity(user_input)

    async def _select_activity(self, user_input):
        options = self._init_options()
        errors = {}
        if user_input is not None:
            activity = next(
                (item for item in options["activities"] if item["id"] == user_input.get("activity_id")),
                None,
            )
            if activity is None:
                errors["base"] = "activity_not_found"
            elif self._operation == "edit":
                self._activity = deepcopy(activity)
                return await self.async_step_basic()
            elif self._operation == "remove":
                options["activities"].remove(activity)
                return self._save()
            elif self._operation == "toggle":
                activity["enabled"] = not activity.get("enabled", True)
                return self._save()
            else:
                manager = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
                if manager is None:
                    errors["base"] = "integration_not_loaded"
                else:
                    try:
                        await manager.async_test(activity["id"])
                    except HomeAssistantError:
                        errors["base"] = "test_failed"
                    else:
                        return self.async_abort(reason="test_sent")
        return self.async_show_form(
            step_id=self._operation,
            data_schema=vol.Schema(
                {
                    vol.Required("activity_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": item["id"],
                                    "label": f"{item.get('name', item['entity_id'])} ({'enabled' if item.get('enabled', True) else 'disabled'})",
                                }
                                for item in options["activities"]
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    def _schema(self, fields: dict[str, Any], required: set[str] | None = None):
        schema = {}
        for key, (validator, default) in fields.items():
            value = self._activity.get(key, default)
            marker = vol.Required if key in (required or set()) else vol.Optional
            if value is None:
                schema[marker(key)] = validator
            else:
                schema[marker(key, default=value)] = validator
        return vol.Schema(schema)

    def _merge(self, user_input: dict[str, Any], fields: dict[str, Any]) -> None:
        for key, (_, default) in fields.items():
            if key not in user_input:
                if key not in self._activity and default is not None and default != "":
                    self._activity[key] = deepcopy(default)
                continue
            value = user_input.get(key)
            if value is None or value == "":
                self._activity.pop(key, None)
            else:
                self._activity[key] = value

    async def async_step_basic(self, user_input=None):
        fields = {
            "entity_id": (selector.EntitySelector(), None),
            "name": (_text(), None),
            "preset": (
                selector.SelectSelector(selector.SelectSelectorConfig(options=PRESETS)),
                "generic",
            ),
            "enabled": (selector.BooleanSelector(), True),
        }
        errors = {}
        if user_input is not None:
            entity_id = user_input.get("entity_id", "")
            if self.hass.states.get(entity_id) is None:
                errors["entity_id"] = "invalid_entity"
            else:
                self._merge(user_input, fields)
                state = self.hass.states.get(entity_id)
                self._activity.setdefault("name", state.attributes.get("friendly_name", entity_id))
                return await self.async_step_lifecycle()
        return self.async_show_form(
            step_id="basic",
            data_schema=self._schema(fields, {"entity_id", "preset", "enabled"}),
            errors=errors,
        )

    async def async_step_lifecycle(self, user_input=None):
        default = DOMAIN_DEFAULTS.get(
            self._activity["entity_id"].split(".", 1)[0],
            ("on", "off", "mdi:information-outline"),
        )
        fields = {
            "start_states": (_text(), default[0]),
            "end_states": (_text(), default[1]),
            "icon": (
                selector.IconSelector(),
                {
                    "alert": "mdi:alert-circle-outline",
                    "countdown": "mdi:timer-outline",
                    "steps": "mdi:format-list-numbered",
                    "gauge": "mdi:gauge",
                }.get(self._activity.get("preset"), default[2]),
            ),
        }
        errors = {}
        if user_input is not None:
            starts, ends = (
                _states(user_input.get("start_states")),
                _states(user_input.get("end_states")),
            )
            if not starts or not ends or set(starts) & set(ends):
                errors["base"] = "invalid_states"
            else:
                self._merge(user_input, fields)
                self._activity.update(start_states=starts, end_states=ends)
                return await self.async_step_presentation()
        # Convert persisted lists into editable comma-separated fields.
        schema_activity = deepcopy(self._activity)
        for key in ("start_states", "end_states"):
            if isinstance(self._activity.get(key), list):
                self._activity[key] = ",".join(self._activity[key])
        schema = self._schema(fields, {"start_states", "end_states"})
        self._activity = schema_activity
        return self.async_show_form(step_id="lifecycle", data_schema=schema, errors=errors)

    async def async_step_presentation(self, user_input=None):
        fields = {
            "subtitle": (_text(), ""),
            "critical_text": (_text(), None),
            "accent_color": (_text(), None),
            "text_color": (_text(), None),
            "background_color": (_text(), None),
            "progress_color": (_text(), None),
            "progress_bar_direction": (
                selector.SelectSelector(selector.SelectSelectorConfig(options=["increasing", "decreasing"])),
                "increasing",
            ),
            "url": (_text(), "/lovelace"),
            "relevance_score": (_number(0, 1, 0.05), 0.5),
            "severity": (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["info", "warning", "critical"])
                ),
                "info",
            ),
            "thresholds": (selector.ObjectSelector(), None),
        }
        errors = {}
        if user_input is not None:
            for key in (
                "accent_color",
                "text_color",
                "background_color",
                "progress_color",
            ):
                if user_input.get(key) and not COLOR_RE.fullmatch(str(user_input[key])):
                    errors[key] = "invalid_color"
            relevance = number(user_input.get("relevance_score", 0.5))
            if relevance is None or not 0 <= relevance <= 1:
                errors["relevance_score"] = "invalid_range"
            url = user_input.get("url", "")
            if url and (
                not isinstance(url, str) or not url.startswith(("/", "https://", "homeassistant://"))
            ):
                errors["url"] = "invalid_url"
            thresholds = user_input.get("thresholds")
            if thresholds is not None and (
                not isinstance(thresholds, list)
                or any(
                    not isinstance(item, dict)
                    or number(item.get("value")) is None
                    or not COLOR_RE.fullmatch(str(item.get("color", "")))
                    for item in thresholds
                )
            ):
                errors["thresholds"] = "invalid_thresholds"
            if not errors:
                self._merge(user_input, fields)
                return await self.async_step_sources()
        return self.async_show_form(step_id="presentation", data_schema=self._schema(fields), errors=errors)

    async def async_step_sources(self, user_input=None):
        fields = {
            "progress_entity": (selector.EntitySelector(), None),
            "progress_attribute": (_text(), None),
            "progress_min": (_number(-1000000000, 1000000000, 0.1), 0),
            "progress_max": (_number(-1000000000, 1000000000, 0.1), 100),
            "remaining_entity": (selector.EntitySelector(), None),
            "remaining_attribute": (_text(), None),
            "eta_entity": (selector.EntitySelector(), None),
            "eta_attribute": (_text(), None),
            "subtitle_entity": (selector.EntitySelector(), None),
            "subtitle_attribute": (_text(), None),
            "step_total": (_number(1, 10000), 5),
        }
        errors = {}
        if user_input is not None:
            high = number(user_input.get("progress_max", 100))
            low = number(user_input.get("progress_min", 0))
            if high is None or low is None or high <= low:
                errors["progress_max"] = "invalid_range"
            for key in (
                "progress_entity",
                "remaining_entity",
                "eta_entity",
                "subtitle_entity",
            ):
                if user_input.get(key) and self.hass.states.get(user_input[key]) is None:
                    errors[key] = "invalid_entity"
            if not errors:
                self._merge(user_input, fields)
                return await self.async_step_timing()
        return self.async_show_form(step_id="sources", data_schema=self._schema(fields), errors=errors)

    async def async_step_timing(self, user_input=None):
        fields = {
            "min_update_interval": (_number(1, 86400), 60),
            "debounce_seconds": (_number(0, 60, 0.1), 2),
            "change_threshold": (_number(0, 100, 0.1), 5),
            "completion_delay": (_number(0, 14400), 10),
            "completion_behavior": (
                selector.SelectSelector(selector.SelectSelectorConfig(options=["dismiss", "keep"])),
                "dismiss",
            ),
            "finish_at_eta": (selector.BooleanSelector(), True),
        }
        errors = {}
        if user_input is not None:
            self._merge(user_input, fields)
            try:
                validated = validate_config(self._activity)
            except (ValueError, TypeError):
                errors["base"] = "invalid_config"
            else:
                activities = self._init_options()["activities"]
                activities[:] = [item for item in activities if item["id"] != validated["id"]]
                activities.append(deepcopy(validated))
                return self._save()
        return self.async_show_form(step_id="timing", data_schema=self._schema(fields), errors=errors)
