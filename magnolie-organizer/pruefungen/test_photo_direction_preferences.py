"""Direction choices do not create unsupported PC→phone send/write authority."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_preferences import PhotoPreferences,ProtectedPhotoPreferences
from test_photo_preferences import preferences,configure
from test_video_preferences import videos,choice
from test_file_authenticated_desktop import native,bind
import magnolie_telefon as phone


def test_absent_and_legacy_direction_default_to_phone_only_without_passive_migration(preferences):
    service,_,prefs,_,_,_=preferences
    assert prefs.read().direction=='phone_to_desktop'
    assert not (Path(service.store.root)/prefs._name).exists()
    saved=configure(preferences)
    blob=prefs._db.execute('SELECT payload FROM policy').fetchone()[0]
    assert saved.direction=='phone_to_desktop' and saved.policy.direction is None and 'direction' not in saved.policy.wire()
    assert PhotoPreferences.parse(saved.policy.wire()).wire()==saved.policy.wire()
    assert prefs.read()==saved and prefs._db.execute('SELECT payload FROM policy').fetchone()[0]==blob


def test_explicit_direction_is_encrypted_cas_metadata_not_reverse_grant_or_delete_permission(preferences):
    service,authority,prefs,_,target,_=preferences
    photo=configure(preferences)
    both=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',direction='bidirectional')
    assert both.direction=='bidirectional' and both.policy.destination==photo.policy.destination
    assert not both.include_videos and not both.policy.phone_to_pc_delete and not both.policy.pc_to_phone_delete
    for ready in (False,True):
        assert not prefs.local_grant(ready).grants.send_files and not prefs.local_grant(ready).grants.receive_files
    assert b'bidirectional' not in (Path(service.store.root)/prefs._name/'prefs.sqlite').read_bytes()
    with pytest.raises(TransferError,match='cas_conflict'):
        prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',direction='phone_to_desktop')
    prefs.close();reopened=ProtectedPhotoPreferences(authority)
    try:assert reopened.read()==both
    finally:reopened.close()
    assert not list(target.iterdir())


def test_direction_updates_keep_video_animation_recording_settings_and_both_destinations_independent(preferences,videos):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    all_options=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=True,
        video_destination_choice=choice(videos),separate_animations=True,separate_own_recordings=True,direction='bidirectional')
    only=prefs.configure(prefs.issue_action(),all_options,enabled=True,mode='manual',direction='phone_to_desktop')
    assert only.direction=='phone_to_desktop' and only.include_videos and only.separate_animations and only.separate_own_recordings
    assert only.policy.videos==all_options.policy.videos and only.policy.destination==all_options.policy.destination
    changed=prefs.configure(prefs.issue_action(),only,enabled=True,mode='automatic')
    assert changed.direction=='phone_to_desktop'


@pytest.mark.parametrize('value',[True,1,'two_way','desktop_to_phone',[],{}])
def test_unknown_or_non_string_direction_is_rejected_without_store_creation(preferences,value):
    service,_,prefs,_,_,_=preferences
    with pytest.raises(TransferError,match='invalid_direction'):
        prefs.configure(prefs.issue_action(),prefs.read(),enabled=False,mode='manual',direction=value)
    assert not (Path(service.store.root)/prefs._name).exists()


@pytest.mark.parametrize('value',[None,True,1,'two_way',{},[]])
def test_corrupt_persisted_direction_is_not_normalized_to_a_grant_or_default(preferences,value):
    photo=configure(preferences);wire=photo.policy.wire();wire['direction']=value
    with pytest.raises(TransferError):PhotoPreferences.parse(wire)
    assert preferences[2].read()==photo


def test_new_pairing_never_renews_previous_bidirectional_choice_implicitly(preferences):
    service,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',direction='bidirectional')
    peer=service.store.peers[0];peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([3])*32)
    service.store.save_peers();channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    replacement=ProtectedPhotoPreferences(authority)
    try:
        old=replacement.read()
        assert old.policy==saved.policy and old.direction=='phone_to_desktop'
        accepted=replacement.configure(replacement.issue_action(),old,enabled=True,mode='manual')
        assert accepted.associated and accepted.direction=='phone_to_desktop'
        assert not replacement.local_grant(True).grants.send_files
    finally:replacement.close();authority.close()
