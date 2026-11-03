"""Completed private cache capacity is separate from immutable save history."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog, NativeJobCatalogLimits
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, reconnect
from test_photo_mappings import save


def test_saved_cache_retirement_frees_active_budget_but_keeps_photo_mapping_and_original_index(receiving):
    connection = receiving[3]; receiver, _, association = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original = receiver.job; receipts = receiver._index.saved_receipts()
    mapping = connection._mappings.lookup((association,)); history = receiver._index.media_history
    target = receiving[4] / receipts[0].relative_path
    before = (target.stat().st_ino, target.read_bytes())
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    retired = connection._catalog.jobs()[0]
    assert retired.owner == original.owner and retired.accepted == original.accepted
    assert retired.protected_record_sha256 == original.protected_record_sha256
    assert original.reserved_bytes > 0 and retired.reserved_bytes == 0 and retired.cache_retirement_sha256
    assert (target.stat().st_ino, target.read_bytes()) == before
    assert connection._mappings.lookup((association,)) == mapping
    assert not (Path(connection._authority.binding.native_directory) / ('file-transfer-' + original.owner)).exists()
    assert not (receiving[4] / ('.magnolie-publication-' + original.owner)).exists()
    with pytest.raises(TransferError): connection._catalog.require_reserved(retired)
    with reconnect(receiving) as fresh:
        from test_file_desktop_sources import status
        from magnolie_file_receive import NativeFileReceiveOperation
        status(fresh)
        fresh[3]._open_catalog(allow_create=False)
        assert fresh[3]._catalog.jobs() == (retired,)
        protection = fresh[3]._authority.protection
        assert NativeFileReceiveOperation.read_media_history(fresh[3]._catalog, retired, fresh[3]._receive_binding,
            protection.seal, protection.unseal) == history
        assert NativeFileReceiveOperation.read_saved_receipts(fresh[3]._catalog, retired, fresh[3]._receive_binding,
            protection.seal, protection.unseal) == receipts
        from dataclasses import replace
        from test_file_desktop_sources import ready_source
        from test_file_desktop_media import collect, send_offer, dispatch
        ready_source(fresh)
        old = original.accepted.manifest
        full = replace(old, source_id='8' * 32, transfer_id='9' * 32, files=(replace(old.files[0], id='a' * 32),))
        collect(fresh, full); offered, result = send_offer(fresh, full); dispatch(fresh, result)
        assert fresh[3].review_pending_photos(fresh[3].issue_receive_action()).nothing_to_download
        assert fresh[3]._run is None and fresh[3]._catalog.jobs() == (retired,)


def test_unknown_owned_cache_entry_preserves_reservation_and_never_deletes_user_target(receiving):
    connection = receiving[3]; receiver, _, association = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original = receiver.job; target = receiving[4] / receiver._index.saved_receipts()[0].relative_path
    stage = Path(connection._authority.binding.native_directory) / ('file-transfer-' + original.owner)
    foreign = stage / 'keep-unknown.txt'; foreign.write_bytes(b'preserve unfamiliar bytes')
    with pytest.raises(TransferError): connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    assert connection._catalog.jobs() == (original,)
    assert original.reserved_bytes > 0 and connection._run is not None
    assert foreign.read_bytes() == b'preserve unfamiliar bytes' and target.read_bytes() == b'hello'


def test_retired_metadata_does_not_exhaust_a_single_active_job_slot(receiving, monkeypatch):
    original_init = ProtectedTransferJobCatalog.__init__
    def initialize(self, *args, **kwargs):
        if kwargs.get('create'):
            kwargs['limits'] = NativeJobCatalogLimits(max_jobs=1)
        original_init(self, *args, **kwargs)
    monkeypatch.setattr(ProtectedTransferJobCatalog, '__init__', initialize)
    connection = receiving[3]; receiver, _, _ = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    original = receiver.job
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    from dataclasses import replace
    from magnolie_file_acceptance import NativeAcceptedTransfer
    manifest = replace(original.accepted.manifest, transfer_id='e' * 32, source_id='f' * 32)
    accepted = NativeAcceptedTransfer.capture(manifest, original.accepted.binding, dict(original.accepted.targets),
        original.accepted.destination.path, connection._receive_binding)
    next_job = connection._catalog.reserve(accepted, connection._receive_binding)
    assert next_job.reserved_bytes > 0 and next_job.owner != original.owner
    assert len(connection._catalog.jobs()) == 2
    assert sum(job.cache_retirement_sha256 is None for job in connection._catalog.jobs()) == 1


@pytest.mark.parametrize('change', ['missing_receipt', 'reappeared_cache'])
def test_fresh_catalog_rejects_missing_retirement_proof_or_reappeared_owned_cache(receiving, change):
    connection = receiving[3]; receiver, _, _ = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action()); owner = receiver.job.owner
    connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    parent = Path(connection._authority.binding.native_directory)
    if change == 'missing_receipt':
        (parent / ProtectedTransferJobCatalog.NAME / ('cache-retired-' + owner + '.enc')).unlink()  # Fixture loss only.
    else:
        foreign = parent / ('file-transfer-' + owner); foreign.mkdir(mode=0o700)
        (foreign / 'keep.txt').write_bytes(b'foreign bytes remain')
    connection._catalog.close()
    protection = connection._authority.protection
    with pytest.raises(TransferError):
        ProtectedTransferJobCatalog(parent, connection._authority.identity, protection.seal, protection.unseal)
    assert (receiving[4] / 'Camera/photo0.jpg').read_bytes() == b'hello'
    if change == 'reappeared_cache': assert (foreign / 'keep.txt').read_bytes() == b'foreign bytes remain'


def test_failed_retirement_membership_commit_never_reports_freed_budget(receiving, monkeypatch):
    connection = receiving[3]; receiver, _, _ = save(receiving, publish=False)
    connection.publish_received(connection.issue_receive_action())
    def fail(*args, **kwargs): raise OSError('fixture retirement aggregate commit failed')
    monkeypatch.setattr(connection._catalog._registry, 'commit', fail)
    with pytest.raises(OSError): connection.finish_saved_receive(connection.issue_receive_action(), retire_cache=True)
    assert connection._run is not None and connection._catalog._failed
    with pytest.raises(TransferError): connection._catalog.jobs()
    assert (receiving[4] / 'Camera/photo0.jpg').read_bytes() == b'hello'
