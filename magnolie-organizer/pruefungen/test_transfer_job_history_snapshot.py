"""Readonly catalog history and exact reservation-list CAS, metadata only."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_transfer_job_catalog import fixture


def test_history_inspection_does_not_allow_nested_reservation_and_original_snapshot_is_usable_afterward(fixture):
    f=fixture;catalog=f.open(create=True);accepted=f.accepted()
    with catalog.inspect_jobs() as (parent,jobs):
        assert parent==f.parent and jobs==()
        with pytest.raises(TransferError,match='history_readonly'):catalog.reserve(accepted,lambda:f.current)
        assert catalog.jobs()==()
    job=catalog.reserve(accepted,lambda:f.current,expected_jobs=jobs)
    assert catalog.jobs()==(job,) and not list(f.destination.iterdir())


def test_another_actual_native_reservation_invalidates_previously_authenticated_history_snapshot(fixture):
    f=fixture;catalog=f.open(create=True)
    with catalog.inspect_jobs() as (_,before):assert before==()
    added=catalog.reserve(f.accepted(),lambda:f.current)
    with pytest.raises(TransferError,match='history_changed'):
        catalog.reserve(f.accepted('b'),lambda:f.current,expected_jobs=before)
    assert catalog.jobs()==(added,) and not list(f.destination.iterdir())


@pytest.mark.parametrize('wire',[[],{},True,({},)])
def test_untyped_history_observation_is_not_a_reservation_grant(fixture,wire):
    f=fixture;catalog=f.open(create=True)
    with pytest.raises(TransferError,match='native_history_required'):
        catalog.reserve(f.accepted(),lambda:f.current,expected_jobs=wire)
    assert catalog.jobs()==() and not list(f.destination.iterdir())
