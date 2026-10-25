# Verification and remaining device checks

Verification performed on 25 October 2026. No connection to the user's live Home Assistant or iPhone was made, and no existing Pushward configuration was changed.

## Executed automated checks

The full integration suite runs in **Ubuntu 24.04 under WSL**, using **CPython 3.14.9**, **Home Assistant Core 2026.10.4**, and `pytest-homeassistant-custom-component==0.13.375`. These are real Home Assistant fixtures, not a replacement HA implementation. Notification actions are mocked; `mobile_app` dependency startup is isolated in config-flow tests so unrelated camera/cloud dependencies do not run.

The final complete suite includes multi-device divergence, route migration, countdown-anchor recovery and quiet-payload regressions.

```text
140 passed in 36.91 seconds
Combined line coverage: 90% (integration + migration helper)
Ruff lint: passed
Ruff format: 20 Python files already formatted
Mypy: passed for the four configured source modules
```

Ruff lint and format checks pass. Mypy passes for the explicitly configured transport/model/engine/migration modules; this is not a claim that every dynamically typed HA adapter method has strict type coverage. YAML/JSON installation files and English translations are parsed by tests. The checked Core 2026.7.0 source exposes the APIs used here, but the full runtime suite has only executed on 2026.10.4.

The tests exercise config/options persistence, multiple trackers, lifecycle/tag reuse, all native presets, number/time conversion, malformed/missing states, debounce/coalescing, percentage thresholds, per-device duplicate suppression, partial failures, bounded retries, completion/restart races, absolute countdown persistence, outage completion, route changes, manual actions, schema rejection, expiration, and listener/task/timer cleanup. The migration tests exercise conservative conversion, unsupported-template retention, nesting, non-mutation, output-file protection and redacted warnings.

Reproduction:

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q --timeout=30 --cov=custom_components.home_island --cov=tools.migrate_pushward
.venv/bin/ruff check custom_components tools tests
.venv/bin/ruff format --check custom_components tools tests
.venv/bin/mypy
```

On this Windows host, `tools/setup_linux_tests.sh` created an ignored workspace-local WSL toolchain. It is a development convenience, and is not part of installation on Home Assistant Green. Native Windows HA fixture loading failed on HA's Unix-only `fcntl` import; no shims were used to hide that failure.

## iOS source prototype

`ios/` contains local Generic and Board ActivityKit controls and WidgetKit views, mock previews, shared models, and XcodeGen/xtool configurations. Both plist files and YAML target/path/bundle/extension metadata were checked. A separate static code review checked lifecycle cancellation and the source was corrected accordingly.

**Swift compilation, Apple SDK builds, simulator execution, signing, physical iPhone display and APNs delivery have not run.** No Apple SDK, Xcode, xtool or signing account is available here. The source prototype has no remote provider or authenticated token exchange. These are documented follow-up work in [iOS feasibility](ios-feasibility.md) and [the prototype README](../ios/README.md). Do not describe source previews or metadata parsing as a successful app build.

## Physical Home Assistant Green / iPhone acceptance

Perform this with Pushward still enabled for rollback, using a separate test activity:

1. Install `custom_components/home_island`, restart HA, add Home Island and select the actual iPhone notify action. Verify a Companion build with Live Activities and iOS permission is present.
2. Run `home_island.test`. Confirm a single card appears, then completes and dismisses. Check Lock Screen and all available Dynamic Island modes.
3. Create a tracker with an entity you can safely control (a helper or a test timer is sufficient). Start it, change status/progress, then end it. Confirm the card updates in place and the final status lasts for the configured delay.
4. Test countdown, Gauge, Steps and Alert separately. Confirm actual layout, icon/color support, relevance beta behavior, tap URL and accessibility on the installed app version. A timer may replace the message region.
5. Test two recipients and two simultaneous activities. Ensure each tag stays distinct and activities do not duplicate.
6. Restart HA while running, during completion, and after an entity completes during an outage. Confirm current state is reconciled and a previously displayed countdown does not reset.
7. Complete and immediately start a new cycle. Confirm the old dismissal never clears the new run. Change a configured recipient and confirm old-route cleanup and new-route creation.
8. Test locked/background behavior on home Wi-Fi, then away from home using existing secure HA access. Check the Companion token handshake and any Local Push/APNs fallback. A successful HA action alone does not establish display.
9. Review dispatch diagnostics alongside Companion's authoritative push counter. Confirm configured update rates are reasonable alongside your other notification automations.
10. Only then disable equivalent Pushward automations, validate a real full cycle, and follow [the migration guide](migration.md) before removing Pushward.

Repository metadata points to [Ampersandman/HA-LiveActivities](https://github.com/Ampersandman/HA-LiveActivities), maintained by [@Ampersandman](https://github.com/Ampersandman). Use that URL as a HACS custom repository with category Integration, or copy `custom_components/home_island` to `/config/custom_components/home_island` manually. A default HACS store listing, hosted HACS validation/hassfest, and downloading or installing through HACS have not been verified here.
