"""Home Assistant adapter for the reusable activity engine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import DOMAIN, MAX_AGE_SECONDS
from .engine import ActivityEngine
from .models import INVALID_STATES, deadline, render, validate_config

_LOGGER = logging.getLogger(__name__)


class HomeIslandManager:
    """Keep HA listeners, services, persistence and rendering outside the engine."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.engine = ActivityEngine(self._send, self._save)
        self.configs: dict[str, dict[str, Any]] = {}
        self._unsubs: list = []
        self._tasks: set[asyncio.Task] = set()
        self._remaining_cache: dict[str, tuple[Any, float | None]] = {}
        self._reconcile_locks: dict[str, asyncio.Lock] = {}
        self._closed = False

    @property
    def recipients(self) -> list[str]:
        return self.entry.options.get("recipients", self.entry.data.get("recipients", []))

    @callback
    def _save(self) -> None:
        if not self._closed:
            self.store.async_delay_save(self.engine.snapshot, 1)

    async def _send(self, recipient: str, payload: dict[str, Any]) -> None:
        service = recipient.removeprefix("notify.")
        if not self.hass.services.has_service("notify", service):
            raise HomeAssistantError("Companion notification action is unavailable")
        await self.hass.services.async_call("notify", service, payload, blocking=True)

    async def async_setup(self) -> None:
        self.engine.restore(await self.store.async_load())
        for config in self.entry.options.get("activities", []):
            try:
                if not isinstance(config.get("id"), str) or not isinstance(config.get("entity_id"), str):
                    raise ValueError("Missing tracker identifier")
                validate_config(config)
            except (ValueError, TypeError, KeyError):
                _LOGGER.warning("A saved tracker has invalid settings and was skipped")
                continue
            if config.get("enabled", True):
                self.configs["tracker_" + config["id"]] = config
        entities = set()
        for config in self.configs.values():
            for key in ("entity_id", "progress_entity", "remaining_entity", "eta_entity", "subtitle_entity"):
                if config.get(key):
                    entities.add(config[key])
        if entities:
            self._unsubs.append(async_track_state_change_event(self.hass, entities, self._state_changed))
        self._unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._stopping))
        if self.hass.is_running:
            await self._async_restore()
        else:
            self._unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._started))

    @callback
    def _spawn(self, coro) -> None:
        if self._closed:
            coro.close()
            return
        task = self.entry.async_create_background_task(self.hass, coro, "Home Island state change")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            _LOGGER.error("Activity reconciliation failed (%s)", type(task.exception()).__name__)

    @callback
    def _started(self, event) -> None:
        self._spawn(self._async_restore())

    async def _stopping(self, event) -> None:
        await self.async_close()

    async def _async_restore(self) -> None:
        for activity_id, record in list(self.engine.records.items()):
            if activity_id.startswith("tracker_") and activity_id not in self.configs:
                await self.engine.end(activity_id)
            elif activity_id in self.configs and record["recipients"] != list(
                dict.fromkeys(self.configs[activity_id].get("recipients") or self.recipients)
            ):
                await self.engine.end(activity_id)
                # A deliberate route change starts a fresh activity on the new phones.
                record["entity_state"] = None
        for activity_id in self.configs:
            await self._reconcile(activity_id, initial=True)
        unavailable = {
            activity_id
            for activity_id, config in self.configs.items()
            if not (state := self.hass.states.get(config["entity_id"])) or state.state in INVALID_STATES
        }
        await self.engine.resume(skip_pending=unavailable)
        for activity_id, record in self.engine.records.items():
            if not activity_id.startswith("tracker_") and record["phase"] == "running":
                self._arm_countdown(
                    activity_id,
                    record["settings"],
                    record.get("countdown_at", record.get("payload", {}).get("data", {}).get("when")),
                )

    @callback
    def _state_changed(self, event) -> None:
        changed = event.data["entity_id"]
        for activity_id, config in self.configs.items():
            watched = {
                config.get(key)
                for key in (
                    "entity_id",
                    "progress_entity",
                    "remaining_entity",
                    "eta_entity",
                    "subtitle_entity",
                )
            }
            if changed in watched:
                self._spawn(self._reconcile(activity_id))

    def _source(self, config: dict[str, Any], kind: str) -> tuple[Any, str]:
        state = self.hass.states.get(config.get(kind + "_entity") or config["entity_id"])
        if state is None or state.state in INVALID_STATES:
            return None, "s"
        attribute = config.get(kind + "_attribute")
        value = state.attributes.get(attribute) if attribute else state.state
        return value, state.attributes.get("unit_of_measurement", "s")

    def _payload(
        self, activity_id: str, config: dict[str, Any], *, complete: bool = False, new_cycle: bool = False
    ) -> tuple[dict[str, Any], float | None]:
        state = self.hass.states.get(config["entity_id"])
        progress = (
            self._source(config, "progress")[0]
            if config.get("progress_entity") or config.get("progress_attribute")
            else None
        )
        subtitle = (
            self._source(config, "subtitle")[0]
            if config.get("subtitle_entity") or config.get("subtitle_attribute")
            else config.get("subtitle", "")
        )
        end_at = None
        if config.get("eta_entity") or config.get("eta_attribute"):
            value, _ = self._source(config, "eta")
            end_at = deadline(value, self.engine.now(), absolute=True)
        elif (
            config.get("remaining_entity")
            or config.get("remaining_attribute")
            or config["entity_id"].startswith("timer.")
        ):
            if config["entity_id"].startswith("timer.") and not (
                config.get("remaining_entity") or config.get("remaining_attribute")
            ):
                value = state.attributes.get("finishes_at") if state else None
                end_at = deadline(value, self.engine.now(), absolute=True)
            else:
                value, unit = self._source(config, "remaining")
                # Reuse absolute deadline until source value changes; other events do not reset timers.
                source_key = (value, unit)
                cached = self._remaining_cache.get(activity_id)
                if cached and cached[0] == source_key:
                    end_at = cached[1]
                else:
                    end_at = deadline(value, self.engine.now(), unit=unit)
                    self._remaining_cache[activity_id] = (source_key, end_at)
                record = self.engine.records.get(activity_id)
                if record is not None:
                    if not new_cycle and record.get("remaining_source") == list(source_key):
                        end_at = record.get("remaining_deadline")
                        self._remaining_cache[activity_id] = (source_key, end_at)
                    else:
                        record.update(remaining_source=list(source_key), remaining_deadline=end_at)
        return render(
            config,
            activity_id,
            status=state.state if state else "",
            progress=progress,
            end_at=end_at,
            subtitle=str(subtitle) if subtitle is not None else "",
            complete=complete,
        ), end_at

    async def _reconcile(self, activity_id: str, *, initial: bool = False) -> None:
        async with self._reconcile_locks.setdefault(activity_id, asyncio.Lock()):
            await self._reconcile_locked(activity_id, initial=initial)

    async def _reconcile_locked(self, activity_id: str, *, initial: bool = False) -> None:
        if self._closed:
            return
        config = self.configs[activity_id]
        state = self.hass.states.get(config["entity_id"])
        if not state or state.state in INVALID_STATES:
            return
        record = self.engine.records.get(activity_id)
        previous = record.get("entity_state") if record else None
        phase = record["phase"] if record else "idle"
        start_states = config.get("start_states", ["on"])
        end_states = config.get("end_states", ["off"])
        if state.state in end_states:
            if phase == "running":
                payload, _ = self._payload(activity_id, config, complete=True)
                await self.engine.complete(activity_id, payload)
        elif phase == "running":
            assert record is not None
            if self.engine.now() >= record["started_at"] + MAX_AGE_SECONDS:
                await self.engine.end(activity_id)
                record["entity_state"] = state.state
                self._save()
                return
            payload, end_at = self._payload(activity_id, config)
            record["settings"] = dict(config)
            # State text changes are important; source-only changes are cosmetic.
            await self.engine.update(activity_id, payload, important=previous != state.state)
            self._arm_countdown(activity_id, config, end_at)
        elif state.state in start_states and (
            phase in ("idle", "ending")
            and (previous != state.state or previous is None)
            or phase == "completing"
            and previous in end_states
        ):
            self._remaining_cache.pop(activity_id, None)
            payload, end_at = self._payload(activity_id, config, new_cycle=True)
            recipients = config.get("recipients") or self.recipients
            if recipients:
                await self.engine.start(activity_id, payload, recipients, dict(config))
                if cached := self._remaining_cache.get(activity_id):
                    self.engine.records[activity_id].update(
                        remaining_source=list(cached[0]), remaining_deadline=cached[1]
                    )
                self._arm_countdown(activity_id, config, end_at)
        if record := self.engine.records.get(activity_id):
            record["entity_state"] = state.state
            self._save()

    def _arm_countdown(self, activity_id: str, config: dict[str, Any], end_at: float | None) -> None:
        self.engine._cancel(activity_id, "countdown")
        record = self.engine.records.get(activity_id)
        if record is not None:
            record["countdown_at"] = end_at
            self._save()
        if end_at is None or not config.get("finish_at_eta", config.get("preset") == "countdown"):
            return

        async def complete() -> None:
            if config.get("entity_id"):
                payload, _ = self._payload(activity_id, config, complete=True)
            else:
                payload = render(config, activity_id, complete=True)
            await self.engine.complete(activity_id, payload)

        self.engine._schedule(activity_id, "countdown", end_at, complete)

    async def async_manual(self, action: str, data: dict[str, Any]) -> None:
        activity_id = "manual_" + data.get("activity_id", "home_island_test")
        record = self.engine.records.get(activity_id)
        if action == "end":
            if record and not data.get("immediate", True):
                final_settings = {
                    **record["settings"],
                    "completion_message": record["settings"].get("message", "Complete"),
                }
                await self.engine.complete(activity_id, render(final_settings, activity_id, complete=True))
            else:
                await self.engine.end(activity_id)
            return
        if action == "update" and (not record or record["phase"] != "running"):
            raise ServiceValidationError("Start this activity before updating it")
        settings = dict(record["settings"]) if record and action == "update" else {}
        settings.update(
            {key: value for key, value in data.items() if key not in ("activity_id", "immediate")}
        )
        if record and record["phase"] == "running":
            settings["title"] = record["payload"]["title"]
            if "recipients" in data and list(dict.fromkeys(data["recipients"])) != record["recipients"]:
                raise ServiceValidationError("End the activity before changing its recipients")
        try:
            validate_config(settings)
        except (ValueError, TypeError) as error:
            raise ServiceValidationError(str(error)) from error
        recipients = settings.get("recipients") or self.recipients
        if not recipients:
            raise ServiceValidationError("Select a Companion recipient in Home Island options")
        end_at = settings.get("when")
        if "remaining_seconds" in data:
            end_at = deadline(data["remaining_seconds"], self.engine.now())
            settings["when"] = end_at
        if action == "test":
            settings.setdefault("title", "Home Island test")
            settings.setdefault("message", "Native Companion Live Activity")
            settings.setdefault("progress", 50)
            settings["finish_at_eta"] = True
            end_at = self.engine.now() + 30
        payload = render(settings, activity_id, end_at=end_at)
        if action == "update":
            assert record is not None
            record["settings"] = settings
            await self.engine.update(activity_id, payload)
        else:
            await self.engine.start(activity_id, payload, recipients, settings)
        self._arm_countdown(activity_id, settings, end_at)

    async def async_test(self, activity_id: str) -> None:
        config = self.configs.get("tracker_" + activity_id)
        if not config:
            raise ServiceValidationError("Enable the tracker before testing")
        payload, _ = self._payload("test_" + activity_id, config)
        test_id = "test_" + activity_id
        settings = {**config, "finish_at_eta": True, "completion_delay": 5}
        await self.engine.start(test_id, payload, config.get("recipients") or self.recipients, settings)
        self._arm_countdown(test_id, settings, self.engine.now() + 30)

    async def async_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await self.engine.close()
        await self.store.async_save(self.engine.snapshot())

    def diagnostics(self) -> dict[str, Any]:
        """Only numeric counts and lifecycle phases; no IDs, payloads or tokens."""
        return {
            "tracker_count": len(self.configs),
            "activities": [
                {
                    "phase": rec["phase"],
                    "recipient_count": len(rec["recipients"]),
                    "retry": rec["retry"],
                    "pending": rec.get("pending") is not None,
                }
                for rec in self.engine.records.values()
            ],
            "devices": [dict(counters) for counters in self.engine.accounting.values()],
            "pending_timers": len(self.engine._timers),
        }
