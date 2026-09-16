#!/usr/bin/python3 -I
"""Fail-closed selection of an optional KDE backend using the installed dpkg DB.

No apt, distro-name heuristic, D-Bus activation, or account setup is performed.
The build also uses this exact dependency resolver to audit genuine rootfs data.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FIELDS = ("Package", "Architecture", "Status", "Version", "Provides", "Depends", "Pre-Depends", "Multi-Arch")
QUERY = ["/usr/bin/dpkg-query", "-W", "-f=" + "\t".join("${" + f + "}" for f in FIELDS) + "\n"]
ATOM = re.compile(r"([a-z0-9][a-z0-9+.-]*)(?::(any|native|[a-z0-9-]+))?(?:\s*\((<<|<=|=|>=|>>)\s*([^()\s]+)\))?")


def package_db(text):
    packages = []
    for line in text.splitlines():
        values = line.split("\t")
        if len(values) != len(FIELDS):
            raise ValueError("KDE dependency database is malformed")
        record = dict(zip(FIELDS, values))
        if record["Status"].split()[1:] == ["ok", "installed"]:
            packages.append(record)
    return packages


def atom(text):
    match = ATOM.fullmatch(text.strip())
    if not match:
        raise ValueError("Unsupported KDE dependency expression: " + text)
    return match.groups()


def closure(requirements, packages):
    """Resolve all Depends/Pre-Depends, including versioned virtual Provides.

    Cycles are allowed only within the current alternative's traversal. A broken
    alternative must not make another alternative appear configured and complete.
    """
    index = {}
    for package in packages:
        index.setdefault(package["Package"], []).append((package, package["Version"]))
        for provided in filter(None, package["Provides"].split(",")):
            name, arch, op, version = atom(provided)
            if arch or op not in (None, "="):
                raise ValueError("Invalid installed KDE Provides")
            index.setdefault(name, []).append((package, version))

    def resolve(expression, visited):
        result = dict(visited)
        for group in filter(None, expression.split(",")):
            selected = None
            for alternative in group.split("|"):
                name, arch, op, version = atom(alternative)
                for package, provided_version in index.get(name, []):
                    pa = package["Architecture"]
                    if arch == "any":
                        if package["Multi-Arch"] != "allowed":
                            continue
                    elif pa not in ("all", "amd64" if arch in (None, "native") else arch):
                        if arch is not None or package["Multi-Arch"] != "foreign":
                            continue
                    if op and (provided_version is None or subprocess.run(
                            ["/usr/bin/dpkg", "--compare-versions", provided_version, op, version],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0):
                        continue
                    key = package["Package"] + ":" + pa
                    branch = dict(result)
                    if key not in branch:
                        branch[key] = package
                        try:
                            branch = resolve(",".join(filter(None, (package["Pre-Depends"], package["Depends"]))), branch)
                        except ValueError:
                            continue
                    selected = branch
                    break
                if selected is not None:
                    break
            if selected is None:
                raise ValueError("KDE requires configured native dependencies: " + group.strip())
            result = selected
        return result

    return resolve(requirements, {})


def select_backend(directory, packages):
    # Require the existing server first, not just a client with the same SONAME.
    closure("akonadi-server", packages)
    matches, errors = [], []
    manifests = sorted(directory.glob("*/manifest.json"))
    if len(manifests) != 3:
        raise ValueError("KDE backend manifests are missing")
    for path in manifests:
        manifest = json.loads(path.read_text())
        if manifest.get("schema") != "magnolie-kde-backend-v1" or manifest.get("target") != path.parent.name:
            raise ValueError("Invalid KDE backend manifest")
        try:
            closure(manifest["abi"] + ", " + manifest["requirements"], packages)
        except ValueError as error:
            errors.append(str(error))
            continue
        binary = path.parent / "backend"
        if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("KDE backend checksum mismatch")
        matches.append((binary, manifest))
    if len(matches) != 1:
        raise ValueError("KDE has no unique supported, complete installed ABI: " + "; ".join(errors))
    return matches[0]


def main():
    try:
        # Ignore loader/plugin injection for selection, self-check and execution.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LD_", "QT_", "PYTHON"))}
        env.update(PATH="/usr/bin:/bin", LC_ALL="C.UTF-8", LD_BIND_NOW="1")
        database = subprocess.check_output(QUERY, text=True, env=env, timeout=10)
        binary, manifest = select_backend(Path(__file__).resolve().parent / "kde", package_db(database))
        # Resolves every native relocation without creating an Akonadi session.
        probe = subprocess.run([str(binary), "--self-check"], capture_output=True, text=True, env=env, timeout=10)
        if probe.returncode or json.loads(probe.stdout) != {"ok": True, "selfCheck": True}:
            raise ValueError("KDE native libraries cannot be loaded: " + probe.stderr.strip()[:1000])
        if sys.argv[1:] == ["--check"]:
            print(json.dumps({"ok": True, "target": manifest["target"], "activated": False}))
            return 0
        if sys.argv[1:]:
            raise ValueError("Unsupported KDE launcher argument")
        os.execve(binary, [str(binary)], env)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
