"""One-use contact proposal through the actual encrypted/atomic Linux writer."""
import copy
import hashlib
import json
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace

import pytest

from test_contact_source_saved_book import data
from magnolie_contact_source_book import (NativeContactSourceBook, NativeContactSourceResultCommit,
    NativeContactSourceSavedWitness)
from test_startup_read_failure import native


@pytest.mark.parametrize('mode', ['serialized-order', 'unknown-token', 'no-offer', 'other-domain',
    'changed-uid', 'changed-contact', 'later-save-before', 'later-save-after', 'revoke-before',
    'session-after', 'mixed-proof', 'reused-offer'])
def test_actual_bridge_only_claims_an_exact_native_offer_for_the_existing_writer(native, monkeypatch, mode):
    from test_startup_read_failure import Host
    host = Host(native)
    host._gesperrt = False
    host._aktuelle_daten = data()
    host._wirklich_beenden = False
    host._daten_dek_kennung = None
    host._kontakt_quellen_buch = NativeContactSourceBook()
    host._kontakt_quellen_buch.set_ready(True)
    host._journal_snapshot = lambda _: None
    original = json.dumps(host._aktuelle_daten)
    native.speichere_text(original)
    host._kontakt_quellen_buch.record_saved(*host._kontakt_quellen_buchbindung(), original)
    snapshot = host._kontakt_quellen_buchaufnahme()
    proposed = copy.deepcopy(host._aktuelle_daten)
    proposed['kontakte'][0]['notiz'] = 'Verified native proposed result'
    live = [True]
    def require_session():
        if not live[0]: raise PermissionError('Controlled revoked native session')
    offered = host._kontakt_quellen_ergebnis_anbieten(snapshot, proposed, require_session)
    # Actual frontend JSON serialization need not share Python key order/spacing.
    payload = dict(reversed(list(proposed.items())))
    if mode == 'other-domain': payload['notizen'] = []
    if mode == 'changed-uid': payload['kontakte'][0]['uid'] = 'replacement'
    if mode == 'changed-contact': payload['kontakte'][0]['notiz'] = 'Unapproved renderer replacement'
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if mode == 'later-save-before': host._kontakt_quellen_buch.record_saved(*host._kontakt_quellen_buchbindung(), original)
    if mode == 'revoke-before': host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen'}))
    if mode == 'no-offer': host._kontakt_quellen_commit_angebot = None
    message = {'cmd': 'speichern', 'id': 31, 'text': serialized,
               'kontaktOriginalLauf': '0' * 64 if mode == 'unknown-token' else offered['token']}
    if mode == 'mixed-proof': message['baumSyncLauf'] = {'forged': True}
    host.bei_nachricht(json.dumps(message))
    queued = mode in ('serialized-order', 'later-save-after', 'session-after', 'reused-offer')
    assert host._speicher_auftraege.qsize() == int(queued)
    if mode == 'later-save-after': host._kontakt_quellen_buch.record_saved(*host._kontakt_quellen_buchbindung(), original)
    if mode == 'session-after': live[0] = False
    if mode == 'reused-offer':
        host.bei_nachricht(json.dumps(dict(message, id=32)))
        assert host._speicher_auftraege.qsize() == 1
        assert host.responses[-1][1]['ok'] is False
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
    host._speicher_auftraege.put(None)
    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(host,), daemon=True)
    worker.start(); worker.join(timeout=15)
    assert not worker.is_alive()
    responses = [value for callback, value in host.responses if callback == 'App.gespeichert' and value['id'] == 31]
    response, = responses
    assert response['ok'] is (mode in ('serialized-order', 'reused-offer'))
    if response['ok']:
        assert not response['repairPending']
        assert Path(native.daten_datei()).read_text() == serialized
        assert response['standSha256'] == hashlib.sha256(serialized.encode()).hexdigest()
        assert host._kontakt_quellen_buchaufnahme().book() == proposed
    else:
        assert Path(native.daten_datei()).read_text() == original


@pytest.mark.parametrize('mode', ['plain', 'encrypted', 'changed-book', 'later-save', 'revoked',
    'wrong-payload', 'impostor', 'mixed-proof', 'mixed-historical', 'failure-before-write',
    'failure-after-unknown', 'repair-after-rename', 'reminder-repair', 'reuse', 'wire-encrypted'])
def test_exact_one_use_contact_commit_runs_actual_native_writer(native, monkeypatch, tmp_path, mode):
    before = data()
    before['version'] = 7
    source = None
    if mode == 'wire-encrypted':
        from test_contact_source_dav_factory import Source
        import magnolie_nextcloud as nc
        source = Source(native)
        key = nc.source_id('addressbook', source.href, 'generic-dav')
        contact = native.vcf_lesen(source.wire)['kontakte'][0]
        contact.update(id='local', uid='canonical-person', sync=True)
        native._dav_syncquelle_setzen(contact, key, source.resource, source.etag,
                                     baseline=native.vcf_lesen(source.wire)['kontakte'][0])
        contact['notiz'] = 'Canonical note'
        before['kontakte'] = [contact]
    proposed = copy.deepcopy(before)
    proposed['kontakte'][0]['notiz'] = 'Verified original-source result'
    before_text = json.dumps(before, ensure_ascii=False)
    password = 'Synthetic-only-618-result' if mode in ('encrypted', 'wire-encrypted') else ''
    initial, dek, dek_id, wrapper = native.daten_huelle_anlegen(before_text, password) if password else (before_text, None, None, None)
    native.speichere_text(initial)
    path = Path(native.daten_datei())
    original_bytes = path.read_bytes()
    book = NativeContactSourceBook(); book.set_ready(True)
    replies, snapshots, writes = [], [], []
    probe = SimpleNamespace(_kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id,
        _daten_umschlag=wrapper, _aktuelle_daten=before, _daten_sperre=threading.RLock(),
        _speicher_auftraege=queue.Queue(), _gesperrt=False, _ladefehler='',
        _operation_laeuft=False, _sync_laeuft=False, _wirklich_beenden=False,
        _kontakt_quellen_buch=book, _journal_snapshot=lambda reason: snapshots.append(reason),
        antwort=lambda callback, value: replies.append((callback, value)))
    for name in ('_vielleicht_verschluesseln', '_kontakt_quellen_buchbindung',
                 '_kontakt_quellen_buchnachweis', '_kontakt_quellen_buchaufnahme', '_kontakt_quellen_schutz'):
        setattr(probe, name, MethodType(getattr(native.Fenster, name), probe))
    original_state = book.record_saved(*probe._kontakt_quellen_buchbindung(), before_text)
    snapshot = probe._kontakt_quellen_buchaufnahme()
    if source is not None:
        from test_contact_source_dav_factory import account
        from magnolie_contact_source_dav import NativeDavApprovalScope, NativeBoundDavFactory
        store = account(tmp_path)
        scope = NativeDavApprovalScope(probe._kontakt_quellen_buchnachweis, store)
        catalog = nc.NextcloudDav(store.checked_client(store.read_snapshot()[2], transport=source.transport)).collections('addressbook')
        scope.configure(catalog, lambda choices, selected: [key])
        def build(approval, hrefs, guard):
            return NativeBoundDavFactory(store, approval, hrefs, guard,
                lambda: probe._kontakt_quellen_schutz(snapshot), native.kontakt_original_vcard_beobachtung,
                transport=source.transport)
        run = native.kontakt_quellen_updates_vorbereiten(snapshot,
            probe._kontakt_quellen_buchaufnahme, scope.capture(), build)
        proposed = run['book']
        assert source.writes == 1 and proposed['kontakte'][0]['syncQuellen'][key]['etag'] == '"v2"'
        assert probe._aktuelle_daten['kontakte'][0]['syncQuellen'][key]['etag'] == '"v1"'
        protection, = native.journal_liste()
        _, recovered = native.journal_snapshot_lesen(protection['snapshotId'], password)
        assert recovered['daten'] == before
    live = [True]
    def require_session():
        if not live[0]: raise PermissionError('Controlled revoked native run')
    token = (native.Fenster._kontakt_quellen_ergebnis_speichern(probe, snapshot, proposed, require_session)
             if source is not None else NativeContactSourceResultCommit(
                 snapshot, proposed, probe._kontakt_quellen_buchaufnahme, require_session))
    text = token.text
    assert token.result is None and not token.done.is_set()
    with pytest.raises(PermissionError): token.saved_witness()
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: mode != 'reminder-repair')
    actual_write = native.speichere_text
    def checked_write(payload):
        assert probe._kontakt_quellen_buchaufnahme() is None
        writes.append(payload)
        if mode == 'failure-before-write': raise OSError('Controlled pre-write failure')
        actual_write(payload)
        if mode in ('failure-after-unknown', 'repair-after-rename'): raise OSError('Controlled post-rename failure')
    monkeypatch.setattr(native, 'speichere_text', checked_write)
    if mode == 'failure-after-unknown':
        monkeypatch.setattr(native, '_erinnerungsprofil_lesen', lambda: (_ for _ in ()).throw(OSError('Controlled unknown readback')))
    if mode == 'changed-book': before['unsavedNativeEdit'] = True
    if mode == 'later-save': book.record_saved(*probe._kontakt_quellen_buchbindung(), before_text)
    if mode == 'revoked': live[0] = False
    if mode == 'wrong-payload': text = json.dumps(proposed, indent=2)
    invocation = {'saved': True} if mode == 'impostor' else token
    proof = {'renderer': 'not-a-proof'} if mode == 'mixed-proof' else None
    historical = {} if mode == 'mixed-historical' else None
    if source is None:
        probe._speicher_auftraege.put((1, text, proof, historical, invocation))
    if mode == 'reuse': probe._speicher_auftraege.put((2, text, None, None, token))
    probe._speicher_auftraege.put(None)
    worker = threading.Thread(target=native.Fenster._speicher_lauf, args=(probe,), daemon=True)
    worker.start(); worker.join(timeout=15)
    assert not worker.is_alive(), 'Actual writer failed bounded shutdown'
    responses = [value for callback, value in replies if callback == 'App.gespeichert']
    response = responses[0]
    successful = mode in ('plain', 'encrypted', 'reuse', 'wire-encrypted')
    if successful:
        assert response['ok'] and response['committed'] and not response['repairPending']
        assert token.done.is_set() and token.result == {'confirmed': True, 'committed': True, 'repairPending': False}
        current = probe._kontakt_quellen_buchaufnahme()
        assert current.sequence == original_state['sequence'] + 1 and current.book() == proposed
        assert current.saved_sha256 == hashlib.sha256(token.text.encode()).hexdigest()
        assert len(writes) == 1
        witness = token.saved_witness()
        assert witness.require_current() == (current.book_source, current.sequence,
            current.saved_sha256, current.content_sha256)
        assert token.saved_witness() is witness
        with pytest.raises(PermissionError): NativeContactSourceSavedWitness(token).require_current()
        if mode == 'reuse': assert responses[1]['ok'] is False and token.result['confirmed'] is True
    elif mode in ('repair-after-rename', 'reminder-repair'):
        assert response['ok'] and response['committed'] and response['repairPending']
        assert token.done.is_set() and token.result == {'confirmed': False, 'committed': True, 'repairPending': True}
        assert probe._kontakt_quellen_buchaufnahme() is None
    else:
        assert response['ok'] is False
        if mode != 'impostor': assert token.done.is_set() and token.result['confirmed'] is False
        if mode not in ('failure-before-write', 'failure-after-unknown'):
            assert not writes and not snapshots and path.read_bytes() == original_bytes
    if writes and mode != 'failure-before-write':
        stored = native.daten_entschluesseln(path.read_text(), password) if password else path.read_text()
        assert stored == token.text
    if mode != 'impostor':
        with pytest.raises(PermissionError): token.write(token.text, lambda _: pytest.fail('Consumed result wrote again'))
    if not successful:
        with pytest.raises(PermissionError): token.saved_witness()


@pytest.mark.parametrize('mode', ['other-domain', 'removed-contact', 'changed-uid', 'changed-id', 'forged-snapshot'])
def test_native_contact_result_cannot_replace_other_domains_or_identities(native, monkeypatch, mode):
    book = NativeContactSourceBook(); book.set_ready(True)
    before = data()
    book.record_saved('synthetic-native-result', True, json.dumps(before))
    snapshot = book.capture('synthetic-native-result', True, before)
    proposed = copy.deepcopy(before)
    if mode == 'other-domain': proposed['notizen'] = []
    if mode == 'removed-contact': proposed['kontakte'] = []
    if mode == 'changed-uid': proposed['kontakte'][0]['uid'] = 'replacement'
    if mode == 'changed-id': proposed['kontakte'][0]['id'] = 'replacement'
    if mode == 'forged-snapshot':
        from dataclasses import replace
        snapshot = replace(snapshot, text=snapshot.text + ' ')
    with pytest.raises(ValueError):
        NativeContactSourceResultCommit(snapshot, proposed,
            lambda: book.capture('synthetic-native-result', True, before), lambda: None)


@pytest.mark.parametrize('change', ['unsaved', 'later-save', 'locked', 'session', 'during-capture'])
def test_confirmed_native_witness_rechecks_the_exact_saved_generation_and_live_session(change):
    book = NativeContactSourceBook(); book.set_ready(True)
    current = [data()]; live = [True]; callback = [None]
    book.record_saved('native-book', True, json.dumps(current[0]))
    def capture():
        result = book.capture('native-book', True, current[0])
        if callback[0] is not None: callback[0]()
        return result
    def guard():
        if not live[0]: raise PermissionError('Controlled revoked sender')
    proposal = copy.deepcopy(current[0]); proposal['kontakte'][0]['notiz'] = 'Native saved result'
    token = NativeContactSourceResultCommit(capture(), proposal, capture, guard)
    def writer(payload):
        current[0] = json.loads(payload); book.record_saved('native-book', True, payload)
    token.write(token.text, writer)
    token.complete({'ok': True, 'committed': True, 'repairPending': False,
                    'standSha256': hashlib.sha256(token.text.encode()).hexdigest()})
    witness = token.saved_witness(); witness.require_current()
    if change == 'unsaved': current[0]['kontakte'][0]['notiz'] = 'Later edit'
    if change == 'later-save': book.record_saved('native-book', True, token.text)
    if change == 'locked': book.set_ready(False)
    if change == 'session': live[0] = False
    if change == 'during-capture': callback[0] = lambda: live.__setitem__(0, False)
    with pytest.raises(PermissionError): witness.require_current()
    with pytest.raises(PermissionError): token.saved_witness()


def test_json_results_or_impostor_owners_cannot_issue_a_native_saved_witness():
    class Impostor:
        def _require_saved_witness(self, _): pytest.fail('An impostor may not attest itself')
    for owner in ({'confirmed': True}, Impostor(), None):
        with pytest.raises(PermissionError): NativeContactSourceSavedWitness(owner).require_current()
