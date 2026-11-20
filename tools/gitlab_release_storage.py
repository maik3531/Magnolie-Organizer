#!/usr/bin/env python3
"""Plan, verify, activate, then retire one explicitly managed GitLab release.

This is a storage transaction, not a build or a grant of release authority.
Every entry point requires the caller's existing release gate. Public metadata
and a persistent compare-and-swap state serialize cooperating publishers.
"""

import argparse
import base64
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
import tempfile

from gitlab_storage_api import GitLabAPI, GitLabAPIError


PROJECTS = frozenset("maik3531/" + name for name in (
    "mint-forgs", "LibreOffice_KI-Assistent", "dictation", "iptv-recorder",
    "mint-youtube-tui", "toktik-player", "tux-i-maskottchen"))
STATE_PATH = "release-storage/state.json"
STATE_SCHEMA = "gitlab-release-state-v1"
PLAN_SCHEMA = "gitlab-release-storage-plan-v1"
SPEC_SCHEMA = "gitlab-release-storage-spec-v1"
MIB = 1024 * 1024
POLICY = {
    "git_lfs_limit_bytes": 10 * 1024 * MIB,
    "git_lfs_reserve_bytes": 512 * MIB,
    # An operational budget, NOT a GitLab.com Package Registry quota.
    "registry_budget_bytes": 10 * 1024 * MIB,
    "registry_reserve_bytes": 512 * MIB,
    "maximum_release_bytes": 2 * 1024 * MIB,
}
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
VERSION = re.compile(r"[0-9]+(?:[.-][0-9]+){1,5}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def identity(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def decode_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON field")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON number")))


def integer(value, *, positive=False):
    return type(value) is int and value >= (1 if positive else 0)


def file_record(value):
    require(isinstance(value, dict) and set(value) == {"sha256", "bytes"} and
            isinstance(value["sha256"], str) and SHA256.fullmatch(value["sha256"]) and
            integer(value["bytes"], positive=True), "Invalid file hash or byte count")
    return value


def safe_file(directory, name):
    require(isinstance(name, str) and SEGMENT.fullmatch(name), "Unsafe artifact filename")
    directory = Path(directory).absolute()
    path = directory / name
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlinked release input")
    require(path.is_file(), "Missing release input")
    return path


def inspect_local(directory, name, expected, *, content=False):
    file_record(expected)
    path = safe_file(directory, name)
    digest = hashlib.sha256()
    chunks, length = [], 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "Non-regular release input")
        require(before.st_size == expected["bytes"], "Release input size changed")
        for chunk in iter(lambda: stream.read(MIB), b""):
            length += len(chunk)
            require(length <= expected["bytes"], "Release input grew while reading")
            digest.update(chunk)
            if content:
                require(length <= MIB, "Metadata too large")
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(stamp(before) == stamp(after) == stamp(path.stat()), "Release input changed while reading")
    require(length == expected["bytes"] and digest.hexdigest() == expected["sha256"],
            "Release input hash changed")
    return b"".join(chunks) if content else path


def metadata_path(path):
    require(isinstance(path, str) and len(path) <= 400 and
            str(PurePosixPath(path)) == path and all(SEGMENT.fullmatch(p) for p in path.split("/")) and
            path != STATE_PATH and path.endswith((".json", ".xml", ".sha256", ".txt", ".md")),
            "Unsafe public metadata path")
    return path


def validate_spec(spec):
    require(isinstance(spec, dict) and set(spec) == {
        "schema", "project", "branch", "package", "version", "files", "metadata"}, "Invalid storage specification")
    require(spec["schema"] == SPEC_SCHEMA and spec["project"] in PROJECTS,
            "Unapproved GitLab storage project")
    require(spec["branch"] == "main", "Release storage only manages the main distribution branch")
    require(isinstance(spec["package"], str) and SEGMENT.fullmatch(spec["package"]), "Invalid package name")
    require(isinstance(spec["version"], str) and VERSION.fullmatch(spec["version"]), "Invalid stable version")
    require(isinstance(spec["files"], dict) and 0 < len(spec["files"]) <= 200, "Invalid artifact inventory")
    for name, record in spec["files"].items():
        require(isinstance(name, str) and SEGMENT.fullmatch(name), "Unsafe artifact filename")
        file_record(record)
    require(sum(f["bytes"] for f in spec["files"].values()) <= POLICY["maximum_release_bytes"],
            "Release exceeds the operational upload budget")
    require(isinstance(spec["metadata"], dict) and 0 < len(spec["metadata"]) <= 30, "Missing activation metadata")
    for path, source in spec["metadata"].items():
        metadata_path(path)
        require(source in spec["files"] and spec["files"][source]["bytes"] <= MIB,
                "Activation metadata must be a bounded verified package file")
    return spec


def desktop_spec(spec):
    """The signed manifest must reach its actual client path, not an alias."""
    validate_spec(spec)
    require(spec["project"] == "maik3531/mint-forgs" and spec["package"] == "magnolie-desktop",
            "This CLI uses the Magnolie desktop gate; other projects require their own release-gate adapter")
    require(spec["metadata"].get("Magnolie-Organitzer/update.xml") == "update.xml" and
            all(path == "Magnolie-Organitzer/" + source for path, source in spec["metadata"].items()),
            "Desktop metadata must preserve each verified filename and the exact update-manifest path")
    return spec


def stats(api, project):
    result = api.project()
    require(isinstance(result, dict) and result.get("path_with_namespace") == project and
            integer(result.get("id"), positive=True), "GitLab project identity changed")
    value = result.get("statistics")
    require(isinstance(value, dict) and all(integer(value.get(k)) for k in
            ("repository_size", "lfs_objects_size", "packages_size")), "Missing or invalid GitLab storage statistics")
    return {"project_id": result["id"], **{k: value[k] for k in
            ("repository_size", "lfs_objects_size", "packages_size")}}


def check_budget(value, added_bytes, metadata_bytes):
    require(value["repository_size"] + value["lfs_objects_size"] + metadata_bytes +
            POLICY["git_lfs_reserve_bytes"] <= POLICY["git_lfs_limit_bytes"],
            "Git/LFS reserve would be exhausted")
    require(value["packages_size"] + added_bytes + POLICY["registry_reserve_bytes"] <=
            POLICY["registry_budget_bytes"], "Registry operational reserve would be exhausted")


def remote_file(api, path, ref):
    value = api.file(path, ref)
    if value is None:
        return None
    require(isinstance(value, dict) and value.get("file_path") == path and
            value.get("encoding") == "base64" and integer(value.get("size")) and value["size"] <= MIB and
            isinstance(value.get("last_commit_id"), str) and COMMIT.fullmatch(value["last_commit_id"]),
            "Invalid GitLab metadata response")
    try:
        data = base64.b64decode(value["content"], validate=True)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("Invalid GitLab metadata encoding") from error
    digest = hashlib.sha256(data).hexdigest()
    require(len(data) == value["size"] and value.get("content_sha256") == digest,
            "GitLab metadata hash or size mismatch")
    return {"sha256": digest, "bytes": len(data), "last_commit_id": value["last_commit_id"],
            "content": base64.b64encode(data).decode("ascii")}


def state_data(snapshot, project):
    if snapshot is None:
        return {"schema": STATE_SCHEMA, "project": project, "channels": {}, "operation": None}
    value = decode_json(base64.b64decode(snapshot["content"], validate=True))
    require(isinstance(value, dict) and set(value) == {"schema", "project", "channels", "operation"} and
            value["schema"] == STATE_SCHEMA and value["project"] == project and
            isinstance(value["channels"], dict), "Unknown remote release state")
    return value


def package_snapshot(api, value, name):
    require(isinstance(value, dict) and integer(value.get("id"), positive=True) and
            value.get("name") == name and value.get("package_type") == "generic" and
            isinstance(value.get("version"), str) and VERSION.fullmatch(value["version"]) and
            value.get("status") in {"default", "deprecated"}, "Package is not a stable readable release")
    files, ids = {}, set()
    for item in api.files(value["id"]):
        require(isinstance(item, dict) and integer(item.get("id"), positive=True) and
                item["id"] not in ids and isinstance(item.get("file_name"), str) and
                SEGMENT.fullmatch(item["file_name"]) and item["file_name"] not in files,
                "Duplicate or invalid registry file")
        ids.add(item["id"])
        record = file_record({"sha256": item.get("file_sha256"), "bytes": item.get("size")})
        files[item["file_name"]] = dict(record, id=item["id"])
    return {"id": value["id"], "name": name, "version": value["version"],
            "status": value["status"], "files": files}


def inventory(api, name):
    result, ids = [], set()
    for item in api.packages(name):
        require(item.get("id") not in ids, "Duplicate registry package")
        ids.add(item.get("id"))
        result.append(package_snapshot(api, item, name))
    require(len({p["version"] for p in result}) == len(result), "Duplicate registry version")
    return sorted(result, key=lambda p: p["id"])


def hashes(package):
    return {name: {"sha256": f["sha256"], "bytes": f["bytes"]} for name, f in package["files"].items()}


def version_key(value):
    parts = tuple(int(p) for p in re.split(r"[.-]", value))
    return parts + (0,) * (6 - len(parts))


def local_metadata(directory, spec):
    result = {}
    for path, source in spec["metadata"].items():
        data = inspect_local(directory, source, spec["files"][source], content=True)
        text = data.decode("utf-8")
        require("\x00" not in text and not text.startswith("version https://git-lfs.github.com/spec/v1"),
                "Binary/LFS data in activation metadata")
        result[path] = {**spec["files"][source], "content": base64.b64encode(data).decode("ascii")}
    require(sum(m["bytes"] for m in result.values()) <= MIB, "Activation metadata exceeds budget")
    return result


def build_plan(api, spec, directory, authorize):
    """Read-only: bind exact old IDs, new bytes, metadata and storage reserves."""
    validate_spec(spec)
    authorize()
    for name, expected in spec["files"].items():
        inspect_local(directory, name, expected)
    metadata = local_metadata(directory, spec)
    before_stats = stats(api, spec["project"])
    head = api.head(spec["branch"])
    require(isinstance(head, str) and COMMIT.fullmatch(head), "Invalid distribution HEAD")
    old_file = remote_file(api, STATE_PATH, head)
    old = state_data(old_file, spec["project"])
    require(old["operation"] is None, "Another release is unfinished; resume its exact saved plan")
    packages = inventory(api, spec["package"])
    previous = old["channels"].get(spec["package"])
    retired = []
    if previous is not None:
        require(isinstance(previous, dict) and set(previous) == {
            "version", "package_id", "files", "metadata", "plan_sha256"}, "Invalid managed channel")
        require(VERSION.fullmatch(previous["version"]) and
                version_key(spec["version"]) > version_key(previous["version"]), "Release version must advance")
        require(set(previous["metadata"]) == set(metadata), "Activation must cover every managed metadata file")
        retired = [p for p in packages if p["id"] == previous["package_id"]]
        require(len(retired) == 1 and retired[0]["version"] == previous["version"] and
                hashes(retired[0]) == previous["files"], "Previously active package changed or disappeared")
    target = [p for p in packages if p["version"] == spec["version"]]
    require(len(packages) == len(retired) + len(target),
            "Unmanaged versions found; explicit dependency review required before adopting them")
    require(not target or (target[0]["status"] == "default" and all(
        spec["files"].get(name) == f for name, f in hashes(target[0]).items())),
        "Existing target version differs from the candidate")
    for channel, data in old["channels"].items():
        require(isinstance(data, dict) and isinstance(data.get("metadata"), dict), "Invalid channel metadata")
        require(channel == spec["package"] or not set(data["metadata"]) & set(metadata),
                "Metadata is owned by another release channel")
    old_metadata = {p: remote_file(api, p, head) for p in metadata}
    if previous:
        require(all(old_metadata[p] is not None and old_metadata[p]["sha256"] == digest
                    for p, digest in previous["metadata"].items()), "Active download metadata changed")
    missing = set(spec["files"]) - (set(target[0]["files"]) if target else set())
    added = sum(spec["files"][name]["bytes"] for name in missing)
    # Three small state commits plus changed metadata; never count release bytes as Git growth.
    growth = sum(m["bytes"] for m in metadata.values()) + 3 * (len(canonical(old)) +
             len(canonical(spec["files"])) + 65536)
    check_budget(before_stats, added, growth)
    require(api.head(spec["branch"]) == head, "Distribution changed while planning")
    return {"schema": PLAN_SCHEMA, "policy": POLICY, "spec": copy.deepcopy(spec), "head": head,
            "state_before": old_file, "metadata_before": old_metadata, "metadata_after": metadata,
            "inventory_before": packages, "delete": retired, "statistics_before": before_stats,
            "expected_upload_bytes": added, "expected_git_growth_bytes": growth}


def action(path, snapshot, data):
    result = {"action": "update" if snapshot is not None else "create", "file_path": path,
              "encoding": "base64", "content": base64.b64encode(data).decode("ascii")}
    if snapshot is not None:
        result["last_commit_id"] = snapshot["last_commit_id"]
    return result


def read_current(api, spec):
    head = api.head(spec["branch"])
    snapshot = remote_file(api, STATE_PATH, head)
    state = state_data(snapshot, spec["project"])
    return head, snapshot, state


def metadata_matches(api, spec, expected, head):
    for path, value in expected.items():
        found = remote_file(api, path, head)
        if value is None:
            require(found is None, "Activation metadata appeared after planning")
        else:
            require(found is not None and found["sha256"] == value["sha256"] and
                    found["bytes"] == value["bytes"], "Activation metadata changed")
    require(api.head(spec["branch"]) == head, "Distribution changed during verification")


def assert_owned(api, spec, expected, metadata):
    head, snapshot, state = read_current(api, spec)
    require(snapshot is not None and state == expected and snapshot["last_commit_id"] == head,
            "Release lease or branch changed; no further mutation")
    metadata_matches(api, spec, metadata, head)
    return head, snapshot


def commit_state(api, spec, snapshot, state, actions, metadata):
    """One CAS state-file action in EVERY transaction, with read-back on ambiguity."""
    payload = actions + [action(STATE_PATH, snapshot, canonical(state))]
    failure = None
    try:
        api.commit(spec["branch"], payload, "Maintain verified release storage (Refs #698)")
    except (GitLabAPIError, OSError) as error:
        failure = error
    try:
        return assert_owned(api, spec, state, metadata)
    except (ValueError, GitLabAPIError, OSError):
        if failure is not None:
            raise failure
        raise


def target_package(api, spec, *, complete):
    packages = inventory(api, spec["package"])
    targets = [p for p in packages if p["version"] == spec["version"]]
    require(len(targets) <= 1, "Duplicate target package")
    if not targets:
        require(not complete, "Uploaded target package is missing")
        return None, packages
    target = targets[0]
    require(target["status"] == "default" and all(spec["files"].get(n) == r for n, r in hashes(target).items()),
            "Target package contains changed or unexpected files")
    require(not complete or hashes(target) == spec["files"], "Uploaded release is incomplete")
    return target, packages


def verify_target(api, spec):
    target, _ = target_package(api, spec, complete=True)
    for name, expected in spec["files"].items():
        api.verify_download(spec["package"], spec["version"], name, expected)
    again, _ = target_package(api, spec, complete=True)
    require(again == target, "Uploaded release changed during full download verification")
    return target


def apply_plan(api, plan, directory, accepted_sha256, authorize, report=None, *, execution_id=None,
               previous_report=None):
    """Resume the exact plan; never delete before verified activation read-back."""
    require(isinstance(accepted_sha256, str) and SHA256.fullmatch(accepted_sha256) and
            identity(plan) == accepted_sha256, "Saved plan changed or exact plan identity missing")
    require(plan.get("schema") == PLAN_SCHEMA and plan.get("policy") == POLICY, "Unknown storage plan/policy")
    spec = validate_spec(plan["spec"])
    require(local_metadata(directory, spec) == plan["metadata_after"], "Planned metadata changed")
    authorize()
    for name, expected in spec["files"].items():
        inspect_local(directory, name, expected)
    old = state_data(plan["state_before"], spec["project"])
    require(old["operation"] is None, "Plan did not start from idle state")
    execution_id = secrets.token_hex(16) if execution_id is None else execution_id
    require(isinstance(execution_id, str) and re.fullmatch(r"[0-9a-f]{32}", execution_id),
            "Invalid release execution identity")
    uploading = copy.deepcopy(old)
    execution_digest = hashlib.sha256(execution_id.encode("ascii")).hexdigest()
    operation = lambda phase: {"plan_sha256": accepted_sha256, "execution_sha256": execution_digest, "phase": phase}
    uploading["operation"] = operation("uploading")
    journal = {"schema": "gitlab-release-storage-result-v1", "plan_sha256": accepted_sha256,
               "execution_id": execution_id,
               "status": "started", "planned_delete_ids": [p["id"] for p in plan["delete"]],
               "delete_requested_ids": [], "deleted_ids": [], "already_absent_ids": [], "confirmed_deleted_object_bytes": 0,
               "statistics_before": plan["statistics_before"], "statistics_after": None,
               "physical_freed_bytes": None}
    if previous_report is not None:
        require(previous_report.get("schema") == journal["schema"] and
                previous_report.get("plan_sha256") == accepted_sha256 and
                previous_report.get("execution_id") == execution_id and
                previous_report.get("planned_delete_ids") == journal["planned_delete_ids"],
                "Previous execution report belongs to another transaction")
        # Preserve evidence of already completed effects. This is an audit log,
        # never authority to skip any remote precondition or deletion check.
        for key in ("delete_requested_ids", "deleted_ids", "already_absent_ids"):
            values = previous_report.get(key)
            require(isinstance(values, list) and len(values) == len(set(values)) and
                    set(values) <= set(journal["planned_delete_ids"]), "Invalid prior execution report")
            journal[key] = list(values)
        journal["confirmed_deleted_object_bytes"] = sum(
            f["bytes"] for p in plan["delete"] if p["id"] in journal["deleted_ids"] for f in p["files"].values())
    emit = lambda: report(copy.deepcopy(journal)) if report is not None else None
    emit()
    try:
        current_stats = stats(api, spec["project"])
        require(current_stats["project_id"] == plan["statistics_before"]["project_id"],
                "GitLab project ID changed since planning")
        existing_target, _ = target_package(api, spec, complete=False)
        existing_names = set(existing_target["files"]) if existing_target else set()
        missing_bytes = sum(v["bytes"] for n, v in spec["files"].items() if n not in existing_names)
        head, snapshot, current = read_current(api, spec)
        completed_before = current["channels"].get(spec["package"], {}).get("plan_sha256") == accepted_sha256
        remaining_growth = 0 if completed_before and current["operation"] is None else plan["expected_git_growth_bytes"]
        check_budget(current_stats, missing_bytes, remaining_growth)
        if current == old and snapshot == plan["state_before"]:
            require(head == plan["head"], "Stale plan: distribution HEAD changed")
            require(inventory(api, spec["package"]) == plan["inventory_before"], "Stale registry inventory")
            metadata_matches(api, spec, plan["metadata_before"], head)
            commit_state(api, spec, snapshot, uploading, [], plan["metadata_before"])
            current = uploading
        current_operation = current.get("operation")
        completed = current["channels"].get(spec["package"], {}).get("plan_sha256") == accepted_sha256
        require(current == uploading or (completed and current_operation in (
            None, operation("active"))),
            "Another release owns this channel; resume its saved plan")
        if current == uploading:
            assert_owned(api, spec, uploading, plan["metadata_before"])
            target, packages = target_package(api, spec, complete=False)
            old_packages = [p for p in packages if p["version"] != spec["version"]]
            require(old_packages == plan["delete"], "Old package inventory changed before upload")
            for name, expected in spec["files"].items():
                assert_owned(api, spec, uploading, plan["metadata_before"])
                target, _ = target_package(api, spec, complete=False)
                if target is None or name not in target["files"]:
                    inspect_local(directory, name, expected)
                    api.upload(spec["package"], spec["version"], name, safe_file(directory, name))
                    inspect_local(directory, name, expected)
            target = verify_target(api, spec)
            require([p for p in inventory(api, spec["package"]) if p["version"] != spec["version"]] ==
                    plan["delete"], "Old package inventory changed during upload")
            authorize()
            check_budget(stats(api, spec["project"]), 0, plan["expected_git_growth_bytes"])
            _, snapshot = assert_owned(api, spec, uploading, plan["metadata_before"])
            active = copy.deepcopy(old)
            active["channels"][spec["package"]] = {
                "version": spec["version"], "package_id": target["id"], "files": spec["files"],
                "metadata": {p: v["sha256"] for p, v in plan["metadata_after"].items()},
                "plan_sha256": accepted_sha256}
            active["operation"] = operation("active")
            actions = [action(p, plan["metadata_before"][p], base64.b64decode(v["content"], validate=True))
                       for p, v in plan["metadata_after"].items()]
            commit_state(api, spec, snapshot, active, actions, plan["metadata_after"])
            current = active
        target = verify_target(api, spec)
        expected_active = copy.deepcopy(old)
        expected_active["channels"][spec["package"]] = {
            "version": spec["version"], "package_id": target["id"], "files": spec["files"],
            "metadata": {p: v["sha256"] for p, v in plan["metadata_after"].items()},
            "plan_sha256": accepted_sha256}
        idle = copy.deepcopy(expected_active)
        expected_active["operation"] = operation("active")
        require(current in (expected_active, idle), "Activated state does not match this exact plan")
        assert_owned(api, spec, current, plan["metadata_after"])
        journal["status"] = "active"
        emit()
        for retired in plan["delete"]:
            require(retired["id"] != target["id"] and retired["name"] == spec["package"] and
                    retired["version"] != spec["version"], "Deletion targets the active or another package")
            assert_owned(api, spec, current, plan["metadata_after"])
            packages = inventory(api, spec["package"])
            require(all(p["id"] in {target["id"], *journal["planned_delete_ids"]} for p in packages),
                    "Unexpected package appeared during cleanup")
            candidate = [p for p in packages if p["id"] == retired["id"]]
            if not candidate:
                if retired["id"] not in journal["deleted_ids"] and retired["id"] not in journal["already_absent_ids"]:
                    journal["already_absent_ids"].append(retired["id"])
                emit()
                continue
            require(current == expected_active and candidate == [retired], "Deletion inventory changed")
            # Both full active inventory and public downloads were verified above.
            require(next((p for p in packages if p["id"] == target["id"]), None) == target,
                    "Active package changed before cleanup")
            api.delete_package(retired["id"])
            if retired["id"] not in journal["delete_requested_ids"]:
                journal["delete_requested_ids"].append(retired["id"])
            emit()
            # A detail-endpoint 404 alone is NOT proof: check the all-status list.
            require(not any(p["id"] == retired["id"] for p in api.packages(spec["package"])),
                    "Deletion is not yet complete; retain active lease and retry later")
            if retired["id"] not in journal["deleted_ids"]:
                journal["deleted_ids"].append(retired["id"])
                journal["confirmed_deleted_object_bytes"] += sum(f["bytes"] for f in retired["files"].values())
            emit()
        require(inventory(api, spec["package"]) == [target], "Cleanup did not leave exactly one managed version")
        _, snapshot = assert_owned(api, spec, current, plan["metadata_after"])
        journal["statistics_after"] = stats(api, spec["project"])
        check_budget(journal["statistics_after"], 0, 0)
        if current != idle:
            commit_state(api, spec, snapshot, idle, [], plan["metadata_after"])
        journal["status"] = "complete"
        emit()
        return journal
    except BaseException as error:
        journal["status"] = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
        journal["error_type"] = type(error).__name__
        emit()
        raise


def save_json(path, value, *, exclusive=False):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlinked storage record")
    if exclusive:
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(path.parent)
        return
    fd, temporary = tempfile.mkstemp(prefix=".storage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def report_lock(path):
    """Two local invocations must not share the resume identity concurrently."""
    path = Path(str(path) + ".lock").absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlinked report lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "Invalid report lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "apply"))
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--accept-candidate", required=True)
    parser.add_argument("--accept-plan-sha256")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    # Fixed module from this source checkout, never an imported caller-supplied gate.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "magnolie-organizer/werkzeuge"))
    import release_gate
    require(root == Path(__file__).resolve().parents[1], "Use the canonical product source checkout")
    if args.operation == "plan":
        require(args.spec is not None, "Storage specification required")
        spec = release_gate.json_read(args.spec)
        plan = None
    else:
        plan = release_gate.json_read(args.plan)
        require(identity(plan) == args.accept_plan_sha256, "Exact plan identity required before network access")
        spec = plan["spec"]
    desktop_spec(spec)

    def authorize():
        record, identity_, _ = release_gate.verify(root, args.candidate.resolve(), args.approval,
                                                  args.accept_candidate)
        release_gate.storage_candidate_check(args.directory, record, identity_)
        exported = release_gate.json_read(args.directory / "storage-candidate.json")
        require(spec["files"] == exported["artifacts"] and spec["version"] == record["version"],
                "Storage plan differs from the approved publication")

    api = GitLabAPI(spec["project"])
    if args.operation == "plan":
        plan = build_plan(api, spec, args.directory, authorize)
        save_json(args.plan, plan, exclusive=True)
        print("Read-only plan saved. SHA256: " + identity(plan))
    else:
        require(args.report is not None, "A durable execution report is required")
        require(args.report.absolute() not in {args.plan.absolute(), args.approval.absolute(),
                args.candidate.absolute() / "candidate.json"}, "Execution report cannot overwrite a release input")
        with report_lock(args.report):
            execution_id = None
            previous = None
            if args.report.exists():
                previous = release_gate.json_read(args.report)
                require(previous.get("schema") == "gitlab-release-storage-result-v1" and
                        previous.get("plan_sha256") == args.accept_plan_sha256,
                        "Execution report belongs to another plan")
                execution_id = previous["execution_id"]
            result = apply_plan(api, plan, args.directory, args.accept_plan_sha256, authorize,
                                lambda value: save_json(args.report, value), execution_id=execution_id,
                                previous_report=previous)
        print("Verified release storage transaction: " + result["status"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, GitLabAPIError, KeyError, TypeError) as error:
        sys.exit("Release storage rejected: " + str(error))
