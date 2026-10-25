"""Exercise the HA adapter, actions, listeners and storage with real HA fixtures."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_island import async_setup_entry, async_unload_entry
from custom_components.home_island.const import DOMAIN
from custom_components.home_island.manager import HomeIslandManager
from custom_components.home_island.services import (
    END_SCHEMA,
    START_SCHEMA,
    TEST_SCHEMA,
    async_register_services,
    vol,
)


@pytest.fixture
def notification_calls(hass):
    calls = []

    async def iphone(call):
        calls.append(("iphone", deepcopy(dict(call.data))))

    async def second(call):
        calls.append(("second", deepcopy(dict(call.data))))

    hass.services.async_register("notify", "mobile_app_iphone", iphone)
    hass.services.async_register("notify", "mobile_app_second", second)
    return calls


@pytest.fixture
async def make_manager(hass, notification_calls):
    managers = []

    async def make(*, activities=None, snapshot=None, recipients=None, now=None):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"recipients": recipients or ["notify.mobile_app_iphone"]},
            options={"activities": activities or []},
        )
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)
        manager = HomeIslandManager(hass, entry)
        if now is not None:
            manager.engine.now = now
        manager.store = SimpleNamespace(
            async_load=AsyncMock(return_value=deepcopy(snapshot)),
            async_save=AsyncMock(),
            async_delay_save=Mock(),
        )
        managers.append(manager)
        await manager.async_setup()
        await manager._async_restore()
        return manager

    yield make
    for manager in managers:
        await manager.async_close()


def tracker(tracker_id="washer", entity="sensor.washer", **extra):
    return {
        "id": tracker_id,
        "entity_id": entity,
        "name": "Laundry",
        "preset": "generic",
        "start_states": ["washing", "rinsing", "spinning"],
        "end_states": ["off", "complete"],
        "progress_attribute": "progress",
        "completion_delay": 30,
        "min_update_interval": 60,
        "debounce_seconds": 2,
        **extra,
    }


async def settle(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_multiple_entities_route_once_and_reuse_tags(hass, make_manager, notification_calls):
    hass.states.async_set("sensor.washer", "off", {"progress": 0})
    hass.states.async_set("sensor.dryer", "off", {"progress": 0})
    manager = await make_manager(
        activities=[tracker(), tracker("dryer", "sensor.dryer")],
        recipients=["notify.mobile_app_iphone", "notify.mobile_app_second"],
    )
    assert not notification_calls
    hass.states.async_set("sensor.washer", "washing", {"progress": 10})
    await settle(hass)
    assert len(notification_calls) == 2
    tag = notification_calls[0][1]["data"]["tag"]
    assert {recipient for recipient, _ in notification_calls} == {"iphone", "second"}
    assert all(payload["data"]["live_update"] is True for _, payload in notification_calls)

    hass.states.async_set("sensor.washer", "rinsing", {"progress": 50})
    await settle(hass)
    assert len(notification_calls) == 4
    assert all(payload["data"]["tag"] == tag for _, payload in notification_calls)

    hass.states.async_set("sensor.dryer", "washing", {"progress": 5})
    await settle(hass)
    assert len(notification_calls) == 6
    assert notification_calls[-1][1]["data"]["tag"] != tag
    assert len(manager.engine.records) == 2


async def test_complete_then_immediate_restart_cancels_dismissal(hass, make_manager, notification_calls):
    hass.states.async_set("sensor.washer", "washing", {"progress": 25})
    manager = await make_manager(activities=[tracker()])
    tag = notification_calls[-1][1]["data"]["tag"]
    hass.states.async_set("sensor.washer", "complete", {"progress": 100})
    await settle(hass)
    assert manager.engine.records["tracker_washer"]["phase"] == "completing"
    assert ("tracker_washer", "dismiss") in manager.engine._timers
    hass.states.async_set("sensor.washer", "washing", {"progress": 0})
    await settle(hass)
    assert manager.engine.records["tracker_washer"]["phase"] == "running"
    assert ("tracker_washer", "dismiss") not in manager.engine._timers
    assert notification_calls[-1][1]["data"]["tag"] == tag
    assert not any(payload["message"] == "clear_notification" for _, payload in notification_calls)


async def test_source_burst_coalesces_latest_and_duplicate_is_suppressed(
    hass, make_manager, notification_calls
):
    hass.states.async_set("sensor.washer", "washing", {"progress": 10})
    manager = await make_manager(activities=[tracker(change_threshold=5)])
    hass.states.async_set("sensor.washer", "washing", {"progress": 20})
    hass.states.async_set("sensor.washer", "washing", {"progress": 40})
    await settle(hass)
    assert len(notification_calls) == 1
    await manager.engine.flush("tracker_washer")
    assert len(notification_calls) == 2
    assert notification_calls[-1][1]["data"]["progress"] == 40
    hass.states.async_set("sensor.washer", "washing", {"progress": 41})
    await settle(hass)
    await manager.engine.flush("tracker_washer")
    assert len(notification_calls) == 2


async def test_unavailable_removed_and_malformed_sources_are_safe(hass, make_manager, notification_calls):
    hass.states.async_set("sensor.washer", "unavailable")
    manager = await make_manager(activities=[tracker(), tracker("missing", "sensor.absent")])
    assert not notification_calls
    hass.states.async_set("sensor.washer", "washing", {"progress": "not-a-number"})
    await settle(hass)
    assert len(notification_calls) == 1
    assert "progress" not in notification_calls[-1][1]["data"]
    hass.states.async_remove("sensor.washer")
    await settle(hass)
    assert manager.engine.records["tracker_washer"]["phase"] == "running"


async def test_restart_reconciles_without_resending_same_start(hass, make_manager, notification_calls):
    hass.states.async_set("sensor.washer", "washing", {"progress": 40})
    manager = await make_manager(activities=[tracker()])
    snapshot = manager.engine.snapshot()
    await manager.async_close()
    restored = await make_manager(activities=[tracker()], snapshot=snapshot)
    assert len(notification_calls) == 1
    assert restored.engine.records["tracker_washer"]["phase"] == "running"
    assert ("tracker_washer", "expire") in restored.engine._timers


async def test_recipient_change_on_restore_clears_old_route_then_starts_new_route(
    hass, make_manager, notification_calls
):
    hass.states.async_set("sensor.washer", "washing", {"progress": 40})
    manager = await make_manager(activities=[tracker()])
    original_tag = notification_calls[-1][1]["data"]["tag"]
    snapshot = manager.engine.snapshot()
    await manager.async_close()

    restored = await make_manager(
        activities=[tracker()], snapshot=snapshot, recipients=["notify.mobile_app_second"]
    )

    assert [recipient for recipient, _ in notification_calls] == ["iphone", "iphone", "second"]
    assert notification_calls[1][1] == {"message": "clear_notification", "data": {"tag": original_tag}}
    assert notification_calls[2][1]["data"]["live_update"] is True
    assert notification_calls[2][1]["data"]["tag"] == original_tag
    assert restored.engine.records["tracker_washer"]["recipients"] == ["notify.mobile_app_second"]
    assert restored.engine.records["tracker_washer"]["phase"] == "running"


async def test_completion_during_outage_is_reconciled(hass, make_manager, notification_calls):
    hass.states.async_set("sensor.washer", "washing", {"progress": 40})
    manager = await make_manager(activities=[tracker()])
    snapshot = manager.engine.snapshot()
    await manager.async_close()
    hass.states.async_set("sensor.washer", "off", {"progress": 100})
    restored = await make_manager(activities=[tracker()], snapshot=snapshot)
    assert restored.engine.records["tracker_washer"]["phase"] == "completing"
    assert len(notification_calls) == 2
    await restored.engine.end("tracker_washer")
    assert notification_calls[-1][1] == {
        "message": "clear_notification",
        "data": {"tag": notification_calls[0][1]["data"]["tag"]},
    }


async def test_remaining_time_anchor_survives_restart_before_first_update(
    hass, make_manager, notification_calls
):
    clock = [1000.0]
    config = tracker(preset="countdown", remaining_attribute="remaining")
    hass.states.async_set("sensor.washer", "washing", {"progress": 10, "remaining": 120})
    manager = await make_manager(activities=[config], now=lambda: clock[0])
    original_deadline = notification_calls[-1][1]["data"]["when"]
    assert original_deadline == 1120
    assert notification_calls[-1][1]["data"]["when_relative"] is False
    snapshot = manager.engine.snapshot()
    await manager.async_close()
    clock[0] += 30
    restored = await make_manager(activities=[config], snapshot=snapshot, now=lambda: clock[0])
    assert restored.engine.records["tracker_washer"]["payload"]["data"]["when"] == original_deadline
    assert len(notification_calls) == 1


async def test_new_cycle_reanchors_unchanged_remaining_value_without_resetting_platform_lifetime(
    hass, make_manager, notification_calls
):
    clock = [1000.0]
    config = tracker(preset="countdown", remaining_attribute="remaining")
    hass.states.async_set("sensor.washer", "washing", {"progress": 0, "remaining": 120})
    manager = await make_manager(activities=[config], now=lambda: clock[0])
    first_payload = notification_calls[-1][1]
    assert first_payload["data"]["when"] == 1120

    clock[0] = 1050
    hass.states.async_set("sensor.washer", "complete", {"progress": 100, "remaining": 120})
    await settle(hass)
    assert manager.engine.records["tracker_washer"]["phase"] == "completing"

    clock[0] = 1055
    hass.states.async_set("sensor.washer", "washing", {"progress": 0, "remaining": 120})
    await settle(hass)
    record = manager.engine.records["tracker_washer"]
    assert notification_calls[-1][1]["data"]["when"] == 1175
    assert notification_calls[-1][1]["data"]["tag"] == first_payload["data"]["tag"]
    assert record["countdown_at"] == 1175
    assert record["started_at"] == 1000
    assert record["phase"] == "running"
    assert not any(payload["message"] == "clear_notification" for _, payload in notification_calls)


@pytest.mark.parametrize(
    ("action", "data", "duration"),
    [
        ("start", {"activity_id": "clock", "preset": "countdown", "remaining_seconds": 120}, 120),
        ("test", {"activity_id": "clock"}, 30),
    ],
)
async def test_manual_countdown_deadline_is_persisted_and_rearmed_on_restore(
    hass, make_manager, notification_calls, action, data, duration
):
    clock = [1000.0]
    manager = await make_manager(now=lambda: clock[0])
    await manager.async_manual(action, data)
    deadline = 1000 + duration
    record = manager.engine.records["manual_clock"]
    assert record["countdown_at"] == deadline
    assert notification_calls[-1][1]["data"]["when"] == deadline
    snapshot = manager.engine.snapshot()
    await manager.async_close()

    clock[0] += 10
    restored = await make_manager(snapshot=snapshot, now=lambda: clock[0])
    assert restored.engine.records["manual_clock"]["countdown_at"] == deadline
    assert ("manual_clock", "countdown") in restored.engine._timers
    assert len(notification_calls) == 1


async def test_timer_uses_finishes_at_and_final_update_stops_chronometer(
    hass, make_manager, notification_calls
):
    config = tracker(
        "timer", "timer.kitchen", preset="countdown", start_states=["active"], end_states=["idle"]
    )
    finishes_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    hass.states.async_set("timer.kitchen", "active", {"finishes_at": finishes_at})
    manager = await make_manager(activities=[config])
    assert notification_calls[-1][1]["data"]["chronometer"] is True
    assert notification_calls[-1][1]["data"]["when_relative"] is False
    hass.states.async_set("timer.kitchen", "idle")
    await settle(hass)
    assert notification_calls[-1][1]["data"]["chronometer"] is False
    assert "when" not in notification_calls[-1][1]["data"]
    assert manager.engine.records["tracker_timer"]["phase"] == "completing"


async def test_manual_actions_and_schema_are_real_registered_services(hass, make_manager, notification_calls):
    manager = await make_manager()
    hass.data[DOMAIN] = {manager.entry.entry_id: manager}
    async_register_services(hass)
    await hass.services.async_call(
        DOMAIN,
        "start",
        {
            "activity_id": "automation washer",
            "title": "Washer",
            "message": "Washing",
            "progress": 25,
            "min_update_interval": 0,
            "debounce_seconds": 0,
        },
        blocking=True,
    )
    assert notification_calls[-1][1]["title"] == "Washer"
    tag = notification_calls[-1][1]["data"]["tag"]
    assert " " not in tag and len(tag) <= 64
    await hass.services.async_call(
        DOMAIN,
        "update",
        {"activity_id": "automation washer", "message": "Spinning", "progress": 80},
        blocking=True,
    )
    await manager.engine.flush("manual_automation washer")
    assert notification_calls[-1][1]["message"] == "Spinning"
    assert notification_calls[-1][1]["title"] == "Washer"
    assert notification_calls[-1][1]["data"]["tag"] == tag
    await hass.services.async_call(DOMAIN, "end", {"activity_id": "automation washer"}, blocking=True)
    assert notification_calls[-1][1] == {"message": "clear_notification", "data": {"tag": tag}}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "update", {"activity_id": "never_started"}, blocking=True)
    await hass.services.async_call(DOMAIN, "test", {}, blocking=True)
    assert notification_calls[-1][1]["title"] == "Home Island test"


async def test_running_manual_update_rejects_recipient_changes_without_rerouting(
    hass, make_manager, notification_calls
):
    manager = await make_manager()
    hass.data[DOMAIN] = {manager.entry.entry_id: manager}
    async_register_services(hass)
    await hass.services.async_call(
        DOMAIN, "start", {"activity_id": "private", "message": "Running"}, blocking=True
    )
    snapshot = manager.engine.snapshot()
    with pytest.raises(ServiceValidationError, match="End the activity"):
        await hass.services.async_call(
            DOMAIN,
            "update",
            {"activity_id": "private", "recipients": ["notify.mobile_app_second"], "message": "Changed"},
            blocking=True,
        )
    assert manager.engine.snapshot() == snapshot
    assert len(notification_calls) == 1
    assert notification_calls[0][0] == "iphone"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"activity_id": ""},
        {"activity_id": "x", "progress": float("nan")},
        {"activity_id": "x", "relevance_score": 1.1},
        {"activity_id": "x", "recipients": ["notify.everyone"]},
        {"activity_id": "x", "accent_color": "red"},
        {"activity_id": "x", "progress_max": 0},
        {"activity_id": "x", "remaining_seconds": -1},
        {"activity_id": "x", "progress_bar_direction": "left_to_right"},
        {"activity_id": "x", "unsupported_payload": True},
    ],
)
def test_service_schema_rejects_invalid_inputs(data):
    with pytest.raises(vol.Invalid):
        START_SCHEMA(data)


def test_end_and_test_schema_defaults():
    assert END_SCHEMA({"activity_id": "x"}) == {"activity_id": "x", "immediate": True}
    assert TEST_SCHEMA({}) == {"activity_id": "home_island_test"}


async def test_partial_device_failure_retries_only_failed_recipient(hass, make_manager, notification_calls):
    manager = await make_manager(recipients=["notify.mobile_app_iphone", "notify.mobile_app_second"])
    attempts = 0

    async def unreliable(call):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HomeAssistantError("temporary failure with private content")
        notification_calls.append(("second", deepcopy(dict(call.data))))

    hass.services.async_register("notify", "mobile_app_second", unreliable)
    await manager.async_manual("start", {"activity_id": "retry", "message": "Private content"})
    assert attempts == 1
    assert len(notification_calls) == 1
    assert manager.engine.records["manual_retry"]["pending"] is not None
    await manager.engine.flush("manual_retry")
    assert attempts == 2
    assert [recipient for recipient, _ in notification_calls] == ["iphone", "second"]
    assert manager.engine.records["manual_retry"]["pending"] is None
    diagnostics = manager.diagnostics()
    assert "Private content" not in str(diagnostics)
    assert "notify.mobile_app" not in str(diagnostics)


async def test_unload_removes_services_listeners_tasks_and_saves_runtime(hass, notification_calls):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"recipients": ["notify.mobile_app_iphone"]}, options={"activities": [tracker()]}
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    hass.states.async_set("sensor.washer", "off")
    store = SimpleNamespace(
        async_load=AsyncMock(return_value=None), async_save=AsyncMock(), async_delay_save=Mock()
    )
    with patch("custom_components.home_island.manager.Store", return_value=store):
        assert await async_setup_entry(hass, entry)
    manager = entry.runtime_data
    await manager._async_restore()
    await hass.services.async_call(
        DOMAIN, "start", {"activity_id": "persist", "message": "Running"}, blocking=True
    )
    assert manager.engine._timers
    assert await async_unload_entry(hass, entry)
    assert not manager._unsubs
    assert not manager._tasks
    assert not manager.engine._timers
    assert manager.engine.closed
    store.async_save.assert_awaited_once()
    assert "manual_persist" in store.async_save.call_args.args[0]["records"]
    assert not hass.services.has_service(DOMAIN, "start")
    hass.states.async_set("sensor.washer", "washing", {"progress": 20})
    await settle(hass)
    assert len(notification_calls) == 1
