# Architecture

## Decision and feasibility

| Approach | Green/HA OS backend | App requirement | Layout control | Delivery | Implementation |
| --- | --- | --- | --- | --- | --- |
| A: Companion | Normal HACS integration | Existing Companion | Fixed native fields | HA notify → local/relay → APNs where needed | Free MVP |
| B: custom ActivityKit | Integration can eventually be APNs provider | Separately signed app + WidgetKit extension | Original SwiftUI views | Direct Apple APNs, token registration/auth required | Local source prototype only; remote provider deferred |

The [native API](native-api.md) is the most practical free path. It needs no new server, public webhook, Apple membership or Python installation on Green. It removes Pushward but retains the installed Companion app and delivery infrastructure. The custom app must not become a free-MVP dependency.

## Module boundaries

`models.py` validates plain configuration and renders complete native payload snapshots. `engine.py` is independent of HA imports: it owns activity phases, stable identity, scheduling, per-recipient deduplication, retry and serializable state. Its async sender callback can later be implemented by another transport. `manager.py` adapts HA entity events, config entries, Store, notify services, startup and shutdown. `config_flow.py` implements setup and a multi-form options editor; there is one integration entry with multiple persisted tracker configurations. `services.py` exposes validated manual actions. `diagnostics.py` returns numeric and phase-only information.

There is no network client, credential store, thread worker, polling scheduler or extra runtime dependency in Approach A. `Store.async_load/async_save/async_delay_save` handle private persistence without synchronous file access. App/token management belongs to the Companion integration.

## State machine

| Phase | Trigger | Result |
| --- | --- | --- |
| Idle / absent | Configured start state or manual start | Running, same deterministic tag |
| Running | State or source event | Render full latest snapshot; suppress duplicates; queue cosmetic changes |
| Running | End state / countdown deadline / delayed manual end | Completing; final status; schedule dismissal unless keep selected |
| Completing | A real end→start transition | Cancel dismissal; Running, reusing the still-existing activity |
| Running / Completing | Explicit end / expiration / dismissal deadline | Ending; send `clear_notification` with tag |
| Ending | All recipients accept clear | Idle |
| Ending | New cycle starts | Supersede pending clear; Running |

Lifecycle operations and send acceptance are serialized in the engine. HA reconciliations have a separate per-activity lock, so a suspended notify call cannot race another state reconciliation into overwriting the last observed state. Timers are cancellable handles and all asynchronous tasks are tracked for unload.

The platform age remains anchored to the initial start if a cycle restarts before dismissal, because reusing an existing native activity cannot reset Apple's lifetime. A 7h55m deadline leaves margin before iOS's eight-hour limit. It is a local cleanup policy, not a promise that iOS will keep any activity visible that long.

## Sending and recovery

The pending payload always represents the latest meaningful state. Debounce waits from the beginning of a burst; the minimum interval bounds cosmetic sends. Subthreshold progress accumulates against the last accepted snapshot. Status changes and lifecycle operations take priority. Color threshold crossings are meaningful presentation changes. Duplicate acceptance is tracked separately for each recipient, so retrying a failed phone does not re-send to one that already accepted the payload.

Backoff is 5, 10, 20, 40, and 80 seconds, with at most five scheduled retries after an initial failure. Later events or a restart can reattempt pending work. A missing notify action is surfaced as a retryable error. Core's own swallowed remote errors cannot be retried reliably, and APNs/device receipt is not observable here.

After HA startup, removed/disabled trackers and changed recipient routes are cleared, then current entity state is reconciled before retrying stale pending running payloads. Unknown/missing entities preserve runtime state without sending old pending content. A completion deadline survives restart. Remaining-time sources are converted to a persisted absolute deadline, avoiding countdown resets after restart or unrelated entity events. Native timer `finishes_at` and ETA timestamps are already absolute.

Private runtime storage includes payloads so exact retry and restoration are possible. Diagnostics deliberately omit content, IDs and token data. No Apple private keys or Pushward credentials are used. The [optional remote-app design](ios-feasibility.md) describes additional authentication/security requirements; those endpoints are not implemented or exposed by the MVP.
