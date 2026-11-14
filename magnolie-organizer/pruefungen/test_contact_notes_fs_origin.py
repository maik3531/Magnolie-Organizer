"""#628: actual Linux FS1 crypto/receiver -> native retained origin, no sockets."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_contact_notes_return import NativeNotesFsOrigin
from test_startup_read_failure import native


def frame(native, service, sender, receiver, body, marker=b'R' * 16):
    remote = {'kennung': receiver['kennung'], 'oeffentlich': receiver['oeffentlich']}
    start, secret = native.fs_start_bauen(sender, remote)
    status, answer = service.behandeln('/magnolie/v2/sitzung', start, '127.0.0.1')
    assert status == 200
    channel = native.fs_antwort_oeffnen(sender, remote, start, answer, secret)
    envelope = native.umschlag_bauen_fs(channel, sender['kennung'], receiver['kennung'], body, native._fs_b64(marker))
    return channel, envelope, service._fs_sitzungen[channel['sid']]


def fixture(native, callback):
    sender = native.baum_schluessel_erzeugen('Synthetic sender')
    receiver = native.baum_schluessel_erzeugen('Synthetic receiver')
    receiver.update(an=True, syncEpoch='synthetic-origin-epoch')
    peer = native.baum_partner_aufnehmen(receiver, sender['name'], sender['kennung'], sender['oeffentlich'], '127.0.0.1')
    peer['bestaetigt'] = True
    saved = []
    service = native.BaumDienst(lambda: receiver, lambda state: saved.append(copy.deepcopy(state)),
        bei_sicherer_nachricht=callback)
    return sender, receiver, peer, saved, service


def test_actual_fs1_mints_body_transport_and_pinned_identity_not_copied_json(native):
    captured = []
    body = {'art': 'kontakt_original_ergebnis', 'synthetic': 'No original/provider IO'}
    def accept(peer, received, origin, transport):
        identities = origin.require_current(received, transport)
        captured.append((origin, transport, identities))
        return True
    sender, receiver, peer, saved, service = fixture(native, accept)
    channel, envelope, opened = frame(native, service, sender, receiver, body)
    try:
        status, ack = service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')
        assert status == 200 and native.fs_ack_pruefen(channel, envelope, ack)
        origin, transport, identities = captured[0]
        assert identities == ((sender['kennung'], sender['oeffentlich']), (receiver['kennung'], receiver['oeffentlich']))
        assert origin.require_current(dict(reversed(list(body.items()))), transport) == identities
        for fake in (None, {}, body, identities):
            with pytest.raises(PermissionError): NativeNotesFsOrigin(fake).require_current(body, transport)
        with pytest.raises(PermissionError): origin.require_current(body | {'injected': True}, transport)
        with pytest.raises(PermissionError): origin.require_current(body, native._fs_b64(b'X' * 16))
        peer['name'] = receiver['name'] = 'Cosmetic change'
        assert origin.require_current(body, transport) == identities
        assert len(saved) == 1 and len(captured) == 1
        assert bytes(opened['sitzung']['kenc']) == b'\0' * 32
        assert bytes(opened['sitzung']['kack']) == b'\0' * 32
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()


@pytest.mark.parametrize('change', ['peer-key', 'own-key', 'own-id', 'epoch', 'off', 'unconfirmed', 'stopped', 'expired'])
def test_retained_origin_cannot_acquire_later_native_context(native, change):
    captured = []
    body = {'art': 'kontakt_original_ergebnis', 'synthetic': True}
    def accept(peer, received, origin, transport):
        captured.append((origin, transport)); return True
    sender, receiver, peer, saved, service = fixture(native, accept)
    channel, envelope, opened = frame(native, service, sender, receiver, body)
    try:
        assert service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] == 200
        origin, transport = captured[0]
        if change == 'peer-key': peer['oeffentlich'] = native.baum_schluessel_erzeugen('Different synthetic peer')['oeffentlich']
        if change == 'own-key': receiver['oeffentlich'] = native.baum_schluessel_erzeugen('Different synthetic own')['oeffentlich']
        if change == 'own-id': receiver['kennung'] = 'other-native-identity'
        if change == 'epoch': receiver['syncEpoch'] = 'new-native-epoch'
        if change == 'off': receiver['an'] = False
        if change == 'unconfirmed': peer['bestaetigt'] = False
        if change == 'stopped': service.anhalten()
        if change == 'expired': opened['ablauf'] = 0  # Own captured session only; never change the OS clock.
        with pytest.raises(PermissionError): origin.require_current(body, transport)
        assert len(saved) == 1
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()


@pytest.mark.parametrize('change', ['content', 'pin', 'stop', 'deny'])
def test_changed_context_inside_actual_callback_prevents_replay_commit_and_ack(native, change):
    body = {'art': 'kontakt_original_ergebnis', 'synthetic': True}
    service = None
    def accept(peer, received, origin, transport):
        origin.require_current(received, transport)
        if change == 'content': received['synthetic'] = 'Retargeted inside callback'
        if change == 'pin': peer['oeffentlich'] = native.baum_schluessel_erzeugen('Changed synthetic peer')['oeffentlich']
        if change == 'stop': service.anhalten()
        return change != 'deny'
    sender, receiver, peer, saved, service = fixture(native, accept)
    channel, envelope, opened = frame(native, service, sender, receiver, body)
    try:
        assert service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] != 200
        assert saved == [] and peer.get('transportIds', []) == []
        assert bytes(opened['sitzung']['kenc']) == b'\0' * 32
        assert bytes(opened['sitzung']['kack']) == b'\0' * 32
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()


def test_draft_full_result_has_no_default_renderer_or_inbox_fallback(native):
    sender, receiver, peer, saved, service = fixture(native, None)
    legacy = []
    service.bei_nachricht = lambda peer, body: legacy.append(body)
    channel, envelope, opened = frame(native, service, sender, receiver, {'art': 'kontakt_original_ergebnis'})
    try:
        assert service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] == 403
        assert legacy == [] and saved == [] and peer.get('transportIds', []) == []
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()


def test_native_result_callback_does_not_replace_the_existing_notes_inbox(native):
    sender, receiver, peer, saved, service = fixture(native,
        lambda *args: pytest.fail('A normal note entered the full-result controller'))
    legacy = []
    service.bei_nachricht = lambda peer, body: legacy.append(body)
    body = {'art': 'notiz', 'synthetic': True}
    channel, envelope, opened = frame(native, service, sender, receiver, body)
    try:
        status, ack = service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')
        assert status == 200 and native.fs_ack_pruefen(channel, envelope, ack)
        assert legacy == [body] and len(saved) == 1
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()
