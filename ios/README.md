# Home Island local iOS prototype

This isolated SwiftUI/ActivityKit/WidgetKit source prototype demonstrates original **Generic** and **Board** layouts. Both define Lock Screen and compact, minimal and expanded Dynamic Island presentations. The app supplies local mock start/update/complete/end controls and reattaches to its active ActivityKit activities when reopened.

**Build status: unverified.** No Swift compiler, Apple SDK, xtool, Xcode, simulator, signing identity or physical iPhone is available in this Windows workspace. Only configuration/plist structure was checked here. The project must be built and exercised in an Apple SDK environment before describing it as working on a device. No remote-push backend, authenticated registration endpoint or APNs entitlement is implemented.

The Home Assistant integration remains independent of this directory and needs no developer membership.

## Local behavior

1. Choose Generic or Board, then **Start or restart sample** while the app is foregrounded. `Activity.request(..., pushType: nil)` starts the activity without requesting a push token.
2. Lock a supported device or use the simulator's Lock Screen. Generic shows a wash status, progress and a system-rendered countdown. Board shows four labeled sample metrics.
3. **Update** advances mock progress or a sample metric. **Complete** shows a final state and requests immediate dismissal five seconds later. **End now** dismisses directly.
4. Starting the same logical sample while it is active updates that existing activity. Starting during the completion delay cancels that delay. After ending, the next start creates another lifecycle generation.

The five-second delay belongs to this foreground demonstration; it is not a reliable background scheduler. Suspension, termination or force-quit can interrupt it. A countdown does not mean the app will execute when it reaches zero. Reopen the app and use **End now** to clear a remaining sample. The Home Assistant integration's server-side completion/recovery logic is separate.

There are no entity subscriptions, real metrics, Home Assistant login or remote delivery in this prototype. Tapping an activity uses the platform's default app opening behavior; a dashboard router is future work. App Intent buttons, Timeline, Log, Media and Approval are also future work.

## Xcode fallback (macOS)

Install Xcode, select its developer directory, and install [XcodeGen](https://github.com/yonaskolb/XcodeGen) following its own instructions. From this directory:

```sh
xcodegen generate
xcodebuild -list -project HomeIsland.xcodeproj
xcodebuild -project HomeIsland.xcodeproj -scheme HomeIslandApp \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
```

Open `HomeIsland.xcodeproj`, select **HomeIslandApp**, choose a simulator running iOS 17.2 or later and run it. Use the app controls, the Widget target's source previews, and a Dynamic Island simulator to inspect all presentations. The source previews display mock Lock Screen surfaces; they are not evidence of ActivityKit runtime behavior.

For a physical iPhone, replace the example bundle IDs in `project.yml`, select your development team in Xcode, regenerate and sign both the app and extension. A free Personal Team may allow limited local testing subject to Apple's current capabilities and seven-day provisioning restrictions. This source does not claim physical-device installation was verified. Do not add Push Notifications merely to run the local sample.

## xtool path (SDK-capable host)

Follow [xtool installation and setup](https://github.com/xtool-org/xtool). `Package.swift` exposes separate app and WidgetKit library products, and `xtool.yml` packages them using the documented [app extension configuration](https://xtool.sh/documentation/xtool/appex/). From this directory, with the SDK and signing configuration already set up:

```sh
xtool dev build
xtool dev
```

Use `xtool dev --help` for the installed version's build and device options. The configuration shape was verified against the upstream `PackSchema.swift`, planner and `DemoExtensions` example. The actual compiler/linker, extension installation and signing paths have not run here. Use Xcode if xtool cannot build or provision this combination.

The `Support/*-Info.plist` files are partial plists merged by xtool. XcodeGen generates its own complete target plists under `Generated/`; it does not use those partial files directly. Neither build path includes APNs credentials or push entitlements.

xtool may prefix identifiers when signing; a later APNs topic must match the **actual signed bundle ID**. Its entitlement support depends on Apple's membership rules and xtool's capability mappings. An SDK, toolchain or free signing account does not grant remote push permission.

## Content and lifecycle contract

`HomeIslandModels` is a static shared module used by both targets. `HomeIslandAttributes` carries `logicalID`, `generation`, stable `title` and `presentation`; `ContentState` carries `status`, normalized optional `progress`, optional `endAt`, up to four metrics and a `running`/`completing` phase. Each new Apple activity has immutable attributes. The model follows the integration's identity/progress/deadline/lifecycle semantics, but no adapter connects the two yet.

The Python coordinator remains the authority for any future backend. A future adapter must normalize native integer progress to 0–1, associate update tokens with the correct logical ID and generation, bound content size, and match Swift's default Codable encoding exactly. `Date` does not encode as ISO-8601 with the default encoder; do not send the integration's epoch timestamps directly into this model without conversion. See [Apple's remote payload requirements](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications).

Remote implementation requires paid push provisioning, token rotation, authenticated Home Assistant pairing, private server-side APNs keys, revocation and retry tests. See [the feasibility analysis](../docs/ios-feasibility.md). Apple's normal eight-hour activity limit, 4 KB data bound and iOS update budgets still apply.

## Verification still required

- Build both targets with an iOS SDK; inspect signing and extension embedding.
- Start/update/end on a simulator and a real iPhone, including disabled Live Activities and activity-limit errors.
- Check Generic countdown and Board layout with large text, VoiceOver and every Dynamic Island presentation.
- Complete, restart within five seconds, background and reopen; verify no stale completion dismisses a restarted run.
- Confirm that already-ended or system-dismissed activities disappear from the control list after refresh.
- If a later remote transport is implemented, test it independently with real entitlement, token and APNs credentials. APNs acceptance alone does not prove display.
