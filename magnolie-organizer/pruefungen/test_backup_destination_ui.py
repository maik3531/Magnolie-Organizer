"""Actual native GTK callback/private IPC; no physical dialog acceptance claim."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os
import threading

import pytest

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_album_worker import prepared
from test_file_video_authority import ack_all
import magnolie_hintergrund as background
import magnolie_telefon as phone


def prepare_native_picker(fixture,monkeypatch):
    prepared(fixture)
    service,peer,channel=fixture[:3]
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    ack_all(service,peer,channel)
    assert service.photo_sync_state(peer['device_id']) is not None


@contextmanager
def picker(fixture,tmp_path,selection):
    service,peer=fixture[:2]
    server=background.IPCServer(None,str(tmp_path/'backup-picker.sock'),phone_backend=service,
        settings_getter=lambda:background.normalize_settings({})).start()
    try:
        tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
        method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
            if isinstance(node,ast.FunctionDef) and node.name=='_telefon_backupziel')
        idle=[];calls=[];answers=[]
        namespace={'_':lambda text:text,'threading':threading,'os':os,'GLib':SimpleNamespace(idle_add=idle.append)}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-native-backup-picker-handler','exec'),namespace)
        def choose(title,**options):
            assert threading.current_thread() is threading.main_thread()
            calls.append((title,options));return selection(window) if callable(selection) else selection
        window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),_organizer_vertraut=lambda:True,
            _ordner_waehlen=choose,antwort=lambda name,value:answers.append((name,value)))
        payload=dict(cmd='telefon_backupziel',kennung=peer['device_id'],fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32)),
            media_type='images',action='choose',requestId='actual-native-backup-picker')
        def invoke(extra=None):
            worker=namespace['_telefon_backupziel'](window,{**payload,**(extra or {})})
            if worker is not None:
                worker.join(20);assert not worker.is_alive()
                while idle:
                    assert idle.pop(0)() is False
                final=window._telefon_backupziel_worker
                final.join(20);assert not final.is_alive()
            return worker
        yield window,invoke,calls,answers
    finally:server.close()


def test_native_backup_picker_private_ipc_changes_only_future_storage_and_keeps_default_history(receiving,tmp_path,monkeypatch):
    prepare_native_picker(receiving,monkeypatch);connection=receiving[3]
    before=connection._preferences.read();grant=connection._preferences.local_grant(True).grants;sent=receiving[2].send.call_count
    path=tmp_path/'Chosen-Backup-Parent';path.mkdir(mode=0o700)
    with picker(receiving,tmp_path,str(path)) as (_,invoke,calls,answers):
        assert invoke() is not None
        assert calls==[('Backups',dict(standard=str(receiving[4])))]
        assert answers[-1][0]=='App.telefonBackupErgebnis' and answers[-1][1]['ok'] is True
        page=answers[-1][1]['page'];assert page['current_path']==str(path/'Backup') and not page['is_default']
        invoke({'action':'default'})
        assert answers[-1][1]['ok'] is True and answers[-1][1]['page']['is_default']
        assert answers[-1][1]['page']['sources']==page['sources']
    assert connection._preferences.read()==before and connection._preferences.local_grant(True).grants==grant
    assert receiving[2].send.call_count==sent and not list(path.iterdir()) and not (receiving[4]/'Backup').exists()


@pytest.mark.parametrize('change',('cancel','injection','lock','book'))
def test_native_backup_picker_canceled_injected_or_changed_owner_never_saves_choice(receiving,tmp_path,monkeypatch,change):
    from magnolie_media_retention import NativeMediaRetention
    prepare_native_picker(receiving,monkeypatch);connection=receiving[3];before=connection.native_backup_locations('images')
    path=tmp_path/'No-Late-Backup-Choice';path.mkdir(mode=0o700)
    def select(window):
        if change=='cancel':return None
        if change=='lock':window._gesperrt=True
        if change=='book':
            root=Path(connection._authority.binding.native_directory)
            with NativeMediaRetention(root) as policy:
                token=policy.pause();policy.publish_saved(token,phone.strict_json((root.parent/'daten.json').read_bytes()))
        return str(path)
    with picker(receiving,tmp_path,select) as (window,invoke,calls,answers):
        if change=='injection':window._telefon_backupziel_pending=True
        invoke({'path':str(path)} if change=='injection' else None)
        assert len(calls)==(0 if change=='injection' else 1)
        assert answers[-1][1]['ok'] is (change=='cancel')
        if change=='injection':assert window._telefon_backupziel_pending is True
    after=connection.native_backup_locations('images')
    assert after['version']==before['version'] and after['sources']==before['sources'] and after['is_default']
    assert not list(path.iterdir())
