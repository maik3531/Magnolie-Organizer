"""Native update command through real DAV, journal, result offer and writer.

Network/WLAN observations are controlled; no installed frontend acceptance.
"""
import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_startup_read_failure import native, Host
from test_contact_source_dav_factory import account, Source
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_contact_source_dav import NativeDavApprovalScope
import magnolie_nextcloud as nc


@pytest.mark.parametrize('mode', ['success', 'no-grants', 'wrong-hash', 'no-wlan', 'lost-wlan',
    'changed-book', 'revoke-during-protection', 'unknown-write', 'manual-sync-fence', 'later-save-offer'])
def test_actual_native_update_command_has_wlan_book_and_phone_manual_fences(native, tmp_path, monkeypatch, mode):
    host, source, store = Host(native), Source(native), account(tmp_path)
    host._gesperrt = False
    host._wirklich_beenden = False
    host._daten_dek_kennung = None
    remote = native.vcf_lesen(source.wire)['kontakte'][0]
    contact = dict(copy.deepcopy(remote), id='local', uid='canonical-person', sync=True)
    key = nc.source_id('addressbook', source.href, 'generic-dav')
    native._dav_syncquelle_setzen(contact, key, source.resource, source.etag, baseline=remote)
    contact['notiz'] = 'Canonical note'
    host._aktuelle_daten = {'version': 7, 'syncEpoch': 'synthetic-native-epoch',
                           'kontakte': [contact], 'notizen': [{'id': 'preserved', 'text': 'Other domain'}]}
    original_text = json.dumps(host._aktuelle_daten)
    native.speichere_text(original_text)
    host._kontakt_quellen_buch = NativeContactSourceBook(); host._kontakt_quellen_buch.set_ready(True)
    host._kontakt_quellen_buch.record_saved(*host._kontakt_quellen_buchbindung(), original_text)
    snapshot = host._kontakt_quellen_buchaufnahme()
    actual_client = store.checked_client
    native_requests = []
    def provider_transport(*args):
        assert host._telefon_actor_buchbindung()[1] is False, 'Phone actor allowed during original-source operation'
        assert host._kontakt_quellen_buchaufnahme() is not None or mode == 'changed-book'
        native_requests.append(args[0])
        return source.transport(*args)
    monkeypatch.setattr(store, 'checked_client', lambda revision, purpose='dav', transport=None:
                        actual_client(revision, purpose=purpose, transport=provider_transport))
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: store)
    scope = host._kontakt_quellen_freigaben = NativeDavApprovalScope(host._kontakt_quellen_buchnachweis, store)
    catalog = [{'uid': key, 'href': source.href, 'art': 'addressbook', 'canUpdate': True, 'name': 'Synthetic original'}]
    if mode != 'no-grants': scope.configure(catalog, lambda choices, selected: [key])
    wlan = [mode != 'no-wlan']
    monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', lambda: wlan[0])
    protect = host._kontakt_quellen_schutz
    def guarded_protect(original):
        identity = protect(original)
        if mode == 'lost-wlan': wlan[0] = False
        if mode == 'revoke-during-protection': host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen'}))
        return identity
    host._kontakt_quellen_schutz = guarded_protect
    if mode == 'changed-book': source.before_report = lambda: host._aktuelle_daten.update(unsavedEdit=True)
    if mode == 'manual-sync-fence': source.before_report = lambda: host.bei_nachricht(json.dumps({'cmd': 'sync_start', 'mcp': True, 'requestId': 'must-not-run'}))
    if mode == 'unknown-write': source.mode = 'write-failed'
    threads = []
    real_thread = threading.Thread
    def make_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs); threads.append(thread); return thread
    monkeypatch.setattr(native, 'threading', SimpleNamespace(Thread=make_thread))
    host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_update', 'requestId': 'update-probe',
        'standSha256': '0' * 64 if mode == 'wrong-hash' else snapshot.saved_sha256,
        'sources': ['forged'], 'saved': True, 'wlan': True}))
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive(), 'Actual native source worker did not finish bounded run'
    response, = [value for callback, value in host.responses if callback == 'App.originalKontaktErgebnis']
    assert not getattr(host, '_kontakt_quellen_update_aktiv', False)
    assert host._sync_laeuft is False and host._telefon_actor_buchbindung()[1] is True
    successful = mode in ('success', 'manual-sync-fence', 'later-save-offer')
    assert source.writes == int(successful)
    assert Path(native.daten_datei()).read_text() == original_text, 'Native offer prematurely saved the local book'
    if mode == 'manual-sync-fence':
        assert any(callback == 'App.syncMcpFehler' and value['code'] == 'native_busy' for callback, value in host.responses)
    if successful:
        assert response['ok'] and response['token'] and response['kontakte'][0]['uid'] == 'canonical-person'
        proposal = copy.deepcopy(host._aktuelle_daten); proposal['kontakte'] = response['kontakte']
        assert proposal['kontakte'][0]['syncQuellen'][key]['etag'] == '"v2"'
        protection, = native.journal_liste()
        assert native.journal_snapshot_lesen(protection['snapshotId'])[1]['daten'] == snapshot.book()
        if mode == 'later-save-offer':
            host._kontakt_quellen_buch.record_saved(*host._kontakt_quellen_buchbindung(), original_text)
        host.bei_nachricht(json.dumps({'cmd': 'speichern', 'id': 71, 'text': json.dumps(proposal),
                                      'kontaktOriginalLauf': response['token']}))
        if mode == 'later-save-offer':
            assert host.responses[-1][1]['ok'] is False and host._speicher_auftraege.empty()
        else:
            monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **_: True)
            host._journal_snapshot = lambda _: None
            host._speicher_auftraege.put(None)
            native.Fenster._speicher_lauf(host)
            assert host.responses[-1][1]['ok'] is True
            assert host._kontakt_quellen_buchaufnahme().book() == proposal
    else:
        assert not response.get('token') and host._speicher_auftraege.empty()
        if mode in ('no-wlan', 'wrong-hash', 'no-grants'): assert not native_requests
