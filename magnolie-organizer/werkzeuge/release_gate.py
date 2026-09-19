#!/usr/bin/env python3
"""Private candidate records, read-only approval verification, explicit promotion.

Evidence and personal or delegated authorization are supplied by the release
operator, never inferred or generated here. Local records are attestations,
not remote authentication.
"""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from release_sources import SECRET, digest, file_stamp, inventory, inventory_digest, source_identity

PUBLIC_KEY = "8eJWsygSF9wsF22cuf+sChUUV5RtXEZt38Ngcugn/1Y="
BOOTSTRAP_VERSION = "2.0.19"
BOOTSTRAP_SHA256 = "d48a571ddfae9f64311b565ec61e7922218e06cbbefae60c7b796cb705f6bd84"
LINUX = "magnolie-organizer"
WINDOWS = "magnolie-organizer-windows"
ACCEPTANCE = "I explicitly approve publication of this exact candidate after testing it on Linux and Windows."
CHECKS = {
    "linux": {"installation", "upgrade", "ui", "protectedImages", "firstRun", "scaling", "updater",
              "kdeUbuntu2404Mint22", "kdeDebian13", "kdeUbuntu2604"},
    "windows": {"installation", "upgrade", "uninstall", "ui", "protectedImages", "firstRun", "scaling", "updater"},
    "android": {"installation", "upgrade", "interoperability"},
}
KDE_CHECKS = {"kdeUbuntu2404Mint22": "ubuntu24.04", "kdeDebian13": "debian13", "kdeUbuntu2604": "ubuntu26.04"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    path = Path(path).absolute()
    require(path.is_file() and not any(part.is_symlink() for part in (path, *path.parents)),
            "Missing, non-regular or symlinked release input")
    return path


def input_bytes(path, limit=4 * 1024 * 1024):
    path = regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "Non-regular release record")
        require(before.st_size <= limit, "Release record too large")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    require(len(data) <= limit and file_stamp(before) == file_stamp(after) == file_stamp(regular(path).stat()),
            "Release input changed while reading")
    return data


def json_read(path, expected=None, with_digest=False):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "Duplicate JSON field")
            value[key] = item
        return value
    data = input_bytes(path)
    identity = hashlib.sha256(data).hexdigest()
    require(expected is None or identity == expected, "Evidence bytes changed while reading JSON")
    value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
    return (value, identity) if with_digest else value


def signed_manifest(data):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from update_signieren import manifest_felder, signatur_nachricht
    xml = ET.fromstring(data)
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY, validate=True)).verify(
            base64.b64decode(xml.findtext("signature"), validate=True), signatur_nachricht(*manifest_felder(xml)))
    except (InvalidSignature, TypeError, ValueError) as error:
        raise ValueError("Manifest public signature is invalid") from error
    return xml


def bootstrap_check(root):
    data = input_bytes(root / "update.xml")
    require(data == input_bytes(root / LINUX / "update.xml") and
            hashlib.sha256(data).hexdigest() == BOOTSTRAP_SHA256,
            "Published bootstrap manifest changed before approval")
    xml = signed_manifest(data)
    require(xml.findtext("version") == BOOTSTRAP_VERSION, "Unexpected bootstrap version")
    return data


def write_record(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def release_versions(root):
    changelog = (root / LINUX / "debian/changelog").read_text(encoding="utf-8")
    version = re.search(r"^magnolie-organizer \((\d+\.\d+\.\d+)\)", changelog).group(1)
    require(ET.parse(root / WINDOWS / "Directory.Build.props").findtext("./PropertyGroup/Version") == version,
            "Desktop versions disagree")
    handbook = (root / "magnolie-handbuch/debian/changelog").read_text(encoding="utf-8")
    require(handbook.startswith(f"magnolie-handbuch ({version})"), "Handbook version disagrees")
    notes = list(root.glob("magnolie-notes*/app/build.gradle.kts"))
    require(len(notes) == 1, "Exactly one current Notes source is required")
    notes_version = re.search(r'versionName\s*=\s*"(\d+\.\d+\.\d+)"', notes[0].read_text()).group(1)
    return version, notes_version


def artifact_groups(version, notes, arch):
    require(re.fullmatch(r"\d+\.\d+\.\d+", version) and re.fullmatch(r"\d+\.\d+\.\d+", notes), "Invalid version")
    require(arch == "amd64", "The complete AppImage/Flatpak/Fedora release is x86_64 only")
    linux = [f"magnolie-{product}_{version}{suffix}" for product in ("organizer", "handbuch")
             for suffix in ("_all.deb", ".dsc", ".tar.xz")]
    linux += [f"Magnolie-Organizer-{version}-x86_64.{kind}" for kind in ("AppImage", "flatpak")]
    from kde_profiles import artifacts
    linux += artifacts(version, arch)
    linux += [f"magnolie-{product}-{version}-1.fc42.{kind}.rpm"
              for product, binary in (("organizer", "noarch"), ("handbuch", "noarch"), ("organizer-kde", "x86_64"))
              for kind in (binary, "src")]
    windows = [f"Magnolie-Organizer-Windows-{version}-{suffix}" for suffix in
               ("Source.zip", "x64.zip", "Setup-x64.exe", "Setup-x64.exe.build.json", "provenance.json", "PRUEFSUMMEN.sha256")]
    android = [f"Magnolie-Notes-{notes}.apk", f"magnolie-notes_{notes}.tar.xz", "Magnolie-Notes-PRUEFSUMMEN.sha256",
               f"Magnolie-Notes-{notes}-provenance.json"]
    return {"linux": linux, "windows": windows, "notes": android, "metadata": []}


def kde_binding(directory, version, source_record, artifact_record):
    from kde_profiles import PROFILES, artifacts
    prefix = LINUX + "/native/akonadi-helper/"
    expected_source = {name[len(prefix):]: value for name, value in source_record.items() if name.startswith(prefix)}
    require(bool(expected_source), "Missing KDE source provenance")
    proof = json_read(directory / f"kde-{version}-provenance.json")
    require(proof.get("schema") == "magnolie-kde-build-v2" and proof.get("version") == version, "KDE build binding changed")
    require(proof.get("sourceIdentity") == expected_source, "KDE source binding changed")
    expected = {name: artifact_record[name]["sha256"] for name in artifacts(version) if not name.endswith(".json")}
    require(proof.get("artifacts") == expected, "KDE artifact binding changed")
    require(proof.get("reproducible") is True and isinstance(proof.get("profiles"), dict) and
            set(proof["profiles"]) == set(PROFILES), "KDE profiles incomplete")
    binary = expected[f"magnolie-organizer-kde_{version}_amd64.deb"]
    for target, profile in PROFILES.items():
        backend = proof["profiles"][target]
        require(isinstance(backend, dict), "KDE backend audit malformed")
        require(backend.get("sameArtifactCheck") == binary, "KDE checks must bind the same single DEB")
        require(all(backend.get(check) is True for check in ("serialization", "protocolSmoke", "selfCheck")),
                "KDE component build checks incomplete")
        manifest = backend.get("manifest", {})
        require(isinstance(manifest, dict) and manifest.get("target") == target and manifest.get("abi") == profile["abi"] and
                isinstance(backend.get("shlibdeps"), str) and profile["abi"] in backend["shlibdeps"] and
                backend.get("closure") and backend.get("libraries"),
                "KDE genuine native dependency audit missing")


def artifact_map(directory, names):
    result = {}
    for name in sorted(names):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) and name not in {".", ".."}, "Unsafe artifact name")
        path = regular(directory / name)
        require(path.stat().st_size > 0, "Empty artifact")
        result[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return result


def notes_inputs(root, directory):
    version, notes = release_versions(root)
    names = artifact_groups(version, notes, "amd64")["notes"]
    for name in names:
        require((directory / name).is_file(), "Notes candidate input missing: " + name)
        regular(directory / name)
        require((directory / name).stat().st_size > 0, "Notes candidate input is empty: " + name)
    before = artifact_map(directory, names)
    listed = set()
    for line in (directory / names[2]).read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        require(match is not None, "Notes input checksum list is not in flat layout")
        expected, name = match.groups()
        require(name in names[:2] + names[3:] and name not in listed, "Notes input checksum refers to a stale or duplicate artifact")
        require(digest(directory / name) == expected, "Notes input checksum mismatch")
        listed.add(name)
    require(listed == set(names[:2] + names[3:]), "Notes input checksum must cover APK, source and build record")
    from notes_candidate import binding
    binding(root, directory, notes)
    require(artifact_map(directory, names) == before, "Notes inputs changed during provenance verification")
    return names


def windows_binding(directory, version, artifacts):
    prefix = f"Magnolie-Organizer-Windows-{version}-"
    record = json_read(directory / (prefix + "provenance.json"))
    require(set(record) == {"schema", "version", "artifacts"} and
            record["schema"] == "magnolie-windows-candidate-v1" and record["version"] == version,
            "Invalid Windows build provenance")
    expected = {prefix + suffix: artifacts[prefix + suffix]["sha256"] for suffix in
                ("Source.zip", "x64.zip", "Setup-x64.exe", "Setup-x64.exe.build.json")}
    require(record["artifacts"] == expected, "Windows source/binary binding changed")
    build = json_read(directory / (prefix + "Setup-x64.exe.build.json"))
    installer = prefix + "Setup-x64.exe"
    require(build == dict(schema="magnolie-installer-build-v1", artifact=installer, **artifacts[installer]),
            "Installer build record does not match candidate")


def assert_windows_source(root, directory):
    pwsh = os.environ.get("MAGNOLIE_PWSH", "/tmp/opencode/powershell-7.4.13/pwsh")
    subprocess.run([pwsh, "-NoProfile", "-File", str(root / WINDOWS / "build/AssertCandidate.ps1"),
                    "-Root", str(root / WINDOWS), "-Directory", str(directory)],
                   check=True, stdout=subprocess.DEVNULL)


def candidate_check(root, directory):
    record_path = regular(directory / "candidate.json")
    record, identity = json_read(record_path, with_digest=True)
    require(set(record) == {"schema", "version", "notesVersion", "architecture", "sources", "sourceSha256", "artifacts", "gates"}
            and record["schema"] == "magnolie-desktop-candidate-v2", "Invalid candidate schema")
    bootstrap_check(root)
    require((record["version"], record["notesVersion"]) == release_versions(root), "Candidate version is stale")
    require(all(set(value) == {"sha256", "mode"} and type(value["mode"]) is int
                for value in record["sources"].values()), "Invalid v2 source mode inventory")
    require(record["sources"] == inventory(root) and record["sourceSha256"] == inventory_digest(record["sources"]),
            "Canonical sources changed; rebuild and repeat approval")
    groups = artifact_groups(record["version"], record["notesVersion"], record["architecture"])
    names = sum(groups.values(), [])
    require(set(record["artifacts"]) == set(names), "Incomplete or unexpected candidate artifact inventory")
    require(record["artifacts"] == artifact_map(directory, names), "Candidate artifact changed")
    require(set(record["gates"]) == {"fedora", "autopkgtest"} and record["gates"]["fedora"] == "passed" and
            record["gates"]["autopkgtest"] in {"passed", "unavailable"}, "Incomplete system package gates")
    windows_binding(directory, record["version"], record["artifacts"])
    kde_binding(directory, record["version"], record["sources"], record["artifacts"])
    notes_inputs(root, directory)
    assert_windows_source(root, directory)
    require(record["artifacts"] == artifact_map(directory, names) and digest(regular(record_path)) == identity,
            "Candidate changed during Windows proof")
    require(record["sources"] == inventory(root), "Canonical sources changed during Windows proof")
    return record, identity, groups


def evidence_file(base, reference, bindings=None):
    require(isinstance(reference, dict) and set(reference) == {"file", "sha256"}, "Invalid evidence reference")
    name = reference["file"]
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_./-]+", name) and
            not Path(name).is_absolute() and not any(part in {".", ".."} for part in name.split("/")) and
            not SECRET.search(Path(name).name), "Unsafe evidence path")
    path = regular(base / name)
    require(path.stat().st_size > 0 and digest(path) == reference["sha256"], "Evidence bytes changed or missing")
    if bindings is not None:
        require(path not in bindings or bindings[path] == reference["sha256"], "Conflicting evidence references")
        bindings[path] = reference["sha256"]
    return path


def check_bindings(bindings):
    for path, expected in bindings.items():
        require(digest(regular(path)) == expected, "Approval/evidence changed during verification")


def approval_check(directory, approval_path, record, identity, groups, bindings):
    """Check authorization/native records; verify also enforces candidate provenance."""
    approval_path = regular(approval_path)
    approval, approval_identity = json_read(approval_path, with_digest=True)
    bindings[approval_path] = approval_identity
    require(isinstance(approval, dict) and approval.get("schema") in
            {"magnolie-desktop-approval-v1", "magnolie-desktop-approval-v2"}, "Invalid approval schema")
    personal = approval["schema"] == "magnolie-desktop-approval-v1"
    require(set(approval) == {"schema", "candidateSha256", "nativeEvidence", "qemuException",
                             "userAcceptance" if personal else "authorization"} and
            approval["candidateSha256"] == identity,
            "Approval does not identify this candidate")
    require(set(approval["nativeEvidence"]) == set(CHECKS), "Linux, Windows and Android native evidence is required")
    for platform, checks in CHECKS.items():
        reference = approval["nativeEvidence"][platform]
        path = evidence_file(approval_path.parent, reference, bindings)
        evidence = json_read(path, expected=reference["sha256"])
        require(set(evidence) == {"schema", "platform", "candidateSha256", "sourceSha256", "artifacts", "checks"} and
                evidence["schema"] == "magnolie-native-evidence-v1" and evidence["platform"] == platform and
                evidence["candidateSha256"] == identity and evidence["sourceSha256"] == record["sourceSha256"],
                "Native evidence belongs to a different candidate/source")
        binaries = {name: record["artifacts"][name]["sha256"] for name in groups["notes" if platform == "android" else platform]
                    if name.endswith((".deb", ".AppImage", ".flatpak", ".rpm", ".apk", "-Setup-x64.exe", "-x64.zip"))
                    and not name.endswith(".src.rpm")}
        require(evidence["artifacts"] == binaries and set(evidence["checks"]) == checks,
                "Native artifact/test coverage is incomplete")
        for check, outcome in evidence["checks"].items():
            fields = {"exitCode", "log"} | ({"artifact", "sha256", "profile"} if check in KDE_CHECKS else set())
            require(isinstance(outcome, dict) and set(outcome) == fields and
                    type(outcome["exitCode"]) is int and outcome["exitCode"] == 0, "Native check did not pass")
            if check in KDE_CHECKS:
                kde_deb = f"magnolie-organizer-kde_{record['version']}_amd64.deb"
                require(outcome["artifact"] == kde_deb and outcome["sha256"] == binaries[kde_deb] and
                        outcome["profile"] == KDE_CHECKS[check], "KDE native gate must bind the same single DEB and its profile")
            evidence_file(path.parent, outcome["log"], bindings)
    if personal:
        acceptance = approval["userAcceptance"]
        require(isinstance(acceptance, dict) and set(acceptance) == {"accepted", "candidateSha256", "statement", "evidence"} and
                acceptance["accepted"] is True and acceptance["candidateSha256"] == identity and
                acceptance["statement"] == ACCEPTANCE, "Explicit personal user acceptance is missing")
        decision = evidence_file(approval_path.parent, acceptance["evidence"], bindings)
        decision_data = input_bytes(decision, 1024 * 1024)
        require(hashlib.sha256(decision_data).hexdigest() == acceptance["evidence"]["sha256"],
                "User decision changed while reading")
        decision_text = decision_data.decode("utf-8-sig")
        require(identity in decision_text and ACCEPTANCE in decision_text,
                "User decision evidence does not explicitly approve this exact candidate")
    else:
        authorization = approval["authorization"]
        require(isinstance(authorization, dict) and set(authorization) == {"kind", "instructions", "operatorRecord"} and
                authorization["kind"] == "delegated-conditional", "Explicit delegated authorization is missing")
        instructions_path = evidence_file(approval_path.parent, authorization["instructions"], bindings)
        instructions = json_read(instructions_path, expected=authorization["instructions"]["sha256"])
        require(isinstance(instructions, dict) and
                set(instructions) == {"schema", "delegated", "version", "notesVersion", "quote"} and
                instructions["schema"] == "magnolie-delegated-instructions-v1" and instructions["delegated"] is True and
                (instructions["version"], instructions["notesVersion"]) == (record["version"], record["notesVersion"]),
                "Delegated instruction record is missing or outside this release scope")
        operator_path = evidence_file(approval_path.parent, authorization["operatorRecord"], bindings)
        operator = json_read(operator_path, expected=authorization["operatorRecord"]["sha256"])
        require(isinstance(operator, dict) and operator.get("afterTests") is True and operator == dict(
            schema="magnolie-delegated-operator-v1", statement="Operator verified delegated conditions",
            afterTests=True, finalResult="passed", candidateSha256=identity, sourceSha256=record["sourceSha256"],
            artifacts=record["artifacts"], instructions=authorization["instructions"],
            nativeEvidence=approval["nativeEvidence"], qemuException=approval["qemuException"]),
            "Post-test operator record does not bind these delegated conditions and final results")
        quote = evidence_file(instructions_path.parent, instructions["quote"])
        require(quote not in bindings, "Original user quote must be a separate file")
        bindings[quote] = instructions["quote"]["sha256"]
        quote_data = input_bytes(quote, 1024 * 1024)
        require(hashlib.sha256(quote_data).hexdigest() == instructions["quote"]["sha256"],
                "User instruction changed while reading")
        # Meaning/authorship are attested at the trusted operator boundary, not guessed from keywords.
        require(bool(quote_data.decode("utf-8-sig").strip()), "Original user instruction quote is missing")
    if record["gates"]["autopkgtest"] != "passed":
        reason = approval["qemuException"]
        require(isinstance(reason, str) and len(reason.strip()) >= 20,
                "QEMU unavailability needs an explicit reason in the private approval record")
    else:
        require(approval["qemuException"] is None, "Unexpected QEMU exception")


def verify(root, directory, approval_path, accepted_id, *, bindings=None):
    bindings = {} if bindings is None else bindings
    record, identity, groups = candidate_check(root, directory)
    require(accepted_id == identity, "Explicit --accept-candidate must identify this exact candidate")
    bindings[regular(directory / "candidate.json")] = identity
    approval_check(directory, approval_path, record, identity, groups, bindings)
    require(record["artifacts"] == artifact_map(directory, record["artifacts"]), "Candidate changed during approval verification")
    require(record["sources"] == inventory(root), "Canonical sources changed during approval verification")
    check_bindings(bindings)
    return record, identity, groups


def checksums(directory, name, names, expected=None):
    require(name not in names and len(set(names)) == len(names), "Invalid checksum inventory")
    values = artifact_map(directory, names)
    require(expected is None or values == {file: expected[file] for file in names}, "Checksum inputs changed")
    contents = "".join(f"{data['sha256']}  {file}\n" for file, data in values.items()).encode("ascii")
    (directory / name).write_bytes(contents)
    for file, data in values.items():
        require(digest(directory / file) == data["sha256"], "Checksum self-check failed")
    return {"sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents)}


@contextmanager
def release_lock(root):
    path = root / ".magnolie-desktop-release.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    handlers = {}
    def interrupted(_number, _frame):
        raise InterruptedError("Release promotion interrupted")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[number] = signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
        os.close(fd)


@contextmanager
def blocked_signals():
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def publish_files(root, stage, ordered, precondition, postcondition):
    """Publish staged bytes; ordinary-file tests exercise this exact transaction."""
    moved, backups = [], []
    keep_stage = False
    try:
        with blocked_signals():
            precondition()
            for name in ordered:
                target, source = root / name, regular(stage / name)
                require(not target.is_symlink(), "Publication target is a symlink")
                saved = stage / ".rollback" / name
                if target.exists():
                    regular(target)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    # Register intent first, also covering exceptions delivered after a syscall.
                    backups.append((target, saved))
                    os.replace(target, saved)
                moved.append(target)
                os.replace(source, target)
            postcondition()
            os.sync()
    except BaseException:
        keep_stage = True
        try:
            with blocked_signals():
                for target in reversed(moved):
                    if target.exists() or target.is_symlink():
                        target.unlink()
                for target, saved in reversed(backups):
                    require(saved.is_file() and not saved.is_symlink(), "Unknown backup rename state")
                    os.replace(saved, target)
        except BaseException as error:
            raise RuntimeError(f"Rollback incomplete; preserve recovery directory {stage}") from error
        keep_stage = False
        raise
    finally:
        if not keep_stage:
            shutil.rmtree(stage)


def promote(root, directory, approval, accepted_id):
    with release_lock(root):
        bindings = {}
        record, identity, groups = verify(root, directory, approval, accepted_id, bindings=bindings)
        tool = root / LINUX / "werkzeuge/update_signieren.py"
        key = os.environ.get("MAGNOLIE_UPDATE_SIGNING_KEY", str(Path.home() / ".local/share/magnolie-release/update-ed25519.pem"))
        subprocess.run([sys.executable, str(tool), "--check-key", key, PUBLIC_KEY], check=True)
        stage = Path(tempfile.mkdtemp(prefix=".magnolie-desktop-promote-", dir=root))
        keep_stage = False
        try:
            for name in record["artifacts"]:
                shutil.copyfile(regular(directory / name), stage / name)
            require(artifact_map(stage, record["artifacts"]) == record["artifacts"], "Candidate changed during staging")
            (stage / "update.xml").write_bytes(bootstrap_check(root))
            from release_manifest import manifest_schreiben
            v = record["version"]
            deb = stage / f"magnolie-organizer_{v}_all.deb"
            image = stage / f"Magnolie-Organizer-{v}-x86_64.AppImage"
            manifest_schreiben(str(stage / "update.xml"), str(deb), str(image),
                              str(stage / f"magnolie-handbuch_{v}_all.deb"),
                              str(stage / f"Magnolie-Organizer-Windows-{v}-Setup-x64.exe"))
            subprocess.run([sys.executable, str(tool), key, str(stage / "update.xml"), str(deb), str(image)],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable, str(tool), "--verify", PUBLIC_KEY, str(stage / "update.xml"), str(deb), str(image)], check=True)
            manifest_data = input_bytes(stage / "update.xml")
            xml = signed_manifest(manifest_data)
            base = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/"
            for section, artifact, url_field in ((xml, deb.name, "deb"),
                    (xml.find("appimage"), image.name, "url"),
                    (xml.find("manual/linux"), f"magnolie-handbuch_{v}_all.deb", "deb"),
                    (xml.find("manual/windows"), f"Magnolie-Organizer-Windows-{v}-Setup-x64.exe", "url"),
                    (xml.find("windows"), f"Magnolie-Organizer-Windows-{v}-Setup-x64.exe", "url")):
                require(section is not None and section.findtext(url_field) == base + artifact and
                        section.findtext("sha256") == record["artifacts"][artifact]["sha256"],
                        "Signed manifest differs from approved artifacts")
            require(all(xml.findtext(path) == v for path in ("version", "manual/version", "windows/version")),
                    "Signed manifest version differs from approved candidate")
            windows_sum = f"Magnolie-Organizer-Windows-{v}-PRUEFSUMMEN.sha256"
            checksums(stage, windows_sum, [name for name in groups["windows"] if name != windows_sum], record["artifacts"])
            require(digest(stage / windows_sum) == record["artifacts"][windows_sum]["sha256"],
                    "Approved Windows checksums are not in final flat layout")
            published = dict(record["artifacts"])
            # Additional bytes, never a symlink or a candidate-time latest pointer.
            published.update(stage_notes_alias(root, stage, record))
            published["Magnolie-Organizer-PRUEFSUMMEN.sha256"] = checksums(
                stage, "Magnolie-Organizer-PRUEFSUMMEN.sha256", groups["linux"], record["artifacts"])
            published["update.xml"] = {"sha256": hashlib.sha256(manifest_data).hexdigest(), "bytes": len(manifest_data)}
            published["PRUEFSUMMEN.sha256"] = checksums(stage, "PRUEFSUMMEN.sha256", list(published), published)
            names = list(published)
            # Recheck evidence, source and artifact bindings immediately before mutation.
            final_bindings = {}
            verify(root, directory, approval, identity, bindings=final_bindings)
            require(final_bindings == bindings, "Approval/evidence changed during staging")
            (stage / LINUX).mkdir()
            shutil.copyfile(stage / "update.xml", stage / LINUX / "update.xml")
            ordered = sorted(name for name in names if name not in {"update.xml", "PRUEFSUMMEN.sha256"})
            ordered += [f"{LINUX}/update.xml", "update.xml", "PRUEFSUMMEN.sha256"]
            for name in ordered:
                os.chmod(stage / name, 0o755 if name.endswith(".AppImage") else 0o644)
            require(artifact_map(stage, record["artifacts"]) == record["artifacts"], "Approved staged artifact changed")
            after_sources = dict(record["sources"])
            for name in ("update.xml", f"{LINUX}/update.xml"):
                after_sources[name] = source_identity(stage / name)

            def precondition():
                require(artifact_map(directory, record["artifacts"]) == record["artifacts"], "Candidate changed before publication")
                require(artifact_map(stage, names) == published, "Staged publication bytes changed")
                require(inventory(root) == record["sources"], "Canonical sources changed before publication")
                check_bindings(bindings)

            def postcondition():
                require(artifact_map(directory, record["artifacts"]) == record["artifacts"], "Candidate changed during publication")
                require(artifact_map(root, names) == published, "Published bytes differ from verified stage")
                require(input_bytes(root / LINUX / "update.xml") == input_bytes(root / "update.xml"),
                        "Published bootstrap copies differ")
                require(inventory(root) == after_sources, "Canonical sources changed during publication")
                check_bindings(bindings)

            # The transaction owns cleanup from here, preserving ambiguous recovery states.
            keep_stage = True
            publish_files(root, stage, ordered, precondition, postcondition)
        finally:
            if not keep_stage:
                shutil.rmtree(stage)


def stage_notes_alias(root, stage, record):
    notes = json_read(root / "magnolie-handbuch/web/mobile-downloads.json")["notes"]
    alias = notes["filename"]
    require(alias == "Magnolie-Notes.apk" and notes["url"].endswith("/" + alias), "Invalid stable Notes alias")
    versioned = f"Magnolie-Notes-{record['notesVersion']}.apk"
    expected = record["artifacts"][versioned]
    require(artifact_map(stage, [versioned])[versioned] == expected, "Approved Notes bytes changed")
    shutil.copyfile(regular(stage / versioned), stage / alias)
    require(artifact_map(stage, [alias])[alias] == expected, "Notes alias differs from approved APK")
    result = {alias: expected}
    result["Magnolie-Notes-latest-PRUEFSUMMEN.sha256"] = checksums(
        stage, "Magnolie-Notes-latest-PRUEFSUMMEN.sha256", [alias], result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("seal", "inspect", "verify", "promote", "notes-inputs", "bootstrap"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--source-record", type=Path)
    parser.add_argument("--autopkgtest", choices=("passed", "unavailable"))
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--accept-candidate")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.operation == "bootstrap":
        bootstrap_check(root)
        print("Published bootstrap identity and public signature verified; no mutation performed.")
        return
    require(args.candidate is not None, "Candidate directory required")
    directory = args.candidate.resolve()
    if args.operation == "notes-inputs":
        notes_inputs(root, directory)
        print("Notes build binding, archive projection, APK signing/metadata and checksums verified; native/user acceptance remains separate.")
    elif args.operation == "seal":
        bootstrap_check(root)
        require(args.source_record is not None and args.autopkgtest is not None, "Build source record and gate result required")
        sources = json_read(args.source_record)
        require(sources == inventory(root), "Sources changed during build")
        version, notes = release_versions(root)
        groups = artifact_groups(version, notes, "amd64")
        artifacts = artifact_map(directory, sum(groups.values(), []))
        windows_binding(directory, version, artifacts)
        kde_binding(directory, version, sources, artifacts)
        notes_inputs(root, directory)
        assert_windows_source(root, directory)
        require(sources == inventory(root) and artifacts == artifact_map(directory, sum(groups.values(), [])),
                "Source or candidate changed during final build proof")
        write_record(directory / "candidate.json", dict(schema="magnolie-desktop-candidate-v2", version=version,
            notesVersion=notes, architecture="amd64", sources=sources, sourceSha256=inventory_digest(sources),
            artifacts=artifacts, gates={"fedora": "passed", "autopkgtest": args.autopkgtest}))
        print("Private candidate recorded. Native evidence and personal or delegated authorization are still required.")
    elif args.operation == "inspect":
        _, identity, _ = candidate_check(root, directory)
        print(identity)
    else:
        require(args.approval is not None, "Approval record required")
        if args.operation == "verify":
            verify(root, directory, args.approval, args.accept_candidate)
            print("Exact candidate, current source, native evidence and explicit personal or delegated authorization verified. No signing or promotion performed.")
        else:
            promote(root, directory, args.approval, args.accept_candidate)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Release gate rejected: {error}")
