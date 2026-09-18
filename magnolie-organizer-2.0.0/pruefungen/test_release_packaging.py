"""Synthetic packaging/gate fixtures only; never build or approve a product."""

import importlib.util
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tarfile
import zipfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
import release_gate as gate
import release_sources as sources
import notes_candidate as notes_tool


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")


def test_aggregate_kde_recipe_receives_fresh_component_output(tmp_path):
    from kde_profiles import artifacts
    stage = tmp_path / "aggregate"
    source = stage / "magnolie-organizer-2.0.18"
    tools = source / "werkzeuge"
    tools.mkdir(parents=True)
    (stage / "magnolie-handbuch-stamm").mkdir()
    names = artifacts("2.0.18")
    (tools / "kde_deb_bauen.py").write_text(
        "import pathlib, sys\n"
        "output = pathlib.Path(sys.argv[1])\n"
        "output.mkdir(parents=True, exist_ok=True)\n"
        "assert not any(output.iterdir()), 'component output must be fresh'\n"
        f"for name in {names!r}:\n"
        "    (output / name).write_text(name)\n")
    builder = (ROOT / "werkzeuge/release_bauen.sh").read_text()
    commands = builder.split('rm -rf "$PAKET_TEST"\n', 1)[1].split(
        'cd "$STAGE/magnolie-handbuch-stamm"', 1)[0]
    result = subprocess.run(["sh", "-eu", "-c", commands],
        env=dict(os.environ, STAGE=str(stage), WURZEL=str(source)), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all((stage / name).read_text() == name for name in names)
    assert source.is_dir() and (stage / "magnolie-handbuch-stamm").is_dir()


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root, directory, evidence = tmp_path / "canonical", tmp_path / "candidate", tmp_path / "evidence"
    directory.mkdir()
    evidence.mkdir()
    version, notes = "9.8.7", "1.0.14"
    write(root / gate.LINUX / "debian/changelog", f"magnolie-organizer ({version}) unstable; urgency=medium\n")
    write(root / gate.WINDOWS / "Directory.Build.props", f"<Project><PropertyGroup><Version>{version}</Version></PropertyGroup></Project>")
    write(root / "magnolie-handbuch-stamm/debian/changelog", f"magnolie-handbuch ({version}) unstable; urgency=medium\n")
    write(root / "magnolie-handbuch-stamm/web/mobile-downloads.json", {"notes": {
        "filename": "Magnolie-Notes.apk",
        "url": "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes.apk"}})
    write(root / "magnolie-notes-stamm/app/build.gradle.kts", f'versionName = "{notes}"\nversionCode = 14')
    write(root / "contracts/new-contract.json", {"synthetic": True})
    write(root / ".github/workflows/test.yml", "synthetic workflow")
    write(root / "tools/synthetic.py", "# synthetic tool")
    write(root / gate.LINUX / "native/akonadi-helper/main.cpp", "// SYNTHETIC TEST ONLY")
    for name in ("README.md", "README.DE.md", "CHANGELOG.md"):
        write(root / name, "SYNTHETIC TEST DATA, NOT RELEASE APPROVAL")
    manifest = (ROOT / "update.xml").read_text(encoding="utf-8")
    write(root / "update.xml", manifest)
    write(root / gate.LINUX / "update.xml", manifest)
    groups = gate.artifact_groups(version, notes, "amd64")
    for name in sum(groups.values(), []):
        write(directory / name, "SYNTHETIC ARTIFACT: " + name)
    # Only SDK process responses are synthetic; archive, build binding and final
    # gate validation run unchanged. No production key or SDK is accessed.
    monkeypatch.setenv('MAGNOLIE_RELEASE_CERT_SHA256', 'a' * 64)
    monkeypatch.setattr(notes_tool, 'android_sdk', lambda _: tmp_path / 'synthetic-sdk')
    monkeypatch.setattr(notes_tool, 'executable', lambda *_: 'synthetic-sdk-tool')
    def sdk_output(command, **_kwargs):
        if command[1:3] == ['dump', 'badging']:
            return f"package: name='io.gitlab.maik3531.magnolienotes' versionCode='14' versionName='{notes}'\n"
        if command[1:3] == ['dump', 'xmltree']:
            return 'E: manifest\n'
        assert command[1:] == ['verify', '--print-certs', str(directory / groups['notes'][0])]
        return 'Signer #1 certificate SHA-256 digest: ' + 'a' * 64 + '\n'
    monkeypatch.setattr(notes_tool.subprocess, 'check_output', sdk_output)
    with zipfile.ZipFile(directory / groups['notes'][0], 'w') as archive:
        archive.writestr('classes.dex', b'dex\n035\0' + bytes(104))
    _, files, projection = notes_tool.projection(root)
    with tarfile.open(directory / groups['notes'][1], 'w:xz') as archive:
        for name, path in sorted(files.items()):
            data = path.read_bytes()
            entry = tarfile.TarInfo(f'magnolie-notes-{notes}/{name}')
            entry.mode, entry.size = projection[name]['mode'], len(data)
            archive.addfile(entry, io.BytesIO(data))
    write(directory / groups['notes'][3], dict(schema='magnolie-notes-build-v1', version=notes, versionCode=14,
        sources=projection, sourceSha256=sources.inventory_digest(projection),
        apkSha256=sources.digest(directory / groups['notes'][0]), certificateSha256='a' * 64,
        command=notes_tool.BUILD_ARGS, cleanExitCode=0, buildExitCode=0,
        tools={name: 'b' * 64 for name in ('gradle', 'aapt', 'apksigner')}, toolchain='SYNTHETIC Gradle/JVM',
        reports={'TEST-Synthetic.xml': '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="synthetic"/></testsuite>'}))
    gate.checksums(directory, "Magnolie-Notes-PRUEFSUMMEN.sha256", groups["notes"][:2] + groups['notes'][3:])
    prefix = f"Magnolie-Organizer-Windows-{version}-"
    installer = prefix + "Setup-x64.exe"
    write(directory / (installer + ".build.json"), dict(schema="magnolie-installer-build-v1", artifact=installer,
        sha256=sources.digest(directory / installer), bytes=(directory / installer).stat().st_size))
    write(directory / (prefix + "provenance.json"), dict(schema="magnolie-windows-candidate-v1", version=version,
        artifacts={prefix + suffix: sources.digest(directory / (prefix + suffix)) for suffix in
                   ("Source.zip", "x64.zip", "Setup-x64.exe", "Setup-x64.exe.build.json")}))
    windows_sum = prefix + "PRUEFSUMMEN.sha256"
    gate.checksums(directory, windows_sum, [name for name in groups["windows"] if name != windows_sum])
    source_record = sources.inventory(root)
    from kde_profiles import PROFILES, artifacts
    helper_prefix = gate.LINUX + "/native/akonadi-helper/"
    kde_binary = f"magnolie-organizer-kde_{version}_amd64.deb"
    write(directory / f"kde-{version}-provenance.json", dict(
        schema="magnolie-kde-build-v2", version=version,
        sourceIdentity={n[len(helper_prefix):]: v for n, v in source_record.items() if n.startswith(helper_prefix)},
        artifacts={n: sources.digest(directory / n) for n in artifacts(version) if not n.endswith(".json")},
        reproducible=True, profiles={target: dict(
            sameArtifactCheck=sources.digest(directory / kde_binary), serialization=True, protocolSmoke=True, selfCheck=True,
            manifest={"target": target, "abi": profile["abi"]}, shlibdeps=profile["abi"],
            closure={"SYNTHETIC": True}, libraries={"SYNTHETIC": True}) for target, profile in PROFILES.items()}))
    record = dict(schema="magnolie-desktop-candidate-v2", version=version, notesVersion=notes, architecture="amd64",
                  sources=source_record, sourceSha256=sources.inventory_digest(source_record),
                  artifacts=gate.artifact_map(directory, sum(groups.values(), [])), gates={"fedora": "passed", "autopkgtest": "passed"})
    write(directory / "candidate.json", record)
    identity = sources.digest(directory / "candidate.json")
    write(evidence / "synthetic.log", "SYNTHETIC TEST LOG, NOT NATIVE EVIDENCE")
    reference = {"file": "synthetic.log", "sha256": sources.digest(evidence / "synthetic.log")}
    refs = {}
    for platform, checks in gate.CHECKS.items():
        binary = {name: record["artifacts"][name]["sha256"] for name in groups["notes" if platform == "android" else platform]
                  if name.endswith((".deb", ".AppImage", ".flatpak", ".rpm", ".apk", "-Setup-x64.exe", "-x64.zip")) and not name.endswith(".src.rpm")}
        write(evidence / (platform + ".json"), dict(schema="magnolie-native-evidence-v1", platform=platform,
            candidateSha256=identity, sourceSha256=record["sourceSha256"], artifacts=binary,
            checks={check: dict(exitCode=0, log=reference, **(
                {"artifact": kde_binary, "sha256": record["artifacts"][kde_binary]["sha256"], "profile": gate.KDE_CHECKS[check]}
                if check in gate.KDE_CHECKS else {})) for check in checks}))
        refs[platform] = {"file": platform + ".json", "sha256": sources.digest(evidence / (platform + ".json"))}
    approval = evidence / "synthetic-approval.json"
    write(evidence / "synthetic-user-decision.txt", "SYNTHETIC TEST ONLY\n" + identity + "\n" + gate.ACCEPTANCE)
    decision = {"file": "synthetic-user-decision.txt", "sha256": sources.digest(evidence / "synthetic-user-decision.txt")}
    write(approval, dict(schema="magnolie-desktop-approval-v1", candidateSha256=identity, nativeEvidence=refs,
        userAcceptance={"accepted": True, "candidateSha256": identity, "statement": gate.ACCEPTANCE, "evidence": decision}, qemuException=None))
    # Public package tests do not require PowerShell. The real source/archive
    # verifier is exercised separately by release-packaging.ps1.
    monkeypatch.setattr(gate, "assert_windows_source", lambda *_: None)
    return root, directory, approval, identity


def test_complete_synthetic_approval_and_flat_checksums(candidate):
    root, directory, approval, identity = candidate
    record, actual, groups = gate.verify(root, directory, approval, identity)
    assert actual == identity
    assert len(sum(groups.values(), [])) == 28
    assert "HINWEIS.txt" not in record["artifacts"]
    assert "FREIGABE.md" not in record["artifacts"]
    gate.checksums(directory, "synthetic.sha256", list(record["artifacts"]))
    for line in (directory / "synthetic.sha256").read_text().splitlines():
        checksum, name = line.split("  ")
        assert Path(name).name == name
        assert sources.digest(directory / name) == checksum


@pytest.mark.parametrize('directory', ['Magnolie-Organizer-Android-Tablet-Beta', 'Magnolie-Organizer-macOS-Beta', '2.0.18'])
def test_separate_beta_and_old_artifacts_are_not_canonical_sources(candidate, directory):
    root, _, _, _ = candidate
    before = sources.inventory(root)
    write(root / directory / 'app.cs', '// unrelated sibling source')
    write(root / directory / 'artifacts/candidate.json', {'synthetic': True})
    write(root / directory / '.debug-signing/synthetic.keystore', 'SYNTHETIC NON-KEY')
    assert sources.inventory(root) == before


def test_windows_nested_build_outputs_are_not_source(tmp_path):
    root = tmp_path / "windows"
    write(root / "Directory.Build.props", "<Project/>")
    write(root / "tests/Tests.cs", "// source")
    write(root / "build/Build.ps1", "# source")
    for directory in ("bin", "tests/bin", "tests/probe/Bin"):
        for name in ("CoreTests", "libe_sqlite3.so", "native-i18n.json", "CoreTests.deps.json"):
            write(root / directory / "Debug" / name, "generated output")
    selected = {relative.as_posix() for relative, _path in sources.source_files(root)}
    assert selected == {"Directory.Build.props", "tests/Tests.cs", "build/Build.ps1"}
    linux = tmp_path / "linux"
    write(linux / "bin/magnolie-organizer", "# runtime source")
    assert [relative.as_posix() for relative, _path in sources.source_files(linux)] == ["bin/magnolie-organizer"]


@pytest.mark.parametrize("damage", ["source", "source-mode", "new-source", "artifact", "candidate", "approval", "acceptance", "log", "native", "coverage", "explicit-id", "symlink"])
def test_approval_rejects_changed_or_incomplete_input(candidate, damage):
    root, directory, approval, identity = candidate
    if damage == "source":
        write(root / "contracts/new-contract.json", {"changed": True})
    elif damage == "source-mode":
        (root / "tools/synthetic.py").chmod(0o755)
    elif damage == "new-source":
        write(root / gate.LINUX / "native/akonadi-helper/new.cpp", "// new source")
    elif damage == "artifact":
        write(directory / "magnolie-organizer_9.8.7_all.deb", "changed")
    elif damage == "candidate":
        record = gate.json_read(directory / "candidate.json")
        record["gates"]["fedora"] = "skipped"
        write(directory / "candidate.json", record)
    elif damage in {"approval", "acceptance"}:
        value = gate.json_read(approval)
        if damage == "approval":
            value["candidateSha256"] = "0" * 64
        else:
            value["userAcceptance"]["accepted"] = False
        write(approval, value)
    elif damage == "log":
        write(approval.parent / "synthetic.log", "changed")
    elif damage in {"native", "coverage"}:
        path = approval.parent / "windows.json"
        value = gate.json_read(path)
        if damage == "native":
            value["checks"]["ui"]["exitCode"] = 1
        else:
            del value["checks"]["protectedImages"]
        write(path, value)
        value = gate.json_read(approval)
        value["nativeEvidence"]["windows"]["sha256"] = sources.digest(path)
        write(approval, value)
    elif damage == "explicit-id":
        identity = None
    else:
        path = approval.parent / "synthetic.log"
        target = path.with_suffix(".real")
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(ValueError):
        gate.verify(root, directory, approval, identity)


def test_unapproved_promotion_never_accesses_signer(candidate, monkeypatch):
    root, directory, approval, _ = candidate
    monkeypatch.setattr(gate.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("Signer invoked before approval"))
    before = (root / "update.xml").read_bytes()
    with pytest.raises(ValueError):
        gate.promote(root, directory, approval, None)
    assert (root / "update.xml").read_bytes() == before
    assert not (root / "Magnolie-Notes.apk").exists()


def test_promotion_transaction_with_mock_signer(candidate, monkeypatch):
    root, directory, approval, identity = candidate
    calls = []
    monkeypatch.setattr(gate.subprocess, "run", lambda command, **_kwargs: calls.append(command))
    monkeypatch.setattr(gate.os, "sync", lambda: None)
    monkeypatch.setattr(gate, "signed_manifest", ET.fromstring)
    gate.promote(root, directory, approval, identity)
    assert len(calls) == 3 and "--check-key" in calls[0] and "--verify" in calls[2]
    assert (root / "update.xml").read_bytes() == (root / gate.LINUX / "update.xml").read_bytes()
    for line in (root / "PRUEFSUMMEN.sha256").read_text().splitlines():
        checksum, name = line.split("  ")
        assert sources.digest(root / name) == checksum
    assert not (root / "candidate.json").exists()
    assert (root / "Magnolie-Notes.apk").read_bytes() == (directory / "Magnolie-Notes-1.0.14.apk").read_bytes()
    assert not (root / "Magnolie-Notes.apk").is_symlink()


def test_promotion_rolls_back_partial_file_replacement(candidate, monkeypatch):
    root, directory, approval, identity = candidate
    monkeypatch.setattr(gate.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate.os, "sync", lambda: None)
    monkeypatch.setattr(gate, "signed_manifest", ET.fromstring)
    target = root / "magnolie-organizer_9.8.7_all.deb"
    write(target, "old synthetic package")
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    replace = gate.os.replace
    failed = False
    def fail_once(source, destination):
        nonlocal failed
        if Path(destination) == target and not failed:
            failed = True
            raise OSError("synthetic publication fault")
        return replace(source, destination)
    monkeypatch.setattr(gate.os, "replace", fail_once)
    with pytest.raises(OSError, match="synthetic publication fault"):
        gate.promote(root, directory, approval, identity)
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*")
             if path.is_file() and path.name != ".magnolie-desktop-release.lock"}
    assert failed and after == before


def test_source_selection_private_data_contracts_and_new_native_files(tmp_path):
    root = tmp_path / "source"
    write(root / "native/akonadi-helper/extra.cpp", "// synthetic native source")
    write(root / "tests/fixtures/valid.sql", "-- synthetic schema")
    write(root / ".private-testing/never-publish.txt", "private test data")
    write(root / "an-claude.md", "protected placeholder")
    write(root / "node_modules/ignored.txt", "cache")
    selected = dict(sources.source_files(root))
    assert set(map(str, selected)) == {"native/akonadi-helper/extra.cpp", "tests/fixtures/valid.sql"}
    for name in ("local.token", "local.secret", "local.pem"):
        write(root / name, "SYNTHETIC NON-CREDENTIAL")
        with pytest.raises(ValueError, match="Secret"):
            list(sources.source_files(root))
        (root / name).unlink()
    shared = root.parent / "contracts"
    for name in ("new.json", "thunderbird-addressbook-fixture.json"):
        write(shared / name, {"synthetic": name})
    sources.sync_contracts(root)
    assert (root / "contracts/new.json").read_bytes() == (shared / "new.json").read_bytes()


def test_projection_must_match_recorded_sources_and_all_shared_contracts(tmp_path):
    write(tmp_path / "native/akonadi-helper/extra.cpp", "// frozen native source")
    write(tmp_path / "contracts/new.json", {"shared": True})
    record = {
        "magnolie-organizer-2.0.0/native/akonadi-helper/extra.cpp": sources.source_identity(tmp_path / "native/akonadi-helper/extra.cpp"),
        "magnolie-organizer-2.0.0/contracts/new.json": "stale internal projection",
        "contracts/new.json": sources.source_identity(tmp_path / "contracts/new.json"),
    }
    sources.verify_projection(record, "magnolie-organizer-2.0.0", tmp_path)
    write(tmp_path / "native/akonadi-helper/extra.cpp", "// changed during copy")
    with pytest.raises(ValueError, match="projection differs"):
        sources.verify_projection(record, "magnolie-organizer-2.0.0", tmp_path)


def test_installed_pot_version_without_debian_sources(tmp_path):
    spec = importlib.util.spec_from_file_location("pot_installed_test", ROOT / "werkzeuge/pot_erzeugen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write(tmp_path / "version.json", {"version": "9.8.7"})
    assert module.paket_version(str(tmp_path)) == "9.8.7"
    write(tmp_path / "version.json", {"version": "../invalid"})
    with pytest.raises(ValueError):
        module.paket_version(str(tmp_path))
    prefix = tmp_path / "portable-prefix"
    installed = prefix / "share/magnolie-organizer"
    for name in ("i18n-markers.js", "anwendung.js"):
        write(installed / "web" / name, "// synthetic source")
    for name in ("magnolie-organizer", "magnolie_hintergrund.py", "magnolie_setup_ui.py"):
        write(prefix / "bin" / name, "# synthetic source")
    found = module.quellen_finden(str(installed))
    assert found[2] == str(prefix / "bin/magnolie-organizer")
    assert all(Path(path).is_relative_to(prefix) for path in found)


def test_binary_payload_excludes_new_test_fixtures(tmp_path):
    write(tmp_path / "web/anwendung.js", "// synthetic product")
    sources.audit_binary(tmp_path)
    write(tmp_path / "web/fixtures/next-schema.sql", "-- synthetic test")
    with pytest.raises(ValueError, match="Test/private"):
        sources.audit_binary(tmp_path)


def test_record_parser_and_evidence_paths_reject_ambiguity(tmp_path):
    write(tmp_path / "duplicate.json", '{"schema":"one","schema":"two"}')
    with pytest.raises(ValueError, match="Duplicate"):
        gate.json_read(tmp_path / "duplicate.json")
    for name in ("../outside.log", "/absolute.log", "token.secret", "nested/../outside.log"):
        with pytest.raises(ValueError, match="Unsafe"):
            gate.evidence_file(tmp_path, {"file": name, "sha256": "0" * 64})


def test_arbitrary_log_cannot_replace_personal_user_decision(candidate):
    root, directory, approval, identity = candidate
    data = gate.json_read(approval)
    data["userAcceptance"]["evidence"] = {"file": "synthetic.log", "sha256": sources.digest(approval.parent / "synthetic.log")}
    write(approval, data)
    with pytest.raises(ValueError, match="User decision"):
        gate.verify(root, directory, approval, identity)


def test_notes_reference_input_rejects_old_published_checksum(candidate):
    root, directory, _, _ = candidate
    assert gate.notes_inputs(root, directory)[0] == "Magnolie-Notes-1.0.14.apk"
    write(directory / "Magnolie-Notes-PRUEFSUMMEN.sha256", "0" * 64 + "  Magnolie-Notes-1.0.13.apk\n")
    with pytest.raises(ValueError, match="stale"):
        gate.notes_inputs(root, directory)


def test_candidate_build_does_not_sign_or_promote_and_kde_relation_matches():
    script = (ROOT / "werkzeuge/release_bauen.sh").read_text()
    assert 'release_gate.py" promote' in script
    assert "update_signieren.py" not in script
    assert "VEROEFFENTLICHEN=1" not in script
    assert 'KDE_STAGE="$STAGE/kde-component"' in script
    assert 'kde_deb_bauen.py" "$KDE_STAGE"' in script
    assert "Provides: magnolie-organizer-akonadi (= ${binary:Version})" in (ROOT / "native/akonadi-helper/debian/control").read_text()
    assert "test_thunderbird_contacts.py" in script
    assert 'release_sources.py" contracts' in script


def test_kde_profiles_are_internal_to_one_flat_native_artifact():
    from kde_profiles import PROFILES, artifacts
    names = artifacts("2.0.18")
    assert set(PROFILES) == {"ubuntu24.04", "debian13", "ubuntu26.04"}
    assert len(names) == len(set(names)) == 4
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+", n) for n in names)
    assert set(names) <= set(gate.artifact_groups("2.0.18", "1.0.14", "amd64")["linux"])
    assert "magnolie-organizer-kde_2.0.18_amd64.deb" in gate.artifact_groups("2.0.18", "1.0.14", "amd64")["linux"]
    for target in PROFILES:
        assert not any(target in name for name in names)
    builder = (ROOT / "native/akonadi-helper/build.py").read_text()
    assert 'run("dpkg-checkbuilddeps")' in builder
    assert 'run("dpkg-shlibdeps", "-O"' in builder and "SHLIBS_LOCAL" not in builder
    assert {"kdeUbuntu2404Mint22", "kdeDebian13", "kdeUbuntu2604"} <= gate.CHECKS["linux"]
    control = (ROOT / "native/akonadi-helper/debian/control").read_text()
    assert control.count("\nPackage:") == 1
    assert "Suggests: akonadi-server, kdepim-runtime" in control
    selected = {str(n) for n, _ in sources.source_files(ROOT / "native/akonadi-helper")}
    assert {"build.py", "profiles.py", "launcher.py", "tests/test_launcher.py", "debian/rules"} <= selected


@pytest.mark.parametrize("field", ["sourceIdentity", "artifacts", "reproducible", "profiles"])
def test_kde_provenance_rejects_relabelled_or_unverified_build(candidate, field):
    _, directory, _, _ = candidate
    record = gate.json_read(directory / "candidate.json")
    path = directory / "kde-9.8.7-provenance.json"
    proof = gate.json_read(path)
    proof[field] = "SYNTHETIC INVALID PROOF"
    write(path, proof)
    with pytest.raises(ValueError, match="KDE"):
        gate.kde_binding(directory, "9.8.7", record["sources"], record["artifacts"])


@pytest.mark.parametrize("field", ["sameArtifactCheck", "serialization", "shlibdeps", "closure", "libraries"])
@pytest.mark.parametrize("target", list(gate.KDE_CHECKS.values()))
def test_kde_each_backend_is_bound_to_single_deb(candidate, field, target):
    _, directory, _, _ = candidate
    record = gate.json_read(directory / "candidate.json")
    path = directory / "kde-9.8.7-provenance.json"
    proof = gate.json_read(path)
    proof["profiles"][target][field] = None
    write(path, proof)
    with pytest.raises(ValueError, match="KDE"):
        gate.kde_binding(directory, "9.8.7", record["sources"], record["artifacts"])


@pytest.mark.parametrize("field", ["artifact", "sha256", "profile"])
@pytest.mark.parametrize("check", list(gate.KDE_CHECKS))
def test_kde_native_gate_rejects_other_artifact_or_profile(candidate, field, check):
    root, directory, approval, identity = candidate
    path = approval.parent / "linux.json"
    evidence = gate.json_read(path)
    evidence["checks"][check][field] = "WRONG"
    write(path, evidence)
    value = gate.json_read(approval)
    value["nativeEvidence"]["linux"]["sha256"] = sources.digest(path)
    write(approval, value)
    with pytest.raises(ValueError, match="KDE"):
        gate.verify(root, directory, approval, identity)


@pytest.mark.parametrize("damage", ["source", "candidate", "artifact"])
def test_windows_proof_cannot_hide_concurrent_changes(candidate, monkeypatch, damage):
    root, directory, approval, identity = candidate
    path = {"source": root / "tools/synthetic.py", "candidate": directory / "candidate.json",
            "artifact": directory / "magnolie-organizer_9.8.7_all.deb"}[damage]
    monkeypatch.setattr(gate, "assert_windows_source", lambda *_: write(path, "changed during external proof"))
    with pytest.raises(ValueError, match="changed"):
        gate.verify(root, directory, approval, identity)


def test_json_identity_uses_the_parsed_buffer(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    write(path, {"checked": True})
    original = gate.input_bytes
    def replace_after_read(path, *args):
        data = original(path, *args)
        write(path, {"checked": False})
        return data
    monkeypatch.setattr(gate, "input_bytes", replace_after_read)
    value, identity = gate.json_read(path, with_digest=True)
    assert value == {"checked": True}
    assert identity == hashlib.sha256(json.dumps(value).encode()).hexdigest()
    assert identity != sources.digest(path)


@pytest.mark.parametrize("name", ["linux.json", "synthetic-user-decision.txt", "synthetic.log"])
def test_evidence_replacement_after_hash_is_rejected(candidate, monkeypatch, name):
    root, directory, approval, identity = candidate
    original = gate.evidence_file
    def replace_after_check(base, reference, bindings=None):
        path = original(base, reference, bindings)
        if path.name == name:
            write(path, "changed after evidence hash")
        return path
    monkeypatch.setattr(gate, "evidence_file", replace_after_check)
    with pytest.raises(ValueError, match="[Ee]vidence|decision"):
        gate.verify(root, directory, approval, identity)


@pytest.mark.parametrize("mode", [0o655, 0o754, 0o4755])
def test_source_mode_mask_is_not_a_boolean(tmp_path, mode):
    path = tmp_path / "script.sh"
    write(path, "#!/bin/sh\n")
    path.chmod(0o755)
    before = sources.source_identity(path)
    path.chmod(mode)
    after = sources.source_identity(path)
    assert before["sha256"] == after["sha256"] and before["mode"] != after["mode"]
    with pytest.raises(ValueError, match="projection"):
        sources.verify_projection({"component/script.sh": before}, "component", tmp_path)


def test_bootstrap_rejects_changes_before_source_freeze(candidate):
    root, directory, _, _ = candidate
    gate.bootstrap_check(root)
    for path in (root / "update.xml", root / gate.LINUX / "update.xml"):
        write(path, path.read_text().replace("<name>", "<name>changed "))
    record = gate.json_read(directory / "candidate.json")
    record["sources"] = sources.inventory(root)
    record["sourceSha256"] = sources.inventory_digest(record["sources"])
    write(directory / "candidate.json", record)
    with pytest.raises(ValueError, match="bootstrap"):
        gate.candidate_check(root, directory)


@pytest.fixture
def transaction(tmp_path, monkeypatch):
    root, stage = tmp_path / "live", tmp_path / "stage"
    for name in ("one.txt", "two.txt"):
        write(root / name, "old " + name)
        write(stage / name, "new " + name)
    monkeypatch.setattr(gate.os, "sync", lambda: None)
    return root, stage, ["one.txt", "two.txt"]


@pytest.mark.parametrize("where", ["before", "after-backup", "after-install", "postcondition"])
def test_real_transaction_faults_restore_ordinary_files(transaction, monkeypatch, where):
    root, stage, names = transaction
    replace = os.replace
    fired = False
    def fail(source, target):
        nonlocal fired
        inject = not fired and ((where == "after-backup" and Path(source) == root / names[1]) or
                                (where == "after-install" and Path(target) == root / names[1]))
        replace(source, target)
        if inject:
            fired = True
            raise InterruptedError("synthetic rename interruption")
    monkeypatch.setattr(os, "replace", fail)
    def boundary(which):
        if where == which:
            raise ValueError("synthetic changed precondition")
    with pytest.raises((ValueError, InterruptedError)):
        gate.publish_files(root, stage, names, lambda: boundary("before"), lambda: boundary("postcondition"))
    assert [(root / name).read_text() for name in names] == ["old " + name for name in names]
    assert not stage.exists()


def test_real_signal_is_deferred_until_rename_bookkeeping(transaction, monkeypatch):
    root, stage, names = transaction
    replace = os.replace
    fired = False
    def interrupt(source, target):
        nonlocal fired
        replace(source, target)
        if Path(source) == root / names[0] and not fired:
            fired = True
            os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(os, "replace", interrupt)
    with gate.release_lock(root), pytest.raises(InterruptedError):
        gate.publish_files(root, stage, names, lambda: None, lambda: None)
    assert fired and all((root / name).read_text() == "old " + name for name in names)


def test_unknown_backup_state_preserves_recovery(transaction, monkeypatch):
    root, stage, names = transaction
    replace = os.replace
    def fail(source, target):
        if Path(source) == root / names[1]:
            raise OSError("unknown rename result")
        return replace(source, target)
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(RuntimeError, match="preserve recovery directory"):
        gate.publish_files(root, stage, names, lambda: None, lambda: None)
    assert (stage / ".rollback" / names[0]).read_text() == "old " + names[0]
    assert (root / names[1]).read_text() == "old " + names[1]


@pytest.mark.parametrize("prefix", ["AppDir/usr", "app", "usr", "source"])
def test_pot_uses_only_own_prefix(tmp_path, prefix):
    launcher = ROOT / "bin/magnolie-organizer"
    tree = ast.parse(launcher.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "pot_erzeugen")
    installed = tmp_path / prefix
    helper = installed / ("werkzeuge/pot_erzeugen.py" if prefix == "source" else
                          "share/magnolie-organizer/werkzeuge/pot_erzeugen.py")
    write(helper, "# synthetic helper")
    calls = []
    namespace = dict(os=os, sys=sys, __file__=str(installed / "bin/magnolie-organizer"),
                     subprocess=SimpleNamespace(DEVNULL=-3, PIPE=-1, run=lambda args, **_: calls.append(args)))
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(launcher), "exec"), namespace)
    namespace["pot_erzeugen"](str(tmp_path / "unused.pot"))
    assert calls[0][1] == str(helper)
    helper.unlink()
    with pytest.raises(FileNotFoundError):
        namespace["pot_erzeugen"](str(tmp_path / "unused.pot"))


def test_debian_unpack_preserves_existing_status(tmp_path):
    script = (ROOT / "pruefungen/test_debian_koinstallation.sh").read_text()
    function = script[script.index("entpacke() {"):script.index("\n\npruefe_vorgaenger()")]
    stub = '''
dpkg() {
    wc -c < "$root/var/lib/dpkg/status" >&2
    printf 'Package: synthetic\nStatus: install ok unpacked\n' > "$root/var/lib/dpkg/status"
}
bwrap() {
    case " $* " in *" --cap-add CAP_SYS_CHROOT "*) ;; *) exit 99;; esac
    while [ "$1" != dpkg ]; do shift; done
    shift
    dpkg "$@"
}
'''
    result = subprocess.run(["sh", "-eu", "-c", stub + function + '\nARBEIT="$1"\nentpacke "$1" OLD\nentpacke "$1" NEW',
                             "synthetic", str(tmp_path / "database")], capture_output=True, text=True, check=True)
    first, second = map(int, result.stderr.split())
    assert first == 0 and second > 0


def test_shared_selector_is_shipped_and_identical_when_handbook_present():
    local = ROOT / "werkzeuge/source_selection.py"
    assert local.is_file()
    handbook = ROOT.parent / "magnolie-handbuch-stamm/werkzeuge/source_selection.py"
    if handbook.exists():
        assert local.read_bytes() == handbook.read_bytes()


@pytest.mark.parametrize("damage", ["source", "evidence", "candidate-artifact", "stage-artifact", "stage-manifest"])
def test_promotion_boundaries_reject_drift_without_real_signer(candidate, monkeypatch, damage):
    root, directory, approval, identity = candidate
    old_manifest = (root / "update.xml").read_bytes()
    monkeypatch.setattr(gate.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate, "signed_manifest", ET.fromstring)
    monkeypatch.setattr(gate.os, "sync", lambda: None)
    transaction = gate.publish_files
    def inject(root, stage, ordered, precondition, postcondition):
        def check_after():
            if damage == "source":
                write(root / "tools/synthetic.py", "concurrent source edit")
            elif damage == "evidence":
                write(approval.parent / "synthetic.log", "concurrent evidence edit")
            elif damage == "candidate-artifact":
                write(directory / "magnolie-organizer_9.8.7_all.deb", "concurrent candidate edit")
            postcondition()
        if damage.startswith("stage-"):
            name = "update.xml" if damage == "stage-manifest" else "magnolie-organizer_9.8.7_all.deb"
            write(stage / name, "concurrent stage edit")
        transaction(root, stage, ordered, precondition, check_after)
    monkeypatch.setattr(gate, "publish_files", inject)
    with pytest.raises(ValueError, match="changed|differ"):
        gate.promote(root, directory, approval, identity)
    assert (root / "update.xml").read_bytes() == old_manifest
    assert not (root / "PRUEFSUMMEN.sha256").exists()
    assert not list(root.glob(".magnolie-desktop-promote-*"))


def test_real_public_bootstrap_signature_rejects_tamper():
    data = (ROOT / "update.xml").read_bytes()
    manifest = gate.signed_manifest(data)
    version = manifest.findtext("version")
    tampered = data.replace(f"<version>{version}</version>".encode(),
                            f"<version>{version}.1</version>".encode(), 1)
    assert tampered != data
    with pytest.raises(ValueError, match="public signature"):
        gate.signed_manifest(tampered)


@pytest.mark.parametrize("schema,mode", [("magnolie-desktop-candidate-v1", 0o644),
                                         ("magnolie-desktop-candidate-v2", True),
                                         ("magnolie-desktop-candidate-v2", 420.0)])
def test_old_schema_and_noninteger_modes_are_not_migrated(candidate, schema, mode):
    root, directory, _, _ = candidate
    record = gate.json_read(directory / "candidate.json")
    record["schema"] = schema
    record["sources"]["tools/synthetic.py"]["mode"] = mode
    write(directory / "candidate.json", record)
    with pytest.raises(ValueError, match="schema|mode inventory"):
        gate.candidate_check(root, directory)
