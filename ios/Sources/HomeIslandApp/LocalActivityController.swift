import ActivityKit
import Foundation
import HomeIslandModels
import SwiftUI

/// Foreground-only local demonstration. This controller is not an APNs
/// provider and does not connect to Home Assistant or monitor real entities.
@MainActor
final class LocalActivityController: ObservableObject {
    private static let generationStorageKey = "HomeIsland.sampleGenerations"
    @Published private(set) var activities: [Activity<HomeIslandAttributes>] = []
    @Published private(set) var errorMessage: String?

    private var finishTasks: [String: Task<Void, Never>] = [:]
    private var operationIDs: [String: UUID] = [:]
    private var endingActivityIDs: Set<String> = []
    private var generations: [String: Int] = [:]

    init() {
        let stored = UserDefaults.standard.dictionary(forKey: Self.generationStorageKey) ?? [:]
        generations = stored.compactMapValues { $0 as? Int }
        refresh()
    }

    func refresh() {
        let systemActivities = Activity<HomeIslandAttributes>.activities
        endingActivityIDs.formIntersection(Set(systemActivities.map(\.id)))
        activities = systemActivities
            .filter {
                !endingActivityIDs.contains($0.id)
                    && ($0.activityState == .active || $0.activityState == .stale)
            }
            .sorted { $0.attributes.logicalID < $1.attributes.logicalID }
        for activity in activities {
            let attributes = activity.attributes
            generations[attributes.logicalID] = max(generations[attributes.logicalID] ?? 0, attributes.generation)
        }
        UserDefaults.standard.set(generations, forKey: Self.generationStorageKey)
    }

    func start(_ presentation: HomeIslandAttributes.Presentation) async {
        errorMessage = nil
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            errorMessage = "Enable Live Activities for Home Island in Settings."
            return
        }
        refresh()
        let logicalID = "demo_\(presentation.rawValue)"
        beginOperation(logicalID)
        let state = HomeIslandSamples.state(presentation)
        if let existing = activities.first(where: { $0.attributes.logicalID == logicalID }) {
            // Reuse a still-running activity and cancel delayed completion.
            await existing.update(ActivityContent(state: state, staleDate: .now.addingTimeInterval(3600)))
            refresh()
            return
        }
        let generation = (generations[logicalID] ?? 0) + 1
        do {
            _ = try Activity<HomeIslandAttributes>.request(
                attributes: HomeIslandSamples.attributes(presentation, generation: generation),
                content: ActivityContent(state: state, staleDate: .now.addingTimeInterval(3600)),
                pushType: nil
            )
            generations[logicalID] = generation
            refresh()
        } catch {
            errorMessage = "Could not start the local activity: \(error.localizedDescription)"
        }
    }

    func update(_ activity: Activity<HomeIslandAttributes>) async {
        beginOperation(activity.attributes.logicalID)
        var state = activity.content.state
        state.phase = .running
        switch activity.attributes.presentation {
        case .generic:
            let value = min(1, (state.progress ?? 0) + 0.1)
            state.progress = value
            state.status = value >= 0.8 ? "Spinning · almost there" : "Rinsing · cotton cycle"
        case .board:
            if let solarIndex = state.metrics.firstIndex(where: { $0.id == "solar" }) {
                let value = (Double(state.metrics[solarIndex].value) ?? 3.4) + 0.2
                state.metrics[solarIndex].value = String(format: "%.1f", value)
            }
            state.status = "Updated from local sample data"
        }
        await activity.update(ActivityContent(state: state, staleDate: .now.addingTimeInterval(3600)))
        refresh()
    }

    func complete(_ activity: Activity<HomeIslandAttributes>) async {
        let logicalID = activity.attributes.logicalID
        let operationID = beginOperation(logicalID)
        var state = activity.content.state
        state.status = "Complete"
        state.phase = .completing
        state.endAt = nil
        await activity.update(ActivityContent(state: state, staleDate: nil))
        // A start/update can run while the ActivityKit call is suspended.
        // Never arm a delayed dismissal for that newer operation.
        guard operationIDs[logicalID] == operationID else { return }
        refresh()

        finishTasks[logicalID] = Task { [weak self] in
            do {
                try await Task.sleep(for: .seconds(5))
            } catch {
                return
            }
            guard !Task.isCancelled, self?.operationIDs[logicalID] == operationID else { return }
            self?.endingActivityIDs.insert(activity.id)
            self?.refresh()
            await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: .immediate)
            if self?.operationIDs[logicalID] == operationID {
                self?.finishTasks[logicalID] = nil
            }
            self?.refresh()
        }
    }

    func end(_ activity: Activity<HomeIslandAttributes>) async {
        beginOperation(activity.attributes.logicalID)
        var state = activity.content.state
        state.status = "Ended"
        state.phase = .completing
        state.endAt = nil
        endingActivityIDs.insert(activity.id)
        refresh()
        await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: .immediate)
        refresh()
    }

    @discardableResult
    private func beginOperation(_ logicalID: String) -> UUID {
        finishTasks.removeValue(forKey: logicalID)?.cancel()
        let operationID = UUID()
        operationIDs[logicalID] = operationID
        return operationID
    }
}
