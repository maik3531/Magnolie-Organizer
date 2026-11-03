"""Own-camera folder choice is metadata, never camera-origin evidence."""
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


def test_legacy_and_absent_settings_keep_camera_separation_off_without_a_store_migration(preferences):
    service,_,prefs,_,_,_=preferences
    assert not prefs.read().separate_own_recordings
    assert not (Path(service.store.root)/prefs._name).exists()
    photo=configure(preferences)
    blob=prefs._db.execute('SELECT payload FROM policy').fetchone()[0]
    assert photo.policy.separate_own_recordings is None and not photo.separate_own_recordings
    assert 'separate_own_recordings' not in photo.policy.wire()
    assert PhotoPreferences.parse(photo.policy.wire()).wire()==photo.policy.wire()
    assert prefs.read()==photo and prefs._db.execute('SELECT payload FROM policy').fetchone()[0]==blob


def test_camera_choice_does_not_enable_videos_create_folders_or_claim_source_provenance(preferences):
    _,_,prefs,_,target,_=preferences
    photo=configure(preferences)
    original=target/'existing.jpg';original.write_bytes(b'original PC edit');inode=original.stat().st_ino
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_own_recordings=True)
    assert saved.separate_own_recordings and not saved.include_videos and not saved.separate_animations
    assert saved.policy.destination==photo.policy.destination
    assert not hasattr(saved.policy,'camera_origin_proven')
    assert not (target/'Eigene Aufnahmen').exists() and original.stat().st_ino==inode
    assert original.read_bytes()==b'original PC edit'
    assert not prefs.local_grant(False).grants.receive_files


def test_own_camera_selection_applies_to_both_requested_media_without_replacing_either_root(preferences,videos):
    _,authority,prefs,_,target,_=preferences
    photo=configure(preferences)
    both=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',include_videos=True,
        video_destination_choice=choice(videos),separate_animations=True,separate_own_recordings=True)
    assert both.include_videos and both.separate_animations and both.separate_own_recordings
    assert both.policy.destination==photo.policy.destination and both.policy.videos.destination.path==str(videos[1])
    assert not (target/'Eigene Aufnahmen').exists() and not (videos[1]/'Eigene Aufnahmen').exists()
    off=prefs.configure(prefs.issue_action(),both,enabled=True,mode='manual',separate_own_recordings=False)
    assert not off.separate_own_recordings and off.include_videos and off.separate_animations
    assert off.policy.videos==both.policy.videos and off.policy.destination==both.policy.destination
    prefs.close();reopened=ProtectedPhotoPreferences(authority)
    try:assert reopened.read()==off
    finally:reopened.close()


@pytest.mark.parametrize('value',[1,0,'true',[],{}])
def test_non_boolean_camera_selection_cannot_create_a_policy(preferences,value):
    service,_,prefs,_,_,_=preferences
    with pytest.raises(TransferError,match='capture_preferences_invalid_settings'):
        prefs.configure(prefs.issue_action(),prefs.read(),enabled=False,mode='manual',separate_own_recordings=value)
    assert not (Path(service.store.root)/prefs._name).exists()


@pytest.mark.parametrize('value',[None,1,'true',{},[]])
def test_corrupt_camera_setting_cannot_be_accepted_as_default_or_provenance(preferences,value):
    saved=configure(preferences);wire=saved.policy.wire();wire['separate_own_recordings']=value
    with pytest.raises(TransferError):PhotoPreferences.parse(wire)
    assert preferences[2].read()==saved


def test_stale_camera_option_cannot_overwrite_a_later_photo_update(preferences):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    updated=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='automatic')
    with pytest.raises(TransferError,match='cas_conflict'):
        prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_own_recordings=True)
    assert prefs.read()==updated and not updated.separate_own_recordings


def test_repairing_preserves_folder_metadata_without_renewing_camera_routing_selection(preferences):
    service,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_own_recordings=True)
    peer=service.store.peers[0]
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([5])*32)
    service.store.save_peers();channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    replacement=ProtectedPhotoPreferences(authority)
    try:
        old=replacement.read()
        assert old.policy==saved.policy and not old.associated and not old.separate_own_recordings
        accepted=replacement.configure(replacement.issue_action(),old,enabled=True,mode='manual')
        assert accepted.associated and not accepted.separate_own_recordings
        assert accepted.policy.destination==saved.policy.destination
    finally:replacement.close();authority.close()
