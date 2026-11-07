"""Existing native keys/destinations only; no installed UI or physical sync."""
from pathlib import Path
import sqlite3
import fcntl
import os
import sys
import threading

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_destination import NativePhotoDestinationController
from magnolie_file_transfer import TransferError
import magnolie_telefon as phone
from test_file_authenticated_desktop import native, bind


@pytest.fixture
def preferences(native, tmp_path):
    service, peer, _ = native
    channel, binding = bind(service, peer)
    authority = service.open_native_file_authority(peer['device_id'], peer['static_public'], channel, binding.generation)
    clock = [100]
    prefs = ProtectedPhotoPreferences(authority, monotonic_ms=lambda: clock[0])
    chooser = NativePhotoDestinationController(authority)
    target = tmp_path / 'explicit-native-photo-target'
    target.mkdir(mode=0o700)
    try:
        yield service, authority, prefs, chooser, target, clock
    finally:
        prefs.close(); chooser.close(); authority.close()


def configure(fixture, **settings):
    _, _, prefs, chooser, target, _ = fixture
    choice = chooser.choose_custom(chooser.issue_action(), target)
    return prefs.configure(prefs.issue_action(), prefs.read(), enabled=True, mode='manual',
                           destination_choice=choice, **settings)


def test_separate_sending_choice_bootstraps_only_explicit_consent_and_never_source_handlers(preferences):
    service,authority,prefs,_,target,_=preferences
    before=prefs.read()
    assert prefs.configure_sending(prefs.issue_action(),before,photos=False,videos=False)==before
    assert not (Path(service.store.root)/prefs._name).exists()
    saved=prefs.configure_sending(prefs.issue_action(),before,photos=True,videos=False)
    assert saved.policy.sending.photos and not saved.policy.sending.videos
    assert saved.policy.sending.pairing_epoch==authority.current_peer().pairing_epoch
    assert not saved.policy.enabled and saved.policy.destination is None and saved.policy.videos is None
    assert not prefs.local_grant(True).grants.send_files and not prefs.local_grant(True).grants.receive_files
    assert not list(target.iterdir())
    assert prefs.configure_sending(prefs.issue_action(),saved,photos=True,videos=False)==saved
    prefs.close()
    reopened=ProtectedPhotoPreferences(authority)
    try:assert reopened.read()==saved
    finally:reopened.close()


def test_sending_and_receiving_updates_preserve_independent_choices_but_require_new_control_revision(preferences):
    _,_,prefs,_,_,_=preferences
    received=configure(preferences)
    source=prefs.configure_sending(prefs.issue_action(),received,photos=True,videos=True)
    assert source.policy.destination==received.policy.destination and source.policy.destination_token==received.policy.destination_token
    assert source.policy.enabled==received.policy.enabled and source.policy.pairing_epoch==received.policy.pairing_epoch
    assert source.policy.permission_revision==source.policy.revision and source.policy.permission_epoch!=received.policy.permission_epoch
    changed=prefs.configure(prefs.issue_action(),source,enabled=True,mode='manual')
    assert changed.policy.sending==source.policy.sending
    behavior=prefs.set_mode(prefs.issue_action(),changed,'automatic')
    assert behavior.policy.sending==source.policy.sending
    off=prefs.configure_sending(prefs.issue_action(),behavior,photos=False,videos=True)
    assert not off.policy.sending.photos and off.policy.sending.videos
    assert off.policy.destination==received.policy.destination and off.policy.enabled
    assert not prefs.local_grant(True).grants.send_files


def test_sending_choices_reject_wire_stale_replayed_and_expired_native_actions(preferences):
    _,_,prefs,_,_,clock=preferences
    before=prefs.read();action=prefs.issue_action()
    saved=prefs.configure_sending(action,before,photos=True,videos=False)
    for candidate,expected in ((action,saved),(prefs.issue_action(),before),({'approve':True},saved)):
        with pytest.raises(TransferError):prefs.configure_sending(candidate,expected,photos=False,videos=True)
    expired=prefs.issue_action();clock[0]+=60001
    with pytest.raises(TransferError):prefs.configure_sending(expired,saved,photos=False,videos=True)
    assert prefs.read()==saved


def test_explicit_sending_repair_consent_does_not_rebind_old_receiving_rights(preferences):
    service,_,prefs,_,_,_=preferences
    received=configure(preferences)
    saved=prefs.configure_sending(prefs.issue_action(),received,photos=True,videos=False)
    peer=service.store.peers[0];peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([8])*32)
    service.store.save_peers();channel,binding=bind(service,peer)
    replacement=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    new=ProtectedPhotoPreferences(replacement)
    try:
        observed=new.read()
        assert observed.policy.sending==saved.policy.sending and not observed.associated
        changed=new.configure_sending(new.issue_action(),observed,photos=True,videos=False)
        assert changed.policy.sending.pairing_epoch==replacement.current_peer().pairing_epoch
        assert changed.policy.pairing_epoch==received.policy.pairing_epoch and not changed.associated
        assert changed.policy.destination==received.policy.destination and changed.policy.enabled
        assert not new.local_grant(True).grants.send_files and not new.local_grant(True).grants.receive_files
    finally:new.close();replacement.close()


@pytest.mark.parametrize('sending',[None,{},dict(photos=1,videos=False,pairing_epoch='a'*64),
    dict(photos=True,videos=False,pairing_epoch='bad'),dict(photos=True,videos=False,pairing_epoch='a'*64,read=True)])
def test_sending_codec_rejects_ambiguous_or_authority_like_fields(preferences,sending):
    from magnolie_photo_preferences import PhotoPreferences
    saved=configure(preferences)
    with pytest.raises(TransferError):PhotoPreferences.parse(dict(saved.policy.wire(),sending=sending))


def test_absent_read_and_grants_are_inert_manual_off_without_creating_metadata(preferences):
    service, _, prefs, _, _, _ = preferences
    root = Path(service.store.root)
    before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    first = prefs.read()
    assert first.policy is None and first.mode == 'manual'
    assert not first.associated and not first.destination_available
    for handlers in (False, True):
        grant = prefs.local_grant(handlers)
        assert not grant.grants.send_files and not grant.grants.receive_files
    assert not (root / prefs._name).exists()
    assert before == {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def test_explicit_native_configuration_is_encrypted_readback_and_not_reverse_permission(preferences):
    service, authority, prefs, _, target, _ = preferences
    snapshot = configure(preferences)
    assert snapshot.policy.revision == 2 and snapshot.policy.enabled and snapshot.associated
    assert not snapshot.policy.phone_to_pc_delete and not snapshot.policy.pc_to_phone_delete
    assert snapshot.destination_available and snapshot.policy.destination.path == str(target)
    assert prefs.read() == snapshot
    assert prefs.local_grant(True).grants.receive_files
    assert not prefs.local_grant(True).grants.send_files
    assert not prefs.local_grant(False).grants.receive_files
    database = Path(service.store.root) / prefs._name / 'prefs.sqlite'
    assert str(target).encode() not in database.read_bytes()
    prefs.close()
    reopened = ProtectedPhotoPreferences(authority)
    try:
        assert reopened.read() == snapshot
    finally:
        reopened.close()


def test_stale_snapshot_and_replayed_native_action_cannot_overwrite_policy(preferences):
    _, _, prefs, _, _, _ = preferences
    absent = prefs.read(); current = configure(preferences)
    action = prefs.issue_action()
    with pytest.raises(TransferError, match='cas_conflict'):
        prefs.configure(action, absent, enabled=False, mode='automatic')
    with pytest.raises(TransferError, match='action_not_current'):
        prefs.configure(action, current, enabled=False, mode='manual')
    assert prefs.read() == current


@pytest.mark.parametrize('settings', [dict(pc_to_phone_delete=True), dict(enabled=True)])
def test_unsupported_reverse_delete_and_missing_destination_do_not_create_store(preferences, settings):
    service, _, prefs, _, _, _ = preferences
    arguments = dict(enabled=False, mode='manual'); arguments.update(settings)
    with pytest.raises(TransferError):
        prefs.configure(prefs.issue_action(), prefs.read(), **arguments)
    assert not (Path(service.store.root) / prefs._name).exists()


def test_same_key_new_pairing_keeps_old_policy_unassociated_and_off(preferences):
    service, authority, prefs, _, _, _ = preferences
    saved = configure(preferences)
    peer = service.store.peers[0]
    peer['file_pairing_epoch'] = phone.native_file_pairing_epoch(bytes([9])*32)
    service.store.save_peers()
    channel, binding = bind(service, peer)
    replacement = service.open_native_file_authority(peer['device_id'], peer['static_public'], channel, binding.generation)
    new = ProtectedPhotoPreferences(replacement)
    try:
        observed = new.read()
        assert observed.policy == saved.policy and not observed.associated
        assert not new.local_grant(True).grants.receive_files
        assert new.local_grant(True).grants.epoch != saved.policy.permission_epoch
    finally:
        new.close(); replacement.close()


@pytest.mark.parametrize('failure', ['crypto', 'expiry'])
def test_failure_before_transaction_preserves_existing_record(preferences, monkeypatch, failure):
    _, authority, prefs, _, _, clock = preferences
    saved = configure(preferences)
    seal = authority.protection.seal
    def failed(*args):
        if failure == 'crypto':
            raise OSError('synthetic existing-key encryption failure')
        result = seal(*args); clock[0] += 60_000; return result
    monkeypatch.setattr(authority.protection, 'seal', failed)
    with pytest.raises((OSError, TransferError)):
        prefs.configure(prefs.issue_action(), saved, enabled=False, mode='automatic')
    monkeypatch.setattr(authority.protection, 'seal', seal)
    assert prefs.read() == saved


@pytest.mark.parametrize('damage', ['owner', 'policy', 'schema', 'root', 'lock', 'unknown'])
def test_corrupt_or_missing_native_metadata_is_preserved_without_reset(preferences, damage):
    service, authority, prefs, _, _, _ = preferences
    configure(preferences)
    root = Path(service.store.root) / prefs._name
    prefs.close()
    if damage in ('owner', 'policy', 'schema'):
        with sqlite3.connect(root / 'prefs.sqlite') as db:
            if damage == 'schema': db.execute('CREATE TABLE foreign_record (value TEXT)')
            else: db.execute('DELETE FROM ' + damage)
    elif damage == 'root': root.chmod(0o755)
    elif damage == 'lock': (root / 'prefs.lock').unlink()
    else: (root / 'unknown-record').write_bytes(b'preserve me')
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    reopened = ProtectedPhotoPreferences(authority)
    try:
        with pytest.raises((OSError, TransferError)): reopened.read()
        with pytest.raises(TransferError): reopened.local_grant(True)
        assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    finally:
        reopened.close()


def test_nonwaiting_native_lock_retry_closes_partial_descriptors(preferences):
    service, authority, prefs, _, _, _ = preferences
    saved = configure(preferences)
    root = Path(service.store.root) / prefs._name
    second = ProtectedPhotoPreferences(authority)
    fd = os.open(root / 'prefs.lock', os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TransferError, match='busy'): second.read()
        assert all(getattr(second, name) is None for name in ('_db', '_parent_fd', '_root_fd', '_db_fd', '_lock_fd'))
        fcntl.flock(fd, fcntl.LOCK_UN)
        assert second.read() == saved
    finally:
        os.close(fd); second.close()


def test_close_during_blocked_seal_revokes_immediately_and_retains_handles_until_io_end(preferences, monkeypatch):
    _, authority, prefs, _, _, _ = preferences
    saved = configure(preferences)
    entered = threading.Event(); release = threading.Event(); ended = threading.Event(); errors = []; results = []
    seal = authority.protection.seal
    def blocked(*args):
        entered.set(); assert release.wait(5)
        return seal(*args)
    monkeypatch.setattr(authority.protection, 'seal', blocked)
    def write():
        try: results.append(prefs.configure(prefs.issue_action(), saved, enabled=False, mode='manual'))
        except Exception as error: errors.append(error)
        finally: ended.set()
    worker = threading.Thread(target=write); worker.start()
    try:
        assert entered.wait(5)
        held = prefs._db_fd
        assert not prefs.close() and prefs._db_fd == held
        with pytest.raises(TransferError): prefs.local_grant(True)
        assert os.fstat(held).st_ino > 0 and not ended.is_set()
        release.set(); assert ended.wait(5); worker.join(5)
        assert not results and len(errors) == 1 and isinstance(errors[0], TransferError)
        assert prefs._db_fd is None
        reopened = ProtectedPhotoPreferences(authority)
        try: assert reopened.read() == saved
        finally: reopened.close()
    finally:
        release.set(); worker.join(5)
        assert not worker.is_alive()


def test_lost_destination_closes_grant_but_does_not_prevent_explicit_disable(preferences):
    _, _, prefs, _, target, _ = preferences
    saved = configure(preferences)
    target.rename(target.with_name('held-native-folder'))
    assert not prefs.local_grant(True).grants.receive_files
    disabled = prefs.configure(prefs.issue_action(), saved, enabled=False, mode='manual')
    assert not disabled.policy.enabled and not disabled.destination_available
    assert disabled.policy.destination == saved.policy.destination


def test_competing_transaction_is_busy_not_corrupt_and_retry_keeps_original_record(preferences):
    _, authority, prefs, _, _, _ = preferences
    saved = configure(preferences)
    other = ProtectedPhotoPreferences(authority)
    try:
        with prefs._operation(), prefs._locked():
            prefs._db.execute('BEGIN IMMEDIATE')
            prefs._db.execute('UPDATE owner SET payload=payload WHERE id=1')
            try:
                with pytest.raises(TransferError, match='busy'): other.read()
                assert not other._uncertain
            finally: prefs._db.rollback()
        assert other.read() == saved
    finally: other.close()


@pytest.mark.parametrize('failure', ['expired', 'durability'])
def test_transaction_failure_never_reports_success_and_requires_fresh_readback(preferences, monkeypatch, failure):
    _, authority, prefs, _, _, clock = preferences
    saved = configure(preferences)
    if failure == 'expired':
        fresh = prefs._fresh
        def expire_in_transaction():
            fresh()
            if prefs._db.in_transaction: clock[0] += 60_000
        monkeypatch.setattr(prefs, '_fresh', expire_in_transaction)
    else:
        def fail_sync(): raise OSError('synthetic post-commit durability failure')
        monkeypatch.setattr(prefs, '_sync', fail_sync)
    with pytest.raises((TransferError, OSError)):
        prefs.configure(prefs.issue_action(), saved, enabled=False, mode='manual')
    assert prefs._uncertain
    with pytest.raises(TransferError): prefs.local_grant(True)
    prefs.close()
    reopened = ProtectedPhotoPreferences(authority)
    try:
        observed = reopened.read()
        if failure == 'expired': assert observed == saved
        else:
            assert observed.policy.revision == saved.policy.revision + 1
            assert not observed.policy.enabled
    finally: reopened.close()


def test_failed_initial_encryption_preserves_incomplete_store_without_default_reset(preferences, monkeypatch):
    service, authority, prefs, _, _, _ = preferences
    seal = authority.protection.seal
    def fail(*args): raise OSError('synthetic initial header encryption failure')
    monkeypatch.setattr(authority.protection, 'seal', fail)
    with pytest.raises(OSError): configure(preferences)
    root = Path(service.store.root) / prefs._name
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    monkeypatch.setattr(authority.protection, 'seal', seal)
    prefs.close()
    reopened = ProtectedPhotoPreferences(authority)
    try:
        with pytest.raises(TransferError): reopened.read()
        assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    finally: reopened.close()


def test_missing_existing_storage_key_cannot_create_policy_or_replacement_key(preferences):
    service, _, prefs, _, _, _ = preferences
    key = Path(service.store.storage_path); held = key.with_name('held-existing-key')
    key.rename(held)
    try:
        with pytest.raises((OSError, TransferError)): prefs.read()
        assert not key.exists() and not (Path(service.store.root) / prefs._name).exists()
    finally: held.rename(key)


@pytest.mark.parametrize('mutation', ['cipher', 'schema', 'rollback'])
def test_live_record_corruption_or_revision_rollback_fails_closed(preferences, mutation):
    _, _, prefs, _, _, _ = preferences
    saved = configure(preferences)
    old_owner = prefs._db.execute('SELECT payload FROM owner').fetchone()[0]
    old_policy = prefs._db.execute('SELECT payload FROM policy').fetchone()[0]
    if mutation == 'rollback':
        prefs.configure(prefs.issue_action(), saved, enabled=False, mode='manual')
        with prefs._db:
            prefs._db.execute('UPDATE owner SET payload=?', (old_owner,))
            prefs._db.execute('UPDATE policy SET payload=?', (old_policy,))
    elif mutation == 'cipher':
        with prefs._db: prefs._db.execute('UPDATE policy SET payload=?', (old_policy[:-1]+bytes([old_policy[-1]^1]),))
    else:
        with prefs._db: prefs._db.execute('CREATE TABLE unexpected (value TEXT)')
    with pytest.raises((TransferError, InvalidTag)): prefs.read()
    assert prefs._uncertain
    with pytest.raises(TransferError): prefs.local_grant(True)
