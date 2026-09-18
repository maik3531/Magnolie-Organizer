#!/usr/bin/env python3
"""Read-only local package prerequisites. Never build, sign, install or approve."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

from release_gate import LINUX, WINDOWS, artifact_groups, bootstrap_check, notes_inputs, release_versions
from runtime_pruefen import package_modules


def executable(*choices):
    for choice in choices:
        if not choice:
            continue
        path = shutil.which(str(choice))
        if path:
            return str(Path(path).absolute())
    return None


def metadata(path):
    """Secret paths are stat'ed only; neither their bytes nor hashes are read."""
    if path is None:
        return {"configured": False, "exists": False}
    path = Path(path)
    try:
        value = path.lstat()
        return {"configured": True, "exists": True, "regular": stat.S_ISREG(value.st_mode),
                "mode": stat.S_IMODE(value.st_mode), "bytes": value.st_size}
    except FileNotFoundError:
        return {"configured": True, "exists": False}


def android_sdk_candidates():
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not data_home.is_absolute():
        data_home = Path.home() / ".local/share"
    choices = ["/opt/android-sdk", "/tmp/opencode/android-sdk", "/tmp/android-sdk", "/usr/lib/android-sdk",
               str(Path.home() / "Android/Sdk"), str(Path.home() / "Android/sdk")]
    choices += [data_home / "android-sdk", Path.home() / ".local/share/android-sdk", Path.home() / ".local/android-sdk"]
    choices += sorted(Path("/tmp").glob("*/sdk")) + sorted(Path("/tmp/opencode").glob("*/sdk"))
    return list(dict.fromkeys(Path(value) for value in choices))


def android_sdk_complete(sdk):
    return (sdk / "platforms/android-35/android.jar").is_file() and bool(executable(sdk / "platform-tools/adb")) and any(
        all(executable(version / name) for name in ("aapt", "apksigner", "zipalign"))
        for version in (sdk / "build-tools").glob("*"))


def android_sdk(configured=None):
    for explicit in (configured, os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME")):
        if explicit:
            return Path(explicit)
    choices = android_sdk_candidates()
    return next((path for path in choices if android_sdk_complete(path)), None) or next(
        (path for path in choices if (path / "platform-tools/adb").is_file()), None)


def report(root, sdk=None, notes=None, windows_input=None):
    linux, windows = root / LINUX, root / WINDOWS
    result = {"schema": "magnolie-package-preflight-v1", "readOnly": True, "tools": {}, "blockers": [],
              "unverified": ["Native Linux/Windows GUI, upgrades and Android interoperability",
                             "Reproducible fresh product builds and production signing identity",
                             "Fedora network/rootfs execution and QEMU installation tests"]}
    version, notes_version = release_versions(root)
    result["versions"] = {"desktop": version, "notes": notes_version}
    bootstrap_check(root)
    modules = {path.name for path in (linux / "bin").glob("*.py")}
    packages = package_modules(linux)
    result["runtimeHelpers"] = sorted(modules)
    result["runtimeClosure"] = {name: {"missing": sorted(modules - files), "unexpected": sorted(files - modules)}
                                for name, files in packages.items()}
    for name, values in result["runtimeClosure"].items():
        if any(values.values()):
            result["blockers"].append("Runtime closure differs: " + name)
    tools = {name: (name,) for name in (
        "dpkg-buildpackage", "dpkg-parsechangelog", "dpkg-deb", "dpkg-architecture", "dh", "fakeroot",
        "msgfmt", "xgettext", "msgmerge", "msgattrib", "tar", "xz", "sha256sum", "flock", "bwrap", "curl",
        "xvfb-run", "xauth", "g-ir-inspect", "xdg-dbus-proxy", "flatpak", "autopkgtest",
        "qemu-system-x86_64", "gcc", "nm", "readelf", "gio-querymodules", "unzip", "timeout")}
    tools.update({"javascript": ("node", "nodejs", "bun", str(Path.home() / ".bun/bin/bun")),
                  "dotnet": (os.environ.get("MAGNOLIE_DOTNET"), "/tmp/opencode/dotnet-8.0.408/dotnet", "dotnet"),
                  "pwsh": (os.environ.get("MAGNOLIE_PWSH"), "/tmp/opencode/powershell-7.4.13/pwsh", "pwsh"),
                  "makensis": ("/tmp/opencode/nsis-root/usr/bin/makensis", "makensis"),
                  "7zip": (os.environ.get("SEVENZIP"), "7z", "7zz", "7za"),
                  "java17": ("/usr/lib/jvm/java-17-openjdk-amd64/bin/java", "java"),
                  "javac17": ("/usr/lib/jvm/java-17-openjdk-amd64/bin/javac", "javac")})
    for name, choices in tools.items():
        result["tools"][name] = executable(*choices)
        if not result["tools"][name]:
            result["blockers"].append("Executable not found in PATH/configured local paths: " + name)
    result["nsisData"] = "/tmp/opencode/nsis-root/usr/share/nsis"
    if not (Path(result["nsisData"]) / "Include/MUI2.nsh").is_file():
        result["blockers"].append("Local NSIS data/Include/MUI2.nsh missing")
    result["nsisEnvironmentConfigured"] = os.environ.get("NSISDIR") == result["nsisData"]
    if not result["nsisEnvironmentConfigured"]:
        result["blockers"].append("Set NSISDIR to the reported local NSIS data directory before CrossCompile")
    result["buildToolsOutsidePath"] = sorted({value for key in ("dotnet", "makensis", "javascript")
        if (value := result["tools"][key]) and shutil.which(Path(value).name) is None})
    if result["buildToolsOutsidePath"]:
        result["blockers"].append("Existing candidate-build tools require their directories in PATH")
    result["toolVersions"] = {}
    for name, arguments, expected in (("dotnet", ["--list-sdks"], "8.0."),
                                      ("java17", ["-version"], 'version "17.'),
                                      ("javac17", ["-version"], "javac 17.")):
        if result["tools"][name]:
            environment = {key: value for key, value in os.environ.items()
                           if key not in {'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS'}}
            probe = subprocess.run([result["tools"][name], *arguments], capture_output=True, text=True, timeout=20, env=environment)
            text = (probe.stdout + probe.stderr).strip()
            result["toolVersions"][name] = text
            if probe.returncode or expected not in text:
                result["blockers"].append("Required tool version could not be verified: " + name)
    imports = ("pytest", "cryptography", "OpenSSL", "phonenumbers", "qrcode", "zeroconf", "gi", "enchant")
    result["pythonDependencies"] = {name: importlib.util.find_spec(name) is not None for name in imports}
    result["pythonLocalRoots"] = {name: sorted(str(path.parents[1]) for path in Path('/tmp/opencode').glob('*/' + name + '/__init__.py'))
                                  for name in imports if not result["pythonDependencies"][name]}
    for name, present in result["pythonDependencies"].items():
        if not present:
            result["blockers"].append(("Configure existing local Python dependency root: " if result["pythonLocalRoots"].get(name)
                                       else "Python dependency not located: ") + name)
    result["giTypelibs"] = {}
    for namespace, typelib_version in (("Gtk", "3.0"), ("WebKit2", "4.1"), ("Notify", "0.7")):
        probe = subprocess.run([sys.executable, "-I", "-B", "-c",
            f"import gi; gi.require_version({namespace!r}, {typelib_version!r}); from gi.repository import {namespace}"],
            capture_output=True, timeout=15)
        result["giTypelibs"][namespace] = probe.returncode == 0 and not probe.stderr.strip()
        if not result["giTypelibs"][namespace]:
            result["blockers"].append("Required host GI typelib unavailable or emitted diagnostics: " + namespace)
    if result["tools"]["javascript"]:
        probe = subprocess.run([result["tools"]["javascript"], "-e",
            'require("node:module").createRequire(process.argv[1]).resolve("jsdom")',
            str(linux / "pruefungen/test.js")], capture_output=True, timeout=15)
        result["jsdomResolvableFromLinuxTests"] = probe.returncode == 0
        if probe.returncode:
            result["blockers"].append("jsdom cannot be resolved from the Linux test source")
    result["flatpak"] = {}
    if result["tools"]["flatpak"]:
        for ref in ("org.gnome.Platform//49", "org.gnome.Sdk//49", "org.flatpak.Builder"):
            probe = subprocess.run([result["tools"]["flatpak"], "info", "--user", "--show-location", ref],
                                   capture_output=True, text=True, timeout=20)
            location = probe.stdout.strip() if probe.returncode == 0 else None
            result["flatpak"][ref] = location
            if not location:
                result["blockers"].append("Flatpak user ref unavailable: " + ref)
            if location and ref.startswith("org.gnome.Platform"):
                for file in ("bin/xgettext", "share/zoneinfo/Europe/Berlin"):
                    if not (Path(location) / "files" / file).is_file():
                        result["blockers"].append("GNOME runtime missing " + file)
    from kde_profiles import PROFILES
    result["kdeRootfs"] = {}
    for target, profile in PROFILES.items():
        kde = Path(os.environ.get(profile["env"], profile["rootfs"]))
        configs = (("Qt5Core", "KF5Akonadi", "KF5CalendarCore", "KF5Contacts") if target == "ubuntu24.04"
                   else ("Qt6Core", "KPim6Akonadi", "KF6CalendarCore", "KF6Contacts"))
        kde_configs = {name: bool(list((kde / "usr/lib").glob("*/cmake/" + name + "/*Config.cmake"))) for name in configs}
        result["kdeRootfs"][target] = {"path": str(kde), "label": profile["label"],
                                    "dpkgBuildpackage": (kde / "usr/bin/dpkg-buildpackage").is_file(), "cmakeConfigs": kde_configs}
        if not result["kdeRootfs"][target]["dpkgBuildpackage"] or not all(kde_configs.values()):
            result["blockers"].append(target + ": KDE build rootfs lacks dpkg-buildpackage or required CMake configs")
    result["qemuImage"] = metadata(os.environ.get("MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE"))
    if not result["qemuImage"]["exists"]:
        result["blockers"].append("MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE not supplied/existing; exception requires explicit recorded unavailability")
    sdk = android_sdk(sdk)
    result["android"] = {"sdk": str(sdk) if sdk else None}
    if sdk:
        result["android"]["compileSdk35Ready"] = android_sdk_complete(sdk)
        if not result["android"]["compileSdk35Ready"]:
            result["blockers"].append("Selected Android SDK is incomplete for compilation; explicit overrides are not replaced")
        result["android"]["emulator"] = executable(sdk / "emulator/emulator")
        result["android"]["runtimeImages"] = {
            str(api): any(path.is_file() for path in (sdk / "system-images" / ("android-" + str(api))).glob("*/*/system.img"))
            for api in (34, 35)}
        result["android"]["adb"] = executable(str(sdk / "platform-tools/adb"))
        if not result["android"]["adb"]:
            result["blockers"].append("Configured Android SDK lacks platform-tools/adb")
        for name in ("aapt", "apksigner", "zipalign"):
            candidates = sorted((sdk / "build-tools").glob("*/" + name))
            result["android"][name] = executable(*reversed(candidates))
            if not result["android"][name]:
                result["blockers"].append("Android SDK tool missing: " + name)
        result["android"]["platform35"] = (sdk / "platforms/android-35/android.jar").is_file()
        if not result["android"]["platform35"]:
            result["blockers"].append("Android platform 35 missing")
    else:
        result["blockers"].append("Android SDK not located; supply --android-sdk")
    android_source = next(root.glob("magnolie-notes*/app/build.gradle.kts")).parents[1]
    properties = os.environ.get("MAGNOLIE_SCHLUESSEL_PROPERTIES", str(android_source / "app/schluessel.properties"))
    result["android"]["signingPropertiesMetadataOnly"] = metadata(properties)
    result["android"]["keystoreMetadataOnly"] = metadata(os.environ.get("MAGNOLIE_KEYSTORE_FILE"))
    result["android"]["expectedCertificateConfigured"] = "MAGNOLIE_RELEASE_CERT_SHA256" in os.environ
    if not result["android"]["signingPropertiesMetadataOnly"].get("regular") or not result["android"]["signingPropertiesMetadataOnly"].get("bytes"):
        result["blockers"].append("Android production signing properties not present at configured/default path (contents not read)")
    if not result["android"]["expectedCertificateConfigured"]:
        result["blockers"].append("MAGNOLIE_RELEASE_CERT_SHA256 not configured")
    result["brandingConfigured"] = "MAGNOLIE_CONTRIBUTOR_HASH" in os.environ
    if not result["brandingConfigured"]:
        result["blockers"].append("Contributor branding must be supplied externally for candidate builds")
    try:
        result["notesInputs"] = notes_inputs(root, Path(notes or os.environ.get("MAGNOLIE_NOTES_ARTIFACTS", root)))
    except (OSError, ValueError) as error:
        result["notesInputs"] = {"ready": False, "reason": str(error)}
        result["blockers"].append("Current private Notes input not ready")
    result["windowsCoreGroups"] = len(re.findall(r'^runner\.Add\(', (windows / "tests/Program.cs").read_text(), re.M))
    windows_input = Path(windows_input or os.environ.get("MAGNOLIE_WINDOWS_ARTIFACTS", windows))
    result["windowsCandidateInputs"] = {name: metadata(windows_input / name) for name in artifact_groups(version, notes_version, "amd64")["windows"]}
    if not all(value.get("regular") and value.get("bytes", 0) > 0 for value in result["windowsCandidateInputs"].values()):
        result["blockers"].append("Windows candidate inputs incomplete; build private Windows candidate first")
    result["templates"] = {}
    for name, path in (("linux", linux / "po/magnolie-organizer.pot"),
                       ("windows", windows / "app/po/magnolie-organizer.pot"),
                       ("handbook", root / "magnolie-handbuch/po/magnolie-handbuch.pot")):
        result["templates"][name] = max(0, len(re.findall(r'^msgid ', path.read_text(), re.M)) - 1)
    handbook = root / 'magnolie-handbuch'
    result['handbookCatalogs'] = {
        'languages': len((handbook / 'po/LINGUAS').read_text().split()),
        'runtimeJs': len(list((handbook / 'web/i18n').glob('*.js'))),
        'protectedEnglishEntries': max(0, len(re.findall(r'^msgid ', (handbook / 'po/english/protected.po').read_text(), re.M)) - 1)}
    result['sourceSelectorCopiesIdentical'] = (linux / 'werkzeuge/source_selection.py').read_bytes() == (handbook / 'werkzeuge/source_selection.py').read_bytes()
    if not result['sourceSelectorCopiesIdentical']:
        result['blockers'].append('Standalone source selector copies differ')
    result['buildAuthorized'] = False
    result["readyForWholeCandidateBuild"] = not result["blockers"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--android-sdk", type=Path)
    parser.add_argument("--notes-inputs", type=Path)
    parser.add_argument("--windows-inputs", type=Path)
    args = parser.parse_args()
    value = report(args.root.resolve(), args.android_sdk, args.notes_inputs, args.windows_inputs)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0 if value["readyForWholeCandidateBuild"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
