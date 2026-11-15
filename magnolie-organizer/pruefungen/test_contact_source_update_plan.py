"""Update-only native saved-contact planning; synthetic cards, no provider IO."""
import copy
import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_contact_source_dav_factory import Source, saved_book
from magnolie_contact_source_dav import BoundDavContact
from test_startup_read_failure import native
import magnolie_nextcloud as nc


@pytest.mark.parametrize('mode', ['fresh', 'encrypted', 'older-metadata', 'wrong-readback', 'book-changed', 'write-failed',
    'schema6', 'schema6-encrypted', 'legacy-task'])
def test_exact_native_protection_uses_actual_journal_not_old_periodic_snapshot(native, tmp_path, monkeypatch, mode):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    source, key, local, owner, data, row = fixture(native, tmp_path)
    if mode in ('schema6', 'schema6-encrypted', 'legacy-task'):
        data['version'] = 6
        if mode == 'legacy-task': data['aufgaben'] = [{'id': 'legacy', 'titel': 'Preserve unmigrated graph'}]
        owner.record_saved('native-contact-fixture', True, json.dumps(data))
    password = 'Synthetic-only-618' if mode in ('encrypted', 'schema6-encrypted') else ''
    current = lambda: owner.capture('native-contact-fixture', True, data)
    snapshot = current()
    probe = SimpleNamespace(_daten_sperre=threading.RLock(), _kennwort=password,
                            _kontakt_quellen_buchaufnahme=current)
    older = None
    if mode == 'older-metadata':
        previous = copy.deepcopy(data)
        previous['einstellungen'] = {'view': 'older'}
        assert not native.journal_inhalt_geaendert(previous, data)
        older = native.journal_snapshot_erzeugen(previous, 'weekly')
    original_read = native.journal_snapshot_lesen
    if mode == 'wrong-readback':
        def bad_read(*args, **kwargs):
            stand, actual = original_read(*args, **kwargs)
            actual['daten']['saved'] = 'Not the exact protected book'
            return stand, actual
        monkeypatch.setattr(native, 'journal_snapshot_lesen', bad_read)
    if mode == 'book-changed': data['newEdit'] = True
    if mode == 'write-failed':
        def fail(*args, **kwargs): raise OSError('Controlled protection storage failure')
        monkeypatch.setattr(native, 'journal_snapshot_erzeugen', fail)
    if mode in ('wrong-readback', 'book-changed', 'write-failed'):
        with pytest.raises((RuntimeError, OSError)):
            native.Fenster._kontakt_quellen_schutz(probe, snapshot)
    else:
        identity = native.Fenster._kontakt_quellen_schutz(probe, snapshot)
        stand, actual = original_read(identity, password, exakt=True)
        assert actual['daten'] == snapshot.book() and current() == snapshot
        assert stand['reason'] == 'pre-contact'
        if older: assert identity != older['snapshotId']
        # Exact unchanged snapshots can be reused after actual content verification.
        assert native.Fenster._kontakt_quellen_schutz(probe, snapshot) == identity
        if mode in ('schema6', 'schema6-encrypted', 'legacy-task'):
            assert original_read(identity, password)[1]['daten']['version'] == 7, 'Normal restore migration was disabled'
        if mode == 'schema6-encrypted':
            assert native.journal_umschluesseln('New-synthetic-618', password)['geschafft'] >= 1
            assert original_read(identity, 'New-synthetic-618', exakt=True)[1]['daten'] == snapshot.book()


@pytest.mark.parametrize('mode', ['success', 'revoked', 'source-failed', 'book-during-read',
    'book-on-source-error', 'cancel-during-protection', 'unknown-write', 'conflict'])
def test_native_coordinator_factory_readback_is_only_an_unsaved_proposal(native, tmp_path, mode):
    from test_contact_source_dav_factory import account
    from magnolie_contact_source_dav import NativeDavApprovalScope, NativeBoundDavFactory
    source, key, local, owner, data, row = fixture(native, tmp_path)
    store = account(tmp_path)
    current = lambda: owner.capture('native-contact-fixture', True, data)
    snapshot = current()
    scope = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), store)
    catalog = nc.NextcloudDav(store.checked_client(store.read_snapshot()[2], transport=source.transport)).collections('addressbook')
    scope.configure(catalog, lambda choices, selected: [key])
    approvals = scope.capture()
    cancellation = [False]
    protections = []
    def protect():
        protections.append(snapshot.content_sha256)
        if mode == 'cancel-during-protection': cancellation[0] = True
    def open_source(approval, hrefs, guard):
        if mode == 'source-failed': raise OSError('Controlled unavailable source')
        if mode == 'book-on-source-error':
            data['newEdit'] = True
            raise OSError('Controlled unavailable source with changed book')
        return NativeBoundDavFactory(store, approval, hrefs, guard, protect,
                                     native.kontakt_original_vcard_beobachtung,
                                     lambda: cancellation[0], source.transport)
    if mode == 'revoked': scope.revoke()
    if mode == 'book-during-read': source.before_report = lambda: data.update(newEdit=True)
    if mode == 'unknown-write': source.mode = 'write-failed'
    if mode == 'conflict':
        source.wire = native.vcard_text(dict(source.original, notiz='Independent remote change'))
        source.etag = '"new-remote"'
    before = copy.deepcopy(data)
    args = (snapshot, current, approvals, open_source, lambda: cancellation[0])
    if mode in ('book-during-read', 'book-on-source-error', 'cancel-during-protection'):
        with pytest.raises((RuntimeError, InterruptedError)): native.kontakt_quellen_updates_vorbereiten(*args)
        assert source.writes == 0
    else:
        proposal = native.kontakt_quellen_updates_vorbereiten(*args)
        assert data == before and current() == snapshot
        assert data['kontakte'][0]['syncQuellen'][key]['etag'] == '"v1"'
        if mode == 'success':
            assert source.writes == 1 and protections == [snapshot.content_sha256]
            candidate = proposal['book']['kontakte'][0]
            assert candidate['uid'] == 'canonical-person' and candidate['syncQuellen'][key]['id'] == source.resource
            assert candidate['syncQuellen'][key]['etag'] == '"v2"'
            assert proposal['outcomes'][0]['status'] == 'update'
            # Only a later real native save can make this proposal current.
            assert owner.current('native-contact-fixture', True, proposal['book']) is None
        elif mode == 'conflict':
            assert source.writes == 0 and not protections
            assert proposal['outcomes'][0]['status'] == 'conflict'
            assert proposal['book']['kontakte'][0]['syncQuellen'] == before['kontakte'][0]['syncQuellen']
        else:
            assert source.writes == 0 and proposal['book'] == before
            assert proposal['outcomes'][-1]['status'] == 'held'


def fixture(native, tmp_path):
    source = Source(native)
    key = nc.source_id('addressbook', source.href, 'generic-dav')
    remote = native.vcf_lesen(source.wire)['kontakte'][0]
    uid, digest = native.kontakt_original_vcard_beobachtung(source.wire)
    local = dict(copy.deepcopy(remote), id='local', uid='canonical-person', sync=True)
    native._dav_syncquelle_setzen(local, key, source.resource, source.etag, baseline=remote)
    local['notiz'] = 'Canonical note'
    owner, data, text, current = saved_book(tmp_path, local)
    data['version'] = 7  # Current native book, not a pre-migration import.
    owner.record_saved('native-contact-fixture', True, json.dumps(data))
    return source, key, local, owner, data, BoundDavContact(source.resource, source.etag, source.wire, uid, digest)


@pytest.mark.parametrize('mode', ['two-books', 'first-unavailable', 'first-revoked', 'first-conflict', 'first-unknown'])
def test_source_failure_does_not_acknowledge_or_disable_another_original_book(native, tmp_path, mode):
    from test_contact_source_dav_factory import account
    from magnolie_contact_source_dav import NativeDavApprovalScope, NativeBoundDavFactory
    source, key, local, owner, data, row = fixture(native, tmp_path)
    second = Source(native)
    second.href = source.href.replace('/original/', '/second/')
    second.resource = second.href + 'person.vcf'
    key2 = nc.source_id('addressbook', second.href, 'generic-dav')
    data['kontakte'][0]['syncQuellen'][key2] = dict(local['syncQuellen'][key], id=second.resource)
    owner.record_saved('native-contact-fixture', True, json.dumps(data))
    current = lambda: owner.capture('native-contact-fixture', True, data)
    snapshot = current()
    store = account(tmp_path)
    # Adapt only the controlled fixture's static XML hrefs; production parsing,
    # account guards, conditional PUT and readback still run unchanged.
    def transport2(method, url, headers, body, timeout, limit):
        status, response_headers, payload = second.transport(method, url, headers, body, timeout, limit)
        return status, response_headers, payload.replace(b'/books/original/', b'/books/second/')
    catalog = []
    for transport in (source.transport, transport2):
        catalog += nc.NextcloudDav(store.checked_client(store.read_snapshot()[2], transport=transport)).collections('addressbook')
    scope = NativeDavApprovalScope(lambda: owner.current('native-contact-fixture', True, data), store)
    scope.configure(catalog, lambda choices, selected: [key, key2])
    approvals = scope.capture()
    if mode == 'first-revoked':
        scope.configure(catalog, lambda choices, selected: [key2])
        # Old approvals both expire on reconfiguration. Capture a deliberately
        # stale first token and the new live second token.
        approvals = (approvals[0], scope.capture()[0])
    if mode == 'first-conflict':
        source.wire = native.vcard_text(dict(source.original, notiz='Independent change'))
        source.etag = '"new"'
    if mode == 'first-unknown': source.mode = 'write-failed'
    protections = []
    def build(approval, hrefs, guard):
        if approval.source == key and mode == 'first-unavailable': raise OSError('Controlled unavailable original')
        transport = source.transport if approval.source == key else transport2
        return NativeBoundDavFactory(store, approval, hrefs, guard,
            lambda: protections.append(snapshot.content_sha256), native.kontakt_original_vcard_beobachtung,
            transport=transport)
    proposal = native.kontakt_quellen_updates_vorbereiten(snapshot, current, approvals, build)
    assert current() == snapshot and data['kontakte'][0]['uid'] == 'canonical-person'
    assert second.writes == 1
    mappings = proposal['book']['kontakte'][0]['syncQuellen']
    assert mappings[key2]['id'] == second.resource and mappings[key2]['etag'] == '"v2"'
    assert mappings[key]['etag'] == ('"v2"' if mode == 'two-books' else '"v1"')
    assert source.writes == (1 if mode == 'two-books' else 0)
    assert all(value == snapshot.content_sha256 for value in protections)
    assert all(value['etag'] == '"v1"' for value in data['kontakte'][0]['syncQuellen'].values())


@pytest.mark.parametrize('mode', ['dirty', 'clean', 'disabled', 'unbound', 'legacy', 'duplicate',
    'disabled-duplicate', 'missing-id', 'missing-uid', 'invalid-hash', 'other-source', 'forged-snapshot'])
def test_saved_bindings_are_dirty_existing_unique_targets_only(native, tmp_path, mode):
    source, key, local, owner, data, row = fixture(native, tmp_path)
    item = data['kontakte'][0]
    if mode == 'clean': item['notiz'] = 'Original'
    if mode == 'disabled': item['sync'] = False
    if mode == 'unbound': item['syncQuellen'][key].pop('id')
    if mode == 'legacy': item['syncQuellen'][key].pop('inhaltFormat')
    if mode == 'invalid-hash': item['syncQuellen'][key]['inhaltSha256'] = 'not-a-hash'
    if mode == 'missing-id': item.pop('id')
    if mode == 'missing-uid': item.pop('uid')
    if mode in ('duplicate', 'disabled-duplicate'):
        data['kontakte'].append(copy.deepcopy(item))
        if mode == 'disabled-duplicate': data['kontakte'][1]['sync'] = False
    if mode == 'other-source': key += '-not-this-source'
    owner.record_saved('native-contact-fixture', True, json.dumps(data))
    snapshot = owner.capture('native-contact-fixture', True, data)
    before = copy.deepcopy(data)
    if mode == 'forged-snapshot': snapshot = replace(snapshot, text=snapshot.text + ' ')
    if mode in ('duplicate', 'disabled-duplicate', 'missing-id', 'missing-uid', 'forged-snapshot'):
        with pytest.raises(ValueError): native.kontakt_quellen_update_bindungen(snapshot, key)
    else:
        targets = native.kontakt_quellen_update_bindungen(snapshot, key)
        assert len(targets) == (1 if mode == 'dirty' else 0)
        if targets: targets[0]['notiz'] = 'Only copied input'
    assert data == before


@pytest.mark.parametrize('mode', ['update', 'remote-conflict', 'existing-conflict', 'missing-original',
    'wrong-href', 'canonical-collision', 'disabled', 'unknown-baseline', 'same-etag-changed-content', 'forged-row'])
def test_single_original_plan_reuses_merge_without_identity_or_baseline_adoption(native, tmp_path, mode):
    source, key, local, owner, data, row = fixture(native, tmp_path)
    if mode == 'remote-conflict':
        wire = native.vcard_text(dict(source.original, notiz='Independent remote change'))
        uid, digest = native.kontakt_original_vcard_beobachtung(wire)
        row = BoundDavContact(row.href, '"remote-new"', wire, uid, digest)
    if mode == 'existing-conflict': local['kontaktProviderKonflikte'] = {key: {'status': 'pending'}}
    if mode == 'missing-original': row = None
    if mode == 'wrong-href': row = replace(row, href=source.href + 'different.vcf')
    if mode == 'canonical-collision':
        local['uid'] = 'another-canonical'
        # Binding must resolve by original href, not canonical identity.
    if mode == 'disabled': local['sync'] = False
    if mode == 'unknown-baseline': local['syncQuellen'][key].pop('inhaltFormat')
    if mode == 'same-etag-changed-content':
        wire = native.vcard_text(dict(source.original, notiz='Unversioned remote change'))
        uid, digest = native.kontakt_original_vcard_beobachtung(wire)
        row = BoundDavContact(row.href, row.etag, wire, uid, digest)
    if mode == 'forged-row': row = replace(row, content_sha256='0' * 64)
    before = copy.deepcopy(local)
    if mode in ('missing-original', 'wrong-href', 'disabled', 'unknown-baseline', 'same-etag-changed-content', 'forged-row'):
        with pytest.raises((ValueError, TypeError)): native.kontakt_quellen_update_plan(local, key, row)
    else:
        result = native.kontakt_quellen_update_plan(local, key, row)
        assert result['contact']['uid'] == local['uid']
        assert result['contact']['syncQuellen'] == local['syncQuellen']
        if mode in ('remote-conflict', 'existing-conflict'):
            assert result['status'] == 'conflict' and result['wire'] is None
            assert key in result['contact']['kontaktProviderKonflikte']
        else:
            assert result['status'] == 'update'
            assert 'UID:provider-original\r\n' in result['wire']
            assert 'Canonical note' in result['wire'] and local['uid'] not in result['wire']
    assert local == before and data['kontakte'][0]['syncQuellen'][key]['etag'] == '"v1"'
