"""Actual FS1 result -> native pending -> real isolated encrypted book writer.

Mapping setup/export negotiation and durable ACK sending are intentionally not
faked as implemented: this fixture supplies a synthetic native authority guard.
"""
import copy
import hashlib
import json
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace

import pytest

from test_contact_notes_fs_origin import fixture, frame
from test_contact_source_saved_book import data
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_contact_notes_return import NativeNotesPendingResult, NativeNotesExportChoice, notes_content_hash, _frame_bytes
from test_startup_read_failure import native


def prepare_native_book(native):
    before = data()
    original = json.dumps(before, ensure_ascii=False)
    password = 'synthetic-pending-result-only'
    initial, dek, dek_id, wrapper = native.daten_huelle_anlegen(original, password)
    native.speichere_text(initial)
    book = NativeContactSourceBook(); book.set_ready(True)
    replies, snapshots = [], []
    probe = SimpleNamespace(_kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id,
        _daten_umschlag=wrapper, _aktuelle_daten=before, _daten_sperre=threading.RLock(),
        _speicher_auftraege=queue.Queue(), _gesperrt=False, _ladefehler='',
        _operation_laeuft=False, _sync_laeuft=False, _wirklich_beenden=False,
        _kontakt_quellen_buch=book, _journal_snapshot=lambda reason: snapshots.append(reason),
        antwort=lambda callback, value: replies.append((callback, value)))
    for name in ('_vielleicht_verschluesseln', '_kontakt_quellen_buchbindung',
                 '_kontakt_quellen_buchnachweis', '_kontakt_quellen_buchaufnahme'):
        setattr(probe, name, MethodType(getattr(native.Fenster, name), probe))
    book.record_saved(*probe._kontakt_quellen_buchbindung(), original)
    request = {'art': 'kontakt_original_anfrage', 'fassung': 1,
        'request_id': '11111111-1111-4111-8111-111111111111', 'share_id': 'native-canonical-share',
        'before_basis': 'b' * 64, 'target_sha256': 'c' * 64,
        'ziel': {name: '' for name in ('vorname', 'nachname', 'anzeigename', 'firma', 'notiz', 'geburtstag', 'jubilaeum')}}
    request['ziel'].update(vcardName=[], anschriften=[])
    result = {'art': 'kontakt_original_ergebnis', 'fassung': 1,
        **{name: request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')},
        'request_sha256': hashlib.sha256(_frame_bytes(request)).hexdigest(),
        'receipt_id': '22222222-2222-4222-8222-222222222222',
        'native_revision': 2**60 + 1, 'next_basis': 'd' * 64}
    return probe, book, replies, snapshots, request, result


@pytest.mark.parametrize('mode', ['success', 'changed-book', 'later-save', 'revoked-before',
    'revoked-after', 'stop-after', 'repair', 'failed-write', 'duplicate', 'later-save-after', 'owned-request', 'export-selected'])
def test_actual_fs1_pending_result_runs_only_the_exact_saved_book_writer(native, monkeypatch, mode):
    probe, book, replies, snapshots, request, result = prepare_native_book(native)
    live, queued, received, mapping_checks = [True], [], [], []
    def require_mapping():
        mapping_checks.append('native check outside receive callback')
        if not live[0]: raise PermissionError('Synthetic native mapping revoked')
    pending, exports = None, []
    def accept(peer, body, origin, transport):
        if body['art'] == 'kontakt_original_export':
            exports.append((body, origin, transport))
            return True
        checks_before = len(mapping_checks)
        pending.stage_result(body, origin, transport)
        assert len(mapping_checks) == checks_before, 'Receive waited for native book/mapping work'
        received.append((origin, transport))
        queued.append('Schedule outside receive lock')
        return True
    sender, receiver, peer, saved, service = fixture(native, accept)
    if mode == 'export-selected':
        native_before = {'notiz': 'Before native edit', 'telefone': [{'art': 'mobil', 'wert': '+123'}], 'gruppen': ['Native retained']}
        export = {'art': 'kontakt_original_export', 'fassung': 1, 'share_id': 'native-canonical-share',
            'before_basis': 'b' * 64, 'native_revision': 1, 'kontakt': native_before,
            'content_sha256': notes_content_hash(native_before)}
        export_channel, export_frame, _ = frame(native, service, sender, receiver, export, marker=b'E' * 16)
        try:
            status, ack = service.behandeln('/magnolie/v2/nachricht', export_frame, '127.0.0.1')
            assert status == 200 and native.fs_ack_pruefen(export_channel, export_frame, ack)
        finally:
            native.fs_sitzung_loeschen(export_channel)
        body, origin, transport = exports.pop()
        choices = []
        def choose(contacts):
            choices.append(contacts)
            return contacts[0]['id']
        selection = NativeNotesExportChoice(body, origin, transport, probe._kontakt_quellen_buchaufnahme(),
            probe._kontakt_quellen_buchaufnahme, choose)
        pending = selection.pending()
        request = pending.request()
        target = dict(native_before, **request['ziel'])
        assert target['telefone'] == native_before['telefone'] and target['gruppen'] == native_before['gruppen']
        assert request['target_sha256'] == notes_content_hash(target)
        assert len(choices) == 1
        result.update({name: request[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')})
        result['request_sha256'] = hashlib.sha256(_frame_bytes(request)).hexdigest()
    else:
        pending = NativeNotesPendingResult(probe._kontakt_quellen_buchaufnahme(), request, 'local', 'canonical-person',
            (sender['kennung'], sender['oeffentlich']), (receiver['kennung'], receiver['oeffentlich']),
            probe._kontakt_quellen_buchaufnahme, require_mapping)
    if mode == 'owned-request':
        request['ziel']['notiz'] = 'Mutated caller object must not change owned request'
        assert pending.request()['ziel']['notiz'] == ''
    channel, envelope, opened = frame(native, service, sender, receiver, result)
    try:
        status, ack = service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')
        assert status == 200 and native.fs_ack_pruefen(channel, envelope, ack)
        assert queued == ['Schedule outside receive lock'] and not snapshots
        with pytest.raises(PermissionError): pending.confirmed_save()
        original_bytes = Path(native.daten_datei()).read_bytes()
        if mode == 'changed-book': probe._aktuelle_daten['kontakte'][0]['notiz'] = 'Unsaved edit'
        if mode == 'later-save': book.record_saved(*probe._kontakt_quellen_buchbindung(), json.dumps(probe._aktuelle_daten))
        if mode == 'revoked-before': live[0] = False
        if mode in ('changed-book', 'later-save', 'revoked-before'):
            with pytest.raises(PermissionError): pending.prepare_commit()
            assert Path(native.daten_datei()).read_bytes() == original_bytes and not snapshots
            return
        invocation = pending.prepare_commit()
        if mode == 'duplicate':
            origin, transport = received[0]
            pending.stage_result(copy.deepcopy(result), origin, transport)
            assert pending.prepare_commit() is invocation
        monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: mode != 'repair')
        if mode == 'failed-write':
            monkeypatch.setattr(native, 'speichere_text', lambda _: (_ for _ in ()).throw(OSError('Controlled write failure')))
        probe._speicher_auftraege.put((1, invocation.text, None, None, invocation))
        probe._speicher_auftraege.put(None)
        worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(probe,), daemon=True)
        worker.start(); worker.join(timeout=15)
        assert not worker.is_alive()
        assert invocation.done.is_set()
        if mode in ('repair', 'failed-write'):
            with pytest.raises(PermissionError): pending.confirmed_save()
            return
        if mode == 'revoked-after': live[0] = False
        if mode == 'stop-after': service.anhalten()
        if mode == 'later-save-after': book.record_saved(*probe._kontakt_quellen_buchbindung(), invocation.text)
        if mode in ('revoked-after', 'stop-after', 'later-save-after'):
            with pytest.raises(PermissionError): pending.confirmed_save()
            return
        confirmed = pending.confirmed_save()
        current = probe._kontakt_quellen_buchaufnahme()
        assert confirmed['result'] == result
        assert confirmed['saved_book'] == (current.book_source, current.sequence, current.saved_sha256, current.content_sha256)
        stored = json.loads(native.daten_entschluesseln(Path(native.daten_datei()).read_text(), probe._kennwort))
        assert stored == current.book()
        metadata = stored['kontakte'][0].pop('notesOriginalBasis')
        assert metadata['basis'] == result['next_basis'] and metadata['native_revision'] == str(2**60 + 1)
        assert stored == data() and snapshots == ['pre-change']
        assert len(replies) == 1
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()


@pytest.mark.parametrize('field,value', [('request_id', '33333333-3333-4333-8333-333333333333'),
    ('request_sha256', '0' * 64), ('share_id', 'foreign-share'), ('before_basis', '0' * 64),
    ('target_sha256', '0' * 64), ('receipt_id', 'not-native-uuid'), ('native_revision', True),
    ('native_revision', '123'), ('native_revision', 2**63), ('next_basis', 'b' * 64), ('renderer', True)])
def test_actual_authenticated_mismatched_result_cannot_stage_a_book_commit(native, field, value):
    probe, book, replies, snapshots, request, result = prepare_native_book(native)
    pending = None
    def accept(peer, body, origin, transport):
        pending.stage_result(body, origin, transport)
        return True
    sender, receiver, peer, saved, service = fixture(native, accept)
    pending = NativeNotesPendingResult(probe._kontakt_quellen_buchaufnahme(), request, 'local', 'canonical-person',
        (sender['kennung'], sender['oeffentlich']), (receiver['kennung'], receiver['oeffentlich']),
        probe._kontakt_quellen_buchaufnahme, lambda: None)
    body = dict(result, **{field: value})
    channel, envelope, opened = frame(native, service, sender, receiver, body)
    try:
        assert service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] != 200
        with pytest.raises(PermissionError): pending.prepare_commit()
        assert saved == [] and snapshots == [] and replies == []
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()


@pytest.mark.parametrize('mode', ['cancel', 'unknown-id', 'changed-during-choice', 'copied-origin',
    'wrong-content', 'revoked-export', 'stale-result-revision'])
def test_native_export_selection_never_uses_portable_tags_as_mapping_authority(native, mode):
    probe, book, replies, snapshots, request, result = prepare_native_book(native)
    captured = []
    def accept(peer, body, origin, transport):
        captured.append((body, origin, transport)); return True
    sender, receiver, peer, saved, service = fixture(native, accept)
    contact = {'notiz': 'Native before'}
    body = {'art': 'kontakt_original_export', 'fassung': 1, 'share_id': 'native-canonical-share',
        'before_basis': 'b' * 64, 'native_revision': 12, 'kontakt': contact,
        'content_sha256': notes_content_hash(contact)}
    if mode == 'wrong-content': body['content_sha256'] = '0' * 64
    channel, envelope, opened = frame(native, service, sender, receiver, body)
    try:
        assert service.behandeln('/magnolie/v2/nachricht', envelope, '127.0.0.1')[0] == 200
        body, origin, transport = captured.pop()
        snapshot = probe._kontakt_quellen_buchaufnahme()
        choices = []
        def choose(contacts):
            choices.append(contacts)
            if mode == 'cancel': return None
            if mode == 'unknown-id': return 'imported-share-is-not-a-contact-id'
            if mode == 'changed-during-choice':
                book.record_saved(*probe._kontakt_quellen_buchbindung(), json.dumps(probe._aktuelle_daten))
            return 'local'
        if mode in ('cancel', 'unknown-id', 'changed-during-choice', 'copied-origin', 'wrong-content'):
            with pytest.raises((PermissionError, ValueError)):
                NativeNotesExportChoice(body, body if mode == 'copied-origin' else origin, transport,
                    snapshot, probe._kontakt_quellen_buchaufnahme, choose)
            if mode in ('copied-origin', 'wrong-content'): assert not choices
        else:
            selection = NativeNotesExportChoice(body, origin, transport, snapshot, probe._kontakt_quellen_buchaufnahme, choose)
            if mode == 'revoked-export':
                service.anhalten()
                with pytest.raises(PermissionError): selection.pending()
            else:
                pending = selection.pending(); owned = pending.request()
                result.update({name: owned[name] for name in ('request_id', 'share_id', 'before_basis', 'target_sha256')})
                result.update(request_sha256=hashlib.sha256(_frame_bytes(owned)).hexdigest(), native_revision=12)
                service.bei_sicherer_nachricht = lambda peer, body, origin, tid: pending.stage_result(body, origin, tid)
                second, second_frame, _ = frame(native, service, sender, receiver, result, marker=b'V' * 16)
                try:
                    assert service.behandeln('/magnolie/v2/nachricht', second_frame, '127.0.0.1')[0] != 200
                    with pytest.raises(PermissionError): pending.prepare_commit()
                finally:
                    native.fs_sitzung_loeschen(second)
        assert not snapshots and not replies
    finally:
        native.fs_sitzung_loeschen(channel); service.anhalten()
