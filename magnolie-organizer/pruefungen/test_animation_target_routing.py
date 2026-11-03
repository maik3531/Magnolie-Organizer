"""Only fresh animations are routed; original jobs/locations always win."""
from base64 import b64decode
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import FileManifest,ManifestFile,TransferError
from magnolie_photo_mappings import PhotoMappingAssociation
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,negotiate,chunk,reconnect,offer as direct_offer
from test_file_desktop_sources import ready_source,request
from test_file_desktop_media import media,dispatch,send_offer
from test_file_desktop_mapping_save import saved_messages

# Two actual GIF image blocks; the PNG is a one-pixel static image. These are
# byte/hash transport fixtures, not a semantic photograph/graphic classifier.
GIF=bytes.fromhex('47494638396101000100800000000000ffffff')+2*bytes.fromhex('21f90400010000002c0000000001000100000202440100')+b';'
PNG=b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jB9sAAAAASUVORK5CYII=')


def settings(fixture,enabled):
    connection=fixture[3];prefs=connection._preferences
    prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',separate_animations=enabled)
    negotiate(*fixture[:4])


def offered(fixture,*,paths=('Camera/clip.gif','Camera/still.png'),kinds=('animation','image')):
    connection=fixture[3];ready_source(fixture)
    data=(GIF,PNG)[:len(paths)]
    full=FileManifest('1'*32,'2'*32,fixture[1]['device_id'],fixture[0].store.identity['device_id'],
        tuple(ManifestFile(f'{i+1:032x}',path,len(data[i]),sha256(data[i]).hexdigest()) for i,path in enumerate(paths)),sum(map(len,data)))
    req=request(fixture,'media_page');reply=media(req,full)
    for entry,kind in zip(reply['body']['page']['entries'],kinds):entry['media_kind']=kind
    dispatch(fixture,reply);message,result=send_offer(fixture,full);dispatch(fixture,result)
    return full,data,message


def receive_all(fixture,full,data,message):
    connection=fixture[3];connection.accept_pending_offer(connection.issue_receive_action(),message['message_id'])
    for payload in data:dispatch(fixture,chunk(connection.request_next_chunk(),payload))
    return connection._run.receiver


@pytest.mark.parametrize('separate',[False,True])
def test_new_animation_and_static_image_use_exact_native_targets_saved_mappings_and_fresh_recovery(receiving,separate):
    connection=receiving[3];settings(receiving,separate);full,data,message=offered(receiving)
    receiver=receive_all(receiving,full,data,message);accepted=receiver._accepted
    wanted={full.files[0].id:('Animationen/' if separate else '')+full.files[0].path,full.files[1].id:full.files[1].path}
    assert dict(accepted.targets)==wanted and receiver._index.accepted_transfer==accepted
    assert all(not (receiving[4]/path).exists() for path in wanted.values())
    connection.publish_received(connection.issue_receive_action())
    receipts=receiver._index.saved_receipts();evidence=receiver._index.saved_mapping_receipt()
    assert len(receipts)==2 and evidence is not None and len(saved_messages(receiving))==1
    for file,payload in zip(full.files,data):
        assert (receiving[4]/wanted[file.id]).read_bytes()==payload
    history=receiver._index.media_history
    associations=tuple(PhotoMappingAssociation(history.source_epoch,e.photo_id,history.media_type) for e in history.entries)
    _,records=connection._mappings.lookup(associations)
    assert {record.source_file_id:record.relative_path for record in records}==wanted
    assert records[0].association.media_type=='images' and not connection.read_preferences().include_videos
    if separate:(receiving[4]/wanted[full.files[0].id]).write_bytes(b'preserve newer PC animation edit')
    with reconnect(receiving) as fresh:
        assert fresh[3].recover_saved_confirmation(fresh[3].issue_receive_action(),receiver.job.owner)==evidence
        assert len(fresh[3]._catalog.jobs())==1
    if separate:assert (receiving[4]/wanted[full.files[0].id]).read_bytes()==b'preserve newer PC animation edit'


def test_routed_target_collision_is_rejected_before_any_job_or_target_is_created(receiving,monkeypatch):
    connection=receiving[3];settings(receiving,True)
    full,data,message=offered(receiving,paths=('Camera/clip.gif','Animationen/Camera/clip.gif'))
    before=tuple(Path(connection._authority.binding.native_directory).iterdir())
    def forbidden(*args,**kwargs):raise AssertionError('colliding routed targets must fail before reservation')
    monkeypatch.setattr(ProtectedTransferJobCatalog,'reserve',forbidden)
    with pytest.raises(TransferError):connection.accept_pending_offer(connection.issue_receive_action(),message['message_id'])
    assert connection._run is None and connection._catalog.jobs()==() and not list(receiving[4].iterdir())
    assert tuple(Path(connection._authority.binding.native_directory).iterdir())==before


def test_new_animation_cannot_overwrite_existing_user_file_in_special_folder(receiving):
    connection=receiving[3];settings(receiving,True);full,data,message=offered(receiving,paths=('Camera/clip.gif',),kinds=('animation',))
    receiver=receive_all(receiving,full,data,message)
    target=receiving[4]/'Animationen/Camera/clip.gif';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(b'preserve user animation edit');inode=target.stat().st_ino
    with pytest.raises(TransferError):connection.publish_received(connection.issue_receive_action())
    assert target.read_bytes()==b'preserve user animation edit' and target.stat().st_ino==inode
    assert not saved_messages(receiving) and len(connection._catalog.jobs())==1
    assert not receiver._index.saved_receipts()


def test_animation_preference_without_correlated_media_cannot_fall_back_to_unrouted_legacy_target(receiving):
    connection=receiving[3];settings(receiving,True);message,_=direct_offer(receiving)
    with pytest.raises(TransferError,match='source_media_not_correlated'):
        connection.accept_pending_offer(connection.issue_receive_action(),message['message_id'])
    assert connection._run is None and connection._catalog is None and not list(receiving[4].iterdir())


@pytest.mark.parametrize('initial',[False,True])
def test_grouping_change_keeps_original_mapping_and_location_without_new_copy_or_move(receiving,initial):
    connection=receiving[3];settings(receiving,initial)
    full,data,message=offered(receiving,paths=('Camera/clip.gif',),kinds=('animation',))
    receiver=receive_all(receiving,full,data,message);connection.publish_received(connection.issue_receive_action())
    receipt=receiver._index.saved_receipts()[0];target=receiving[4]/receipt.relative_path
    original=(target.read_bytes(),target.stat().st_ino);snapshot=connection._mappings.read();jobs=connection._catalog.jobs()
    receiver.close();connection._run=None
    settings(receiving,not initial)
    # End the old native source-run owner before any fresh source run; do not
    # bypass the no-overlap guard or retire the original held job/quota.
    with reconnect(receiving) as fresh:
        reopened=fresh[3];_,_,again=offered(fresh,paths=('Camera/clip.gif',),kinds=('animation',))
        with pytest.raises(TransferError,match='requires_reconcile'):
            reopened.accept_pending_offer(reopened.issue_receive_action(),again['message_id'])
        assert reopened._run is None and reopened._mappings.read()==snapshot
        assert reopened._open_catalog(allow_create=False) and reopened._catalog.jobs()==jobs
    assert (target.read_bytes(),target.stat().st_ino)==original
    other=receiving[4]/(('' if initial else 'Animationen/')+full.files[0].path)
    assert not other.exists()
