"""Optional photo-side animation routing metadata, never moves existing files."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_preferences import ProtectedPhotoPreferences, PhotoPreferences
from magnolie_file_transfer import TransferError
from test_photo_preferences import preferences,configure
from test_file_authenticated_desktop import native,bind
from test_video_preferences import videos,choice
import magnolie_telefon as phone


def test_old_and_absent_photo_records_keep_animation_option_off_without_passive_migration(preferences):
    service,_,prefs,_,_,_=preferences
    assert not prefs.read().separate_animations
    assert not (Path(service.store.root)/prefs._name).exists()
    saved=configure(preferences)
    blob=prefs._db.execute('SELECT payload FROM policy').fetchone()[0]
    assert saved.policy.separate_animations is None and not saved.separate_animations
    assert 'separate_animations' not in saved.policy.wire()
    assert PhotoPreferences.parse(saved.policy.wire()).wire()==saved.policy.wire()
    assert prefs.read()==saved and prefs._db.execute('SELECT payload FROM policy').fetchone()[0]==blob


def test_explicit_animation_option_is_photo_side_encrypted_metadata_and_never_moves_existing_gif(preferences):
    service,authority,prefs,_,target,_=preferences
    photo=configure(preferences)
    gif=target/'old-animation.gif';gif.write_bytes(b'GIF89a-existing-user-fixture');inode=gif.stat().st_ino
    enabled=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_animations=True)
    assert enabled.separate_animations and not enabled.include_videos
    assert enabled.policy.destination==photo.policy.destination and enabled.policy.destination_token==photo.policy.destination_token
    assert enabled.policy.videos is None and not prefs.local_grant(False).grants.receive_files
    assert gif.stat().st_ino==inode and gif.read_bytes()==b'GIF89a-existing-user-fixture'
    assert not (target/'Animationen').exists()
    assert b'separate_animations' not in (Path(service.store.root)/prefs._name/'prefs.sqlite').read_bytes()
    prefs.close();restored=ProtectedPhotoPreferences(authority)
    try:assert restored.read()==enabled
    finally:restored.close()


def test_animation_video_and_photo_changes_preserve_independent_selections_and_targets(preferences,videos):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    both=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_animations=True,
        include_videos=True,video_destination_choice=choice(videos))
    assert both.separate_animations and both.include_videos
    video_off=prefs.configure(prefs.issue_action(),both,enabled=True,mode='manual',include_videos=False)
    assert video_off.separate_animations and not video_off.include_videos
    assert video_off.policy.videos.destination==both.policy.videos.destination
    animation_off=prefs.configure(prefs.issue_action(),video_off,enabled=True,mode='manual',separate_animations=False)
    assert not animation_off.separate_animations and not animation_off.include_videos
    assert animation_off.policy.destination==photo.policy.destination
    assert animation_off.policy.videos==video_off.policy.videos


@pytest.mark.parametrize('value',[1,0,'true',[],{}])
def test_non_boolean_animation_settings_never_create_metadata_or_a_subfolder(preferences,value):
    service,_,prefs,_,target,_=preferences
    with pytest.raises(TransferError,match='animation_preferences_invalid_settings'):
        prefs.configure(prefs.issue_action(),prefs.read(),enabled=False,mode='manual',separate_animations=value)
    assert not (Path(service.store.root)/prefs._name).exists() and not list(target.iterdir())


@pytest.mark.parametrize('value',[None,1,'true',{},[]])
def test_corrupt_optional_animation_record_is_rejected_instead_of_defaulting_or_migrating(preferences,value):
    saved=configure(preferences)
    wire=saved.policy.wire();wire['separate_animations']=value
    with pytest.raises(TransferError):PhotoPreferences.parse(wire)
    assert preferences[2].read()==saved


def test_stale_animation_configuration_cannot_overwrite_concurrent_video_or_photo_policy(preferences):
    _,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    updated=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='automatic')
    with pytest.raises(TransferError,match='cas_conflict'):
        prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_animations=True)
    assert prefs.read()==updated and not updated.separate_animations


def test_new_pairing_keeps_targets_but_does_not_renew_animation_routing_selection(preferences):
    service,_,prefs,_,_,_=preferences
    photo=configure(preferences)
    saved=prefs.configure(prefs.issue_action(),photo,enabled=True,mode='manual',separate_animations=True)
    peer=service.store.peers[0]
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([6])*32)
    service.store.save_peers()
    channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    replacement=ProtectedPhotoPreferences(authority)
    try:
        old=replacement.read()
        assert old.policy==saved.policy and not old.associated and not old.separate_animations
        accepted=replacement.configure(replacement.issue_action(),old,enabled=True,mode='manual')
        assert accepted.associated and not accepted.separate_animations
        assert accepted.policy.destination==saved.policy.destination
    finally:replacement.close();authority.close()
