#!/usr/bin/env python3
"""Build and close the internal AirPlay bundle from an explicit, local SDK.

No downloads, package managers or application-start installation. The SDK has
GStreamer.framework/, openssl/, libplist/ and sdk.json (see AIRPLAY-BUILD.md). Only
Apple system libraries or libraries within the declared SDK may be linked.
This is development packaging, not a claim of native iPhone acceptance.
"""
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile


UPSTREAM_VERSION = "1.73.7"
UPSTREAM_COMMIT = "df67c212a433cf6dda3676dd40c097900d24e645"
HELPER = "Helpers/magnolie-airplay-receiver"
FRAMEWORK = "Frameworks/GStreamer.framework"
RUNTIME = {
    "pluginDirectory": FRAMEWORK + "/Versions/Current/lib/gstreamer-1.0",
    "pluginScanner": FRAMEWORK + "/Versions/Current/libexec/gstreamer-1.0/gst-plugin-scanner",
    "gioModules": FRAMEWORK + "/Versions/Current/lib/gio/modules",
}
MACH_MAGICS = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
               b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
               b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def below(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def safe_relative(root, value, *, directory=False):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Invalid SDK relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in (".", "..") for part in value.split("/")):
        raise ValueError("SDK path escapes its root: " + value)
    path = Path(root) / relative
    if not below(path, root) or not (path.is_dir() if directory else path.is_file()):
        raise ValueError("Missing or escaping SDK path: " + value)
    return path


def checked_tree(root):
    """Keep ordinary framework symlinks, reject links out of the supplied tree."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("SDK component must be a real directory: " + str(root))
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            if not path.exists() or not below(path, root):
                raise ValueError("SDK symlink leaves its component: " + str(path))
        elif path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise ValueError("Special SDK file refused: " + str(path))
    return files


def is_macho(path):
    if Path(path).suffix in {".a", ".o"}:
        return False  # Fat static archives/relocatable objects are not runtime images.
    with Path(path).open("rb") as stream:
        return stream.read(4) in MACH_MAGICS


def system_library(name):
    # macOS shared-cache libraries need not exist as physical files. Do not
    # accidentally admit traversal or /usr/local merely because it is absolute.
    path = PurePosixPath(name)
    return (path.is_absolute() and ".." not in path.parts and
            (name.startswith("/usr/lib/") or name.startswith("/System/Library/")))


@dataclass(frozen=True)
class MachO:
    dependencies: tuple
    rpaths: tuple = ()
    install_id: str | None = None
    minimum: str | None = None
    platform: str | None = None


def macos_deployment_target(text, *, allow_legacy=False):
    """Refs #806: bind one deployment version to its actual macOS platform."""
    deployments = []
    for block in re.split(r"(?m)^Load command \d+\s*$", text)[1:]:
        commands = re.findall(r"(?m)^\s*cmd\s+(\S+)\s*$", block)
        if len(commands) != 1:
            raise ValueError("Malformed Mach-O load command")
        command = commands[0]
        if command == "LC_BUILD_VERSION" or command.startswith("LC_VERSION_MIN_"):
            deployments.append((command, block))
    if len(deployments) != 1:
        raise ValueError("Expected one unambiguous Mach-O deployment command")
    command, block = deployments[0]
    platforms = re.findall(r"(?m)^\s*platform\s+(\S+)\s*$", block)
    if command == "LC_BUILD_VERSION":
        if len(platforms) != 1 or platforms[0].lower() not in {"1", "macos"}:
            raise ValueError("Mach-O is not built for macOS")
        field = "minos"
    elif allow_legacy and command == "LC_VERSION_MIN_MACOSX" and not platforms:
        field = "version"
        if re.search(r"(?m)^\s*(?:minos|ntools|tool)\s+", block):
            raise ValueError("Invalid legacy Mach-O deployment command")
    else:
        raise ValueError("Mach-O is not built for macOS")
    # LC_BUILD_VERSION also prints each compiler/linker tool's `version`.
    # Those are not deployment versions; only the command's own field counts.
    versions = re.findall(r"(?m)^\s*" + field + r"\s+(\S+)\s*$", block)
    if len(versions) != 1 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", versions[0]):
        raise ValueError("Invalid Mach-O deployment version")
    return versions[0]


def parse_load_commands(text):
    minimum = macos_deployment_target(text, allow_legacy=True)
    dependencies, rpaths, install_id = [], [], None
    for block in re.split(r"(?m)^Load command \d+\s*$", text)[1:]:
        command = re.search(r"(?m)^\s*cmd\s+(LC_\S+)\s*$", block)
        if not command:
            continue
        kind = command.group(1)
        if kind in {"LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB",
                    "LC_LAZY_LOAD_DYLIB", "LC_LOAD_UPWARD_DYLIB", "LC_ID_DYLIB"}:
            name = re.search(r"(?m)^\s*name (.+) \(offset \d+\)\s*$", block)
            if not name:
                raise ValueError("Malformed Mach-O library load command")
            if kind == "LC_ID_DYLIB":
                install_id = name.group(1)
            else:
                dependencies.append(name.group(1))
        elif kind == "LC_RPATH":
            name = re.search(r"(?m)^\s*path (.+) \(offset \d+\)\s*$", block)
            if not name:
                raise ValueError("Malformed Mach-O runpath")
            rpaths.append(name.group(1))
    return MachO(tuple(dependencies), tuple(rpaths), install_id, minimum, "macos")


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){1,2}", value):
        raise ValueError("Invalid library deployment target: " + repr(value))
    result = tuple(map(int, value.split(".")))
    return result + (0,) * (3 - len(result))


class AppleTools:
    def __init__(self, architecture, minimum):
        if architecture not in {"arm64", "x86_64"}:
            raise ValueError("Unsupported AirPlay architecture: " + architecture)
        self.architecture = architecture
        self.minimum = minimum

    def run(self, arguments):
        return subprocess.check_output(arguments, text=True, stderr=subprocess.STDOUT)

    def inspect(self, path):
        arches = self.run(["xcrun", "lipo", "-archs", str(path)]).split()
        if self.architecture not in arches:
            raise ValueError("AirPlay binary lacks " + self.architecture + ": " + str(path))
        parsed = parse_load_commands(self.run(["xcrun", "otool", "-arch", self.architecture,
                                               "-l", str(path)]))
        if parsed.platform not in {"1", "macos"}:
            raise ValueError("AirPlay dependency is not built for macOS: " + str(path))
        if parsed.minimum is None or version_tuple(parsed.minimum) > version_tuple(self.minimum):
            raise ValueError("AirPlay dependency needs a newer macOS than " + self.minimum + ": " + str(path))
        return parsed

    def change(self, path, old, new):
        self.run(["xcrun", "install_name_tool", "-change", old, new, str(path)])

    def set_id(self, path, name):
        self.run(["xcrun", "install_name_tool", "-id", name, str(path)])

    def delete_rpath(self, path, name):
        self.run(["xcrun", "install_name_tool", "-delete_rpath", name, str(path)])

    def sign(self, path):
        self.run(["codesign", "--force", "--sign", "-", str(path)])

    def verify(self, path):
        self.run(["codesign", "--verify", "--strict", str(path)])


class SDK:
    """Explicit immutable inputs; no search in the build machine's libraries."""
    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)
        self.manifest = json.loads(safe_relative(self.path, "sdk.json").read_text())
        if self.manifest.get("schemaVersion") != 1:
            raise ValueError("Unsupported AirPlay SDK manifest")
        self.components = {}
        self.roots = []
        for component in self.manifest.get("components", []):
            name = component.get("name", "")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or name in self.components:
                raise ValueError("Invalid or duplicate SDK component")
            if not component.get("version") or not component.get("license"):
                raise ValueError("SDK component version and license are required: " + name)
            root = safe_relative(self.path, component["root"], directory=True)
            checked_tree(root)
            if any(below(root, existing) or below(existing, root) for existing in self.roots):
                raise ValueError("Overlapping SDK components are ambiguous")
            for field in ("licenseFiles", "sourceArchives"):
                if not component.get(field):
                    raise ValueError("SDK component lacks " + field + ": " + name)
                for entry in component[field]:
                    source = safe_relative(self.path, entry["path"])
                    if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")) or sha256(source) != entry["sha256"]:
                        raise ValueError("SDK source/license hash mismatch: " + entry["path"])
            self.components[name] = component
            self.roots.append(root.resolve())
        required = {"gstreamer": "GStreamer.framework", "openssl": "openssl", "libplist": "libplist"}
        for name, root in required.items():
            if self.components.get(name, {}).get("root") != root:
                raise ValueError("SDK requires component " + name + " at " + root)
        if not str(self.components["openssl"]["version"]).startswith("3."):
            raise ValueError("The internal receiver requires OpenSSL 3")
        self.framework = self.path / "GStreamer.framework"
        self.prefixes = {"/Library/Frameworks/GStreamer.framework": self.framework}
        for old, new in self.manifest.get("loadPrefixMappings", {}).items():
            if not isinstance(old, str) or not old.startswith("/") or ".." in PurePosixPath(old).parts or system_library(old + "/dummy"):
                raise ValueError("Invalid SDK load prefix")
            target = safe_relative(self.path, new, directory=True)
            if target.resolve() not in self.roots:
                raise ValueError("Load prefix must map exactly to a declared SDK component")
            self.prefixes[old.rstrip("/")] = target
        self.initial_hashes = self.inventory()

    def inventory(self):
        result = {"sdk.json": sha256(self.path / "sdk.json")}
        for root in self.roots:
            for path in checked_tree(root):
                result[path.relative_to(self.path).as_posix()] = sha256(path)
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    result[path.relative_to(self.path).as_posix()] = hashlib.sha256(
                        b"symlink\0" + os.readlink(path).encode()).hexdigest()
        for component in self.components.values():
            for entry in component["sourceArchives"] + component["licenseFiles"]:
                result[entry["path"]] = sha256(safe_relative(self.path, entry["path"]))
        return result

    def unchanged(self):
        if self.inventory() != self.initial_hashes:
            raise ValueError("AirPlay SDK changed during packaging")

    def allowed(self, path):
        path = Path(path).resolve()
        return path.is_file() and any(below(path, root) for root in self.roots)

    def absolute(self, name):
        candidate = Path(name)
        if self.allowed(candidate):
            return candidate.resolve()
        for prefix, target in sorted(self.prefixes.items(), key=lambda item: -len(item[0])):
            if name.startswith(prefix + "/"):
                candidate = target / name[len(prefix) + 1:]
                if self.allowed(candidate):
                    return candidate.resolve()
        return None

    def resolve(self, name, loader, executable, rpaths):
        if system_library(name):
            return None
        candidates = set()

        def consider(value):
            if value.startswith("/"):
                match = self.absolute(value)
                if match:
                    candidates.add(match)

        def expand(value):
            if value.startswith("@loader_path/"):
                return str(loader.parent / value[len("@loader_path/"):])
            if value.startswith("@executable_path/"):
                return str(executable.parent / value[len("@executable_path/"):])
            return value

        if name.startswith("@rpath/"):
            suffix = name[len("@rpath/"):]
            if ".." in PurePosixPath(suffix).parts:
                raise ValueError("Parent traversal in dependency runpath")
            for rpath in rpaths:
                consider(expand(rpath).rstrip("/") + "/" + suffix)
            consider(str(self.path / suffix))
            # The supplied SDK is the only permitted fallback, and ambiguity
            # is rejected. This also closes plugins loaded by gst-plugin-scanner
            # separately from the receiver executable.
            for root in self.roots:
                for base in (root / "lib", root / "Versions/Current/lib", root):
                    consider(str(base / suffix))
        else:
            consider(expand(name))
        if len(candidates) != 1:
            raise ValueError("Unresolved or ambiguous non-system AirPlay dependency: " + name)
        return candidates.pop()


def loader_reference(source, target):
    return "@loader_path/" + os.path.relpath(target, source.parent).replace(os.sep, "/")


def relocate_framework_links(source, destination):
    """Preserve SDK-internal absolute links as bundle-internal relative links."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    for path in sorted(destination.rglob("*")):
        if not path.is_symlink() or not Path(os.readlink(path)).is_absolute():
            continue
        target = Path(os.readlink(path)).resolve(strict=True)
        if not target.is_relative_to(source):
            raise ValueError("Copied framework link leaves its original component")
        relocated = destination / target.relative_to(source)
        relative = os.path.relpath(relocated, path.parent)
        path.unlink()
        path.symlink_to(relative, target_is_directory=relocated.is_dir())
    checked_tree(destination)


def copy_closure(sdk, helper, contents, apple):
    """Copy, relocate and audit *all* framework Mach-O files, including plugins."""
    contents = Path(contents).resolve()
    framework = contents / FRAMEWORK
    helper_destination = contents / HELPER
    if framework.exists() or helper_destination.exists():
        raise ValueError("An existing AirPlay bundle is never overwritten")
    framework.parent.mkdir(parents=True, exist_ok=True)
    helper_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(sdk.framework, framework, symlinks=True)
    relocate_framework_links(sdk.framework, framework)
    shutil.copy2(helper, helper_destination)
    helper_destination.chmod(0o755)
    source_to_destination = {Path(helper).resolve(): helper_destination}
    for path in checked_tree(sdk.framework):
        if is_macho(path):
            source_to_destination[path.resolve()] = framework / path.relative_to(sdk.framework)
    pending = list(source_to_destination)
    inspected = {}
    while pending:
        source = pending.pop()
        destination = source_to_destination[source]
        destination.chmod(destination.stat().st_mode | 0o200)
        info = apple.inspect(source)
        inspected[source] = info
        for dependency in info.dependencies:
            target = sdk.resolve(dependency, source, Path(helper), info.rpaths)
            if target is None:
                continue
            if target not in source_to_destination:
                if not is_macho(target):
                    raise ValueError("Runtime dependency is not Mach-O: " + str(target))
                # Component name plus relative path preserves same-named dylibs
                # without accidentally replacing a library from another source.
                component = next(root for root in sdk.roots if below(target, root))
                relative = target.relative_to(component)
                target_destination = contents / "Frameworks/AirPlay" / component.name / relative
                if below(target, sdk.framework):
                    target_destination = framework / target.relative_to(sdk.framework.resolve())
                if not target_destination.exists():
                    target_destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, target_destination)
                source_to_destination[target] = target_destination
                pending.append(target)
            apple.change(destination, dependency, loader_reference(destination, source_to_destination[target]))
        if info.install_id:
            apple.set_id(destination, "@rpath/" + destination.relative_to(contents / "Frameworks").as_posix())
        # Every dependency is now a precise @loader_path reference or an Apple
        # system dependency. External runpaths are unnecessary and inadmissible.
        for rpath in set(info.rpaths):
            apple.delete_rpath(destination, rpath)
    destinations = sorted(set(source_to_destination.values()))
    audit_closed_bundle(contents, destinations, apple)
    for path in destinations:
        apple.sign(path)
    # Sign nested framework bundles after their libraries, then the top-level
    # framework. build_dev.py signs the containing .app last, without --deep.
    nested = [path for path in framework.rglob("*.framework") if path.is_dir() and not path.is_symlink()]
    for path in sorted(nested, key=lambda item: -len(item.parts)) + [framework]:
        apple.sign(path)
    for path in destinations + [framework]:
        apple.verify(path)
    audit_closed_bundle(contents, destinations, apple)
    return destinations


def audit_closed_bundle(contents, binaries, apple):
    contents = Path(contents).resolve()
    known = {path.resolve() for path in binaries}
    for binary in binaries:
        if not below(binary, contents):
            raise ValueError("Packaged binary leaves the application")
        info = apple.inspect(binary)
        if info.rpaths:
            raise ValueError("Unclosed AirPlay runpath remains")
        for dependency in info.dependencies:
            if system_library(dependency):
                continue
            if not dependency.startswith("@loader_path/"):
                raise ValueError("External dependency remains in AirPlay bundle: " + dependency)
            target = (binary.parent / dependency[len("@loader_path/"):]).resolve()
            if not below(target, contents) or target not in known or not target.is_file():
                raise ValueError("Missing or escaping AirPlay bundle dependency: " + dependency)


def source_archive(receiver, destination):
    """Ship the exact integrated source, including Magnolie's bridge changes."""
    receiver = Path(receiver)
    files = [path for path in checked_tree(receiver)
             if not any(part in {".build", "build", "CMakeFiles", "__pycache__"}
                        for part in path.relative_to(receiver).parts)]
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in files:
                    info = archive.gettarinfo(str(path), "Magnolie-AirPlay-Receiver/" + path.relative_to(receiver).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as source:
                        archive.addfile(info, source)


def sdk_environment(sdk, minimum):
    environment = dict(os.environ)
    # A build environment may select its compiler/tools; dependency search and
    # deployment target are pinned to the explicit input stage.
    for name in tuple(environment):
        if name.startswith(("DYLD_", "GST_", "CMAKE_", "PKG_CONFIG_")) or name in {
                "CPATH", "LIBRARY_PATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH",
                "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "OBJCFLAGS", "OBJCXXFLAGS"}:
            environment.pop(name, None)
    directories = [sdk.framework / "Versions/Current/lib/pkgconfig", sdk.path / "openssl/lib/pkgconfig",
                   sdk.path / "libplist/lib/pkgconfig"]
    for root in sdk.roots:
        path = root / "lib/pkgconfig"
        if path.is_dir() and path not in directories:
            directories.append(path)
    if any(not path.is_dir() for path in directories):
        raise ValueError("Incomplete AirPlay development SDK (pkg-config directories)")
    environment.update(MACOSX_DEPLOYMENT_TARGET=minimum, PKG_CONFIG_PATH="",
                       PKG_CONFIG_LIBDIR=os.pathsep.join(map(str, directories)))
    return environment


def prepare_pkgconfig(sdk, environment, target):
    """Relocate declared .pc prefixes in private build copies, never in the SDK."""
    target.mkdir()
    modules = {}
    for directory in environment["PKG_CONFIG_LIBDIR"].split(os.pathsep):
        for path in sorted(Path(directory).glob("*.pc")):
            text = path.read_text()
            # Preserve pcfiledir's meaning even though the copy is in a private
            # scratch directory. Ordinary ${prefix} variables stay untouched.
            text = text.replace("${pcfiledir}", str(path.parent))
            for old, new in sorted(sdk.prefixes.items(), key=lambda item: -len(item[0])):
                text = text.replace(old, str(new))
            if path.name in modules and modules[path.name] != text:
                raise ValueError("Ambiguous pkg-config module in SDK: " + path.name)
            modules[path.name] = text
    for name, text in modules.items():
        (target / name).write_text(text)
    return dict(environment, PKG_CONFIG_LIBDIR=str(target))


def check_pkgconfig_paths(sdk, environment):
    modules = ["gstreamer-1.0", "gstreamer-sdp-1.0", "gstreamer-video-1.0",
               "gstreamer-app-1.0", "glib-2.0", "libplist-2.0", "openssl"]
    result = subprocess.check_output(["pkg-config", "--cflags", "--libs", *modules],
                                     env=environment, text=True)
    for argument in shlex.split(result):
        if argument.startswith(("-I", "-L", "-F")):
            value = argument[2:]
            if not value or not Path(value).is_absolute() or not any(below(value, root) for root in sdk.roots):
                raise ValueError("pkg-config refers outside the explicit AirPlay SDK: " + argument)
        elif argument.startswith("/") and not system_library(argument):
            if not sdk.allowed(argument):
                raise ValueError("pkg-config links a library outside the AirPlay SDK: " + argument)


def verify_receiver_source(receiver):
    provenance = json.loads((receiver / "UPSTREAM.json").read_text())
    if provenance.get("version") != UPSTREAM_VERSION or provenance.get("revision") != UPSTREAM_COMMIT:
        raise ValueError("Unexpected internal AirPlay upstream revision")
    hashes = provenance.get("vendored_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Missing vendored AirPlay source inventory")
    vendor = receiver / "vendor/UxPlay"
    if any(path.is_symlink() for path in vendor.rglob("*")):
        raise ValueError("Symlinked vendored AirPlay source refused")
    actual = {file.relative_to(vendor).as_posix(): sha256(file) for file in checked_tree(vendor)}
    if actual != hashes:
        raise ValueError("Vendored AirPlay source differs from its checked manifest")


def build_airplay_bundle(beta, app, sdk_path, architecture, minimum="12.7"):
    if platform.system() != "Darwin":
        raise RuntimeError("The AirPlay bundle must be built and audited on macOS")
    for tool in ("cmake", "pkg-config", "xcrun", "codesign"):
        if not shutil.which(tool):
            raise RuntimeError("Missing AirPlay build tool: " + tool)
    sdk = SDK(sdk_path)
    beta, contents = Path(beta), Path(app) / "Contents"
    receiver = beta / "Receiver"
    if not (receiver / "CMakeLists.txt").is_file():
        raise ValueError("Integrated AirPlay receiver source is absent")
    verify_receiver_source(receiver)
    environment = sdk_environment(sdk, minimum)
    apple = AppleTools(architecture, minimum)
    with tempfile.TemporaryDirectory(prefix="magnolie-airplay-build-") as temporary:
        build = Path(temporary)
        environment = prepare_pkgconfig(sdk, environment, build / "pkgconfig")
        check_pkgconfig_paths(sdk, environment)
        for component, module in (("gstreamer", "gstreamer-1.0"), ("openssl", "openssl"), ("libplist", "libplist-2.0")):
            version = subprocess.check_output(["pkg-config", "--modversion", module], env=environment, text=True).strip()
            if version != sdk.components[component]["version"]:
                raise ValueError("SDK version differs from pkg-config: " + component)
        arguments = ["cmake", "-S", str(receiver), "-B", str(build),
                     "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_OSX_ARCHITECTURES=" + architecture,
                     "-DCMAKE_OSX_DEPLOYMENT_TARGET=" + minimum,
                     "-DOPENSSL_ROOT_DIR=" + str(sdk.path / "openssl"), "-DOPENSSL_USE_STATIC_LIBS=FALSE",
                     "-DMAGNOLIE_AIRPLAY_SDK_ROOT=" + str(sdk.path),
                     "-DCMAKE_FIND_ROOT_PATH=" + str(sdk.path),
                     "-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY", "-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY",
                     "-DCMAKE_PREFIX_PATH=" + ";".join(map(str, sdk.roots)),
                     "-DCMAKE_EXE_LINKER_FLAGS=-Wl,-headerpad_max_install_names",
                     "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE", "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE"]
        subprocess.run(arguments, env=environment, check=True, timeout=180)
        subprocess.run(["cmake", "--build", str(build), "--parallel", "2"], env=environment, check=True, timeout=600)
        helper = build / "magnolie-airplay-receiver"
        if not helper.is_file() or not is_macho(helper):
            raise ValueError("Internal AirPlay helper was not built")
        binaries = copy_closure(sdk, helper, contents, apple)
    for name, value in RUNTIME.items():
        safe_relative(contents, value, directory=name != "pluginScanner")
    resources = contents / "Resources/AirPlay"
    resources.mkdir(parents=True, exist_ok=False)
    source_archive(receiver, resources / "Magnolie-AirPlay-Receiver-source.tar.gz")
    components = []
    for component in sdk.components.values():
        copied = dict(component)
        copied.pop("root", None)
        for field, directory in (("licenseFiles", "Licenses"), ("sourceArchives", "Sources")):
            copied[field] = []
            for entry in component[field]:
                source = safe_relative(sdk.path, entry["path"])
                destination = resources / directory / component["name"] / Path(entry["path"]).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ValueError("Colliding SDK notice/source archive filenames")
                shutil.copy2(source, destination)
                copied[field].append({"path": destination.relative_to(contents).as_posix(), "sha256": sha256(destination)})
        components.append(copied)
    sdk.unchanged()
    provenance = {
        "schemaVersion": 1, "uxplayVersion": UPSTREAM_VERSION, "uxplayCommit": UPSTREAM_COMMIT,
        "components": components, "sdkInputSHA256": sdk.initial_hashes,
        "receiverSourceSHA256": sha256(resources / "Magnolie-AirPlay-Receiver-source.tar.gz"),
        "binaries": {path.relative_to(contents).as_posix(): sha256(path) for path in binaries},
    }
    provenance_path = resources / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    manifest = {
        "schemaVersion": 1, "protocolVersion": 1, "helper": HELPER,
        "uxplayVersion": UPSTREAM_VERSION, "uxplayCommit": UPSTREAM_COMMIT,
        "architecture": architecture, "minimumSystemVersion": minimum,
        "runtime": RUNTIME, "dependencyClosureVerified": True,
        "nativeDeviceValidated": False, "signing": "ad-hoc development only, not notarized",
        "provenance": "Resources/AirPlay/provenance.json", "provenanceSHA256": sha256(provenance_path),
    }
    (resources / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
