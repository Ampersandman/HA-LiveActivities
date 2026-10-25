"""Transport independent values and native Companion presentation rendering."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
from typing import Any

from .const import PRESETS

TAG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
RECIPIENT = re.compile(r"^(?:notify\.)?mobile_app_[a-z0-9_]+$")
INVALID_STATES = {"unknown", "unavailable", "None", ""}


def stable_tag(activity_id: str) -> str:
    """Keep valid caller IDs readable; hash long or otherwise invalid IDs."""
    if TAG.fullmatch(activity_id):
        return activity_id
    return "hi_" + hashlib.sha256(activity_id.encode()).hexdigest()[:48]


def number(value: Any) -> float | None:
    """Reject NaN, infinity, boolean, and unavailable values."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def deadline(value: Any, now: float, *, absolute: bool = False, unit: str = "s") -> float | None:
    """Convert ISO dates, H:MM:SS durations, or unit-aware seconds to UTC epoch."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.timestamp() if value.tzinfo else None
    numeric = number(value)
    if numeric is not None:
        if absolute:
            return numeric if numeric > 0 else None
        scale = {"min": 60, "minutes": 60, "h": 3600, "hours": 3600, "ms": 0.001}.get(unit, 1)
        return now + max(0, numeric * scale)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except ValueError:
        pass
    if not absolute and re.fullmatch(r"\d+:\d{2}(?::\d{2})?", text):
        parts = [int(part) for part in text.split(":")]
        if any(part >= 60 for part in parts[1:]):
            return None
        seconds = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]
        return now + seconds
    return None


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate persisted configuration and manual service values."""
    result = dict(config)
    if result.get("preset", "generic") not in PRESETS:
        raise ValueError("Unsupported native preset")
    for key in ("accent_color", "text_color", "background_color", "progress_color"):
        if result.get(key) and not COLOR.fullmatch(result[key]):
            raise ValueError(f"{key} must use #RRGGBB")
    for key, lower, upper in (
        ("relevance_score", 0, 1),
        ("min_update_interval", 0, 86400),
        ("debounce_seconds", 0, 60),
        ("change_threshold", 0, 100),
        ("completion_delay", 0, 14400),
        ("step_total", 1, 10000),
    ):
        if key in result and (number(result[key]) is None or not lower <= float(result[key]) <= upper):
            raise ValueError(f"{key} must be between {lower} and {upper}")
    for recipient in result.get("recipients", []):
        if not isinstance(recipient, str) or not RECIPIENT.fullmatch(recipient):
            raise ValueError("Recipients must be Companion notify.mobile_app_* actions")
    if result.get("completion_behavior", "dismiss") not in ("dismiss", "keep"):
        raise ValueError("Invalid completion behavior")
    if result.get("severity", "info") not in ("info", "warning", "critical"):
        raise ValueError("Invalid severity")
    if result.get("progress_bar_direction", "increasing") not in ("increasing", "decreasing"):
        raise ValueError("Invalid progress direction")
    for threshold in result.get("thresholds", []):
        if (
            not isinstance(threshold, dict)
            or number(threshold.get("value")) is None
            or not COLOR.fullmatch(str(threshold.get("color", "")))
        ):
            raise ValueError("Thresholds require a numeric value and #RRGGBB color")
    low = number(result.get("progress_min", 0))
    high = number(result.get("progress_max", 100))
    if low is None or high is None or high <= low:
        raise ValueError("progress_max must exceed progress_min")
    for key in ("remaining_seconds", "when", "progress"):
        if key in result and number(result[key]) is None:
            raise ValueError(f"{key} must be finite")
    if result.get("url") and not str(result["url"]).startswith(
        ("/", "https://", "http://", "homeassistant://")
    ):
        raise ValueError("URL must be a dashboard path or http(s)/Home Assistant URL")
    return result


def render(
    config: dict[str, Any],
    activity_id: str,
    *,
    status: str = "",
    progress: Any = None,
    end_at: float | None = None,
    subtitle: str = "",
    complete: bool = False,
) -> dict[str, Any]:
    """Build only documented native fields with correct notify nesting."""
    preset = config.get("preset", "generic")
    message = subtitle or config.get("message") or config.get("subtitle") or status or "In progress"
    if complete:
        message = config.get("completion_message", "Complete")
    data: dict[str, Any] = {
        "tag": stable_tag(activity_id),
        "live_update": True,
        "relevance_score": float(config.get("relevance_score", 0.5)),
        "notification_icon": config.get("icon")
        or {
            "countdown": "mdi:timer-outline",
            "alert": "mdi:alert-circle-outline",
            "steps": "mdi:format-list-numbered",
            "gauge": "mdi:gauge",
        }.get(preset, "mdi:home-assistant"),
        "notification_icon_color": config.get("accent_color") or "#2196F3",
        "alert_once": config.get("alert_once", True),
    }
    if "silent" in config:
        data["silent"] = config["silent"]
    for key, native in (
        ("background_color", "background_color"),
        ("text_color", "text_color"),
        ("progress_color", "progress_bar_color"),
        ("url", "url"),
        ("critical_text", "critical_text"),
        ("progress_bar_direction", "progress_bar_direction"),
    ):
        if config.get(key):
            data[native] = config[key]
    if preset == "alert":
        severity = config.get("severity", "info")
        data.setdefault("critical_text", severity.capitalize())
        data["notification_icon_color"] = (
            config.get("accent_color")
            or {"info": "#2196F3", "warning": "#FF9800", "critical": "#F44336"}[severity]
        )
    current = number(progress if progress is not None else config.get("progress"))
    low = float(config.get("progress_min", 0)) if preset == "gauge" else 0
    high = float(config.get("step_total", 5)) if preset == "steps" else float(config.get("progress_max", 100))
    if current is not None and high > low:
        scale = 1000 if preset == "gauge" else max(1, min(2147483647, round(high - low)))
        data["progress"] = round(max(0, min(1, (current - low) / (high - low))) * scale)
        data["progress_max"] = scale
        if preset == "steps" and not complete:
            message = f"Step {current:g} of {high:g} · {message}"
        if preset == "gauge" and not complete:
            message = f"{current:g} / {high:g} · {message}"
        for threshold in sorted(config.get("thresholds", []), key=lambda row: float(row["value"])):
            if current >= float(threshold["value"]):
                data["progress_bar_color"] = threshold["color"]
    if end_at is not None and not complete:
        data.update(chronometer=True, when=int(end_at), when_relative=False)
    if complete:
        data["notification_icon"] = "mdi:check-circle-outline"
        data["notification_icon_color"] = "#4CAF50"
        # Explicitly remove a previously displayed countdown on completion.
        data["chronometer"] = False
    return {
        "title": config.get("title") or config.get("name") or "Home Island",
        "message": str(message),
        "data": data,
    }


def meaningful(
    previous: dict[str, Any], current: dict[str, Any], threshold: float, *, preset: str = ""
) -> bool:
    """Allow text/lifecycle changes immediately; gate cosmetic progress deltas."""
    if previous == current:
        return False
    before, after = dict(previous["data"]), dict(current["data"])
    p1, p2 = before.pop("progress", None), after.pop("progress", None)
    before_message, after_message = previous.get("message"), current.get("message")
    if preset in ("gauge", "steps"):
        before_message = str(before_message).partition(" · ")[2] or before_message
        after_message = str(after_message).partition(" · ")[2] or after_message
    if previous.get("title") != current.get("title") or before_message != after_message or before != after:
        return True
    if p1 is None or p2 is None:
        return True
    maximum = number(after.get("progress_max")) or 100
    return abs(p2 - p1) / maximum * 100 >= threshold
