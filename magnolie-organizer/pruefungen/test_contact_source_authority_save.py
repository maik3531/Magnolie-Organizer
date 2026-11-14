"""Signed before/confirmed-save chain; no production writer wiring claimed."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_contact_source_authority import NativeContactSourceApprovalStore
from magnolie_contact_source_book import NativeContactSourceBook
from test_contact_source_authority import context, approve


def planned(context, **changes):
    data = dict(context[4], **changes)
    return data, json.dumps(data, ensure_ascii=False)


def actual_saved(context, new_data, text):
    store, root, accounts, owner, data, old_text, capture, binding, scope = context
    owner.invalidate_saved()
    # Synthetic adapter records only the controlled native write-success result.
    (root.parent / 'synthetic-book.json').write_text(text)
    data.clear(); data.update(new_data)
    owner.record_saved('native-contact-fixture', True, text)
    return capture()


def test_ordinary_save_advances_same_consent_without_keyring_access(context, monkeypatch):
    first = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    def forbidden(*args, **kwargs): pytest.fail('Native autosave queried keyring')
    with monkeypatch.context() as quiet:
        quiet.setattr(accounts, 'read_snapshot', forbidden)
        next_data, next_text = planned(context, ordinaryEdit='synthetic-note')
        intent = store.prepare_save(capture(), next_text)
        assert (root / '.book-intent.json').is_file()
        with pytest.raises(PermissionError): store.load_current()
        confirmed = actual_saved(context, next_data, next_text)
        assert store.confirm_save(intent, confirmed) == confirmed.content_sha256
        assert not (root / '.book-intent.json').exists()
    restored = store.load_current()
    assert restored.sources == first.sources and restored.generation == first.generation
    assert restored.key_fingerprint == first.key_fingerprint and restored.snapshot == confirmed
    with pytest.raises(PermissionError): first.require_current()
    with pytest.raises(PermissionError): store.confirm_save(intent, confirmed)
    restored.require_current()


@pytest.mark.parametrize('outcome', ['old', 'new', 'unknown'])
def test_restart_recovery_accepts_only_signed_known_old_or_new_saved_outcome(context, monkeypatch, outcome):
    first = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    next_data, next_text = planned(context, ordinaryEdit='synthetic-next')
    store.prepare_save(capture(), next_text)
    if outcome == 'new': actual_saved(context, next_data, next_text)
    if outcome == 'unknown': actual_saved(context, dict(next_data, thirdEdit='unknown'), json.dumps(dict(next_data, thirdEdit='unknown')))
    restarted_owner = NativeContactSourceBook(); restarted_owner.set_ready(True)
    restarted_owner.record_saved('restart-fixture', True, (root.parent / 'synthetic-book.json').read_text())
    capture_after = lambda: restarted_owner.capture('restart-fixture', True, data)
    restarted = NativeContactSourceApprovalStore(str(root), accounts, capture_after, binding)
    def forbidden(*args, **kwargs): pytest.fail('Crash recovery queried keyring')
    with monkeypatch.context() as quiet:
        quiet.setattr(accounts, 'read_snapshot', forbidden)
        if outcome == 'unknown':
            with pytest.raises(PermissionError): restarted.recover_saved(capture_after())
            assert (root / '.book-intent.json').exists()
            return
        assert restarted.recover_saved(capture_after()) == capture_after().content_sha256
    restored = restarted.load_current()
    assert restored.generation == first.generation and restored.sources == first.sources


@pytest.mark.parametrize('mode', ['no-previous', 'different-previous', 'array', 'bad-json', 'duplicate-json',
    'changed-book', 'different-binding', 'pending'])
def test_prepare_requires_recognized_actual_previous_book_and_no_outstanding_intent(context, mode):
    approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    previous = capture(); next_data, next_text = planned(context, ordinaryEdit='next')
    if mode == 'no-previous': previous = None
    if mode == 'different-previous': previous = replace(previous, content_sha256='a' * 64)
    if mode == 'array': next_text = '[]'
    if mode == 'bad-json': next_text = '{broken'
    if mode == 'duplicate-json': next_text = '{"einstellungen":{},"einstellungen":{"auto":true}}'
    if mode == 'changed-book': data['not-saved'] = True
    if mode == 'different-binding': store._binding = lambda: 'unrecognized-native-book'
    if mode == 'pending': store.prepare_save(previous, next_text)
    with pytest.raises((TypeError, ValueError, PermissionError)): store.prepare_save(previous, next_text)


@pytest.mark.parametrize('mode', ['no-save', 'wrong-content', 'forged-token', 'dict-token', 'different-store',
    'revoked', 'reapproved', 'book-unavailable'])
def test_confirm_cannot_bless_unconfirmed_changed_or_revoked_native_save(context, mode):
    approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    previous = capture(); next_data, next_text = planned(context, ordinaryEdit='next')
    intent = store.prepare_save(previous, next_text)
    if mode != 'no-save': confirmed = actual_saved(context, next_data, next_text)
    else: confirmed = previous
    if mode == 'wrong-content': confirmed = actual_saved(context, dict(next_data, unexpected=True), json.dumps(dict(next_data, unexpected=True)))
    if mode == 'forged-token': intent = replace(intent, token='0' * 64)
    if mode == 'dict-token': intent = {'token': intent.token}
    if mode == 'different-store': intent = replace(intent, store=object())
    if mode == 'revoked': store.revoke()
    if mode == 'reapproved':
        # Explicit new native decision is separate from any pending old save.
        scope.configure([{'uid': first.source, 'href': first.href, 'art': 'addressbook', 'canUpdate': True}
                         for first in scope.capture()], lambda choices, selected: [choices[0]['uid']])
        store.approve(capture(), scope.capture())
    if mode == 'book-unavailable': owner.invalidate_saved()
    with pytest.raises((TypeError, PermissionError)): store.confirm_save(intent, confirmed)


@pytest.mark.parametrize('stage', ['before-record', 'after-record', 'before-unlink'])
def test_crash_during_advancement_remains_recoverable_from_actual_new_save(context, monkeypatch, stage):
    first = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    next_data, next_text = planned(context, ordinaryEdit='next')
    intent = store.prepare_save(capture(), next_text)
    confirmed = actual_saved(context, next_data, next_text)
    actual_write, actual_remove = store._write, store._remove_intent
    with monkeypatch.context() as failure:
        def write(directory, name, value):
            if stage == 'before-record' and name == 'approval.json': raise OSError('Controlled pre-write failure')
            actual_write(directory, name, value)
            if stage == 'after-record' and name == 'approval.json': raise OSError('Controlled post-write failure')
        def remove(directory):
            if stage == 'before-unlink': raise OSError('Controlled pre-unlink failure')
            actual_remove(directory)
        failure.setattr(store, '_write', write); failure.setattr(store, '_remove_intent', remove)
        with pytest.raises(OSError): store.confirm_save(intent, confirmed)
    with pytest.raises(PermissionError): store.load_current()
    assert store.recover_saved(capture()) == confirmed.content_sha256
    assert store.load_current().generation == first.generation


def test_already_advanced_state_cannot_be_recovered_back_to_old_book(context, monkeypatch):
    approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    original = dict(data); next_data, next_text = planned(context, ordinaryEdit='next')
    intent = store.prepare_save(capture(), next_text)
    confirmed = actual_saved(context, next_data, next_text)
    with monkeypatch.context() as failure:
        failure.setattr(store, '_remove_intent', lambda directory: (_ for _ in ()).throw(OSError('Controlled unlink failure')))
        with pytest.raises(OSError): store.confirm_save(intent, confirmed)
    old = actual_saved(context, original, text)
    with pytest.raises(PermissionError): store.recover_saved(old)


@pytest.mark.parametrize('mode', ['corrupt', 'other-generation', 'symlink', 'hardlink', 'fifo', 'public'])
def test_corrupt_or_insecure_save_intent_never_restores_permissions(context, tmp_path, mode):
    approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    store.prepare_save(capture(), planned(context, ordinaryEdit='next')[1])
    path = root / '.book-intent.json'
    if mode == 'corrupt': path.write_text('{bad')
    if mode == 'other-generation':
        record = json.loads(path.read_text()); record['payload']['generation'] = 'a' * 64
        from magnolie_contact_source_authority import _json
        key = (root / '.key').read_bytes(); record['mac'] = store._tag(key, b'book-save', _json(record['payload']))
        path.write_bytes(_json(record))
    if mode == 'symlink':
        moved = tmp_path / 'moved-intent'; path.rename(moved); path.symlink_to(moved)
    if mode == 'hardlink': os.link(path, tmp_path / 'other-intent')
    if mode == 'fifo': path.unlink(); os.mkfifo(path, 0o600)
    if mode == 'public': path.chmod(0o644)
    with pytest.raises((PermissionError, ValueError, OSError)): store.load_current()
    with pytest.raises((PermissionError, ValueError, OSError)): store.recover_saved(capture())


def test_no_consent_or_revoked_consent_never_creates_save_intent(context, monkeypatch):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    def forbidden(*args, **kwargs): pytest.fail('Disabled native save path observed book/account')
    store._capture = forbidden
    monkeypatch.setattr(accounts, 'read_snapshot', forbidden)
    assert store.prepare_save(None, 'ignored') is None
    assert store.recover_saved(None) is None and not root.exists()
    store.revoke()
    assert store.prepare_save(None, 'ignored') is None
    assert store.recover_saved(None) is None and not (root / '.book-intent.json').exists()
