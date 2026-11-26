#!/usr/bin/env python3
"""Local unsigned/ad-hoc debug bundle only. No production build, installer, upload or publication."""
import argparse
import json
import os
import platform
import re
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from project_ui import BETA, GENERATED, verify
from airplay_bundle import build_airplay_bundle
from import_python_bundle import bundle_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--airplay-sdk", type=Path,
                        help="Local, source/license-complete AirPlay SDK; builds the internal receiver into the app")
    parser.add_argument("--import-runtime", type=Path, required=True,
                        help="Private CPython SDK built by tools/import_python_bundle.py; no system-Python fallback")
    arguments = parser.parse_args()
    if platform.system() != "Darwin":
        raise RuntimeError("Apple macOS host required. Linux and UI-only tests do not provide Apple's SDK; use a suitable macOS VM or runner.")
    for tool in ("xcrun", "swift", "codesign"):
        if not shutil.which(tool):
            raise RuntimeError("Missing Apple developer tool: " + tool)
    subprocess.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True)
    identity = json.loads((BETA / "Resources/BetaIdentity.json").read_text())
    minimum = identity["minimumSystemVersion"]
    if minimum != "12.7":
        raise RuntimeError("Unsupported development deployment target.")
    build_environment = dict(os.environ, MACOSX_DEPLOYMENT_TARGET=minimum)
    manifest = verify()
    # Mac tests exercise the actual CryptoKit, CommonCrypto and POSIX implementation.
    subprocess.run(["swift", "test", "--jobs", "2"], cwd=BETA, check=True, timeout=300,
                   env=dict(build_environment, MACOS_BETA_UI_PATH=str(GENERATED)))
    subprocess.run(["swift", "build", "-c", "debug", "--jobs", "2"], cwd=BETA, check=True, timeout=300, env=build_environment)
    binaries = Path(subprocess.check_output(["swift", "build", "-c", "debug", "--show-bin-path"], cwd=BETA, text=True, env=build_environment).strip())
    executable = binaries / "Magnolie Organizer macOS Beta"
    deployment = subprocess.check_output(["xcrun", "vtool", "-show-build", str(executable)], text=True)
    targets = re.findall(r"^\s*minos\s+(\S+)\s*$", deployment, flags=re.MULTILINE)
    if not targets or any(target not in (minimum, minimum + ".0") for target in targets):
        raise RuntimeError("Built Mach-O minimum OS does not match " + minimum + ": " + repr(targets))
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
    shutil.copy2(executable, contents / "MacOS/Magnolie Organizer macOS Beta")
    shutil.copy2(BETA / "Resources/Info.plist", contents / "Info.plist")
    with (contents / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleIdentifier"] == "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta"
    assert info["MagnolieBetaVersion"] == identity["version"]
    assert info["CFBundleShortVersionString"] == identity["bundleShortVersion"]
    assert info["CFBundleVersion"] == identity["bundleVersion"]
    assert info["LSMinimumSystemVersion"] == minimum
    shutil.copytree(GENERATED, contents / "Resources/UI")
    # The helper is not web-readable and runs only via bounded native stdio.
    helper = contents / "Resources/UI/ImportHelper"
    if not (helper / "manifest.json").is_file() or not (helper / "helper.py").is_file():
        raise RuntimeError("Verified current-source import helper is missing.")
    shutil.move(str(helper), str(contents / "Resources/ImportHelper"))
    import_runtime = bundle_runtime(app, arguments.import_runtime)
    airplay = None
    if arguments.airplay_sdk is not None:
        airplay = build_airplay_bundle(BETA, app, arguments.airplay_sdk, platform.machine(), minimum)
    (contents / "Resources/Magnolie Organizer macOS Beta-build.json").write_text(json.dumps({
        "name": identity["name"], "version": identity["version"], "configuration": "debug", "architecture": platform.machine(),
        "sourceInputs": manifest["inputs"], "swiftTestsPassed": True,
        "minimumSystemVersion": minimum, "machOMinimumVerified": True,
        "montereyRuntimeValidated": False,
        "nativeUIValidated": False, "productionRelease": False,
        "importRuntimeVersion": import_runtime["pin"]["version"],
        "importRuntimeSourceSHA256": import_runtime["pin"]["sourceSHA256"],
        "importRuntimeRelocationVerified": True,
        "importNativeUIValidated": False,
        "airplayBundled": airplay is not None,
        "airplayDependencyClosureVerified": airplay is not None,
        "airplayNativeDeviceValidated": False,
        "signing": "ad-hoc development only, not notarized"
    }, indent=2) + "\n")
    verify()  # Refuse a source change during the native build as well.
    # Swift's arm64 executable may already carry an automatic ad-hoc signature.
    # Replace it only inside this newly created, versioned development bundle.
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)
    if airplay is not None or import_runtime is not None:
        # Helpers/libraries were signed individually before the outer bundle;
        # this verifies the enclosing seals without modifying nested signatures.
        subprocess.run(["codesign", "--verify", "--strict", "--deep", str(app)], check=True)
    print(str(app))
    print("Development bundle only. No native UI test, notarization, release approval or publication implied.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("macOS Beta build blocked: " + str(error), file=sys.stderr)
        sys.exit(1)
