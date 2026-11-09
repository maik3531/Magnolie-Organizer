"""#429: automatic source selection cannot fall back to a retained old head."""
from dataclasses import replace
from pathlib import Path

import pytest

from test_media_source import source,native,receiving,mappings
from test_photo_version_history_safety import version
from magnolie_file_transfer import TransferError


def test_latest_only_lease_rejects_actual_historical_version_but_preserves_explicit_backup_lease(receiving):
    connection,association=version(receiving);owner=connection._mappings
    snapshot=owner.read();records=owner._mapping_records(association)
    assert len(records)==2
    latest,old=records[0][1],records[-1][1]
    before=owner._db.execute('SELECT association,payload FROM mappings ORDER BY association').fetchall()
    with pytest.raises(TransferError,match='lease_latest_required'):
        with owner.saved_record_lease(association,old.protected_record_sha256,expected=snapshot,latest=True):
            pytest.fail('Automatic source selection adopted a retained historical mapping')
    with owner.saved_record_lease(association,latest.protected_record_sha256,expected=snapshot,latest=True) as (selected,current):
        assert selected==latest;current()
    with owner.saved_record_lease(association,old.protected_record_sha256) as (retained,current):
        assert retained==old;current() # Metadata lease only; never current file presence or READ.
    assert owner.read()==snapshot and owner._db.execute('SELECT association,payload FROM mappings ORDER BY association').fetchall()==before


def test_source_pins_actual_current_mapping_inside_plan_and_fresh_copy(source):
    h=source;snapshot=h.mappings.read()
    selected=h.source.plan(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256,mapping_snapshot=snapshot)
    assert not selected.changed
    cached=h.source.freeze_observed(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256,
        selected.observation,catalog_version=selected.catalog_version,mapping_snapshot=snapshot)
    with h.source.prepared_cache(cached.manifest.source_id) as reader:assert reader.read_chunk(0)==b'hello'
    assert h.mappings.read()==snapshot and h.target.read_bytes()==b'hello'


def test_stale_or_untyped_mapping_selection_cannot_open_source_and_does_not_poison_current_store(source,monkeypatch):
    h=source;snapshot=h.mappings.read()
    monkeypatch.setattr(h.source,'_file',lambda *args:pytest.fail('Stale source selection opened a file'))
    for selection,error in ((replace(snapshot,version='f'*64),'lease_snapshot_changed'),({},'native_mapping_selection_required')):
        with pytest.raises(TransferError,match=error):
            h.source.plan(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256,mapping_snapshot=selection)
    for options in (dict(expected={}),dict(latest=1)):
        with pytest.raises(TransferError,match='native_associations_required'):
            with h.mappings.saved_record_lease(h.association,h.record.protected_record_sha256,**options):
                pytest.fail('Untyped automatic selection entered a protected lease')
    assert h.mappings.read()==snapshot and not h.source._prepared
    assert not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))


def test_normal_conditional_copy_rechecks_mapping_snapshot_after_plan_before_cache(source,native,monkeypatch):
    from test_media_source_connection import composition,agree,png
    with composition(source,native[0]) as h:
        agree(h,native[0]);h.target.write_bytes(png());snapshot=h.mappings.read();original=h.source.plan
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            # A different legitimate mapping-table revision can occur while the
            # selected file itself stays unchanged. No Saved flag is invented.
            owner=h.mappings
            with owner._operation():
                with owner._locked():
                    body=owner._unprotect(owner._db.execute('SELECT payload FROM owner').fetchone()[0],'owner')
                    body['revision']+=1
                    owner._db.execute('UPDATE owner SET payload=? WHERE id=1',(owner._protect(body,'owner'),));owner._db.commit()
            return result
        with monkeypatch.context() as patch:
            patch.setattr(h.source,'plan',changed)
            with pytest.raises(TransferError,match='lease_snapshot_changed'):
                h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,
                    h.record.protected_record_sha256,mapping_snapshot=snapshot)
        assert not h.source._prepared and not list(Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part'))
        fresh=h.mappings.read();assert fresh!=snapshot
        selected=h.connection.prepare_changed_media_source(h.connection.issue_receive_action(),h.preferences.read(),h.association,
            h.record.protected_record_sha256,mapping_snapshot=fresh)
        assert selected.plan.changed and selected.cache is not None
