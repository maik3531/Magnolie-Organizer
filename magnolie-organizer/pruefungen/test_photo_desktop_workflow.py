"""Organizer/native service action through real grants, albums and file worker."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from queue import Queue
import sys
import threading
import uuid
import ast
import tempfile
import sqlite3
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'bin'))
import magnolie_telefon as phone
import magnolie_hintergrund as background
import magnolie_file_sources as sources
from magnolie_file_control import FileControlPacket,FileGrantState,NativeLocalFileGrant,NativeFilePeer,NativeFileControlSession
from magnolie_file_desktop_connection import NativeDesktopFileConnection
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_sources import response,CATALOG,ALBUM
from test_file_desktop_media import manifest
from test_file_desktop_album_worker import phone_batches
from test_file_desktop_album_worker import prepared
from magnolie_file_desktop_connection import NativePhotoDesktopSession
from test_file_desktop_receive import receiving


def converge_controls(service,peer,channel):
    for kind,body in (('capabilities.update',deepcopy(peer['capabilities'])),
                      ('grants.update',deepcopy(peer['grants'])),
                      ('personal_sync.settings',dict(format=1,own_device=True))):
        at=phone.now_ms()
        if kind in ('capabilities.update','grants.update'):body['revision']+=1
        service._payload(peer,channel,dict(type='message',v=1,message_id=str(uuid.uuid4()),kind=kind,
            created_ms=at,expires_ms=at+60_000,body=body))
    channel.send.reset_mock()


@contextmanager
def metadata_phone(service,peer,channel,*,grant_on_read=True,initial_enabled=False,initial_read=False):
    queue=Queue(); errors=[]; commands=[]; enabled=initial_enabled; revision=2 if enabled else 1; read_allowed=initial_read
    binding=service._file_channel_bindings[channel]
    remote_peer=NativeFilePeer(binding.local_identity.receiver_id,binding.local_identity.receiver_identity_sha256,
        object(),True,True,True,True,True)
    owner=object()
    def local():return NativeLocalFileGrant(FileGrantState(revision,sha256(str(revision).encode()).hexdigest(),enabled,False),owner,True)
    from magnolie_transfer_job_catalog import NativeJobCatalogIdentity
    remote=NativeFileControlSession(NativeJobCatalogIdentity(peer['device_id'],sha256(phone.unb64(peer['static_public'],32)).hexdigest()),lambda:remote_peer,local)
    def dispatch(message):service._payload(peer,channel,message)
    def controls():
        if remote.needs_packet:
            packet=remote.packet(); at=phone.now_ms()
            dispatch(dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='file_transfer.control',created_ms=at,expires_ms=at+60_000,body=packet.wire()))
            remote.mark_sent(packet)
    def run():
        nonlocal enabled,revision,read_allowed
        try:
            while True:
                message=queue.get()
                if message is None:return
                if message.get('type')=='ack':continue
                if message['kind']=='file_transfer.control':
                    remote.observe_remote(FileControlPacket.parse(message['body']),remote_peer);controls()
                elif message['kind']==sources.REQUEST:
                    operation=message['body']['operation'];commands.append(operation)
                    if operation in ('status','configure'):
                        if operation=='configure':enabled=message['body']['enabled'];revision+=1
                        dispatch(response(message,sources.RESULT,version='b'*64 if enabled else 'a'*64,revision=2 if enabled else 0,
                            enabled=enabled,associated=enabled,repair_pending=False,kinds=sorted(sources.KINDS) if enabled else []))
                        controls()
                    elif operation=='request_read':
                        dispatch(response(message,sources.PERMISSION_RESULT,version='b'*64,state='notification_posted'))
                        read_allowed=grant_on_read # Independent fixture phone coverage, never a client grant.
                    elif operation=='discover':
                        dispatch(response(message,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
                            after=0,next_cursor=None,coverage='full_images' if read_allowed else 'none',proves_deletion=False,
                            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)] if read_allowed else [])))
                    else:raise AssertionError(operation)
        except BaseException as error:errors.append(error)
    channel.send.side_effect=queue.put
    thread=threading.Thread(target=run,name='fixture-native-photo-metadata');thread.start()
    try:yield commands,errors
    finally:
        queue.put(None);thread.join(10);assert not thread.is_alive()
        channel.send.side_effect=None
        if errors or sys.exc_info()[0] is not None:
            connection=service._native_file_connections.get(channel)
            service._end_native_file_connection(channel)
            if connection is not None and connection._desktop_session is not None:assert connection._desktop_session.join(10)
        if errors:raise errors[0]


def native_ui(service, peer, request):
    directory=tempfile.TemporaryDirectory(prefix='photos330-ui-',dir='/tmp/opencode')
    server=background.IPCServer(None,str(Path(directory.name)/'service.sock'),phone_backend=service,
        settings_getter=lambda:background.normalize_settings({})).start()
    def cleanup():
        server.close();directory.cleanup()
    request.addfinalizer(cleanup)
    proxy=background.PhoneServiceProxy(server.path)
    path=Path(__file__).parents[1]/'bin/magnolie-organizer'
    tree=ast.parse(path.read_text())
    method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
        if isinstance(node,ast.FunctionDef) and node.name=='_telefon_foto_aktion')
    namespace={'_':lambda value:value}
    exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),namespace)
    answers=[]
    window=SimpleNamespace(_gesperrt=False,_telefon=proxy,antwort=lambda function,value:answers.append((function,value)),
        _telefon_stand_melden=lambda:None)
    fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    def action(value):
        count=len(answers);errors=[]
        def call():
            try:namespace['_telefon_foto_aktion'](window,dict(kennung=peer['device_id'],fingerprint=fingerprint,request=value))
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=call,name='fixture-native-photo-ui');worker.start();worker.join(10)
        assert not worker.is_alive() and not errors
        assert len(answers)==count+1 and answers[-1][0]=='App.telefonFotoErgebnis'
        assert answers[-1][1]['ok'] is True,answers[-1]
    return action


def test_native_enable_permission_catalog_sync_and_repeat_preserve_pairing_and_pc_crop(native,tmp_path,monkeypatch,request):
    service,peer,_=native
    peer.pop('file_pairing_epoch');service.store.save_peers()
    channel,binding=bind(service,peer)
    converge_controls(service,peer,channel)
    original=deepcopy(peer)
    pictures=tmp_path/'Native-Pictures';pictures.mkdir(mode=0o700)
    from gi.repository import GLib
    monkeypatch.setattr(GLib,'get_user_special_dir',lambda kind:str(pictures))
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    monkeypatch.setattr(service.store,'save_peers',lambda:pytest.fail('Native activation used normalizing full-list writer'))
    monkeypatch.setattr(phone.PhoneStore,'__init__',lambda *args,**kwargs:pytest.fail('Native activation reconstructed identity/store'))
    key=Path(service.store.storage_path).read_bytes(); identity=Path(service.store.identity_path).read_bytes()
    fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    ui_action=native_ui(service,peer,request)
    with metadata_phone(service,peer,channel) as (commands,errors):
        ui_action(dict(action='enable'))
        connection=service._native_file_connections[channel];session=connection.desktop_session()
        assert session.join(15),session.snapshot()
        assert session.snapshot()['state']=='albums',session.snapshot().get('error')
        assert not session.snapshot()['busy'] and session.snapshot()['mode']=='manual'
        assert commands==['status','configure','discover','request_read','discover']
        assert service.store.peers[0]==dict(original,file_pairing_epoch=service.store.peers[0]['file_pairing_epoch'])
        assert service._file_channel_bindings[channel].local_identity is binding.local_identity
        with ExistingFileTransferProtection(str(service.store.root)) as protection:
            assert phone.strict_json(protection.read_native_peers_blob())['items']==service.store.peers
        ui_action(dict(action='discover'))
        assert session.join(10) and session.snapshot()['state']=='albums',session.snapshot()
        assert session.snapshot()['albums'][0]['album_id']==ALBUM
        target=Path(session.snapshot()['destination'])
        fixture=(service,peer,channel,connection,target)
        full=manifest(fixture)
    try:
        for cycle in range(2):
            current=replace(full,transfer_id=str(cycle+3)*32,source_id=str(cycle+4)*32,
                files=(replace(full.files[0],id=str(cycle+5)*32),))
            with phone_batches(fixture,[current]) as (chunks,saved,_,_,errors):
                ui_action(dict(action='sync',album_id=ALBUM))
                assert session.join(45),session.snapshot()
                assert session.snapshot()['state']=='complete',session.snapshot().get('error')
                assert len(chunks)==len(saved)==(1 if cycle==0 else 0)
                assert not errors
            path=target/full.files[0].path
            if cycle==0:path.write_bytes(b'user PC crop');before=(path.stat().st_ino,path.read_bytes())
            else:assert (path.stat().st_ino,path.read_bytes())==before
        ui_action(dict(action='disable'))
        assert session.join(10) and session.snapshot()['state']=='off'
        assert connection._preferences.read().policy.enabled is False
        assert Path(service.store.storage_path).read_bytes()==key
        assert Path(service.store.identity_path).read_bytes()==identity
    finally:
        service._end_native_file_connection(channel);assert session.join(10)


@pytest.mark.parametrize('change',['readiness','fingerprint','key','foreign_peer','own_consent'])
def test_native_activation_never_repairs_missing_authority_or_changes_peer_preferences(native,monkeypatch,change):
    service,peer,_=native;peer.pop('file_pairing_epoch');service.store.save_peers();channel,_=bind(service,peer)
    converge_controls(service,peer,channel)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',change!='readiness')
    fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    held=None;key=Path(service.store.storage_path)
    if change=='fingerprint':fingerprint='0'*64
    if change=='key':held=key.with_name('held-native-key');key.rename(held)
    if change=='foreign_peer':service.store.peers[0]=dict(peer,display_name='Preserve a concurrent edit')
    if change=='own_consent':peer['personal_sync']['remote_own_device']=False
    original=deepcopy(service.store.peers);cipher=Path(service.store.peers_path).read_bytes()
    try:
        with pytest.raises((ValueError,OSError)):
            service.photo_sync_action(peer['device_id'],fingerprint,dict(action='enable'))
        assert service.store.peers==original and Path(service.store.peers_path).read_bytes()==cipher
        assert not service._native_file_connections
        if held is not None:assert not key.exists()
    finally:
        if held is not None:held.rename(key)


def test_protected_bootstrap_preserves_original_on_revocation_and_keeps_postcommit_metadata(native):
    service,peer,_=native;peer.pop('file_pairing_epoch');service.store.save_peers()
    original=deepcopy(peer);path=Path(service.store.peers_path);cipher=path.read_bytes()
    with ExistingFileTransferProtection(str(service.store.root)) as protection:
        with pytest.raises(TransferError):protection.initialize_native_file_pairing(original,lambda:False,lambda peer:None)
        assert path.read_bytes()==cipher
        published=[]
        def live():return not published
        with pytest.raises(TransferError):protection.initialize_native_file_pairing(original,live,published.append)
        assert len(published)==1
        saved=phone.strict_json(protection.read_native_peers_blob())['items'][0]
        assert saved==published[0] and {key:value for key,value in saved.items() if key!='file_pairing_epoch'}==original


@pytest.mark.parametrize('change',['preference','staging_alias','key_removed','revoked'])
def test_bootstrap_commit_rechecks_user_edits_staging_identity_existing_key_and_native_consent(native,tmp_path,change):
    service,peer,_=native;peer.pop('file_pairing_epoch');service.store.save_peers()
    original=deepcopy(peer);path=Path(service.store.peers_path);cipher=path.read_bytes();root=path.parent
    key=Path(service.store.storage_path);held=key.with_name('held-bootstrap-key');outside=tmp_path/'outside';outside.write_bytes(b'preserve outside')
    changed=False
    def permitted():
        nonlocal changed
        stages=list(root.glob('peers.json.file-*.new'))
        if stages and not changed:
            changed=True
            if change=='preference':
                peer['display_name']='Keep concurrent native preference';service.store.save_peers()
            elif change=='staging_alias':
                stages[0].rename(stages[0].with_suffix('.held'));stages[0].symlink_to(outside)
            elif change=='key_removed':key.rename(held)
        return not (changed and change=='revoked')
    try:
        with ExistingFileTransferProtection(str(root)) as protection:
            with pytest.raises((TransferError,OSError)):
                protection.initialize_native_file_pairing(original,permitted,lambda value:pytest.fail('Stale bootstrap published'))
        assert changed and outside.read_bytes()==b'preserve outside'
        if change=='preference':
            assert phone.strict_json(service.store._decrypt_file(str(path),'peers','all'))['items'][0]['display_name']=='Keep concurrent native preference'
        else:assert path.read_bytes()==cipher
        assert 'file_pairing_epoch' not in service.store.peers[0]
        if change=='key_removed':assert not key.exists()
    finally:
        if held.exists():held.rename(key)


def test_activation_preserves_unknown_staging_files_instead_of_cleaning_or_overwriting_them(native):
    service,peer,_=native;peer.pop('file_pairing_epoch');service.store.save_peers()
    root=Path(service.store.root);original=Path(service.store.peers_path).read_bytes()
    held={root/f'peers.json.file-user-{index}.new':f'preserve {index}'.encode() for index in range(4)}
    for path,data in held.items():path.write_bytes(data)
    with ExistingFileTransferProtection(str(root)) as protection:
        with pytest.raises(TransferError,match='staging_held'):
            protection.initialize_native_file_pairing(deepcopy(peer),lambda:True,lambda value:None)
    assert {path:path.read_bytes() for path in held}==held
    assert Path(service.store.peers_path).read_bytes()==original


def test_real_gtk_ipc_stop_then_sync_resumes_same_native_job_and_saved_end(receiving,request):
    service,peer,channel,connection,target=receiving
    converge_controls(service,peer,channel)
    batches=prepared(receiving)[:1];session=connection.desktop_session();session._local_enabled(True)
    action=native_ui(service,peer,request)
    def metadata(message):
        assert message['body']['operation']=='discover'
        service._payload(peer,channel,response(message,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
            after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    with phone_batches(receiving,batches,block_chunk=True,metadata_handler=metadata) as (_,saved,entered,release,_):
        action(dict(action='discover'));assert session.join(10),session.snapshot()
        action(dict(action='sync',album_id=ALBUM));assert entered.wait(10),session.snapshot()
        receiver=connection._run.receiver;job=receiver.job;history=receiver._index.media_history
        action(dict(action='stop'))
        assert session.snapshot()['busy'] and service._native_media_activity()['synchronizing']
        release.set();assert session.join(30),session.snapshot()
        assert session.snapshot()['state']=='canceled' and not saved,session.snapshot()
    with phone_batches(receiving,batches,resume_job=job,resume_media=history) as (chunks,saved,_,_,errors):
        action(dict(action='sync',album_id=ALBUM))
        assert session.join(45),session.snapshot()
        assert session.snapshot()['state']=='complete',session.snapshot()
        assert not errors and not chunks and len(saved)==1
        assert connection._catalog.jobs()[0].owner==job.owner
        assert connection._catalog.jobs()[0].reserved_bytes==0
        assert not service._native_media_activity()['synchronizing']
        assert (target/batches[0].files[0].path).read_bytes()==b'hello'


def test_native_session_keeps_existing_custom_destination_and_never_guesses_native_pictures(receiving,monkeypatch):
    service,peer,channel,connection,target=receiving
    from gi.repository import GLib
    monkeypatch.setattr(GLib,'get_user_special_dir',lambda kind:pytest.fail('Custom destination was replaced'))
    session=connection.desktop_session()
    session._local_enabled(True)
    assert Path(session.snapshot()['destination'])==target
    assert connection._preferences.read().policy.destination.path==str(target)
    assert not session.snapshot()['busy'] and connection._album_worker is None


def test_manual_automatic_mode_is_protected_but_never_rotates_native_file_grants_or_destination(receiving):
    service,peer,channel,connection,target=receiving
    preferences=connection._preferences;before=preferences.read();binding=connection._receive_binding()
    grant=preferences.local_grant(True).grants;peers=Path(service.store.peers_path).read_bytes()
    for mode in ('automatic','manual','automatic','manual'):
        current=preferences.set_mode(preferences.issue_action(),preferences.read(),mode)
        assert current.mode==mode
        assert connection._receive_binding()==binding
        assert preferences.local_grant(True).grants==grant
        assert current.policy.destination==before.policy.destination
        assert current.policy.destination_token==before.policy.destination_token
        assert current.policy.permission_epoch==before.policy.permission_epoch
    assert preferences.read().policy.revision>before.policy.revision
    assert Path(service.store.peers_path).read_bytes()==peers
    assert not list(target.iterdir()) and connection._album_worker is None


@pytest.mark.parametrize('capture',[False,True],ids=['ordinary_photos','camera_grouping'])
def test_real_automatic_worker_manual_switch_waits_for_io_end_and_repeat_keeps_pc_edit(receiving,monkeypatch,capture):
    service,peer,channel,connection,target=receiving
    converge_controls(service,peer,channel)
    batches=prepared(receiving)[:1]
    if capture:
        connection.set_future_capture_layout(connection.issue_receive_action(),separate=True,historical_choice='keep_existing')
    session=connection.desktop_session();session._local_enabled(True)
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',.02)
    fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    binding=connection._receive_binding();completed=threading.Event()
    def event(kind,payload):
        if kind=='photo_sync' and session.snapshot()['state']=='complete' and not session.snapshot()['busy']:completed.set()
    service.callback=event
    def metadata(message):
        assert message['body']['operation']=='discover'
        service._payload(peer,channel,response(message,sources.CATALOG,version='b'*64,page=dict(format=1,catalog_id=CATALOG,
            after=0,next_cursor=None,coverage='full_images',proves_deletion=False,
            albums=[dict(album_id=ALBUM,kind='camera',display_name='Camera',visible_images=1,needs_choice=False)])))
    try:
        with phone_batches(receiving,batches,block_chunk=True,metadata_handler=metadata) as (chunks,saved,entered,release,errors):
            service.photo_sync_action(peer['device_id'],fingerprint,dict(action='mode_automatic'))
            assert entered.wait(10),session.snapshot()
            token=session._schedule.active
            assert token is not None and service._native_media_activity()['synchronizing']
            assert connection._run.accepted.binding==binding
            service.photo_sync_action(peer['device_id'],fingerprint,dict(action='mode_manual'))
            # Inspect the committed ciphertext without competing for the live
            # receiver's nonblocking native preference-reader gate.
            prefs_path=Path(connection._authority.binding.native_directory)/connection._preferences._name/'prefs.sqlite'
            with sqlite3.connect(prefs_path.as_uri()+'?mode=ro',uri=True) as observer:
                blob=observer.execute('SELECT payload FROM policy WHERE id=1').fetchone()[0]
            assert sha256(blob).hexdigest()==connection._run.policy_version
            assert session.snapshot()['mode']=='manual' and session._mode=='automatic'
            assert session._schedule.active is token and service._native_media_activity()['synchronizing']
            with pytest.raises(TransferError,match='busy'):
                service.photo_sync_action(peer['device_id'],fingerprint,dict(action='sync',album_id=ALBUM))
            release.set();assert completed.wait(20),session.snapshot();assert session.join(10)
            assert session.snapshot()['mode']=='manual' and connection._preferences.read().mode=='manual'
            assert session._schedule.active is None and not service._native_media_activity()['synchronizing']
            assert len(chunks)==len(saved)==1 and not errors
            assert connection._receive_binding()==binding
            path=target/(('Eigene Aufnahmen/' if capture else '')+batches[0].files[0].path)
            path.write_bytes(b'keep automatic PC crop');before=(path.stat().st_ino,path.read_bytes())
            completed.clear()
            service.photo_sync_action(peer['device_id'],fingerprint,dict(action='mode_automatic'))
            assert completed.wait(20),(session.snapshot()['state'],session.snapshot()['error']);assert session.join(10)
            assert len(chunks)==len(saved)==1 # The actual automatic repeat requested no duplicate chunk/Saved.
            assert (path.stat().st_ino,path.read_bytes())==before
            assert not service._native_media_activity()['synchronizing'] # Timer lifetime is not activity.
            service.photo_sync_action(peer['device_id'],fingerprint,dict(action='mode_manual'))
            assert session.join(10) and session._schedule.active is None
            assert connection._receive_binding()==binding
    finally:
        service._end_native_file_connection(channel);assert session.join(10)


def test_file_availability_waits_for_real_control_ack_and_fresh_own_pc_metadata(native,monkeypatch):
    service,peer,_=native;channel,binding=bind(service,peer)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    assert service.photo_sync_state(peer['device_id']) is None
    at=phone.now_ms();message=dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='capabilities.update',
        created_ms=at,expires_ms=at+60_000,body=deepcopy(peer['capabilities']))
    message['body']['revision']+=1
    channel.send.side_effect=OSError('fixture failed encrypted ACK write')
    with pytest.raises(OSError):service._payload(peer,channel,message)
    assert not service._native_file_controls.get(channel)
    channel.send.side_effect=None
    service._payload(peer,channel,message) # Exact duplicate still requires a real new ACK.
    assert 'capabilities.update' in service._native_file_controls[channel]
    assert service.photo_sync_state(peer['device_id']) is None
    converge_controls(service,peer,channel)
    assert service.photo_sync_state(peer['device_id'])['available']
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    try:
        service._payload(peer,channel,dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='personal_sync.settings',
            created_ms=at,expires_ms=at+60_000,body=dict(format=1,own_device=False)))
        assert service.photo_sync_state(peer['device_id']) is None
        assert authority.current_peer() is None
    finally:authority.close()


def test_replayed_positive_own_receipt_cannot_undo_later_file_withdrawal(native,monkeypatch):
    service,peer,_=native;channel,_=bind(service,peer)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    converge_controls(service,peer,channel)
    at=phone.now_ms()
    def decision(own):
        return dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='personal_sync.settings',
            created_ms=at,expires_ms=at+60_000,body=dict(format=1,own_device=own))
    positive=decision(True)
    service._payload(peer,channel,positive)
    service._payload(peer,channel,decision(False))
    assert service.photo_sync_state(peer['device_id']) is None
    service._payload(peer,channel,positive)
    assert service.photo_sync_state(peer['device_id']) is None
    service._payload(peer,channel,decision(True))
    assert service.photo_sync_state(peer['device_id'])['available']


def test_native_own_withdrawal_precedes_ack_and_failed_positive_ack_cannot_restore(native,monkeypatch):
    service,peer,_=native;channel,_=bind(service,peer)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    converge_controls(service,peer,channel)
    assert service.photo_sync_state(peer['device_id'])['available']
    def decision(own,at=None):
        at=phone.now_ms() if at is None else at
        return dict(type='message',v=1,message_id=str(uuid.uuid4()),kind='personal_sync.settings',
            created_ms=at,expires_ms=at+60_000,body=dict(format=1,own_device=own))
    channel.send.side_effect=OSError('Fixture secure ACK failed')
    with pytest.raises(OSError):service._payload(peer,channel,decision(False))
    assert service.photo_sync_state(peer['device_id']) is None
    failed_positive=decision(True)
    with pytest.raises(OSError):service._payload(peer,channel,failed_positive)
    assert service.photo_sync_state(peer['device_id']) is None
    channel.send.side_effect=None
    service._payload(peer,channel,failed_positive) # Old receipt is not a new consent decision.
    assert service.photo_sync_state(peer['device_id']) is None
    service._payload(peer,channel,decision(True,phone.now_ms()-120_000))
    assert service.photo_sync_state(peer['device_id']) is None
    service._payload(peer,channel,decision(True))
    assert service.photo_sync_state(peer['device_id'])['available']


def test_permission_reply_alone_never_exposes_an_album_or_starts_a_download(native,tmp_path,monkeypatch):
    service,peer,_=native;channel,_=bind(service,peer);converge_controls(service,peer,channel)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    monkeypatch.setattr(NativePhotoDesktopSession,'READ_WAIT_SECONDS',.01)
    pictures=tmp_path/'native-pictures';pictures.mkdir(mode=0o700)
    from gi.repository import GLib
    monkeypatch.setattr(GLib,'get_user_special_dir',lambda kind:str(pictures))
    fingerprint=phone.fingerprint(phone.unb64(peer['static_public'],32))
    try:
        with metadata_phone(service,peer,channel,grant_on_read=False):
            service.photo_sync_action(peer['device_id'],fingerprint,dict(action='enable'))
            connection=service._native_file_connections[channel];session=connection.desktop_session()
            assert session.join(10),session.snapshot()
            assert session.snapshot()['state']=='permission_required' and not session.snapshot()['albums']
            assert connection._album_worker is None and connection._run is None
            assert not list(pictures.glob('**/*.jpg'))
            assert not any(call.args[0]['kind']=='file_transfer.chunk.request' for call in channel.send.call_args_list)
    finally:
        connection=service._native_file_connections.get(channel)
        service._end_native_file_connection(channel)
        if connection is not None:assert connection.desktop_session().join(10)


@pytest.mark.parametrize('built,ready',[(False,False),(False,True),(True,False),(True,True)])
def test_discovery_advertisement_requires_compiled_payload_and_actual_native_handlers(monkeypatch,built,ready):
    monkeypatch.setattr(phone.optional_phone,'available',lambda feature:built)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',ready)
    assert (21 in phone.desktop_capabilities()['items']['device_status']['versions']) is (built and ready)


@pytest.mark.parametrize('profile',['absent','legacy'])
def test_reconnect_without_policy_never_bootstraps_or_creates_defaults(native,monkeypatch,profile):
    service,peer,_=native
    if profile=='legacy':peer.pop('file_pairing_epoch');service.store.save_peers()
    channel,_=bind(service,peer)
    monkeypatch.setattr(NativeDesktopFileConnection,'_data_handlers_ready',True)
    root=Path(service.store.root)
    before={path.relative_to(root):path.read_bytes() for path in root.rglob('*') if path.is_file()}
    converge_controls(service,peer,channel)
    after={path.relative_to(root):path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert not service._native_file_connections
    assert not any(path.name.startswith('photo') for path in after if path not in before)
    assert after[Path('storage.key')]==before[Path('storage.key')]
    assert ('file_pairing_epoch' in peer) is (profile!='legacy')
    assert not any(call.args[0].get('kind','').startswith('file_transfer.') for call in channel.send.call_args_list)


@pytest.mark.parametrize('profile',['manual','off','automatic','source_revoked'])
def test_reconnection_resumes_only_existing_automatic_consent_after_new_channel_ack(receiving,monkeypatch,profile):
    service,peer,old_channel,old_connection,target=receiving
    prepared(receiving)
    prefs=old_connection._preferences
    if profile in ('automatic','source_revoked'):prefs.set_mode(prefs.issue_action(),prefs.read(),'automatic')
    if profile=='off':old_connection.desktop_session()._local_enabled(False)
    version=prefs.read().version
    service._end_native_file_connection(old_channel)
    monkeypatch.setattr(NativePhotoDesktopSession,'AUTO_TICK_SECONDS',30) # Isolate reconnect preparation from later scheduled I/O.
    channel,_=bind(service,peer)
    assert channel not in service._native_file_connections
    with metadata_phone(service,peer,channel,initial_enabled=profile!='source_revoked',initial_read=True) as (commands,errors):
        converge_controls(service,peer,channel)
        connection=service._native_file_connections.get(channel)
        if profile in ('manual','off'):
            assert connection is None and commands==[]
            assert not list(target.iterdir())
            return
        try:
            assert connection is not None
            session=connection.desktop_session();assert session.join(10),session.snapshot()
            assert commands==(['status','discover'] if profile=='automatic' else ['status'])
            assert session.snapshot()['state']==('albums' if profile=='automatic' else 'held'),session.snapshot()
            assert connection._preferences.read().version==version
            assert not errors and connection._album_worker is None and not list(target.iterdir())
        finally:
            service._end_native_file_connection(channel);assert session.join(10)
