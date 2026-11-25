#!/usr/bin/env python3
"""Run the actual portable AirPlay Swift sources/tests without Apple-only targets.

No toolchain download or installation. This is a Foundation/POSIX unit check,
not a native AppKit, GStreamer, local-network-permission or iPhone acceptance.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BETA = Path(__file__).resolve().parents[1]
PACKAGE = '''// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "AirPlayCoreCheck", targets: [
    .target(name: "BetaCore"),
    .testTarget(name: "BetaCoreTests", dependencies: ["BetaCore"])
])
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swift", help="Path to an existing Swift 5.9+ executable")
    args = parser.parse_args()
    swift = shutil.which(args.swift or "swift")
    if not swift:
        parser.error("No Swift toolchain is available; AirPlay Swift tests were NOT run.")
    with tempfile.TemporaryDirectory(prefix="magnolie-airplay-core-") as directory:
        root = Path(directory)
        (root / "Package.swift").write_text(PACKAGE, encoding="utf-8")
        for relative in ("Sources/BetaCore", "Tests/BetaCoreTests"):
            files = sorted((BETA / relative).glob("AirPlay*.swift"))
            if not files:
                raise RuntimeError(f"No AirPlay source files in {relative}")
            target = root / relative
            target.mkdir(parents=True)
            for source in files:
                shutil.copyfile(source, target / source.name)
        print("Checking actual AirPlay Foundation/POSIX code; no native device claim.", flush=True)
        result = subprocess.run([swift, "test", "--package-path", str(root), "--jobs", "2"], timeout=240)
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
