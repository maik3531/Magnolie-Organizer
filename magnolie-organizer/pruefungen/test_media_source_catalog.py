"""Native complete source membership; passive observers never repair/adopt."""
from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest
from cryptography.exceptions import InvalidTag

from test_media_source_cache import freeze,stage
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import handshake,acceptance,request,saved,deliver
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import media_path_is_excluded


def snapshot(h):
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        return db.execute("SELECT key,value FROM meta WHERE key GLOB 'native_media_source_*' ORDER BY key").fetchall()


def test_unused_native_scope_queries_are_inert_and_never_create_anchor_head_or_job(source):
    h=source;jobs=_NativeSourceJobs(h.authority);root=Path(h.authority.binding.native_directory)
    before=snapshot(h);names=set(p.name for p in root.iterdir())
    assert jobs.lookup('0'*32) is None and jobs._catalog.lookup() is None
    assert snapshot(h)==before and set(p.name for p in root.iterdir())==names
    assert not (root/jobs._catalog._anchor_name).exists()


def test_actual_writer_commits_plan_and_ready_membership_before_returning_payload_or_preparation(source):
    h=source;jobs=_NativeSourceJobs(h.authority);observed=[]
    def observe(phase):
        if phase not in ('source_cache_job_planned','source_cache_job_ready'):return
        catalog=jobs._catalog.lookup();body=catalog.body
        rows=snapshot(h);members=[[name,sha256(blob).hexdigest()] for name,blob in rows if name.startswith(jobs._prefix)]
        assert body['members']==members and len(members)==1
        assert not catalog.grants_read_authority and not catalog.permits_slot_reuse and not catalog.is_saved_receipt
        if phase=='source_cache_job_planned':assert set(p.name for p in stage(h).iterdir())=={'intent.enc'}
        observed.append(body['revision'])
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=observe)
    try:
        cached=freeze(h,owner);assert observed==[2,3]
        record=jobs.lookup(cached.manifest.source_id)
        assert jobs._catalog.lookup().body['members']==[[jobs._key(cached.manifest.source_id),record.version]]
        anchor=Path(h.authority.binding.native_directory)/jobs._catalog._anchor_name
        assert anchor.stat().st_nlink==1 and not anchor.stat().st_mode&0o077
        assert media_path_is_excluded(anchor) and media_path_is_excluded(str(anchor)+'/foreign/nested.jpg')
        assert not media_path_is_excluded('/Pictures/ordinary-source-catalog.jpg')
    finally:owner.close()


def test_actual_encrypted_wire_attempts_advance_same_native_membership_without_changing_ready_record(source):
    h=source;cached=freeze(h);jobs=_NativeSourceJobs(h.authority);sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    try:
        first=jobs._catalog.lookup();handshake(h,sender)
        assert jobs._catalog.lookup()==first # Actual controls alone do not manufacture a wire attempt.
        offer=sender.send_offer();assert h.wire.receive()==offer
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        deliver(h,sender,request(accepted,cached));assert h.wire.receive()['kind']=='file_transfer.chunk'
        deliver(h,sender,saved(accepted,cached));catalog=jobs._catalog.lookup()
        assert catalog.body['revision']==first.body['revision']+6
        members=dict(catalog.body['members'])
        assert members[jobs._key(cached.manifest.source_id)]==cached._job_version
        assert members[sender._journal._key]==sender.observation().version and len(members)==2
    finally:sender.close()


@pytest.mark.parametrize('change',['missing_head','deleted_job','resealed_job','added_copy','orphan_exchange'])
def test_missing_or_changed_member_holds_live_reads_and_new_observers_without_repair(source,change):
    h=source;cached=freeze(h);jobs=_NativeSourceJobs(h.authority);job=cached.manifest.source_id
    before_cache={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        if change=='missing_head':db.execute('DELETE FROM meta WHERE key=?',(jobs._catalog._key,))
        elif change=='deleted_job':db.execute('DELETE FROM meta WHERE key=?',(jobs._key(job),))
        else:
            key=jobs._key(job);blob=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()[0]
            if change=='resealed_job':
                plain=h.authority.protection.unseal(blob,key)
                db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(plain,key),key))
            elif change=='added_copy':db.execute('INSERT INTO meta VALUES(?,?)',(jobs._key('e'*32),blob))
            else:db.execute('INSERT INTO meta VALUES(?,?)',(jobs._catalog._exchange+'e'*32,blob))
    broken=snapshot(h)
    with pytest.raises(TransferError,match='media_source_catalog'):
        with h.source.prepared_cache(job):pytest.fail('Changed membership granted READ')
    fresh=_NativeSourceJobs(h.authority)
    with pytest.raises(TransferError,match='media_source_catalog'):fresh.lookup(job)
    assert snapshot(h)==broken and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before_cache


@pytest.mark.parametrize('change',['missing','same_bytes_new_inode','cipher'])
def test_original_anchor_cannot_be_recreated_replaced_or_resealed_from_valid_job_history(source,change):
    h=source;cached=freeze(h);jobs=_NativeSourceJobs(h.authority)
    anchor=Path(h.authority.binding.native_directory)/jobs._catalog._anchor_name;raw=anchor.read_bytes()
    if change=='cipher':anchor.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    else:
        anchor.rename(anchor.with_name('held-original-catalog-anchor'))
        if change=='same_bytes_new_inode':anchor.write_bytes(raw);anchor.chmod(0o600)
    broken=snapshot(h)
    with pytest.raises((TransferError,InvalidTag)):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Anchor history was adopted')
    with pytest.raises((TransferError,InvalidTag)):_NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)
    assert snapshot(h)==broken and cached.directory.exists() and h.target.read_bytes()==b'hello'
    if change=='missing':assert not anchor.exists()


def test_all_sql_members_removed_does_not_turn_anchored_scope_into_an_unused_catalog(source):
    h=source;cached=freeze(h);jobs=_NativeSourceJobs(h.authority)
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        db.execute('DELETE FROM meta WHERE key GLOB ?',(jobs._prefix+'*',))
        db.execute('DELETE FROM meta WHERE key=?',(jobs._catalog._key,))
    before=snapshot(h)
    with pytest.raises(TransferError,match='original_head_required'):_NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)
    assert snapshot(h)==before and cached.directory.exists()


def test_legacy_single_journal_without_catalog_or_anchor_is_held_not_backfilled(source):
    h=source;cached=freeze(h);jobs=_NativeSourceJobs(h.authority)
    anchor=Path(h.authority.binding.native_directory)/jobs._catalog._anchor_name
    anchor.rename(anchor.with_name('held-native-anchor-before-legacy-fixture'))
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:db.execute('DELETE FROM meta WHERE key=?',(jobs._catalog._key,))
    before=snapshot(h)
    with pytest.raises(TransferError,match='original_head_required'):_NativeSourceJobs(h.authority).lookup(cached.manifest.source_id)
    assert snapshot(h)==before and not anchor.exists() and cached.directory.exists()


def test_interrupted_original_anchor_creation_is_preserved_as_hold_before_job_or_payload(source):
    h=source
    def stop(phase):
        if phase=='source_catalog_anchor_durable':owner.close()
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=stop)
    try:
        with pytest.raises(TransferError):freeze(h,owner)
    finally:owner.close()
    root=stage(h);assert set(p.name for p in root.iterdir())=={'intent.enc'}
    jobs=_NativeSourceJobs(h.authority);before=snapshot(h)
    assert (Path(h.authority.binding.native_directory)/jobs._catalog._anchor_name).exists()
    with pytest.raises(TransferError,match='original_head_required'):jobs._catalog.lookup()
    with pytest.raises(TransferError,match='cache_existing_hold'):freeze(h)
    assert snapshot(h)==before and not list(root.glob('chunk-*'))
