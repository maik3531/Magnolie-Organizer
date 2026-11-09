"""Real native handler/private Unix RPC and held roots, not installed GUI acceptance."""
import ast
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
import threading
import time

import pytest

from test_media_source_pc import pc,source,mappings,receiving,native
from test_media_source_connection import composition,agree
from test_file_video_authority import ack_all
from magnolie_media_source_collection import NativeCollectionRoot
import magnolie_hintergrund as background
import magnolie_telefon as phone


@pytest.mark.parametrize('scenario',['choose','read','decline','lock','book','proxy','path_injection','flag','stale','fingerprint','substitution','rpc','busy_sending'])
def test_native_source_folder_handler_and_private_ipc_bind_the_original_gui_context_and_real_selection(pc,native,tmp_path,monkeypatch,scenario):
    service=native[0];monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    with composition(pc,service) as h:
        agree(h,service);ack_all(service,h.peer,h.channel)
        assert service.photo_sync_state(h.peer['device_id']) is not None
        with closing(h.preferences.open_collection_roots()) as catalog:before=catalog.read()
        old_policy=h.preferences.read();control=h.connection._controls.packet()
        folder=tmp_path/'native-dialog-source';folder.mkdir(mode=0o700)
        server=background.IPCServer(None,str(tmp_path/'source-choice.sock'),phone_backend=service,
            settings_getter=lambda:background.normalize_settings({})).start()
        try:
            tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
            method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
                if isinstance(node,ast.FunctionDef) and node.name=='_telefon_sammlungsordner')
            idle=[];answers=[];dialogs=[];book=[{'saved':'original-native-book'}];held=[]
            original_init=NativeCollectionRoot.__init__
            def capture(root,path,current):
                original_init(root,path,current)
                if str(path)==str(folder):held.append(root)
            monkeypatch.setattr(NativeCollectionRoot,'__init__',capture)
            def picker(title,standard):
                assert threading.current_thread() is threading.main_thread();dialogs.append(title)
                assert 'Add PC source folder' in title
                if scenario=='lock':window._gesperrt=True
                if scenario=='book':book[0]={'saved':'different-native-book'}
                if scenario=='proxy':window._telefon=None
                return None if scenario=='decline' else str(folder)
            namespace={'_':lambda text:text,'threading':threading,'time':time,'GLib':SimpleNamespace(idle_add=idle.append,
                get_user_special_dir=lambda key:str(tmp_path),UserDirectory=SimpleNamespace(DIRECTORY_PICTURES=1,DIRECTORY_VIDEOS=2))}
            exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-native-source-folder-handler','exec'),namespace)
            def reply(name,value):
                assert all(root._fd is None for root in held)
                answers.append((name,value))
            window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),_organizer_vertraut=lambda:True,
                _telefon_actor_buchnachweis=lambda:book[0],_telefon_stand_melden=lambda:None,antwort=reply,_ordner_waehlen=picker)
            if scenario=='busy_sending':window._telefon_senden_pending=True
            proxy=window._telefon;call=proxy.photo_sync_collection_choice
            def delayed(*args,**kwargs):
                if scenario=='rpc':raise TypeError('synthetic native proxy failure')
                if scenario=='substitution' and args[2]=='commit':
                    folder.rename(folder.with_name('retained-native-dialog-source'));folder.mkdir(mode=0o700)
                return call(*args,**kwargs)
            proxy.photo_sync_collection_choice=delayed
            payload=dict(cmd='telefon_sammlungsordner',kennung=h.peer['device_id'],
                fingerprint=phone.fingerprint(phone.unb64(h.peer['static_public'],32)),media_type='images',
                action='read' if scenario=='read' else 'choose',version=h.controller.display_snapshot()['version'],requestId='native-source-dialog')
            if scenario=='flag':payload['confirmed']=True
            if scenario=='path_injection':payload['path']=str(folder)
            if scenario=='stale':payload['version']='f'*64
            if scenario=='fingerprint':payload['fingerprint']='unrelated-fingerprint'
            worker=namespace['_telefon_sammlungsordner'](window,payload)
            if worker is not None:
                worker.join(20);assert not worker.is_alive()
                while idle:assert idle.pop(0)() is False
                window._telefon_sammlungsordner_worker.join(20);assert not window._telefon_sammlungsordner_worker.is_alive()
            assert answers and answers[-1][0]=='App.telefonFotoErgebnis'
            assert answers[-1][1]['ok'] is (scenario in ('choose','read','decline'))
            assert not {'selection','path','witness'}&answers[-1][1].keys()
            with closing(h.preferences.open_collection_roots()) as catalog:after=catalog.read()
            assert len(after.roots)==len(before.roots)+(scenario=='choose')
            if scenario!='choose':assert after==before
            assert h.preferences.read()==old_policy and h.connection._controls.packet().grants==control.grants
            assert not h.connection._local().grants.receive_files and not h.connection._controls._remote.grants.send_files
            assert not h.connection._media_pc_source._prepared and h.pc_file.read_bytes()==h.raw
            assert h.connection._media_collection_choice is None and not getattr(window,'_telefon_sammlungsordner_pending',False)
            assert len(dialogs)==(0 if scenario in ('read','flag','path_injection','stale','fingerprint','rpc','busy_sending') else 1)
            assert all(root._fd is None for root in held)
        finally:server.close()
