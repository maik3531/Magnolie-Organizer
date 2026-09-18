"""Pure Python record-boundary fixtures, never production approval or native tests.

No monkeypatches, SDKs, signing, builds, network, GPU or VMs. Full candidate
provenance remains mandatory in verify; these units exercise its shared record
validator and real file bindings, not a substitute candidate-verification path.
"""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "werkzeuge"))
import release_gate as gate
import release_sources as sources


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def reference(path):
    return {"file": path.name, "sha256": sources.digest(path)}


@pytest.fixture(params=[1, 2])
def authorization(tmp_path, request):
    directory, evidence = tmp_path / "candidate", tmp_path / "private-evidence"
    directory.mkdir()
    evidence.mkdir(mode=0o700)
    groups = gate.artifact_groups("9.8.7", "9.8.6", "amd64")
    for name in sum(groups.values(), []):
        (directory / name).write_text("SYNTHETIC ARTIFACT ONLY: " + name)
    record = dict(version="9.8.7", notesVersion="9.8.6", sourceSha256="a" * 64,
                  artifacts=gate.artifact_map(directory, sum(groups.values(), [])),
                  gates={"fedora": "passed", "autopkgtest": "passed"})
    write(directory / "candidate.json", record)
    identity = sources.digest(directory / "candidate.json")
    log = evidence / "synthetic.log"
    log.write_text("SYNTHETIC ONLY, NOT AN EXECUTED NATIVE TEST")
    refs = {}
    for platform, checks in gate.CHECKS.items():
        binaries = {name: record["artifacts"][name]["sha256"]
                    for name in groups["notes" if platform == "android" else platform]
                    if name.endswith((".deb", ".AppImage", ".flatpak", ".rpm", ".apk", "-Setup-x64.exe", "-x64.zip"))
                    and not name.endswith(".src.rpm")}
        path = evidence / (platform + ".json")
        write(path, dict(schema="magnolie-native-evidence-v1", platform=platform,
                         candidateSha256=identity, sourceSha256=record["sourceSha256"], artifacts=binaries,
                         checks={check: dict(exitCode=0, log=reference(log), **(
                             {"artifact": "magnolie-organizer-kde_9.8.7_amd64.deb",
                              "sha256": binaries["magnolie-organizer-kde_9.8.7_amd64.deb"],
                              "profile": gate.KDE_CHECKS[check]} if check in gate.KDE_CHECKS else {})) for check in checks}))
        refs[platform] = reference(path)
    approval = dict(schema=f"magnolie-desktop-approval-v{request.param}", candidateSha256=identity,
                    nativeEvidence=refs, qemuException=None)
    if request.param == 1:
        decision = evidence / "synthetic-personal.txt"
        decision.write_text("SYNTHETIC ONLY\n" + identity + "\n" + gate.ACCEPTANCE)
        approval["userAcceptance"] = dict(accepted=True, candidateSha256=identity,
                                          statement=gate.ACCEPTANCE, evidence=reference(decision))
    else:
        quote = evidence / "synthetic-quote.txt"
        # Invented fixture text, deliberately NOT a real user quote or magic phrase.
        quote.write_bytes(b"SYNTHETIC USER: release this fixture only after all required tests pass.\r\n")
        instructions = evidence / "instructions.json"
        write(instructions, dict(schema="magnolie-delegated-instructions-v1", delegated=True,
                                 version=record["version"], notesVersion=record["notesVersion"], quote=reference(quote)))
        operator = evidence / "operator.json"
        write(operator, dict(schema="magnolie-delegated-operator-v1", statement="Operator verified delegated conditions",
                             afterTests=True, finalResult="passed", candidateSha256=identity,
                             sourceSha256=record["sourceSha256"], artifacts=record["artifacts"],
                             instructions=reference(instructions), nativeEvidence=refs, qemuException=None))
        approval["authorization"] = dict(kind="delegated-conditional", instructions=reference(instructions),
                                          operatorRecord=reference(operator))
    path = evidence / "synthetic-approval.json"
    write(path, approval)
    return directory, path, record, identity, groups


def test_complete_records_are_read_only_and_bind_every_file(authorization):
    directory, path, record, identity, groups = authorization
    before = {p: p.read_bytes() for p in directory.parent.rglob("*") if p.is_file()}
    bindings = {directory / "candidate.json": identity}
    gate.approval_check(directory, path, record, identity, groups, bindings)
    gate.check_bindings(bindings)
    assert set(bindings) == {directory / "candidate.json", *path.parent.iterdir()}
    assert {p: p.read_bytes() for p in before} == before
    assert not (directory / "update.xml").exists()


@pytest.mark.parametrize("damage", ["unknown", "missing", "extra", "mixed", "candidate"])
def test_approval_schema_denies_unknown_incomplete_and_stale(authorization, damage):
    directory, path, record, identity, groups = authorization
    approval = gate.json_read(path)
    field = "authorization" if "authorization" in approval else "userAcceptance"
    if damage == "unknown":
        approval["schema"] = "magnolie-desktop-approval-v3"
    elif damage == "missing":
        del approval[field]
    elif damage == "extra":
        approval["automaticBuildApproval"] = True
    elif damage == "mixed":
        approval["userAcceptance" if field == "authorization" else "authorization"] = approval.pop(field)
    else:
        approval["candidateSha256"] = "0" * 64
    write(path, approval)
    with pytest.raises(ValueError):
        gate.approval_check(directory, path, record, identity, groups, {})


@pytest.mark.parametrize("platform", list(gate.CHECKS))
@pytest.mark.parametrize("damage", ["missing-platform", "missing-check", "failure", "bool-exit", "missing-log",
                                   "candidate", "source", "artifacts"])
def test_both_paths_require_all_native_checks(authorization, platform, damage):
    directory, path, record, identity, groups = authorization
    approval = gate.json_read(path)
    native_path = path.parent / (platform + ".json")
    native = gate.json_read(native_path)
    check = sorted(gate.CHECKS[platform])[0]
    if damage == "missing-platform":
        del approval["nativeEvidence"][platform]
    else:
        if damage == "missing-check":
            del native["checks"][check]
        elif damage in {"failure", "bool-exit"}:
            native["checks"][check]["exitCode"] = 1 if damage == "failure" else False
        elif damage == "missing-log":
            del native["checks"][check]["log"]
        elif damage in {"candidate", "source"}:
            native[damage + "Sha256"] = "0" * 64
        else:
            native["artifacts"].pop(next(iter(native["artifacts"])))
        write(native_path, native)
        approval["nativeEvidence"][platform] = reference(native_path)
    if "authorization" in approval:
        operator_path = path.parent / "operator.json"
        operator = gate.json_read(operator_path)
        operator["nativeEvidence"] = approval["nativeEvidence"]
        write(operator_path, operator)
        approval["authorization"]["operatorRecord"] = reference(operator_path)
    write(path, approval)
    with pytest.raises(ValueError, match="Native|native|different candidate"):
        gate.approval_check(directory, path, record, identity, groups, {})


@pytest.mark.parametrize("authorization", [1], indirect=True)
@pytest.mark.parametrize("damage", ["false", "integer", "statement", "candidate", "generic-log", "delegated-quote"])
def test_v1_still_requires_strict_personal_proof(authorization, damage):
    directory, path, record, identity, groups = authorization
    approval = gate.json_read(path)
    acceptance = approval["userAcceptance"]
    if damage in {"false", "integer"}:
        acceptance["accepted"] = False if damage == "false" else 1
    elif damage == "statement":
        acceptance["statement"] = "Operator verified delegated conditions"
    elif damage == "candidate":
        acceptance["candidateSha256"] = "0" * 64
    else:
        decision = path.parent / "synthetic-personal.txt"
        decision.write_text("SYNTHETIC: publish after tests" if damage == "delegated-quote" else "build passed")
        acceptance["evidence"] = reference(decision)
    write(path, approval)
    with pytest.raises(ValueError, match="personal|User decision"):
        gate.approval_check(directory, path, record, identity, groups, {})


@pytest.mark.parametrize("authorization", [2], indirect=True)
@pytest.mark.parametrize("damage", ["kind", "missing-instructions", "missing-operator", "unknown-field",
                                   "delegated-false", "delegated-integer", "instruction-schema", "instruction-version",
                                   "instruction-notesVersion", "instruction-extra", "missing-quote", "empty-quote",
                                   "quote-whitespace", "quote-invalid-utf8", "quote-is-log", "instructions-rebound"])
def test_delegation_is_explicit_scoped_and_requires_original_quote(authorization, damage):
    directory, path, record, identity, groups = authorization
    approval = gate.json_read(path)
    auth = approval["authorization"]
    instructions_path = path.parent / "instructions.json"
    instructions = gate.json_read(instructions_path)
    if damage == "kind":
        auth["kind"] = "build-success"
    elif damage.startswith("missing-") and damage != "missing-quote":
        del auth["instructions" if damage == "missing-instructions" else "operatorRecord"]
    elif damage == "unknown-field":
        auth["accepted"] = True
    else:
        if damage.startswith("delegated-"):
            instructions["delegated"] = False if damage == "delegated-false" else 1
        elif damage.startswith("instruction-"):
            instructions[damage.removeprefix("instruction-")] = "unknown-or-stale"
        elif damage == "missing-quote":
            del instructions["quote"]
        elif damage == "quote-is-log":
            instructions["quote"] = reference(path.parent / "synthetic.log")
        else:
            quote = path.parent / "synthetic-quote.txt"
            quote.write_bytes({"empty-quote": b"", "quote-whitespace": b" \r\n", "quote-invalid-utf8": b"\xff",
                               "instructions-rebound": b"SYNTHETIC changed instructions"}[damage])
            instructions["quote"] = reference(quote)
        write(instructions_path, instructions)
        auth["instructions"] = reference(instructions_path)
        if damage != "instructions-rebound":
            operator_path = path.parent / "operator.json"
            operator = gate.json_read(operator_path)
            operator["instructions"] = auth["instructions"]
            write(operator_path, operator)
            auth["operatorRecord"] = reference(operator_path)
    write(path, approval)
    with pytest.raises(ValueError):
        gate.approval_check(directory, path, record, identity, groups, {})


@pytest.mark.parametrize("authorization", [2], indirect=True)
@pytest.mark.parametrize("field", ["schema", "statement", "afterTests", "finalResult", "candidateSha256", "sourceSha256",
                                  "artifacts", "instructions", "nativeEvidence", "qemuException"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_posttest_operator_record_binds_exact_final_result(authorization, field, damage):
    directory, path, record, identity, groups = authorization
    approval = gate.json_read(path)
    operator_path = path.parent / "operator.json"
    operator = gate.json_read(operator_path)
    if damage == "missing":
        del operator[field]
    else:
        operator[field] = 1 if field == "afterTests" else "SYNTHETIC stale or failed"
    write(operator_path, operator)
    approval["authorization"]["operatorRecord"] = reference(operator_path)
    write(path, approval)
    with pytest.raises(ValueError, match="Post-test operator"):
        gate.approval_check(directory, path, record, identity, groups, {})


@pytest.mark.parametrize("authorization", [2], indirect=True)
@pytest.mark.parametrize("name", ["synthetic-quote.txt", "instructions.json", "operator.json", "linux.json", "synthetic.log",
                                 "synthetic-approval.json", "candidate.json"])
@pytest.mark.parametrize("damage", ["changed", "missing", "symlink"])
def test_new_records_participate_in_final_file_bindings(authorization, name, damage):
    directory, path, record, identity, groups = authorization
    bindings = {directory / "candidate.json": identity}
    gate.approval_check(directory, path, record, identity, groups, bindings)
    target = (directory if name == "candidate.json" else path.parent) / name
    if damage == "changed":
        target.write_bytes(target.read_bytes() + b" ")
    elif damage == "missing":
        target.unlink()
    else:
        moved = target.with_suffix(".moved")
        target.rename(moved)
        target.symlink_to(moved)
    with pytest.raises(ValueError):
        gate.check_bindings(bindings)
    if name not in {"candidate.json", "synthetic-approval.json"}:
        with pytest.raises(ValueError):
            gate.approval_check(directory, path, record, identity, groups, {})


@pytest.mark.parametrize("qemu", [None, "short", "SYNTHETIC QEMU unavailable for a documented reason"])
def test_qemu_exception_requires_explicit_private_reason_in_either_path(authorization, qemu):
    directory, path, record, identity, groups = authorization
    record = copy.deepcopy(record)
    record["gates"]["autopkgtest"] = "unavailable"
    approval = gate.json_read(path)
    approval["qemuException"] = qemu
    if "authorization" in approval:
        operator_path = path.parent / "operator.json"
        operator = gate.json_read(operator_path)
        operator["qemuException"] = qemu
        write(operator_path, operator)
        approval["authorization"]["operatorRecord"] = reference(operator_path)
    write(path, approval)
    if qemu is None or qemu == "short":
        with pytest.raises(ValueError, match="QEMU"):
            gate.approval_check(directory, path, record, identity, groups, {})
    else:
        gate.approval_check(directory, path, record, identity, groups, {})
        assert not (directory / "HINWEIS.txt").exists()


@pytest.mark.parametrize("authorization", [2], indirect=True)
def test_valid_delegation_cannot_bypass_source_inventory(authorization, tmp_path):
    directory, path, record, identity, groups = authorization
    root = tmp_path / "canonical"
    root.mkdir()
    for component in (gate.LINUX, gate.WINDOWS, "magnolie-handbuch-stamm", "contracts", ".github", "tools", "magnolie-notes-stamm"):
        (root / component).mkdir()
    (root / gate.LINUX / "debian").mkdir()
    (root / "magnolie-handbuch-stamm/debian").mkdir()
    (root / "magnolie-notes-stamm/app").mkdir()
    (root / gate.LINUX / "debian/changelog").write_text("magnolie-organizer (9.8.7) unstable; urgency=medium\n")
    (root / "magnolie-handbuch-stamm/debian/changelog").write_text("magnolie-handbuch (9.8.7) unstable; urgency=medium\n")
    (root / gate.WINDOWS / "Directory.Build.props").write_text("<Project><PropertyGroup><Version>9.8.7</Version></PropertyGroup></Project>")
    (root / "magnolie-notes-stamm/app/build.gradle.kts").write_text('versionName = "9.8.6"')
    bootstrap = (Path(gate.__file__).resolve().parents[1] / "update.xml").read_bytes()
    for target in (root / "update.xml", root / gate.LINUX / "update.xml"):
        target.write_bytes(bootstrap)
    existing = root / "tools/existing.py"
    existing.write_text("# SYNTHETIC original source")
    existing.chmod(0o644)
    record.update(schema="magnolie-desktop-candidate-v2", architecture="amd64", sources=sources.inventory(root))
    record["sourceSha256"] = sources.inventory_digest(record["sources"])
    write(directory / "candidate.json", record)
    identity = sources.digest(directory / "candidate.json")
    approval = gate.json_read(path)
    approval["candidateSha256"] = identity
    for platform in gate.CHECKS:
        native_path = path.parent / (platform + ".json")
        native = gate.json_read(native_path)
        native.update(candidateSha256=identity, sourceSha256=record["sourceSha256"])
        write(native_path, native)
        approval["nativeEvidence"][platform] = reference(native_path)
    operator_path = path.parent / "operator.json"
    operator = gate.json_read(operator_path)
    operator.update(candidateSha256=identity, sourceSha256=record["sourceSha256"], nativeEvidence=approval["nativeEvidence"])
    write(operator_path, operator)
    approval["authorization"]["operatorRecord"] = reference(operator_path)
    write(path, approval)
    gate.approval_check(directory, path, record, identity, groups, {})
    for damage in ("source", "mode", "new-source"):
        target = root / "tools/new.py" if damage == "new-source" else existing
        if damage == "mode":
            target.chmod(0o755)
        else:
            target.write_text("# SYNTHETIC changed source")
        with pytest.raises(ValueError, match="Canonical sources changed; rebuild"):
            gate.verify(root, directory, path, identity)
        if damage == "new-source":
            target.unlink()
        existing.write_text("# SYNTHETIC original source")
        existing.chmod(0o644)
