import ActivityKit
import HomeIslandModels
import SwiftUI

struct PrototypeView: View {
    @StateObject private var controller = LocalActivityController()
    @State private var selected: HomeIslandAttributes.Presentation = .generic
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label("Local ActivityKit prototype", systemImage: "testtube.2")
                        .font(.headline)
                    Text("Start a sample, then lock your iPhone or open Dynamic Island. Values are mock data; this app does not connect to Home Assistant.")
                        .foregroundStyle(.secondary)
                }

                Section("Choose a design") {
                    Picker("Presentation", selection: $selected) {
                        ForEach(HomeIslandAttributes.Presentation.allCases, id: \.self) { presentation in
                            Text(presentation.label).tag(presentation)
                        }
                    }
                    .pickerStyle(.segmented)
                    Button {
                        Task { await controller.start(selected) }
                    } label: {
                        Label("Start or restart sample", systemImage: "play.fill")
                    }
                }

                if let message = controller.errorMessage {
                    Section {
                        Text(message).foregroundStyle(.red)
                    }
                }

                Section("Activities on this device") {
                    if controller.activities.isEmpty {
                        Text("No active samples").foregroundStyle(.secondary)
                    }
                    ForEach(controller.activities, id: \.id) { activity in
                        activityRow(activity)
                    }
                    Button("Refresh device state") { controller.refresh() }
                }

                Section("Verification boundary") {
                    Text("No APNs entitlement or remote push is used. Complete displays a final status for five seconds while this app can execute. Background suspension or force-quit can interrupt that delay. Use End now to dismiss immediately.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Home Island")
            .onChange(of: scenePhase) { _, newPhase in
                if newPhase == .active { controller.refresh() }
            }
        }
    }

    private func activityRow(_ activity: Activity<HomeIslandAttributes>) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(activity.attributes.title, systemImage: activity.attributes.presentation.symbol)
                .font(.headline)
            Text(activity.content.state.status).foregroundStyle(.secondary)
            Text("Run \(activity.attributes.generation) · \(activity.content.state.phase.rawValue)")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Button("Update") { Task { await controller.update(activity) } }
                Spacer()
                Button("Complete") { Task { await controller.complete(activity) } }
                Spacer()
                Button("End now", role: .destructive) { Task { await controller.end(activity) } }
            }
            .buttonStyle(.borderless)
        }
        .padding(.vertical, 4)
    }
}

#Preview("Local control app") {
    PrototypeView()
}
