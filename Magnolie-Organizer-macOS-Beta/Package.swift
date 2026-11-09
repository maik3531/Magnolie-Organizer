// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Magnolie-Organizer-macOS-Beta",
    platforms: [.macOS("12.7")],
    products: [.executable(name: "Magnolie Organizer macOS Beta", targets: ["MacBeta"]),
               .executable(name: "TimezoneReferenceWorker", targets: ["TimezoneReferenceWorker"])],
    targets: [
        .target(name: "BetaCore"),
        .executableTarget(name: "MacBeta", dependencies: ["BetaCore"]),
        .executableTarget(name: "TimezoneReferenceWorker", dependencies: ["BetaCore"]),
        .executableTarget(name: "PrintNativeProbe", dependencies: ["BetaCore"]),
        .executableTarget(name: "DomainsNativeProbe", dependencies: ["BetaCore"]),
        .testTarget(name: "BetaCoreTests", dependencies: ["BetaCore", "PrintNativeProbe", "DomainsNativeProbe"],
                    resources: [.copy("Fixtures")])
    ]
)
