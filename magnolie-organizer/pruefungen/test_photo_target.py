"""Actual protected receipts and destination bytes; no synthetic save authority."""
from hashlib import sha256
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_file_transfer import CHUNK_BYTES, MAX_FILE_BYTES, TransferError
from magnolie_photo_plan import (NativePhotoAssociation, NativePhotoBaseline, NativePhotoObservation,
    PhotoContentWitness, compare_photo)
from test_file_saved_receipts import fixture
from test_file_receive import feed
from magnolie_file_acceptance import NativeAcceptedTransfer
from test_file_transfer_stage import description


def saved(f, data=b'hello'):
    operation = f.accept(data)
    feed(operation, data)
    operation.publish_completed()
    receipt = operation.commit_saved_receipts()[0]
    return operation, receipt, f.destination/receipt.relative_path

def test_historical_backup_target_is_unknown_without_reading_payload_or_proving_deletion(fixture,monkeypatch):
    f=fixture;data=b'old original backup'
    folder=f.destination/'Backup'/'deep';folder.mkdir(parents=True,mode=0o700)
    (f.destination/'Backup').chmod(0o700)
    manifest=description(data)
    accepted=NativeAcceptedTransfer.capture(manifest,f.binding,{file.id:'Backup/deep/photo.jpg' for file in manifest.files},f.destination,lambda:f.current)
    op=f.accept(data,accepted=accepted);feed(op,data);op.publish_completed();receipt=op.commit_saved_receipts()[0]
    target=f.destination/receipt.relative_path
    before=op._index._db.execute('SELECT file_id,payload FROM receipts').fetchall()
    original=os.read;reads=[]
    def read(fd,count):
        value=os.fstat(fd)
        if (value.st_dev,value.st_ino)==receipt.file_key:reads.append(fd)
        return original(fd,count)
    monkeypatch.setattr(os,'read',read)
    observed=op.observe_saved_photo(receipt.file_id).observation
    assert observed.state=='unknown' and observed.content is None and not observed.managed and reads==[]
    association=NativePhotoAssociation(op.job.accepted.binding,'a'*64,'b'*64,'c'*64)
    baseline=NativePhotoBaseline(association,PhotoContentWitness(receipt.sha256,receipt.size),receipt.protected_record_sha256)
    assert compare_photo(association,baseline,NativePhotoObservation('deleted'),observed).kind=='pause_unknown'
    assert op._index._db.execute('SELECT file_id,payload FROM receipts').fetchall()==before and target.read_bytes()==data


@pytest.mark.parametrize('data', [b'hello', b''])
def test_observation_reads_real_bytes_from_original_receipted_target_without_rewriting_history(fixture, data):
    op, receipt, target = saved(fixture, data)
    metadata = op._index._db.execute('SELECT file_id,payload FROM receipts').fetchall()
    result = op.observe_saved_photo(receipt.file_id)
    assert result.file_id == receipt.file_id and result.saved_record_sha256 == receipt.protected_record_sha256
    assert result.observation.state == 'present' and result.observation.managed
    assert result.observation.content == PhotoContentWitness(sha256(data).hexdigest(), len(data))
    assert not result.is_saved_receipt and not result.grants_write_authority
    assert op._index._db.execute('SELECT file_id,payload FROM receipts').fetchall() == metadata
    assert target.read_bytes() == data


def test_later_pc_crop_is_actual_new_content_and_planner_preserves_it(fixture):
    op, receipt, target = saved(fixture)
    target.write_bytes(b'user crop')
    result = op.observe_saved_photo(receipt.file_id)
    assert result.observation.managed and result.observation.content.sha256 == sha256(b'user crop').hexdigest()
    association = NativePhotoAssociation(op.job.accepted.binding, 'a'*64, 'b'*64, 'c'*64)
    common = PhotoContentWitness(receipt.sha256, receipt.size)
    baseline = NativePhotoBaseline(association, common, receipt.protected_record_sha256)
    proposal = compare_photo(association, baseline, NativePhotoObservation('present', common, insertion_proven=True), result.observation)
    assert proposal.kind == 'keep_local_edit' and not proposal.grants_write_authority
    assert op._index.saved_receipts() == (receipt,) and target.read_bytes() == b'user crop'


def test_equal_bytes_in_replacement_inode_are_not_adopted_as_managed(fixture):
    op, receipt, target = saved(fixture)
    target.rename(target.with_name('held-original.jpg'))
    target.write_bytes(b'hello'); target.chmod(0o600)
    observed = op.observe_saved_photo(receipt.file_id).observation
    assert observed.state == 'present' and not observed.managed
    assert observed.content.sha256 == receipt.sha256
    assert op._index.saved_receipts() == (receipt,)


@pytest.mark.parametrize('change', ['file', 'parent'])
def test_missing_file_or_album_is_not_a_deletion_tombstone(fixture, change):
    op, receipt, target = saved(fixture)
    if change == 'file': target.unlink()
    else: target.parent.rename(target.parent.with_name('user-moved-album'))
    result = op.observe_saved_photo(receipt.file_id)
    assert result.observation.state == 'missing' and not result.observation.managed
    assert result.observation.content is None
    assert op._index.saved_receipts() == (receipt,)


@pytest.mark.parametrize('change', ['symlink', 'fifo', 'permissions', 'parent-replaced', 'oversized'])
def test_unsafe_or_replaced_native_objects_remain_unknown_without_reading_or_adopting_them(fixture, change):
    op, receipt, target = saved(fixture)
    held = target.with_name('held-original.jpg')
    if change in ('symlink', 'fifo'):
        target.rename(held)
        if change == 'symlink': target.symlink_to(held)
        else: os.mkfifo(target, 0o600)
    elif change == 'permissions': target.chmod(0o644)
    elif change == 'parent-replaced':
        target.parent.rename(target.parent.with_name('held-album'))
        target.parent.mkdir(mode=0o700)
        target.write_bytes(b'hello'); target.chmod(0o600)
    else:
        with target.open('r+b') as out: out.truncate(MAX_FILE_BYTES+1)
    result = op.observe_saved_photo(receipt.file_id)
    assert result.observation.state == 'unknown'
    assert op._index.saved_receipts() == (receipt,)


@pytest.mark.parametrize('change', ['edit', 'replace', 'revoke'])
def test_actual_read_races_cannot_return_stale_valid_content_or_hide_revocation(fixture, monkeypatch, change):
    f = fixture
    op, receipt, target = saved(f, b'x'*(CHUNK_BYTES+1))
    original = os.read; changed = False
    def read(fd, count):
        nonlocal changed
        data = original(fd, count)
        value = os.fstat(fd)
        if not changed and (value.st_dev, value.st_ino) == receipt.file_key:
            changed = True
            if change == 'revoke': f.current = None
            elif change == 'replace':
                target.rename(target.with_name('held-original.jpg'))
                target.write_bytes(b'x'*(CHUNK_BYTES+1)); target.chmod(0o600)
            else: target.write_bytes(b'y'*(CHUNK_BYTES+1))
        return data
    monkeypatch.setattr(os, 'read', read)
    if change == 'revoke':
        with pytest.raises(TransferError): op.observe_saved_photo(receipt.file_id)
    else:
        assert op.observe_saved_photo(receipt.file_id).observation.state == 'unknown'
    assert changed


def test_receiver_requires_fresh_protected_save_receipt_and_rechecks_it_after_target_io(fixture, monkeypatch):
    op = fixture.accept()
    file_id = op.job.accepted.manifest.files[0].id
    with pytest.raises(TransferError, match='receipt_required'): op.observe_saved_photo(file_id)
    feed(op, b'hello'); op.publish_completed(); receipt = op.commit_saved_receipts()[0]
    read = op._index.saved_receipts; calls = []
    def receipts():
        calls.append(1)
        return read() if len(calls) == 1 else ()
    monkeypatch.setattr(op._index, 'saved_receipts', receipts)
    with pytest.raises(TransferError, match='receipt_changed'): op.observe_saved_photo(file_id)
    assert len(calls) == 2 and receipt.file_id == file_id


def test_reopened_saved_job_reads_current_target_instead_of_old_snapshot_bytes(fixture):
    f = fixture
    op, receipt, target = saved(f)
    job = op.job
    op.close()
    target.write_bytes(b'edited after native restart')
    reopened = f.resume(job)
    result = reopened.observe_saved_photo(receipt.file_id)
    assert result.observation.managed
    assert result.observation.content.sha256 == sha256(b'edited after native restart').hexdigest()
    assert reopened._index.saved_receipts() == (receipt,)


def test_unknown_member_or_closed_native_worker_cannot_read_a_target(fixture):
    op, receipt, target = saved(fixture)
    with pytest.raises(TransferError, match='receipt_required'): op.observe_saved_photo('f'*32)
    op.close()
    with pytest.raises(TransferError): op.observe_saved_photo(receipt.file_id)
    assert target.read_bytes() == b'hello'
