"""Durable catalog membership must not become empty after process reopen."""
from pathlib import Path
import sys
import os
import json

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_catalog_membership import CatalogMembership
from test_transfer_job_catalog import fixture


def test_missing_reserved_member_after_catalog_reopen_is_not_an_empty_catalog(fixture):
    f=fixture;catalog=f.open(create=True)
    job=catalog.reserve(f.accepted(),lambda:f.current)
    original=f.root/('job-'+job.owner+'.enc')
    held=f.parent/('held-original-job-'+job.owner+'.enc')
    catalog.close();original.rename(held)
    try:
        with pytest.raises(TransferError):
            reopened=f.open()
            reopened.jobs()
        assert not original.exists() and held.exists()
        assert not list(f.destination.iterdir())
    finally:held.rename(original)


@pytest.mark.parametrize('change',['head-missing','head-cipher','database-missing'])
def test_membership_metadata_loss_or_corruption_is_preserved_not_initialized(fixture,change):
    f=fixture;catalog=f.open(create=True);job=catalog.reserve(f.accepted(),lambda:f.current)
    registry=catalog._registry;held=None
    if change=='head-missing':
        with registry.db:registry.db.execute('DELETE FROM head')
    elif change=='head-cipher':
        blob=registry.db.execute('SELECT payload FROM head').fetchone()[0]
        with registry.db:registry.db.execute('UPDATE head SET payload=?',(blob[:-1]+bytes([blob[-1]^1]),))
    catalog.close()
    if change=='database-missing':
        original=f.root/CatalogMembership.NAME;held=f.parent/'held-original-membership.sqlite';original.rename(held)
    try:
        with pytest.raises((TransferError,OSError,InvalidTag)):f.open()
        assert (f.root/('job-'+job.owner+'.enc')).exists() and not list(f.destination.iterdir())
        if held is not None:assert held.exists() and not original.exists()
    finally:
        if held is not None:held.rename(original)


@pytest.mark.parametrize('suffix',['-journal','-wal','-shm'])
def test_unknown_membership_sidecar_is_preserved_before_sqlite_open(fixture,suffix):
    f=fixture;catalog=f.open(create=True);catalog.close()
    sidecar=f.root/(CatalogMembership.NAME+suffix);sidecar.write_bytes(b'unknown original data');sidecar.chmod(0o600)
    with pytest.raises(TransferError,match='journal_preserved'):f.open()
    assert sidecar.read_bytes()==b'unknown original data'


def test_dangling_membership_sidecar_symlink_is_preserved_without_sqlite_adoption(fixture):
    f=fixture;catalog=f.open(create=True);catalog.close()
    sidecar=f.root/(CatalogMembership.NAME+'-journal');sidecar.symlink_to('missing-original-sidecar-target')
    with pytest.raises(TransferError,match='journal_preserved'):f.open()
    assert sidecar.is_symlink() and os.readlink(sidecar)=='missing-original-sidecar-target'


def test_failed_postcommit_membership_sync_is_not_success_and_fresh_reopen_recovers_actual_committed_job(fixture,monkeypatch):
    f=fixture;catalog=f.open(create=True);registry=catalog._registry;sync=os.fsync;inserted=[]
    registry.db.set_trace_callback(lambda sql:inserted.append(True) if sql.startswith('INSERT OR REPLACE INTO head') else None)
    def interrupted(fd):
        if inserted and fd==registry.fd:raise OSError('fixture membership postcommit sync lost')
        sync(fd)
    monkeypatch.setattr(os,'fsync',interrupted)
    with pytest.raises(OSError,match='postcommit'):catalog.reserve(f.accepted(),lambda:f.current)
    assert catalog._failed and registry.uncertain
    with pytest.raises(TransferError,match='repair_pending'):catalog.reserve(f.accepted('b'),lambda:f.current)
    monkeypatch.setattr(os,'fsync',sync);catalog.close()
    reopened=f.open();jobs=reopened.jobs()
    assert len(jobs)==1 and reopened._registry.last[0]==2
    assert not list(f.destination.iterdir())


def test_job_written_before_membership_commit_failure_is_held_not_ignored_on_reopen(fixture,monkeypatch):
    f=fixture;catalog=f.open(create=True);seal=catalog._seal
    def interrupted(raw,domain):
        if domain.endswith('membership-head'):raise OSError('fixture membership seal failed')
        return seal(raw,domain)
    monkeypatch.setattr(catalog,'_seal',interrupted)
    with pytest.raises(OSError):catalog.reserve(f.accepted(),lambda:f.current)
    assert len(list(f.root.glob('job-*.enc')))==1
    catalog.close()
    with pytest.raises(TransferError,match='membership_changed'):f.open()
    assert len(list(f.root.glob('job-*.enc')))==1


def test_existing_legacy_catalog_stays_legacy_readonly_without_automatic_registry_adoption(fixture):
    f=fixture;catalog=f.open(create=True)
    path=f.root/'owner.enc';raw=f.cipher.open(path.read_bytes(),catalog._domain+'owner.enc');value=json.loads(raw)
    value['payload']['format']=1;del value['payload']['registry_key']
    legacy=f.cipher.seal(catalog._json(value),catalog._domain+'owner.enc');catalog.close()
    path.write_bytes(legacy)
    registry=f.root/CatalogMembership.NAME;held=f.parent/'held-new-registry';registry.rename(held)
    try:
        reopened=f.open();assert reopened.jobs()==() and reopened._registry is None
        with pytest.raises(TransferError,match='legacy_membership_upgrade_required'):reopened.choice()
        assert not registry.exists() and path.read_bytes()==legacy
    finally:held.rename(registry)


@pytest.mark.parametrize('field,value',[('format',True),('count',False),('reserved_bytes',False)])
def test_authenticated_boolean_head_counters_are_not_accepted_as_integer_values(fixture,field,value):
    f=fixture;catalog=f.open(create=True);registry=catalog._registry
    blob=registry.db.execute('SELECT payload FROM head').fetchone()[0]
    payload=json.loads(catalog._unseal(blob,catalog._domain+'membership-head'));payload[field]=value
    altered=catalog._seal(catalog._json(payload),catalog._domain+'membership-head')
    with registry.db:registry.db.execute('UPDATE head SET payload=?',(altered,))
    catalog.close()
    with pytest.raises(TransferError,match='membership_changed'):f.open()
