# Optional iOS app: feasibility and verification boundary

Research checked on 25 October 2026. The free integration uses the installed Home Assistant Companion App; none of the requirements below are dependencies of that integration.

## Decision

Build and validate the native Companion MVP first. A separate SwiftUI app can supply custom layouts, but reliable remote delivery needs Apple's push service and an appropriately provisioned developer account. Running the APNs provider inside Home Assistant would remove a separate hosted application backend; it would not remove Apple or create an unlimited delivery guarantee.

| Development path | What is feasible | What remains to verify |
| --- | --- | --- |
| Free MVP | Existing Companion App, no new Apple membership | Delivery and rendering on the user's iPhone |
| Local custom app | SwiftUI mock views; local ActivityKit start/update/end in a foreground app | macOS/iOS SDK build, simulator and physical-device behavior |
| Personal Team on a device | Limited development deployment using Xcode | Profiles expire after seven days; do not promise push capability |
| Direct APNs custom app | Home Assistant as provider, custom WidgetKit layouts | Paid provisioning, identifiers, entitlements, signing, tokens and end-to-end delivery |
| xtool | Documented WidgetKit app-extension packaging | Actual target build, signing and installation for this project |

Apple permits free Personal Team device testing with limits: up to ten App IDs, three devices and three installed apps per device; profiles expire after seven days. The paid Apple Developer Program provides additional capabilities and distribution. Check Apple's [account overview](https://developer.apple.com/help/account/basics/about-your-developer-account), [capability matrix](https://developer.apple.com/help/account/reference/supported-capabilities-ios), and [membership details](https://developer.apple.com/programs/whats-included). Apple currently lists membership at USD 99 per year or local pricing; do not buy membership to use the free MVP.

## Platform constraints

An ActivityKit view uses a WidgetKit extension, SwiftUI and an `ActivityAttributes` model. Set `NSSupportsLiveActivities` in the app's Info.plist. A Live Activity cannot fetch network data itself. Its combined static and dynamic data is limited to 4 KB. An activity normally lasts at most eight hours, with up to four additional hours of ended content on the Lock Screen; it disappears from the Dynamic Island when ended. iOS chooses presentations and may deny activity creation. These are separate constraints from Home Assistant's notification quota. [Apple: displaying live data](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)

Background execution is not a permanent process: a custom app must not depend on an indefinitely connected Home Assistant WebSocket. App Intents can support buttons and toggles, but a custom ActivityKit layout does not grant unrestricted background execution, arbitrary embedded applications or unlimited controls. [Apple: adding interactivity](https://developer.apple.com/documentation/widgetkit/adding-interactivity-to-widgets-and-live-activities)

## Remote protocol to implement after local validation

Push-to-start requires iOS 17.2 or later; earlier systems can update/end an activity started inside the app. Observe `pushToStartTokenUpdates` and each activity's `pushTokenUpdates`, upload replacements and invalidate old tokens. Start uses `event: start`, `attributes-type`, `attributes`, `content-state` and an `alert`. Update/end use that activity's update token and full `content-state`; end should include final state. APNs headers include `apns-push-type: liveactivity`, `<bundleID>.push-type.liveactivity` as topic, and priority 5 or 10. The payload includes an epoch `timestamp`. iOS 18 adds `input-push-token: 1` for starts requesting an update token. Prioritize ordinary updates conservatively: delivery remains system-controlled. `NSSupportsLiveActivitiesFrequentUpdates` is an opt-in budget setting, not an unlimited entitlement. [Apple: remote ActivityKit notifications](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications)

Use a persistent TLS HTTP/2 provider connection. Sign provider JWTs with ES256 using the developer team's APNs `.p8` key; header `kid`, claims `iss` and `iat` identify the key, team and issuance time. Reuse the JWT and rotate between 20 and 60 minutes. The key must remain exclusively in private server storage. Never put it in the app bundle, checked-in configuration, activity payloads, logs or diagnostics. [Apple: token authentication](https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns)

APNs acceptance is not device delivery confirmation. Stop using tokens after `410`/`Unregistered` or other permanent token errors; replace tokens through registration. Delay `429` retries, and apply Apple's documented retry/backoff rules to server failures. Authentication and malformed payload errors require correction. [Apple: APNs responses](https://developer.apple.com/documentation/usernotifications/handling-notification-responses-from-apns)

## Pairing and credential design

The following is an implementation proposal, not an enabled endpoint:

1. Use Home Assistant's OAuth flow and authenticated WebSocket commands or authenticated HTTP views for pairing and token registration. Bind each installation to its authenticated user.
2. Store refresh credentials in iOS Keychain, with device-appropriate accessibility. Keep update tokens and installation identity server-side in Home Assistant private storage, scoped to that user and installation.
3. Register the latest push-to-start token and activity-token association. Include activity logical ID, generation and Apple activity ID so an old token cannot update a new run accidentally. Avoid storing bearer credentials in shared presentation models.
4. Support revocation: delete installation associations, invalidate tokens, cancel pending sends and clear Keychain credentials. Validate ownership on registration, rotation and deletion.
5. An iPhone away from home needs a securely reachable Home Assistant URL for registration/refresh. Use the user's existing secure remote access or VPN; do not add unauthenticated webhooks or assume a private LAN hostname works remotely.

These security choices follow the [Home Assistant authentication API](https://developers.home-assistant.io/docs/auth_api/) and require dedicated implementation and tests before exposing an endpoint. Home Assistant Storage is private application storage, not a claim of encryption at rest; protect backups and the host.

## xtool and build environment

The official [xtool extension guide](https://xtool.sh/documentation/xtool/appex/) demonstrates a separate SwiftPM library product for a WidgetKit extension, listed under `extensions` with `product` and `infoPath` in `xtool.yml`. Its plist declares `com.apple.widgetkit-extension`. This Foundation app-extension mechanism is suitable in principle for an ActivityKit WidgetKit extension. xtool states that newer ExtensionKit extension types are not yet supported. These packaging capabilities do not bypass Apple provisioning or grant push entitlements. [Guide source](https://github.com/xtool-org/xtool/blob/main/Documentation/xtool.docc/Appex.md)

xtool also documents `entitlementsPath`, notes that some capabilities need explicit support inside xtool, and may prefix the bundle ID during device signing. Any later APNs topic must use the actual signed app identifier. Inspect the built bundle and provisioning profile before enabling push; a configuration file alone is not evidence that the required capability was granted. [xtool structure and entitlements](https://github.com/xtool-org/xtool/blob/main/Documentation/xtool.docc/Control.md)

The current workspace runs on Windows. Inspection found no `swift`, `xtool`, `xcodebuild`, or `docker` command on PATH. There is no Apple simulator or supplied signing identity. Consequently neither an iOS SDK build nor simulator/physical-device/APNs verification can be claimed here. Use an Apple SDK-capable environment with xtool, or Xcode on macOS as the fallback. A future build should first run without APNs entitlements using local ActivityKit calls; configure push only after signing is available. [xtool project](https://github.com/xtool-org/xtool)

## Original local proof-of-concept source

After the MVP's automated Home Assistant suite passed, an isolated local prototype was added under [`ios/`](../ios/README.md). It includes original Generic and Board SwiftUI views, all four iPhone ActivityKit presentations, mock previews, local start/update/complete/end controls, shared Codable models, and XcodeGen/xtool manifests. Source and build configuration exist; compilation, simulator execution, installation, signing and physical rendering remain unverified because this host has no Apple SDK. The prototype calls `Activity.request` with `pushType: nil`; no remote backend or registration endpoint has been enabled.

Keep a transport-neutral content schema: stable logical ID, title, status, optional progress and end date, optional board metrics, and lifecycle generation. The Home Assistant coordinator remains the lifecycle authority; a separate adapter would serialize native notification payloads or ActivityKit `ContentState`.

Generic presents a compact icon/title header, a status line, a restrained accent progress bar and an optional device-rendered countdown. Board presents a title/status header and up to four labeled metric cells. Both define Lock Screen, compact leading/trailing, minimal and expanded Dynamic Island views, accessibility labels, mock content and local start/update/end controls. The views use original styling and SF Symbols; Home Assistant MDI glyphs are not assumed to exist in the new app. Completion delay execution is foreground prototype behavior and may be interrupted by suspension; it is not a remote/background scheduling guarantee.

Timeline, Log, Media and Approval are later layout work. Treat sample data and previews as design tools, not as evidence of Home Assistant connectivity or remote delivery. A local proof of concept must be labeled separately from production push support.
