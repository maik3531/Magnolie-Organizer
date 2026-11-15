"""Private native consent core only; synthetic files/accounts, no provider IO."""
import copy
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_contact_source_authority import NativeContactSourceApprovalStore, NativeStoredContactApproval
from magnolie_contact_source_dav import NativeDavApprovalScope
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_nextcloud import NextcloudSettingsStore, NextcloudError, source_id
from test_contact_source_dav_factory import account, saved_book, Source


@pytest.fixture
def context(tmp_path):
    accounts = account(tmp_path)
    owner, data, text, current = saved_book(tmp_path)
    capture = lambda: owner.capture('native-contact-fixture', True, data)
    binding = lambda: 'synthetic-private-native-book-binding'
    root = tmp_path / 'native-consent'
    store = NativeContactSourceApprovalStore(str(root), accounts, capture, binding)
    scope = NativeDavApprovalScope(current, accounts)
    catalog = [{'uid': source_id('addressbook', Source.href, 'generic-dav'), 'href': Source.href,
                'art': 'addressbook', 'canUpdate': True}]
    scope.configure(catalog, lambda choices, selected: [choices[0]['uid']])
    return store, root, accounts, owner, data, text, capture, binding, scope


def approve(context):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    witness = store.approve(capture(), scope.capture())
    assert type(witness) is NativeStoredContactApproval
    return witness


def test_default_reads_create_nothing_and_observe_no_book_or_credentials(tmp_path, monkeypatch):
    accounts = account(tmp_path)
    def forbidden(*args, **kwargs): pytest.fail('Default consent read observed native context')
    monkeypatch.setattr(accounts, 'read_snapshot', forbidden)
    root = tmp_path / 'absent'
    store = NativeContactSourceApprovalStore(str(root), accounts, forbidden, forbidden)
    assert store.load_current() is None and not root.exists()
    root.mkdir(mode=0o700)
    assert store.load_current() is None and list(root.iterdir()) == []


def test_restart_uses_new_saved_owner_and_fresh_process_revision_without_setup(context):
    first = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    restarted_account = NextcloudSettingsStore(accounts.path, accounts.secrets)
    restarted_account._revision_key = os.urandom(32)  # Simulate a fresh interpreter, not merely a new store object.
    restarted_owner = NativeContactSourceBook(); restarted_owner.set_ready(True)
    restarted_owner.record_saved('new-native-session', True, text)
    capture_after = lambda: restarted_owner.capture('new-native-session', True, data)
    restarted = NativeContactSourceApprovalStore(str(root), restarted_account, capture_after, binding)
    second = restarted.load_current()
    assert second.sources == first.sources and second.generation == first.generation
    assert second.snapshot != first.snapshot and second.account_revision != first.account_revision
    second.require_current()
    raw = (root / 'approval.json').read_text()
    assert 'synthetic-only' not in raw and 'synthetic-private-native-book-binding' not in raw
    assert first.account_revision not in raw and first.snapshot.book_source not in raw
    assert 'customOrganizer' not in raw
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    assert root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('mode', ['dict', 'stale-book', 'stale-source', 'wrong-source', 'duplicate', 'wrong-revision'])
def test_only_current_typed_native_decision_can_persist(context, mode):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    snapshot = capture(); approvals = scope.capture()
    if mode == 'dict': approvals = ({'source': approvals[0].source, 'href': approvals[0].href, 'saved': True},)
    if mode == 'stale-book': owner.record_saved('native-contact-fixture', True, text)
    if mode == 'stale-source': scope.revoke()
    if mode == 'wrong-source': approvals = (replace(approvals[0], source='document-only-claim'),)
    if mode == 'duplicate': approvals = approvals + approvals
    if mode == 'wrong-revision': approvals = (replace(approvals[0], account_revision='document-only-claim'),)
    with pytest.raises((TypeError, ValueError, PermissionError)): store.approve(snapshot, approvals)
    assert not root.exists()


@pytest.mark.parametrize('mode', ['book-edit', 'book-binding', 'account-user', 'account-path', 'account-provider',
    'account-disabled', 'credentials-locked', 'credentials-renewed', 'book-unavailable', 'same-content-new-save'])
def test_context_changes_hold_old_lease_without_erasing_human_intent(context, monkeypatch, mode):
    witness = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    sealed = (root / 'approval.json').read_bytes()
    if mode == 'book-edit': data['uncommitted'] = True
    if mode == 'book-binding': store._binding = lambda: 'different-native-book'
    if mode == 'account-user': accounts.save(True, False, 'https://source.invalid/nc', 'other-user', 'other-synthetic', account_type='generic-dav')
    if mode == 'account-provider': accounts.save(True, False, 'https://source.invalid/nc', 'synthetic', 'synthetic-only', account_type='nextcloud')
    if mode == 'account-path': store._account_store = NextcloudSettingsStore(accounts.path + '.other', accounts.secrets)
    if mode == 'account-disabled': accounts.save(False, False, 'https://source.invalid/nc', 'synthetic', '', account_type='generic-dav')
    if mode == 'credentials-locked':
        def locked(*args): raise NextcloudError('Controlled locked keyring', 'secret_service_locked')
        monkeypatch.setattr(accounts.secrets, 'lookup_noninteractive', locked)
    if mode == 'credentials-renewed': accounts.secrets.values[next(iter(accounts.secrets.values))] = 'synthetic-renewal'
    if mode == 'book-unavailable': owner.set_ready(False)
    if mode == 'same-content-new-save': owner.record_saved('native-contact-fixture', True, text)
    with pytest.raises((PermissionError, NextcloudError)): witness.require_current()
    assert (root / 'approval.json').read_bytes() == sealed
    if mode in ('credentials-renewed', 'same-content-new-save'):
        restored = store.load_current()
        assert restored.generation == witness.generation
        restored.require_current()


def test_temporary_keyring_lock_resumes_without_reapproval(context, monkeypatch):
    witness = approve(context)
    store, root, accounts, *_ = context
    actual = accounts.secrets.lookup_noninteractive
    def locked(*args): raise NextcloudError('Controlled locked keyring', 'secret_service_locked')
    monkeypatch.setattr(accounts.secrets, 'lookup_noninteractive', locked)
    with pytest.raises(NextcloudError): store.load_current()
    monkeypatch.setattr(accounts.secrets, 'lookup_noninteractive', actual)
    assert store.load_current().generation == witness.generation
    witness.require_current()


@pytest.mark.parametrize('mode', ['key', 'state', 'pending', 'missing-key', 'missing-state', 'missing-marker',
    'duplicate-json-key', 'bad-mac'])
def test_unknown_corrupt_or_partial_state_never_restores(context, mode):
    approve(context)
    store, root, *_ = context
    if mode == 'key': (root / '.key').write_bytes(b'x' * 32)
    if mode == 'state': (root / 'approval.json').write_text('{broken')
    if mode == 'pending': (root / '.transaction').write_bytes(b'pending\n')
    if mode.startswith('missing-'):
        (root / {'missing-key': '.key', 'missing-state': 'approval.json', 'missing-marker': '.transaction'}[mode]).unlink()
    if mode == 'duplicate-json-key': (root / 'approval.json').write_text('{"mac":"x","mac":"y","payload":{}}')
    if mode == 'bad-mac':
        record = json.loads((root / 'approval.json').read_text()); record['payload']['sources'][0]['href'] += 'other/'
        (root / 'approval.json').write_text(json.dumps(record))
    with pytest.raises((PermissionError, OSError, ValueError)): store.load_current()


@pytest.mark.parametrize('name,mode', [(name, mode) for name in ('.key', '.transaction', 'approval.json', '.lock', 'root')
    for mode in ('public', 'symlink', 'hardlink', 'fifo') if (name, mode) != ('root', 'hardlink')])
def test_insecure_native_paths_fail_closed_without_blocking(context, tmp_path, name, mode):
    approve(context)
    store, root, *_ = context
    target = root if name == 'root' else root / name
    if mode == 'public': target.chmod(0o777 if name == 'root' else 0o644)
    elif mode == 'hardlink':
        os.link(target, tmp_path / 'foreign-link')
    elif mode == 'symlink':
        moved = tmp_path / 'moved'
        target.rename(moved); target.symlink_to(moved, target_is_directory=name == 'root')
    elif mode == 'fifo':
        if name == 'root':
            target.rename(tmp_path / 'moved-root')
        else: target.unlink()
        os.mkfifo(target, 0o600)
    with pytest.raises((PermissionError, OSError)): store.load_current()


@pytest.mark.parametrize('operation', ['revoke', 'empty-selection', 'reapprove'])
def test_key_rotation_rejects_old_record_replay_and_old_lease(context, operation):
    witness = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    old_key = (root / '.key').read_bytes(); old_record = (root / 'approval.json').read_bytes()
    if operation == 'revoke': store.revoke()
    if operation == 'empty-selection': assert store.approve(capture(), ()) is None
    if operation == 'reapprove': store.approve(capture(), scope.capture())
    assert (root / '.key').read_bytes() != old_key
    with pytest.raises(PermissionError): witness.require_current()
    if operation != 'reapprove': assert store.load_current() is None
    (root / 'approval.json').write_bytes(old_record)
    with pytest.raises(PermissionError): store.load_current()


@pytest.mark.parametrize('write_number', [1, 2, 3, 4])
def test_publish_failure_leaves_no_usable_new_or_partial_approval(context, monkeypatch, write_number):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    actual = store._write; writes = []
    def fail(directory, name, value):
        writes.append(name)
        if len(writes) == write_number: raise OSError('Controlled native write failure')
        return actual(directory, name, value)
    monkeypatch.setattr(store, '_write', fail)
    with pytest.raises(OSError): store.approve(capture(), scope.capture())
    try: result = store.load_current()
    except (OSError, PermissionError): result = None
    assert result is None


def test_callbacks_never_run_under_store_lock(context, monkeypatch):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    def outside(callback):
        def observe(*args, **kwargs):
            if root.exists():
                with open(root / '.lock', 'rb') as stream:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return callback(*args, **kwargs)
        return observe
    store._capture = outside(capture); store._binding = outside(binding)
    monkeypatch.setattr(accounts, 'read_snapshot', outside(accounts.read_snapshot))
    approve(context).require_current()


def test_revocation_during_restore_cannot_return_old_approval(context, monkeypatch):
    approve(context)
    store, root, accounts, *_ = context
    actual = store._account
    def revoke_after_account():
        result = actual(); store.revoke(); return result
    monkeypatch.setattr(store, '_account', revoke_after_account)
    with pytest.raises(PermissionError): store.load_current()


def test_failed_approve_validation_cannot_revoke_newer_native_decision(context, monkeypatch):
    approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    actual_publish = store._publish
    newer = []
    def publish(directory, key, payload):
        actual_publish(directory, key, payload)
        replacement = copy.deepcopy(payload); replacement['generation'] = 'a' * 64
        actual_publish(directory, key, replacement)
        newer.append(replacement['generation'])
    monkeypatch.setattr(store, '_publish', publish)
    with pytest.raises(PermissionError): store.approve(capture(), scope.capture())
    assert newer and store.load_current().generation == newer[-1]


@pytest.mark.parametrize('operation', ['load', 'approve', 'revoke'])
def test_contended_native_lock_fails_without_waiting(context, operation):
    approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    with open(root / '.lock', 'rb') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            if operation == 'load': store.load_current()
            if operation == 'approve': store.approve(capture(), scope.capture())
            if operation == 'revoke': store.revoke()


@pytest.mark.parametrize('stage', ['key', 'state', 'clean-marker'])
def test_post_replace_failure_quarantines_even_a_visible_clean_marker(context, monkeypatch, stage):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    actual = store._write
    def fail(directory, name, value):
        actual(directory, name, value)
        if ((stage == 'key' and name == '.key') or (stage == 'state' and name == 'approval.json') or
                (stage == 'clean-marker' and name == '.transaction' and value == b'clean\n')):
            raise OSError('Controlled failure after replacement before confirmation')
    monkeypatch.setattr(store, '_write', fail)
    with pytest.raises(OSError): store.approve(capture(), scope.capture())
    assert (root / '.transaction').read_bytes() == b'pending\n'
    with pytest.raises(PermissionError): store.load_current()


@pytest.mark.parametrize('observation', [1, 2])
def test_revocation_on_either_account_observation_is_rechecked(context, monkeypatch, observation):
    approve(context)
    store, *_ = context
    actual, calls = store._account, []
    def account_then_revoke():
        value = actual(); calls.append(True)
        if len(calls) == observation: store.revoke()
        return value
    monkeypatch.setattr(store, '_account', account_then_revoke)
    with pytest.raises(PermissionError): store.load_current()


def test_stale_post_approval_context_revokes_only_its_generation(context, monkeypatch):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    actual = store._publish
    def publish_then_change_book(directory, key, payload):
        actual(directory, key, payload)
        if payload['sources']: data['newer-uncommitted-edit'] = True
    monkeypatch.setattr(store, '_publish', publish_then_change_book)
    with pytest.raises(PermissionError): store.approve(capture(), scope.capture())
    assert store.load_current() is None


def test_changed_book_holds_before_any_credential_read(context, monkeypatch):
    approve(context)
    store, root, accounts, owner, data, text, capture, *_ = context
    data['new-confirmed-book'] = True
    owner.record_saved('native-contact-fixture', True, json.dumps(data))
    def forbidden(*args, **kwargs): pytest.fail('Unrecognized book queried credentials')
    monkeypatch.setattr(accounts, 'read_snapshot', forbidden)
    assert store.load_current() is None


@pytest.mark.parametrize('mode', ['version-bool', 'extra-field', 'generation', 'sources-type', 'sources-count',
    'source-extra', 'source-empty', 'source-long', 'duplicate-source', 'duplicate-href', 'content', 'account',
    'revoked-content', 'revoked-account'])
def test_even_correctly_sealed_malformed_records_fail_closed(context, mode):
    approve(context)
    store, root, *_ = context
    with store._locked() as directory: key, payload = store._record(directory)
    if mode == 'version-bool': payload['version'] = True
    if mode == 'extra-field': payload['rendererAuthority'] = True
    if mode == 'generation': payload['generation'] = 'bad'
    if mode == 'sources-type': payload['sources'] = {}
    if mode == 'sources-count': payload['sources'] *= 257
    if mode == 'source-extra': payload['sources'][0]['canUpdate'] = True
    if mode == 'source-empty': payload['sources'][0]['source'] = ''
    if mode == 'source-long': payload['sources'][0]['href'] = 'x' * 8193
    if mode == 'duplicate-source': payload['sources'].append(dict(payload['sources'][0], href=Source.href + 'other/'))
    if mode == 'duplicate-href': payload['sources'].append(dict(payload['sources'][0], source='other-source'))
    if mode == 'content': payload['content'] = 'bad'
    if mode == 'account': payload['account'] = None
    if mode == 'revoked-content': payload['sources'] = []; payload['account'] = None
    if mode == 'revoked-account': payload['sources'] = []; payload['content'] = None
    from magnolie_contact_source_authority import _json
    (root / 'approval.json').write_bytes(_json({'payload': payload, 'mac': store._tag(key, b'record', _json(payload))}))
    with pytest.raises(PermissionError): store.load_current()
