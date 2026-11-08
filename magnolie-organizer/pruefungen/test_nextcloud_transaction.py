"""#438: actual post-rename failures, synthetic credentials, no network."""
import os
import stat
import subprocess
import sys

import pytest

from test_nextcloud import nc, SecretBackend, m


def test_post_config_rename_directory_sync_restores_exact_config_and_both_secrets(tmp_path, monkeypatch):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(str(path), backend)
    store.save(True, False, 'https://old.example.test', 'fixture', 'old-synthetic')
    # Preserve legacy whitespace/representation, not only normalized settings.
    path.write_bytes(b'{ "aktiv": true, "server": "https://old.example.test", "benutzer": "fixture" }\n')
    before = path.read_bytes()
    destination = store.account('https://new.example.test', 'fixture')
    backend.values[destination] = 'destination-synthetic'
    secrets = dict(backend.values)
    fsync = nc.os.fsync
    injected = []

    def fail_after_config_rename(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not injected and b'new.example.test' in path.read_bytes():
            injected.append(True)
            raise OSError('synthetic post-config-rename directory fsync')
        return fsync(fd)

    monkeypatch.setattr(nc.os, 'fsync', fail_after_config_rename)
    with pytest.raises(OSError):
        store.save(True, False, 'https://new.example.test', 'fixture', 'new-synthetic')
    assert injected
    assert path.read_bytes() == before, 'config changed despite failed save'
    assert backend.values == secrets, 'one of the pre-existing credentials was lost'
    assert store.load()['server'] == 'https://old.example.test'


@pytest.mark.parametrize('operation', ['initial', 'same', 'change', 'delete'])
@pytest.mark.parametrize('stage', ['before_config', 'after_config', 'credential_side_effect'])
def test_every_failed_transaction_restores_exact_prior_state(tmp_path, monkeypatch, operation, stage):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    if operation != 'initial':
        store.save(True, False, 'https://old.example.test', 'fixture', 'old-synthetic')
    prior = path.read_bytes() if path.exists() else None
    before = store.read_snapshot()
    secrets = dict(backend.values)
    atomic = nc._atomic_json

    def fail_config(*args):
        if stage == 'after_config':
            atomic(*args)
        raise OSError('synthetic config failure')

    if stage != 'credential_side_effect':
        monkeypatch.setattr(nc, '_atomic_json', fail_config)
    else:
        name = 'clear' if operation == 'delete' else 'store'
        original = getattr(backend, name)
        calls = []

        def mutate_then_fail(*args):
            result = original(*args)
            if not calls:
                calls.append(True)
                raise OSError('synthetic credential side effect')
            return result

        monkeypatch.setattr(backend, name, mutate_then_fail)
    server = 'https://new.example.test' if operation in ('initial', 'change') else 'https://old.example.test'
    with pytest.raises(OSError):
        store.save(operation != 'delete', False, server, 'fixture',
                   '' if operation == 'delete' else 'new-synthetic', operation == 'delete')
    assert (path.read_bytes() if path.exists() else None) == prior
    assert backend.values == secrets
    assert store.read_snapshot() == before
    assert nc.NextcloudSettingsStore(path, backend).read_snapshot() == before
    assert (path.parent / (path.name + '.transaction')).read_bytes() == b'clean\n'


def test_old_credential_clear_failure_after_side_effect_restores_both_identities(tmp_path, monkeypatch):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    store.save(True, False, 'https://old.example.test', 'fixture', 'old-synthetic')
    target = store.account('https://new.example.test', 'fixture')
    backend.values[target] = 'preexisting-destination'
    before = path.read_bytes(), dict(backend.values), store.read_snapshot()
    clear = backend.clear

    def fail_old(key):
        clear(key)
        raise OSError('synthetic old credential removal after side effect')

    monkeypatch.setattr(backend, 'clear', fail_old)
    with pytest.raises(OSError):
        store.save(True, False, 'https://new.example.test', 'fixture', 'new-synthetic')
    assert (path.read_bytes(), backend.values, store.read_snapshot()) == before


@pytest.mark.parametrize('failure', ['config_restore', 'destination_restore', 'old_restore', 'readback'])
def test_uncertain_rollback_attempts_all_restorations_and_blocks_reopened_store(tmp_path, monkeypatch, failure):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    settings = store.save(True, False, 'https://old.example.test', 'fixture', 'old-synthetic')
    old = store.account(settings['server'], 'fixture')
    target = store.account('https://new.example.test', 'fixture')
    backend.values[target] = 'destination-synthetic'
    attempts = []
    rollback = []
    atomic = nc._atomic_bytes
    store_secret, lookup = backend.store, backend.lookup

    def fail_config(*args):
        rollback.append(True)
        raise OSError('synthetic primary failure')

    def restore_bytes(destination, value):
        if str(destination) == str(path) and rollback:
            attempts.append('config')
            if failure == 'config_restore':
                raise OSError('synthetic config rollback failure')
        return atomic(destination, value)

    def restore_secret(key, value):
        if rollback:
            attempts.append(key)
            if (failure == 'destination_restore' and key == target) or (failure == 'old_restore' and key == old):
                raise OSError('synthetic credential rollback failure')
        return store_secret(key, value)

    def readback(key):
        if rollback and failure == 'readback':
            raise OSError('synthetic readback failure')
        return lookup(key)

    monkeypatch.setattr(nc, '_atomic_json', fail_config)
    monkeypatch.setattr(nc, '_atomic_bytes', restore_bytes)
    monkeypatch.setattr(backend, 'store', restore_secret)
    monkeypatch.setattr(backend, 'lookup', readback)
    with pytest.raises(nc.NextcloudError) as raised:
        store.save(True, False, 'https://new.example.test', 'fixture', 'new-synthetic')
    assert raised.value.code == 'account_recovery_required'
    assert set(attempts) == {'config', target, old}
    assert (tmp_path / 'nextcloud.json.transaction').read_bytes() == b'pending\n'
    for owner in (store, nc.NextcloudSettingsStore(path, backend)):
        for action in (owner.load, owner.read_snapshot, lambda: owner.password(settings),
                       lambda: owner.has_password(settings), lambda: nc.configured_client(owner),
                       lambda: owner.checked_client('obsolete'),
                       lambda: owner.save(True, False, settings['server'], 'fixture', 'another'),
                       lambda: owner.save_checked('obsolete', True, False, settings['server'], 'fixture', 'another')):
            with pytest.raises(nc.NextcloudError) as blocked:
                action()
            assert blocked.value.code == 'account_recovery_required'


def test_pending_barrier_failure_precedes_any_mutation(tmp_path, monkeypatch):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    fsync = nc.os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError('synthetic pending marker directory sync')
        return fsync(fd)

    monkeypatch.setattr(nc.os, 'fsync', fail_directory)
    with pytest.raises(OSError):
        store.save(True, False, 'https://new.example.test', 'fixture', 'new-synthetic')
    assert not path.exists() and not backend.values
    with pytest.raises(nc.NextcloudError) as blocked:
        nc.NextcloudSettingsStore(path, backend).load()
    assert blocked.value.code == 'account_recovery_required'


def test_cross_process_lock_blocks_reads_and_writes_without_stealing_owner(tmp_path):
    path = tmp_path / 'nextcloud.json'
    store = nc.NextcloudSettingsStore(path, SecretBackend())
    # A pipe handshake, not timing/sleep, proves the other process owns flock.
    child = subprocess.Popen([sys.executable, '-c',
        'import fcntl,sys; f=open(sys.argv[1], "a"); fcntl.flock(f,fcntl.LOCK_EX); '
        'print("locked",flush=True); sys.stdin.readline()', str(path) + '.lock'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        import select
        assert select.select([child.stdout], [], [], 5)[0]
        assert child.stdout.readline().strip() == 'locked'
        for action in (store.load, lambda: store.save(True, False, 'https://new.example.test', 'fixture', 'synthetic')):
            with pytest.raises(nc.NextcloudError) as blocked:
                action()
            assert blocked.value.code == 'account_busy'
        assert not path.exists()
    finally:
        child.communicate('\n', timeout=5)
    assert store.load() is None


def test_process_exit_after_credential_mutation_leaves_durable_block(tmp_path):
    path = tmp_path / 'nextcloud.json'
    script = '''
import os,sys
sys.path.insert(0, sys.argv[1])
import magnolie_nextcloud as nc
class Secrets:
    def lookup(self, key): return None
    def store(self, key, value): os._exit(73)
    def clear(self, key): pass
nc.NextcloudSettingsStore(sys.argv[2], Secrets()).save(True,False,'https://new.example.test','fixture','synthetic')
'''
    result = subprocess.run([sys.executable, '-c', script, os.path.dirname(nc.__file__), str(path)], timeout=10)
    assert result.returncode == 73
    assert not path.exists()
    assert (tmp_path / 'nextcloud.json.transaction').read_bytes() == b'pending\n'
    with pytest.raises(nc.NextcloudError) as blocked:
        nc.NextcloudSettingsStore(path, SecretBackend()).load()
    assert blocked.value.code == 'account_recovery_required'


def test_native_error_text_explains_recovery_block():
    message = m.nextcloud_fehlertext(nc.NextcloudError('synthetic', 'account_recovery_required'))
    assert 'recovery' in message and 'blocked' in message
    assert 'current operation' in m.nextcloud_fehlertext(nc.NextcloudError('synthetic', 'account_busy'))


@pytest.mark.parametrize('after_rename', [False, True])
def test_clean_marker_failure_never_exposes_unverified_state(tmp_path, monkeypatch, after_rename):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    atomic = nc._atomic_bytes

    def fail_clean(destination, value):
        if value == b'clean\n':
            if after_rename:
                atomic(destination, value)
            raise OSError('synthetic clean marker failure')
        return atomic(destination, value)

    monkeypatch.setattr(nc, '_atomic_bytes', fail_clean)
    if after_rename:
        assert store.save(True, False, 'https://new.example.test', 'fixture', 'synthetic')['davAktiv']
        assert nc.configured_client(store).password == 'synthetic'
    else:
        with pytest.raises(nc.NextcloudError) as failed:
            store.save(True, False, 'https://new.example.test', 'fixture', 'synthetic')
        assert failed.value.code == 'account_recovery_required'
        with pytest.raises(nc.NextcloudError):
            nc.configured_client(nc.NextcloudSettingsStore(path, backend))


def test_silent_backend_write_failure_is_verified_and_rolled_back(tmp_path, monkeypatch):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    store.save(True, False, 'https://old.example.test', 'fixture', 'synthetic-old')
    before = store.read_snapshot(), path.read_bytes(), dict(backend.values)
    original = backend.store

    def ignore_new(key, value):
        if value == 'synthetic-new':
            return True
        return original(key, value)

    monkeypatch.setattr(backend, 'store', ignore_new)
    with pytest.raises(nc.NextcloudError) as failed:
        store.save(True, False, 'https://old.example.test', 'fixture', 'synthetic-new')
    assert failed.value.code == 'verification_failed'
    assert (store.read_snapshot(), path.read_bytes(), backend.values) == before


@pytest.mark.parametrize('marker', [b'pending\n', b'', b'clean\ncorrupt', b'unknown\n'])
def test_non_clean_marker_cannot_be_bypassed_by_new_password(tmp_path, marker):
    path = tmp_path / 'nextcloud.json'
    (tmp_path / 'nextcloud.json.transaction').write_bytes(marker)
    backend = SecretBackend()
    store = nc.NextcloudSettingsStore(path, backend)
    with pytest.raises(nc.NextcloudError) as failed:
        store.save(True, False, 'https://new.example.test', 'fixture', 'synthetic')
    assert failed.value.code == 'account_recovery_required'
    assert not path.exists() and not backend.values


def test_checked_successful_change_has_verified_new_context_and_preserves_unrelated_secret(tmp_path):
    path = tmp_path / 'nextcloud.json'
    backend = SecretBackend()
    backend.values['unrelated'] = 'synthetic-unrelated'
    store = nc.NextcloudSettingsStore(path, backend)
    revision = store.read_snapshot()[2]
    first = store.save_checked(revision, True, False, 'https://old.example.test', 'fixture', 'synthetic-old')
    second = store.save_checked(first[2], True, False, 'https://new.example.test', 'fixture', 'synthetic-new')
    client = store.checked_client(second[2])
    assert client.server == 'https://new.example.test' and client.password == 'synthetic-new'
    assert backend.values == {'unrelated': 'synthetic-unrelated',
                              store.account('https://new.example.test', 'fixture'): 'synthetic-new'}
    assert second[2] != first[2] and second[1]
    assert os.stat(str(path) + '.transaction').st_mode & 0o777 == 0o600
    assert os.stat(str(path) + '.lock').st_mode & 0o777 == 0o600
