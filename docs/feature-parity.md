# Presentation compatibility

Checked against the official [Companion Live Activities contract](https://companion.home-assistant.io/docs/notifications/live-activities/) and the [Companion iOS source](https://github.com/home-assistant/iOS/tree/main/Sources) on 25 October 2026. Home Island sends the Companion contract; it cannot replace the installed app's SwiftUI views.

| Feature | Companion capability | Home Island native preset | Custom iOS extension |
| --- | --- | --- | --- |
| Generic | Fixed title/status/icon with optional progress and countdown | Supported using the native fields | Original layout possible |
| Countdown | Device-rendered chronometer from `when` | Supported; completion still depends on Home Assistant running | Custom timer layout possible |
| Gauge | Integer progress bar, no custom dial | Approximation: normalize configured min/max to a bar, show value in text | Dial, bands and min/max labels possible |
| Alert | Text, icon and colors | Supported presentation; does not grant critical-alert delivery | Custom severity layout possible |
| Steps | Text and a progress bar | Approximation: current/total and description | Custom step indicators possible |
| Timeline | No chart/sparkline payload | Unsupported as a chart | Bounded series rendered in SwiftUI |
| Board | No multi-tile payload | Unsupported as tiles | Multiple metric cells possible |
| Log | No structured history payload | Unsupported as an event feed | Short bounded history possible |
| Media | No artwork/playback-control activity contract | Unsupported | Cached artwork and supported App Intents; separate media API work |
| Approval | No activity-button contract | Unsupported | App Intents plus authenticated decision handling; separate backend work |
| Dynamic Island compact | Companion selects a fixed icon and trailing content | Native app layout | Custom leading/trailing views |
| Dynamic Island minimal | Companion's icon presentation | Native app layout | Custom small view |
| Dynamic Island expanded | Companion's fixed regions | Native app layout | Custom regions within system limits |
| Relevance | Documented `relevance_score` 0–1, currently beta | Forwarded within bounds | Relative ActivityKit relevance also possible |
| Dashboard tap | Companion URL handling | Supported; supply the URL on updates | App deep link/router implementation needed |

The optional [`ios/` prototype](../ios/README.md) now contains Generic and Board source layouts plus local mock lifecycle controls. It has not been compiled or run with an Apple SDK. “Possible” in the custom-extension column describes feasibility; it does not mean remote transport or production device behavior is implemented.

The native chronometer occupies the message area. In compact Dynamic Island, the app decides between timer, short critical text and progress; presentation details can vary by Companion version. Keep the title stable for compatibility with the documented static-title behavior. Native notification action buttons should not be described as ActivityKit controls.

## Platform restrictions that a custom app cannot remove

The system decides activity visibility, space, concurrency and update delivery. An activity cannot perform network requests itself or run an arbitrary continuously executing UI. Data is bounded to 4 KB; normal active duration is at most eight hours, with at most four additional Lock Screen hours after ending. APNs and iOS budgets remain independent of Home Assistant's hosted notification quota. Interactive views use supported App Intents rather than arbitrary web pages. [Apple constraints](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities), [Apple remote delivery](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications)

## What “inspired by Pushward” means

The public [Pushward playground](https://pushward.app/playground) exposes Generic, Gauge, Alert, Timer, Steps, Timeline, Board, Log, Media and Approval families. Its [template documentation](https://pushward.app/docs/live-activities) describes richer multi-field designs; Media and Approval are currently labeled “Soon.” Home Island uses original presets and only documented Companion fields. A progress bar is explicitly a Gauge/Steps approximation, never a claim to reproduce Pushward's complete design.

See [the optional iOS feasibility analysis](ios-feasibility.md) for paid provisioning, token security, xtool and the local build limitations. Physical rendering of every native preset remains unverified until tested on a real iPhone.
