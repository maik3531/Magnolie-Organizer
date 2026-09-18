#!/usr/bin/env python3
"""Local unsigned/ad-hoc debug bundle only. No production build, installer, upload or publication."""
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from project_ui import BETA, GENERATED, verify


def main():
    if platform.system() != "Darwin":
        raise RuntimeError("Apple macOS host required. Linux, jsdom and QEMU are not macOS build or emulation evidence.")
    for tool in ("xcrun", "swift", "codesign"):
        if not shutil.which(tool):
            raise RuntimeError("Missing Apple developer tool: " + tool)
    subprocess.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True)
    manifest = verify()
    # Mac tests exercise the actual CryptoKit, CommonCrypto and POSIX implementation.
    subprocess.run(["swift", "test", "--jobs", "2"], cwd=BETA, check=True, timeout=300,
                   env=dict(os.environ, MACOS_BETA_UI_PATH=str(GENERATED)))
    subprocess.run(["swift", "build", "-c", "debug", "--jobs", "2"], cwd=BETA, check=True, timeout=300)
    binaries = Path(subprocess.check_output(["swift", "build", "-c", "debug", "--show-bin-path"], cwd=BETA, text=True).strip())
    identity = json.loads((BETA / "Resources/BetaIdentity.json").read_text())
    output = BETA / "Output"
    if output.is_symlink():
        raise RuntimeError("Symlinked development output directory refused.")
    output.mkdir(exist_ok=True)
    output = output / (identity["name"] + "-" + identity["version"])
    if output.exists() or output.is_symlink():
        raise RuntimeError("Existing versioned output retained.")
    output.mkdir()
    app = output / "Magnolie Organizer macOS Beta.app"
    if app.exists() or app.is_symlink():
        raise RuntimeError("Existing development app retained. Choose another working copy or explicitly remove your own old build first.")
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    shutil.copy2(binaries / "Magnolie Organizer macOS Beta", contents / "MacOS/Magnolie Organizer macOS Beta")
    shutil.copy2(BETA / "Resources/Info.plist", contents / "Info.plist")
    with (contents / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleIdentifier"] == "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta"
    assert info["MagnolieBetaVersion"] == identity["version"]
    assert info["CFBundleShortVersionString"] == identity["bundleShortVersion"]
    assert info["CFBundleVersion"] == identity["bundleVersion"]
    shutil.copytree(GENERATED, contents / "Resources/UI")
    (contents / "Resources/Magnolie Organizer macOS Beta-build.json").write_text(json.dumps({
        "name": identity["name"], "version": identity["version"], "configuration": "debug", "architecture": platform.machine(),
        "sourceInputs": manifest["inputs"], "swiftTestsPassed": True,
        "nativeUIValidated": False, "productionRelease": False,
        "signing": "ad-hoc development only, not notarized"
    }, indent=2) + "\n")
    verify()  # Refuse a source change during the native build as well.
    subprocess.run(["codesign", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)
    print(str(app))
    print("Development bundle only. No native UI test, notarization, release approval or publication implied.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("macOS Beta build blocked: " + str(error), file=sys.stderr)
        sys.exit(1)
