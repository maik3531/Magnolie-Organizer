"""Explicit Linux acquisition against the real FS1 receiver; no server/GTK."""
import copy
from pathlib import Path
import json

import pytest

from test_contact_notes_consent import Harness, native
from test_contact_notes_controller import Runtime
from magnolie_contact_notes_return import NativeNotesProtocolNegotiation
from magnolie_contact_notes_setup import NativeNotesSetupCollector, NativeNotesSetupCandidate
from magnolie_contact_notes_requests import NativeNotesRequestIntents


@pytest.mark.parametrize('mode', ['native-choice', 'cancel', 'expired', 'missing-offer', 'foreign-challenge', 'invalid-offer',
    'conflict', 'duplicate', 'budget', 'coexist-worker', 'service-stop', 'occupied-slot', 'choice-cancel', 'native-save',
    'stop-during-choice', 'export-before-offer', 'forged-candidate', 'only-setup', 'guard-after-consent'])
def test_explicit_native_setup_acquisition_does_not_replace_worker_or_grant_sources(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    now = [0]
    protocol = NativeNotesProtocolNegotiation((h.sender['kennung'], h.sender['oeffentlich']),
        (h.receiver['kennung'], h.receiver['oeffentlich']))
    collector = NativeNotesSetupCollector(h.service, protocol, clock=lambda: now[0], budget=2)
    original = h.service.bei_sicherer_nachricht
    runtime = None
    try:
        if mode == 'only-setup': h.service.bei_sicherer_nachricht = original = None
        collector.attach()
        if mode == 'coexist-worker':
            h.configure(); runtime = Runtime(h); original = h.service.bei_sicherer_nachricht
            runtime.negotiate()  # Its challenge must not be swallowed by acquisition.
        if mode == 'export-before-offer':
            h.send(h.export)
            assert not collector._changed.is_set()
        if mode != 'missing-offer':
            offer = dict(protocol.request(), antwort=mode != 'invalid-offer')
            if mode == 'foreign-challenge': offer['challenge'] = '11111111-1111-4111-8111-111111111111'
            h.send(offer)
        h.send(h.export)
        if mode == 'cancel': collector.stop()
        if mode == 'expired': now[0] = 120
        if mode == 'service-stop': h.service.anhalten()
        if mode in ('cancel', 'expired', 'service-stop', 'missing-offer', 'foreign-challenge', 'invalid-offer'):
            with pytest.raises(PermissionError): collector.candidates()
            return
        candidate, = collector.wait()
        if mode == 'occupied-slot':
            other = NativeNotesSetupCollector(h.service, NativeNotesProtocolNegotiation(*collector._pins))
            with pytest.raises(PermissionError): other.attach()
            other.stop()
            assert len(collector.candidates()) == 1
        if mode == 'forged-candidate':
            with pytest.raises(PermissionError): NativeNotesSetupCandidate({}).display()
            return
        if mode == 'conflict':
            h.send(dict(h.export, native_revision=2))
            assert not collector.candidates()
            with pytest.raises(PermissionError): candidate.display()
            return
        if mode == 'duplicate':
            for _ in range(30): h.send(h.export)
            with pytest.raises(PermissionError): candidate.display()
            candidate, = collector.candidates()
        if mode == 'budget':
            for index in range(10): h.send(dict(h.export, share_id='bounded-share-' + str(index)))
            assert len(collector.candidates()) == 2
        if mode == 'coexist-worker':
            assert runtime.controller.process_one().kind == 'request' and len(runtime.controller._owners) == 1
            collector.stop()
            assert h.service.bei_sicherer_nachricht == original and len(runtime.controller._owners) == 1
            return
        displayed = candidate.display(); displayed['setup_id'] = 'not-a-grant'
        assert candidate.display()['setup_id'] != 'not-a-grant'
        snapshot = h.probe._kontakt_quellen_buchaufnahme()
        if mode == 'choice-cancel':
            with pytest.raises(PermissionError): candidate.choose(snapshot, h.probe._kontakt_quellen_buchaufnahme, lambda _: None)
            return
        def choose(contacts):
            if mode == 'stop-during-choice': collector.stop()
            if mode == 'native-save':
                edit = copy.deepcopy(h.probe._aktuelle_daten); edit['during-choice'] = 'preserve'
                assert h.save(monkeypatch, edit)['ok']
            return contacts[0]['id']
        if mode in ('native-save', 'stop-during-choice'):
            with pytest.raises(PermissionError): candidate.choose(snapshot, h.probe._kontakt_quellen_buchaufnahme, choose)
            return
        choice = candidate.choose(snapshot, h.probe._kontakt_quellen_buchaufnahme, choose)
        assert not h.store.has_desired_consent()
        requests = NativeNotesRequestIntents(tmp_path / 'ungranted-requests', lambda: b'J' * 32)
        with pytest.raises(PermissionError): requests.seal(choice.pending())
        assert not (tmp_path / 'ungranted-requests').exists()
        if mode == 'guard-after-consent':
            with h.probe._daten_sperre:
                decision = h.store.begin_setup_decision(); decision.commit(choice)
            assert h.store.has_desired_consent()
        collector.stop()
        with pytest.raises(PermissionError): choice.require_current()
        if mode == 'guard-after-consent':
            # Closing acquisition invalidates its ephemeral objects, not the
            # genuine durable source. Only a fresh real export may restore it.
            observed = h.observed()
            with h.probe._daten_sperre: restored = h.store.restore(*observed)
            assert restored.pending() is not None
    finally:
        collector.stop()
        assert h.service.bei_sicherer_nachricht == original
        if mode not in ('coexist-worker', 'guard-after-consent'): assert not h.store.has_desired_consent()
        h.service.anhalten()


def test_setup_slot_never_receives_result_or_terminal_even_if_its_callback_would_accept(native, monkeypatch, tmp_path):
    h = Harness(native, tmp_path)
    collector = NativeNotesSetupCollector(h.service, NativeNotesProtocolNegotiation(
        (h.sender['kennung'], h.sender['oeffentlich']), (h.receiver['kennung'], h.receiver['oeffentlich'])))
    seen = []
    monkeypatch.setattr(collector, 'receive', lambda *args: seen.append(args) or True)
    collector.attach()
    try:
        h.send({'art': 'kontakt_original_ergebnis', 'synthetic': True})
        h.send({'art': 'kontakt_original_abschlussstatus', 'synthetic': True})
        assert not seen
    finally:
        collector.stop(); h.service.anhalten()


def test_setup_helper_is_in_existing_linux_manifests_without_enabling_a_factory():
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
            'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_notes_setup.py' in (root / name).read_text()
    json.loads((root / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())
