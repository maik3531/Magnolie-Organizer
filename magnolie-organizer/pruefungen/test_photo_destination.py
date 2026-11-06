from pathlib import Path
import sys
import types
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_destination import NativePhotoDestinationController,photo_folder_component,native_pictures_directory
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import media_directory_is_backup,NativeVideoDestinationController
from magnolie_photo_preferences import PhotoPreferences,VideoPreferences
from magnolie_file_acceptance import NativeAcceptedDestination
from test_file_authenticated_desktop import native,bind

@pytest.fixture
def chooser(native,tmp_path):
    service,peer,_=native;channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    clock=[100];controller=NativePhotoDestinationController(authority,monotonic_ms=lambda:clock[0])
    pictures=tmp_path/'native-pictures';pictures.mkdir(mode=0o700)
    try:yield service,peer,authority,controller,pictures,clock
    finally:controller.close();authority.close()

def test_default_destination_is_created_only_by_exact_explicit_native_action(chooser,monkeypatch):
    service,peer,_,controller,pictures,_=chooser
    before={path.name:path.read_bytes() for path in Path(service.store.root).iterdir() if path.is_file()}
    action=controller.issue_action();assert not list(pictures.iterdir())
    monkeypatch.setattr(service.store,'peer',lambda *args:pytest.fail('Folder choice used defaulting peer loader'))
    choice=controller.choose_default(action,pictures_provider=lambda:pictures)
    assert choice.destination.path==str(pictures/photo_folder_component(peer['display_name']))
    assert len(choice.destination_token)==64 and not choice.destination.grants_write_authority
    assert controller.verify_choice(choice)==choice.destination
    with pytest.raises(TransferError):controller.choose_default(action,pictures_provider=lambda:pictures)
    assert before=={path.name:path.read_bytes() for path in Path(service.store.root).iterdir() if path.is_file()}

@pytest.mark.parametrize('name',['../.config/Telefon','CON.foo','Phone: Photos\\Downloads','📱','Maiks  Telefon','Müllers Telefon'])
def test_native_phone_name_becomes_one_safe_component_not_a_raw_path(name):
    component=photo_folder_component(name)
    assert component.endswith('-Fotos') and Path(component).name==component
    assert all(character.isalnum() or character in ' -_' for character in component)
    assert len(component)<=66 and not component.startswith('.')

@pytest.mark.parametrize('reason',['expired','rollback','closed','revoked','foreign','wire'])
def test_ended_or_foreign_actions_cannot_create_a_default_folder(chooser,reason):
    _,_,authority,controller,pictures,clock=chooser;action=controller.issue_action()
    if reason=='expired':clock[0]+=60_000
    elif reason=='rollback':clock[0]-=1
    elif reason=='closed':controller.close()
    elif reason=='revoked':authority.revoke()
    elif reason=='foreign':action=NativePhotoDestinationController(authority).issue_action()
    else:action={'token':'wire-token','path':'/private'}
    with pytest.raises(TransferError):controller.choose_default(action,pictures_provider=lambda:pictures)
    assert not list(pictures.iterdir())
    if reason in ('expired','rollback'):
        clock[0]=100
        with pytest.raises(TransferError):controller.choose_default(action,pictures_provider=lambda:pictures)

def test_native_pictures_resolution_uses_glib_user_directory_not_home_or_localized_guess(chooser,monkeypatch):
    *_,pictures,_=chooser
    requested=[];native_constant=object()
    glib=types.SimpleNamespace(UserDirectory=types.SimpleNamespace(DIRECTORY_PICTURES=native_constant),
        get_user_special_dir=lambda kind:requested.append(kind) or str(pictures))
    gi=types.ModuleType('gi');gi.__path__=[];repository=types.ModuleType('gi.repository');repository.GLib=glib
    monkeypatch.setitem(sys.modules,'gi',gi);monkeypatch.setitem(sys.modules,'gi.repository',repository)
    monkeypatch.setenv('HOME','/not-the-native-pictures-directory')
    assert native_pictures_directory()==str(pictures) and requested==[native_constant]

def test_slow_native_folder_resolution_cannot_create_after_action_deadline(chooser):
    _,_,_,controller,pictures,clock=chooser;action=controller.issue_action()
    def late():clock[0]+=60_000;return pictures
    with pytest.raises(TransferError):controller.choose_default(action,pictures_provider=late)
    assert not list(pictures.iterdir())

def test_existing_default_folder_and_pc_edits_are_preserved_and_symlink_is_not_adopted(chooser,tmp_path):
    _,peer,_,controller,pictures,_=chooser
    existing=pictures/photo_folder_component(peer['display_name']);existing.mkdir(mode=0o700)
    original=existing/'keep.txt';original.write_bytes(b'my PC edit');inode=original.stat().st_ino
    controller.choose_default(controller.issue_action(),pictures_provider=lambda:pictures)
    assert original.read_bytes()==b'my PC edit' and original.stat().st_ino==inode
    selected=tmp_path/'selected';selected.mkdir(mode=0o700)
    custom=controller.choose_custom(controller.issue_action(),selected)
    assert custom.destination.path==str(selected)
    linked=tmp_path/'linked-pictures';linked.mkdir(mode=0o700)
    (linked/existing.name).symlink_to(selected,target_is_directory=True)
    with pytest.raises(TransferError):controller.choose_default(controller.issue_action(),pictures_provider=lambda:linked)
    assert (linked/existing.name).is_symlink() and not list(selected.iterdir())

def test_unavailable_native_pictures_directory_does_not_fall_back_or_create_parent(chooser):
    _,_,_,controller,pictures,_=chooser
    with pytest.raises(TransferError):controller.choose_default(controller.issue_action(),pictures_provider=lambda:None)
    assert not list(pictures.iterdir())

@pytest.mark.parametrize('path',[
    '/media/offline/Backup','/media/former/Backup/album/nested',
    '/media/alternative/BACKUP/videos','/home/user/Pictures/phone/Backup/objects'])
def test_backup_subtrees_are_excluded_independently_of_catalog_or_pair(path):
    assert media_directory_is_backup(path)

@pytest.mark.parametrize('path',['/','/media/former/Backup-other/album','/home/user/myBackup','/media/alternative'])
def test_backup_exclusion_matches_a_whole_directory_component_only(path):
    assert not media_directory_is_backup(path)

def test_backup_destinations_hold_before_folder_creation_and_preserve_history(chooser,tmp_path):
    _,_,authority,controller,_,_=chooser
    parent=tmp_path/'old-pair'/'Backup';parent.mkdir(parents=True,mode=0o700)
    child=parent/'deep';child.mkdir(mode=0o700)
    original=child/'original.jpg';original.write_bytes(b'unchanged original backup')
    before={entry.relative_to(parent).as_posix() for entry in parent.rglob('*')}
    with pytest.raises(TransferError,match='media_backup_subtree_excluded'):
        controller.choose_default(controller.issue_action(),pictures_provider=lambda:parent)
    with pytest.raises(TransferError,match='media_backup_subtree_excluded'):
        controller.choose_custom(controller.issue_action(),child)
    video=NativeVideoDestinationController(authority)
    try:
        with pytest.raises(TransferError,match='media_backup_subtree_excluded'):
            video.choose_custom(video.issue_action(),child)
    finally:video.close()
    destination=NativeAcceptedDestination.capture(child)
    policy=PhotoPreferences(2,'a'*64,'b'*64,True,'manual',False,False,destination,'c'*64)
    with pytest.raises(TransferError,match='media_backup_subtree_excluded'):PhotoPreferences.parse(policy.wire())
    with pytest.raises(TransferError,match='media_backup_subtree_excluded'):
        VideoPreferences.parse(VideoPreferences(True,destination,'d'*64).wire())
    assert original.read_bytes()==b'unchanged original backup'
    assert {entry.relative_to(parent).as_posix() for entry in parent.rglob('*')}==before
