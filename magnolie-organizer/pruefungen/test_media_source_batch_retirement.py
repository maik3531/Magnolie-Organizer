"""#330: live whole-photo-batch backup and source completion."""
import base64
import copy
import os
import struct
import zlib
from hashlib import sha256

import pytest

from test_media_source_batch import pc, source, mappings, receiving, native, select
from test_media_source_batch_sender import prepared, chunks, all_saved, readback
from test_media_source_sender import deliver
from test_media_source_batch_backup import originals
from magnolie_media_source_jobs import _NativeSourceJobs, NativeSourceJobRecord
from magnolie_media_source_retirement import (
    verify_completed_batch_exchange, verified_batch_source_backups, _NativeSourceRetirement, _NativeBatchSourceRetirement,
)
from magnolie_media_source_backup import backup_prepared_batch
from magnolie_media_backups import NativeMediaBackups
from magnolie_file_transfer import TransferError


def test_actual_full_source_exchange_requires_every_original_receipt_origin_and_native_peer_binding(pc,monkeypatch):
    h=pc;batch,cache,sender,offer,accepted,raw=prepared(h)
    chunks(h,sender,cache,accepted,raw);receipt=all_saved(accepted,cache);deliver(h,sender,receipt)
    deliver(h,sender,readback(sender,cache,offer,accepted,receipt))
    ready=_NativeSourceJobs(h.authority).require_version(batch._id,cache._job_version)
    record=sender.observation().body;previous={fid:None for fid in batch._entries}
    local_key=h.authority.identity.receiver_identity_sha256;peer_key=h.authority.current_peer().identity_sha256
    import magnolie_media_offer as offer_codec
    import magnolie_file_saved_message as saved_codec
    from unittest.mock import Mock
    with monkeypatch.context() as scoped:
        parse_offer=Mock(wraps=offer_codec.validate_media_offer)
        parse_saved=Mock(wraps=saved_codec.parse_saved)
        scoped.setattr(offer_codec,'validate_media_offer',parse_offer)
        scoped.setattr(saved_codec,'parse_saved',parse_saved)
        assert verify_completed_batch_exchange(record,ready,local_key,peer_key,previous) is None
        parse_offer.assert_called_once()
        parse_saved.assert_called_once()
    for fault in ('unsent','subset-saved','subset-readback','origin','peer','predecessors','new-offer'):
        changed=copy.deepcopy(record);candidate=ready;expected=copy.deepcopy(previous);peer=peer_key
        if fault=='unsent':changed['sent_bits'][cache.manifest.files[-1].id]=0
        elif fault=='subset-saved':changed['peer_saved']['body']['receipts'].pop()
        elif fault=='subset-readback':changed['peer_readback']['body']['members'].pop(cache.manifest.files[-1].id)
        elif fault=='origin':
            body=ready.body;body['members'][cache.manifest.files[-1].id]['local_origin']['file_key'][1]+=100000
            candidate=NativeSourceJobRecord(ready.version,body)
        elif fault=='peer':peer='0'*64
        elif fault=='predecessors':expected.pop(cache.manifest.files[-1].id)
        else:changed['offer']['message_id']='00000000-0000-4000-8000-000000000001'
        with pytest.raises(TransferError):verify_completed_batch_exchange(changed,candidate,local_key,peer,expected)
    with pytest.raises(TransferError,match='whole_batch_retirement'):_NativeSourceRetirement(sender,None,None)
    assert cache.directory.exists() and all(lease._owned for lease in batch._leases.values())
    sender.close();batch.close()


def test_actual_complete_local_backup_map_is_reverified_under_one_live_batch_book_scope_without_move_rights(pc):
    h=pc;batch,raw=originals(h)
    with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
        selected=backup_prepared_batch(backups,batch)
        with batch.cached_reader() as reader:
            proof=verified_batch_source_backups(backups,selected,batch,reader._permission)
            assert set(proof)==set(batch._entries)
            assert len({v['version_id'] for v in proof.values()})==2
            assert len({v['object_key'] for v in proof.values()})==1 # True raw dedup, not a first-file receipt.
            for changed in ({},dict.fromkeys(selected,next(iter(selected.values())))):
                with pytest.raises(TransferError):verified_batch_source_backups(backups,changed,batch,reader._permission)
        with pytest.raises(TransferError,match='live_lease'):
            verified_batch_source_backups(backups,selected,batch,lambda:True)
    assert batch._cache.directory.exists() and all(lease._owned for lease in batch._leases.values())
    batch.close()


def test_changed_earlier_real_backup_object_during_later_verification_prevents_any_complete_map(pc,monkeypatch):
    import magnolie_media_backup_codec as codec
    h=pc
    raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
    chunk=b'npADx';other=raw[:-12]+struct.pack('>I',1)+chunk+struct.pack('>I',zlib.crc32(chunk))+raw[-12:]
    h.pc_file.write_bytes(raw);(h.pc_file.parent/'other.png').write_bytes(other)
    batch=select(h);batch.freeze_cache()
    with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
        selected=backup_prepared_batch(backups,batch)
        with backups._operation():
            first=backups._record('objects',next(iter(selected.values())).object_key)
        actual=codec.verify_raw;calls=[]
        def edited(fd,size,digest,current,**kwargs):
            result=actual(fd,size,digest,current,**kwargs);calls.append(fd)
            if len(calls)==2:
                # The first independently registered RO descriptor must still
                # be held when the final member has finished its real hash.
                assert os.fstat(calls[0]).st_ino==first['key'][1]
                changed=os.open(first['name'],os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=backups._root)
                try:
                    tail=os.pread(changed,1,first['size']-1);os.pwrite(changed,bytes([tail[0]^1]),first['size']-1);os.fsync(changed)
                finally:os.close(changed)
            return result
        monkeypatch.setattr(codec,'verify_raw',edited)
        with pytest.raises(TransferError,match='original_object_changed'):
            with batch.cached_reader() as reader:verified_batch_source_backups(backups,selected,batch,reader._permission)
        assert len(calls)==2 and batch._root is None
    assert h.pc_file.read_bytes()==raw and (h.pc_file.parent/'other.png').read_bytes()==other
    batch.close()


def test_whole_native_batch_drains_every_original_and_cache_fd_before_one_verified_archive_and_journal_end(pc):
    from magnolie_media_retention import NativeMediaRetention
    from magnolie_media_source_pc import NativeCollectionMediaSource
    from magnolie_media_source_batch import NativeCollectionMediaBatch
    from test_media_source_batch import members
    h=pc;batch,cache,sender,offer,accepted,raw=prepared(h)
    chunks(h,sender,cache,accepted,raw);receipt=all_saved(accepted,cache);deliver(h,sender,receipt)
    deliver(h,sender,readback(sender,cache,offer,accepted,receipt))
    phases=[]
    with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
        selected=backup_prepared_batch(backups,batch)
        def checkpoint(phase):
            phases.append(phase)
            if phase=='source_batch_retirement_moved':
                assert owner._record.body['state']=='archive_planned'
                assert batch._root._fd is None and all(not lease._owned for lease in batch._leases.values())
                assert owner._reader._root is None and owner._reader._parent is None
                with pytest.raises(TransferError,match='reader_retired'):owner._reader.read_chunk(cache.manifest.files[0].id,0)
                with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                    with retention.activity(lambda:True,exclusive=True) as competing:assert competing is None
        owner=_NativeBatchSourceRetirement(sender,backups,selected,boundary=checkpoint)
        ended=owner.run()
        assert ended.body['format']==3 and ended.body['state']=='archived'
        assert set(ended.body['backups'])==set(batch._entries)
        assert phases==['source_batch_retirement_planned','source_batch_retirement_moved','source_batch_retirement_archived']
        assert len(backups.versions())==2
    assert not cache.directory.exists() and (cache.directory.parent/ended.body['archive']).is_dir()
    assert batch._root is None and batch._catalog is None and h.source._closed.is_set()
    assert all((h.pc_file.parent/e['path']).read_bytes()==raw for e in batch._entries.values())
    assert not ended.permits_slot_reuse and not ended.permits_deletion
    with pytest.raises(TransferError):owner.run()
    # A historical query is DATA, not a new reader. Resolve BOTH distinct
    # publication receipts by their actual origins, never manifest.files[0].
    jobs=_NativeSourceJobs(h.authority)
    for file in cache.manifest.files:
        previous=jobs.completed_pc_origin(batch._entries[file.id]['local_origin'])
        assert previous.publication_sha256==sha256(file.id.encode()).hexdigest()
        assert previous.ready_version==cache._job_version and previous.retirement_version==ended.version
    # One fresh native action AFTER the completed original batch may select a
    # new whole batch. The unchanged member must keep its own old publication.
    extra=b'npADy';changed=raw[:-12]+struct.pack('>I',1)+extra+struct.pack('>I',zlib.crc32(extra))+raw[-12:]
    h.pc_file.write_bytes(changed)
    h.source=NativeCollectionMediaSource(h.preferences,h.mappings,h.controller)
    chosen=tuple(m for m in members(h) if m.name in (h.pc_file.name,'second.png'))
    successor=select(h,chosen)
    assert type(successor) is NativeCollectionMediaBatch and len(successor._selections)==2
    next_cache=successor.freeze_cache()
    ready=jobs.require_version(successor._id,next_cache._job_version)
    old_by_origin={e['local_origin']['file_path']:sha256(fid.encode()).hexdigest() for fid,e in batch._entries.items()}
    assert {e['path']:ready.body['predecessors'][fid]['publication_sha256'] for fid,e in successor._entries.items()}==old_by_origin
    assert (cache.directory.parent/ended.body['archive']).is_dir() and next_cache.directory.is_dir()
    successor.close()


@pytest.mark.parametrize('interrupted_at', ['source_batch_retirement_planned', 'source_batch_retirement_moved'])
def test_interrupted_batch_end_requires_fresh_local_recovery_without_resend(pc, interrupted_at, monkeypatch):
    from magnolie_media_source_pc import NativeCollectionMediaSource
    from magnolie_media_source_recovery import _NativeBatchSourceRetirementRecovery, recover_pending_pc_source_end
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal

    h = pc
    batch, cache, sender, offer, accepted, raw = prepared(h)
    chunks(h, sender, cache, accepted, raw)
    receipt = all_saved(accepted, cache)
    deliver(h, sender, receipt)
    deliver(h, sender, readback(sender, cache, offer, accepted, receipt))

    def interrupt(phase):
        if phase == interrupted_at:
            raise OSError('simulated interruption after durable checkpoint')

    with NativeMediaBackups(h.selected.directory, h.authority.protection, lambda: True, create=True) as backups:
        selected = backup_prepared_batch(backups, batch)
        owner = _NativeBatchSourceRetirement(sender, backups, selected, boundary=interrupt)
        with pytest.raises(OSError, match='simulated interruption'):
            owner.run()
        assert len(backups.versions()) == len(cache.manifest.files)

    jobs = _NativeSourceJobs(h.authority)
    journal = _NativeSourceRetirementJournal(jobs)
    pending = journal.lookup(batch._id)
    assert pending.body['format'] == 3 and pending.body['state'] == 'archive_planned'
    assert set(pending.body['backups']) == set(batch._entries)
    assert cache.directory.is_dir() == (interrupted_at == 'source_batch_retirement_planned')
    assert (cache.directory.parent / pending.body['archive']).is_dir() == (interrupted_at == 'source_batch_retirement_moved')
    assert batch._root is None and batch._catalog is None
    assert all((h.pc_file.parent / entry['path']).read_bytes() == raw for entry in batch._entries.values())

    h.source = NativeCollectionMediaSource(h.preferences, h.mappings, h.controller)
    with pytest.raises(TransferError, match='pending_job'):
        select(h)
    # A denied preparation retires its owner; it must not be reused for END.
    assert h.source._original_batch is not None
    h.source.close()
    assert journal.lookup(batch._id) == pending
    h.source = NativeCollectionMediaSource(h.preferences, h.mappings, h.controller)

    wire = (h.channel.send_seq, h.channel.receive_seq)
    unseal = h.authority.protection.unseal

    def metadata_only(cipher, domain):
        assert '/chunk-' not in domain
        return unseal(cipher, domain)

    monkeypatch.setattr(h.authority.protection, 'unseal', metadata_only)
    with NativeMediaBackups(h.selected.directory, h.authority.protection, lambda: True) as backups:
        subset = dict(selected)
        subset.pop(next(iter(subset)))
        incomplete = _NativeBatchSourceRetirementRecovery(h.source, batch._id, pending.version, backups, subset)
        with pytest.raises(TransferError, match='original_job_required'):
            incomplete.run(h.preferences.issue_action(), h.preferences.read())
        assert journal.lookup(batch._id) == pending

    ended = recover_pending_pc_source_end(h.source, lambda: True, ('images',))
    assert ended.body == dict(pending.body, state='archived')
    assert recover_pending_pc_source_end(h.source, lambda: True, ('images',)) is None

    assert (h.channel.send_seq, h.channel.receive_seq) == wire
    assert not cache.directory.exists() and (cache.directory.parent / ended.body['archive']).is_dir()
    assert not h.source._prepared and h.source._original_batch is None
    for file_id, entry in batch._entries.items():
        previous = jobs.completed_pc_origin(entry['local_origin'])
        assert previous.publication_sha256 == sha256(file_id.encode()).hexdigest()
        assert (h.pc_file.parent / entry['path']).read_bytes() == raw
    h.source.close()
