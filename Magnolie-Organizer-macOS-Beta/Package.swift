// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Magnolie-Organizer-macOS-Beta",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "Magnolie Organizer macOS Beta", targets: ["MacBeta"])],
    targets: [
        .target(name: "BetaCore"),
        .executableTarget(name: "MacBeta", dependencies: ["BetaCore"]),
        .testTarget(name: "BetaCoreTests", dependencies: ["BetaCore"],
                    resources: [.copy("Fixtures")])
    ]
)
