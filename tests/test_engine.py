"""Exercise the real lifecycle queue with notification transport mocked."""

import asyncio
from copy import deepcopy

import pytest
import pytest_asyncio

from custom_components.home_island.const import MAX_AGE_SECONDS
from custom_components.home_island.engine import ActivityEngine
from custom_components.home_island.models import render

pytestmark = pytest.mark.asyncio


class Clock:
    def __init__(self):
        self.value = 1700000000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest_asyncio.fixture
async def engine():
    calls = []
    clock = Clock()

    async def send(recipient, payload):
        calls.append((recipient, deepcopy(payload)))

    instance = ActivityEngine(send, lambda: None, now=clock)
    yield instance, calls, clock
    await instance.close()


def payload(progress=10, message="Washing"):
    return render({"name": "Washer"}, "washer", status=message, progress=progress)


async def test_multiple_devices_receive_one_start_each_and_stable_tag(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(), ["phone", "tablet", "phone"], {})
    assert [call[0] for call in calls] == ["phone", "tablet"]
    assert {call[1]["data"]["tag"] for call in calls} == {"washer"}
    assert instance.records["washer"]["phase"] == "running"
    await instance.start("washer", payload(), ["phone", "tablet"], {})
    assert len(calls) == 2


async def test_independent_activities_keep_distinct_tags_and_lifecycles(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(), ["phone"], {})
    await instance.start("charger", render({}, "charger", progress=20), ["phone"], {})
    await instance.end("washer")
    assert instance.records["washer"]["phase"] == "idle"
    assert instance.records["charger"]["phase"] == "running"
    assert calls[-1][1] == {"message": "clear_notification", "data": {"tag": "washer"}}


async def test_cosmetic_updates_coalesce_latest_state_at_bounded_deadline(engine):
    instance, calls, clock = engine
    settings = {"min_update_interval": 60, "debounce_seconds": 2, "change_threshold": 0}
    await instance.start("washer", payload(), ["phone"], settings)
    clock.advance(10)
    await instance.update("washer", payload(20))
    first_due = instance._timers[("washer", "flush")].when()
    clock.advance(1)
    await instance.update("washer", payload(30))
    # The wall clock moved, while the real event-loop clock did not.
    assert instance._timers[("washer", "flush")].when() < first_due
    assert len(calls) == 1
    assert instance.records["washer"]["pending"]["data"]["progress"] == 30
    clock.advance(49)
    await instance.flush("washer")
    assert len(calls) == 2
    assert calls[-1][1]["data"]["progress"] == 30


async def test_threshold_accumulates_against_accepted_payload(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(20), ["phone"], {"change_threshold": 5})
    await instance.update("washer", payload(24))
    assert instance.records["washer"]["pending"] is None
    await instance.update("washer", payload(25))
    assert instance.records["washer"]["pending"] is not None
    await instance.flush("washer")
    assert len(calls) == 2


async def test_reverting_to_accepted_state_cancels_pending_and_resets_debounce(engine):
    instance, calls, clock = engine
    await instance.start("washer", payload(10), ["phone"], {"min_update_interval": 0, "debounce_seconds": 2})
    clock.advance(10)
    await instance.update("washer", payload(30))
    await instance.update("washer", payload(10))
    assert ("washer", "flush") not in instance._timers
    assert "pending_since" not in instance.records["washer"]
    clock.advance(20)
    await instance.update("washer", payload(40))
    due_delay = instance._timers[("washer", "flush")].when() - asyncio.get_running_loop().time()
    assert 1.8 < due_delay <= 2
    assert len(calls) == 1


async def test_important_state_changes_flush_immediately(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(), ["phone"], {"min_update_interval": 3600})
    await instance.update("washer", payload(11, "Rinsing"), important=True)
    assert len(calls) == 2
    assert calls[-1][1]["message"] == "Rinsing"
    assert ("washer", "flush") not in instance._timers


async def test_real_debounce_timer_fires_once_with_latest_payload():
    calls = []

    async def send(recipient, value):
        calls.append(deepcopy(value))

    instance = ActivityEngine(send, lambda: None)
    try:
        await instance.start(
            "washer", payload(), ["phone"], {"min_update_interval": 0, "debounce_seconds": 0.02}
        )
        await instance.update("washer", payload(30))
        await instance.update("washer", payload(70))
        await asyncio.sleep(0.05)
        assert len(calls) == 2
        assert calls[-1]["data"]["progress"] == 70
        assert not instance._tasks
    finally:
        await instance.close()


async def test_partial_failure_retries_only_failed_device(engine):
    instance, calls, clock = engine
    attempts = []
    fail_tablet = True

    async def send(recipient, value):
        attempts.append(recipient)
        if recipient == "tablet" and fail_tablet:
            raise OSError("private notification contents must not be logged")
        calls.append((recipient, deepcopy(value)))

    instance.send = send
    await instance.start("washer", payload(), ["phone", "tablet"], {})
    assert attempts == ["phone", "tablet"]
    assert instance.records["washer"]["retry"] == 1
    assert instance.accounting["phone"]["accepted"] == 1
    assert instance.accounting["tablet"]["failed"] == 1
    fail_tablet = False
    clock.advance(5)
    await instance.flush("washer")
    assert attempts == ["phone", "tablet", "tablet"]
    assert instance.records["washer"]["pending"] is None
    assert instance.records["washer"]["retry"] == 0


async def test_retry_budget_is_bounded_and_logs_no_content(engine, caplog):
    instance, _, _ = engine

    async def fail(recipient, value):
        raise OSError("sensitive-content-123")

    instance.send = fail
    await instance.start("washer", payload(), ["phone"], {})
    for _ in range(5):
        instance._cancel("washer", "flush")  # Consume a scheduled retry deterministically.
        await instance.flush("washer")
    assert instance.records["washer"]["retry"] == 6
    assert ("washer", "flush") not in instance._timers
    assert "sensitive-content-123" not in caplog.text


async def test_revert_after_partial_acceptance_repairs_only_the_divergent_phone(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(10), ["phone", "tablet"], {})
    normal_send = instance.send

    async def partial_send(recipient, value):
        if recipient == "tablet" and value["data"].get("progress") == 30:
            raise OSError("offline")
        await normal_send(recipient, value)

    instance.send = partial_send
    await instance.update("washer", payload(30), important=True)
    # The phone has 30 while the tablet still has the old accepted 10.
    await instance.update("washer", payload(10))
    assert instance.records["washer"]["pending"] is not None
    await instance.flush("washer")
    assert calls[-1][0] == "phone"
    assert calls[-1][1]["data"]["progress"] == 10
    assert len([call for call in calls if call[0] == "tablet"]) == 1
    assert instance.records["washer"]["pending"] is None


async def test_complete_then_delayed_clear_and_restart_cancels_old_dismissal(engine):
    instance, calls, clock = engine
    settings = {"completion_delay": 10}
    await instance.start("washer", payload(), ["phone"], settings)
    started = instance.records["washer"]["started_at"]
    await instance.complete("washer", render({}, "washer", complete=True))
    assert instance.records["washer"]["phase"] == "completing"
    assert calls[-1][1]["message"] == "Complete"
    assert ("washer", "dismiss") in instance._timers
    clock.advance(1)
    await instance.start("washer", payload(0), ["phone"], settings)
    assert instance.records["washer"]["phase"] == "running"
    assert instance.records["washer"]["started_at"] == started
    assert ("washer", "dismiss") not in instance._timers
    assert calls[-1][1]["data"]["tag"] == "washer"


async def test_completion_keep_still_has_platform_expiration(engine):
    instance, _, _ = engine
    await instance.start("washer", payload(), ["phone"], {"completion_behavior": "keep"})
    await instance.complete("washer", render({}, "washer", complete=True))
    assert ("washer", "dismiss") not in instance._timers
    assert ("washer", "expire") in instance._timers


async def test_end_is_idempotent_and_uses_documented_clear_command(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(), ["phone"], {})
    await instance.end("washer")
    await instance.end("washer")
    await instance.end("unknown")
    assert len(calls) == 2
    assert calls[-1][1] == {"message": "clear_notification", "data": {"tag": "washer"}}
    assert instance.accounting["phone"]["clears"] == 1
    assert not instance._timers


async def test_restarting_while_clear_is_retrying_supersedes_old_clear(engine):
    instance, calls, _ = engine
    original_send = instance.send

    async def send(recipient, value):
        if value["message"] == "clear_notification":
            raise OSError("offline")
        await original_send(recipient, value)

    instance.send = send
    await instance.start("washer", payload(), ["phone"], {})
    await instance.end("washer")
    assert instance.records["washer"]["phase"] == "ending"
    await instance.start("washer", payload(0), ["phone"], {})
    assert instance.records["washer"]["phase"] == "running"
    assert ("washer", "flush") not in instance._timers
    assert calls[-1][1]["data"]["progress"] == 0


async def test_restore_preserves_tags_without_duplicate_accepted_start(engine):
    instance, calls, clock = engine
    await instance.start("washer", payload(), ["phone"], {})
    snapshot = instance.snapshot()
    await instance.close()
    restored = ActivityEngine(instance.send, lambda: None, now=clock)
    try:
        restored.restore(snapshot)
        await restored.resume()
        assert len(calls) == 1
        assert restored.records["washer"]["payload"]["data"]["tag"] == "washer"
        assert ("washer", "expire") in restored._timers
    finally:
        await restored.close()


async def test_restore_expired_activity_clears_instead_of_restarting(engine):
    instance, calls, clock = engine
    await instance.start("washer", payload(), ["phone"], {})
    snapshot = instance.snapshot()
    await instance.close()
    clock.advance(MAX_AGE_SECONDS + 1)
    restored = ActivityEngine(instance.send, lambda: None, now=clock)
    try:
        restored.restore(snapshot)
        await restored.resume()
        assert calls[-1][1]["message"] == "clear_notification"
        assert restored.records["washer"]["phase"] == "idle"
    finally:
        await restored.close()


async def test_restore_completion_past_display_delay_ends_immediately(engine):
    instance, calls, clock = engine
    await instance.start("washer", payload(), ["phone"], {"completion_delay": 10})
    await instance.complete("washer", render({}, "washer", complete=True))
    snapshot = instance.snapshot()
    await instance.close()
    clock.advance(11)
    restored = ActivityEngine(instance.send, lambda: None, now=clock)
    try:
        restored.restore(snapshot)
        await restored.resume()
        assert calls[-1][1]["message"] == "clear_notification"
        assert restored.records["washer"]["phase"] == "idle"
    finally:
        await restored.close()


async def test_snapshot_is_detached_and_accounting_resets_per_utc_day(engine):
    instance, _, clock = engine
    await instance.start("washer", payload(), ["phone"], {})
    snapshot = instance.snapshot()
    snapshot["records"]["washer"]["phase"] = "broken"
    assert instance.records["washer"]["phase"] == "running"
    clock.advance(86400)
    await instance.update("washer", payload(90, "Complete soon"), important=True)
    assert instance.accounting["phone"]["accepted"] == 1


async def test_quota_warning_is_once_per_device_day(engine, caplog):
    instance, _, _ = engine
    for _ in range(401):
        instance._count("phone", failed=False, clear=False)
    assert caplog.text.count("400 Home Island dispatches") == 1
    assert instance.accounting["phone"]["accepted"] == 401


async def test_close_cancels_timers_and_pending_work_without_sending_clear(engine):
    instance, calls, _ = engine
    await instance.start("washer", payload(), ["phone"], {})
    await instance.update("washer", payload(50))
    assert instance._timers
    await instance.close()
    assert instance.closed
    assert not instance._timers
    assert not instance._tasks
    assert len(calls) == 1
