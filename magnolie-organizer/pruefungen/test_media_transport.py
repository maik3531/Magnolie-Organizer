"""Native encrypted socket-pair agreement; no physical network or source IO."""
from pathlib import Path
import base64
import copy
import socket
import sys
import types
import uuid

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_telefon as phone
import magnolie_media_sync as media
from magnolie_media_transport import NativeMediaSettingsTransport
from magnolie_file_native_authority import capture_authenticated_binding
from test_file_authenticated_desktop import native

AT=1800000000000


class PeerWire:
    def __init__(self,sock):self.sock=sock;self.sent=0;self.received=0

    def send(self,message):
        header=dict(p=phone.PROTOCOL,sid=phone.b64(bytes([3])*16),seq=self.sent,dir='phone_to_desktop')
        cipher=AESGCM(bytes([2])*32).encrypt(bytes([2])*4+self.sent.to_bytes(8,'big'),phone.canonical(message),phone.canonical(header))
        phone.send_frame(self.sock,dict(header,ciphertext=phone.b64(cipher)));self.sent+=1

    def receive(self):
        frame=phone.receive_frame(self.sock,phone.SECURE_FRAME_MAX)
        header=dict(p=phone.PROTOCOL,sid=phone.b64(bytes([3])*16),seq=self.received,dir='desktop_to_phone')
        assert {key:value for key,value in frame.items() if key!='ciphertext'}==header
        raw=AESGCM(bytes([1])*32).decrypt(bytes([1])*4+self.received.to_bytes(8,'big'),base64.b64decode(frame['ciphertext']),phone.canonical(header))
        self.received+=1;result=phone.strict_json(raw);assert phone.canonical(result)==raw;return result


@pytest.fixture
def transport(native):
    service,peer,_=native
    peer['capabilities']['items']['device_status']['versions'].append(23);service.store.save_peers()
    left,right=socket.socketpair();left.settimeout(2);right.settimeout(2)
    channel=phone.SecureChannel(left,bytes([3])*16,bytes([1])*32,bytes([1])*4,bytes([2])*32,bytes([2])*4)
    binding=capture_authenticated_binding(dict(service.store.identity),dict(peer),service._generation,service.store)
    service._activate_connection(peer['device_id'],channel,'wifi',file_binding=binding)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    ready=[True];controller=NativeMediaSettingsTransport(authority,lambda:ready[0],clock=lambda:AT)
    wire=PeerWire(right)
    try:yield types.SimpleNamespace(service=service,peer=peer,authority=authority,controller=controller,ready=ready,wire=wire,channel=channel)
    finally:controller.close();authority.close();left.close();right.close()


def incoming(body,identifier=None):
    return dict(type='message',v=1,message_id=identifier or str(uuid.uuid4()),kind=media.KIND,created_ms=AT,
        expires_ms=AT+60000,body=copy.deepcopy(body))


def deliver(h,message):
    h.wire.send(message);return h.controller.observe(h.channel,h.channel.receive())


def echo(h,body):
    assert deliver(h,incoming(body));ack=h.wire.receive();assert ack['type']=='ack' and ack['status']=='accepted'


def agreement(h):
    h.controller.change('enabled',True);h.controller.change('direction','two_way')
    attempted=h.controller.send_settings();sent=h.wire.receive();assert sent==attempted
    assert h.controller.intent_for('images',to_phone=True) is None
    assert deliver(h,dict(type='ack',message_id=sent['message_id'],status='accepted',error='none'))
    assert h.controller.intent_for('images',to_phone=True) is None
    echo(h,sent['body'])
    return sent


def test_actual_secure_send_correlated_ack_and_acknowledged_peer_echo_are_all_required(transport):
    h=transport;sent=agreement(h);token=h.controller.intent_for('images',to_phone=True)
    assert token is not None and token.body==sent['body']
    assert h.controller.intent_for('video',to_phone=True) is None
    body=token.body;body['settings']['enabled'].clear()
    assert token.body==sent['body']
    from magnolie_photo_preferences import ProtectedPhotoPreferences
    prefs=ProtectedPhotoPreferences(h.authority)
    try:
        assert prefs.read().policy is None
        assert not prefs.local_grant(True).grants.send_files and not prefs.local_grant(True).grants.receive_files
    finally:prefs.close()


def test_unrelated_ack_or_foreign_channel_cannot_publish_and_peer_echo_before_ack_still_waits(transport):
    h=transport;h.controller.change('enabled',True);sent=h.controller.send_settings();assert h.wire.receive()==sent
    echo(h,sent['body'])
    assert h.controller.intent_for('images') is None
    assert not deliver(h,dict(type='ack',message_id=str(uuid.uuid4()),status='accepted',error='none'))
    ack=dict(type='ack',message_id=sent['message_id'],status='duplicate',error='none')
    assert not h.controller.observe(object(),ack) and h.controller.intent_for('images') is None
    assert deliver(h,ack) and h.controller.intent_for('images') is not None


def test_failed_actual_peer_ack_output_never_publishes_even_after_persisted_merge(transport,monkeypatch):
    h=transport;h.controller.change('enabled',True);sent=h.controller.send_settings();h.wire.receive()
    deliver(h,dict(type='ack',message_id=sent['message_id'],status='accepted',error='none'))
    send=h.channel.send
    def fail_ack(message):
        if message.get('type')=='ack':raise OSError('explicit native ACK output failure')
        return send(message)
    monkeypatch.setattr(h.channel,'send',fail_ack)
    with pytest.raises(OSError):deliver(h,incoming(sent['body']))
    assert h.controller._store.read()==sent['body'] and h.controller.intent_for('images') is None


def test_local_change_and_backend_withdrawal_cannot_reuse_historical_matching_receipts(transport):
    h=transport;sent=agreement(h);assert h.controller.intent_for('images',to_phone=True) is not None
    h.ready[0]=False;assert h.controller.intent_for('images') is None
    h.ready[0]=True
    assert not deliver(h,dict(type='ack',message_id=sent['message_id'],status='accepted',error='none'))
    assert h.controller.intent_for('images') is None
    fresh=h.controller.send_settings();assert h.wire.receive()==fresh
    assert deliver(h,dict(type='ack',message_id=fresh['message_id'],status='accepted',error='none'))
    echo(h,fresh['body']);assert h.controller.intent_for('images') is not None
    h.controller.change('enabled',False);assert h.controller.intent_for('images') is None
    echo(h,fresh['body']);new=h.wire.receive();assert new['kind']==media.KIND and new['body']!=fresh['body']
    assert h.controller.intent_for('images') is None


def test_local_change_during_real_output_retires_the_exact_attempt_without_false_send_completion(transport,monkeypatch):
    h=transport;h.controller.change('enabled',True);send=h.channel.send
    def changed_after_output(message):
        send(message)
        if message.get('kind')==media.KIND:h.controller.change('enabled',False)
    monkeypatch.setattr(h.channel,'send',changed_after_output)
    assert h.controller.send_settings() is None
    actual=h.wire.receive();assert media.effective(actual['body'])['enabled']
    assert not deliver(h,dict(type='ack',message_id=actual['message_id'],status='accepted',error='none'))
    assert h.controller.intent_for('images') is None


def test_malformed_expired_and_equivocated_peer_messages_hold_without_source_intent(transport):
    h=transport;sent=agreement(h);assert h.controller.intent_for('images') is not None
    expired=incoming(sent['body']);expired['expires_ms']=AT
    with pytest.raises(ValueError):deliver(h,expired)
    assert h.controller.intent_for('images') is None
    first=incoming(sent['body']);echo_body=first['body'];assert deliver(h,first);h.wire.receive()
    # Receiving this body after invalidation may emit a fresh settings frame.
    if h.controller._sent is not None:h.wire.receive()
    changed=copy.deepcopy(first);changed['body']=media.change(echo_body,h.peer['device_id'],h.authority.identity.receiver_id,'skip_deletions',True)
    with pytest.raises(ValueError):deliver(h,changed)
    assert h.controller.intent_for('images') is None


def test_native_owner_revocation_and_close_end_projection_without_closing_shared_socket(transport):
    h=transport;agreement(h);assert h.controller.intent_for('images') is not None
    h.authority.revoke();assert h.controller.intent_for('images') is None
    h.controller.close();assert h.channel.sock.fileno()>=0
    with pytest.raises(PermissionError):h.controller.send_settings()
