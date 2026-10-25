# Native notification contract

Verified on 2026-10-25 against the [Companion documentation](https://companion.home-assistant.io/docs/notifications/live-activities/) and the source references below. Home Island uses the existing Companion integration; it does not register its own APNs tokens or contact Pushward.

```yaml
action: notify.mobile_app_my_iphone
data:
  title: Washing machine
  message: Rinsing
  data:
    tag: home-island-washer
    live_update: true
    progress: 40
    progress_max: 100
    chronometer: true
    when: 1792936800 # example absolute Unix timestamp; supply the actual deadline
    when_relative: false
    notification_icon: mdi:washing-machine
    notification_icon_color: "#2196F3"
    background_color: "#101820"
    text_color: "#FFFFFF"
    progress_bar_color: "#2196F3"
    progress_bar_direction: increasing
    relevance_score: 0.5
    critical_text: Rinsing
    url: /lovelace/laundry
    silent: true
    alert_once: true
```

Only `title` and `message` belong at the outer notification level. A start and subsequent updates reuse the same tag, containing 1–64 ASCII letters, digits, hyphens or underscores. Home Island validates its own values more strictly than the app's permissive decoder: finite numbers, positive progress maximum, bounded progress, and relevance in 0–1. Integers are used for progress. Colors use hex values. The activity header remains stable for compatibility with app versions that treat it as a creation attribute.

End using the documented notification command, with no invented end flag:

```yaml
action: notify.mobile_app_my_iphone
data:
  message: clear_notification
  data:
    tag: home-island-washer
```

The [native payload parser](https://github.com/home-assistant/iOS/blob/98dc06438125cdf65ea7816c83a0c846a9447526/Sources/Shared/Notifications/NotificationCommands/HandlerLiveActivity.swift) treats `when` as Unix seconds unless `when_relative` is true, in which case it adds the value to receipt time. Home Island favors absolute deadlines, preserving the countdown anchor across updates and retries. `chronometer` enables device-side ticking; it is independent of activity expiration. Main-branch support for a negative relative value is intentionally not used because the published contract does not document that extension.

## Rendering and prerequisites

Use Core 2026.7.0 or newer and an iOS 17.2+ Companion build that exposes Live Activities. Enable Live Activities in iOS and the app. The feature has had TestFlight-only releases and beta behavior; confirm availability in the installed Companion build. Remote starts require the phone to contact Home Assistant for a token handshake. Home Assistant must therefore be securely reachable when the phone is away. A successful automation does not establish that this handshake or an iOS rendering occurred.

The app supplies the layouts. A timer can replace the message in the Lock Screen design; compact content is chosen from timer, supplementary text and progress. Custom colors do not recolor the system Dynamic Island background. A chart, tile grid, artwork or approval-button payload is not part of this native API. See [feature parity](feature-parity.md).

The public documentation and current development source are inconsistent about mutable titles, iPad availability and some text precedence. Home Island targets iPhone, keeps titles stable, and requires a physical-device check of the installed version. Do not infer behavior of a released binary from development source alone.

## Delivery, accounting and Local Push

The [published delivery policy](https://companion.home-assistant.io/docs/notifications/notification-details/) gives each device 500 hosted pushes per UTC day; commands are exempt. The Companion counter includes other integrations. Home Island's diagnostics count its own accepted dispatches and surfaced errors, not the authoritative quota. `silent` and `alert_once` quiet updates do not silence a newly created activity. Quiet updates can be delayed by iOS. Apple's update and push-to-start budgets are separate from Home Assistant's daily allowance.

Core's [2026.10.4 mobile_app notification implementation](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/components/mobile_app/notify.py) catches some remote `HomeAssistantError` exceptions and logs them rather than returning a failure to the caller. Consequently Home Island can retry surfaced service exceptions, but cannot guarantee retries for every remote failure or prove delivery from a successful service return. Check Companion notification diagnostics and Core logs for the full picture.

[Local Push](https://companion.home-assistant.io/docs/notifications/notification-local/) uses a local connection and does not consume hosted quota. On iOS it depends on the internal URL and configured Wi-Fi SSIDs. It cannot be treated as a reliable APNs replacement for background ActivityKit delivery: the [app's Local Push manager](https://github.com/home-assistant/iOS/blob/98dc06438125cdf65ea7816c83a0c846a9447526/Sources/Shared/Notifications/LocalPush/LocalPushManager.swift) hands Live Activity work from the network extension to the app, which may be suspended. The [confirmation tracker](https://github.com/home-assistant/iOS/blob/98dc06438125cdf65ea7816c83a0c846a9447526/Sources/Shared/LiveActivity/LocalPush/LiveActivityLocalPushConfirmTracker.swift) then requests APNs fallback when the app cannot perform it. Behavior is version dependent; keep normal remote push enabled and test locked/background starts and ends.

Apple limits activity lifetime to eight hours. Home Island's expiration handling ends stale activities instead of continually restarting them to evade that limit. Delivery to, and rendering on, an actual iPhone remain unverified until the installation checklist is completed.
