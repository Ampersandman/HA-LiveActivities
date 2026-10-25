import ActivityKit
import HomeIslandModels
import SwiftUI
import WidgetKit

@main
struct HomeIslandWidgetBundle: WidgetBundle {
    var body: some Widget {
        HomeIslandActivity()
    }
}

struct HomeIslandActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: HomeIslandAttributes.self) { context in
            ActivitySurface(attributes: context.attributes, state: context.state, stale: context.isStale)
                .activityBackgroundTint(IslandPalette.background)
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Image(systemName: context.attributes.presentation.symbol)
                        .foregroundStyle(IslandPalette.accent)
                        .accessibilityLabel(context.attributes.presentation.label)
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(context.attributes.title)
                        .font(.headline)
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if context.state.phase == .completing {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                    } else if context.isStale {
                        Image(systemName: "clock.badge.exclamationmark").foregroundStyle(.orange)
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    ActivityDetails(presentation: context.attributes.presentation, state: context.state)
                        .padding(.top, 4)
                }
            } compactLeading: {
                Image(systemName: context.attributes.presentation.symbol)
                    .foregroundStyle(IslandPalette.accent)
                    .accessibilityLabel(context.attributes.title)
            } compactTrailing: {
                CompactValue(state: context.state)
            } minimal: {
                Image(systemName: context.state.phase == .completing ? "checkmark" : context.attributes.presentation.symbol)
                    .foregroundStyle(IslandPalette.accent)
                    .accessibilityLabel(context.attributes.title)
            }
            .keylineTint(IslandPalette.accent)
        }
    }
}

enum IslandPalette {
    static let background = Color(red: 0.035, green: 0.075, blue: 0.10)
    static let accent = Color(red: 0.30, green: 0.91, blue: 0.80)
    static let secondary = Color(red: 0.69, green: 0.77, blue: 0.80)
}

struct ActivitySurface: View {
    let attributes: HomeIslandAttributes
    let state: HomeIslandAttributes.ContentState
    var stale = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: attributes.presentation.symbol)
                    .foregroundStyle(IslandPalette.accent)
                Text(attributes.title).font(.headline).lineLimit(1)
                Spacer(minLength: 4)
                if state.phase == .completing {
                    Label("Complete", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(IslandPalette.accent)
                        .font(.caption.weight(.semibold))
                } else if stale {
                    Text("Out of date").font(.caption).foregroundStyle(.orange)
                }
            }
            ActivityDetails(presentation: attributes.presentation, state: state)
        }
        .foregroundStyle(.white)
        .padding(14)
    }
}

struct ActivityDetails: View {
    let presentation: HomeIslandAttributes.Presentation
    let state: HomeIslandAttributes.ContentState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(state.status)
                .font(.subheadline)
                .foregroundStyle(IslandPalette.secondary)
                .lineLimit(1)

            if presentation == .board {
                MetricBoard(metrics: Array(state.metrics.prefix(4)))
            } else {
                if let progress = state.progress, progress.isFinite {
                    HStack(spacing: 12) {
                        ProgressView(value: min(1, max(0, progress)))
                            .tint(IslandPalette.accent)
                        Text(min(1, max(0, progress)), format: .percent.precision(.fractionLength(0)))
                            .font(.caption.monospacedDigit().weight(.semibold))
                    }
                    .accessibilityElement(children: .combine)
                }
                if let endAt = state.endAt, state.phase == .running {
                    HStack {
                        Label("Remaining", systemImage: "timer")
                            .font(.caption)
                            .foregroundStyle(IslandPalette.secondary)
                        Spacer()
                        CountdownValue(endAt: endAt)
                            .font(.subheadline.monospacedDigit().weight(.semibold))
                    }
                }
            }
        }
    }
}

struct MetricBoard: View {
    let metrics: [HomeIslandAttributes.Metric]

    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 8) {
            ForEach(Array(metrics.enumerated()), id: \.offset) { _, metric in
                HStack(spacing: 7) {
                    Image(systemName: metric.symbol)
                        .font(.caption)
                        .foregroundStyle(IslandPalette.accent)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(metric.label)
                            .font(.caption2)
                            .foregroundStyle(IslandPalette.secondary)
                            .lineLimit(1)
                        HStack(alignment: .firstTextBaseline, spacing: 3) {
                            Text(metric.value).font(.subheadline.monospacedDigit().weight(.semibold))
                            Text(metric.unit).font(.caption2).foregroundStyle(IslandPalette.secondary)
                        }
                        .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }
}

struct CompactValue: View {
    let state: HomeIslandAttributes.ContentState

    var body: some View {
        Group {
            if state.phase == .completing {
                Image(systemName: "checkmark.circle.fill")
            } else if let progress = state.progress, progress.isFinite {
                Text(min(1, max(0, progress)), format: .percent.precision(.fractionLength(0)))
            } else if let metric = state.metrics.first {
                Text("\(metric.value)\(metric.unit)").lineLimit(1).minimumScaleFactor(0.7)
            } else {
                Image(systemName: "house.fill")
            }
        }
        .font(.caption.monospacedDigit().weight(.semibold))
        .foregroundStyle(IslandPalette.accent)
        .accessibilityLabel(state.status)
    }
}

struct CountdownValue: View {
    let endAt: Date

    var body: some View {
        // Date text is rendered by the system; no per-second background task.
        Text(timerInterval: min(Date.now, endAt)...endAt, countsDown: true)
            .multilineTextAlignment(.trailing)
            .accessibilityLabel("Time remaining")
    }
}

#Preview("Generic · Lock Screen surface") {
    ActivitySurface(
        attributes: HomeIslandSamples.attributes(.generic),
        state: HomeIslandSamples.state(.generic)
    )
    .background(IslandPalette.background)
}

#Preview("Board · Lock Screen surface") {
    ActivitySurface(
        attributes: HomeIslandSamples.attributes(.board),
        state: HomeIslandSamples.state(.board)
    )
    .background(IslandPalette.background)
}

#Preview("Generic · complete") {
    ActivitySurface(
        attributes: HomeIslandSamples.attributes(.generic),
        state: .init(status: "Ready to unload", progress: 1, phase: .completing)
    )
    .background(IslandPalette.background)
}
