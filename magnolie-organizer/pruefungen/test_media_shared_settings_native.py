"""#429: actual native shared-setting actions, independent of RECEIVE/SEND."""
from pathlib import Path
from types import SimpleNamespace
import ast
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
import pytest
import magnolie_telefon as phone
import magnolie_hintergrund as background
from magnolie_file_control import KIND as CONTROL
from test_file_authenticated_desktop import native
from test_media_sending_setup import setup_peer
from test_media_source_connection import dispatch
from test_media_source_sender import message
from test_media_source_connection import source,receiving,mappings,composition
from test_media_source_worker import warm_metadata


def confirm(h):
    state=h.service.photo_sync_state(h.peer['device_id'])
    selected=h.service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'prepare',True,False,None,state['sending_setup']['version'])
    h.service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'commit',None,None,selected['selection'],None)
    assert h.wire.receive()['kind']==CONTROL
    return h.service._native_file_connections[h.channel]


def change(h,field,value,version):
    return h.service.photo_sync_action(h.peer['device_id'],h.fingerprint,
        dict(action='shared_setting',field=field,value=value,version=version))


def prime_receiving(h,service):
    """Real encrypted native control/status/catalog preconditions, not booleans."""
    from magnolie_file_control import FileControlPacket,FileGrantState
    import magnolie_file_sources as sources
    from test_file_desktop_sources import response,ALBUM,CATALOG
    warm_metadata(h,service);c=h.connection;session=c.desktop_session()
    session._local_enabled(True)
    first=FileControlPacket.parse(h.wire.receive()['body'])
    remote=FileControlPacket(FileGrantState(1,'6'*64,True,True),'7'*64,1,first.challenge)
    dispatch(h,service,message(CONTROL,remote.wire()));h.wire.receive()
    c.request_source(c.issue_receive_action(),'status');request=h.wire.receive()
    dispatch(h,service,response(request,sources.RESULT,version='b'*64,revision=2,enabled=True,
        associated=True,repair_pending=False,kinds=sorted(sources.KINDS)))
    refreshed=FileControlPacket(remote.grants,remote.session_epoch,2,first.challenge)
    dispatch(h,service,message(CONTROL,refreshed.wire())) # Same challenge needs no redundant echo.
    session.start('discover');discover=h.wire.receive()
    dispatch(h,service,response(discover,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
        after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
        albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    assert session.join(15) and session.snapshot()['state']=='albums',session.snapshot()
    return c,session


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


@pytest.mark.parametrize('valid',[True,False])
def test_actual_gtk_action_echoes_only_bounded_request_ids_and_reaches_native_setting(native,tmp_path,valid):
    with setup_peer(native,tmp_path,'fresh') as h:
        c=confirm(h);answers=[];reports=[];before=c._preferences.read()
        tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
        method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
            if isinstance(node,ast.FunctionDef) and node.name=='_telefon_foto_aktion')
        namespace={'_':lambda text:text}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-shared-setting-action','exec'),namespace)
        server=background.IPCServer(None,str(tmp_path/'shared-choice.sock'),phone_backend=h.service,
            settings_getter=lambda:background.normalize_settings({})).start()
        try:
            window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),antwort=lambda name,value:answers.append((name,value)),
                _telefon_stand_melden=lambda:reports.append(True))
            request=dict(action='shared_setting',field='direction',value='pc_to_phone',version=c.desktop_snapshot()['shared_media']['version'])
            payload=dict(kennung=h.peer['device_id'],fingerprint=h.fingerprint,request=request,requestId='actual-shared-choice' if valid else 'x'*129)
            namespace['_telefon_foto_aktion'](window,payload)
        finally:server.close()
        assert len(answers)==1 and reports==[True] and answers[0][0]=='App.telefonFotoErgebnis'
        assert answers[0][1]['ok'] is valid
        if valid:
            assert answers[0][1]['requestId']=='actual-shared-choice'
            assert h.wire.receive()['kind']=='file_transfer.shared_settings'
        else:
            assert 'requestId' not in answers[0][1] and c._media_transport._store.read() is None
        assert c._preferences.read()==before and c._source_pending is None


@pytest.mark.parametrize('state',['disabled','unconfirmed'])
def test_selected_legacy_start_cannot_bypass_configured_shared_off_or_pending_agreement(source,native,monkeypatch,state):
    from magnolie_file_transfer import TransferError
    from test_file_desktop_sources import ALBUM
    with composition(source,native[0]) as h:
        c,session=prime_receiving(h,native[0])
        h.controller.change('enabled',False) if state=='disabled' else h.controller.change('direction','phone_to_pc')
        offered=h.controller.send_settings();assert h.wire.receive()==offered
        if state=='disabled':
            dispatch(h,native[0],dict(type='ack',message_id=offered['message_id'],status='accepted',error='none'))
            dispatch(h,native[0],message('file_transfer.shared_settings',offered['body']));assert h.wire.receive()['type']=='ack'
        assert c._receive_binding() is not None # Real independent receiving consent/control still positive.
        attempted=[]
        def blocked(*args,**kwargs):attempted.append(args[1]);raise TransferError('unexpected_shared_phone_request')
        monkeypatch.setattr(c,'request_source',blocked)
        native[0].photo_sync_action(h.peer['device_id'],phone.fingerprint(phone.unb64(h.peer['static_public'],32)),dict(action='sync',album_id=ALBUM))
        assert session.join(15),session.snapshot()
        assert not attempted,'Legacy selected action bypassed shared '+state+': '+str(attempted)
        assert session.snapshot()['state']=='held' and session.snapshot()['error']=='media_source_current_intent_required'
