# Home Island

Home Assistant Live Activities on your iPhone, using the Companion App you already have. Home Island runs as a normal custom integration on Home Assistant Green / Home Assistant OS. No Pushward account, API, subscription, add-on, extra server, or new Apple Developer membership is needed.

**Status: executable MVP with automated tests; physical iPhone and Home Assistant Green validation is still required.** It uses the Companion App's existing layouts. Rich charts, tiles, artwork and interactive approval controls require a separate iOS extension; see the [compatibility matrix](docs/feature-parity.md).

## Requirements

- Home Assistant Core **2026.7.0 or newer**.
- iPhone with **iOS 17.2+**, registered in the Home Assistant Companion App, with its `notify.mobile_app_*` action available.
- A current Companion version containing native Live Activities. Availability/settings can vary by release and beta channel; the [official documentation](https://companion.home-assistant.io/docs/notifications/live-activities/) still flags beta features. If the feature is absent, check the Companion release notes/TestFlight rather than assuming installation of this integration can add it.
- Notifications and Live Activities allowed in iOS settings. Open the Companion App once after setup so it can register tokens.
- The phone must reach your Home Assistant for the Live Activity token handshake. Away from home this requires an existing secure remote connection (for example your existing remote URL or VPN).

Native delivery still uses Home Assistant's push infrastructure and Apple's APNs when needed. Home Assistant's hosted allowance is 500 notifications/device/day, independent of Apple's update budgets. Local Push has background restrictions and cannot guarantee fully local Live Activity creation. See the [verified native API notes](docs/native-api.md).

## Install on Home Assistant Green

### Manual installation — usable from this checkout

1. Copy **only** [`custom_components/home_island`](custom_components/home_island/) into `/config/custom_components/home_island` on Home Assistant. The File editor/Studio Code Server app or a Samba share can copy the files; do not copy development virtual environments or `ios/`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Home Island**.
4. Select one or more iPhone Companion notification actions. Unmatched registrations are labeled so you can verify the device; known Android registrations are excluded.
5. Open **Configure → Add tracked activity** on the integration and follow the forms.

You do not install Python or build anything on Home Assistant Green. Home Assistant supplies the runtime and dependencies.

### HACS

Repository: [Ampersandman/HA-LiveActivities](https://github.com/Ampersandman/HA-LiveActivities), maintained by [@Ampersandman](https://github.com/Ampersandman).

Open **HACS → Custom repositories**, add **https://github.com/Ampersandman/HA-LiveActivities** with category **Integration**, download Home Island and restart Home Assistant. Then add Home Island under **Settings → Devices & services**. For manual installation, copy `custom_components/home_island` to `/config/custom_components/home_island` as described above. This is a custom repository, with no claimed default-store listing; downloading and installing through HACS have not been tested here.

## Quick start: washing machine

In **Configure → Add tracked activity**:

| Setting | Example |
| --- | --- |
| Entity | `sensor.washer_status` |
| Name / preset | `Washing machine` / `generic` |
| Start states | `washing,rinsing,spinning` (use your entity's exact states) |
| End states | `complete,off` |
| Icon | `mdi:washing-machine` |
| Progress entity | `sensor.washer_progress` (0–100) |
| Remaining time entity | `sensor.washer_remaining` (seconds; units min/h also accepted) |
| Minimum interval / threshold | `60` seconds / `5` percentage points |
| Completion display delay | `10` seconds |
| Dashboard URL | `/lovelace/laundry` |

You can instead select an attribute on the tracked entity, or a separate entity and attribute. ETA accepts timezone-aware timestamps or Unix seconds. Remaining time accepts seconds, `MM:SS`, `H:MM:SS`, or timezone-aware timestamps. A native `timer.*` automatically reads its `finishes_at` attribute. The device animates the countdown; Home Island does not push every second. Turn off **Finish at ETA** if only the appliance's explicit end state should complete it.

Use **Configure → Test activity** to send a separate temporary activity. Test start, progress, completion, and dismissal on your iPhone before disabling Pushward. A test completes after 30 seconds. The same options menu edits, enables/disables, and removes trackers. Settings persist in the config entry; runtime recovery uses HA's private `.storage` directory.

## Automation actions

Manual activities do not need a tracker. Configure Home Island once to establish default recipients, then use Developer Tools → Actions:

```yaml
action: home_island.start
data:
  activity_id: laundry
  title: Washing machine
  message: Washing
  icon: mdi:washing-machine
  progress: 15
  progress_max: 100
  remaining_seconds: 2700
  url: /lovelace/laundry
```

```yaml
action: home_island.update
data:
  activity_id: laundry
  message: Rinsing
  progress: 65
```

```yaml
action: home_island.end
data:
  activity_id: laundry
  immediate: false  # show the last message, then dismiss after completion_delay
```

`home_island.end` defaults to immediate dismissal. `home_island.test` works without arguments. Reuse an ID to update its existing activity; distinct IDs create simultaneous activities. Updates merge previous settings, so an omitted countdown deadline does not restart. Titles stay stable while running for compatibility. Manual updates follow the same debounce/threshold settings; start/end and tracked state transitions have priority. `update` requires a running manual activity.

See [`services.yaml`](custom_components/home_island/services.yaml), [complete automation examples](examples/automations.yaml), and the [Pushward migration guide](docs/migration.md). The offline migration helper proposes YAML and never calls Home Assistant.

## Presentations

- **Generic:** title, status, icon, optional progress and chronometer.
- **Countdown:** device-side countdown with optional progress and scheduled completion.
- **Gauge:** min/max/value mapped to an integer native progress bar; numeric value in text, configurable color thresholds.
- **Alert:** visual severity, message and dashboard link. Severity does not send critical alerts.
- **Steps:** current step, total steps, description and calculated progress bar.

These are presets of Companion's fixed UI. The chronometer can occupy the status area; Dynamic Island chooses its own compact/minimal/expanded content. Native payloads cannot define custom charts, tiles or controls.

## Efficiency, recovery and diagnostics

Entity events drive updates; no polling loop runs. Cosmetic changes are coalesced and compared against the last accepted payload. Default 60-second minimum intervals and 5-point progress thresholds suit short appliance cycles. For activities running all day, consider at least 180–300 seconds; other automations share the 500/day cloud allowance. Important lifecycle/status transitions can exceed the cosmetic rate limit.

The engine persists tags, pending payloads, recipient acceptance and completion deadlines. It reconciles entity state after HA starts, suppresses identical restored sends, retries surfaced failures with bounded backoff and cancels a delayed dismissal when a new cycle starts. It clears activities before eight hours instead of pretending iOS allows indefinite sessions. An entity still active after expiry needs an end/start transition to begin a new session. Completion during an outage is reconciled when HA returns; no remote background code can execute while HA is offline.

An accepted notify action is **not** an iPhone delivery receipt: Core may log remote delivery failures without raising. Home Island reports conservative per-device accepted-dispatch counts, failures and clears, warns at 400/day, and cannot measure your exact remaining relay quota. Integration diagnostics contain counts and phases, without notification content, entity IDs, recipient names, URLs, or tokens. HA service traces and your private HA storage can still contain your configured notification text.

Reload/unload removes listeners, tasks and timers while preserving runtime state for recovery. Disabling/removing a tracker clears its previous recipients on reload. Missing/unavailable entities do not start activities; an already running one remains subject to the lifetime limit. Renamed entity IDs need updating in Configure. Device connectivity and iOS policies can delay delivery.

## Development and verification

The integration has no third-party runtime requirements. Pure model/engine/migration tests can run independently; full HA fixtures require Linux and Python 3.14.2+ for the pinned current Core.

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check custom_components tools tests
.venv/bin/ruff format --check custom_components tools tests
.venv/bin/mypy
```

For a lightweight unit-only environment, install `requirements-test-unit.txt`, then run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/test_models.py tests/test_engine.py tests/test_migration.py`.

See [architecture](docs/architecture.md), [verification results and physical-device checklist](docs/verification.md), and [optional iOS feasibility](docs/ios-feasibility.md). The advanced iOS work is isolated from the free MVP. No paid provisioning, APNs credentials or unauthenticated endpoints are part of this integration.

## License

MIT. Home Island is an independent project and is not affiliated with Pushward, Apple, Nabu Casa, or Home Assistant. No proprietary Pushward code or branding is included.
