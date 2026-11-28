"""Refs #330: actual local whole-source backup under one native book/cache IO."""
import base64
from pathlib import Path
import pytest

from test_media_source_batch import pc, source, mappings, receiving, native, select
from magnolie_media_backups import NativeMediaBackups
from magnolie_media_source_backup import backup_prepared_batch, source_provenance
from magnolie_file_transfer import TransferError


def originals(h):
    raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
    h.pc_file.write_bytes(raw);directory=h.pc_file.parent/'day';directory.mkdir(mode=0o700)
    (directory/h.pc_file.name).write_bytes(raw)
    batch=select(h);batch.freeze_cache();return batch,raw


def test_actual_all_member_local_backups_pin_same_original_root_and_reuse_verified_content_not_native_rights(pc,monkeypatch):
    import magnolie_media_source_backup as source_backup
    from magnolie_media_source_jobs import _NativeSourceJobs

    h=pc;batch,raw=originals(h)
    ready=_NativeSourceJobs(h.authority).require_version(batch._id,batch._cache._job_version)
    expected={f.id:source_backup.batch_source_provenance_ready(ready,f) for f in batch._cache.manifest.files}
    canonical=source_backup.canonical;aggregates=[]

    def observe(value):
        if type(value) is dict and set(value)=={'members','predecessors'}:aggregates.append(True)
        return canonical(value)

    monkeypatch.setattr(source_backup,'canonical',observe)
    with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
        result=backup_prepared_batch(backups,batch)
        assert aggregates==[True]
        assert set(result)==set(batch._entries) and len(result)==2
        assert len({v.id for v in result.values()})==2 and len({v.object_key for v in result.values()})==1
        assert len(backups.versions())==2
        sources={fid:source_provenance(backups,v) for fid,v in result.items()}
        assert sources==expected
        assert len({s['batch_members_sha256'] for s in sources.values()})==1
        for fid,value in sources.items():
            assert value['format']==3 and value['job_id']==batch._id
            assert value['manifest_sha256']==batch._cache.manifest.fingerprint
            assert value['file']['id']==fid and value['file']['path']==batch._entries[fid]['path']
            assert value['local_origin']==batch._entries[fid]['local_origin']
            with pytest.raises(TransferError,match='pc_restore_publication_owner_required'):backups._restore_lineage(result[fid])
        assert backup_prepared_batch(backups,batch)==result  # Same versions, no fresh grants or clocks.
        assert aggregates==[True,True]
        assert len(backups.versions())==2
    assert all((h.pc_file.parent/e['path']).read_bytes()==raw for e in batch._entries.values())
    assert batch._cache.directory.exists();batch.close()


@pytest.mark.parametrize('stop,recoverable',[
    ('source_backup_intent_durable',False),
    ('source_backup_payload_verified',True),
],ids=['intent-only','verified-payload'])
def test_original_batch_backup_expiry_never_completes_a_version_or_moves_the_cache(pc,monkeypatch,stop,recoverable):
    h=pc;tick=[1000]
    monkeypatch.setattr(h.preferences,'_clock',lambda:tick[0])
    batch,raw=originals(h);phases=[]
    first=batch._cache.manifest.files[0]

    def expire(phase):
        phases.append(phase)
        if phase==stop:tick[0]+=60_000

    try:
        with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
            with pytest.raises(TransferError,match='photo_destination_action_not_current'):
                backup_prepared_batch(backups,batch,boundary=expire)
            assert phases[-1]==stop and 'source_backup_complete' not in phases
            assert backups.versions()==()
            assert len(backups._pending_members())==1
            pending=backups.pending_recovery_versions()
            assert len(pending)==int(recoverable)
            if recoverable:
                assert source_provenance(backups,pending[0])['file']['id']==first.id
        assert batch._cache.directory.is_dir()
        assert all((h.pc_file.parent/e['path']).read_bytes()==raw for e in batch._entries.values())
        assert batch._root is None and all(not lease._owned for lease in batch._leases.values())
    finally:batch.close()


def test_cancel_during_actual_backup_object_write_keeps_original_fds_and_native_book_until_io_finishes(pc,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import os
    import threading
    from magnolie_media_retention import NativeMediaRetention
    h=pc;batch,raw=originals(h);entered=threading.Event();release=threading.Event();actual=os.write;held={}
    def blocked(fd,data):
        name=os.path.basename(os.readlink('/proc/self/fd/%d'%fd))
        if name.startswith('object-') and name.endswith('.raw'):
            held['fd']=fd;entered.set();assert release.wait(5)
        return actual(fd,data)
    monkeypatch.setattr(os,'write',blocked)
    with NativeMediaBackups(h.selected.directory,h.authority.protection,lambda:True,create=True) as backups:
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempt=pool.submit(backup_prepared_batch,backups,batch)
            try:
                assert entered.wait(15);batch.close()
                assert not attempt.done() and h.source._gate.locked()
                os.fstat(held['fd'])
                for lease in batch._leases.values():os.fstat(lease._owned[-1])
                with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                    with retention.activity(lambda:True,exclusive=True) as competing:assert competing is None
            finally:release.set()
            with pytest.raises(TransferError):attempt.result(timeout=15)
        assert backups.versions()==()
    assert batch._root is None and all(not lease._owned for lease in batch._leases.values())
    assert all((h.pc_file.parent/e['path']).read_bytes()==raw for e in batch._entries.values())
