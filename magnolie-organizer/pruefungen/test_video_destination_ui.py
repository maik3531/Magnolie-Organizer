"""Native picker callback/IPC, actual protected choices; no installed GUI claim."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_album_worker import prepared as prepared_images
from test_file_video_authority import ack_all
from magnolie_file_desktop_connection import NativeDesktopFileConnection
import magnolie_hintergrund as background
import magnolie_telefon as phone


def prepare_choice(fixture,monkeypatch):
    prepared_images(fixture)
    service,peer,channel=fixture[:3]
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    peer['capabilities']['items']['device_status']['versions'].append(22)
    service.store.save_peers();ack_all(service,peer,channel)
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)


@contextmanager
def native_picker(fixture,tmp_path,selection):
    service,peer=fixture[:2]
    server=background.IPCServer(None,str(tmp_path/'video-picker.sock'),phone_backend=service,
        settings_getter=lambda:background.normalize_settings({})).start()
    try:
        tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
        method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
            if isinstance(node,ast.FunctionDef) and node.name=='_telefon_videoziel_waehlen')
        namespace={'_':lambda text:text,'threading':threading,
            'GLib':SimpleNamespace(UserDirectory=SimpleNamespace(DIRECTORY_VIDEOS='native-videos'),
                get_user_special_dir=lambda kind:str(tmp_path/'Native-Videos') if kind=='native-videos' else pytest.fail('Wrong native folder'))}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-native-picker-handler','exec'),namespace)
        calls=[];answers=[]
        def choose(title,**options):
            assert threading.current_thread() is threading.main_thread()
            calls.append((title,options));return selection(window) if callable(selection) else selection
        window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),_ordner_waehlen=choose,
            antwort=lambda name,value:answers.append((name,value)),_telefon_stand_melden=lambda:None)
        payload=dict(cmd='telefon_videoziel_waehlen',kennung=peer['device_id'],fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32)))
        def invoke(extra=None):
            worker=namespace['_telefon_videoziel_waehlen'](window,{**payload,**(extra or {})})
            if worker is not None:
                worker.join(10);assert not worker.is_alive()
            return worker
        yield window,invoke,calls,answers
    finally:server.close()


def test_native_picker_private_ipc_saves_initial_custom_video_root_off_without_photo_grant_change(receiving,tmp_path,monkeypatch):
    prepare_choice(receiving,monkeypatch);connection=receiving[3];before=connection._preferences.read()
    grant=connection._preferences.local_grant(True).grants;sent=receiving[2].send.call_count
    target=tmp_path/'Explicit-Video-Choice';target.mkdir(mode=0o700)
    with native_picker(receiving,tmp_path,str(target)) as (_,invoke,calls,answers):
        assert invoke() is not None
        assert connection.desktop_session().join(20)
        state=connection.desktop_session().snapshot();assert state['state']=='videos_off',state
        assert calls==[('Destination folder',dict(standard=str(tmp_path/'Native-Videos')))]
        assert answers[-1][0]=='App.telefonFotoErgebnis' and answers[-1][1]['ok'] is True
    after=connection._preferences.read()
    assert not after.include_videos and after.policy.videos.destination.path==str(target)
    assert after.policy.videos.destination_token!=after.policy.destination_token
    assert after.policy.destination==before.policy.destination and after.policy.permission_epoch==before.policy.permission_epoch
    assert connection._preferences.local_grant(True).grants==grant
    assert receiving[2].send.call_count==sent and not list(target.iterdir())


@pytest.mark.parametrize('injected',[False,True])
def test_native_picker_cancel_or_web_path_injection_cannot_write_preferences_or_start_action(receiving,tmp_path,monkeypatch,injected):
    prepare_choice(receiving,monkeypatch);connection=receiving[3];before=connection._preferences.read();sent=receiving[2].send.call_count
    with native_picker(receiving,tmp_path,None) as (_,invoke,calls,answers):
        assert invoke({'path':str(tmp_path/'untrusted-web-path')} if injected else None) is None
        assert len(calls)==(0 if injected else 1)
        assert answers[-1][1]['ok'] is (not injected)
    assert connection._preferences.read()==before and receiving[2].send.call_count==sent
    assert not (tmp_path/'untrusted-web-path').exists()
    service,peer=receiving[:2]
    for request in (dict(action='videos_destination',path=str(tmp_path)),dict(action='videos_enable',path=str(tmp_path))):
        with pytest.raises(ValueError,match='photo_sync_invalid_action'):
            service.photo_sync_action(peer['device_id'],phone.fingerprint(phone.unb64(peer['static_public'],32)),request)


def test_native_picker_reselects_exact_original_but_never_reassociates_existing_video_root(receiving,tmp_path,monkeypatch):
    prepare_choice(receiving,monkeypatch);connection=receiving[3];target=tmp_path/'Original-Videos';target.mkdir(mode=0o700)
    with native_picker(receiving,tmp_path,str(target)) as (_,invoke,_,_):
        invoke();assert connection.desktop_session().join(20)
    (target/'keep.txt').write_bytes(b'Keep user file')
    original=connection._preferences.read()
    with native_picker(receiving,tmp_path,str(target)) as (_,invoke,_,_):
        invoke();assert connection.desktop_session().join(20)
        assert connection.desktop_session().snapshot()['state']=='videos_off'
    assert connection._preferences.read()==original
    other=tmp_path/'Different-Videos';other.mkdir(mode=0o700)
    with native_picker(receiving,tmp_path,str(other)) as (_,invoke,_,_):
        invoke();assert connection.desktop_session().join(20)
        state=connection.desktop_session().snapshot()
        assert state['state']=='held' and state['error']=='video_preferences_destination_reassociation_required'
    assert connection._preferences.read()==original and (target/'keep.txt').read_bytes()==b'Keep user file'
    assert not list(other.iterdir())


def test_lock_during_native_picker_prevents_late_choice_from_reaching_private_ipc(receiving,tmp_path,monkeypatch):
    prepare_choice(receiving,monkeypatch);connection=receiving[3];before=connection._preferences.read()
    target=tmp_path/'Chosen-Before-Lock';target.mkdir(mode=0o700)
    def lock(window):window._gesperrt=True;return str(target)
    with native_picker(receiving,tmp_path,lock) as (_,invoke,calls,answers):
        invoke();assert len(calls)==1 and answers[-1][1]['ok'] is False
    assert connection._preferences.read()==before and not list(target.iterdir())
