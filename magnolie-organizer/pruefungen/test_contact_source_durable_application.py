"""Actual bridge/serial writer/native durable setup with synthetic account/UI.

Encrypted files are private fixtures; no live provider, keyring or installed UI.
"""
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from test_startup_read_failure import native, Host
from test_contact_source_dav_factory import account, Source
from test_contact_source_saved_book import data
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_nextcloud import NextcloudError


@pytest.fixture
def application(native, tmp_path, monkeypatch):
    accounts, source = account(tmp_path), Source(native)
    actual_checked = accounts.checked_client
    monkeypatch.setattr(accounts, 'checked_client', lambda revision, purpose='dav', transport=None, **kw:
        actual_checked(revision, purpose=purpose, transport=source.transport, **kw))
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: accounts)
    monkeypatch.setattr(native, 'erinnerungsdaten_schreiben', lambda **kw: True)
    idles, threads, decisions = [], [], []
    monkeypatch.setattr(native, 'GLib', SimpleNamespace(idle_add=lambda cb, *args: idles.append((cb, args))))
    actual_thread = threading.Thread
    def worker(*args, **kwargs):
        thread = actual_thread(*args, **kwargs); threads.append(thread); return thread
    monkeypatch.setattr(native, 'threading', SimpleNamespace(Thread=worker))
    def drain():
        while True:
            for thread in list(threads):
                thread.join(timeout=15); assert not thread.is_alive()
            if not idles and all(not thread.is_alive() for thread in threads): break
            pending = list(idles); idles.clear()
            for cb, args in pending: cb(*args)
    initial = data()
    password = 'synthetic-only-durable-application'
    envelope, _, _, _ = native.daten_huelle_anlegen(json.dumps(initial), password)
    native.speichere_text(envelope)
    def start():
        host = Host(native); host._gesperrt = False; host._wirklich_beenden = False
        text, host._daten_dek, host._daten_dek_kennung, host._daten_umschlag = native.daten_entschluesseln(
            Path(native.daten_datei()).read_text(), password, mit_schluessel=True)
        host._kennwort = password; host._aktuelle_daten = json.loads(text)
        host._kontakt_quellen_buch = NativeContactSourceBook(); host._kontakt_quellen_buch.set_ready(True)
        host._kontakt_quellen_dauerstore()  # Same native construction as the window constructor.
        return host
    def save(host, changes=None):
        proposed = dict(host._aktuelle_daten, **(changes or {}))
        host.responses.clear()
        host.bei_nachricht(json.dumps({'cmd': 'speichern', 'id': 51, 'text': json.dumps(proposed)}))
        host._speicher_auftraege.put(None)
        worker(target=host._speicher_lauf, daemon=True).start(); drain()
        return next(value for cb, value in host.responses if cb == 'App.gespeichert')
    def setup(host, answer='allow'):
        def choose(parent, choices, selected):
            decisions.append((tuple(row['uid'] for row in choices), selected))
            return None if answer == 'cancel' else () if answer == 'empty' else [choices[0]['uid']]
        monkeypatch.setattr(native, 'kontakt_quellen_freigabe_dialog', choose)
        host.responses.clear()
        host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_freigabe', 'requestId': 'native-setup'}))
        drain()
        return next(value for cb, value in reversed(host.responses) if cb == 'App.originalKontaktFreigabe')
    yield SimpleNamespace(native=native, accounts=accounts, source=source, start=start, save=save, setup=setup,
        drain=drain, worker=worker, decisions=decisions, monkeypatch=monkeypatch)
    drain()


def test_default_construction_and_save_touch_no_credentials_or_primary_and_create_no_authority(application):
    app = application; host = app.start()
    def forbidden(*args, **kw): pytest.fail('Disabled durable feature observed primary or credentials')
    app.monkeypatch.setattr(app.accounts, 'read_snapshot', forbidden)
    host._kontakt_quellen_hauptdatei_aufnahme = forbidden
    reply = app.save(host)
    assert reply['ok'] and not reply.get('kontaktQuellenDauerhaft')
    assert not Path(host._kontakt_quellen_dauerfreigabe.root).exists()
    assert app.source.records == []


def test_once_approved_restart_first_real_save_advances_and_restores_without_new_dialog(application):
    app = application; host = app.start()
    app.save(host)
    assert app.setup(host)['freigaben'] == 1
    original = host._kontakt_quellen_dauerfreigabe.load_current()
    after = app.start()
    assert after._kontakt_quellen_buchaufnahme() is None
    assert not hasattr(after, '_kontakt_quellen_freigaben')
    reply = app.save(after, {'ordinaryNormalizedField': {'number': 1.25}})
    assert reply['ok'] and reply['kontaktQuellenDauerhaft'] is True
    callbacks = [cb for cb, _ in after.responses]
    assert callbacks.index('App.gespeichert') < callbacks.index('App.originalKontaktDauerfreigabe')
    notice = next(value for cb, value in after.responses if cb == 'App.originalKontaktDauerfreigabe')
    assert notice == {'id': 51, 'standSha256': reply['standSha256'], 'ok': True, 'freigaben': 1}
    current = after._kontakt_quellen_dauerfreigabe.load_current()
    assert current.generation == original.generation and current.sources == original.sources
    assert current.snapshot.book()['ordinaryNormalizedField']['number'] == 1.25
    assert len(after._kontakt_quellen_freigaben.capture()) == 1 and len(app.decisions) == 1
    assert app.source.writes == 0


@pytest.mark.parametrize('durable', [False, True])
def test_bridge_distinguishes_volatile_pause_from_durable_revocation_across_restart(application, durable):
    app = application; host = app.start(); app.save(host); app.setup(host)
    root = Path(host._kontakt_quellen_dauerfreigabe.root); old_key = (root / '.key').read_bytes()
    host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen', 'dauerhaft': durable}))
    app.drain()
    assert host._kontakt_quellen_freigaben.capture() == ()
    assert ((root / '.key').read_bytes() != old_key) is durable
    after = app.start(); reply = app.save(after, {'laterOrdinaryEdit': True})
    assert bool(reply.get('kontaktQuellenDauerhaft')) is not durable
    if not durable: assert len(after._kontakt_quellen_freigaben.capture()) == 1
    else: assert not hasattr(after, '_kontakt_quellen_freigaben')
    assert len(app.decisions) == 1


@pytest.mark.parametrize('answer', ['cancel', 'empty'])
def test_native_reconfiguration_cancel_preserves_intent_empty_selection_rotates_and_revokes(application, answer):
    app = application; host = app.start(); app.save(host); app.setup(host)
    root = Path(host._kontakt_quellen_dauerfreigabe.root); old_key = (root / '.key').read_bytes()
    reply = app.setup(host, answer)
    assert reply['ok'] and reply['changed'] is (answer == 'empty')
    assert reply['freigaben'] == (1 if answer == 'cancel' else 0)
    assert ((root / '.key').read_bytes() != old_key) is (answer == 'empty')


def test_keyring_lock_keeps_verified_desired_intent_and_monitor_restores_same_saveack_quietly(application):
    app = application; host = app.start(); app.save(host); app.setup(host)
    after = app.start()
    def locked(*args): raise NextcloudError('Controlled locked account', 'secret_service_locked')
    actual_lookup = app.accounts.secrets.lookup_noninteractive
    app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', locked)
    reply = app.save(after, {'editWhileKeyringLocked': True})
    notice = next(value for cb, value in after.responses if cb == 'App.originalKontaktDauerfreigabe')
    assert reply['ok'] and reply['kontaktQuellenDauerhaft'] and notice['ok'] is False
    after._kontakt_quellen_netz_timer = 123; after._kontakt_quellen_netz_generation = 1
    app.monkeypatch.setattr(app.native, 'kontakt_quellen_wlan_verfuegbar', lambda: True)
    after._kontakt_quellen_netz_pruefen(); app.drain()
    assert after._kontakt_quellen_netz_timer == 123 and len(app.decisions) == 1
    app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', actual_lookup)
    after._kontakt_quellen_netz_pruefen(); app.drain()
    notice = [value for cb, value in after.responses if cb == 'App.originalKontaktDauerfreigabe'][-1]
    assert notice == {'id': 51, 'standSha256': reply['standSha256'], 'ok': True, 'freigaben': 1}
    assert len(after._kontakt_quellen_freigaben.capture()) == 1 and len(app.decisions) == 1
    assert app.source.writes == 0


def test_first_setup_retains_initial_real_saveack_for_quiet_access_return_before_any_delivery(application):
    app = application; host = app.start(); reply = app.save(host)
    setup = app.setup(host)
    assert setup['dauerhaft'] is True and setup['id'] == 51 and setup['standSha256'] == reply['standSha256']
    actual_lookup = app.accounts.secrets.lookup_noninteractive
    def locked(*args): raise NextcloudError('Controlled locked account', 'secret_service_locked')
    app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', locked)
    before = len(app.source.records)
    host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_update', 'requestId': 'initial-account-wait',
        'standSha256': reply['standSha256']})); app.drain()
    result = next(value for cb, value in host.responses if cb == 'App.originalKontaktErgebnis')
    assert result['code'] == 'account_access_wait' and len(app.source.records) == before
    app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', actual_lookup)
    host._kontakt_quellen_netz_timer = 123; host._kontakt_quellen_netz_generation = 1
    app.monkeypatch.setattr(app.native, 'kontakt_quellen_wlan_verfuegbar', lambda: True)
    host._kontakt_quellen_netz_pruefen(); app.drain()
    assert [value for cb, value in host.responses if cb == 'App.originalKontaktDauerfreigabe'][-1]['ok'] is True
    assert len(app.decisions) == 1


@pytest.mark.parametrize('mode', ['wrong-id', 'wrong-hash', 'newer-edit', 'paused', 'locked'])
def test_stale_or_unavailable_saveack_cannot_restore_or_emit_positive_authority(application, mode):
    app = application; host = app.start(); app.save(host); app.setup(host)
    reply = app.save(host)
    host.responses.clear(); save_id, fingerprint = 51, reply['standSha256']
    if mode == 'wrong-id': save_id += 1
    if mode == 'wrong-hash': fingerprint = 'a' * 64
    if mode == 'newer-edit': host._aktuelle_daten['notYetSaved'] = True
    if mode == 'paused': host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen'})); host.responses.clear()
    if mode == 'locked': host._gesperrt = True
    assert host._kontakt_quellen_dauerwiederherstellen(save_id, fingerprint) is False
    assert not any(cb == 'App.originalKontaktDauerfreigabe' for cb, _ in host.responses)


def test_corrupt_private_store_does_not_block_ordinary_save_or_grant_from_imported_flags(application):
    app = application; host = app.start(); app.save(host); app.setup(host)
    (Path(host._kontakt_quellen_dauerfreigabe.root) / 'approval.json').write_text('{broken')
    reply = app.save(host, {'einstellungen': {'sync': {'automatisch': True}}, 'sourceAdmissions': ['claimed']})
    assert reply['ok'] and reply['committed'] and not reply['repairPending']
    assert not reply.get('kontaktQuellenDauerhaft') and host._kontakt_quellen_dauerfehler
    assert not any(cb == 'App.originalKontaktDauerfreigabe' for cb, _ in host.responses)


def test_lost_account_context_after_nonempty_decision_is_not_interpreted_as_explicit_empty_revoke(application):
    from magnolie_contact_source_dav import NativeDavApprovalScope
    app = application; host = app.start(); app.save(host); app.setup(host)
    root = Path(host._kontakt_quellen_dauerfreigabe.root)
    previous_key, previous_state = (root / '.key').read_bytes(), (root / 'approval.json').read_bytes()
    actual_configure = NativeDavApprovalScope.configure
    def locked(*args): raise NextcloudError('Controlled lost account context', 'secret_service_locked')
    def configure_then_lock(scope, *args):
        result = actual_configure(scope, *args)
        app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', locked)
        return result
    app.monkeypatch.setattr(NativeDavApprovalScope, 'configure', configure_then_lock)
    reply = app.setup(host)
    assert reply['ok'] is False and reply['freigaben'] == 0
    assert (root / '.key').read_bytes() == previous_key and (root / 'approval.json').read_bytes() == previous_state


def test_account_lock_after_durable_write_keeps_waiting_setup_and_resumes_without_another_decision(application):
    from magnolie_contact_source_dav import NativeDavApprovalScope
    app = application; host = app.start(); saved = app.save(host)
    actual_restore = NativeDavApprovalScope.restore
    actual_lookup = app.accounts.secrets.lookup_noninteractive
    def locked(*args): raise NextcloudError('Controlled locked after durable write', 'secret_service_locked')
    def restore_then_lock(scope, stored, *args):
        result = actual_restore(scope, stored, *args)
        app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', locked)
        return result
    with app.monkeypatch.context() as scope_patch:
        scope_patch.setattr(NativeDavApprovalScope, 'restore', restore_then_lock)
        reply = app.setup(host)
    assert reply['ok'] and reply['dauerhaft'] and reply['wartet'] and reply['freigaben'] == 0
    assert reply['id'] == 51 and reply['standSha256'] == saved['standSha256']
    app.monkeypatch.setattr(app.accounts.secrets, 'lookup_noninteractive', actual_lookup)
    host._kontakt_quellen_netz_timer = 123; host._kontakt_quellen_netz_generation = 1
    app.monkeypatch.setattr(app.native, 'kontakt_quellen_wlan_verfuegbar', lambda: True)
    host._kontakt_quellen_netz_pruefen(); app.drain()
    assert [value for cb, value in host.responses if cb == 'App.originalKontaktDauerfreigabe'][-1]['ok'] is True
    assert len(app.decisions) == 1


def test_native_pause_between_restore_observation_and_scope_assignment_cannot_regrant(application):
    from magnolie_contact_source_dav import NativeDavApprovalScope
    app = application; host = app.start(); app.save(host); app.setup(host)
    actual_restore = NativeDavApprovalScope.restore
    def pause_before_restore(scope, stored, *args):
        host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen'}))
        return actual_restore(scope, stored, *args)
    app.monkeypatch.setattr(NativeDavApprovalScope, 'restore', pause_before_restore)
    reply = app.save(host, {'ordinaryEdit': 'synthetic-pause-race'})
    assert reply['ok'] and reply['kontaktQuellenDauerhaft']
    assert host._kontakt_quellen_freigaben.capture() == ()
    assert not any(cb == 'App.originalKontaktDauerfreigabe' for cb, _ in host.responses)
    assert host._kontakt_quellen_dauerfreigabe.has_desired_consent()


def test_failed_durable_revoke_reports_failure_and_does_not_restore_in_current_process(application):
    app = application; host = app.start(); app.save(host); app.setup(host)
    app.monkeypatch.setattr(host._kontakt_quellen_dauerfreigabe, 'revoke', lambda:
        (_ for _ in ()).throw(OSError('Controlled durable revoke failure')))
    host.responses.clear()
    host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen', 'dauerhaft': True})); app.drain()
    result = next(value for cb, value in host.responses if cb == 'App.originalKontaktFreigabe')
    assert result['ok'] is False and result['freigaben'] == 0
    assert host._kontakt_quellen_freigaben.capture() == () and host._kontakt_quellen_dauerhaft_gesperrt
    app.save(host, {'ordinaryEditAfterFailure': True})
    assert not any(cb == 'App.originalKontaktDauerfreigabe' for cb, _ in host.responses)
