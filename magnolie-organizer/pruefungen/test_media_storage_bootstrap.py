"""Joint native root binding is explicit, atomic and never enables transfers."""
from dataclasses import replace
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_storage_bootstrap import NativeMediaStorageBootstrap
from magnolie_photo_preferences import ProtectedPhotoPreferences
from magnolie_photo_mappings import ProtectedPhotoMappings
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving,negotiate,reconnect


def unchanged_settings(before,after):
    assert replace(after.policy,revision=before.policy.revision,permission_epoch=before.policy.permission_epoch,
        mapping_store=before.policy.mapping_store,job_catalog=before.policy.job_catalog)==before.policy


def test_first_explicit_bootstrap_binds_both_roots_but_keeps_disabled_manual_phone_only_defaults(native):
    service,peer,_=native;channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    prefs=ProtectedPhotoPreferences(authority);controller=NativeMediaStorageBootstrap(authority)
    try:
        expected=prefs.read();assert expected.policy is None
        result=controller.prepare(controller.issue_action(),expected)
        assert result.policy.mapping_store is not None and result.policy.job_catalog is not None
        assert not result.policy.enabled and result.policy.mode=='manual' and result.direction=='phone_to_desktop'
        assert not result.policy.phone_to_pc_delete and not result.policy.pc_to_phone_delete
        assert result.policy.destination is None and not channel.send.call_count
        assert prefs.read()==result
    finally:controller.close();prefs.close();authority.close()


def test_joint_binding_preserves_existing_settings_targets_and_persistent_choices(receiving):
    connection=receiving[3];prefs=connection._preferences
    expected=prefs.configure(prefs.issue_action(),prefs.read(),enabled=False,mode='automatic',phone_to_pc_delete=True,
        separate_animations=True,separate_own_recordings=True,direction='bidirectional')
    controller=NativeMediaStorageBootstrap(connection._authority)
    try:
        result=controller.prepare(controller.issue_action(),expected);unchanged_settings(expected,result)
        assert result.policy.mapping_store is not None and result.policy.job_catalog is not None
        again=controller.prepare(controller.issue_action(),result);unchanged_settings(result,again)
        assert again.policy.mapping_store==result.policy.mapping_store and again.policy.job_catalog==result.policy.job_catalog
        assert not list(receiving[4].iterdir()) and not receiving[2].send.call_count
    finally:controller.close()


def test_joint_bound_roots_support_actual_native_save_and_fresh_receipt_only_recovery(receiving):
    from test_photo_mappings import save
    connection=receiving[3];controller=NativeMediaStorageBootstrap(connection._authority)
    try:bound=controller.prepare(controller.issue_action(),connection._preferences.read())
    finally:controller.close()
    negotiate(*receiving[:4]) # Fresh explicit control agreement after policy epoch changes.
    receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());original=receiver._index.saved_mapping_receipt()
    assert original.store.witness==bound.policy.mapping_store and len(connection._catalog.jobs())==1
    with reconnect(receiving) as fresh:
        reopened=fresh[3]
        assert reopened.read_preferences()==bound
        assert reopened.recover_saved_confirmation(reopened.issue_receive_action(),receiver.job.owner)==original
        assert len(reopened._catalog.jobs())==1 and reopened._run is None


@pytest.mark.parametrize('which',['mapping','catalog'])
def test_expected_missing_root_is_not_recreated_or_bound_to_new_defaults(receiving,which):
    connection=receiving[3];controller=NativeMediaStorageBootstrap(connection._authority)
    try:
        saved=controller.prepare(controller.issue_action(),connection._preferences.read())
        parent=Path(connection._authority.binding.native_directory)
        if which=='catalog':root=parent/ProtectedTransferJobCatalog.NAME
        else:
            observer=ProtectedPhotoMappings(connection._authority)
            try:root=parent/observer._name
            finally:observer.close()
        held=root.with_name(root.name+'-held-original');root.rename(held)
        try:
            with pytest.raises((TransferError,OSError)):controller.prepare(controller.issue_action(),saved)
            assert not root.exists() and held.is_dir() and connection._preferences.read()==saved
        finally:held.rename(root)
        assert not receiving[2].send.call_count and not list(receiving[4].iterdir())
    finally:controller.close()


def test_stale_preferences_stop_before_creating_storage_or_sending(receiving):
    connection=receiving[3];prefs=connection._preferences;expected=prefs.read()
    prefs.configure(prefs.issue_action(),expected,enabled=False,mode='manual')
    controller=NativeMediaStorageBootstrap(connection._authority);parent=Path(connection._authority.binding.native_directory)
    before={entry.name for entry in parent.iterdir()}
    try:
        with pytest.raises(TransferError,match='preferences_changed'):controller.prepare(controller.issue_action(),expected)
        assert {entry.name for entry in parent.iterdir()}==before and not receiving[2].send.call_count
    finally:controller.close()


@pytest.mark.parametrize('which',['mapping','catalog'])
def test_valid_replacement_root_cannot_replace_previously_bound_original(receiving,which):
    connection=receiving[3];authority=connection._authority;controller=NativeMediaStorageBootstrap(authority)
    held=None
    try:
        saved=controller.prepare(controller.issue_action(),connection._preferences.read())
        parent=Path(authority.binding.native_directory)
        if which=='mapping':
            replacement=ProtectedPhotoMappings(authority);root=parent/replacement._name
            held=root.with_name(root.name+'-held-original');root.rename(held)
            try:replacement.bootstrap(replacement.issue_action(),replacement.read())
            finally:replacement.close()
        else:
            root=parent/ProtectedTransferJobCatalog.NAME;held=root.with_name(root.name+'-held-original');root.rename(held)
            protection=authority.protection
            with ProtectedTransferJobCatalog(parent,authority.identity,protection.seal,protection.unseal,create=True):pass
        before={entry.name:entry.read_bytes() for entry in root.iterdir() if entry.is_file()}
        with pytest.raises(TransferError):controller.prepare(controller.issue_action(),saved)
        assert held.is_dir() and root.is_dir() and connection._preferences.read()==saved
        assert {entry.name:entry.read_bytes() for entry in root.iterdir() if entry.is_file()}==before
        assert not receiving[2].send.call_count
    finally:controller.close() # Both fixture roots intentionally preserved; no replacement/reset.


def test_original_bounded_action_is_not_renewed_by_subactions(receiving,monkeypatch):
    connection=receiving[3];clock=[1000];controller=NativeMediaStorageBootstrap(connection._authority,monotonic_ms=lambda:clock[0])
    prefs=connection._preferences;before=prefs.read();bootstrap=ProtectedPhotoMappings.bootstrap
    def expired(owner,*args,**kwargs):
        result=bootstrap(owner,*args,**kwargs);clock[0]+=60_000;return result
    monkeypatch.setattr(ProtectedPhotoMappings,'bootstrap',expired)
    try:
        with pytest.raises(TransferError,match='action_not_current'):controller.prepare(controller.issue_action(),before)
        assert prefs.read()==before and not receiving[2].send.call_count
        assert (Path(connection._authority.binding.native_directory)/ProtectedTransferJobCatalog.NAME).is_dir()
    finally:controller.close()


def test_joint_sql_failure_keeps_both_roots_unbound_and_retry_reuses_originals(receiving,monkeypatch):
    import sqlite3
    connection=receiving[3];before=connection._preferences.read();protect=ProtectedPhotoPreferences._protect
    def interrupted(owner,value,label):
        blob=protect(owner,value,label)
        if type(owner) is ProtectedPhotoPreferences and label=='policy' and value.get('mapping_store') is not None:
            owner._db.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and args[0]=='owner' else sqlite3.SQLITE_OK)
        return blob
    monkeypatch.setattr(ProtectedPhotoPreferences,'_protect',interrupted)
    controller=NativeMediaStorageBootstrap(connection._authority)
    try:
        with pytest.raises(sqlite3.DatabaseError):controller.prepare(controller.issue_action(),before)
        assert connection._preferences.read()==before
        parent=Path(connection._authority.binding.native_directory)
        roots={entry.name:entry.stat().st_ino for entry in parent.iterdir() if entry.is_dir()}
        assert ProtectedTransferJobCatalog.NAME in roots
        monkeypatch.setattr(ProtectedPhotoPreferences,'_protect',protect)
        result=controller.prepare(controller.issue_action(),before)
        assert {entry.name:entry.stat().st_ino for entry in parent.iterdir() if entry.is_dir()}==roots
        unchanged_settings(before,result)
        assert not receiving[2].send.call_count and not list(receiving[4].iterdir())
    finally:controller.close()


def test_lost_joint_postcommit_sync_reports_no_success_fresh_read_has_both_original_bindings(receiving,monkeypatch):
    connection=receiving[3];expected=connection._preferences.read();protect=ProtectedPhotoPreferences._protect
    sync=ProtectedPhotoPreferences._sync;marked=set()
    def observe(owner,value,label):
        blob=protect(owner,value,label)
        if type(owner) is ProtectedPhotoPreferences and label=='policy' and value.get('mapping_store') is not None:marked.add(id(owner))
        return blob
    def lost(owner):
        if id(owner) in marked:raise OSError('fixture joint postcommit sync lost')
        return sync(owner)
    monkeypatch.setattr(ProtectedPhotoPreferences,'_protect',observe);monkeypatch.setattr(ProtectedPhotoPreferences,'_sync',lost)
    controller=NativeMediaStorageBootstrap(connection._authority)
    try:
        with pytest.raises(OSError,match='postcommit'):controller.prepare(controller.issue_action(),expected)
        monkeypatch.setattr(ProtectedPhotoPreferences,'_sync',sync)
        reader=ProtectedPhotoPreferences(connection._authority)
        try:
            actual=reader.read();assert actual.policy.mapping_store is not None and actual.policy.job_catalog is not None
            unchanged_settings(expected,actual)
        finally:reader.close()
        assert not receiving[2].send.call_count
    finally:controller.close()


def test_legacy_catalog_is_preserved_without_mapping_creation_or_implicit_inventory_adoption(receiving):
    connection=receiving[3];authority=connection._authority;protection=authority.protection
    parent=Path(authority.binding.native_directory)
    with ProtectedTransferJobCatalog(parent,authority.identity,protection.seal,protection.unseal,create=True) as catalog:
        root=parent/catalog.NAME;path=root/'owner.enc';domain=catalog._domain
        value=json.loads(protection.unseal(path.read_bytes(),domain+'owner.enc'))
        value['payload']['format']=1;del value['payload']['registry_key']
        legacy=protection.seal(catalog._json(value),domain+'owner.enc')
    path.write_bytes(legacy);database=root/'membership.sqlite';held=parent/'held-original-membership.sqlite';database.rename(held)
    controller=NativeMediaStorageBootstrap(authority);prefs=connection._preferences;expected=prefs.read()
    before={entry.name:entry.read_bytes() for entry in root.iterdir()}
    try:
        with pytest.raises(TransferError,match='legacy_membership_upgrade_required'):controller.prepare(controller.issue_action(),expected)
        assert {entry.name:entry.read_bytes() for entry in root.iterdir()}==before and prefs.read()==expected
        assert not list(parent.glob('photo-mappings-v1-*')) and not receiving[2].send.call_count
    finally:controller.close();held.rename(database)


@pytest.mark.parametrize('operation',['close','revoke'])
def test_close_or_revocation_after_roots_prepare_cannot_bind_preferences(receiving,monkeypatch,operation):
    connection=receiving[3];controller=NativeMediaStorageBootstrap(connection._authority)
    expected=connection._preferences.read();bootstrap=ProtectedPhotoMappings.bootstrap
    original=connection._preferences._db.execute('SELECT payload FROM policy').fetchone()[0]
    def stop(owner,*args,**kwargs):
        result=bootstrap(owner,*args,**kwargs)
        if operation=='close':controller.close()
        else:connection._authority.revoke()
        return result
    monkeypatch.setattr(ProtectedPhotoMappings,'bootstrap',stop)
    try:
        with pytest.raises(TransferError):controller.prepare(controller.issue_action(),expected)
        assert not receiving[2].send.call_count and not list(receiving[4].iterdir())
        if operation=='close':assert connection._preferences.read()==expected
        else:
            assert connection._preferences._db.execute('SELECT payload FROM policy').fetchone()[0]==original
    finally:controller.close()
