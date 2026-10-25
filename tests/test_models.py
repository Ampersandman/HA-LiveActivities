"""Native payload and conversion contracts, independent of Home Assistant."""

import re
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from custom_components.home_island.models import (
    deadline,
    meaningful,
    number,
    render,
    stable_tag,
    validate_config,
)


@pytest.mark.parametrize(
    "value", [None, True, False, "unknown", "unavailable", "NaN", float("inf"), "-inf", {}, []]
)
def test_non_numeric_and_non_finite_values_are_rejected(value):
    assert number(value) is None


@pytest.mark.parametrize("value, expected", [(0, 0), ("0", 0), ("12.5", 12.5), (-4, -4)])
def test_numeric_values(value, expected):
    assert number(value) == expected


@pytest.mark.parametrize(
    "value, unit, expected",
    [
        (30, "s", 1030),
        (2, "min", 1120),
        (1.5, "h", 6400),
        (2000, "ms", 1002),
        ("01:30", "s", 1090),
        ("1:02:03", "s", 4723),
        (-10, "s", 1000),
    ],
)
def test_remaining_time_is_converted_once_to_deadline(value, unit, expected):
    assert deadline(value, 1000, unit=unit) == expected


def test_absolute_timestamp_and_timezone_conversion():
    expected = datetime(2026, 10, 25, 12, tzinfo=timezone.utc).timestamp()
    assert deadline("2026-10-25T14:00:00+02:00", 1000, absolute=True) == expected
    assert deadline("2026-10-25T12:00:00Z", 1000, absolute=True) == expected
    assert deadline(datetime(2026, 10, 25, 12, tzinfo=timezone.utc), 1000) == expected
    assert deadline(expected, 1000, absolute=True) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        "unknown",
        "1:61",
        "1:00:90",
        "not a date",
        "2026-10-25T12:00:00",
        datetime(2026, 10, 25, 12),
    ],
)
def test_malformed_or_timezone_ambiguous_time_is_ignored(value):
    assert deadline(value, 1000) is None


def test_tag_is_stable_safe_and_reused_by_updates():
    assert stable_tag("washer-cycle_1") == "washer-cycle_1"
    raw = "Washing machine / " + "x" * 100
    tag = stable_tag(raw)
    assert tag == stable_tag(raw)
    assert len(tag) <= 64
    assert re.fullmatch(r"[A-Za-z0-9_-]+", tag)
    assert render({}, raw)["data"]["tag"] == tag
    assert render({}, raw, progress=80)["data"]["tag"] == tag


def test_payload_uses_only_documented_fields_and_nesting():
    payload = render(
        {
            "name": "Washer",
            "accent_color": "#112233",
            "text_color": "#FFFFFF",
            "background_color": "#000000",
            "progress_color": "#00FF00",
            "progress_bar_direction": "decreasing",
            "critical_text": "Rinsing",
            "url": "/lovelace/laundry",
            "relevance_score": 0.7,
        },
        "washer",
        status="washing",
        progress=50,
        end_at=1700000123,
    )
    assert set(payload) == {"title", "message", "data"}
    assert payload["title"] == "Washer"
    assert payload["message"] == "washing"
    assert payload["data"] == {
        "tag": "washer",
        "live_update": True,
        "relevance_score": 0.7,
        "notification_icon": "mdi:home-assistant",
        "notification_icon_color": "#112233",
        "alert_once": True,
        "background_color": "#000000",
        "text_color": "#FFFFFF",
        "progress_bar_color": "#00FF00",
        "url": "/lovelace/laundry",
        "critical_text": "Rinsing",
        "progress_bar_direction": "decreasing",
        "progress": 50,
        "progress_max": 100,
        "chronometer": True,
        "when": 1700000123,
        "when_relative": False,
    }


@pytest.mark.parametrize("progress, expected", [(-20, 0), (30, 30), (150, 100)])
def test_progress_is_clamped_to_valid_range(progress, expected):
    data = render({}, "id", progress=progress)["data"]
    assert data["progress"] == expected
    assert data["progress_max"] == 100


def test_gauge_maps_nonzero_minimum_and_applies_highest_threshold():
    payload = render(
        {
            "preset": "gauge",
            "progress_min": -20,
            "progress_max": 80,
            "thresholds": [{"value": 40, "color": "#FF0000"}, {"value": 0, "color": "#00FF00"}],
        },
        "temperature",
        progress=50,
        status="Heating",
    )
    assert payload["data"]["progress"] == 700
    assert payload["data"]["progress_max"] == 1000
    assert payload["data"]["progress_bar_color"] == "#FF0000"
    assert "50 / 80" in payload["message"]


def test_steps_are_approximated_as_status_and_progress():
    payload = render({"preset": "steps", "step_total": 5}, "cycle", progress=3, status="Spinning")
    assert payload["data"]["progress"] == 3
    assert payload["data"]["progress_max"] == 5
    assert "Step 3 of 5" in payload["message"]
    assert "Spinning" in payload["message"]


def test_alert_does_not_request_critical_alert_privileges():
    payload = render({"preset": "alert", "severity": "critical"}, "alarm", status="Alarm triggered")
    assert payload["data"]["critical_text"] == "Critical"
    assert payload["data"]["notification_icon_color"] == "#F44336"
    assert "push" not in payload["data"]
    assert "sound" not in payload["data"]


def test_explicit_quiet_flags_use_native_nested_fields():
    result = render({"silent": True, "alert_once": False}, "id")
    assert result["data"]["silent"] is True
    assert result["data"]["alert_once"] is False


def test_completion_removes_countdown_without_fabricating_progress():
    payload = render(
        {"completion_message": "Laundry is ready"}, "washer", progress=80, end_at=1700000000, complete=True
    )
    assert payload["message"] == "Laundry is ready"
    assert payload["data"]["chronometer"] is False
    assert "when" not in payload["data"]
    assert payload["data"]["progress"] == 80


@pytest.mark.parametrize(
    "config",
    [
        {"preset": "board"},
        {"accent_color": "red"},
        {"relevance_score": 1.01},
        {"relevance_score": float("nan")},
        {"min_update_interval": -1},
        {"debounce_seconds": 61},
        {"change_threshold": 101},
        {"completion_delay": -1},
        {"progress_min": 5, "progress_max": 5},
        {"progress_max": float("inf")},
        {"step_total": 0},
        {"recipients": ["notify.notify"]},
        {"completion_behavior": "forever"},
        {"severity": "urgent"},
        {"progress_bar_direction": "left_to_right"},
        {"thresholds": [{"value": True, "color": "#FF0000"}]},
        {"thresholds": [{"value": 50, "color": "red"}]},
        {"remaining_seconds": float("inf")},
        {"url": "javascript:alert(1)"},
    ],
)
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        validate_config(config)


def test_config_validation_accepts_native_ranges_and_returns_independent_mapping():
    config = {
        "preset": "gauge",
        "progress_min": -100,
        "progress_max": 200,
        "relevance_score": 0,
        "progress_bar_direction": "increasing",
        "recipients": ["notify.mobile_app_iphone"],
        "thresholds": [{"value": 80, "color": "#00FF00"}],
    }
    validated = validate_config(config)
    assert validated == config
    assert validated is not config


def test_threshold_compares_to_last_accepted_progress_and_text_changes_override_it():
    baseline = render({}, "washer", status="Washing", progress=20)
    assert not meaningful(baseline, deepcopy(baseline), 5)
    assert not meaningful(baseline, render({}, "washer", status="Washing", progress=24), 5)
    assert meaningful(baseline, render({}, "washer", status="Washing", progress=25), 5)
    assert meaningful(baseline, render({}, "washer", status="Rinsing", progress=21), 5)
