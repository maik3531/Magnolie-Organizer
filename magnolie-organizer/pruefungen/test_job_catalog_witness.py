"""Immutable bootstrap witness and strictly owner-only native observation."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_job_catalog_witness import JobCatalogWitness
from test_transfer_job_catalog import fixture


def test_owner_only_probe_works_inside_existing_catalog_lock_without_jobs_or_reservation(fixture):
    f=fixture;catalog=f.open(create=True);choice=catalog.choice()
    with catalog.inspect_jobs():
        observer=f.open(owner_only=True)
        assert observer.verify_witness(choice.witness)==choice.witness
        assert not choice.witness.grants_write_authority
        for callback in (observer.jobs,observer.choice,lambda:observer.reserve(f.accepted(),lambda:f.current)):
            with pytest.raises(TransferError,match='owner_only'):callback()
        observer.close()
    assert catalog.jobs()==() and not list(f.destination.iterdir())


def test_owner_only_probe_cannot_create_catalog_or_accept_untyped_witness(fixture):
    f=fixture
    with pytest.raises(TransferError):f.open(create=True,owner_only=True)
    assert not f.root.exists()
    with pytest.raises(FileNotFoundError):f.open(owner_only=True)
    assert not f.root.exists()
    catalog=f.open(create=True)
    with pytest.raises(TransferError):catalog.verify_witness(catalog.choice().witness.wire())


@pytest.mark.parametrize('part',['root','catalog.lock','owner.enc'])
def test_original_catalog_bootstrap_missing_after_probe_reopen_is_never_created(fixture,part):
    f=fixture;catalog=f.open(create=True);witness=catalog.choice().witness;catalog.close()
    original=f.root if part=='root' else f.root/part
    held=original.with_name(original.name+'-held-original');original.rename(held)
    try:
        with pytest.raises((TransferError,OSError)):
            with f.open(owner_only=True) as observer:observer.verify_witness(witness)
        assert not original.exists() and held.exists()
    finally:held.rename(original)


def test_malformed_witness_values_are_not_coerced(fixture):
    f=fixture;catalog=f.open(create=True);witness=catalog.choice().witness
    for name,value in [('format',True),('receiver_id',False),('owner_sha256','bad'),('owner_key',[1,True]),('root_key',[1,0])]:
        wire=witness.wire();wire[name]=value
        with pytest.raises(TransferError):JobCatalogWitness.parse(wire)
    assert JobCatalogWitness.parse(witness.wire())==witness
