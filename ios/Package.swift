// swift-tools-version: 6.0

import PackageDescription

// xtool packages the two library products as an application and a WidgetKit
// extension. Use project.yml with XcodeGen for the Xcode/simulator workflow.
let package = Package(
    name: "HomeIsland",
    platforms: [.iOS("17.2")],
    products: [
        .library(name: "HomeIslandApp", targets: ["HomeIslandApp"]),
        .library(name: "HomeIslandWidgets", targets: ["HomeIslandWidgets"]),
    ],
    targets: [
        .target(name: "HomeIslandModels"),
        .target(name: "HomeIslandApp", dependencies: ["HomeIslandModels"]),
        .target(name: "HomeIslandWidgets", dependencies: ["HomeIslandModels"]),
    ],
    swiftLanguageModes: [.v5]
)
