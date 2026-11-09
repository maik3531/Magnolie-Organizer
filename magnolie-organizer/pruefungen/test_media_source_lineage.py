"""#429: protected chronology, not UUID order or arbitrary historical hashes."""
from hashlib import sha256

import pytest

from test_media_source_media_retirement import source,native,receiving,mappings,completed,png
from test_media_source_cache import freeze
from test_media_source_backup import open_backup
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_media_source_lineage import _NativeSourceLineage
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical,strict_json


def test_absent_chronology_is_readonly_and_does_not_bootstrap_catalog(source):
    jobs=_NativeSourceJobs(source.authority)
    with jobs._database() as (db,_):before=db.execute('SELECT key,value FROM meta ORDER BY key').fetchall()
    result=_NativeSourceLineage(jobs).lookup()
    assert result.catalog_version is None and result.legacy_count==0 and result.records==()
    assert result.legacy_sha256==sha256(canonical([])).hexdigest()
    assert not result.grants_read_authority and not result.is_saved_receipt and not result.permits_deletion
    with jobs._database() as (db,_):assert db.execute('SELECT key,value FROM meta ORDER BY key').fetchall()==before


def test_live_tip_is_metadata_only_and_cannot_be_a_completed_predecessor(source):
    cached=freeze(source);jobs=_NativeSourceJobs(source.authority);lineage=_NativeSourceLineage(jobs)
    result=lineage.lookup();assert len(result.records)==1
    record=result.records[0]
    assert record.version==cached._job_version and record.body['format']==2
    assert record.body['lineage']==dict(legacy_sha256=sha256(canonical([])).hexdigest(),previous_job=None,previous_ready=None,previous_retirement=None)
    source.target.unlink()
    assert lineage.lookup()==result and not source.target.exists()
    with jobs._database() as (db,key):
        db.execute('BEGIN');catalog=jobs._catalog.verify(db,key)
        with pytest.raises(TransferError,match='lineage_pending_job'):lineage.predecessor(db,key,catalog)


@pytest.mark.parametrize('fault',['baseline','missing_predecessor','self_cycle','fork','legacy_downgrade','malformed'])
def test_authenticated_invalid_chronology_is_not_hidden_by_valid_catalog_membership(source,fault):
    cached=freeze(source);jobs=_NativeSourceJobs(source.authority);job=cached.manifest.source_id
    before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with jobs._database() as (db,key):
        db.execute('BEGIN IMMEDIATE');catalog=jobs._catalog.verify(db,key)
        record=jobs._read(db,key,job);body=record.body
        if fault=='baseline':body['lineage']['legacy_sha256']='f'*64
        elif fault in ('missing_predecessor','self_cycle'):
            body['lineage'].update(previous_job='e'*32 if fault=='missing_predecessor' else job,previous_ready=record.version,previous_retirement='f'*64)
        elif fault=='legacy_downgrade':body['format']=1;body.pop('lineage')
        elif fault=='malformed':body['lineage']['previous_ready']='f'*64
        elif fault=='fork':
            body.update(job_id='e'*32,state='cache_planned',manifest=None,proof_sha256=None,original_references=None)
            job='e'*32
        name=jobs._key(job)
        db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(name,source.authority.protection.seal(canonical(body),name)))
        jobs._catalog.advance(db,key,catalog)
    with pytest.raises(TransferError,match='lineage_'):_NativeSourceLineage(_NativeSourceJobs(source.authority)).lookup()
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before


def test_actual_media_completion_binds_exact_predecessor_without_modifying_old_archive(source,monkeypatch):
    import secrets
    from types import SimpleNamespace
    import magnolie_media_source_cache as cache_module
    ids=iter(['f'*32,secrets.token_hex(16),secrets.token_hex(16),'1'*32,secrets.token_hex(16),secrets.token_hex(16)])
    monkeypatch.setattr(cache_module,'secrets',SimpleNamespace(token_hex=lambda n:next(ids) if n==16 else secrets.token_hex(n)))
    h=source;sender,cached,_=completed(h)
    try:
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            retired=_NativeSourceRetirement(sender,backups,version).run()
            archive=cached.directory.with_name(retired.body['archive'])
            before={p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}
            h.target.write_bytes(png(1));second=freeze(h)
            jobs=_NativeSourceJobs(h.authority);result=_NativeSourceLineage(jobs).lookup()
            assert [r.body['job_id'] for r in result.records]==[cached.manifest.source_id,second.manifest.source_id]
            assert cached.manifest.source_id>second.manifest.source_id # Deliberately opposite UUID order.
            assert result.records[-1].body['lineage']==dict(legacy_sha256=result.legacy_sha256,
                previous_job=cached.manifest.source_id,previous_ready=cached._job_version,previous_retirement=retired.version)
            assert result.records[0].body['manifest']['files'][0]['sha256']!=result.records[-1].body['manifest']['files'][0]['sha256']
            assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
            assert not result.grants_read_authority
            with jobs._database() as (db,key):
                db.execute('BEGIN IMMEDIATE');catalog=jobs._catalog.verify(db,key)
                name=jobs._key(cached.manifest.source_id)
                raw=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()[0]
                plain=h.authority.protection.unseal(raw,name)
                db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(plain,name),name))
                jobs._catalog.advance(db,key,catalog)
            with pytest.raises(TransferError,match='lineage_original_completion_required'):
                _NativeSourceLineage(_NativeSourceJobs(h.authority)).lookup()
            assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
    finally:sender.close()


def test_actual_legacy_archive_is_unordered_baseline_not_fabricated_latest(source,monkeypatch):
    h=source;protection=h.authority.protection;seal=protection.seal
    def legacy_seal(plain,name):
        if name.startswith('native_media_source_jobs_v1/'):
            body=strict_json(plain)
            if body.get('format')==2:
                body['format']=1;body.pop('lineage');plain=canonical(body)
        return seal(plain,name)
    # Emit the previously supported job format through the actual cache/sender/
    # backup/archive lifecycle. No completion or authority flag is fabricated.
    with monkeypatch.context() as patch:
        patch.setattr(protection,'seal',legacy_seal)
        sender,cached,_=completed(h)
    try:
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            retired=_NativeSourceRetirement(sender,backups,version).run()
            jobs=_NativeSourceJobs(h.authority);before=_NativeSourceLineage(jobs).lookup()
            assert before.records==() and before.legacy_count==1
            assert before.legacy_sha256==sha256(canonical([[cached.manifest.source_id,cached._job_version,retired.version]])).hexdigest()
            h.target.write_bytes(png(1));second=freeze(h)
            after=_NativeSourceLineage(jobs).lookup()
            assert after.legacy_count==1 and after.legacy_sha256==before.legacy_sha256
            assert [r.body['job_id'] for r in after.records]==[second.manifest.source_id]
            assert after.records[0].body['lineage']['previous_job'] is None
            assert jobs.lookup(cached.manifest.source_id).body['format']==1
    finally:sender.close()
