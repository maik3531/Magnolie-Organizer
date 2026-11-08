"""#429: explicit first SEND setup, never a receiving/bootstrap side effect."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import ast
import socket
import sqlite3
import sys
import threading
import time
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
import magnolie_telefon as phone
import magnolie_hintergrund as background
from magnolie_file_native_authority import capture_authenticated_binding
from magnolie_media_retention import NativeMediaRetention
from magnolie_photo_preferences import ProtectedPhotoPreferences
from test_file_authenticated_desktop import native
from test_media_transport import PeerWire
from test_media_source_worker import warm_metadata


@contextmanager
def setup_peer(native,tmp_path,profile):
    service,peer,_=native
    peer['capabilities']['items']['device_status']['versions'].append(23)
    if profile=='fresh':peer.pop('file_pairing_epoch')
    service.store.save_peers()
    book=tmp_path/'daten.json'
    book.write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":0}}}');book.chmod(0o600)
    with NativeMediaRetention(service.store.root) as policy:assert policy.adopt_existing_saved()
    left,right=socket.socketpair();left.settimeout(2);right.settimeout(10)
    channel=phone.SecureChannel(left,bytes([3])*16,bytes([1])*32,bytes([1])*4,bytes([2])*32,bytes([2])*4)
    binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
    service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
    h=SimpleNamespace(peer=peer,channel=channel,wire=PeerWire(right),service=service,
        fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32)))
    try:
        if profile=='off':
            authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
            try:
                prefs=ProtectedPhotoPreferences(authority)
                try:
                    prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=True,videos=False)
                    prefs.configure_sending(prefs.issue_action(),prefs.read(),photos=False,videos=False)
                finally:prefs.close()
            finally:authority.close()
        warm_metadata(h,service)
        assert channel not in service._native_file_connections
        yield h
    finally:
        service._end_native_file_connection(channel);left.close();right.close()


def files(root):
    result={}
    for path in Path(root).rglob('*'):
        if not path.is_file() or path.name in ('phone.db-wal','phone.db-shm'):continue
        if path.name=='phone.db':
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:result[str(path.relative_to(root))]='\n'.join(db.iterdump())
        else:result[str(path.relative_to(root))]=path.read_bytes()
    return result


@pytest.mark.parametrize('profile',['fresh','off'])
def test_first_send_prepare_cancel_and_confirm_do_not_require_receiving(native,tmp_path,profile):
    with setup_peer(native,tmp_path,profile) as h:
        service=h.service;root=Path(service.store.root);before=files(root)
        state=service.photo_sync_state(h.peer['device_id'])
        assert state.get('sending_setup'),'SEND setup is unavailable unless receiving was enabled first'
        assert files(root)==before and h.channel not in service._native_file_connections
        def call(operation,**kwargs):
            return service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,operation,
                kwargs.get('photos'),kwargs.get('videos'),kwargs.get('selection'),kwargs.get('version'))
        choice=call('prepare',photos=True,videos=False,version=state['sending_setup']['version'])
        assert not choice['current_photos'] and not choice['current_videos']
        assert files(root)==before and h.channel not in service._native_file_connections
        assert call('cancel',selection=choice['selection'])==dict(canceled=True)
        assert files(root)==before and h.channel not in service._native_file_connections
        with pytest.raises((ValueError,RuntimeError)):call('commit',selection=choice['selection'])
        choice=call('prepare',photos=True,videos=False,version=state['sending_setup']['version'])
        result=call('commit',selection=choice['selection'])
        assert result['photos'] and not result['videos']
        connection=service._native_file_connections[h.channel]
        policy=connection._preferences.read().policy
        assert not policy.enabled and policy.sending.photos and not policy.sending.videos
        assert policy.destination is None and policy.mapping_store is None and policy.job_catalog is None
        assert connection._media_source is not None and not connection._media_source._prepared
        assert connection._source_pending is None and connection._mapped_worker is None
        assert not connection._local().grants.receive_files
        assert files(root)['storage.key']==before['storage.key']


@pytest.mark.parametrize('fault',['book','metadata','superseded','expired','fingerprint'])
def test_first_send_setup_failure_never_initializes_pairing_or_grants(native,tmp_path,fault):
    with setup_peer(native,tmp_path,'fresh') as h:
        service=h.service;state=service.photo_sync_state(h.peer['device_id'])
        choice=service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'prepare',True,False,None,state['sending_setup']['version'])
        if fault=='book':(tmp_path/'daten.json').write_text('{"changed":"saved book replaced"}')
        if fault=='metadata':service._native_file_controls[h.channel].pop('grants.update')
        if fault=='expired':
            ticket=service._native_sending_setups[h.channel]
            service._native_sending_setups[h.channel]=(ticket[0],time.monotonic()-1,*ticket[2:])
        latest=None
        if fault=='superseded':
            latest=service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'prepare',False,True,None,state['sending_setup']['version'])
        before=files(Path(service.store.root))
        with pytest.raises((ValueError,RuntimeError)):
            service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint if fault!='fingerprint' else 'wrong',
                'commit',None,None,choice['selection'],None)
        assert files(Path(service.store.root))==before and 'file_pairing_epoch' not in h.peer
        assert h.channel not in service._native_file_connections
        if latest is not None:assert service._native_sending_setups[h.channel][0]==latest['selection']
        if fault=='metadata':
            warm_metadata(h,service)
            assert service.photo_sync_state(h.peer['device_id']) is not None
            with pytest.raises((ValueError,RuntimeError)):
                service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'commit',None,None,choice['selection'],None)
            assert h.channel not in service._native_file_connections and 'file_pairing_epoch' not in h.peer


@pytest.mark.parametrize('scenario',['grant','decline','lock','book','metadata'])
def test_first_send_uses_actual_native_dialog_and_private_ipc_without_receiving(native,tmp_path,scenario):
    with setup_peer(native,tmp_path,'fresh') as h:
        service=h.service;before=files(Path(service.store.root));state=service.photo_sync_state(h.peer['device_id'])
        tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
        method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
            if isinstance(node,ast.FunctionDef) and node.name=='_telefon_medien_senden')
        idle=[];answers=[];dialogs=[];book=[{'saved':'original'}]
        class Question:
            def __init__(self,**kwargs):dialogs.append(self);self.default=None
            def set_default_response(self,value):self.default=value
            def format_secondary_text(self,value):self.text=value
            def run(self):
                assert threading.current_thread() is threading.main_thread() and self.default=='no'
                assert 'Organizer → ' in self.text
                if scenario=='lock':window._gesperrt=True
                if scenario=='book':book[0]={'saved':'different'}
                if scenario=='metadata':service._native_file_controls[h.channel].pop('grants.update')
                return 'no' if scenario=='decline' else 'yes'
            def destroy(self):self.destroyed=True
        gtk=SimpleNamespace(MessageDialog=Question,DialogFlags=SimpleNamespace(MODAL=1),MessageType=SimpleNamespace(QUESTION=1),
            ButtonsType=SimpleNamespace(YES_NO=1),ResponseType=SimpleNamespace(YES='yes',NO='no'))
        namespace={'_':lambda text:text,'threading':threading,'time':time,'GLib':SimpleNamespace(idle_add=idle.append),'Gtk':gtk}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-first-send-dialog','exec'),namespace)
        server=background.IPCServer(None,str(tmp_path/'first-send.sock'),phone_backend=service,
            settings_getter=lambda:background.normalize_settings({})).start()
        try:
            window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),_organizer_vertraut=lambda:True,
                _telefon_actor_buchnachweis=lambda:book[0],_telefon_stand_melden=lambda:None,antwort=lambda name,value:answers.append(value))
            payload=dict(cmd='telefon_medien_senden',kennung=h.peer['device_id'],fingerprint=h.fingerprint,
                photos=True,videos=False,requestId='first-send-native',version=state['sending_setup']['version'])
            worker=namespace['_telefon_medien_senden'](window,payload)
            worker.join(20);assert not worker.is_alive()
            while idle:assert idle.pop(0)() is False
            window._telefon_senden_worker.join(20);assert not window._telefon_senden_worker.is_alive()
            assert answers[-1]['ok'] is (scenario in ('grant','decline'))
            assert len(dialogs)==1 and dialogs[0].destroyed
            assert not service._native_sending_setups
            if scenario=='grant':
                connection=service._native_file_connections[h.channel]
                assert connection._preferences.read().policy.sending.photos
                assert not connection._local().grants.receive_files and connection._source_pending is None
            else:
                assert files(Path(service.store.root))==before and h.channel not in service._native_file_connections
                assert 'file_pairing_epoch' not in h.peer
        finally:server.close()


def test_first_send_does_not_create_a_missing_native_key(native,tmp_path):
    with setup_peer(native,tmp_path,'fresh') as h:
        service=h.service;state=service.photo_sync_state(h.peer['device_id'])
        root=Path(service.store.root);key=root/'storage.key';held=root/'held-key';key.rename(held)
        try:
            before=files(root)
            with pytest.raises((OSError,ValueError,RuntimeError)):
                service.photo_sync_sending_consent(h.peer['device_id'],h.fingerprint,'prepare',True,False,None,state['sending_setup']['version'])
            assert files(root)==before and not key.exists() and not service._native_sending_setups
            assert h.channel not in service._native_file_connections and 'file_pairing_epoch' not in h.peer
        finally:held.rename(key)
