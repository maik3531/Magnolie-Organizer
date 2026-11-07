"""#416 opt-in subprocess test host; no production listener or persisted keys.

Preparatory mapping/original offer use existing synthetic fixtures. Actual
encrypted frames then pass unchanged between the real PC channel and Kotlin
via a loopback transport relay (no synthetic readback/acceptance producer).
"""
import base64
import os
import socket
import traceback

import pytest

from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import offered
from test_media_source_backup import open_backup
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_file_published_readback import KIND
from magnolie_file_transfer import TransferError
import magnolie_telefon as phone


@pytest.mark.skipif(not os.environ.get('MAGNOLIE_PAIRED_READBACK_PORT'),reason='Explicit Kotlin subprocess only')
def test_actual_kotlin_provider_proof_completes_python_retry_and_preserves_originals(source):
    try:_run(source)
    except BaseException:
        traceback.print_exc()
        raise


def _run(source):
    h=source
    with socket.create_connection(('127.0.0.1',int(os.environ['MAGNOLIE_PAIRED_READBACK_PORT'])),timeout=10) as tcp:
        tcp.settimeout(15)
        bootstrap=phone.receive_frame(tcp,65536)
        print('paired416 mode',bootstrap['mode'],flush=True)
        raw=base64.b64decode(bootstrap['png'],validate=True);assert raw.startswith(b'\x89PNG\r\n\x1a\n')
        h.target.write_bytes(raw);old,cached,_=offered(h)
        sender=_NativeMediaSourceSender.retry(h.source,cached.manifest.source_id,old.observation().version)
        try:
            local=h.authority.identity;peer=h.authority.current_peer()
            phone.send_frame(tcp,dict(manifest=cached.manifest.wire(),pc_id=local.receiver_id,
                pc_hash=local.receiver_identity_sha256,phone_id=peer.peer_id,phone_hash=peer.identity_sha256,
                phone_send_seq=h.channel.receive_seq,phone_receive_seq=h.channel.send_seq))
            def outgoing():
                # Byte-equivalent authenticated frame relay; no payload decoding.
                phone.send_frame(tcp,phone.receive_frame(h.wire.sock,phone.SECURE_FRAME_MAX))
            def incoming():
                phone.send_frame(h.wire.sock,phone.receive_frame(tcp,phone.SECURE_FRAME_MAX))
                return h.channel.receive()
            for _ in range(3):
                print('paired416 control round',_,flush=True)
                sender.send_controls();outgoing();sender.observe_controls(h.channel,incoming())
            offer=sender.send_offer();outgoing();before_state=sender.observation()
            proof=incoming();assert proof['kind']==KIND
            if bootstrap['mode']=='wrong_offer':
                assert proof['body']['offer_id']!=offer['message_id']
                with pytest.raises(TransferError):sender.observe(h.channel,proof)
                assert sender.observation()==before_state and cached.directory.exists() and h.target.read_bytes()==raw
                phone.send_frame(tcp,dict(result='rejected',proof_sha256=proof['body']['readback_sha256'],
                    offer_id=offer['message_id'],sent_bits=sender.observation().body['sent_bits']))
                return
            assert bootstrap['mode']=='positive'
            sender.observe(h.channel,proof)
            state=sender.observation().body
            assert state['phase']=='peer_readback' and state['sent_bits']==0 and state['acceptance'] is None and state['peer_saved'] is None
            before={p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()}
            with open_backup(h) as backups:
                version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
                result=_NativeSourceRetirement(sender,backups,version).run()
            archive=cached.directory.parent/result.body['archive']
            assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
            assert h.target.read_bytes()==raw and state['peer_readback']==proof
            phone.send_frame(tcp,dict(result='archived',proof_sha256=proof['body']['readback_sha256'],
                offer_id=offer['message_id'],sent_bits=state['sent_bits']))
        finally:sender.close();old.close()
