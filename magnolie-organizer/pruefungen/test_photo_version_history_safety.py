"""Version heads cannot turn incomplete/corrupt native history into authority."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_file_media_history import NativeMediaHistory
from magnolie_photo_mappings import ProtectedPhotoMappings,PhotoMappingAssociation
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_album_worker import prepared
from test_photo_version_workflow import cycle,changed


def version(fixture):
    connection=fixture[3];full=prepared(fixture)[0]
    assert cycle(fixture,full)[0]['state']=='complete'
    assert cycle(fixture,changed(full,'c',b'world'),b'world')[0]['state']=='complete'
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    return connection,association


def test_version_history_is_strict_local_metadata_not_read_or_write_authority(receiving):
    connection,association=version(receiving);_,(mapping,)=connection._mappings.lookup((association,))
    job=next(job for job in connection._catalog.jobs() if job.owner==mapping.job_owner)
    protection=connection._authority.protection
    with connection._catalog.inspect_jobs() as (parent,_):
        with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,lambda:None,
                protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
            history=index.media_history
    assert history.wire()['format']==3 and history.version_parents
    assert not history.grants_write_authority and not history.is_saved_receipt
    assert NativeMediaHistory.parse(history.wire(),job.accepted)==history
    variants=[]
    for field in ('mapping_store','version_parents'):
        value=deepcopy(history.wire());value.pop(field);variants.append(value)
    value=deepcopy(history.wire());value['version_parents']*=2;variants.append(value)
    value=deepcopy(history.wire());value['version_parents'][0]['photo_id']='d'*64;variants.append(value)
    value=deepcopy(history.wire());value['version_parents'][0]['record_sha256']='invalid';variants.append(value)
    value=deepcopy(history.wire());value['insertion_witness']=False;variants.append(value)
    value=deepcopy(history.wire());value['format']=2;variants.append(value)
    value=deepcopy(history.wire());value['version_parents'][0]['permission']=True;variants.append(value)
    for value in variants:
        with pytest.raises(TransferError):NativeMediaHistory.parse(value,job.accepted)


@pytest.mark.parametrize('change',['cycle','wrong_predecessor','missing_original'])
def test_authenticated_but_invalid_version_chain_stays_held_without_touching_user_files(receiving,change):
    connection,association=version(receiving);owner=connection._mappings
    before={path.relative_to(receiving[4]):(path.stat().st_ino,path.read_bytes()) for path in receiving[4].rglob('*') if path.is_file()}
    _,(record,)=owner.lookup((association,));key=owner._version_key(association,record.receipt_sha256)
    if change=='missing_original':
        owner._db.execute('DELETE FROM mappings WHERE association=?',(association.key,))
    else:
        blob=owner._db.execute('SELECT payload FROM mappings WHERE association=?',(key,)).fetchone()[0]
        value=owner._unprotect(blob,'version/'+key)
        if change=='cycle':value['previous_key']=key
        else:value['previous_sha256']='e'*64
        blob=owner._protect(value,'version/'+key)
        owner._db.execute('UPDATE mappings SET payload=? WHERE association=?',(blob,key))
        head_key=owner._head_key(association)
        blob_head=owner._db.execute('SELECT payload FROM mappings WHERE association=?',(head_key,)).fetchone()[0]
        head=owner._unprotect(blob_head,'head/'+head_key);head['record_sha256']=sha256(blob).hexdigest()
        owner._db.execute('UPDATE mappings SET payload=? WHERE association=?',(owner._protect(head,'head/'+head_key),head_key))
    # Authenticate the aggregate too: the test must reach chain invariants, not
    # merely reject an unprotected byte edit. Only synthetic fixture records.
    count,digest=owner._rows_digest()
    previous=owner._db.execute('SELECT payload FROM owner WHERE id=1').fetchone()[0]
    header=owner._unprotect(previous,'owner');header.update(revision=header['revision']+1,count=count,mappings_sha256=digest)
    owner._db.execute('UPDATE owner SET payload=? WHERE id=1',(owner._protect(header,'owner'),))
    owner._db.commit();owner.close()
    reopened=ProtectedPhotoMappings(connection._authority);connection._mappings=reopened
    with pytest.raises(TransferError,match='version_(chain_changed|original_required)'):
        reopened.lookup((association,))
    assert {path.relative_to(receiving[4]):(path.stat().st_ino,path.read_bytes()) for path in receiving[4].rglob('*') if path.is_file()}==before


def test_lost_version_mapping_receipt_requires_explicit_metadata_repair_without_republication(receiving,monkeypatch):
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    protect=ProtectedTransferJobIndex._protect
    failed=[]
    def lost(self,value,label):
        if label=='mapping-receipt' and not failed:
            failed.append(True)
            raise OSError('Fixture version mapping receipt not committed')
        return protect(self,value,label)
    monkeypatch.setattr(ProtectedTransferJobIndex,'_protect',lost)
    state,_,saved=cycle(receiving,changed(full,'c',b'world'),b'world')
    assert failed and state['state']=='held' and not saved,state
    monkeypatch.setattr(ProtectedTransferJobIndex,'_protect',protect)
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    _,(current,)=connection._mappings.lookup((association,))
    assert (receiving[4]/current.relative_path).read_bytes()==b'world'
    assert (receiving[4]/full.files[0].path).read_bytes()==b'hello'
    with pytest.raises(TransferError,match='complete_evidence_required'):
        connection.recover_saved_confirmation(connection.issue_receive_action(),current.job_owner)
    before={path.relative_to(receiving[4]):(path.stat().st_ino,path.read_bytes()) for path in receiving[4].rglob('*') if path.is_file()}
    def forbidden(*args,**kwargs):pytest.fail('Metadata repair must not recreate source, stage or publisher')
    for name in ('EncryptedTransferStage','ProtectedPublicationJournal','NativeFilePublisher'):
        monkeypatch.setattr('magnolie_file_receive.'+name,forbidden)
    receipt=connection.repair_saved_mapping_receipt(connection.issue_receive_action(),current.job_owner)
    assert receipt.owner==current.job_owner
    assert connection.recover_saved_confirmation(connection.issue_receive_action(),current.job_owner)==receipt
    assert {path.relative_to(receiving[4]):(path.stat().st_ino,path.read_bytes()) for path in receiving[4].rglob('*') if path.is_file()}==before
