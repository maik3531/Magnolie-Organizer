"""Native-only DAV approval/factory with actual codecs, CAS and readback.

All profiles, credentials, decision callbacks and transports are synthetic.
No automatic frontend/dispatcher, live provider or baseline commit is claimed.
"""
import copy
from dataclasses import replace
import html
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_nextcloud as nc
from magnolie_contact_source_book import NativeContactSourceBook
from magnolie_contact_source_dav import NativeDavApprovalScope, NativeBoundDavFactory
from test_startup_read_failure import native


class Secrets:
    def __init__(self): self.values = {}
    def store(self, key, value): self.values[key] = value; return True
    def lookup(self, key): return self.values.get(key)
    def clear(self, key): self.values.pop(key, None); return True


def account(tmp_path, account_type='generic-dav'):
    store = nc.NextcloudSettingsStore(str(tmp_path / 'account.json'), Secrets())
    store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'synthetic-only', account_type=account_type)
    return store


class Source:
    href = 'https://source.invalid/nc/books/original/'
    resource = href + 'person.vcf'
    def __init__(self, native):
        self.native = native
        self.permission = True
        self.records = []
        self.writes = 0
        self.etag = '"v1"'
        self.original = {'uid': 'provider-original', 'vorname': 'Alex', 'nachname': 'Fixture', 'notiz': 'Original'}
        self.wire = native.vcard_text(self.original)
        self.mode = ''
        self.before_report = lambda: None
        self.before_redirect = lambda: None

    def transport(self, method, url, headers, body, _timeout, _limit):
        self.records.append((method, url, copy.deepcopy(headers)))
        if method == 'PROPFIND':
            if headers['Depth'] != '1':
                xml = '<d:response><d:href>/nc/</d:href><d:propstat><d:prop><c:addressbook-home-set><d:href>/nc/books/</d:href></c:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
            else:
                privilege = '' if self.permission is None else '<d:current-user-privilege-set><d:privilege><d:' + ('write-content' if self.permission else 'read') + '/></d:privilege></d:current-user-privilege-set>'
                xml = '<d:response><d:href>/nc/books/original/</d:href><d:propstat><d:prop><d:displayname>Original</d:displayname><d:resourcetype><c:addressbook/></d:resourcetype>' + privilege + '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
        elif method == 'REPORT':
            self.before_report()
            assert url == self.href
            xml = '<d:response><d:href>/nc/books/original/person.vcf</d:href><d:propstat><d:prop><d:getetag>' + html.escape(self.etag) + '</d:getetag><c:address-data>' + html.escape(self.wire) + '</c:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
        elif method == 'PUT':
            assert url == self.resource and headers.get('If-Match') == self.etag and 'If-None-Match' not in headers
            assert b'UID:provider-original\r\n' in body and b'UID:canonical-person' not in body
            if self.mode == 'write-failed': raise OSError('Controlled unknown provider outcome')
            if self.mode in ('redirect-revoked', 'redirect-retarget', 'redirect-account-changed'):
                self.before_redirect()
                return 307, {'Location': self.href + 'other.vcf' if self.mode == 'redirect-retarget' else self.resource}, b''
            self.writes += 1
            self.wire, self.etag = body.decode(), '"v2"'
            if self.mode == 'bad-readback-uid': self.wire = self.wire.replace('UID:provider-original\r\n', 'UID:different-original\r\n')
            if self.mode == 'missing-readback-uid': self.wire = self.wire.replace('UID:provider-original\r\n', '')
            if self.mode == 'bad-content': self.wire = self.wire.replace('Canonical note', 'Independent provider change')
            return 204, {'ETag': self.etag}, b''
        elif method == 'GET': return 200, {'ETag': self.etag}, self.wire.encode()
        else: pytest.fail('Unexpected create/delete/provider method: ' + method)
        return 207, {}, ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">' + xml + '</d:multistatus>').encode()


def saved_book(tmp_path, contact=None):
    data = {'kontakte': [copy.deepcopy(contact)] if contact is not None else [], 'syncEpoch': 'not-a-native-grant', 'saved': True,
            'sourceAdmissions': ['document-claims-only'], 'customOrganizer': {'x': 1.25}}
    text = json.dumps(data, ensure_ascii=False)
    nc._atomic_bytes(str(tmp_path / 'synthetic-book.json'), text.encode())
    owner = NativeContactSourceBook(); owner.set_ready(True)
    owner.record_saved('native-contact-fixture', True, text)
    current = lambda: owner.current('native-contact-fixture', True, data)
    return owner, data, text, current


@pytest.mark.parametrize('mode', ['success', 'no-grant', 'readonly', 'unknown', 'revoked-before-read', 'account-changed',
    'book-during-read', 'snapshot-failed', 'revoked-during-snapshot', 'account-during-snapshot', 'capability-during-snapshot',
    'book-during-snapshot', 'cancel-before-open', 'cancel-during-snapshot', 'wrong-outgoing-uid', 'bad-readback-uid',
    'missing-readback-uid', 'bad-content', 'write-failed', 'redirect-revoked', 'redirect-retarget', 'missing-bound',
    'duplicate-binding', 'escape-binding', 'duplicate-original-uid', 'missing-original-uid', 'wrong-revision', 'wrong-source',
    'wrong-origin', 'forged-admission', 'missing-protection', 'redirect-account-changed', 'encoded-escape-binding',
    'uid-spaces', 'duplicate-card', 'nextcloud', 'invalid-cancel', 'failed-reread', 'weak-etag', 'missing-etag', 'malformed-etag'])
def test_native_dav_factory_preserves_original_authority_and_actual_readback(native, tmp_path, mode):
    store = account(tmp_path, 'nextcloud' if mode == 'nextcloud' else 'generic-dav')
    source = Source(native)
    catalog = nc.NextcloudDav(store.checked_client(store.read_snapshot()[2], transport=source.transport)).collections('addressbook')
    local, = native.vcf_lesen(source.wire)['kontakte']
    baseline = native.kontakt_original_vcard_beobachtung(source.wire)[1]
    local.update(id='local', uid='canonical-person', sync=True, notiz='Canonical note', syncQuellen={catalog[0]['uid']: {
        'id': source.resource, 'etag': source.etag, 'inhaltSha256': baseline, 'eigen': True}})
    owner, data, text, current = saved_book(tmp_path, local)
    scope = NativeDavApprovalScope(current, store)
    assert scope.capture() == ()
    if mode != 'no-grant':
        scope.configure(catalog, lambda choices, selected: [choices[0]['uid']])
    approval = scope.capture()[0] if scope.capture() else None
    if mode == 'wrong-revision': approval = replace(approval, account_revision='not-the-native-account-revision')
    if mode == 'wrong-source': approval = replace(approval, source='thunderbird-addressbook:wrong')
    if mode == 'wrong-origin':
        foreign = 'https://foreign.invalid/nc/books/original/'
        approval = replace(approval, href=foreign, source=nc.source_id('addressbook', foreign, 'generic-dav'))
    if mode == 'forged-admission': approval = {'source': catalog[0]['uid'], 'href': source.href, 'saved': True, 'canUpdate': True}
    original_book = copy.deepcopy(current())
    cancelled = [mode == 'cancel-before-open']
    protections = []
    def require_book():
        if current() != original_book: raise RuntimeError('Controlled native book changed')
    def protect():
        protections.append(True)
        if mode == 'snapshot-failed': raise OSError('Controlled protection failure')
        nc._atomic_bytes(str(tmp_path / 'pre-contact.json'), text.encode())
        if mode == 'revoked-during-snapshot': scope.revoke()
        if mode == 'account-during-snapshot': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed-only', account_type='generic-dav')
        if mode == 'capability-during-snapshot': source.permission = False
        if mode == 'book-during-snapshot': data['newNativeEdit'] = True
        if mode == 'cancel-during-snapshot': cancelled[0] = True
    if mode in ('readonly', 'unknown'): source.permission = False if mode == 'readonly' else None
    if mode == 'revoked-before-read': scope.revoke()
    if mode == 'account-changed': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed-only', account_type='generic-dav')
    if mode == 'book-during-read': source.before_report = lambda: data.update(newNativeEdit=True)
    if mode == 'duplicate-original-uid': source.wire = source.wire.replace('UID:provider-original', 'UID:one\r\nUID:provider-original')
    if mode == 'missing-original-uid': source.wire = source.wire.replace('UID:provider-original\r\n', '')
    if mode == 'uid-spaces': source.wire = source.wire.replace('UID:provider-original', 'UID: provider-original ')
    if mode == 'duplicate-card': source.wire *= 2
    if mode == 'weak-etag': source.etag = 'W/"v1"'
    if mode == 'missing-etag': source.etag = ''
    if mode == 'malformed-etag': source.etag = '"v1"\r\nAnything: unsafe'
    source.mode = mode
    source.before_redirect = scope.revoke
    if mode == 'redirect-account-changed':
        source.before_redirect = lambda: store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed-on-redirect', account_type='generic-dav')
    bindings = [item['syncQuellen'][catalog[0]['uid']]['id'] for item in data['kontakte']]
    if mode == 'missing-bound': bindings = []
    if mode == 'duplicate-binding': bindings *= 2
    if mode == 'escape-binding': bindings = [source.href + '../foreign.vcf']
    if mode == 'encoded-escape-binding': bindings = [source.href + '%2e%2e/foreign.vcf']
    if mode == 'wrong-origin': bindings = [approval.href + 'person.vcf']
    factory = None
    records_before = len(source.records)
    original = None
    desired = native.vcard_text(dict(source.original, notiz='Canonical note', uid='canonical-person' if mode == 'wrong-outgoing-uid' else 'provider-original'))
    def run():
        nonlocal factory, original
        factory = NativeBoundDavFactory(store, approval, bindings, require_book, None if mode == 'missing-protection' else protect,
            native.kontakt_original_vcard_beobachtung, True if mode == 'invalid-cancel' else lambda: cancelled[0], source.transport)
        original, = factory.read_bound()
        if mode == 'failed-reread':
            source.before_report = lambda: (_ for _ in ()).throw(OSError('Controlled failed fresh provider read'))
            with pytest.raises(OSError): factory.read_bound()
        return factory.update_existing(original, desired)
    try:
        if mode in ('success', 'nextcloud'):
            result = run()
            assert result.href == source.resource and result.etag == '"v2"' and result.native_uid == 'provider-original'
            assert result.content_sha256 == native.kontakt_original_vcard_beobachtung(desired)[1]
            assert source.writes == 1 and protections == [True] and current() == original_book
            assert data['kontakte'][0]['uid'] == 'canonical-person' and data['kontakte'][0]['syncQuellen'][catalog[0]['uid']]['etag'] == '"v1"'
            assert (tmp_path / 'synthetic-book.json').read_text() == text, 'Provider readback silently saved a local baseline'
            assert (tmp_path / 'pre-contact.json').read_text() == text
            with pytest.raises(PermissionError): factory._dav.delete(source.resource, source.etag)
            with pytest.raises(PermissionError): factory._dav.put(source.resource, desired, create=True)
        else:
            expected = TypeError if mode in ('no-grant', 'forged-admission', 'missing-protection', 'invalid-cancel') else (PermissionError, ValueError, InterruptedError, OSError, nc.NextcloudError, RuntimeError)
            with pytest.raises(expected): run()
            assert source.writes == (1 if mode in ('bad-readback-uid', 'missing-readback-uid', 'bad-content') else 0)
            if mode in ('no-grant', 'revoked-before-read', 'account-changed', 'cancel-before-open', 'missing-bound', 'duplicate-binding', 'escape-binding',
                        'wrong-revision', 'wrong-source', 'wrong-origin', 'forged-admission', 'missing-protection', 'encoded-escape-binding', 'invalid-cancel'):
                assert len(source.records) == records_before and not protections
            if mode in ('wrong-outgoing-uid', 'duplicate-original-uid', 'missing-original-uid', 'book-during-read', 'uid-spaces', 'duplicate-card', 'failed-reread',
                        'weak-etag', 'missing-etag', 'malformed-etag'):
                assert not protections
            if mode in ('write-failed', 'bad-readback-uid', 'missing-readback-uid', 'bad-content', 'redirect-revoked', 'redirect-retarget', 'redirect-account-changed', 'failed-reread'):
                count = len(source.records)
                with pytest.raises(PermissionError): factory.update_existing(original, desired)
                assert len(source.records) == count, 'Uncertain original was blindly reused'
            if mode.startswith('redirect-'):
                assert sum(method == 'PUT' for method, _, _ in source.records) == 1
    finally:
        if factory is not None:
            factory.close()
            count = len(source.records)
            with pytest.raises(PermissionError): factory.read_bound()
            assert len(source.records) == count


@pytest.mark.parametrize('mode', ['later-save', 'cancel', 'empty', 'invalid', 'duplicate', 'revoke', 'reapprove',
    'lock', 'account-change', 'revoke-during-decision', 'save-during-decision', 'account-during-decision'])
def test_native_approval_generation_is_session_bound_not_discovery_or_imported_json(native, tmp_path, mode):
    store = account(tmp_path); source = Source(native)
    catalog = nc.NextcloudDav(store.checked_client(store.read_snapshot()[2], transport=source.transport)).collections('addressbook')
    owner, data, text, current = saved_book(tmp_path)
    scope = NativeDavApprovalScope(current, store)
    assert scope.capture() == ()
    eligible = catalog + [dict(catalog[0], canUpdate=None), dict(catalog[0], readOnly=True), dict(catalog[0], uid='thunderbird-addressbook:wrong')]
    def choose(choices, selected):
        assert len(choices) == 1 and not selected
        return [choices[0]['uid']]
    scope.configure(eligible, choose)
    approval, = scope.capture(); approval.require_current()
    if mode in ('cancel', 'empty', 'invalid', 'duplicate') or mode.endswith('-decision'):
        def decision(choices, selected):
            assert selected == (catalog[0]['uid'],)
            if mode == 'revoke-during-decision': scope.revoke()
            if mode == 'save-during-decision': owner.record_saved('native-contact-fixture', True, text)
            if mode == 'account-during-decision': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed', account_type='generic-dav')
            return None if mode == 'cancel' else [] if mode == 'empty' else ['unapproved'] if mode == 'invalid' else [catalog[0]['uid']] * (2 if mode == 'duplicate' else 1)
        if mode in ('invalid', 'duplicate'):
            with pytest.raises(ValueError): scope.configure(catalog, decision)
        elif mode.endswith('-decision'):
            with pytest.raises(PermissionError): scope.configure(catalog, decision)
        else: assert scope.configure(catalog, decision) is (mode != 'cancel')
    if mode == 'later-save': owner.invalidate_saved(); owner.record_saved('native-contact-fixture', True, text)
    if mode in ('revoke', 'reapprove'): scope.revoke()
    if mode == 'reapprove': scope.configure(catalog, choose)
    if mode == 'lock': owner.set_ready(False)
    if mode == 'account-change': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed', account_type='generic-dav')
    retained = mode in ('later-save', 'cancel', 'invalid', 'duplicate', 'save-during-decision')
    assert len(scope.capture()) == (1 if retained or mode == 'reapprove' else 0)
    if retained: approval.require_current()
    else:
        with pytest.raises(PermissionError): approval.require_current()
