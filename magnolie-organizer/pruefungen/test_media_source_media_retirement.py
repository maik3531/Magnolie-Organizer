"""Media readback does not replace actual native drain or independent backup."""
from dataclasses import replace
import threading
import pytest

from test_media_source_media_offer import source, native, receiving, mappings, media_offered, chunks, saved, deliver, readback, png, freeze
from test_media_source_retirement import archive_path
from test_media_source_backup import open_backup, restore
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_reader import _NativeSourceCacheReader
from magnolie_media_retention import NativeMediaRetention
from magnolie_file_transfer import TransferError


def completed(h,*,publish=True):
    sender,cached,offer=media_offered(h);accepted=chunks(h,sender,cached,offer)
    deliver(h,sender,saved(accepted,cached))
    if publish:deliver(h,sender,readback(sender,cached,offer))
    return sender,cached,offer


def test_actual_media_readback_and_verified_backup_archive_all_original_bytes_then_allow_fresh_explicit_preparation(source,tmp_path):
    h=source;sender,cached,_=completed(h)
    try:
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            before={p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()}
            result=_NativeSourceRetirement(sender,backups,version).run();archive=archive_path(h,sender,cached)
            assert result.body['state']=='archived' and not cached.directory.exists()
            assert (archive.stat().st_dev,archive.stat().st_ino)==cached.root_key
            assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
            assert not result.grants_read_authority and not result.is_saved_receipt and not result.permits_deletion and not result.permits_slot_reuse
            with pytest.raises(TransferError,match='prepared_owner_required'):
                with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Archived media cache regained READ')
            h.target.write_bytes(png(1));second=freeze(h)
            assert second.manifest.source_id!=cached.manifest.source_id and second.root_key!=cached.root_key
            assert second.manifest.files[0].sha256!=cached.manifest.files[0].sha256
            restore(backups,version,tmp_path/'retained-first-version.png')
            assert (tmp_path/'retained-first-version.png').read_bytes()==png()
            assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
    finally:sender.close()


@pytest.mark.parametrize('fault',['saved_only','copied_metadata','stale_backup'])
def test_media_completion_metadata_without_readback_native_owner_or_exact_backup_cannot_archive(source,fault):
    h=source;sender,cached,_=completed(h,publish=fault!='saved_only')
    try:
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            if fault=='copied_metadata':
                with pytest.raises(TransferError,match='native_completed_owner_required'):_NativeSourceRetirement(sender.observation(),backups,version)
            else:
                if fault=='stale_backup':version=replace(version,record_sha256='f'*64)
                owner=_NativeSourceRetirement(sender,backups,version)
                with pytest.raises(TransferError):owner.run()
                assert owner._journal.lookup(sender._job) is None
            assert cached.directory.exists() and not archive_path(h,sender,cached).exists() and h.target.read_bytes()==png()
    finally:sender.close()


def test_peer_readback_committed_while_actual_reader_is_still_draining_cannot_start_native_archive(source,monkeypatch):
    h=source;sender,cached,offer=completed(h,publish=False)
    entered=threading.Event();release=threading.Event();errors=[];verify=_NativeSourceCacheReader.verify
    try:
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            def blocked(reader):
                if threading.current_thread().name=='media-readback-drain-proof':
                    entered.set();assert release.wait(8)
                return verify(reader)
            monkeypatch.setattr(_NativeSourceCacheReader,'verify',blocked)
            def receive():
                try:deliver(h,sender,readback(sender,cached,offer))
                except BaseException as error:errors.append(error)
            worker=threading.Thread(target=receive,name='media-readback-drain-proof');worker.start()
            owner=_NativeSourceRetirement(sender,backups,version)
            try:
                assert entered.wait(5) and sender.observation().body['phase']=='peer_readback'
                with pytest.raises(TransferError,match='sender_busy'):owner.run()
                with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                    with retention.activity(lambda:True) as permit:assert permit is None
                assert cached.directory.exists() and not archive_path(h,sender,cached).exists()
            finally:release.set();worker.join(10)
            assert not worker.is_alive() and not errors
            result=owner.run();assert result.body['state']=='archived' and archive_path(h,sender,cached).exists()
    finally:release.set();sender.close()
