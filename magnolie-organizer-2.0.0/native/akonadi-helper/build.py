#!/usr/bin/env python3
"""Standalone multi-rootfs source recipe for ONE optional KDE DEB."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from launcher import QUERY, closure, package_db
from profiles import PROFILES, artifacts, build_depends

SOURCE = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    files = [p for p in SOURCE.iterdir() if p.is_file()]
    files += [p for folder in ("debian", "tests") for p in (SOURCE / folder).rglob("*") if p.is_file()]
    return {str(p.relative_to(SOURCE)): {"sha256": sha(p), "mode": stat.S_IMODE(p.stat().st_mode)}
            for p in sorted(files) if "__pycache__" not in p.parts
            and p.name not in {"files", "debhelper-build-stamp"}
            and not p.name.endswith((".substvars", ".debhelper.log"))
            and not any(part.startswith(".debhelper") or part == "magnolie-organizer-kde" for part in p.relative_to(SOURCE).parts)}


def bounded():
    """An aggregate memory cap, not merely a per-compiler address-space limit."""
    group = Path("/sys/fs/cgroup") / Path(Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]).relative_to("/")
    limits = [group, *list(group.parents)[:-2]]
    memory = any((p / "memory.max").is_file() and (p / "memory.max").read_text().strip() != "max"
                 and int((p / "memory.max").read_text()) <= 6 * 1024**3 for p in limits)
    cpu = False
    for p in limits:
        if (p / "cpu.max").is_file():
            quota, period = (p / "cpu.max").read_text().split()
            cpu |= quota != "max" and int(quota) <= 2 * int(period)
    return memory and cpu


def sandbox(rootfs, source, work, epoch):
    return ["bwrap", "--unshare-all", "--die-with-parent", "--uid", "0", "--gid", "0",
        "--ro-bind", str(rootfs), "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--ro-bind", str(source), "/tmp/source", "--bind", str(work), "/tmp/build", "--chdir", "/tmp/build",
        "--clearenv", "--setenv", "PATH", "/usr/sbin:/usr/bin:/sbin:/bin", "--setenv", "HOME", "/tmp",
        "--setenv", "LC_ALL", "C.UTF-8", "--setenv", "SOURCE_DATE_EPOCH", str(epoch),
        "--setenv", "DEB_BUILD_OPTIONS", "parallel=2", "--setenv", "CMAKE_BUILD_PARALLEL_LEVEL", "2",
        "--setenv", "LD_BIND_NOW", "1", "--setenv", "DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/no-session"]


def payload(destination, epoch):
    destination.mkdir(parents=True, exist_ok=True)
    libexec = destination / "usr/libexec/magnolie-organizer"
    records = {}
    for target, profile in PROFILES.items():
        rootfs = Path(os.environ.get(profile["env"], profile["rootfs"])).resolve()
        release = dict(line.split("=", 1) for line in (rootfs / "etc/os-release").read_text().splitlines() if "=" in line)
        require(release["ID"].strip('"') == profile["os"] and release["VERSION_ID"].strip('"') == profile["version"],
                "Wrong KDE build rootfs: " + target)
        with tempfile.TemporaryDirectory(prefix="kde-native-") as temporary:
            work = Path(temporary)
            (work / "debian").mkdir()
            (work / "debian/control").write_text("Source: magnolie-kde-backend\nBuild-Depends: " + build_depends(target) +
                "\n\nPackage: magnolie-kde-backend\nArchitecture: amd64\nDepends: ${shlibs:Depends}\n")
            base = sandbox(rootfs, SOURCE, work, epoch)

            def run(*command, **kwargs):
                result = subprocess.run(base + list(command), **kwargs)
                if result.returncode and kwargs.get("capture_output"):
                    print(result.stdout, result.stderr, file=sys.stderr)
                result.check_returncode()
                return result

            require(run("dpkg", "--print-architecture", capture_output=True, text=True).stdout.strip() == "amd64", "Not amd64")
            audit = run("dpkg", "--audit", capture_output=True, text=True)
            require(not audit.stdout.strip() and not audit.stderr.strip(), "Unconfigured rootfs packages")
            run("dpkg-checkbuilddeps")
            database = run(*QUERY, capture_output=True, text=True).stdout
            packages = package_db(database)
            flags = (["-DCMAKE_DISABLE_FIND_PACKAGE_KPim6Akonadi=ON"] if profile["qt"] == 5 else
                     ["-DCMAKE_REQUIRE_FIND_PACKAGE_" + name + "=ON" for name in ("KPim6Akonadi", "KF6CalendarCore", "KF6Contacts")])
            run("cmake", "-S", "/tmp/source", "-B", "/tmp/build/cmake", "-DCMAKE_BUILD_TYPE=Release", *flags)
            run("cmake", "--build", "/tmp/build/cmake", "--parallel", "2")
            run("ctest", "--test-dir", "/tmp/build/cmake", "--output-on-failure")
            binary = work / "cmake/magnolie-akonadi-helper"
            run("strip", "--strip-unneeded", "/tmp/build/cmake/magnolie-akonadi-helper")
            generated = run("dpkg-shlibdeps", "-O", "-e/tmp/build/cmake/magnolie-akonadi-helper", capture_output=True, text=True)
            require(generated.stdout.startswith("shlibs:Depends="), "No native shlibdeps output")
            deps = generated.stdout.strip().removeprefix("shlibs:Depends=")
            require(profile["abi"] in deps and f"libqt{profile['qt']}core" in deps, "Missing genuine target ABI requirement")
            native_closure = closure("akonadi-server, " + deps, packages)
            ldd = run("ldd", "/tmp/build/cmake/magnolie-akonadi-helper", capture_output=True, text=True).stdout
            require("not found" not in ldd, "Incomplete native library closure")
            libraries = {}
            for line in ldd.splitlines():
                fields = line.split()
                path = fields[2] if "=>" in fields else fields[0]
                if path.startswith("/"):
                    real = run("readlink", "-f", path, capture_output=True, text=True).stdout.strip()
                    owner = subprocess.run(base + ["dpkg-query", "-S", real], capture_output=True, text=True)
                    if owner.returncode and real.startswith("/usr/"):
                        owner = run("dpkg-query", "-S", real.removeprefix("/usr"), capture_output=True, text=True)
                    require(owner.returncode == 0, "Native library has no package owner: " + path)
                    libraries[path] = {"sha256": run("sha256sum", path, capture_output=True, text=True).stdout.split()[0],
                                       "owner": owner.stdout.strip(), "realpath": real}
            targetdir = libexec / "kde" / target
            targetdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, targetdir / "backend")
            manifest = {"schema": "magnolie-kde-backend-v1", "target": target, "abi": profile["abi"],
                "requirements": "akonadi-server, " + deps, "sha256": sha(binary)}
            (targetdir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            require(json.loads(run("/tmp/build/cmake/magnolie-akonadi-helper", "--self-check", capture_output=True, text=True).stdout)
                    == {"ok": True, "selfCheck": True}, "Native self-check failed")
            for command, error in (("unsupported-smoke", "unsupported command"), ("status", "KDE service is not running")):
                probe = subprocess.run(base + ["/tmp/build/cmake/magnolie-akonadi-helper"],
                    input=json.dumps({"command": command}), capture_output=True, text=True, timeout=15)
                reply = json.loads(probe.stdout)
                require(probe.returncode == 1 and reply["ok"] is False and error in reply["error"], "Protocol smoke failed")
            records[target] = {"manifest": manifest, "shlibdeps": generated.stdout, "shlibdepsDiagnostics": generated.stderr,
                "closure": native_closure, "libraries": libraries, "osRelease": release,
                "buildDepends": build_depends(target), "packageDatabaseSha256": hashlib.sha256(database.encode()).hexdigest(),
                "serialization": True, "protocolSmoke": True, "selfCheck": True, "installedLiveKde": False}
            # Keep the genuine package database, not just a claim that dependency checks passed.
            (targetdir / "build-audit.json").write_text(json.dumps(records[target], indent=2, sort_keys=True) + "\n")
            (targetdir / "build-packages.tsv").write_text(database)
            print("KDE native build passed: " + target, flush=True)
    shutil.copy2(SOURCE / "launcher.py", libexec / "magnolie-akonadi-helper")
    (libexec / "magnolie-akonadi-helper").chmod(0o755)
    (destination.parent / "native-records.json").write_text(json.dumps(records, sort_keys=True, indent=2) + "\n")


def component(output, epoch):
    identity = inputs()
    version = subprocess.check_output(["dpkg-parsechangelog", "-SVersion"], cwd=SOURCE, text=True).strip()
    output.mkdir(parents=True, exist_ok=True)
    require(not any(output.glob("magnolie-organizer-*")), "Use a fresh component output directory; old candidates are not overwritten")
    with tempfile.TemporaryDirectory(prefix="kde-one-") as temporary:
        work = Path(temporary)
        project = work / "akonadi-helper"
        for name in identity:
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / name, target)
        require(identity == inputs(), "KDE component source changed during projection")
        for path in [project, *project.rglob("*")]:
            os.utime(path, (epoch, epoch))
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch), DEB_BUILD_OPTIONS="parallel=2")
        # Build the coherent .dsc before binary build products exist.
        subprocess.run(["dpkg-buildpackage", "-S", "-us", "-uc"], cwd=project, env=env, check=True)
        hashes = []
        for _ in range(2):
            subprocess.run(["dpkg-buildpackage", "-b", "-us", "-uc", "--jobs=2"], cwd=project, env=env, check=True)
            hashes.append(sha(work / artifacts(version)[0]))
        require(hashes[0] == hashes[1], "Single KDE DEB is not reproducible")
        package = work / artifacts(version)[0]
        installed = work / "installed"
        subprocess.run(["dpkg-deb", "-x", str(package), str(installed)], check=True)
        extracted = installed / "usr/libexec/magnolie-organizer"
        records = json.loads((project / "build/native-records.json").read_text())
        for target, profile in PROFILES.items():
            rootfs = Path(os.environ.get(profile["env"], profile["rootfs"])).resolve()
            base = sandbox(rootfs, project, work, epoch)
            check = subprocess.run(base + ["/tmp/build/installed/usr/libexec/magnolie-organizer/magnolie-akonadi-helper", "--check"],
                capture_output=True, text=True, timeout=30)
            require(check.returncode == 0 and json.loads(check.stdout) == {"ok": True, "target": target, "activated": False},
                    "Same-artifact launcher check failed: " + target + ": " + check.stdout + check.stderr)
            records[target]["sameArtifactCheck"] = hashes[0]
            records[target]["manifestSha256"] = sha(extracted / "kde" / target / "manifest.json")
        require(identity == inputs(), "KDE component source changed; unrelated UI files are not part of this freeze")
        names = artifacts(version)[:-1]
        proof = {"schema": "magnolie-kde-build-v2", "version": version, "sourceIdentity": identity,
            "artifacts": {n: sha(work / n) for n in names}, "profiles": records, "reproducible": True,
            "resources": {"maxCpus": 2, "memoryMaxBytes": 6 * 1024**3, "sequential": True},
            "installedLiveKde": False, "published": False}
        for name in names:
            shutil.copy2(work / name, output / name)
        (output / artifacts(version)[-1]).write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"artifacts": proof["artifacts"], "output": str(output)}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--payload", type=Path)
    args = parser.parse_args()
    require(bool(args.output) != bool(args.payload), "Choose component output or --payload")
    if not bounded():
        require(os.environ.get("MAGNOLIE_KDE_SCOPE") != "1", "Cannot enforce KDE build cgroup limits")
        command = ["systemd-run", "--user", "--scope", "--quiet", "-p", "CPUQuota=200%", "-p", "MemoryMax=6G",
                   "-p", "MemorySwapMax=0", "env", "MAGNOLIE_KDE_SCOPE=1", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
        return subprocess.call(command)
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    os.nice(10)
    epoch = int(subprocess.check_output(["dpkg-parsechangelog", "-STimestamp"], cwd=SOURCE, text=True).strip())
    if args.payload:
        payload(args.payload.resolve(), epoch)
    else:
        with open(Path(tempfile.gettempdir()) / ("magnolie-kde-component-" + str(os.getuid()) + ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            component(args.output.resolve(), epoch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
