"""Non-prompting native credential path; controlled libsecret/SDK adapters only."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_nextcloud as nc
from magnolie_contact_source_dav import NativeDavApprovalScope, NativeBoundDavFactory
from test_contact_source_dav_factory import account, Source, saved_book
from test_startup_read_failure import native


class Cancellation:
    def __init__(self): self.event = threading.Event()
    def cancel(self): self.event.set()
    def is_cancelled(self): return self.event.is_set()


@pytest.mark.parametrize('mode', ['success', 'missing', 'locked', 'duplicate', 'lock-during-read',
    'no-value', 'invalid-text', 'service-failed', 'search-failed', 'timeout', 'cancel-during-text'])
def test_noninteractive_libsecret_never_unlocks_prompts_or_uses_password_lookup(monkeypatch, mode):
    cancellation, calls = Cancellation(), []
    monkeypatch.setattr(nc, '_secret_cancellable', lambda: cancellation)
    schema = object()
    def forbidden(*_): pytest.fail('Automatic credential access called an interactive operation')
    def get_text():
        calls.append('text')
        if mode == 'cancel-during-text': cancellation.cancel()
        return {'not': 'text'} if mode == 'invalid-text' else 'synthetic-only-app-secret'
    def get_locked():
        return mode == 'locked' or mode == 'lock-during-read' and 'text' in calls
    def get_secret():
        assert not get_locked(), 'Read a locked secret'
        calls.append('secret')
        return None if mode == 'no-value' else SimpleNamespace(get_text=get_text)
    item = SimpleNamespace(get_locked=get_locked, get_secret=get_secret)
    def search(actual_schema, attributes, flags, token):
        assert actual_schema is schema and attributes == {'account': 'synthetic-account'}
        assert flags == 10 and not flags & 4 and token is cancellation  # ALL|LOAD, NEVER UNLOCK
        calls.append('search')
        if mode == 'search-failed': raise OSError('Controlled service search failure')
        if mode == 'timeout':
            assert token.event.wait(timeout=1)
            raise OSError('Controlled cancelled lookup')
        return [] if mode == 'missing' else [item, item] if mode == 'duplicate' else [item]
    def get_service(flags, token):
        assert flags == 1 and token is cancellation
        if mode == 'service-failed': raise OSError('Controlled service unavailable')
        return SimpleNamespace(search_sync=search, unlock_sync=forbidden, prompt_sync=forbidden)
    secret = SimpleNamespace(Service=SimpleNamespace(get_sync=get_service),
        ServiceFlags=SimpleNamespace(OPEN_SESSION=1), SearchFlags=SimpleNamespace(ALL=2, LOAD_SECRETS=8, UNLOCK=4),
        password_lookup_sync=forbidden)
    store = nc.SecretServiceStore()
    store.LOOKUP_TIMEOUT = 0.03 if mode == 'timeout' else 1
    monkeypatch.setattr(store, '_secret', lambda: (secret, schema))
    if mode in ('success', 'missing', 'no-value'):
        assert store.lookup_noninteractive('synthetic-account') == ('synthetic-only-app-secret' if mode == 'success' else None)
    else:
        expected = ('secret_service_locked' if mode in ('locked', 'lock-during-read') else
                    'secret_ambiguous' if mode == 'duplicate' else
                    'secret_lookup_timeout' if mode in ('timeout', 'cancel-during-text') else 'secret_read_unavailable')
        with pytest.raises(nc.NextcloudError) as caught: store.lookup_noninteractive('synthetic-account')
        assert caught.value.code == expected
        assert 'synthetic-only-app-secret' not in str(caught.value)
    if mode in ('locked', 'duplicate'): assert 'secret' not in calls and 'text' not in calls
    assert not any(thread.name == 'magnolie-secret-noninteractive' for thread in threading.enumerate())


@pytest.mark.parametrize('mode', ['quiet', 'manual-only', 'quiet-failed'])
def test_custom_native_backend_must_explicitly_support_noninteractive_lookup(mode):
    calls = []
    backend = SimpleNamespace(lookup=lambda key: calls.append('manual') or 'synthetic-secret')
    if mode != 'manual-only':
        def quiet(key):
            calls.append('quiet')
            if mode == 'quiet-failed': raise OSError('Controlled backend failure')
            return 'synthetic-secret'
        backend.lookup_noninteractive = quiet
    store = nc.SecretServiceStore(backend)
    if mode == 'quiet': assert store.lookup_noninteractive('synthetic') == 'synthetic-secret'
    else:
        with pytest.raises(nc.NextcloudError): store.lookup_noninteractive('synthetic')
    assert 'manual' not in calls
    assert store.lookup('synthetic') == 'synthetic-secret' and calls[-1] == 'manual'


@pytest.mark.parametrize('mode', ['same-context', 'locked', 'changed-secret'])
def test_quiet_snapshot_and_client_preserve_exact_native_credential_revision(tmp_path, monkeypatch, mode):
    store = account(tmp_path)
    before = store.read_snapshot()
    def forbidden(*_): pytest.fail('Automatic account snapshot/client used interactive lookup')
    monkeypatch.setattr(store.secrets, 'lookup', forbidden)
    if mode == 'locked':
        monkeypatch.setattr(store.secrets, 'lookup_noninteractive', lambda key: (_ for _ in ()).throw(nc.NextcloudError('Controlled locked store', 'secret_service_locked')))
    if mode == 'changed-secret': store.secrets.values[next(iter(store.secrets.values))] = 'changed-synthetic-secret'
    quiet = store.read_snapshot(interactive=False)
    if mode == 'same-context':
        assert quiet == before
        client = store.checked_client(before[2], interactive=False)
        assert client.password == 'synthetic-only'
        client.password = ''
    else:
        if mode == 'locked': assert quiet[1:3] == (False, None) and quiet[3].code == 'secret_service_locked'
        else: assert quiet[2] != before[2]
        with pytest.raises(nc.NextcloudError): store.checked_client(before[2], interactive=False)


def test_automatic_native_dav_scope_and_original_read_never_use_interactive_credentials(native, tmp_path, monkeypatch):
    store, source = account(tmp_path), Source(native)
    owner, data, text, current = saved_book(tmp_path)
    def forbidden(*_): pytest.fail('Native automatic DAV path requested interactive credential access')
    monkeypatch.setattr(store.secrets, 'lookup', forbidden)
    scope = NativeDavApprovalScope(current, store)
    scope.configure([{'uid': nc.source_id('addressbook', source.href, 'generic-dav'), 'href': source.href,
                      'art': 'addressbook', 'canUpdate': True}], lambda choices, selected: [choices[0]['uid']])
    approval, = scope.capture()
    original_book = current()
    def require_book(): assert current() == original_book
    factory = NativeBoundDavFactory(store, approval, [source.resource], require_book,
        lambda: pytest.fail('Read-only credential test attempted a mutation'),
        native.kontakt_original_vcard_beobachtung, transport=source.transport)
    try:
        row, = factory.read_bound()
        assert row.native_uid == 'provider-original' and source.writes == 0
    finally: factory.close()


def test_empty_native_approval_scope_does_not_touch_credentials_or_book():
    def forbidden(*args, **kwargs): pytest.fail('Empty default scope read credentials/book')
    scope = NativeDavApprovalScope(forbidden, SimpleNamespace(read_snapshot=forbidden))
    assert scope.capture() == ()


def test_unavailable_native_saved_book_revokes_before_any_credential_read(tmp_path, monkeypatch):
    store = account(tmp_path)
    owner, data, text, current = saved_book(tmp_path)
    scope = NativeDavApprovalScope(current, store)
    href = 'https://source.invalid/nc/books/original/'
    scope.configure([{'uid': nc.source_id('addressbook', href, 'generic-dav'), 'href': href,
                      'art': 'addressbook', 'canUpdate': True}], lambda choices, selected: [choices[0]['uid']])
    owner.set_ready(False)
    def forbidden(*args, **kwargs): pytest.fail('Unavailable book requested keyring credentials')
    monkeypatch.setattr(store, 'read_snapshot', forbidden)
    assert scope.capture() == ()


@pytest.mark.parametrize('locked', [False, True])
def test_native_read_only_account_status_is_quiet_and_reports_waiting_not_password_loss(native, tmp_path, monkeypatch, locked):
    store = account(tmp_path)
    def forbidden(*_): pytest.fail('Read-only status requested interactive credential access')
    monkeypatch.setattr(store.secrets, 'lookup', forbidden)
    if locked:
        monkeypatch.setattr(store.secrets, 'lookup_noninteractive', lambda key:
            (_ for _ in ()).throw(nc.NextcloudError('Controlled locked keyring', 'secret_service_locked')))
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: store)
    result = native.nextcloud_status(discover=False)
    if locked:
        assert result['fehlerCode'] == 'secret_service_locked' and 'Waiting for account access' in result['fehler']
        assert 'not stored' not in result['fehler']
    else:
        assert result['zustand'] == 'bereit' and result['kennwortVorhanden'] is True


@pytest.mark.parametrize('operation', ['outbox', 'mailbox-poll', 'legacy-sync'])
def test_native_background_entrypoints_explicitly_forbid_interactive_credentials(native, tmp_path, monkeypatch, operation):
    from test_startup_read_failure import Host
    store = account(tmp_path, 'nextcloud')
    store.save(True, True, 'https://source.invalid/nc', 'synthetic', 'synthetic-only')
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: store)
    host = Host(native); host._gesperrt = False
    host._baum_zustand = lambda: {'kennung': 'synthetic'}
    host._journal_snapshot = lambda _: None
    calls = []
    def configured(actual_store, transport=None, purpose='dav', *, interactive=True):
        assert actual_store is store and interactive is False
        calls.append(purpose)
        raise nc.NextcloudError('Controlled locked keyring', 'secret_service_locked')
    monkeypatch.setattr(native, 'configured_client', configured)
    if operation == 'outbox':
        monkeypatch.setattr(native, 'baum_post_wartung', lambda *args, **kwargs: {'zugestellt': 0})
        assert host._baum_post_lauf() == {'zugestellt': 0}
    else:
        with pytest.raises(nc.NextcloudError):
            if operation == 'mailbox-poll': host._baum_briefkasten_poll()
            else: host._nextcloud_sync_ausfuehren({'daten': {}}, [], '')
    assert calls == ['dav' if operation == 'legacy-sync' else 'briefkasten']


def test_initial_automatic_approval_capture_runs_off_the_gtk_thread(native, tmp_path, monkeypatch):
    from test_startup_read_failure import Host
    store, source = account(tmp_path), Source(native)
    owner, data, text, current = saved_book(tmp_path)
    scope = NativeDavApprovalScope(current, store)
    scope.configure([{'uid': nc.source_id('addressbook', source.href, 'generic-dav'), 'href': source.href,
                      'art': 'addressbook', 'canUpdate': True}], lambda choices, selected: [choices[0]['uid']])
    actual_capture = scope.capture
    calls = []
    def capture():
        assert threading.current_thread() is not threading.main_thread()
        calls.append(True)
        return actual_capture()
    monkeypatch.setattr(scope, 'capture', capture)
    host = Host(native); host._gesperrt = False; host._wirklich_beenden = False
    host._aktuelle_daten = data
    host._kontakt_quellen_freigaben = scope
    host._kontakt_quellen_buchaufnahme = lambda: owner.capture('native-contact-fixture', True, data)
    snapshot = host._kontakt_quellen_buchaufnahme()
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: store)
    monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', lambda: True)
    threads, actual_thread = [], threading.Thread
    def worker(*args, **kwargs):
        thread = actual_thread(*args, **kwargs); threads.append(thread); return thread
    monkeypatch.setattr(native, 'threading', SimpleNamespace(Thread=worker))
    host._kontakt_quellen_updates_starten('synthetic-worker', snapshot.saved_sha256)
    for thread in threads:
        thread.join(timeout=5); assert not thread.is_alive()
    assert calls and host.responses[-1][1]['ok'] is True and source.records == []
    assert not host._kontakt_quellen_update_aktiv
