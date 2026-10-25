"""Persistent, transport independent activity lifecycle and delivery queue."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime, timezone
from functools import partial
from typing import Any

from .const import MAX_AGE_SECONDS
from .models import meaningful, stable_tag

_LOGGER = logging.getLogger(__name__)
Send = Callable[[str, dict[str, Any]], Awaitable[None]]


class ActivityEngine:
    """Own tags, lifecycle, per-device acceptance, retries, and persisted deadlines.

    Send success means that HA accepted the action, never proof of APNs delivery.
    No polling is used: every timer is a pending update or lifecycle deadline.
    """

    def __init__(self, send: Send, save: Callable[[], None], *, now: Callable[[], float] = time.time) -> None:
        self.send = send
        self.save = save
        self.now = now
        self.records: dict[str, dict[str, Any]] = {}
        self.accounting: dict[str, dict[str, Any]] = {}
        self._timers: dict[tuple[str, str], asyncio.TimerHandle] = {}
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self.closed = False

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"records": self.records, "accounting": self.accounting})

    def restore(self, data: dict[str, Any] | None) -> None:
        if data:
            self.records = data.get("records", {})
            self.accounting = data.get("accounting", {})

    def _cancel(self, activity_id: str, kind: str) -> None:
        if handle := self._timers.pop((activity_id, kind), None):
            handle.cancel()

    def _schedule(
        self, activity_id: str, kind: str, at: float, operation: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        self._cancel(activity_id, kind)
        if self.closed:
            return

        def fire() -> None:
            self._timers.pop((activity_id, kind), None)
            if not self.closed:
                task = asyncio.create_task(operation())
                self._tasks.add(task)
                task.add_done_callback(self._task_done)

        self._timers[(activity_id, kind)] = asyncio.get_running_loop().call_later(
            max(0, at - self.now()), fire
        )

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            # Avoid leaking notification text through exception messages.
            _LOGGER.error("An activity background operation failed (%s)", type(task.exception()).__name__)

    async def start(
        self, activity_id: str, payload: dict[str, Any], recipients: list[str], settings: dict[str, Any]
    ) -> None:
        async with self._lock:
            record = self.records.get(activity_id)
            if record and record["phase"] == "running":
                record["settings"] = settings
                # A repeated start is an update, preserving the platform lifetime.
                self._queue(activity_id, payload, important=True)
                await self._flush_locked(activity_id)
                return
            for kind in ("flush", "dismiss", "expire", "countdown"):
                self._cancel(activity_id, kind)
            previous = record or {}
            record = self.records[activity_id] = {
                "phase": "running",
                "started_at": previous.get("started_at", self.now())
                if previous.get("phase") == "completing"
                else self.now(),
                "last_sent": 0,
                "recipients": list(dict.fromkeys(recipients)),
                "settings": settings,
                "accepted": previous.get("accepted", {}) if previous.get("phase") == "completing" else {},
                "pending": payload,
                "payload": payload,
                "retry": 0,
                "entity_state": previous.get("entity_state"),
            }
            self.save()
            self.arm_expiration(activity_id)
            await self._flush_locked(activity_id)

    def arm_expiration(self, activity_id: str) -> None:
        record = self.records[activity_id]
        if record["phase"] in ("running", "completing"):
            self._schedule(
                activity_id, "expire", record["started_at"] + MAX_AGE_SECONDS, lambda: self.end(activity_id)
            )

    async def update(self, activity_id: str, payload: dict[str, Any], *, important: bool = False) -> None:
        async with self._lock:
            record = self.records.get(activity_id)
            if not record or record["phase"] != "running":
                return
            self._queue(activity_id, payload, important=important)
            if important:
                self._cancel(activity_id, "flush")
                await self._flush_locked(activity_id)

    def _queue(self, activity_id: str, payload: dict[str, Any], *, important: bool) -> None:
        record = self.records[activity_id]
        record["payload"] = payload
        baseline = record.get("last_payload")
        diverged = baseline is not None and any(
            record["accepted"].get(recipient) != baseline for recipient in record["recipients"]
        )
        if (
            baseline
            and not meaningful(
                baseline,
                payload,
                float(record["settings"].get("change_threshold", 5)),
                preset=record["settings"].get("preset", ""),
            )
            and not diverged
        ):
            # Reverting to the accepted state also cancels a pending cosmetic update.
            record["pending"] = None
            record.pop("pending_since", None)
            record.pop("pending_since", None)
            self._cancel(activity_id, "flush")
            self.save()
            return
        record["pending"] = payload
        record.setdefault("pending_since", self.now())
        record["retry"] = 0
        self.save()
        if important:
            return
        settings = record["settings"]
        due = max(
            record["last_sent"] + float(settings.get("min_update_interval", 60)),
            record["pending_since"] + float(settings.get("debounce_seconds", 2)),
        )
        self._schedule(activity_id, "flush", due, lambda: self.flush(activity_id))

    async def flush(self, activity_id: str) -> None:
        async with self._lock:
            await self._flush_locked(activity_id)

    def _count(self, recipient: str, *, failed: bool, clear: bool) -> None:
        day = datetime.fromtimestamp(self.now(), timezone.utc).date().isoformat()
        counters = self.accounting.setdefault(recipient, {})
        if counters.get("utc_day") != day:
            counters.update(utc_day=day, accepted=0, failed=0, clears=0, warned=False)
        key = "failed" if failed else "clears" if clear else "accepted"
        counters[key] += 1
        if counters["accepted"] >= 400 and not counters["warned"]:
            counters["warned"] = True
            _LOGGER.warning(
                "A recipient reached 400 Home Island dispatches today; increase update intervals. Other integrations also consume the 500/day cloud allowance"
            )

    async def _flush_locked(self, activity_id: str) -> None:
        record = self.records.get(activity_id)
        if not record or not record.get("pending") or self.closed:
            return
        payload = record["pending"]
        failed = False
        for recipient in record["recipients"]:
            if record["accepted"].get(recipient) == payload:
                continue
            try:
                async with asyncio.timeout(30):
                    await self.send(recipient, copy.deepcopy(payload))
            except (Exception, TimeoutError) as error:
                failed = True
                self._count(recipient, failed=True, clear=False)
                _LOGGER.warning(
                    "Companion notification action failed (%s); a bounded retry is queued",
                    type(error).__name__,
                )
            else:
                record["accepted"][recipient] = copy.deepcopy(payload)
                self._count(recipient, failed=False, clear=payload["message"] == "clear_notification")
        if failed:
            record["retry"] += 1
            if record["retry"] <= 5:
                self._schedule(
                    activity_id,
                    "flush",
                    self.now() + min(300, 5 * 2 ** (record["retry"] - 1)),
                    lambda: self.flush(activity_id),
                )
        else:
            record["pending"] = None
            record.pop("pending_since", None)
            record["last_payload"] = copy.deepcopy(payload)
            record["last_sent"] = self.now()
            record["retry"] = 0
            if record["phase"] == "ending":
                record["phase"] = "idle"
        self.save()

    async def complete(self, activity_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            record = self.records.get(activity_id)
            if not record or record["phase"] != "running":
                return
            self._cancel(activity_id, "flush")
            self._cancel(activity_id, "countdown")
            record.update(phase="completing", payload=payload, pending=payload, retry=0)
            delay = float(record["settings"].get("completion_delay", 10))
            record["dismiss_at"] = self.now() + delay
            if record["settings"].get("completion_behavior", "dismiss") == "dismiss":
                self._schedule(activity_id, "dismiss", record["dismiss_at"], lambda: self.end(activity_id))
            self.save()
            await self._flush_locked(activity_id)

    async def end(self, activity_id: str) -> None:
        async with self._lock:
            record = self.records.get(activity_id)
            if not record or record["phase"] == "idle":
                return
            for kind in ("flush", "dismiss", "expire", "countdown"):
                self._cancel(activity_id, kind)
            record.update(
                phase="ending",
                pending={"message": "clear_notification", "data": {"tag": stable_tag(activity_id)}},
                retry=0,
            )
            self.save()
            await self._flush_locked(activity_id)

    async def resume(self, *, skip_pending: set[str] | None = None) -> None:
        """Restore work without resending already accepted identical payloads."""
        for activity_id, record in list(self.records.items()):
            if record["phase"] == "idle":
                continue
            if self.now() >= record["started_at"] + MAX_AGE_SECONDS:
                await self.end(activity_id)
                continue
            self.arm_expiration(activity_id)
            if (
                record["phase"] == "completing"
                and record["settings"].get("completion_behavior", "dismiss") == "dismiss"
            ):
                if record["dismiss_at"] <= self.now():
                    await self.end(activity_id)
                    continue
                self._schedule(activity_id, "dismiss", record["dismiss_at"], partial(self.end, activity_id))
            if record.get("pending") and activity_id not in (skip_pending or set()):
                await self.flush(activity_id)

    async def close(self) -> None:
        self.closed = True
        for handle in self._timers.values():
            handle.cancel()
        self._timers.clear()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
