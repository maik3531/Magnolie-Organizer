"""Typed durable-native scope rehydration; no application startup/UI claim."""
from dataclasses import replace
import json

import pytest

from test_contact_source_authority import context, approve
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_contact_source_dav import NativeDavApprovalScope
from magnolie_nextcloud import NextcloudError
from test_startup_read_failure import native


def restored(context):
    stored = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    fresh = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), accounts)
    assert fresh.restore(stored) is True
    approval, = fresh.capture()
    assert (approval.source, approval.href) == stored.sources[0]
    approval.require_current()
    return fresh, approval


@pytest.mark.parametrize('mode', ['dictionary', 'changed-sources', 'changed-snapshot', 'changed-revision', 'different-book'])
def test_scope_restore_requires_exact_current_native_witness(context, mode):
    stored = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    if mode == 'dictionary': stored = {'sources': stored.sources, 'saved': True}
    if mode == 'changed-sources': stored = replace(stored, sources=(('document-only', 'https://other.invalid/book/'),))
    if mode == 'changed-snapshot': stored = replace(stored, snapshot=replace(stored.snapshot, sequence=999))
    if mode == 'changed-revision': stored = replace(stored, account_revision='not-current')
    current = lambda: owner.current('different-book' if mode == 'different-book' else 'native-contact-fixture', True, data)
    fresh = NativeDavApprovalScope(current, accounts)
    with pytest.raises((TypeError, PermissionError)): fresh.restore(stored)
    assert fresh.capture() == ()


@pytest.mark.parametrize('mode', ['durable-revoke', 'volatile-revoke', 'new-save', 'book-locked', 'credentials-locked', 'credentials-renewed'])
def test_restored_source_guard_cannot_outlive_durable_or_current_native_authority(context, monkeypatch, mode):
    fresh, approval = restored(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    if mode == 'durable-revoke': store.revoke()
    if mode == 'volatile-revoke': fresh.revoke()
    if mode == 'new-save': owner.record_saved('native-contact-fixture', True, text)
    if mode == 'book-locked': owner.set_ready(False)
    if mode == 'credentials-locked':
        def locked(*args): raise NextcloudError('Controlled locked account', 'secret_service_locked')
        monkeypatch.setattr(accounts.secrets, 'lookup_noninteractive', locked)
    if mode == 'credentials-renewed': accounts.secrets.values[next(iter(accounts.secrets.values))] = 'synthetic-renewal'
    with pytest.raises(PermissionError): approval.require_current()
    assert fresh.capture() == ()
    if mode in ('volatile-revoke', 'new-save', 'credentials-renewed'):
        current = store.load_current()
        assert current is not None
        fresh.restore(current)
        replacement, = fresh.capture()
        replacement.require_current()


def test_keyring_unavailability_drops_only_volatile_scope_and_restores_without_decision(context, monkeypatch):
    fresh, original = restored(context)
    store, root, accounts, *_ = context
    def locked(*args): raise NextcloudError('Controlled locked account', 'secret_service_locked')
    with monkeypatch.context() as quiet:
        quiet.setattr(accounts.secrets, 'lookup_noninteractive', locked)
        assert fresh.capture() == ()
    fresh.restore(store.load_current())
    renewed, = fresh.capture()
    renewed.require_current()
    with pytest.raises(PermissionError): original.require_current()


def test_restart_scope_uses_new_actual_native_saved_owner_without_catalog_or_dialog(context):
    first = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    after = NativeContactSourceBook(); after.set_ready(True)
    after.record_saved('after-restart', True, text)
    store._capture = lambda: after.capture('after-restart', True, data)
    fresh = NativeDavApprovalScope(lambda: after.current('after-restart', True, data), accounts)
    restored = store.load_current()
    assert restored.snapshot != first.snapshot
    fresh.restore(restored)
    source, = fresh.capture(); source.require_current()


def test_concurrent_volatile_revoke_during_restore_cannot_be_undone(context, monkeypatch):
    stored = approve(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    fresh = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), accounts)
    actual = store.load_current
    def observe_then_revoke():
        result = actual(); fresh.revoke(); return result
    monkeypatch.setattr(store, 'load_current', observe_then_revoke)
    with pytest.raises(PermissionError): fresh.restore(stored)
    assert fresh.capture() == ()


@pytest.mark.parametrize('mode', ['rejected-context', 'context-revokes', 'invalid-context'])
def test_final_native_application_guard_cannot_be_skipped_or_regrant_after_revoke(context, mode):
    stored = approve(context)
    store, root, accounts, owner, data, *_ = context
    fresh = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), accounts)
    def require_context():
        if mode == 'rejected-context': raise PermissionError('Controlled application generation changed')
        fresh.revoke()
    with pytest.raises((PermissionError, TypeError)):
        fresh.restore(stored, {'saved': True} if mode == 'invalid-context' else require_context)
    assert fresh.capture() == ()


def test_signed_ordinary_save_needs_fresh_scope_hydration_not_old_lease(context):
    fresh, original = restored(context)
    store, root, accounts, owner, data, text, capture, binding, scope = context
    next_data = dict(data, ordinaryEdit='synthetic-next')
    next_text = json.dumps(next_data)
    intent = store.prepare_save(capture(), next_text)
    assert fresh.capture() == ()
    owner.invalidate_saved(); data.clear(); data.update(next_data)
    owner.record_saved('native-contact-fixture', True, next_text)
    store.confirm_save(intent, capture())
    fresh.restore(store.load_current())
    current, = fresh.capture(); current.require_current()
    with pytest.raises(PermissionError): original.require_current()


@pytest.mark.parametrize('revoke_before_update', [False, True])
def test_restored_native_scope_connects_actual_bound_dav_factory_and_revocation_gate(context, native, revoke_before_update):
    from magnolie_contact_source_dav import NativeBoundDavFactory
    from test_contact_source_dav_factory import Source
    fresh, approval = restored(context)
    store, root, accounts, *_ = context
    source = Source(native)
    current = store.load_current()
    protections = []
    factory = NativeBoundDavFactory(accounts, approval, [source.resource], current.require_current,
        lambda: protections.append(True), native.kontakt_original_vcard_beobachtung, transport=source.transport)
    try:
        original, = factory.read_bound()
        desired = native.vcard_text(dict(source.original, notiz='Canonical note'))
        if revoke_before_update:
            store.revoke()
            with pytest.raises(PermissionError): factory.update_existing(original, desired)
            assert source.writes == 0 and protections == []
        else:
            result = factory.update_existing(original, desired)
            assert result.native_uid == 'provider-original' and result.etag == '"v2"'
            assert source.writes == 1 and protections == [True]
    finally:
        factory.close()
