"""Native cache/job ordering, protected CAS and non-authoritative history (#338)."""
import sqlite3

import pytest
from cryptography.exceptions import InvalidTag

from test_media_source_cache import freeze,stage,decode
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_jobs import _NativeSourceJobs
from magnolie_file_transfer import TransferError
from magnolie_telefon import strict_json


def alter(h,jobs,job,change):
    with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
        key=jobs._key(job)
        if change=='missing':db.execute('DELETE FROM meta WHERE key=?',(key,))
        elif change=='cipher':
            raw=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()[0]
            db.execute('UPDATE meta SET value=? WHERE key=?',(raw[:-1]+bytes([raw[-1]^1]),key))
        else:
            raw=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()[0]
            plain=h.authority.protection.unseal(raw,key)
            db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(plain,key),key))


def test_job_plan_is_durable_after_intent_before_payload_and_ready_matches_actual_sealed_cache(source):
    h=source;jobs=_NativeSourceJobs(h.authority);seen=[]
    def observe(phase):
        if phase not in ('source_cache_job_planned','source_cache_sealed_durable','source_cache_job_ready'):return
        root=stage(h);intent=strict_json(decode(h,root/'intent.enc'));record=jobs.lookup(intent['job_id'])
        assert record.body['nonce']==intent['job_nonce']
        assert not record.grants_read_authority and not record.is_saved_receipt
        if phase=='source_cache_job_planned':
            assert record.state=='cache_planned' and set(p.name for p in root.iterdir())=={'intent.enc'}
        elif phase=='source_cache_sealed_durable':assert record.state=='cache_planned'
        else:assert record.state=='cache_ready'
        seen.append(phase)
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=observe)
    try:
        cached=freeze(h,owner);record=jobs.require_version(cached.manifest.source_id,cached._job_version)
        assert record.body['manifest']==cached.manifest.wire()
        assert record.body['proof_sha256']==cached.proof_sha256
        copy=record.body;copy['state']='invented';assert record.state=='cache_ready'
        with owner.prepared_cache(cached.manifest.source_id) as reader:assert reader.read_chunk(0)==b'hello'
        other=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
        try:
            with pytest.raises(TransferError,match='prepared_owner_required'):
                with other.prepared_cache(record.body['job_id']):pytest.fail('History granted READ')
        finally:other.close()
    finally:owner.close()
    assert seen==['source_cache_job_planned','source_cache_sealed_durable','source_cache_job_ready']


def test_interrupted_plan_remains_historical_without_payload_or_restart_adoption(source):
    h=source
    def stop(phase):
        if phase=='source_cache_job_planned':owner.close()
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=stop)
    try:
        with pytest.raises(TransferError):freeze(h,owner)
    finally:owner.close()
    root=stage(h);before={p.name:p.read_bytes() for p in root.iterdir()}
    assert set(before)=={'intent.enc'}
    intent=strict_json(decode(h,root/'intent.enc'));jobs=_NativeSourceJobs(h.authority)
    assert jobs.lookup(intent['job_id']).state=='cache_planned'
    with pytest.raises(TransferError,match='cache_existing_hold'):freeze(h)
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before


@pytest.mark.parametrize('change',['missing','cipher','resealed'])
def test_ready_record_missing_tampered_or_resealed_never_recreates_read_authority(source,change):
    h=source;cached=freeze(h);job=cached.manifest.source_id;jobs=_NativeSourceJobs(h.authority)
    before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    with pytest.raises((TransferError,InvalidTag)):
        with h.source.prepared_cache(job) as reader:
            alter(h,jobs,job,change)
            reader.read_chunk(0)
    with pytest.raises(TransferError,match='prepared_retired'):
        with h.source.prepared_cache(job):pytest.fail('Damaged job was revived')
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
    if change=='missing':assert jobs.lookup(job) is None
    assert h.target.read_bytes()==b'hello'


def test_changed_plan_cannot_advance_to_ready_or_copy_payload(source):
    h=source;jobs=_NativeSourceJobs(h.authority)
    def remove(phase):
        if phase=='source_cache_job_planned':
            intent=strict_json(decode(h,stage(h)/'intent.enc'));alter(h,jobs,intent['job_id'],'missing')
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=remove)
    try:
        with pytest.raises(TransferError,match='source_jobs_plan_changed'):freeze(h,owner)
    finally:owner.close()
    assert not list(stage(h).glob('chunk-*')) and not (stage(h)/'manifest.enc').exists()
    assert h.target.read_bytes()==b'hello'


@pytest.mark.parametrize('change',['missing','resealed'])
def test_ready_compare_and_swap_requires_the_exact_original_durable_plan(source,change):
    h=source;jobs=_NativeSourceJobs(h.authority);selected=[]
    def change_plan(phase):
        if phase=='source_cache_sealed_durable':
            root=stage(h);intent=strict_json(decode(h,root/'intent.enc'));job=intent['job_id']
            selected.append(job);alter(h,jobs,job,change)
    owner=NativeMappedMediaSource(h.preferences,h.mappings,h.controller,boundary=change_plan)
    try:
        with pytest.raises(TransferError,match='source_jobs_plan_changed'):freeze(h,owner)
        with pytest.raises(TransferError,match='prepared_owner_required'):
            with owner.prepared_cache(selected[0]):pytest.fail('Failed CAS created a live preparation')
    finally:owner.close()
    assert (stage(h)/'manifest.enc').exists() and h.target.read_bytes()==b'hello'
    record=jobs.lookup(selected[0])
    assert record is None if change=='missing' else record.state=='cache_planned'
