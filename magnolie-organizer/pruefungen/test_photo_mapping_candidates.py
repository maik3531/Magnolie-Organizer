"""Protected bounded candidate metadata, never current source or deletion rights."""
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import pytest

from test_photo_mappings import native, receiving, mappings, save
from test_photo_version_history_safety import version
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_transfer import TransferError


def test_absent_candidate_read_is_inert_and_invalid_cursor_does_not_poison_the_store(mappings):
    fixture,owner=mappings;root=Path(fixture[0].store.root)
    before={path.name:path.read_bytes() for path in root.iterdir() if path.is_file()}
    snapshot,page,cursor=owner.candidate_page('images')
    assert page==() and cursor is None and snapshot.count==0
    assert not (root/owner._name).exists()
    with pytest.raises(TransferError,match='cursor_changed'):owner.candidate_page('images',after='a'*64,expected=snapshot)
    assert owner.candidate_page('images')[0]==snapshot
    assert before=={path.name:path.read_bytes() for path in root.iterdir() if path.is_file()}


def test_paged_candidates_pin_owner_snapshot_and_never_inspect_or_recreate_actual_targets(mappings,monkeypatch):
    fixture,owner=mappings;receiver,pages,_=save(fixture,count=3)
    snapshot,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    target=fixture[4]/records[0].relative_path;target.unlink() # Synthetic native deletion must not be undone by listing.
    monkeypatch.setattr(NativeAcceptedDestination,'verify',lambda *args:pytest.fail('Candidate enumeration opened a destination'))
    rows=owner._db.execute('SELECT association,payload FROM mappings ORDER BY association').fetchall()
    current,first,cursor=owner.candidate_page('images',limit=1)
    assert current==snapshot and len(first)==1 and cursor==first[0].association.key
    with pytest.raises(TransferError,match='snapshot_changed'):
        owner.candidate_page('images',after=cursor,expected=replace(snapshot,version='f'*64),limit=1)
    current,second,cursor2=owner.candidate_page('images',after=cursor,expected=snapshot,limit=1)
    _,third,end=owner.candidate_page('images',after=cursor2,expected=snapshot,limit=1)
    found=first+second+third
    assert end is None and tuple(record.association.key for record in found)==tuple(sorted(record.association.key for record in records))
    assert {record.protected_record_sha256 for record in found}=={record.protected_record_sha256 for record in records}
    assert all(not record.grants_write_authority and not record.is_saved_receipt for record in found)
    assert owner.candidate_page('video')[1:]==((),None) and not target.exists()
    assert owner._db.execute('SELECT association,payload FROM mappings ORDER BY association').fetchall()==rows


def test_candidates_authenticate_all_version_families_and_select_only_the_current_head(receiving):
    connection,association=version(receiving);owner=connection._mappings
    snapshot,(latest,)=owner.lookup((association,))
    current,records,cursor=owner.candidate_page('images')
    assert current==snapshot and records==(latest,) and cursor is None
    assert latest.saved_sha256==sha256(b'world').hexdigest()
    assert (receiving[4]/latest.relative_path).read_bytes()==b'world'
    assert len(owner._mapping_records(association))==2


@pytest.mark.parametrize('kind',['images','video'])
def test_authenticated_orphan_version_cannot_be_hidden_by_candidate_type_filter(mappings,kind):
    fixture,owner=mappings;receiver,pages,association=save(fixture)
    _,(record,)=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    key=owner._version_key(association,record.receipt_sha256)
    body=dict(format=2,mapping=record.wire(),previous_key=association.key,previous_sha256=record.protected_record_sha256)
    owner._db.execute('INSERT INTO mappings VALUES(?,?)',(key,owner._protect(body,'version/'+key)))
    count,digest=owner._rows_digest()
    old=owner._unprotect(owner._db.execute('SELECT payload FROM owner').fetchone()[0],'owner')
    old.update(revision=old['revision']+1,count=count,mappings_sha256=digest)
    owner._db.execute('UPDATE owner SET payload=? WHERE id=1',(owner._protect(old,'owner'),));owner._db.commit()
    rows=owner._db.execute('SELECT association,payload FROM mappings ORDER BY association').fetchall()
    with pytest.raises(TransferError,match='orphan_member'):owner.candidate_page(kind)
    assert owner._db.execute('SELECT association,payload FROM mappings ORDER BY association').fetchall()==rows
    assert (fixture[4]/record.relative_path).read_bytes()==b'hello'


@pytest.mark.parametrize('variant',[dict(kind='other'),dict(kind='images',limit=True),dict(kind='images',limit=129),
    dict(kind='images',after='a'*64),dict(kind='images',expected={})])
def test_candidate_request_bounds_cannot_create_or_mutate_store(mappings,variant):
    fixture,owner=mappings
    with pytest.raises(TransferError,match='request_invalid'):owner.candidate_page(**variant)
    assert not (Path(fixture[0].store.root)/owner._name).exists()
