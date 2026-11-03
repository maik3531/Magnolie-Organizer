"""Explicit expected-store anchoring, never an absent-store reset."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_mappings import ProtectedPhotoMappings
from magnolie_photo_mapping_witness import PhotoMappingStoreWitness
from magnolie_photo_preferences import ProtectedPhotoPreferences,PhotoPreferences
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_photo_preferences import preferences,configure


@pytest.fixture
def anchored(preferences):
    prefs=preferences[2];photo=configure(preferences)
    owner=ProtectedPhotoMappings(preferences[1])
    try:
        choice=owner.bootstrap(owner.issue_action(),owner.read())
        saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',mapping_store_choice=choice)
        yield preferences,owner,choice,saved
    finally:owner.close()


def test_explicit_bootstrap_and_encrypted_policy_reopen_keep_original_store_witness(anchored):
    fixture,owner,choice,saved=anchored
    witness=choice.witness
    assert saved.policy.mapping_store==witness and not witness.grants_write_authority
    assert owner.verify_witness(witness)==witness and owner.read().count==0
    data=(Path(fixture[0].store.root)/fixture[2]._name/'prefs.sqlite').read_bytes()
    assert witness.scope.encode() not in data
    reopened=ProtectedPhotoPreferences(fixture[1])
    try:
        assert reopened.read()==saved
        updated=reopened.configure(reopened.issue_action(),saved,enabled=False,mode='manual')
        assert updated.policy.mapping_store==witness
    finally:reopened.close()
    assert not list(fixture[4].iterdir())


def test_passive_absent_store_and_legacy_preferences_do_not_create_or_infer_witness(preferences):
    photo=configure(preferences);owner=ProtectedPhotoMappings(preferences[1])
    try:
        assert owner.read().revision==0 and photo.policy.mapping_store is None
        assert 'mapping_store' not in photo.policy.wire()
        assert PhotoPreferences.parse(photo.policy.wire()).wire()==photo.policy.wire()
        assert not (Path(preferences[0].store.root)/owner._name).exists()
    finally:owner.close()


@pytest.mark.parametrize('missing',['root','prefs.sqlite','prefs.lock'])
def test_expected_missing_original_after_reopen_stays_missing_and_never_bootstraps_empty_defaults(anchored,missing):
    fixture,owner,choice,saved=anchored
    root=Path(fixture[0].store.root)/owner._name
    original=root if missing=='root' else root/missing
    held=original.with_name(original.name+'-held-original')
    expected=owner.read()
    owner.close();original.rename(held)
    reopened=ProtectedPhotoMappings(fixture[1])
    try:
        with pytest.raises((TransferError,OSError)):reopened.verify_witness(saved.policy.mapping_store)
        assert not original.exists() and held.exists() and reopened._uncertain
        with pytest.raises(TransferError):reopened.bootstrap(reopened.issue_action(),expected)
        assert not original.exists() and held.exists()
    finally:
        reopened.close();held.rename(original)


def test_existing_policy_cannot_be_rebound_to_new_empty_store_after_original_is_displaced(anchored):
    fixture,owner,choice,saved=anchored
    root=Path(fixture[0].store.root)/owner._name;held=root.with_name(root.name+'-held-original')
    owner.close();root.rename(held)
    replacement=ProtectedPhotoMappings(fixture[1])
    try:
        new_choice=replacement.bootstrap(replacement.issue_action(),replacement.read())
        assert new_choice.witness!=choice.witness
        prefs=fixture[2]
        with pytest.raises(TransferError,match='original_mapping_store_required'):
            prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',mapping_store_choice=new_choice)
        assert prefs.read()==saved and held.is_dir()
    finally:replacement.close()
    # Both original and explicitly created orphan are preserved, never removed
    # or substituted by production code. The isolated fixture owns their cleanup.


def test_wrong_wire_choice_and_malformed_persisted_witness_do_not_change_policy(anchored):
    fixture,owner,choice,saved=anchored;prefs=fixture[2]
    with pytest.raises(TransferError,match='foreign_mapping_store_choice'):
        prefs.configure(prefs.issue_action(),saved,enabled=True,mode='manual',mapping_store_choice=choice.witness.wire())
    variants=[None,True,{},dict(choice.witness.wire(),scope='not-a-scope')]
    for value in variants:
        wire=saved.policy.wire();wire['mapping_store']=value
        with pytest.raises(TransferError):PhotoPreferences.parse(wire)
    for key in ('root_key','database_key','lock_key'):
        wire=deepcopy(choice.witness.wire());wire[key][1]=True
        with pytest.raises(TransferError):PhotoMappingStoreWitness.parse(wire)
    assert prefs.read()==saved


def test_corrupt_expected_store_metadata_is_preserved_and_fenced(anchored):
    fixture,owner,choice,saved=anchored
    blob=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
    broken=blob[:-1]+bytes([blob[-1]^1])
    with owner._db:owner._db.execute('UPDATE owner SET payload=?',(broken,))
    with pytest.raises((TransferError,InvalidTag)):owner.verify_witness(choice.witness)
    assert owner._uncertain and owner._db.execute('SELECT payload FROM owner').fetchone()[0]==broken
    assert fixture[2].read()==saved


@pytest.mark.parametrize('failure_call',[2,3])
def test_bootstrap_store_loss_during_policy_commit_or_readback_never_returns_success(preferences,monkeypatch,failure_call):
    prefs=preferences[2];photo=configure(preferences);owner=ProtectedPhotoMappings(preferences[1])
    choice=owner.bootstrap(owner.issue_action(),owner.read())
    root=Path(preferences[0].store.root)/owner._name;held=root.with_name(root.name+'-held-original')
    verify=owner.verify_choice;calls=[]
    def interrupted(value):
        calls.append(1)
        if len(calls)==failure_call:root.rename(held)
        return verify(value)
    monkeypatch.setattr(owner,'verify_choice',interrupted)
    try:
        with pytest.raises((TransferError,OSError)):
            prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',mapping_store_choice=choice)
        assert prefs._uncertain and not root.exists() and held.is_dir()
        reopened=ProtectedPhotoPreferences(preferences[1])
        try:
            recovered=reopened.read()
            if failure_call==2:assert recovered==photo
            else:assert recovered.policy.mapping_store==choice.witness
        finally:reopened.close()
        assert not list(preferences[4].iterdir())
    finally:
        owner.close()
        if held.exists():held.rename(root)
