import copy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_calendar_dedup import apply_birthdays, CleanupArchive
from test_calendar_birthday_dedup import event, local


def fixture():
    remote = {"original": event("original"), "copy": event("copy", created="20260101T000000Z")}
    items = [local("original"), local("copy")]
    saved = {}; mutations = []
    def save(value): saved.clear(); saved.update(copy.deepcopy(value))
    def remove(uid):
        assert saved["operations"][uid]["phase"] == "prepared"
        assert saved["operations"][uid]["removeText"] == remote[uid]
        mutations.append(uid); del remote[uid]
    def run(**overrides):
        return apply_birthdays(items, list(remote.values()), "calendar", "eds:calendar",
            **dict(read_current=remote.get, remove=remove, load_state=lambda: copy.deepcopy(saved), save_state=save, **overrides))
    return remote, items, saved, mutations, run, save


def test_backup_precedes_delete_and_replay_rebinds_without_recreating():
    remote, items, saved, mutations, run, _ = fixture()
    assert run() == {"removed": 1, "recovered": 0}
    assert mutations == ["copy"] and set(remote) == {"original"}
    assert saved["operations"]["copy"]["phase"] == "removed"
    assert items[1]["uid"] == "original"
    assert run() == {"removed": 0, "recovered": 0} and mutations == ["copy"]


def test_failed_prepared_backup_does_not_mutate_provider():
    remote, items, saved, mutations, _, _ = fixture()
    def fail(_): raise OSError("synthetic journal failure")
    with pytest.raises(OSError):
        apply_birthdays(items, list(remote.values()), "calendar", "eds:calendar",
            read_current=remote.get, remove=lambda uid: mutations.append(uid), load_state=lambda: {}, save_state=fail)
    assert mutations == [] and items[1]["uid"] == "copy"


def test_crash_after_remote_delete_resumes_from_durable_prepared_plan():
    remote, items, saved, mutations, run, save = fixture()
    def crash(value):
        if any(operation["phase"] == "removed" for operation in value["operations"].values()):
            raise OSError("synthetic crash after deletion")
        save(value)
    def remove(uid): mutations.append(uid); del remote[uid]
    with pytest.raises(OSError):
        apply_birthdays(items, list(remote.values()), "calendar", "eds:calendar",
            read_current=remote.get, remove=remove, load_state=lambda: {}, save_state=crash)
    assert saved["operations"]["copy"]["phase"] == "prepared" and items[1]["uid"] == "copy"
    assert run() == {"removed": 0, "recovered": 1}
    assert items[1]["uid"] == "original" and mutations == ["copy"]


def test_changed_remote_and_provider_failure_leave_local_identity_unchanged():
    remote, items, saved, mutations, _, save = fixture()
    snapshot = list(remote.values()); remote["copy"] = event("copy", trigger="-PT30M")
    with pytest.raises(ValueError):
        apply_birthdays(items, snapshot, "calendar", "eds:calendar", read_current=remote.get,
            remove=lambda uid: mutations.append(uid), load_state=lambda: {}, save_state=save)
    assert mutations == [] and items[1]["uid"] == "copy"
    remote["copy"] = event("copy", created="20260101T000000Z")
    def denied(_): raise PermissionError("synthetic provider denial")
    with pytest.raises(PermissionError):
        apply_birthdays(items, list(remote.values()), "calendar", "eds:calendar", read_current=remote.get,
            remove=denied, load_state=lambda: {}, save_state=save)
    assert items[1]["uid"] == "copy" and "copy" in remote


def test_wrong_calendar_journal_cannot_rebind_or_delete():
    remote, items, _, mutations, _, _ = fixture()
    with pytest.raises(ValueError):
        apply_birthdays(items, list(remote.values()), "calendar", "eds:calendar", read_current=remote.get,
            remove=lambda uid: mutations.append(uid), load_state=lambda: {"version": 1, "sourceUid": "other", "sourceKey": "eds:other", "operations": {}}, save_state=lambda _: None)
    assert mutations == [] and items[1]["uid"] == "copy"


def test_archive_is_encrypted_source_bound_atomic_and_bounded(tmp_path):
    key = bytes([17]) * 32
    archive = CleanupArchive(tmp_path, "eds:calendar\0epoch", lambda: key)
    assert archive.load() == {} and not archive.exists()
    state = {"version": 1, "sourceUid": "calendar", "sourceKey": "eds:calendar", "operations": {}}
    with archive:
        archive.save(state)
        assert archive.load() == state
        assert b"sourceUid" not in archive.path.read_bytes()
        assert archive.path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(BlockingIOError):
            with CleanupArchive(tmp_path, "eds:calendar\0epoch", lambda: key): pass
        original = archive.path.read_bytes(); archive.MAX_BYTES = 64
        with pytest.raises(ValueError): archive.save(dict(state, extra="x" * 100))
        assert archive.path.read_bytes() == original
    other = CleanupArchive(tmp_path, "eds:other\0epoch", lambda: key)
    other.path.write_bytes(original)
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag): other.load()
