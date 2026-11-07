"""Actual prepared PC-version backup, distinct from historical phone Saved."""
import os

import pytest

from test_media_source_cache import freeze
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_backups import idle
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_backup import backup_prepared_source,source_provenance
from magnolie_media_backups import NativeMediaBackups
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from magnolie_media_trash import NativeMediaRetentionPermit
from magnolie_file_acceptance import NativeAcceptedDestination


def open_backup(h,**kwargs):
    return NativeMediaBackups(h.record.destination,h.authority.protection,lambda:True,create=True,**kwargs)


def restore(owner,version,target):
    fd=os.open(target,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        owner.restore(version,fd)
        with pytest.raises(TransferError):owner.restore(version,fd)
    finally:os.close(fd)


def test_changed_pc_version_has_separate_source_provenance_and_restores_offline_without_forging_saved(source,tmp_path):
    h=source;raw=(b'actual edited original JPEG bytes\x00'*3000)+b'end';directory=h.authority.binding.native_directory
    with open_backup(h) as owner:
        original=owner.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
        h.target.write_bytes(raw);cached=freeze(h);version=backup_prepared_source(owner,h.source,cached.manifest.source_id)
        assert version.id!=original.id and len(owner.versions())==2
        provenance=source_provenance(owner,version)
        assert provenance['manifest']==cached.manifest.wire() and provenance['original_mapping']==h.record.wire()
        assert provenance['original_mapping']['saved_sha256']!=cached.manifest.files[0].sha256
        assert owner.selected_mapping(original)==h.record
        with pytest.raises(TransferError,match='source_version_has_no_saved_mapping'):owner.selected_mapping(version)
        assert backup_prepared_source(owner,h.source,cached.manifest.source_id)==version
    h.source.close();h.target.unlink();cached.directory.rename(cached.directory.with_name('held-source-fixture'))
    with ExistingFileTransferProtection(directory) as protection:
        with NativeMediaBackups(h.record.destination,protection,lambda:True) as offline:
            restore(offline,version,tmp_path/'restored-current-PC-version.jpg')
            restore(offline,original,tmp_path/'restored-original-phone-version.jpg')
    assert (tmp_path/'restored-current-PC-version.jpg').read_bytes()==raw
    assert (tmp_path/'restored-original-phone-version.jpg').read_bytes()==b'hello'


def test_source_bytes_deduplicate_with_real_saved_backup_without_changing_mapping_and_pin_shared_object(source):
    h=source;now=[1800000000000]
    with open_backup(h,clock_ms=lambda:now[0]) as owner:
        original=owner.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
        cached=freeze(h);version=backup_prepared_source(owner,h.source,cached.manifest.source_id)
        assert version.id!=original.id and version.object_key==original.object_key
        paths=list((h.target.parents[len(h.record.relative_path.split('/'))-1]/'Backup').glob('object-*.raw'))
        assert len(paths)==1 and paths[0].read_bytes()==b'hello'
        assert paths[0].stat().st_nlink==1 and paths[0].stat().st_ino!=h.target.stat().st_ino
        now[0]+=31*86400000
        assert owner.compression_candidates(90)==()
        assert not owner.compress_one(version.object_key,idle(),NativeMediaRetentionPermit(90,lambda:90))
        assert owner.selected_mapping(original)==h.record and len(owner.versions())==2


@pytest.mark.parametrize('phase',['source_backup_chunk_durable','source_backup_payload_verified'])
def test_interrupted_source_backup_exposes_only_independently_verified_complete_bytes(source,tmp_path,phase):
    h=source;raw=b'bounded original source version\x00'*3000;h.target.write_bytes(raw);cached=freeze(h)
    def stop(current):
        if current==phase:raise RuntimeError('explicit interrupted source backup')
    with open_backup(h) as owner:
        with pytest.raises(RuntimeError,match='interrupted source backup'):
            backup_prepared_source(owner,h.source,cached.manifest.source_id,boundary=stop)
        assert owner.versions()==()
        pending=owner.pending_recovery_versions()
        if phase=='source_backup_chunk_durable':assert pending==()
        else:
            assert len(pending)==1 and source_provenance(owner,pending[0])['manifest']==cached.manifest.wire()
            h.source.close();restore(owner,pending[0],tmp_path/'recovered-complete-interrupted-version.jpg')
            assert (tmp_path/'recovered-complete-interrupted-version.jpg').read_bytes()==raw
        assert cached.directory.exists() and h.target.read_bytes()==raw


@pytest.mark.parametrize('change',['reconstructed_owner','withdrawn_consent'])
def test_source_metadata_or_withdrawn_consent_cannot_create_backup_intent_or_payload(source,change):
    h=source;cached=freeze(h);other=None
    if change=='withdrawn_consent':h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    else:other=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        with open_backup(h) as owner:
            with pytest.raises(TransferError):backup_prepared_source(owner,other or h.source,cached.manifest.source_id)
            assert owner.versions()==() and owner.pending_recovery_versions()==()
            assert owner._members('objects')==[] and owner._pending_members()==[]
    finally:
        if other is not None:other.close()


def test_alternative_source_backup_preserves_default_catalog_and_authenticates_original_data_scope(source,tmp_path):
    h=source;alternative=tmp_path/'alternative';alternative.mkdir(mode=0o700)
    with open_backup(h) as default:
        original=default.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
        h.target.write_bytes(b'a different PC version');cached=freeze(h)
        with open_backup(h,storage_parent=NativeAcceptedDestination.capture(alternative)) as chosen:
            version=backup_prepared_source(chosen,h.source,cached.manifest.source_id)
            restore(chosen,version,tmp_path/'alternative-restored.jpg')
        assert default.versions()==(original,) and default.selected_mapping(original)==h.record
        assert (tmp_path/'alternative-restored.jpg').read_bytes()==b'a different PC version'
