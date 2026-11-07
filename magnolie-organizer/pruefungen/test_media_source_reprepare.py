"""Actual fresh original descriptor preparation, not a metadata READ shortcut."""
import os
import sqlite3
import threading

import pytest
from cryptography.exceptions import InvalidTag

from test_media_source import source,inspect
from test_media_source_cache import freeze
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_retirement import completed
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_reprepare import _NativeSourceRepreparation
from magnolie_media_retention import NativeMediaRetention
from magnolie_file_transfer import TransferError


def reprepare(h,owner,cached):
    return owner.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
        cached.manifest.source_id,cached._job_version)


def metadata(h):
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        return db.execute("SELECT key,value FROM meta WHERE key GLOB 'native_media_source_*' ORDER BY key").fetchall()


def test_new_native_owner_reprepares_only_after_actual_full_original_read_and_keeps_old_readers_retired(source,monkeypatch):
    h=source;cached=freeze(h);job=cached.manifest.source_id
    with h.source.prepared_cache(job) as old:assert old.read_chunk(0)==b'hello'
    h.source.close();before=metadata(h);bytes_before={p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()}
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller);pread=os.pread;reads=[]
    def observed(fd,size,offset):
        value=os.fstat(fd)
        if (value.st_dev,value.st_ino)==h.record.file_key:reads.append((size,offset))
        return pread(fd,size,offset)
    monkeypatch.setattr(os,'pread',observed)
    try:
        with pytest.raises(TransferError,match='prepared_owner_required'):
            with fresh.prepared_cache(job):pytest.fail('New owner read from metadata only')
        renewed=reprepare(h,fresh,cached)
        assert renewed==cached and not renewed.grants_read_authority and not renewed.is_saved_receipt
        assert reads==[(5,0),(1,5)] # Real full original read plus guarded EOF.
        with fresh.prepared_cache(job) as reader:
            assert reader.read_chunk(0)==b'hello'
            with pytest.raises(TransferError):old.read_chunk(0)
        with pytest.raises(TransferError):old.read_chunk(0)
        assert metadata(h)==before and {p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()}==bytes_before
        assert not h.preferences.local_grant(True).grants.send_files
    finally:fresh.close()


def test_observations_and_job_metadata_cannot_call_repreparation_completion_without_actual_live_original_read(source):
    h=source;observed=inspect(h);cached=freeze(h);fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        plan=_NativeSourceRepreparation(fresh,cached.manifest.source_id,cached._job_version,'images')
        with pytest.raises(TransferError,match='actual_original_read_required'):
            plan.complete(h.record,observed,cached._book_version,lambda:True)
        assert fresh._prepared=={} and cached.directory.exists()
    finally:fresh.close()


@pytest.mark.parametrize('change',['edited','replacement','hardlink','missing','cipher','cipher_inode','unknown_child','missing_job'])
def test_repreparation_never_promotes_changed_original_or_cache_evidence_and_preserves_every_byte(source,change):
    h=source;cached=freeze(h);h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    if change=='edited':h.target.write_bytes(b'changed')
    elif change=='replacement':h.target.rename(h.target.with_name('held-original'));h.target.write_bytes(b'hello')
    elif change=='hardlink':os.link(h.target,h.target.with_name('held-linked-original'))
    elif change=='missing':h.target.rename(h.target.with_name('held-original'))
    elif change in ('cipher','cipher_inode'):
        path=cached.directory/'chunk-00000000.enc';raw=path.read_bytes()
        if change=='cipher':path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        else:path.rename(cached.directory.parent/'held-original-cipher');path.write_bytes(raw);path.chmod(0o600)
    elif change=='unknown_child':(cached.directory/'foreign-data').write_bytes(b'preserve foreign original')
    else:
        from magnolie_media_source_jobs import _NativeSourceJobs
        jobs=_NativeSourceJobs(h.authority)
        with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:db.execute('DELETE FROM meta WHERE key=?',(jobs._key(cached.manifest.source_id),))
    before=metadata(h);bytes_before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    try:
        with pytest.raises((TransferError,OSError,InvalidTag)):reprepare(h,fresh,cached)
        assert fresh._prepared=={} and metadata(h)==before and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==bytes_before
    finally:fresh.close()


@pytest.mark.parametrize('change',['consent','intent','renewed_book'])
def test_fresh_repreparation_requires_actual_current_native_rights_and_exact_original_book(source,change):
    h=source;cached=freeze(h);h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    if change=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
    elif change=='intent':h.controller.change('enabled',False)
    else:
        from pathlib import Path
        from magnolie_telefon import strict_json
        directory=Path(h.authority.binding.native_directory)
        with NativeMediaRetention(directory) as retention:
            token=retention.pause();retention.publish_saved(token,strict_json((directory.parent/'daten.json').read_bytes()))
    before=metadata(h)
    try:
        with pytest.raises(TransferError):reprepare(h,fresh,cached)
        assert fresh._prepared=={} and metadata(h)==before and h.target.read_bytes()==b'hello'
    finally:fresh.close()


def test_cancel_during_actual_repreparation_original_read_holds_real_os_lane_until_read_ends(source,monkeypatch):
    h=source;cached=freeze(h);h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    entered=threading.Event();release=threading.Event();ended=threading.Event();results=[];pread=os.pread
    def blocked(fd,size,offset):
        value=os.fstat(fd)
        if (value.st_dev,value.st_ino)==h.record.file_key and offset==0:entered.set();assert release.wait(8)
        return pread(fd,size,offset)
    monkeypatch.setattr(os,'pread',blocked)
    def work():
        try:results.append(reprepare(h,fresh,cached))
        except BaseException as error:results.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);fresh.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5);fresh.close()
    assert ended.is_set() and not worker.is_alive() and len(results)==1 and isinstance(results[0],TransferError)
    assert fresh._prepared=={} and cached.directory.exists() and h.target.read_bytes()==b'hello'
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None


@pytest.mark.parametrize('change',['signature','mapping','unknown_stage'])
def test_matching_plaintext_alone_cannot_replace_original_signature_mapping_or_complete_scope_layout(source,change):
    h=source;cached=freeze(h);h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    if change=='signature':
        value=h.target.stat();os.utime(h.target,ns=(value.st_atime_ns,value.st_mtime_ns+1_000_000))
    elif change=='unknown_stage':
        from magnolie_media_source_jobs import _NativeSourceJobs
        jobs=_NativeSourceJobs(h.authority)
        (cached.directory.parent/('.magnolie-source-'+jobs._scope[:32]+'-'+'f'*32+'.retired')).mkdir(mode=0o700)
    before=metadata(h)
    try:
        with pytest.raises(TransferError):
            if change=='mapping':fresh.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,'f'*64,
                cached.manifest.source_id,cached._job_version)
            else:reprepare(h,fresh,cached)
        assert fresh._prepared=={} and metadata(h)==before and h.target.read_bytes()==b'hello'
    finally:fresh.close()


def test_actual_multichunk_original_is_fully_reprepared_without_cipher_rewrite(source,monkeypatch):
    h=source;raw=bytes(range(256))*600;h.target.write_bytes(raw);cached=freeze(h);h.source.close()
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller);before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    try:
        renewed=reprepare(h,fresh,cached)
        with fresh.prepared_cache(renewed.manifest.source_id) as reader:
            assert b''.join(reader.read_chunk(i) for i in range(renewed.manifest.files[0].chunks))==raw
        assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before and h.target.read_bytes()==raw
    finally:fresh.close()


def test_existing_native_retirement_intent_never_becomes_fresh_preparation_even_with_matching_original(completed):
    from magnolie_media_source_retirement import _NativeSourceRetirement
    h,sender,cached,backups,version=completed
    def stop(phase):
        if phase=='source_retirement_planned':owner.close()
    owner=_NativeSourceRetirement(sender,backups,version,boundary=stop)
    with pytest.raises(TransferError):owner.run()
    h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller);before=metadata(h)
    try:
        with pytest.raises(TransferError,match='reprepare_retirement_held'):reprepare(h,fresh,cached)
        assert fresh._prepared=={} and metadata(h)==before and cached.directory.exists()
    finally:fresh.close()


def test_fresh_repreparation_of_second_job_keeps_exact_earlier_archived_job_and_bytes(completed):
    from magnolie_media_source_retirement import _NativeSourceRetirement
    h,sender,cached,backups,version=completed;archived=_NativeSourceRetirement(sender,backups,version).run()
    archive=cached.directory.parent/archived.body['archive'];before={p.name:p.read_bytes() for p in archive.iterdir()}
    h.target.write_bytes(b'new second original version');second=freeze(h);h.source.close()
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller);records=metadata(h)
    try:
        renewed=reprepare(h,fresh,second)
        with fresh.prepared_cache(renewed.manifest.source_id) as reader:assert reader.read_chunk(0)==b'new second original version'
        assert metadata(h)==records and {p.name:p.read_bytes() for p in archive.iterdir()}==before
    finally:fresh.close()
