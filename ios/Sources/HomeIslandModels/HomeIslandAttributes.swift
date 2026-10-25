import ActivityKit
import Foundation

/// A separate transport adapter can map the Home Assistant coordinator's
/// logical ID, lifecycle generation, progress and deadline to this model.
/// No Companion payload is decoded directly: the native contracts differ.
public struct HomeIslandAttributes: ActivityAttributes {
    public enum Presentation: String, Codable, CaseIterable, Hashable {
        case generic
        case board

        public var label: String {
            switch self {
            case .generic: return "Generic"
            case .board: return "Board"
            }
        }

        public var symbol: String {
            switch self {
            case .generic: return "washer.fill"
            case .board: return "square.grid.2x2.fill"
            }
        }
    }

    public enum Phase: String, Codable, Hashable {
        case running
        case completing
    }

    public struct Metric: Codable, Hashable, Identifiable {
        public var id: String
        public var label: String
        public var value: String
        public var unit: String
        public var symbol: String

        public init(id: String, label: String, value: String, unit: String, symbol: String) {
            self.id = id
            self.label = label
            self.value = value
            self.unit = unit
            self.symbol = symbol
        }
    }

    public struct ContentState: Codable, Hashable {
        public var status: String
        /// Normalized 0...1, independent of a native notification's progress_max.
        public var progress: Double?
        /// Codable's default Date representation; a future APNs adapter must
        /// match this encoding rather than assuming ISO-8601 JSON dates.
        public var endAt: Date?
        public var metrics: [Metric]
        public var phase: Phase

        public init(
            status: String,
            progress: Double? = nil,
            endAt: Date? = nil,
            metrics: [Metric] = [],
            phase: Phase = .running
        ) {
            self.status = status
            self.progress = progress
            self.endAt = endAt
            self.metrics = Array(metrics.prefix(4))
            self.phase = phase
        }
    }

    public var logicalID: String
    public var generation: Int
    public var title: String
    public var presentation: Presentation

    public init(logicalID: String, generation: Int, title: String, presentation: Presentation) {
        self.logicalID = logicalID
        self.generation = generation
        self.title = title
        self.presentation = presentation
    }
}

/// Deterministic mock values; dates are supplied by the caller for previews.
public enum HomeIslandSamples {
    public static func attributes(
        _ presentation: HomeIslandAttributes.Presentation,
        generation: Int = 1
    ) -> HomeIslandAttributes {
        HomeIslandAttributes(
            logicalID: "demo_\(presentation.rawValue)",
            generation: generation,
            title: presentation == .generic ? "Washing machine" : "Home overview",
            presentation: presentation
        )
    }

    public static func state(
        _ presentation: HomeIslandAttributes.Presentation,
        now: Date = .now
    ) -> HomeIslandAttributes.ContentState {
        switch presentation {
        case .generic:
            return .init(status: "Washing · cotton cycle", progress: 0.42, endAt: now.addingTimeInterval(2160))
        case .board:
            return .init(status: "Everything is looking good", metrics: [
                .init(id: "solar", label: "Solar", value: "3.4", unit: "kW", symbol: "sun.max.fill"),
                .init(id: "battery", label: "Battery", value: "78", unit: "%", symbol: "battery.75percent"),
                .init(id: "home", label: "Indoors", value: "21.6", unit: "°C", symbol: "thermometer.medium"),
                .init(id: "charger", label: "Car", value: "6.8", unit: "kW", symbol: "bolt.car.fill"),
            ])
        }
    }
}
