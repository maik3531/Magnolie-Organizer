"""Native picker callback/IPC, actual protected choices; no installed GUI claim."""
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time
from queue import Queue, Empty

import pytest

from test_file_authenticated_desktop import native, bind
from test_file_desktop_receive import receiving
from test_file_desktop_album_worker import prepared as prepared_images
from test_file_video_authority import ack_all
from magnolie_file_desktop_connection import NativeDesktopFileConnection
import magnolie_hintergrund as background
import magnolie_telefon as phone
from magnolie_media_retention import NativeMediaRetention
from magnolie_native_book_json import book_hash, canonical_book
from magnolie_personal_actor_store import NativeBookOwnerScope


def saved_book_inputs_for_root(root):
    with NativeMediaRetention(root) as book:
        saved=book._read()
        assert saved is not None and saved['book_sha256'] is not None
        return dict(book_version=saved['book_sha256'],book_witness=list(saved['book_file']))


def saved_book_inputs(connection):
    return saved_book_inputs_for_root(connection._authority.binding.native_directory)


def prepare_choice(fixture,monkeypatch):
    prepared_images(fixture)
    service,peer,channel=fixture[:3]
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    peer['capabilities']['items']['device_status']['versions'].append(22)
    service.store.save_peers();ack_all(service,peer,channel)
    monkeypatch.setattr(NativeDesktopFileConnection,'_video_data_handlers_ready',True)


@contextmanager
def native_picker(fixture,tmp_path,selection,*,photos=False,clock=None,cold=False,saved_ack=False):
    service,peer=fixture[:2]
    server=background.IPCServer(None,str(tmp_path/'video-picker.sock'),phone_backend=service,
        settings_getter=lambda:background.normalize_settings({})).start()
    try:
        tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
        names={'_telefon_videoziel_waehlen','_telefon_actor_buchbindung','_telefon_actor_buchquelle','_telefon_actor_buchnachweis'}
        methods=[node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
            if isinstance(node,ast.FunctionDef) and node.name in names]
        assert {node.name for node in methods}==names
        idle=Queue()
        namespace={'_':lambda text:text,'threading':threading,'time':clock or time,'hashlib':hashlib,'json':json,'os':os,'daten_datei':lambda:str(tmp_path/'daten.json'),
            'GLib':SimpleNamespace(UserDirectory=SimpleNamespace(DIRECTORY_VIDEOS='native-videos',DIRECTORY_PICTURES='native-pictures'),
                get_user_special_dir=lambda kind:str(tmp_path/('Native-Pictures' if photos else 'Native-Videos')) if kind==('native-pictures' if photos else 'native-videos') else pytest.fail('Wrong native folder'),
                idle_add=lambda callback:idle.put(callback) or 1)}
        exec(compile(ast.Module(body=methods,type_ignores=[]),'actual-native-picker-handler','exec'),namespace)
        calls=[];answers=[]
        def choose(title,**options):
            assert threading.current_thread() is threading.main_thread()
            calls.append((title,options));return selection(window) if callable(selection) else selection
        inputs=saved_book_inputs_for_root(service.store.root)
        proof=dict(book_source='native-test-book',sequence=1)
        window=SimpleNamespace(_gesperrt=False,_telefon=background.PhoneServiceProxy(server.path),_ordner_waehlen=choose,
            antwort=lambda name,value:answers.append((name,value)),_telefon_stand_melden=lambda:None,
            _organizer_vertraut=lambda:True,
            _notes_actor_saved_data=(proof['book_source'],proof['sequence'],inputs['book_version']),
            _telefon_actor_buchnachweis=lambda:dict(proof))
        if cold or saved_ack:
            del window._notes_actor_saved_data
            window._notes_actor_book_owner=NativeBookOwnerScope()
            window._notes_actor_book_owner.set_ready(True)
            for name in names-{'_telefon_videoziel_waehlen'}:
                setattr(window,name,namespace[name].__get__(window))
            window._aktuelle_daten=json.loads((tmp_path/'daten.json').read_bytes())
            window._operation_laeuft=window._sync_laeuft=window._wirklich_beenden=False
            window._daten_dek_kennung=None
            window._ladefehler=''
            window._speicher_laeuft=False
            window._speicher_auftraege=Queue()
            if saved_ack:
                # Record the actual committed bytes, then exercise the native
                # current-book comparison instead of the ordinary fixture stub.
                raw=(tmp_path/'daten.json').read_bytes()
                observed=window._notes_actor_book_owner.record_saved(
                    *window._telefon_actor_buchbindung(),hashlib.sha256(raw).hexdigest())
                window._notes_actor_saved_data=(observed['book_source'],observed['sequence'],
                    book_hash(window._aktuelle_daten))
        payload=dict(cmd='telefon_fotoziel_waehlen' if photos else 'telefon_videoziel_waehlen',kennung=peer['device_id'],fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32)))
        def invoke(extra=None):
            worker=namespace['_telefon_videoziel_waehlen'](window,{**payload,**(extra or {})})
            # Drive the actual GLib scheduling boundary on the main thread;
            # native prepare/commit stay on their real separate IO threads.
            deadline=time.monotonic()+30
            latest=worker
            while worker is not None:
                try:idle.get_nowait()()
                except Empty:pass
                latest=getattr(window,'_telefon_videoziel_worker',worker)
                latest.join(.01)
                if not worker.is_alive() and not latest.is_alive() and idle.empty():break
                assert time.monotonic()<deadline,'Native destination worker did not drain'
            # Preserve the helper's old distinction: only an actual commit
            # returns a worker, not a cancelled/rejected dialog preparation.
            return latest if latest is not None and latest.name.endswith('-commit') else None
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


@pytest.mark.parametrize('cold',[False,True],ids=['save-ack','reopened'])
@pytest.mark.parametrize('fractional',[False,True],ids=['integer-book','fractional-book'])
def test_video_picker_matches_existing_saved_book_after_reopen_or_save_ack(receiving,tmp_path,monkeypatch,cold,fractional):
    prepare_choice(receiving,monkeypatch)
    connection=receiving[3];before=connection._preferences.read();sent=receiving[2].send.call_count
    service=receiving[0];book=tmp_path/'daten.json';data=json.loads(book.read_bytes())
    if fractional:
        data['customOrganizer']={'drawing':{'points':[{'x':12.5,'y':-3.75}], 'zoom':1.0}}
    with NativeMediaRetention(service.store.root) as retention:
        token=retention.pause()
        book.write_bytes(canonical_book(data))
        retention.publish_saved(token,data)
        retained=retention._read()
        assert retained['book_sha256']==book_hash(data)
    book_before=book.read_bytes();peers_before=Path(service.store.peers_path).read_bytes()
    grant=connection._preferences.local_grant(True).grants
    original=Path(before.policy.destination.path)/'preserved-photo.jpg';original.write_bytes(b'Keep existing photo')
    target=tmp_path/'After-Reopen-Video';target.mkdir(mode=0o700)
    with native_picker(receiving,tmp_path,str(target),cold=cold,saved_ack=not cold) as (window,invoke,calls,answers):
        proof=window._telefon_actor_buchnachweis()
        assert (proof is None)==cold
        assert invoke() is not None and len(calls)==1 and answers[-1][1]['ok']
        assert window._telefon_actor_buchnachweis()==proof
    after=connection._preferences.read()
    assert after.policy.videos.destination.path==str(target) and not after.include_videos
    assert after.policy.destination==before.policy.destination and after.policy.permission_epoch==before.policy.permission_epoch
    assert connection._preferences.local_grant(True).grants==grant
    assert Path(service.store.peers_path).read_bytes()==peers_before and original.read_bytes()==b'Keep existing photo'
    with NativeMediaRetention(service.store.root) as retention:assert retention._read()==retained
    assert book.read_bytes()==book_before and receiving[2].send.call_count==sent and not list(target.iterdir())


@pytest.mark.parametrize('injected',[False,True])
@pytest.mark.parametrize('photos',[False,True])
def test_native_picker_cancel_or_web_path_injection_cannot_write_preferences_or_start_action(receiving,tmp_path,monkeypatch,injected,photos):
    prepare_choice(receiving,monkeypatch);connection=receiving[3]
    if photos:connection.desktop_session()._local_enabled(False)
    before=connection._preferences.read();sent=receiving[2].send.call_count
    with native_picker(receiving,tmp_path,None,photos=photos) as (_,invoke,calls,answers):
        assert invoke({'path':str(tmp_path/'untrusted-web-path')} if injected else None) is None
        assert len(calls)==(0 if injected else 1)
        assert answers[-1][1]['ok'] is (not injected)
    assert connection._preferences.read()==before and receiving[2].send.call_count==sent
    assert not (tmp_path/'untrusted-web-path').exists()
    service,peer=receiving[:2]
    for request in (dict(action='videos_destination',path=str(tmp_path)),dict(action='videos_enable',path=str(tmp_path)),
            dict(action='photos_destination',path=str(tmp_path)),dict(action='photos_default_destination',path=str(tmp_path))):
        with pytest.raises(ValueError,match='photo_sync_invalid_action'):
            service.photo_sync_action(peer['device_id'],phone.fingerprint(phone.unb64(peer['static_public'],32)),request)


def test_native_picker_reselects_original_and_explicit_new_video_choice_keeps_old_files(receiving,tmp_path,monkeypatch):
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
        assert state['state']=='videos_off',state.get('error')
    changed=connection._preferences.read()
    assert changed.policy.videos.destination.path==str(other) and not changed.include_videos
    assert changed.policy.destination==original.policy.destination and changed.policy.permission_epoch==original.policy.permission_epoch
    assert (target/'keep.txt').read_bytes()==b'Keep user file'
    assert not list(other.iterdir())


def test_native_photo_picker_private_ipc_keeps_disabled_state_and_original_files(receiving,tmp_path,monkeypatch):
    prepare_choice(receiving,monkeypatch);connection=receiving[3];session=connection.desktop_session()
    session._local_enabled(False)
    before=connection._preferences.read();old=Path(before.policy.destination.path)/'original-user-photo.jpg';old.write_bytes(b'keep old photo')
    target=tmp_path/'Explicit-Photo-Choice';target.mkdir(mode=0o700);sent=receiving[2].send.call_count
    with native_picker(receiving,tmp_path,str(target),photos=True) as (_,invoke,calls,answers):
        assert invoke() is not None;assert session.join(20)
        assert session.snapshot()['state']=='off',session.snapshot().get('error')
        assert calls==[('Destination folder',dict(standard=str(tmp_path/'Native-Pictures')))]
        assert answers[-1][1]['ok'] is True
    changed=connection._preferences.read()
    assert changed.policy.destination.path==str(target) and not changed.policy.enabled
    assert changed.policy.videos==before.policy.videos and changed.policy.mapping_store==before.policy.mapping_store and changed.policy.job_catalog==before.policy.job_catalog
    assert old.read_bytes()==b'keep old photo' and not list(target.iterdir()) and receiving[2].send.call_count==sent
    with native_picker(receiving,tmp_path,str(target),photos=True) as (_,invoke,_,_):
        invoke();assert session.join(20)
    assert connection._preferences.read()==changed


@pytest.mark.parametrize('case',['first','cancel','stale_book','unsafe_choice','failed_enable','legacy_failed_enable','cold','cold_dirty','cold_changed'])
def test_native_photo_picker_before_successful_enable(native,tmp_path,monkeypatch,case):
    service,peer,_=native
    if case=='legacy_failed_enable':
        peer.pop('file_pairing_epoch');service.store.save_peers()
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    channel,_=bind(service,peer);ack_all(service,peer,channel);channel.send.reset_mock()
    book=tmp_path/'daten.json';book.write_text('{"einstellungen":{"papierkorb":{"an":false,"tage":0}}}')
    book.chmod(0o600)
    with NativeMediaRetention(service.store.root) as retention:assert retention.adopt_existing_saved()
    saved_book=book.read_bytes()
    pictures=tmp_path/'Native-Pictures';pictures.mkdir(mode=0o700);pictures.chmod(0o775)
    original=pictures/'unchanged.jpg';original.write_bytes(b'original')
    target=tmp_path/'Explicit-Safe-Photo-Choice';target.mkdir(mode=0o700)
    monkeypatch.setattr('magnolie_photo_destination.native_pictures_directory',lambda:pictures)
    peer_id=peer['device_id'];fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    try:
        assert service.photo_sync_state(peer_id).get('photo_destination_setup',False) is (case!='legacy_failed_enable')
        assert channel not in service._native_file_connections
        before=None
        if case.endswith('failed_enable'):
            service.photo_sync_action(peer_id,fingerprint,dict(action='enable'))
            connection=service._native_file_connections[channel];assert connection.desktop_session().join(20)
            stand=service.photo_sync_state(peer_id)
            assert stand['state']=='held' and stand['error']=='file_acceptance_unsafe_destination',stand
            assert not stand['enabled'] and not stand['destination'] and stand['photo_destination_setup']
            before=connection._preferences.read()
            assert before.associated and before.policy.mapping_store and before.policy.job_catalog
        else:
            assert not any(Path(service.store.root).glob('photo-preferences-v1-*'))
        paired_before=Path(service.store.peers_path).read_bytes()
        def choose(_):
            assert not channel.send.called
            prefs=service._native_file_connections[channel]._preferences
            if before is None:assert prefs.read().policy is None
            else:assert prefs.read()==before
            if case in ('stale_book','cold_changed'):book.write_bytes(saved_book+b' ')
            if case=='unsafe_choice':return str(pictures)
            return None if case=='cancel' else str(target)
        with native_picker((service,peer),tmp_path,choose,photos=True,cold=case.startswith('cold')) as (window,invoke,calls,answers):
            if case=='cold_dirty':window._aktuelle_daten['notizen']=[{'titel':'Unsaved synthetic change'}]
            invoke()
            assert len(calls)==(0 if case=='cold_dirty' else 1)
            assert answers[-1][1]['ok'] is (case not in ('stale_book','unsafe_choice','cold_dirty','cold_changed'))
            assert answers[-1][1].get('canceled',False) is (case=='cancel')
        connection=service._native_file_connections[channel]
        after=connection._preferences.read()
        if case in ('cancel','stale_book','unsafe_choice','cold_dirty','cold_changed'):
            assert after.policy is None and not any(Path(service.store.root).glob('photo-preferences-v1-*'))
        else:
            assert after.associated and after.policy.destination.path==str(target)
            assert not after.policy.enabled and not after.include_videos and after.policy.mode=='manual'
            assert after.policy.sending is None and not after.policy.phone_to_pc_delete and not after.policy.pc_to_phone_delete
            stand=service.photo_sync_state(peer_id)
            assert stand['state']=='off' and stand['error'] is None and stand['permission'] is None
            if before is not None:
                assert after.policy.mapping_store==before.policy.mapping_store and after.policy.job_catalog==before.policy.job_catalog
        assert not connection._preferences.local_grant(True).grants.receive_files
        assert not channel.send.called and Path(service.store.peers_path).read_bytes()==paired_before
        assert book.read_bytes()==saved_book+(b' ' if case in ('stale_book','cold_changed') else b'')
        assert list(pictures.iterdir())==[original] and pictures.stat().st_mode & 0o777==0o775
        assert original.read_bytes()==b'original' and not list(target.iterdir())
    finally:service._end_native_file_connection(channel)


def test_cold_photo_picker_does_not_open_enabled_receive_policy(receiving,tmp_path,monkeypatch):
    service,peer,old,connection,_=receiving
    assert connection._preferences.read().policy.enabled
    service._end_native_file_connection(old)
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    channel,_=bind(service,peer);ack_all(service,peer,channel);channel.send.reset_mock()
    try:
        with native_picker((service,peer),tmp_path,None,photos=True) as (_,invoke,calls,answers):
            assert invoke() is None and not calls and answers[-1][1]['ok'] is False
        assert channel not in service._native_file_connections and not channel.send.called
    finally:service._end_native_file_connection(channel)


@pytest.mark.parametrize('photos',[False,True])
def test_lock_during_native_picker_prevents_late_choice_from_reaching_private_ipc(receiving,tmp_path,monkeypatch,photos):
    prepare_choice(receiving,monkeypatch);connection=receiving[3]
    if photos:connection.desktop_session()._local_enabled(False)
    before=connection._preferences.read()
    target=tmp_path/'Chosen-Before-Lock';target.mkdir(mode=0o700)
    def lock(window):window._gesperrt=True;return str(target)
    with native_picker(receiving,tmp_path,lock,photos=photos) as (_,invoke,calls,answers):
        invoke();assert len(calls)==1 and answers[-1][1]['ok'] is False
    assert connection._preferences.read()==before and not list(target.iterdir())
