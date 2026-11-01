"""Native accepted-scope paging; no GUI, wire endpoint or producer admission."""
import copy
import sqlite3
import tempfile
from pathlib import Path
import pytest
import magnolie_content_scope as scope
import magnolie_personal_sync as personal
from test_personal_actor_source import actor_source_fixture
from test_personal_actor_transport import gtk_actor_bridge
from magnolie_personal_actor_store import NativeBookOwnerScope
import magnolie_hintergrund as background
from test_hintergrunddienst import FakeBackend
from test_shared_sync_transport import message
import magnolie_shared_sync as shared


def test_pages_preserve_utf8_order_cross_module_boundary_and_are_detached():
    manifest = scope.create(['a', 'ä', '😀'], ['b', 'z'])
    before = copy.deepcopy(manifest); members = {'notes': [], 'tasks': []}; offset = 0
    while True:
        page = scope.read_page(manifest, offset, 2)
        assert page['total'] == 5 and page['notes_total'] == 3 and page['tasks_total'] == 2
        assert page['scope'] == scope.reference(manifest)
        for kind in members: members[kind].extend(page['members'][kind])
        if page['next_offset'] is None: break
        assert page['next_offset'] > offset
        offset = page['next_offset']
    assert members == manifest['members'] and manifest == before
    first = scope.read_page(manifest, 0, 1); first['members']['notes'][0] = 'Caller edit'
    first['scope']['scope_hash'] = 'b' * 64
    assert manifest == before
    assert scope.read_page(manifest, 5, 128)['next_offset'] is None
    assert scope.read_page(scope.create([], []))['total'] == 0


@pytest.mark.parametrize('offset,limit', [(-1, 1), (6, 1), (0, 0), (0, 129), (True, 1), (0, True), ('0', 1)])
def test_page_ranges_are_strict(offset, limit):
    with pytest.raises(ValueError): scope.read_page(scope.create(['a', 'b', 'c'], ['d', 'e']), offset, limit)


def test_maximum_scope_and_escaped_identifiers_are_byte_bounded():
    manifest = scope.create(['id%05d' % index + '\u0001' * 150 for index in range(50000)], [])
    first = scope.read_page(manifest)
    assert first['total'] == 50000 and 0 < first['next_offset'] < 128
    assert len(personal.canonical(first)) <= 32000
    last = scope.read_page(manifest, 49999)
    assert len(last['members']['notes']) == 1 and last['next_offset'] is None


def test_native_service_pages_have_no_data_queue_wire_or_gui_side_effects(tmp_path, monkeypatch):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    service.native_actor_book_source = lambda: 'a' * 64
    source = service.current_actor_source(peer['device_id'], fingerprint)
    wire = copy.deepcopy(channel.sent); before_peer = copy.deepcopy(peer); events = []
    service.callback = lambda *event: events.append(event)
    def rows():
        with sqlite3.connect(service.store.database_path) as db:
            return db.execute('SELECT * FROM outbox ORDER BY message_id').fetchall(), db.execute('SELECT * FROM meta ORDER BY key').fetchall()
    before = rows()
    first = service.read_personal_actor_scope(peer['device_id'], fingerprint, source, 0, 1)
    last = service.read_personal_actor_scope(peer['device_id'], fingerprint, source, 1, 1)
    assert first['sourceRevision'] == source and first['members'] == {'notes': ['note-one'], 'tasks': []}
    assert first['next_offset'] == 1 and last['next_offset'] is None
    assert last['members'] == {'notes': [], 'tasks': ['task-one']}
    assert rows() == before and peer == before_peer and channel.sent == wire and events == []
    bridge = gtk_actor_bridge()
    result = bridge(None, service, {'action': 'notes_actor_scope', 'peerId': peer['device_id'], 'fingerprint': fingerprint,
        'sourceRevision': source, 'offset': 1, 'limit': 1})
    assert result == {'ok': True, 'scopePage': last}


@pytest.mark.parametrize('gate', ['stale-pin', 'book', 'grant', 'channel', 'scope', 'during-read'])
def test_native_pages_reject_changed_authority_before_or_after_read(tmp_path, monkeypatch, gate):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    service.native_actor_book_source = lambda: 'a' * 64
    source = service.current_actor_source(peer['device_id'], fingerprint)
    if gate == 'stale-pin': source = 'b' * 64
    if gate == 'book': service.native_actor_book_source = lambda: 'b' * 64
    if gate == 'grant': peer['local_grants']['grants']['personal_tasks_sync'] = False
    if gate == 'channel': service.connections.clear()
    if gate == 'scope': service.content_scope_sessions.clear()
    if gate == 'during-read':
        original = scope.read_page
        def changed(*args, **kwargs):
            page = original(*args, **kwargs)
            service.native_actor_book_source = lambda: 'b' * 64
            return page
        monkeypatch.setattr(scope, 'read_page', changed)
    with pytest.raises(PermissionError): service.read_personal_actor_scope(peer['device_id'], fingerprint, source)


@pytest.mark.parametrize('gate', ['success', 'foreign-gui', 'lock', 'during-ipc'])
def test_real_private_ipc_scope_pages_remain_bound_to_the_exact_gui_lease(tmp_path, monkeypatch, gate):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    owner = NativeBookOwnerScope(); owner.set_ready(True)
    provider = lambda: owner.current('native-page-profile', True)
    with tempfile.TemporaryDirectory(prefix='actor-scope-ipc-') as root:
        path = str(Path(root) / 'bridge.sock')
        server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
        service.personal_sync_available = server.gui_personal_ready
        proxy = background.PhoneServiceProxy(path); other = background.PhoneServiceProxy(path)
        proxy.native_actor_book_source = provider; other.native_actor_book_source = provider
        try:
            proxy.start(); proxy.set_visible(True); proxy.set_ready(True)
            source = proxy.current_actor_source(peer['device_id'], fingerprint)
            assert source
            wire = copy.deepcopy(channel.sent)
            if gate == 'foreign-gui':
                other.start(); other.set_visible(True); other.set_ready(True)
                assert other.current_actor_source(peer['device_id'], fingerprint) != source
                with pytest.raises(background.IPCError): other.read_personal_actor_scope(peer['device_id'], fingerprint, source)
            elif gate == 'lock':
                owner.set_ready(False)
                with pytest.raises(background.IPCError): proxy.read_personal_actor_scope(peer['device_id'], fingerprint, source)
            elif gate == 'during-ipc':
                original = proxy._call
                def changed(operation, **kwargs):
                    result = original(operation, **kwargs)
                    if operation == 'actor_scope': owner.invalidate()
                    return result
                monkeypatch.setattr(proxy, '_call', changed)
                with pytest.raises(background.IPCError): proxy.read_personal_actor_scope(peer['device_id'], fingerprint, source)
            else:
                response = gtk_actor_bridge()(None, proxy, {'action': 'notes_actor_scope', 'peerId': peer['device_id'],
                    'fingerprint': fingerprint, 'sourceRevision': source, 'offset': 0, 'limit': 1})
                assert response['ok'] and response['scopePage']['members'] == {'notes': ['note-one'], 'tasks': []}
                assert response['scopePage']['sourceRevision'] == source
                assert not server._phone_actor_owners, 'Pre-admission scope read created an Actor owner'
            assert channel.sent == wire and service.server is None
            assert service.native_actor_producer_book is None, 'Scope paging introduced a daemon plaintext provider/cache'
        finally:
            for item in (proxy, other):
                item.stop()
                if item._event_thread is not None: item._event_thread.join(timeout=3)
            server.close()


@pytest.mark.parametrize('field,value', [('offset', True), ('offset', -1), ('offset', 50001), ('limit', True),
    ('limit', 0), ('limit', 129), ('expected_source', 'client-name'), ('subscriber', 'not-owner')])
def test_scope_page_ipc_is_strict_and_bounded(field, value):
    arguments = {'subscriber': 'a' * 32, 'peer_id': '11111111-1111-4111-8111-111111111111',
        'fingerprint': 'AAAA-BBBB-CCCC-DDDD', 'book_source': 'b' * 64, 'expected_source': 'c' * 64,
        'offset': 0, 'limit': 128}
    arguments[field] = value
    with pytest.raises(background.IPCError): background._request_shape('phone_actor_scope', arguments)


@pytest.mark.parametrize('gate', ['allowed', 'skip', 'local-grant', 'remote-grant', 'format3', 'no-format'])
def test_baseline_policy_is_derived_from_current_native_controls(tmp_path, monkeypatch, gate):
    service, peer, channel, fingerprint, manifest = actor_source_fixture(tmp_path, monkeypatch)
    service.native_actor_book_source = lambda: 'a' * 64
    peer['local_grants']['grants']['personal_deletions_sync'] = gate != 'local-grant'
    peer['grants']['grants']['personal_deletions_sync'] = gate != 'remote-grant'
    service.note_controls[channel]['grants.update'] = copy.deepcopy(peer['grants'])
    if gate in ('format3', 'no-format'):
        for name in ('personal_notes_sync', 'personal_tasks_sync'):
            peer['capabilities']['items'][name]['versions'] = [value for value in peer['capabilities']['items'][name]['versions']
                if value != 14 and (gate != 'no-format' or value != 3)]
        service.note_controls[channel]['capabilities.update'] = copy.deepcopy(peer['capabilities'])
    setting = service.store.change_shared_setting(peer['device_id'], peer['static_public'], 'skip_deletions', gate == 'skip')
    remote = shared.merge(shared.create(peer['device_id']), setting, peer['device_id'], service.store.identity['device_id'])
    service._payload(peer, channel, message(remote))
    # Shared preference application legitimately updates the local deletion
    # grant. Exercise a subsequent native revocation, not a superseded fixture.
    if gate == 'local-grant': peer['local_grants']['grants']['personal_deletions_sync'] = False
    source = service.current_actor_source(peer['device_id'], fingerprint)
    assert source
    if gate == 'no-format':
        with pytest.raises(PermissionError): service.read_personal_actor_scope(peer['device_id'], fingerprint, source)
    else:
        policy = service.read_personal_actor_scope(peer['device_id'], fingerprint, source)['baseline']
        assert policy == {'record_format': 3 if gate == 'format3' else 14,
            'propagate_deletions': gate in ('allowed', 'format3')}
