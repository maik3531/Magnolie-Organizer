"""#429: actual native shared-setting actions, independent of RECEIVE/SEND."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
import pytest
import magnolie_telefon as phone
from magnolie_file_control import KIND as CONTROL
from test_file_authenticated_desktop import native
from test_media_sending_setup import setup_peer
from test_media_source_connection import dispatch
from test_media_source_sender import message


def confirm(h):
    state=h.service.photo_sync_state(h.peer['device_id'])
    selected=h.service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'prepare',True,False,None,state['sending_setup']['version'])
    h.service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'commit',None,None,selected['selection'],None)
    assert h.wire.receive()['kind']==CONTROL
    return h.service._native_file_connections[h.channel]


def change(h,field,value,version):
    return h.service.photo_sync_action(h.peer['device_id'],h.fingerprint,
        dict(action='shared_setting',field=field,value=value,version=version))


def test_actual_native_shared_setting_cas_and_ack_do_not_enable_reception_or_rewrite_sending(native,tmp_path,monkeypatch):
    with setup_peer(native,tmp_path,'fresh') as h:
        c=confirm(h);before=c._preferences.read();owner=c._local().owner
        state=c.desktop_snapshot()
        assert state.get('shared_media'),'New SEND-only source has no shared settings entry'
        version=state['shared_media']['version']
        change(h,'direction','pc_to_phone',version)
        packet=h.wire.receive();assert packet['kind']=='file_transfer.shared_settings'
        projected=c.desktop_snapshot()['shared_media']
        assert projected['values']['direction']=='pc_to_phone' and not projected['agreed']
        assert projected['version']!=version and c._media_transport.intent_for('images',to_phone=True) is None
        with monkeypatch.context() as patch:
            patch.setattr(c._media_transport._store,'read',lambda:pytest.fail('Passive native display opened shared store'))
            assert h.service.photo_sync_state(h.peer['device_id'])['shared_media']==projected
        with pytest.raises((ValueError,RuntimeError)):change(h,'enabled',True,version)
        assert c.desktop_snapshot()['shared_media']==projected and c._preferences.read()==before
        dispatch(h,h.service,dict(type='ack',message_id=packet['message_id'],status='accepted',error='none'))
        dispatch(h,h.service,message('file_transfer.shared_settings',packet['body']))
        assert h.wire.receive()['type']=='ack'
        assert c.desktop_snapshot()['shared_media']['agreed']
        assert c._preferences.read()==before and c._local().owner is owner
        assert not c._local().grants.receive_files and c._source_pending is None and c._mapped_worker is None


def test_native_import_scope_keeps_configured_direction_and_never_creates_export_authority(native,tmp_path):
    with setup_peer(native,tmp_path,'fresh') as h:
        c=confirm(h)
        for field,value in [('direction','pc_to_phone'),('collection_mode','import_only'),('enabled',True)]:
            shared=c.desktop_snapshot()['shared_media']
            change(h,field,value,shared['version'])
            packet=h.wire.receive()
            dispatch(h,h.service,dict(type='ack',message_id=packet['message_id'],status='accepted',error='none'))
            dispatch(h,h.service,message('file_transfer.shared_settings',packet['body']));assert h.wire.receive()['type']=='ack'
        assert c.desktop_snapshot()['shared_media']['values']['direction']=='pc_to_phone'
        assert c.desktop_snapshot()['shared_media']['values']['collection_mode']=='import_only'
        assert c._media_transport.intent_for('images',to_phone=True) is None
        assert not c._preferences.read().policy.enabled and c._source_pending is None


@pytest.mark.parametrize('field,value',[('enabled','yes'),('direction','file:///tmp/not-a-mode'),
    ('unknown',True),(['enabled'],True),('photos_enabled',1),('auto_mode','automatic')])
def test_invalid_native_shared_setting_does_not_create_records_or_change_grants(native,tmp_path,field,value):
    with setup_peer(native,tmp_path,'fresh') as h:
        c=confirm(h);before=c.desktop_snapshot()['shared_media'];policy=c._preferences.read()
        with pytest.raises((ValueError,RuntimeError)):change(h,field,value,before['version'])
        assert c.desktop_snapshot()['shared_media']==before and c._media_transport._store.read() is None
        assert c._preferences.read()==policy and c._source_pending is None and c._mapped_worker is None
