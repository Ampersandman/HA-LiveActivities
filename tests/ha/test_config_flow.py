"""Exercise Home Island's persisted configuration using real HA flows."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_island.config_flow import recipient_options
from custom_components.home_island.const import DOMAIN


@pytest.fixture(autouse=True)
def mobile_services(hass):
    """Expose harmless notification services without making a push request."""
    # The mobile_app dependency is represented by the mock notify actions below.
    # Loading its real cloud/camera dependencies would exercise unrelated systems.
    hass.config.components.add("mobile_app")
    for name in ("mobile_app_iphone", "mobile_app_ipad", "mobile_app_android"):
        hass.services.async_register("notify", name, AsyncMock())


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={"recipients": ["notify.mobile_app_iphone"]},
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_routes_to_multiple_companion_devices(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"recipients": ["notify.mobile_app_iphone", "notify.mobile_app_ipad"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["recipients"] == [
        "notify.mobile_app_iphone",
        "notify.mobile_app_ipad",
    ]


async def test_setup_rejects_empty_missing_and_unrelated_actions(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    for recipients in ([], ["notify.mobile_app_absent"], ["notify.notify"]):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"recipients": recipients})
        assert result["errors"] == {"base": "invalid_recipients"}


async def test_singleton(hass, entry):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_recipient_options_exclude_known_android(hass):
    for os_name, name in (("iOS", "iPhone"), ("Android", "Android")):
        item = MockConfigEntry(domain="mobile_app", data={"os_name": os_name, "device_name": name})
        item.add_to_hass(hass)
    options = {item["value"]: item["label"] for item in recipient_options(hass)}
    assert "notify.mobile_app_iphone" in options
    assert "verify" not in options["notify.mobile_app_iphone"]
    assert "notify.mobile_app_android" not in options
    assert "verify" in options["notify.mobile_app_ipad"]


async def _add_activity(hass, entry, entity_id="sensor.washer", name="Washing machine"):
    hass.states.async_set(entity_id, "off", {"friendly_name": name})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add"})
    assert result["step_id"] == "basic"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"entity_id": entity_id, "name": name, "preset": "generic", "enabled": True},
    )
    assert result["step_id"] == "lifecycle"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "start_states": "washing,rinsing,spinning",
            "end_states": "off,complete",
            "icon": "mdi:washing-machine",
        },
    )
    assert result["step_id"] == "presentation"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"accent_color": "#2196F3", "relevance_score": 0.8, "url": "/lovelace/laundry"},
    )
    assert result["step_id"] == "sources"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "progress_attribute": "progress",
            "progress_min": 0,
            "progress_max": 100,
            "remaining_attribute": "remaining",
        },
    )
    assert result["step_id"] == "timing"
    return await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "min_update_interval": 60,
            "debounce_seconds": 2,
            "change_threshold": 5,
            "completion_delay": 10,
            "completion_behavior": "dismiss",
            "finish_at_eta": True,
        },
    )


async def test_add_persists_and_supports_multiple_trackers(hass, entry):
    result = await _add_activity(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    activity = entry.options["activities"][0]
    assert activity["start_states"] == ["washing", "rinsing", "spinning"]
    assert activity["end_states"] == ["off", "complete"]
    assert activity["progress_attribute"] == "progress"
    assert activity["relevance_score"] == 0.8
    assert entry.options["recipients"] == ["notify.mobile_app_iphone"]
    await _add_activity(hass, entry, "sensor.charger", "EV charger")
    assert len(entry.options["activities"]) == 2
    assert len({item["id"] for item in entry.options["activities"]}) == 2


async def test_toggle_remove_and_manual_ui_test(hass, entry):
    await _add_activity(hass, entry)
    activity_id = entry.options["activities"][0]["id"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "toggle"})
    await hass.config_entries.options.async_configure(result["flow_id"], {"activity_id": activity_id})
    assert entry.options["activities"][0]["enabled"] is False

    manager = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "test"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"activity_id": activity_id}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "test_sent"
    manager.async_test.assert_awaited_once_with(activity_id)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove"})
    await hass.config_entries.options.async_configure(result["flow_id"], {"activity_id": activity_id})
    assert entry.options["activities"] == []


async def test_edit_keeps_activity_identity_and_other_fields(hass, entry):
    await _add_activity(hass, entry)
    old = dict(entry.options["activities"][0])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "edit"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"activity_id": old["id"]})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "entity_id": old["entity_id"],
            "name": "New washer name",
            "preset": "countdown",
            "enabled": True,
        },
    )
    assert result["step_id"] == "lifecycle"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"start_states": "washing", "end_states": "complete"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"accent_color": "#FF0000"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"progress_attribute": "progress", "progress_min": 0, "progress_max": 100},
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"completion_delay": 20})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["activities"][0]["id"] == old["id"]
    assert entry.options["activities"][0]["name"] == "New washer name"
    assert entry.options["activities"][0]["completion_delay"] == 20


async def test_invalid_state_color_range_and_missing_entity(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity_id": "sensor.absent"}
    )
    assert result["errors"] == {"entity_id": "invalid_entity"}
    hass.states.async_set("sensor.washer", "off")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity_id": "sensor.washer"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"start_states": "on", "end_states": "on"}
    )
    assert result["errors"] == {"base": "invalid_states"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"start_states": "on", "end_states": "off"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"accent_color": "red"})
    assert result["errors"] == {"accent_color": "invalid_color"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"accent_color": "#00FF00"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"progress_min": 100, "progress_max": 0}
    )
    assert result["errors"] == {"progress_max": "invalid_range"}


async def test_change_recipients_preserves_existing_trackers(hass, entry):
    await _add_activity(hass, entry)
    previous = list(entry.options["activities"])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "recipients"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"recipients": ["notify.mobile_app_ipad"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["recipients"] == ["notify.mobile_app_ipad"]
    assert entry.options["activities"] == previous
