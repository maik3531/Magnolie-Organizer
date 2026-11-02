"""No sleeps, background workers, personal settings or automatic filesystem I/O."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import NativeTransferBinding, TransferError
from magnolie_photo_schedule import NativePhotoRun, NativePhotoSyncScope, PhotoSyncSchedule


class Fixture:
    def __init__(self):
        self.now = 100
        self.scope = NativePhotoSyncScope(NativeTransferBinding("sender_fixture_01", "receiver_fixture_01",
            "d" * 64, "e" * 64, "f" * 64, "0" * 64), "a" * 64, object())
        self.reads = 0
        self.schedule = PhotoSyncSchedule(self.current, lambda: self.now)

    def current(self):
        self.reads += 1
        return self.scope


def test_manual_default_does_not_read_sources_or_schedule_anything_and_sync_now_reuses_progress():
    f = Fixture()
    assert f.schedule.mode == "manual" and f.schedule.active is None and f.reads == 0
    assert f.schedule.cancellation_requested(None)
    f.schedule.hint_changed()
    assert f.schedule.take_due() is None and f.reads == 0
    run = f.schedule.request_now()
    assert run.trigger == "manual" and f.schedule.active is run
    assert f.schedule.request_now() is run
    assert not f.schedule.cancellation_requested(run)
    assert f.schedule.finished(run)
    assert f.schedule.take_due() is None and f.schedule.active is None


def test_explicit_automatic_runs_are_bounded_coalesced_and_never_overlap():
    f = Fixture()
    f.schedule.set_mode("automatic")
    first = f.schedule.take_due()
    assert first.trigger == "automatic"
    for _ in range(20):
        f.schedule.hint_changed()
        assert f.schedule.take_due() is None and f.schedule.request_now() is first
    assert f.schedule.finished(first)
    assert f.schedule.take_due() is None
    f.now += 999
    assert f.schedule.take_due() is None
    f.now += 1
    second = f.schedule.take_due()
    assert second is not first and f.schedule.active is second
    assert f.schedule.finished(second)
    f.now += PhotoSyncSchedule.INTERVAL_MS - 1
    assert f.schedule.take_due() is None
    f.now += 1
    assert f.schedule.take_due() is not None


def test_automatic_to_manual_stops_repeats_without_resetting_or_cancelling_accepted_work():
    f = Fixture()
    f.schedule.set_mode("automatic")
    run = f.schedule.take_due()
    original = run.scope
    f.schedule.hint_changed()
    f.schedule.set_mode("manual")
    assert f.schedule.active is run and not f.schedule.cancellation_requested(run)
    assert run.scope is original
    assert f.schedule.finished(run)
    f.now += 10 * PhotoSyncSchedule.INTERVAL_MS
    f.schedule.hint_changed()
    assert f.schedule.take_due() is None
    assert f.schedule.request_now().trigger == "manual"


def test_offline_revocation_scope_changes_request_cancel_but_hold_active_until_real_worker_end():
    for change in ("offline", "owner", "key", "permission", "source", "destination"):
        f = Fixture()
        f.schedule.set_mode("automatic")
        run = f.schedule.take_due()
        old = f.scope
        if change == "offline":
            f.scope = None
        elif change == "owner":
            f.scope = replace(old, owner=object())
        elif change == "source":
            f.scope = replace(old, source_epoch="b" * 64)
        else:
            field = {"key": "sender_identity_sha256", "permission": "permission_epoch", "destination": "destination_token"}[change]
            f.scope = replace(old, binding=replace(old.binding, **{field: "b" * 64}))
        assert f.schedule.cancellation_requested(run)
        assert f.schedule.take_due() is None and f.schedule.active is run
        assert f.schedule.request_now() is run  # The caller displays cancellation/progress, not a second run.
        assert f.schedule.finished(run)
        if change == "offline":
            f.now += PhotoSyncSchedule.INTERVAL_MS
            assert f.schedule.take_due() is None
            with pytest.raises(TransferError, match="not_ready"):
                f.schedule.request_now()
            f.scope = old
            assert f.schedule.take_due() is not None


def test_forged_duplicate_and_late_end_callbacks_cannot_release_another_native_run():
    f = Fixture()
    first = f.schedule.request_now()
    forged = NativePhotoRun(first.id, first.scope, first.trigger)
    assert not f.schedule.finished(forged) and f.schedule.active is first
    assert f.schedule.cancellation_requested(forged)
    assert f.schedule.finished(first) and not f.schedule.finished(first)
    second = f.schedule.request_now()
    assert not f.schedule.finished(first) and f.schedule.active is second


def test_close_requests_cancellation_but_does_not_fabricate_worker_completion():
    f = Fixture()
    run = f.schedule.request_now()
    f.schedule.close()
    assert f.schedule.active is run and f.schedule.cancellation_requested(run)
    with pytest.raises(TransferError, match="closed"):
        f.schedule.request_now()
    assert f.schedule.finished(run) and f.schedule.active is None
    assert not f.schedule.finished(run)


def test_invalid_modes_and_monotonic_clock_rollback_do_not_enable_background_work():
    f = Fixture()
    for mode in (True, "auto", None, ""):
        with pytest.raises(TransferError, match="invalid_mode"):
            f.schedule.set_mode(mode)
    assert f.schedule.mode == "manual"
    run = f.schedule.request_now()
    f.now -= 1
    with pytest.raises(TransferError, match="clock_changed"):
        f.schedule.finished(run)
    assert f.schedule.active is run
