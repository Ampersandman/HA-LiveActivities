# Migrate from Pushward

Home Island never edits existing Home Assistant configuration. Keep Pushward installed while validating a separate Home Island activity. Export or back up your automation YAML before editing it.

1. In Settings → Devices & Services → Pushward, note tracked entities, start/end states, companion progress/ETA entities, names, icons and device destinations. Search your exported automation and script YAML for `pushward.`. Also inspect visual-editor automations, packages and blueprints.
2. Install Home Island and select the Companion iPhone notification action. Confirm that the installed Companion build offers Live Activities, and that the phone can reach Home Assistant. See [the native API prerequisites](native-api.md).
3. Add a tracked activity through Home Island's configuration UI. Reuse your entity, start/end states and progress source. Choose one of the five supported presets. Use an `mdi:` icon; Pushward SF Symbol names need an equivalent Material Design Icon. Do not enable an automatic tracker and an automation that independently controls the same activity.
4. Keep the existing Pushward automation unchanged. Create a separate Home Island test automation with a different trigger or enable it only for a controlled cycle. Start once, change the status and progress, then finish. Verify that a single card updates in place. Test device-side countdown behavior while the phone is locked. Repeated push-to-start tests can exhaust Apple's separate temporary start budget.
5. Validate final text, completion delay and dismissal. Restart Home Assistant during an activity and confirm recovery. Repeat the test away from home with secure remote Home Assistant access. Service success alone does not prove iPhone delivery.
6. Once all equivalent activities pass, disable the matching Pushward automations and tracked entities. Run a complete real cycle using Home Island. Keep the backup available for rollback.
7. Remove the Pushward integration, unused automations and iOS app only when nothing still depends on them. Revoke the Pushward integration key from its account settings if you no longer use it. Home Island does not need that key.

## Automation examples

The [current Pushward integration](https://github.com/mac-lucky/pushward-hass) separates object registration from template-specific updates. A registration by itself does not display an ongoing activity. Its priority, expiration options and proprietary layouts do not have exact native equivalents. The examples use its documented action names; older installations may still use deprecated `pushward.update_activity` with a `template` field.

Before, for a washing machine:

```yaml
actions:
  - action: pushward.create_activity
    data:
      slug: washer
      name: Washing machine
  - action: pushward.update_activity_generic
    data:
      slug: washer
      state: ongoing
      state_text: Washing
      progress: 0.25
      icon: mdi:washing-machine
```

After, the first content update also starts the native activity:

```yaml
actions:
  - action: home_island.start
    data:
      activity_id: washer
      title: Washing machine
      message: Washing
      preset: generic
      progress: 25
      progress_max: 100
      icon: mdi:washing-machine
  # Later, from another trigger or script:
  - action: home_island.update
    data:
      activity_id: washer
      message: Spinning
      progress: 90
```

For a timer, replace a Pushward countdown update containing `remaining_time: 600` with:

```yaml
action: home_island.start
data:
  activity_id: kitchen_timer
  title: Kitchen timer
  message: Pasta
  preset: countdown
  remaining_seconds: 600
  finish_at_eta: true
```

`remaining_seconds` is normalized to one absolute deadline; the iPhone ticks the timer without one push per second. For automatic tracking of a Home Assistant `timer.*`, choose its `finishes_at` attribute as the ETA source, and configure `active` as a start state and `idle` as an end state. An idle timer after a restart cannot reveal whether it was completed or cancelled during the outage; both safely finish any restored activity.

For final text, replace `pushward.end_activity` with `completion_message` by a final update followed by a delayed end:

```yaml
actions:
  - action: home_island.update
    data:
      activity_id: washer
      message: Laundry is ready
      progress: 100
      completion_delay: 30
  - action: home_island.end
    data:
      activity_id: washer
      immediate: false
```

For immediate dismissal, replace `pushward.delete_activity` with `home_island.end`, passing the same `activity_id` and `immediate: true`. Recipient routing defaults to your Home Island configuration; set `recipients: [notify.mobile_app_my_iphone]` on the start if it needs a different destination.

## Optional offline proposal helper

Run this on a development computer with Python and PyYAML, using a user-exported file. It is not required on Home Assistant Green and has no Home Assistant/network client:

```shell
python tools/migrate_pushward.py exported-automations.yaml --output proposed-automations.yaml
```

The output must be a new file: existing files, including the input, are never overwritten. JSON input/output also works and needs only the Python standard library. The helper prints a proposal and structural warnings; it does not contact Home Assistant, install automations or execute Jinja.

It folds a simple `create_activity` plus first ongoing native-compatible update in the same sequence into `home_island.start`. Later updates become `home_island.update`. It scales literal fractional progress, translates the five supported template names, and traverses nested action sequences. A standalone converted update requires a prior Home Island start.

Unsupported fields/actions remain as their original Pushward action and are explicitly reported. Review every warning and search the proposal for `pushward.` before enabling it. Charts, grids, logs, media controls, approval buttons, images, HTTP tap actions, TTL/priority semantics, templated fractional progress and completion messages require manual decisions. No custom design is silently replaced. Rebuilding the native-compatible information in a fixed Companion layout is a deliberate visual change, even when the data conversion is supported.

Review disabled/conditional actions, parallel branches and dependencies across scripts manually: an offline converter cannot prove runtime equivalence. For full safety, prefer creating one tracked activity in the UI and testing it before migrating automation YAML.
