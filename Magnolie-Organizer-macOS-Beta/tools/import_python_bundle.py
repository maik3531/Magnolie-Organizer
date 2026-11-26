#!/usr/bin/env python3
"""#785: build a private, relocated CPython from an explicitly pinned source.

This is a development build dependency, never an application-start install.
No Homebrew/Python-framework or user-Python fallback is accepted. Runtime
images may link only Apple system libraries. All bundle paths are fixed.
"""
import argparse
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
import urllib.parse
import urllib.request

from airplay_bundle import is_macho, system_library

BETA = Path(__file__).resolve().parents[1]
PIN = json.loads((BETA / "Resources/ImportPython.json").read_text())
LIBLZMA_PIN = PIN["liblzma"]
MAXIMUM_EXPANDED = 256 * 1024 * 1024
EXCLUDED = {"__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip", "site-packages"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path, pin=PIN):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= pin["maximumArchiveBytes"]:
        raise ValueError("Invalid " + pin["implementation"] + " source archive")
    if sha256(path) != pin["sourceSHA256"]:
        raise ValueError(pin["implementation"] + " source archive checksum mismatch")


def source_url_allowed(url, pin):
    if url == pin["sourceURL"]:
        return True
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in pin.get("allowedRedirectHosts", []) and
            parsed.port in (None, 443) and parsed.username is None and parsed.password is None)


def fetch_archive(path, pin=PIN):
    """Explicit build-tool operation; the installed app has no download path."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        verify_archive(path, pin)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="python-source-", delete=False) as output:
        temporary = Path(output.name)
        try:
            with urllib.request.urlopen(pin["sourceURL"], timeout=60) as source:
                if not source_url_allowed(source.geturl(), pin):
                    raise ValueError("Unexpected " + pin["implementation"] + " download redirect")
                size = 0
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if size > pin["maximumArchiveBytes"]:
                        raise ValueError(pin["implementation"] + " download exceeds its size bound")
                    output.write(block)
            output.flush()
            os.fsync(output.fileno())
            verify_archive(temporary, pin)
            # Keep a concurrently supplied file; do not replace someone else's input.
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def extract_source(archive, destination, pin=PIN):
    """No links, special files, traversal or unbounded tar expansion."""
    root_name = pin.get("sourceRoot", "Python-" + pin["version"])
    label = pin["implementation"]
    seen, expanded = set(), 0
    with tarfile.open(archive, "r:xz") as source:
        members = source.getmembers()
        if len(members) > 20000:
            raise ValueError("Too many " + label + " source members")
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or not path.parts or path.parts[0] != root_name or
                    any(part in ("", ".", "..") for part in member.name.rstrip("/").split("/")) or
                    "\\" in member.name or member.name in seen or not (member.isdir() or member.isfile())):
                raise ValueError("Unsafe " + label + " source member")
            seen.add(member.name)
            expanded += member.size
            if member.size < 0 or expanded > pin.get("maximumExpandedBytes", MAXIMUM_EXPANDED):
                raise ValueError(label + " source expansion exceeds its bound")
        for member in members:
            target = Path(destination) / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    return Path(destination) / root_name


def extension_output(path, source):
    """Resolve only CPython's generated build/lib.* -> ../../Modules/name link."""
    path, source = Path(path), Path(source)
    if (source.is_symlink() or (source / "build").is_symlink() or path.parent.is_symlink() or
            path.parent.parent != source / "build" or not path.parent.name.startswith("lib.") or
            path.suffix != ".so"):
        raise ValueError("Invalid CPython extension output path")
    if not path.is_symlink():
        if not path.is_file():
            raise ValueError("Invalid CPython extension output file")
        return path
    target = source / "Modules" / path.name
    if (os.readlink(path) != "../../Modules/" + path.name or (source / "Modules").is_symlink() or
            target.is_symlink() or not target.is_file()):
        raise ValueError("Unapproved CPython extension output link")
    return target


def build_liblzma(archive, temporary, environment):
    """Build only the pinned static codec and headers into an owned temporary prefix."""
    verify_archive(archive, LIBLZMA_PIN)
    temporary = Path(temporary)
    source = extract_source(archive, temporary, LIBLZMA_PIN)
    build, prefix = temporary / "liblzma-build", temporary / "liblzma-sdk"
    build.mkdir()
    subprocess.run([str(source / "configure"), "--prefix=" + str(prefix),
                    "--disable-shared", "--enable-static", "--enable-pic", "--disable-xz",
                    "--disable-xzdec", "--disable-lzmadec", "--disable-lzmainfo", "--disable-lzma-links",
                    "--disable-scripts", "--disable-doc", "--disable-nls", "--disable-dependency-tracking",
                    "--disable-rpath"], cwd=build, env=environment, check=True, timeout=180)
    library_build = build / "src" / "liblzma"
    subprocess.run(["make", "-C", str(library_build), "-j2"], env=environment, check=True, timeout=300)
    subprocess.run(["make", "-C", str(library_build), "install"], env=environment, check=True, timeout=120)
    files = checked_files(prefix)
    library, include = prefix / "lib" / "liblzma.a", prefix / "include"
    if (not library.is_file() or not (include / "lzma.h").is_file() or
            library.read_bytes()[:8] != b"!<arch>\n" or
            any(path.suffix in (".so", ".dylib") for path in files)):
        raise ValueError("Pinned liblzma did not produce a private static SDK")
    return {"source": source, "library": library, "include": include,
            "proof": {"version": LIBLZMA_PIN["version"], "sourceSHA256": LIBLZMA_PIN["sourceSHA256"],
                      "linkage": "static", "librarySHA256": sha256(library)}}


def checked_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Runtime must be a real directory")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Linked or special runtime file refused")
        if path.is_file():
            files.append(path)
    return files


def version_tuple(value):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", value):
        raise ValueError("Invalid Mach-O minimum OS")
    parts = [int(part) for part in value.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def check_macho(path, architecture, minimum):
    arch = subprocess.check_output(["lipo", "-archs", str(path)], text=True).strip().split()
    if arch != [architecture]:
        raise ValueError("Import runtime architecture mismatch")
    build = subprocess.check_output(["xcrun", "vtool", "-show-build", str(path)], text=True)
    targets = re.findall(r"^\s*minos\s+(\S+)\s*$", build, re.MULTILINE)
    if not targets or any(version_tuple(value) > version_tuple(minimum) for value in targets):
        raise ValueError("Import runtime exceeds the application's minimum macOS")
    links = subprocess.check_output(["otool", "-L", str(path)], text=True).splitlines()[1:]
    libraries = [line.strip().split(" (compatibility version", 1)[0] for line in links if line.strip()]
    if not libraries or any(not system_library(library) for library in libraries):
        raise ValueError("Import runtime has a non-system dynamic dependency")
    return {"minimumOS": targets, "dependencies": libraries}


def verify_relocation(runtime):
    """Executed on the final relocated tree, with hostile Python env ignored."""
    runtime = Path(runtime).resolve()
    script = (
        "import importlib,json,os,sys; root=os.path.realpath(sys.argv[1]); "
        "[importlib.import_module(x) for x in json.loads(sys.argv[2])]; "
        "assert sys.version.split()[0]==sys.argv[3]; "
        "assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode; "
        "assert os.path.realpath(sys.prefix)==root; "
        "assert all(os.path.commonpath([root,os.path.realpath(x)])==root for x in sys.path); "
        "print(json.dumps({'version':sys.version.split()[0],'isolated':True,'moduleClosure':True}))"
    )
    with tempfile.TemporaryDirectory(prefix="magnolie-python-hostile-") as hostile:
        Path(hostile, "sitecustomize.py").write_text("raise RuntimeError('external Python path admitted')\n")
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": hostile, "PYTHONHOME": hostile}
        response = subprocess.check_output(
            [str(runtime / PIN["executable"]), "-I", "-S", "-B", "-c", script, str(runtime),
             json.dumps(PIN["requiredModules"]), PIN["version"]], cwd=hostile, env=environment,
            timeout=30, text=True)
    return json.loads(response)


def build_runtime(archive, destination, architecture, minimum, liblzma_archive=None):
    if platform.system() != "Darwin" or architecture != platform.machine() or architecture not in ("arm64", "x86_64"):
        raise ValueError("A matching native Apple build host is required")
    if minimum != PIN["minimumSystemVersion"]:
        raise ValueError("Unreviewed import runtime deployment target")
    verify_archive(archive)
    liblzma_archive = Path(liblzma_archive) if liblzma_archive is not None else Path(archive).with_name(LIBLZMA_PIN["archiveName"])
    verify_archive(liblzma_archive, LIBLZMA_PIN)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Existing runtime output retained")
    sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    compiler = subprocess.check_output(["xcrun", "--find", "clang"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="magnolie-cpython-build-") as temporary:
        source = extract_source(archive, temporary)
        # Exclude optional third-party services. liblzma is statically linked
        # from the pinned source; all required codecs are checked after relocation.
        (source / "Modules/Setup.local").write_text(
            "*disabled*\n" + "\n".join(["_ssl", "_hashlib", "_tkinter", "_ctypes", "_sqlite3",
                                        "_gdbm", "_dbm", "readline", "_curses", "_curses_panel",
                                        "_zstd", "_remote_debugging"]) + "\n")
        environment = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C",
            "CC": shlex.quote(compiler), "MACOSX_DEPLOYMENT_TARGET": minimum,
            "CFLAGS": f"-O2 -arch {architecture} -isysroot {shlex.quote(sdk)} -mmacosx-version-min={minimum}",
            "LDFLAGS": f"-arch {architecture} -isysroot {shlex.quote(sdk)} -mmacosx-version-min={minimum}",
        }
        liblzma = build_liblzma(liblzma_archive, temporary, environment)
        python_environment = dict(environment,
                                  LIBLZMA_CFLAGS="-I" + shlex.quote(str(liblzma["include"])),
                                  LIBLZMA_LIBS=shlex.quote(str(liblzma["library"])))
        subprocess.run([str(source / "configure"), "--prefix=" + str(Path(temporary) / "not-installed"),
                        "--disable-shared", "--without-ensurepip", "--disable-test-modules",
                        "--without-readline", "--with-pkg-config=no", "--enable-experimental-jit=no"],
                       cwd=source, env=python_environment, check=True, timeout=180)
        subprocess.run(["make", "-j2"], cwd=source, env=python_environment, check=True, timeout=900)
        (destination / "bin").mkdir(parents=True)
        # CPython calls this python.exe on case-insensitive Mac volumes because
        # its source already contains a directory named Python.
        binaries = [path for path in [source / "python", source / "python.exe"] if path.is_file() and not path.is_symlink()]
        if len(binaries) != 1:
            raise ValueError("Ambiguous CPython executable output")
        shutil.copy2(binaries[0], destination / PIN["executable"])
        library = destination / "lib" / ("python" + PIN["series"])
        shutil.copytree(source / "Lib", library, ignore=lambda _, names: [name for name in names if name in EXCLUDED])
        dynamic = library / "lib-dynload"
        dynamic.mkdir()
        builds = list((source / "build").glob("lib.*"))
        if len(builds) != 1 or builds[0].is_symlink() or not builds[0].is_dir():
            raise ValueError("Ambiguous CPython extension output")
        for path in sorted(builds[0].iterdir()):
            if path.suffix == ".so":
                shutil.copy2(extension_output(path, source), dynamic / path.name)
            elif path.is_symlink():
                raise ValueError("Linked CPython metadata output refused")
            elif path.name.startswith("_sysconfigdata_") and path.suffix == ".py":
                shutil.copy2(path, library / path.name)
        shutil.copy2(source / "LICENSE", destination / "LICENSE-Python.txt")
        for original, installed in LIBLZMA_PIN["licenseFiles"].items():
            shutil.copy2(liblzma["source"] / original, destination / installed)
    # No original build path remains available at this point.
    proof = verify_relocation(destination)
    images = {}
    for path in checked_files(destination):
        if is_macho(path):
            images[str(path.relative_to(destination))] = check_macho(path, architecture, minimum)
            subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True)
            subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
    if PIN["executable"] not in images:
        raise ValueError("Runtime executable is not Mach-O")
    manifest = {"schema": 1, "pin": PIN, "architecture": architecture, "minimumSystemVersion": minimum,
                "relocation": proof, "machO": images,
                "staticDependencies": {"liblzma": liblzma["proof"]},
                "files": {str(path.relative_to(destination)): sha256(path) for path in checked_files(destination)},
                "signing": "ad-hoc development only", "nativeUIValidated": False}
    (destination / "runtime.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def bundle_runtime(app, runtime):
    """Accept only the exact, complete locally built SDK; sign nested images first."""
    runtime = Path(runtime)
    manifest = json.loads((runtime / "runtime.json").read_text())
    if (manifest.get("schema") != 1 or manifest.get("pin") != PIN or
            manifest.get("architecture") != platform.machine() or
            manifest.get("minimumSystemVersion") != PIN["minimumSystemVersion"]):
        raise ValueError("Import runtime identity mismatch")
    actual = {str(path.relative_to(runtime)): sha256(path) for path in checked_files(runtime) if path.name != "runtime.json"}
    if manifest.get("files") != actual:
        raise ValueError("Import runtime inventory mismatch")
    target = Path(app) / "Contents" / PIN["bundleDirectory"]
    shutil.copytree(runtime, target)
    for path in checked_files(target):
        if is_macho(path):
            check_macho(path, platform.machine(), PIN["minimumSystemVersion"])
            subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
    verify_relocation(target)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--liblzma-source-archive", type=Path,
                        help="Pinned XZ archive; defaults to its pinned filename beside the CPython archive")
    parser.add_argument("--download", action="store_true", help="Explicitly fetch the checksum-pinned build source")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    liblzma_archive = arguments.liblzma_source_archive or arguments.source_archive.with_name(LIBLZMA_PIN["archiveName"])
    if arguments.download:
        fetch_archive(arguments.source_archive)
        fetch_archive(liblzma_archive, LIBLZMA_PIN)
    result = build_runtime(arguments.source_archive, arguments.output, platform.machine(), PIN["minimumSystemVersion"], liblzma_archive)
    print(json.dumps({"version": PIN["version"], "architecture": result["architecture"], "relocated": True}))


if __name__ == "__main__":
    main()
