"""#623: native record-copy hardening, not an external IPC exploit claim.

Only own synthetic native books/accounts, decision callbacks and DAV transport.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_contact_source_authority import context, approve
from test_contact_source_dav_factory import Source
from test_startup_read_failure import native
from magnolie_contact_source_dav import (
    NativeDavApprovalScope, NativeDavSourceApproval, NativeBoundDavFactory, require_native_decision)
from magnolie_nextcloud import source_id


def changed(context, mode):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    original, = scope.capture()
    approval = original
    if mode in ('retarget', 'normalized-href', 'unsafe-href'):
        href = {'retarget': 'https://source.invalid/nc/books/not-selected/',
                'normalized-href': 'https://SOURCE.invalid/nc/books/original/',
                'unsafe-href': 'https://source.invalid/nc/books/%2e%2e/not-selected/'}[mode]
        approval = replace(approval, source=source_id('addressbook', href, 'generic-dav'), href=href)
    if mode == 'revision': approval = replace(approval, account_revision='not-current')
    if mode == 'missing': approval = replace(approval, _native_consent=None)
    if mode == 'fake': approval = replace(approval, _native_consent=object())
    if mode == 'unminted': approval = NativeDavSourceApproval(original.source, original.href, original.account_revision, lambda: None)
    if mode in ('revoked', 'callback-bypass'):
        scope.revoke()
        if mode == 'callback-bypass': approval = replace(approval, require_current=lambda: None)
    if mode == 'account-changed':
        accounts.save(True, False, 'https://source.invalid/nc', 'synthetic', 'renewed-only', account_type='generic-dav')
    if mode == 'book-changed': data['not-yet-saved'] = True
    return approval


@pytest.mark.parametrize('surface', ['persistent', 'factory'])
@pytest.mark.parametrize('mode', ['retarget', 'normalized-href', 'unsafe-href', 'revision', 'missing', 'fake',
    'unminted', 'revoked', 'callback-bypass', 'account-changed', 'book-changed'])
def test_copied_native_record_never_retargets_or_bypasses_its_original_decision(context, native, surface, mode):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    snapshot = capture()
    approval = changed(context, mode)
    source = Source(native)
    with pytest.raises((PermissionError, TypeError, ValueError)):
        if surface == 'persistent': store.approve(snapshot, (approval,))
        else:
            NativeBoundDavFactory(accounts, approval, (approval.href + 'person.vcf',), lambda: None,
                lambda: pytest.fail('Rejected approval reached protection'), native.kontakt_original_vcard_beobachtung,
                transport=source.transport)
    assert source.records == [] and source.writes == 0
    assert not root.exists(), 'Rejected native record changed private consent files'


@pytest.mark.parametrize('restored', [False, True])
def test_legitimate_native_wrapper_preserves_private_witness_and_existing_original_access(context, native, restored):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    if restored:
        stored = approve(context)
        scope = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), accounts)
        scope.restore(stored)
    original, = scope.capture()
    calls = []
    def wrapper():
        calls.append(True)
        original.require_current()
    approval = replace(original, require_current=wrapper)
    require_native_decision(approval)
    source = Source(native)
    factory = NativeBoundDavFactory(accounts, approval, (source.resource,), lambda: None, lambda: None,
        native.kontakt_original_vcard_beobachtung, transport=source.transport)
    try:
        card, = factory.read_bound()
        assert card.native_uid == 'provider-original' and source.writes == 0 and calls
    finally:
        factory.close()
    # A genuine new UI decision clears the old restored-store dependency before
    # reapproval; simple lifetime wrappers do not silently become a new decision.
    if not restored:
        assert store.approve(capture(), (approval,)).sources == ((original.source, original.href),)


def test_restored_scope_mints_new_bound_witness_and_rejects_copies_without_touching_saved_intent(context):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    stored = approve(context)
    fresh = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), accounts)
    fresh.restore(stored)
    original, = fresh.capture()
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    href = 'https://source.invalid/nc/books/not-selected/'
    copied = replace(original, source=source_id('addressbook', href, 'generic-dav'), href=href)
    with pytest.raises(PermissionError): store.approve(capture(), (copied,))
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    require_native_decision(original)
    assert store.load_current().sources == stored.sources


def test_native_witness_is_not_a_mutable_or_replaceable_dataclass(context):
    *_, scope = context
    approval, = scope.capture()
    with pytest.raises(AttributeError): approval._native_consent._ConsentWitness__href = 'https://source.invalid/other/'
    with pytest.raises(TypeError): replace(approval._native_consent, href='https://source.invalid/other/')
    require_native_decision(approval)


def test_fake_durable_store_cannot_self_attest_a_forged_typed_restore(context):
    store, root, accounts, owner, data, text, capture, binding, scope = context
    original = approve(context)
    calls = []
    fake = SimpleNamespace()
    forged = replace(original, store=fake)
    fake.load_current = lambda: calls.append(True) or forged
    fresh = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), accounts)
    with pytest.raises(TypeError): fresh.restore(forged)
    assert calls == [] and fresh.capture() == ()


@pytest.mark.parametrize('surface', ['scope', 'factory'])
def test_native_account_boundary_rejects_fake_store_before_callbacks(context, native, surface):
    *_, scope = context
    approval, = scope.capture()
    fake = SimpleNamespace(read_snapshot=lambda **_: pytest.fail('Fake account callback used as native permission'))
    with pytest.raises(TypeError):
        if surface == 'scope': NativeDavApprovalScope(lambda: {}, fake)
        else: NativeBoundDavFactory(fake, approval, (Source.resource,), lambda: None, lambda: None,
            native.kontakt_original_vcard_beobachtung)
