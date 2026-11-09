"""Actual GTK callback and private Unix IPC; not an installed dialog acceptance."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import pytest

from test_media_source_connection import source, native, receiving, mappings, composition
from test_file_video_authority import ack_all
import magnolie_hintergrund as background
import magnolie_telefon as phone


@pytest.mark.parametrize('scenario',['grant','decline','lock','book','proxy','injection','withdraw','stale','fingerprint','rpc'])
def test_actual_native_sending_dialog_and_private_ipc_preserve_original_context_and_independent_receiving(source,native,tmp_path,monkeypatch,scenario):
    service=native[0]
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    with composition(source,service) as h:
        ack_all(service,h.peer,h.channel)
        assert service.photo_sync_state(h.peer['device_id']) is not None
        if scenario!='withdraw':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        h.connection._local()
        before=h.preferences.read()
        server=background.IPCServer(None,str(tmp_path/'sending-native.sock'),phone_backend=service,
            settings_getter=lambda:background.normalize_settings({})).start()
        try:
            tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
            method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
                if isinstance(node,ast.FunctionDef) and node.name=='_telefon_medien_senden')
            idle=[];answers=[];dialogs=[];book=[{'saved':'original-native-book'}]
            class Question:
                def __init__(self,**options):
                    assert threading.current_thread() is threading.main_thread();self.default=None;dialogs.append(self)
                def set_default_response(self,value):self.default=value
                def format_secondary_text(self,value):self.text=value
                def run(self):
                    assert self.default=='no' and 'Organizer → ' in self.text
                    if scenario=='lock':window._gesperrt=True
                    if scenario=='book':book[0]={'saved':'different-native-book'}
                    if scenario=='proxy':window._telefon=None
                    return 'no' if scenario=='decline' else 'yes'
                def destroy(self):self.destroyed=True
            gtk=SimpleNamespace(MessageDialog=Question,DialogFlags=SimpleNamespace(MODAL=1),MessageType=SimpleNamespace(QUESTION=1),
                ButtonsType=SimpleNamespace(YES_NO=1),ResponseType=SimpleNamespace(YES='yes',NO='no'))
            namespace={'_':lambda text:text,'threading':threading,'time':time,'GLib':SimpleNamespace(idle_add=idle.append),'Gtk':gtk}
            exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-native-sending-handler','exec'),namespace)
            window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),_organizer_vertraut=lambda:True,
                _telefon_actor_buchnachweis=lambda:book[0],_telefon_stand_melden=lambda:None,antwort=lambda name,value:answers.append((name,value)))
            if scenario=='rpc':
                def failed(*args,**kwargs):raise TypeError('synthetic native proxy failure')
                window._telefon.photo_sync_sending_consent=failed
            payload=dict(cmd='telefon_medien_senden',kennung=h.peer['device_id'],fingerprint=phone.fingerprint(phone.unb64(h.peer['static_public'],32)),
                photos=scenario!='withdraw',videos=False,requestId='actual-native-send-choice',version=before.version)
            if scenario=='injection':payload['confirmed']=True
            if scenario=='stale':payload['version']='f'*64
            if scenario=='fingerprint':payload['fingerprint']='unrelated-fingerprint'
            worker=namespace['_telefon_medien_senden'](window,payload)
            if worker is not None:
                worker.join(20);assert not worker.is_alive()
                while idle:assert idle.pop(0)() is False
                window._telefon_senden_worker.join(20);assert not window._telefon_senden_worker.is_alive()
            assert answers and answers[-1][0]=='App.telefonFotoErgebnis'
            assert answers[-1][1]['ok'] is (scenario in ('grant','decline','withdraw'))
            after=h.preferences.read()
            if scenario in ('grant','withdraw'):
                assert after.policy.sending.photos is (scenario=='grant') and not after.policy.sending.videos
                assert not after.policy.enabled and after.policy.destination==before.policy.destination
                assert not h.connection._local().grants.receive_files
            else:assert after==before
            assert len(dialogs)==(0 if scenario in ('withdraw','injection','stale','fingerprint','rpc') else 1)
            assert not getattr(window,'_telefon_senden_pending',False)
            assert all(dialog.destroyed for dialog in dialogs) and h.target.read_bytes()==b'hello' and not h.source._prepared
        finally:server.close()
