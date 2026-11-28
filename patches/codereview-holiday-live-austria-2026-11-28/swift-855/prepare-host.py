#!/usr/bin/env python3
"""Prepare the transparent Linux XCTest host for the actual Mac holiday source.

No source algorithm is reimplemented. Whole product/test files are copied exactly;
DTO declarations are extracted verbatim. The unused native transport boundary
throws if reached. See README.md for the explicit native-platform exclusions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(data):
    return hashlib.sha256(data).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--swift-crypto", type=Path, required=True,
                    help="Unpacked official swift-crypto 5.2.0 source directory")
parser.add_argument("--expected-manifest", type=Path,
                    default=Path(__file__).with_name("SOURCE-MANIFEST.json"))
args = parser.parse_args()
repo, host = args.repo.resolve(), args.output.resolve()
expected = json.loads(args.expected_manifest.read_text())
for row in expected:
    source = repo / row["source"]
    required = row.get("sha256", row.get("source_sha256"))
    if digest(source.read_bytes()) != required:
        raise SystemExit("Source differs from the recorded input: " + row["source"])

core = repo / "Magnolie-Organizer-macOS-Beta/Sources/BetaCore"
for child in ["Sources/BetaCore", "Sources/CryptoKit", "Tests/BetaCoreTests"]:
    (host / child).mkdir(parents=True, exist_ok=True)
for row in expected:
    if row["projection"] == "whole unchanged file":
        shutil.copyfile(repo / row["source"], host / row["host_path"])

dav = (core / "DAV.swift").read_text()
dto = dav[dav.index("public struct BoundedHTTPRequest {"):dav.index("\npublic enum DAVError:")]
dto_row = next(row for row in expected if row["host_path"].endswith("BoundedHTTPTypes.swift"))
if digest(dto.encode()) != dto_row["projection_sha256"]:
    raise SystemExit("The exact DTO extraction differs from the recorded input")
(host / "Sources/BetaCore/BoundedHTTPTypes.swift").write_text("import Foundation\n\n" + dto + "\n")
(host / "Sources/BetaCore/UnusedDefaultTransport.swift").write_text('''import Foundation

/// Test-host dependency only. Every executed service test injects the original
/// XCTest Transport double. The native default URLSession implementation is not
/// under test; fail closed if a test accidentally attempts to use this boundary.
public struct URLSessionBoundedTransport: BoundedHTTPTransport {
    public init() {}
    public func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        throw BetaError("The native default transport is outside this controlled Swift service host.")
    }
}
''')
(host / "Sources/CryptoKit/Exports.swift").write_text("@_exported import Crypto\n")
crypto = args.swift_crypto.resolve()
package_name = crypto.name
(host / "Package.swift").write_text('''// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "MagnolieHolidayServiceHost",
    dependencies: [.package(path: ''' + json.dumps(str(crypto)) + ''')],
    targets: [
        .target(name: "CryptoKit", dependencies: [.product(name: "Crypto", package: ''' + json.dumps(package_name) + ''')]),
        .target(name: "BetaCore", dependencies: ["CryptoKit"]),
        .testTarget(name: "BetaCoreTests", dependencies: ["BetaCore"])
    ]
)
''')
resolved = Path(__file__).with_name("Package.resolved")
if resolved.exists():
    shutil.copyfile(resolved, host / "Package.resolved")
print(host)
