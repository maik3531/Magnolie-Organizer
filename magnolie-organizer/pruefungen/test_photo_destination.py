from pathlib import Path
import json
import os
import subprocess
import sys
import types
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_destination import NativePhotoDestinationController,photo_folder_component,native_pictures_directory
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import media_directory_is_backup,media_path_is_excluded,require_media_directory,NativeVideoDestinationController
from magnolie_photo_destination import video_folder_component
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

def test_group_writable_default_is_held_but_explicit_private_choice_is_available(chooser,tmp_path):
    _,_,_,controller,pictures,_=chooser
    pictures.chmod(0o775)
    original=pictures/'existing.jpg';original.write_bytes(b'original')
    with pytest.raises(TransferError,match='file_acceptance_unsafe_destination'):
        controller.choose_default(controller.issue_action(),pictures_provider=lambda:pictures)
    assert list(pictures.iterdir())==[original] and original.read_bytes()==b'original'
    assert pictures.stat().st_mode & 0o777==0o775
    private=tmp_path/'private-photo-choice';private.mkdir(mode=0o700)
    choice=controller.choose_custom(controller.issue_action(),private)
    assert controller.verify_choice(choice).path==str(private)
    assert not choice.destination.grants_write_authority and not list(private.iterdir())

@pytest.mark.parametrize('kind',['photos','videos'])
def test_verified_private_home_parent_keeps_permissions_and_requires_a_private_leaf(chooser,monkeypatch,kind):
    import magnolie_photo_destination as native_destination
    _,peer,authority,controller,pictures,_=chooser
    # Use the real filesystem for identity/mode enforcement; the isolated
    # /tmp test path is not a system account's private home.
    base=NativeAcceptedDestination.capture(pictures)
    monkeypatch.setattr(native_destination,'_private_home_parent_keys',
                        lambda path: base.ancestor_keys if path==pictures else pytest.fail('wrong parent'))
    original=pictures/'keep.jpg';original.write_bytes(b'untouched')
    pictures.chmod(0o775)
    video=NativeVideoDestinationController(authority) if kind=='videos' else None
    try:
        owner=video or controller
        provider={'videos_provider' if video else 'pictures_provider':lambda:pictures}
        folder=video_folder_component if video else photo_folder_component
        choice=owner.choose_default(owner.issue_action(),**provider)
        leaf=pictures/folder(peer['display_name'])
        assert choice.destination.path==str(leaf) and leaf.stat().st_mode & 0o777==0o700
        assert pictures.stat().st_mode & 0o777==0o775 and original.read_bytes()==b'untouched'
        leaf.chmod(0o775)
        with pytest.raises(TransferError,match='file_acceptance_unsafe_destination'):
            owner.choose_default(owner.issue_action(),**provider)
        assert leaf.stat().st_mode & 0o777==0o775
    finally:
        if video is not None:video.close()

@pytest.mark.parametrize('other_user,other_member,nss_source,allowed',[
    (False,False,'files systemd',True),(True,False,'files systemd',False),
    (False,True,'files systemd',False),(False,False,'files sss',False)])
def test_private_primary_group_requires_exclusive_local_membership(monkeypatch,other_user,other_member,nss_source,allowed):
    import magnolie_photo_destination as native_destination
    account=types.SimpleNamespace(pw_name='owner',pw_gid=1000,pw_uid=1000)
    other=types.SimpleNamespace(pw_name='other',pw_gid=1000,pw_uid=1001)
    group=types.SimpleNamespace(gr_name='owner',gr_gid=1000,gr_mem=['other'] if other_member else [])
    monkeypatch.setattr(Path,'read_text',lambda path: f'passwd: {nss_source}\ngroup: files systemd\n')
    monkeypatch.setattr(native_destination.grp,'getgrgid',lambda _:group)
    monkeypatch.setattr(native_destination.grp,'getgrall',lambda:[group])
    monkeypatch.setattr(native_destination.pwd,'getpwall',lambda:[account,other] if other_user else [account])
    assert native_destination._local_private_user_group(account) is allowed

@pytest.mark.parametrize('permission,mask,extra_writes', [(1,5,False),(3,5,False),(3,7,True)])
def test_standard_parent_acl_uses_effective_write_right(chooser,monkeypatch,permission,mask,extra_writes):
    import struct
    import magnolie_photo_destination as native_destination
    entries=((1,7,0xffffffff),(2,permission,99),(4,5,0xffffffff),(16,mask,0xffffffff),(32,0,0xffffffff))
    xattr=b'\x02\x00\x00\x00'+b''.join(struct.pack('<HHI',*entry) for entry in entries)
    monkeypatch.setattr(os,'getxattr',lambda *args,**kwargs:xattr)
    assert native_destination._acl_has_extra_writers(chooser[4]) is extra_writes

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

def test_real_glib_resolves_independent_personal_roots_without_guessing_home_or_creating_them(chooser,tmp_path):
    pytest.importorskip('gi')
    _,peer,authority,photos,_,_=chooser
    home=tmp_path/'isolated-home';home.mkdir(mode=0o700)
    xdg=home/'isolated-config';xdg.mkdir(mode=0o700)
    photos_root=home/'Native Picture Library';photos_root.mkdir(mode=0o700)
    videos_root=home/'Native Video Library';videos_root.mkdir(mode=0o700)
    config=xdg/'user-dirs.dirs'
    config.write_text('XDG_PICTURES_DIR="$HOME/Native Picture Library"\nXDG_VIDEOS_DIR="$HOME/Native Video Library"\n',encoding='utf-8')
    env=dict(os.environ,HOME=str(home),XDG_CONFIG_HOME=str(xdg),PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=str(Path(__file__).resolve().parents[1]/'bin'))
    # GLib caches user directories per process. Keep the real GUI's environment
    # unchanged and run the unmocked resolver with an isolated XDG configuration.
    probe='''import json
from magnolie_photo_destination import native_pictures_directory,native_videos_directory
from magnolie_file_transfer import TransferError
result=[]
for provider in (native_pictures_directory,native_videos_directory):
    try:result.append(provider())
    except TransferError as error:result.append(str(error))
print(json.dumps(result))
'''
    def resolve():return json.loads(subprocess.check_output([sys.executable,'-c',probe],env=env,text=True,timeout=10))
    photo_path,video_path=resolve()
    assert (photo_path,video_path)==(str(photos_root),str(videos_root))
    assert not list(photos_root.iterdir()) and not list(videos_root.iterdir())
    videos=NativeVideoDestinationController(authority)
    try:
        photo=photos.choose_default(photos.issue_action(),pictures_provider=lambda:photo_path)
        video=videos.choose_default(videos.issue_action(),videos_provider=lambda:video_path)
        assert Path(photo.destination.path)==photos_root/photo_folder_component(peer['display_name'])
        assert Path(video.destination.path)==videos_root/video_folder_component(peer['display_name'])
        assert photo.destination_token!=video.destination_token
        assert all(not choice.destination.grants_write_authority for choice in (photo,video))
    finally:videos.close()
    config.write_text('XDG_DESKTOP_DIR="$HOME/Desktop"\n',encoding='utf-8')
    assert resolve()==['photo_destination_native_pictures_unavailable','video_destination_native_videos_unavailable']
    assert not (home/'Pictures').exists() and not (home/'Videos').exists()


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

@pytest.mark.parametrize('path,excluded',(
    ('/native/Backup/photo.jpg',True),
    ('/native/.magnolie-restore-'+'a'*32+'.part',True),
    ('/native/.magnolie-restore-'+'a'*32+'.part/sub/file.jpg',True),
    ('/native/.magnolie-publication-'+'b'*32+'/photo.jpg',True),
    ('/native/photo - restored '+'a'*32+'.jpg',False),
    ('/native/.magnolie-restore-personal.part',False),
    ('/native/.magnolie-restore-'+'a'*31+'.part',False),
    ('/native/.magnolie-restore-'+'a'*32+'.part-personal.jpg',False),
    ('/native/.magnolie-publication-personal/photo.jpg',False)))
def test_unpublished_native_stages_are_deny_only_and_restored_new_files_remain_eligible(path,excluded):
    assert media_path_is_excluded(path) is excluded
    if excluded:
        with pytest.raises(TransferError,match='excluded'):require_media_directory(path)
    else:require_media_directory(path)

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
