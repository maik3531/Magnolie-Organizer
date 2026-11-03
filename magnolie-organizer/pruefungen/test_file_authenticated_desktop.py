from pathlib import Path
import hashlib
import hmac
import socket
import sys
import threading
import uuid
from unittest import mock
import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_telefon as phone
from magnolie_file_native_authority import capture_authenticated_binding
from magnolie_file_transfer import TransferError
from test_telefon import _complete_peer,FakeBluetooth

@pytest.fixture
def native(tmp_path):
    service=phone.PhoneService(str(tmp_path/'telephone'),'Fixture PC',bluetooth_backend=FakeBluetooth())
    private=X25519PrivateKey.from_private_bytes(bytes([2])*32)
    public=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    peer=_complete_peer(public=public)
    peer['personal_sync'].update(own_device=True,remote_own_device=True)
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([1])*32)
    peer['capabilities']=phone.desktop_capabilities();peer['capabilities']['items']['device_status']['versions'].append(21)
    service.store.peers=[peer];service.store.save_peers();service.enabled=True
    return service,peer,private

def bind(service,peer):
    channel=mock.Mock();binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
    service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
    return channel,binding

def test_actual_native_binding_cache_never_reloads_identity_and_factory_uses_only_existing_native_root(native,monkeypatch):
    service,peer,_=native;channel,binding=bind(service,peer)
    monkeypatch.setattr(phone.PhoneStore,'__init__',lambda *args,**kwargs:pytest.fail('File route constructed PhoneStore'))
    monkeypatch.setattr(service.store,'peer',lambda *args:pytest.fail('File route normalized personal peer'))
    monkeypatch.setattr(service.store,'sole_peer',lambda *args:pytest.fail('File route normalized personal peer'))
    identity=Path(service.store.identity_path);held=identity.with_name('held-identity');identity.rename(held)
    try:
        assert service.current_native_file_identity(peer['device_id'],peer['static_public'],channel,binding.generation)==binding.local_identity
        assert service.current_native_file_identity(peer['device_id'],peer['static_public'],mock.Mock(),binding.generation) is None
        assert service.current_native_file_identity(peer['device_id'],peer['static_public'],channel,binding.generation+1) is None
        authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
        try:
            assert authority.identity==binding.local_identity
            assert authority.current_peer().pairing_epoch==binding.pairing_epoch
            assert not identity.exists()
            service.stop_event.set()
            assert authority.current_peer() is None
            service.stop_event.clear()
            assert authority.current_peer() is None # Revoked native owner cannot revive.
        finally:authority.close()
        assert not identity.exists()
    finally:held.rename(identity)

def test_missing_native_key_cannot_be_recreated_even_with_an_authenticated_cached_identity(native):
    service,peer,_=native;channel,binding=bind(service,peer)
    key=Path(service.store.storage_path);held=key.with_name('held-storage-key');key.rename(held)
    before={path.name for path in key.parent.iterdir()}
    try:
        assert service.current_native_file_identity(peer['device_id'],peer['static_public'],channel,binding.generation) is not None
        with pytest.raises((OSError,TransferError)):service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
        assert not key.exists() and before=={path.name for path in key.parent.iterdir()}
    finally:held.rename(key)

def test_native_repair_or_store_generation_change_permanently_invalidates_authority(native):
    service,peer,_=native;channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    try:
        epoch=peer['file_pairing_epoch'];peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([3])*32);service.store.save_peers()
        assert authority.current_peer() is None
        peer['file_pairing_epoch']=epoch;service.store.save_peers()
        assert authority.current_peer() is None
        service._generation+=1
        assert service.current_native_file_identity(peer['device_id'],peer['static_public'],channel,binding.generation) is None
    finally:authority.close()

def test_replaced_authenticated_channel_cannot_reuse_its_authority_even_with_same_peer_and_key(native):
    service,peer,_=native;channel,binding=bind(service,peer)
    old=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    try:
        replacement,replacement_binding=bind(service,peer)
        assert old.current_peer() is None
        assert service.current_native_file_identity(peer['device_id'],peer['static_public'],channel,binding.generation) is None
        current=service.open_native_file_authority(peer['device_id'],peer['static_public'],replacement,replacement_binding.generation)
        try:assert current.current_peer().pairing_epoch==binding.pairing_epoch
        finally:current.close()
        assert old.current_peer() is None
    finally:old.close()

def test_native_revocation_does_not_wait_for_peer_io_or_return_late_authority(native,monkeypatch):
    service,peer,_=native;channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    entered=threading.Event();release=threading.Event();ended=threading.Event();results=[];errors=[]
    original=authority.protection.read_native_peers_blob
    def blocked():
        assert not service.lock._is_owned(), 'Native peer I/O ran under PhoneService ownership monitor'
        entered.set();assert release.wait(5)
        return original()
    monkeypatch.setattr(authority.protection,'read_native_peers_blob',blocked)
    def read():
        try:results.append(authority.current_peer())
        except Exception as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=read);worker.start()
    try:
        assert entered.wait(5)
        authority.revoke()
        assert not authority.protection._closed # Native owner retains resources until actual I/O end.
        assert authority.current_peer() is None
        release.set();assert ended.wait(5);worker.join(5)
        assert results==[None] and not errors
        authority.close();assert authority.protection._closed
    finally:
        release.set();assert ended.wait(5);worker.join(5);authority.close()

@pytest.mark.parametrize('mode',['normal','generation-change','file-control','file-receive'])
def test_actual_crypto_session_captures_its_authenticated_public_identity_and_removes_it_at_transport_end(native,monkeypatch,mode):
    service,peer,private=native
    # Leave unrelated personal outbox producers inert in this focused crypto /
    # native-channel test. No listener, external server or background scheduler.
    monkeypatch.setattr(service,'_ensure_desktop_updates',lambda *args,**kwargs:None)
    monkeypatch.setattr(service,'_queue_note_settings',lambda *args,**kwargs:None)
    monkeypatch.setattr(service.store,'pending',lambda *args,**kwargs:[])
    activated=threading.Event();service.callback=lambda event,payload:activated.set() if event=='status' else None
    identity=dict(service.store.identity);server_public=X25519PublicKey.from_public_bytes(phone.unb64(identity['static_public'],32))
    ids=b'\0'.join(sorted([peer['device_id'].encode(),identity['device_id'].encode()]))
    static_root=phone.hkdf(private.exchange(server_public),hashlib.sha256(b'magnolie-phone-fs1/static-salt\0'+ids).digest(),b'magnolie-phone-fs1/static-root\0'+ids,32)
    auth=phone.hkdf(static_root,None,b'magnolie-phone-fs1/auth\0',32)
    ephemeral=X25519PrivateKey.from_private_bytes(bytes([3])*32);sid=bytes([5])*16
    start=dict(p=phone.PROTOCOL,type='session_start',sid=phone.b64(sid),**{'from':peer['device_id'],'to':identity['device_id']},
               initiator_role='phone',ephemeral_public=phone.b64(ephemeral.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)),nonce=phone.b64(bytes([6])*32),versions=[1])
    start['mac']=phone.b64(hmac.new(auth,b'magnolie-phone-fs1/start\0'+phone.canonical(start),hashlib.sha256).digest())
    left,right=socket.socketpair();left.settimeout(5);right.settimeout(5);failed=[]
    def serve():
        try:service._session(left,start)
        except Exception as error:failed.append(error)
    worker=threading.Thread(target=serve);worker.start()
    try:
        response=phone.receive_frame(right,phone.PAIR_FRAME_MAX);without=dict(response);without.pop('mac')
        assert hmac.compare_digest(phone.unb64(response['mac'],32),hmac.new(auth,b'magnolie-phone-fs1/response\0'+phone.canonical(start)+phone.canonical(without),hashlib.sha256).digest())
        transcript=hashlib.sha256(phone.canonical(start)+phone.canonical(response)).digest()
        salt=hmac.new(static_root,b'magnolie-phone-fs1/session-salt\0'+transcript,hashlib.sha256).digest()
        material=phone.hkdf(ephemeral.exchange(X25519PublicKey.from_public_bytes(phone.unb64(response['ephemeral_public'],32))),salt,b'magnolie-phone-fs1/session-keys\0'+transcript,72)
        # Production SecureChannel is deliberately desktop-directional. This
        # native phone counterpart must use the opposite authenticated dir/AAD.
        sent=0;received=0
        def send(payload):
            nonlocal sent
            aad=dict(p=phone.PROTOCOL,sid=phone.b64(sid),seq=sent,dir='phone_to_desktop')
            encrypted=AESGCM(material[:32]).encrypt(material[32:36]+sent.to_bytes(8,'big'),phone.canonical(payload),phone.canonical(aad))
            phone.send_frame(right,dict(aad,ciphertext=phone.b64(encrypted)));sent+=1
        def receive():
            nonlocal received
            frame=phone.receive_frame(right,phone.SECURE_FRAME_MAX)
            aad=dict(p=phone.PROTOCOL,sid=phone.b64(sid),seq=received,dir='desktop_to_phone')
            assert {key:value for key,value in frame.items() if key!='ciphertext'}==aad
            plain=AESGCM(material[36:68]).decrypt(material[68:72]+received.to_bytes(8,'big'),phone.base64.b64decode(frame['ciphertext'],validate=True),phone.canonical(aad))
            received+=1;return phone.strict_json(plain)
        if mode=='generation-change':service._generation+=1
        send(dict(type='session_ready',connection_id=str(uuid.uuid4()),capabilities_revision=1,last_received_seq=-1))
        assert receive()['type']=='session_ready'
        if mode=='generation-change':
            worker.join(5);assert not worker.is_alive()
            assert len(failed)==1 and isinstance(failed[0],OSError) and 'native_channel_changed' in str(failed[0]);failed.clear()
            assert not service._file_channel_bindings and not service.connections
        else:
            assert activated.wait(5)
            server_channel=service.connections[peer['device_id']]
            native_identity=service.current_native_file_identity(peer['device_id'],peer['static_public'],server_channel,service._generation)
            assert native_identity.receiver_id==identity['device_id']
            assert native_identity.receiver_identity_sha256==hashlib.sha256(phone.unb64(identity['static_public'],32)).hexdigest()
            native_connection = None
            if mode in ('file-control', 'file-receive'):
                from magnolie_file_control import KIND, FileControlPacket, FileGrantState
                if mode == 'file-receive':
                    from magnolie_file_desktop_connection import NativeDesktopFileConnection
                    monkeypatch.setattr(NativeDesktopFileConnection, '_data_handlers_ready', True)  # Fixture only.
                native_connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], server_channel, service._generation)
                if mode == 'file-receive':
                    from magnolie_photo_destination import NativePhotoDestinationController
                    target = Path(service.store.root).parent/'explicit-native-photo-target'
                    target.mkdir(mode=0o700)
                    chooser = NativePhotoDestinationController(native_connection._authority)
                    try:
                        choice = chooser.choose_custom(chooser.issue_action(), target)
                        prefs = native_connection._preferences
                        prefs.configure(prefs.issue_action(), prefs.read(), enabled=True, mode='manual', destination_choice=choice)
                    finally: chooser.close()
                observed = threading.Event()
                dispatch = native_connection.receive
                def receive_native(message):
                    try: return dispatch(message)
                    finally: observed.set()
                monkeypatch.setattr(native_connection, 'receive', receive_native)
                assert native_connection.send_controls()
                first = receive()
                assert first['kind'] == KIND
                local = FileControlPacket.parse(first['body'])
                remote = FileControlPacket(FileGrantState(1, 'a'*64, mode == 'file-receive', mode != 'file-receive'), 'b'*64, 1, local.challenge)
                at = phone.now_ms()
                send(dict(type='message', v=1, message_id=str(uuid.uuid4()), kind=KIND,
                          created_ms=at, expires_ms=at+60_000, body=remote.wire()))
                echo = receive()
                assert echo['kind'] == KIND and observed.wait(5)
                echoed = FileControlPacket.parse(echo['body'])
                assert echoed.echo == remote.challenge
                assert not echoed.grants.send_files
                assert native_connection._controls._sent_grants == echoed.grants
                if mode == 'file-control':
                    assert not echoed.grants.receive_files
                    assert native_connection.read_preferences().policy is None
                    assert not list(Path(service.store.root).glob('photo-preferences-v1-*'))
                else:
                    from magnolie_file_offer import create_offer
                    from magnolie_file_transfer import FileManifest, ManifestFile
                    assert echoed.grants.receive_files
                    data = b'actual encrypted native receiver bytes'
                    manifest = FileManifest('1'*32, '2'*32, peer['device_id'], identity['device_id'],
                        (ManifestFile('3'*32, 'Camera/native.jpg', len(data), hashlib.sha256(data).hexdigest()),), len(data))
                    offered = create_offer(manifest)
                    observed.clear(); send(offered); assert observed.wait(5)
                    assert not (target/'Camera/native.jpg').exists()
                    native_connection.accept_pending_offer(native_connection.issue_receive_action(), offered['message_id'])
                    accepted = receive()
                    assert accepted['kind'] == 'file_transfer.accept'
                    assert accepted['body']['manifest_sha256'] == manifest.fingerprint
                    request = native_connection.request_next_chunk()
                    assert receive() == request
                    at = phone.now_ms()
                    response = dict(type='message', v=1, message_id=str(uuid.uuid4()), kind='file_transfer.chunk',
                        created_ms=at, expires_ms=at+60_000, body=dict(request['body'], request_id=request['message_id'],
                        data_base64=phone.base64.b64encode(data).decode(), data_sha256=hashlib.sha256(data).hexdigest()))
                    observed.clear(); send(response); assert observed.wait(5)
                    progress = native_connection.receive_progress()
                    assert progress.verified_bytes == len(data) and progress.checkpoint_verified_bytes == len(data)
                    assert not progress.is_saved_receipt and not (target/'Camera/native.jpg').exists()
                    native_connection.publish_received(native_connection.issue_receive_action())
                    saved = receive()
                    assert saved['kind'] == 'file_transfer.saved'
                    assert saved['body']['receipts'][0]['sha256'] == manifest.files[0].sha256
                    assert (target/'Camera/native.jpg').read_bytes() == data
                    assert len(native_connection._catalog.jobs()) == 1
            send(dict(type='close',reason='normal'));worker.join(5)
            assert not worker.is_alive() and not failed
            assert server_channel not in service._file_channel_bindings
            assert service.current_native_file_identity(peer['device_id'],peer['static_public'],server_channel,service._generation) is None
            if native_connection is not None:
                assert server_channel not in service._native_file_connections
                assert native_connection._authority.protection._closed
    finally:
        service.enabled=False;left.close();right.close();worker.join(5)
        assert not worker.is_alive()
        assert not failed,[(type(error).__name__,str(error)) for error in failed]
