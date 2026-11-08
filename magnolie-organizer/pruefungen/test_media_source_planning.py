"""#429: actual native source bytes versus the last completed source version."""
from hashlib import sha256

import pytest

from test_media_source_media_retirement import source,native,receiving,mappings,completed,png
from test_media_source_backup import open_backup
from test_media_source_cache import freeze
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_file_transfer import TransferError
from test_media_source_retirement import completed as generic_completed


def plan(h):
    return h.source.plan(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256)


def test_original_mapping_is_only_baseline_until_an_outgoing_completion_exists(source):
    h=source;root=h.authority.binding.native_directory
    from pathlib import Path
    before={p.name:p.read_bytes() for p in Path(root).iterdir() if p.is_file()}
    result=plan(h)
    assert not result.changed and result.basis=='original_mapping' and result.latest_job_id is None and result.catalog_version is None
    assert result.observation.sha256==sha256(b'hello').hexdigest()
    h.target.write_bytes(b'PC changed bytes')
    changed=plan(h)
    assert changed.changed and changed.basis=='original_mapping'
    assert not changed.grants_read_authority and not changed.is_saved_receipt and not changed.permits_deletion
    assert not h.source._prepared and not list(Path(root).glob('.magnolie-source-*'))
    assert before=={p.name:p.read_bytes() for p in Path(root).iterdir() if p.is_file()}


def test_pending_job_blocks_comparison_without_granting_restart_or_creating_second_cache(source):
    h=source;cached=freeze(h);before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with pytest.raises(TransferError,match='slot_pending_job'):plan(h)
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
    assert set(h.source._prepared)=={cached.manifest.source_id}


def test_missing_mapped_file_is_not_recreated_by_planning(source):
    h=source;h.target.unlink()
    with pytest.raises(FileNotFoundError):plan(h)
    assert not h.target.exists() and not h.source._prepared


def test_withdrawn_native_consent_stops_planning_before_opening_source(source,monkeypatch):
    h=source;h.policy=h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    monkeypatch.setattr(h.source,'_file',lambda *args:pytest.fail('Planning read before native consent'))
    with pytest.raises(TransferError,match='local_consent_required'):plan(h)
    assert not h.source._prepared


def archive(h,sender,cached,backups):
    version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
    result=_NativeSourceRetirement(sender,backups,version).run()
    return cached.directory.with_name(result.body['archive'])


def test_only_latest_actual_media_completion_can_skip_equal_bytes_and_rollback_is_new_change(source,monkeypatch):
    h=source;first,cached,_=completed(h)
    try:
        with open_backup(h) as backups:
            first_archive=archive(h,first,cached,backups)
            unchanged=plan(h)
            assert not unchanged.changed and unchanged.basis=='latest_completed' and unchanged.latest_job_id==cached.manifest.source_id
            import test_media_source_media_offer as offer_module
            with monkeypatch.context() as patch:
                patch.setattr(offer_module,'png',lambda salt=0:png(1))
                second,newer,_=completed(h)
            try:
                second_archive=archive(h,second,newer,backups)
                retained=[{p.name:(p.stat().st_ino,p.read_bytes()) for p in root.iterdir()} for root in (first_archive,second_archive)]
                same=plan(h)
                assert not same.changed and same.latest_job_id==newer.manifest.source_id and same.basis=='latest_completed'
                h.target.write_bytes(png()) # Matches an older completed version, NOT the latest.
                rollback=plan(h)
                assert rollback.changed and rollback.latest_job_id==newer.manifest.source_id
                h.target.write_bytes(b'hello') # Also do not fall back to the original phone Saved hash.
                assert plan(h).changed
                assert not h.source._prepared
                assert retained==[{p.name:(p.stat().st_ino,p.read_bytes()) for p in root.iterdir()} for root in (first_archive,second_archive)]
                assert _NativeSourceJobs(h.authority)._catalog.lookup().version==same.catalog_version
            finally:second.close()
    finally:first.close()


def test_generic_file_saved_history_never_becomes_a_normal_media_deduplication_baseline(generic_completed):
    h,sender,cached,backups,version=generic_completed
    _NativeSourceRetirement(sender,backups,version).run()
    result=plan(h)
    assert result.changed and result.basis=='completion_not_comparable' and result.latest_job_id==cached.manifest.source_id
    assert not h.source._prepared


def test_unknown_legacy_order_never_skips_equal_bytes(source,monkeypatch):
    from magnolie_telefon import canonical,strict_json
    h=source;protection=h.authority.protection;seal=protection.seal
    def legacy_seal(plain,name):
        if name.startswith('native_media_source_jobs_v1/'):
            body=strict_json(plain)
            if body.get('format')==2:
                body['format']=1;body.pop('lineage');plain=canonical(body)
        return seal(plain,name)
    with monkeypatch.context() as patch:
        patch.setattr(protection,'seal',legacy_seal)
        sender,cached,_=completed(h)
    try:
        with open_backup(h) as backups:
            archive(h,sender,cached,backups)
            result=plan(h)
            assert result.changed and result.basis=='legacy_order_unknown' and result.latest_job_id is None
            assert not h.source._prepared
    finally:sender.close()
