"""Actual completed restore to frozen original bytes and distinct backup (#404)."""
from pathlib import Path
import base64

import pytest

from test_media_restored_source import restored,source,mappings,receiving,native
from test_media_source_cache import decode,stage
from test_media_source_sender import handshake,acceptance,request,saved,deliver
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_backup import backup_prepared_source,source_provenance
from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupLocations,NativeMediaBackupRecoveryUi
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_transfer import TransferError
from magnolie_telefon import strict_json
from hashlib import sha256
from magnolie_telefon import canonical


def freeze_restored(r,*,source_owner=None,record=None):
    h=r.h
    return (source_owner or h.source).freeze_restored(h.preferences.issue_action(),h.policy,r.owner,r.result.operation,
        record or r.candidate.protected_record_sha256)


def test_restored_source_freezes_actual_new_inode_then_backs_up_under_new_destination_and_recovers_offline(restored,tmp_path):
    r=restored;h=r.h;raw=b'current restored original bytes\x00'*2600;r.path.write_bytes(raw)
    cached=freeze_restored(r);intent=strict_json(decode(h,cached.directory/'intent.enc'))
    assert intent['restored_source']==r.candidate.wire()
    assert h.source._prepared[cached.manifest.source_id].original_mapping==h.record
    with h.source.prepared_cache(cached.manifest.source_id) as reader:
        assert b''.join(reader.read_chunk(index) for index in range(cached.manifest.files[0].chunks))==raw
    with NativeMediaBackups(r.target,h.authority.protection,lambda:True,create=True) as backups:
        version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
        provenance=source_provenance(backups,version)
        assert provenance['restored_source']==r.candidate.wire() and provenance['original_mapping']==h.record.wire()
        assert provenance['original_mapping_sha256']==h.record.protected_record_sha256
    with NativeMediaBackupLocations(r.directory,r.scope,lambda:True) as locations:
        locations.choose(locations.issue_action(),locations.read(),h.record.destination,r.target)
    h.source.close();r.path.unlink();cached.directory.rename(cached.directory.with_name('held-frozen-restored-source'))
    internal=sha256(canonical(dict(local_backup_scope=r.scope))).hexdigest();source_id=NativeMediaBackupLocations.source_id(r.target)
    target=tmp_path/'offline';target.mkdir(mode=0o700)
    recovery=NativeMediaBackupRecoveryUi(r.directory,lambda:True)
    result=recovery.restore(internal,source_id,version.id,version.record_sha256,NativeAcceptedDestination.capture(target))
    assert (target/result.name).read_bytes()==raw and result.original_mapping==h.record
    assert result.source_version['source']['restored_source']==r.candidate.wire()
    assert h.target.read_bytes()==b'hello' and not result.is_saved_receipt


def test_private_sender_sends_frozen_restored_bytes_with_unchanged_phone_original_reference(restored):
    r=restored;h=r.h;raw=b'native edited restored payload';r.path.write_bytes(raw);cached=freeze_restored(r)
    sender=_NativeMediaSourceSender(h.source,cached.manifest.source_id)
    try:
        handshake(h,sender);offer=sender.send_offer();assert h.wire.receive()==offer
        accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
        deliver(h,sender,request(accepted,cached));chunk=h.wire.receive()
        assert base64.b64decode(chunk['body']['data_base64'],validate=True)==raw
        deliver(h,sender,saved(accepted,cached))
        assert sender.observation().body['phase']=='peer_saved'
        assert cached.original_references=={cached.manifest.files[0].id:h.record.phone_original_reference()}
        assert r.owner.history()[0].original_mapping==h.record and not h.preferences.local_grant(True).grants.send_files
    finally:sender.close()


def test_restored_source_backup_cannot_adopt_original_saved_destination_or_overwrite_completed_source_stage(restored):
    r=restored;h=r.h;cached=freeze_restored(r);before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with NativeMediaBackups(h.record.destination,h.authority.protection,lambda:True) as original:
        old=original.versions()
        with pytest.raises(TransferError,match='original_source_owner_required'):
            backup_prepared_source(original,h.source,cached.manifest.source_id)
        assert original.versions()==old
    with pytest.raises(TransferError,match='cache_existing_hold'):freeze_restored(r)
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before and r.path.read_bytes()==b'hello'


def test_stale_completed_restore_selection_creates_no_source_stage(restored):
    r=restored
    with pytest.raises(TransferError,match='source_selection_changed'):freeze_restored(r,record='f'*64)
    assert not list(Path(r.directory).glob('.magnolie-source-*.part')) and r.path.read_bytes()==b'hello'


def test_interrupted_restored_source_cache_retains_owned_partial_bytes_and_never_adopts_them(restored):
    r=restored;h=r.h
    def stop(phase):
        if phase=='source_cache_chunk_durable':owner.close()
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=stop)
    try:
        with pytest.raises(TransferError):freeze_restored(r,source_owner=owner)
    finally:owner.close()
    root=stage(h);assert (root/'chunk-00000000.enc').exists() and not (root/'manifest.enc').exists()
    before={p.name:p.read_bytes() for p in root.iterdir()}
    with pytest.raises(TransferError,match='cache_existing_hold'):freeze_restored(r)
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before and r.path.read_bytes()==b'hello'
