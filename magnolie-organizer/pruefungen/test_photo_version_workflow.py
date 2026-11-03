"""Real phone-change publication keeps immutable original/earlier save history."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_mappings import PhotoMappingAssociation,photo_version_path
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,reconnect,chunk
from test_file_desktop_album_worker import prepared,phone_batches,ALBUM
from test_file_desktop_sources import ready_source,request
from test_file_desktop_media import media,dispatch,send_offer


def cycle(fixture,full,data=b'hello',**options):
    connection=fixture[3]
    with phone_batches(fixture,[full],insertion_witness=True,content=data,**options) as (chunks,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(40),worker.progress()
        assert not errors
        return worker.progress(),tuple(chunks),tuple(saved)


def changed(full,char,data):
    return replace(full,source_id=char*32,transfer_id=char*32,files=(replace(full.files[0],id=char*32,
        size=len(data),sha256=sha256(data).hexdigest()),),total_bytes=len(data))


def test_changed_phone_versions_publish_without_replacement_and_preserve_all_receipts_and_pc_crops(receiving):
    connection=receiving[3];target=receiving[4];full=prepared(receiving)[0]
    state,chunks,saved=cycle(receiving,full)
    assert state['state']=='complete' and len(chunks)==len(saved)==1,state
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    _,(original,)=connection._mappings.lookup((association,))
    original_blob=connection._mappings._db.execute('SELECT payload FROM mappings WHERE association=?',(association.key,)).fetchone()[0]
    original_target=target/full.files[0].path;before=(original_target.stat().st_ino,original_target.read_bytes())
    evidence=[]
    for char,data in (('c',b'world'),('d',b'again')):
        full=changed(full,char,data)
        state,chunks,saved=cycle(receiving,full,data)
        assert state['state']=='complete' and len(chunks)==len(saved)==1,state
        _,(current,)=connection._mappings.lookup((association,))
        path=target/photo_version_path(association,full.files[0])
        assert path.read_bytes()==data and current.relative_path==str(path.relative_to(target))
        assert (original_target.stat().st_ino,original_target.read_bytes())==before
        assert connection._mappings._db.execute('SELECT payload FROM mappings WHERE association=?',(association.key,)).fetchone()[0]==original_blob
        _,(old,)=connection._mappings.lookup_saved((association,),(original.receipt_sha256,))
        assert old==original
        evidence.append((current,path,path.stat().st_ino,data))
        # A fresh scan of the same frozen content is metadata-only.
        repeat=changed(full,'e' if char=='c' else 'f',data)
        state,chunks,saved=cycle(receiving,repeat,data)
        assert state['state']=='complete' and state['known_files']==1 and not chunks and not saved,state
    assert connection._mappings.read().count==4 # Immutable root + 2 versions + separate head.
    for record,path,inode,data in evidence:
        assert (path.stat().st_ino,path.read_bytes())==(inode,data)
        _,(old,)=connection._mappings.lookup_saved((association,),(record.receipt_sha256,))
        assert old==record
    protection=connection._authority.protection
    with connection._catalog.inspect_jobs() as (parent,jobs):
        assert len(jobs)==3 and all(job.reserved_bytes==0 for job in jobs)
        for job in jobs:
            with ProtectedTransferJobIndex(parent,job.accepted.manifest,job.accepted.binding,lambda:None,
                    protection.seal,protection.unseal,owner=job.owner,accepted=job.accepted) as index:
                connection._verify_completed_mapping_job(index,job,index.media_history)
                if job.owner!=original.job_owner:assert index.media_history.version_parents
    latest=evidence[-1][1];latest.write_bytes(b'PC crop of latest phone version')
    latest_before=(latest.stat().st_ino,latest.read_bytes())
    state,chunks,saved=cycle(receiving,changed(full,'2',b'again'),b'again')
    assert state['state']=='complete' and not chunks and not saved,state
    assert (latest.stat().st_ino,latest.read_bytes())==latest_before
    state,chunks,saved=cycle(receiving,changed(full,'3',b'other'),b'other')
    assert state['state']=='conflicts' and not chunks and not saved,state
    assert state['conflicts'][0].decision=='conflict_edit_edit'
    assert (latest.stat().st_ino,latest.read_bytes())==latest_before
    assert (original_target.stat().st_ino,original_target.read_bytes())==before


def test_version_stop_resumes_exact_verified_job_but_unknown_publication_stays_held(receiving):
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    original=receiving[4]/full.files[0].path;before=(original.stat().st_ino,original.read_bytes())
    full=changed(full,'c',b'world')
    with phone_batches(receiving,[full],insertion_witness=True,content=b'world',block_chunk=True) as (_,saved,entered,release,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10),worker.progress()
        job=connection._run.job
        history=connection._run.receiver._index.media_history
        assert history.version_parents and history.wire()['format']==3
        worker.stop();release.set();assert worker.join(20),worker.progress()
        assert not saved and not errors and worker.progress()['state']=='canceled',worker.progress()
    assert (original.stat().st_ino,original.read_bytes())==before
    assert connection._run is None and job.owner in {item.owner for item in connection._catalog.jobs()}
    ready_source(receiving)
    req=request(receiving,'media_page');reply=media(req,job.accepted.manifest)
    reply['body']['page']['insertion_witness']=True
    reply['body']['page']['entries'][0]['photo_id']=history.entries[0].photo_id
    dispatch(receiving,reply)
    offered,result=send_offer(receiving,job.accepted.manifest);dispatch(receiving,result)
    connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run.job.owner==job.owner and connection._run.receiver._index.media_history==history
    while True:
        req=connection.request_next_chunk()
        if req is None:break
        dispatch(receiving,chunk(req,b'world'))
    # Existing restart safety deliberately has no proof that publication never
    # began. Verified source bytes are not permission to recreate a publisher.
    before_send=receiving[2].send.call_count
    with pytest.raises(TransferError,match='publication_repair_required'):
        connection.publish_received(connection.issue_receive_action())
    assert receiving[2].send.call_count==before_send
    assert (original.stat().st_ino,original.read_bytes())==before
    assert connection._run.job.owner==job.owner and connection._run.receiver._index.media_history==history
    assert len(connection._catalog.jobs())==2
    assert next(item for item in connection._catalog.jobs() if item.owner==job.owner).reserved_bytes>0


def test_existing_version_target_is_not_adopted_or_overwritten_and_original_head_stays_unchanged(receiving):
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    snapshot,records=connection._mappings.lookup((association,));full=changed(full,'c',b'world')
    path=receiving[4]/photo_version_path(association,full.files[0]);path.parent.mkdir(mode=0o700,parents=True)
    path.write_bytes(b'world');before=(path.stat().st_ino,path.read_bytes())
    state,_,saved=cycle(receiving,full,b'world')
    assert state['state']=='held' and not saved,state
    assert (path.stat().st_ino,path.read_bytes())==before
    assert connection._mappings.lookup((association,))==(snapshot,records)
    assert (receiving[4]/'Camera/0.jpg').read_bytes()==b'hello'


def test_restart_uses_immutable_receipts_for_original_and_version_without_republication(receiving,monkeypatch):
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    assert cycle(receiving,changed(full,'c',b'world'),b'world')[0]['state']=='complete'
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    snapshot,records=connection._mappings.lookup((association,));jobs=connection._catalog.jobs()
    before={path.relative_to(receiving[4]):(path.stat().st_ino,path.read_bytes()) for path in receiving[4].rglob('*') if path.is_file()}
    with reconnect(receiving) as fresh:
        reopened=fresh[3]
        assert reopened._mappings.lookup((association,))==(snapshot,records)
        def forbidden(*args,**kwargs):pytest.fail('Historical version recovery reopened publication/cache/source')
        monkeypatch.setattr(reopened._mappings,'commit_saved_history',forbidden)
        for job in jobs:
            evidence=reopened.recover_saved_confirmation(reopened.issue_receive_action(),job.owner)
            assert evidence.owner==job.owner
        assert reopened._run is None
        assert [call.args[0]['kind'] for call in fresh[2].send.call_args_list]==['file_transfer.saved']*2
    assert {path.relative_to(receiving[4]):(path.stat().st_ino,path.read_bytes()) for path in receiving[4].rglob('*') if path.is_file()}==before


def test_mixed_new_photo_and_changed_version_share_real_batch_without_replacing_old_target(receiving):
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    first=changed(full,'c',b'world');new=replace(first.files[0],id='d'*32,path='Camera/new.jpg')
    mixed=replace(first,files=(first.files[0],new),total_bytes=10)
    photos={'Camera/0.jpg':sha256(b'worker-photo-0').hexdigest(),'Camera/new.jpg':sha256(b'worker-new-photo').hexdigest()}
    state,chunks,saved=cycle(receiving,mixed,b'world',photo_ids=photos)
    assert state['state']=='complete' and state['saved_files']==2 and len(chunks)==2 and len(saved)==1,state
    assert (receiving[4]/'Camera/0.jpg').read_bytes()==b'hello'
    assert (receiving[4]/'Camera/new.jpg').read_bytes()==b'world'
    assert connection._mappings.read().count==4
    repeat=replace(mixed,source_id='e'*32,transfer_id='e'*32)
    state,chunks,saved=cycle(receiving,repeat,b'world',photo_ids=photos)
    assert state['state']=='complete' and state['known_files']==2 and not chunks and not saved,state


def test_pc_edit_during_version_download_is_held_before_publication_or_head_advance(receiving):
    connection=receiving[3];full=prepared(receiving)[0]
    assert cycle(receiving,full)[0]['state']=='complete'
    before=connection._mappings.read();target=receiving[4]/full.files[0].path
    version=changed(full,'c',b'world')
    with phone_batches(receiving,[version],insertion_witness=True,content=b'world',block_chunk=True) as (_,saved,entered,release,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert entered.wait(10),worker.progress()
        target.write_bytes(b'concurrent PC edit must survive');inode=target.stat().st_ino
        release.set();assert worker.join(20),worker.progress()
        assert not errors and worker.progress()['state']=='held' and not saved,worker.progress()
        assert worker.progress()['error']=='file_desktop_photo_version_parent_edited'
    assert target.read_bytes()==b'concurrent PC edit must survive' and target.stat().st_ino==inode
    assert connection._mappings.read()==before and not list(receiving[4].glob('Versionen/**/*.jpg'))
