"""Native folder selection and relative layout rules. No scan or file moves."""
from dataclasses import dataclass
import errno
import grp
from pathlib import Path
import os
import pwd
import re
import secrets
import stat
import struct
import threading
import time
import unicodedata

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_transfer import TransferError, _portable_path


def grouped_media_path(original, *, animation, capture):
    """Use exactly the same folder order for new files and historical plans."""
    if type(animation) is not bool or type(capture) is not bool:
        raise TransferError('photo_grouping_invalid_layout')
    _portable_path(original)
    return _portable_path(('Eigene Aufnahmen/' if capture else '')+('Animationen/' if animation else '')+original)


def plan_special_folder_path(original, mapped, *, was_animation, was_capture,
        verified_animation, verified_capture, setting, separate):
    """Pure path candidate, never a move grant or a claim about media content.

    A later native journal must supply the authenticated original manifest path,
    mapping, historical flags/eligibility and recheck both filesystem endpoints.
    Current preferences, a basename or a prefix in an album are not evidence.
    """
    if (setting not in ('animation','capture') or any(type(value) is not bool for value in
            (was_animation,was_capture,verified_animation,verified_capture,separate))):
        raise TransferError('photo_grouping_invalid_layout')
    source=grouped_media_path(original,animation=was_animation,capture=was_capture)
    if type(mapped) is not str or mapped!=source or was_animation and not verified_animation or was_capture and not verified_capture:
        raise TransferError('photo_grouping_original_layout_required')
    animation=separate and verified_animation if setting=='animation' else was_animation
    capture=separate and verified_capture if setting=='capture' else was_capture
    target=grouped_media_path(original,animation=animation,capture=capture)
    return None if target==source else target


@dataclass(frozen=True)
class SpecialFolderOrigin:
    """Historical paths only; source classification is not current eligibility."""
    original_path: str
    mapped_path: str
    mapping_sha256: str
    source_media_kind: str
    was_animation: bool
    was_capture: bool


def special_folder_origin(accepted, history, mapping):
    """Match an already checked saved mapping to its immutable receive job."""
    from magnolie_file_acceptance import NativeAcceptedTransfer
    from magnolie_file_media_history import NativeMediaHistory
    from magnolie_photo_mappings import NativeSavedPhotoMapping
    if (type(accepted) is not NativeAcceptedTransfer or type(history) is not NativeMediaHistory
            or type(mapping) is not NativeSavedPhotoMapping):
        raise TransferError('photo_grouping_original_job_required')
    association=mapping.association
    member=next((entry for entry in history.entries if entry.file_id==mapping.source_file_id),None)
    file=next((entry for entry in accepted.manifest.files if entry.id==mapping.source_file_id),None)
    if (member is None or file is None or (member.photo_id,history.source_epoch,history.media_type)!=
            (association.photo_id,association.source_epoch,association.media_type)
            or association.photo_id in dict(history.version_parents)
            or mapping.accepted_sha256!=history.accepted_sha256 or mapping.accepted_sha256!=accepted.fingerprint
            or mapping.manifest_sha256!=history.manifest_sha256 or mapping.manifest_sha256!=accepted.manifest.fingerprint
            or mapping.relative_path!=dict(accepted.targets).get(file.id) or mapping.destination!=accepted.destination):
        raise TransferError('photo_grouping_original_job_required')
    for capture in (False,True):
        for animation in ((False,True) if member.media_kind=='animation' else (False,)):
            try:path=grouped_media_path(file.path,animation=animation,capture=capture)
            except TransferError:continue
            if path==mapping.relative_path:
                return SpecialFolderOrigin(file.path,path,mapping.protected_record_sha256,member.media_kind,animation,capture)
    raise TransferError('photo_grouping_original_layout_required')


def media_directory_is_backup(path):
    """Deny-only recursive exclusion; no catalog, pairing or IO authority.

    All managed backup locations keep their dedicated Backup child, including
    alternative parents and retained former locations. Missing metadata must
    never turn that subtree into synchronization input/output.
    """
    if not isinstance(path,(str,Path)):
        raise TransferError('photo_destination_native_path_required')
    value=str(path)
    if (not value.startswith('/') or '\x00' in value
            or any(part in ('.','..') for part in value.split('/'))):
        raise TransferError('photo_destination_native_path_required')
    return any(part.casefold()=='backup' for part in value.split('/'))

def require_media_directory(path):
    if media_directory_is_backup(path):raise TransferError('media_backup_subtree_excluded')
    if media_path_is_excluded(path):raise TransferError('media_private_stage_excluded')

def media_path_is_excluded(path):
    """Deny-only sync classification, including unpublished restoration bytes.

    The same function is suitable before descending an inventory directory or
    opening a leaf. Excluded stages never attest deletion or a content baseline.
    """
    if media_directory_is_backup(path):return True
    return any(re.fullmatch(r'\.magnolie-(?:restore-[0-9a-f]{32}\.part|source-(?:[0-9a-f]{32}\.part|[0-9a-f]{32}-[0-9a-f]{32}\.retired|catalog-[0-9a-f]{64}\.seal)|publication-[0-9a-f]{32}|relocation-dir-[0-9a-f]{32})',part)
        is not None for part in str(path).split('/'))

def native_pictures_directory():
    from gi.repository import GLib
    value=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    if type(value) is not str or not value or not Path(value).is_absolute():
        raise TransferError('photo_destination_native_pictures_unavailable')
    return value # Never guessed HOME/Pictures or a localized literal.

def native_videos_directory():
    from gi.repository import GLib
    value=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS)
    if type(value) is not str or not value or not Path(value).is_absolute():
        raise TransferError('video_destination_native_videos_unavailable')
    return value # Independent native Videos location, never the photo destination.

def native_account_name():
    try:return pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:return ''

def _local_private_user_group(account):
    """Only accept a provably single-user group from local account sources."""
    sources={}
    for line in Path('/etc/nsswitch.conf').read_text().splitlines():
        key, _, value=line.partition('#')[0].partition(':')
        if key.strip() in ('passwd','group','initgroups'):
            if key.strip() in sources:return False
            sources[key.strip()]=value.split()
    if not all(sources.get(key) and sources[key][0]=='files' and
               set(sources[key])<= {'files','systemd'} for key in ('passwd','group')):
        return False
    if 'initgroups' in sources and sources['initgroups']!=['files']:return False
    group=grp.getgrgid(account.pw_gid)
    return (group.gr_name==account.pw_name and
            set(group.gr_mem)<= {account.pw_name} and
            all(entry==group for entry in grp.getgrall() if entry.gr_gid==account.pw_gid) and
            {(user.pw_name,user.pw_uid) for user in pwd.getpwall() if user.pw_gid==account.pw_gid}
            == {(account.pw_name,account.pw_uid)})

def _acl_has_extra_writers(directory):
    try:raw=os.getxattr(directory,'system.posix_acl_access',follow_symlinks=False)
    except OSError as error:
        if error.errno==errno.ENODATA:return False
        raise
    # Linux POSIX ACL xattr v2. Inspect effective access, not merely the
    # presence of a named entry (e.g. a read-only traversal permission).
    if len(raw)<4 or raw[:4]!=b'\x02\x00\x00\x00' or (len(raw)-4)%8:
        return True
    entries=tuple(struct.iter_unpack('<HHI',raw[4:]))
    masks=[bits for tag,bits,_ in entries if tag==0x10]
    if len(masks)!=1 or any(tag not in (1,2,4,8,16,32) or bits & ~7 for tag,bits,_ in entries):
        return True
    return any(tag in (2,8) and bits & masks[0] & 2 for tag,bits,_ in entries)

def _private_home_parent_keys(path):
    """A setup parent is not a receipt or permission to write media."""
    try:
        account=pwd.getpwuid(os.geteuid())
        home=Path(account.pw_dir)
        if home not in path.parents or path.resolve(strict=True)!=path or not _local_private_user_group(account):
            raise ValueError
        keys=[]
        under_home=True
        for directory in (path,*path.parents):
            value=directory.lstat()
            if not stat.S_ISDIR(value.st_mode):raise ValueError
            if under_home:
                if (value.st_uid!=account.pw_uid or value.st_mode & stat.S_IWOTH or
                        value.st_mode & stat.S_IWGRP and value.st_gid!=account.pw_gid or
                        _acl_has_extra_writers(directory)):
                    raise ValueError
            elif value.st_uid!=0 or value.st_mode & 0o022:
                raise ValueError
            keys.append((value.st_dev,value.st_ino))
            if directory==home:under_home=False
        return tuple(keys)
    except (OSError,KeyError,ValueError) as error:
        raise TransferError('file_acceptance_unsafe_destination') from error

def photo_folder_component(name,*,fallback_user_name=''):
    return _media_folder_component(name,'-Fotos',fallback_user_name)

def video_folder_component(name,*,fallback_user_name=''):
    return _media_folder_component(name,'-Videos',fallback_user_name)

def _safe_media_name(name):
    if type(name) is not str:raise TransferError('photo_destination_native_name_required')
    normalized=unicodedata.normalize('NFC',name)
    safe=''.join(character if character.isalnum() or character in ' -_' else '_' for character in normalized)
    return ' '.join(safe.split()).strip(' _')[:60].rstrip(' _')

def _media_folder_component(name,suffix,fallback_user_name):
    safe=_safe_media_name(name)
    # An unusable folder component is not evidence that the phone name was absent.
    if not name.strip():safe=_safe_media_name(fallback_user_name)
    return (safe or 'Telefon')+suffix

class NativePhotoDestinationAction:
    def __init__(self,owner,clock,*,native_current=None):
        if native_current is not None and not callable(native_current):raise TransferError('photo_destination_native_guard_required')
        self._owner=owner;self._clock=clock;self._issued=clock();self._used=False;self._valid=False;self._gate=threading.Lock()
        self._native_current=native_current

    def _current(self):
        try:
            if self._native_current is not None and self._native_current() is False:
                raise TransferError('photo_destination_native_guard_changed')
        except BaseException:
            with self._gate:self._valid=False
            raise
    def consume(self,owner):
        with self._gate:
            if self._used or owner is not self._owner:raise TransferError('photo_destination_action_not_current')
            self._used=True # Failure/clock exceptions do not revive an attempted action.
            now=self._clock()
            if type(now) is not int or type(self._issued) is not int or self._issued<0 or now<self._issued or now-self._issued>=60_000:
                raise TransferError('photo_destination_action_not_current')
            self._valid=True
        self._current()
    def validate(self,owner):
        with self._gate:
            if owner is not self._owner or not self._used or not self._valid:raise TransferError('photo_destination_action_not_current')
            now=self._clock()
            if type(now) is not int or now<self._issued or now-self._issued>=60_000:
                self._valid=False
                raise TransferError('photo_destination_action_not_current')
        self._current()

@dataclass(frozen=True)
class NativePhotoDestinationChoice:
    destination: NativeAcceptedDestination
    destination_token: str
    owner: object

@dataclass(frozen=True)
class NativeVideoDestinationChoice(NativePhotoDestinationChoice):
    pass

class NativePhotoDestinationController:
    """Only the private Organizer UI handler issues an action. Wire settings
    cannot construct its exact in-process owner/ticket or choose a path. Folder
    I/O belongs to the native I/O lane; this class starts no worker/timer itself.
    """
    _choice_type=NativePhotoDestinationChoice
    def __init__(self,authority,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000,username_provider=native_account_name):
        if type(authority) is not NativeDesktopFileAuthority:raise TransferError('photo_destination_native_authority_required')
        if not callable(username_provider):raise TransferError('photo_destination_native_name_required')
        self._authority=authority;self._clock=monotonic_ms;self._closed=threading.Event();self._username=username_provider
    def _open(self):
        if self._closed.is_set():raise TransferError('photo_destination_controller_closed')
    def issue_action(self):
        self._open()
        return NativePhotoDestinationAction(self,self._clock) # Inert UI capability, not consent.
    def _peer(self):
        self._open()
        peer=self._authority.current_peer()
        if peer is None:raise TransferError('photo_destination_native_authority_changed')
        self._open()
        return peer
    def _take(self,action):
        self._open()
        if type(action) is not NativePhotoDestinationAction:raise TransferError('photo_destination_native_action_required')
        action.consume(self)
        return self._peer()
    def choose_default(self,action,*,pictures_provider=native_pictures_directory):
        return self._choose_default(action,pictures_provider,photo_folder_component,'photo_destination_native_pictures_unavailable')
    def _choose_default(self,action,provider,folder_component,unavailable):
        peer=self._take(action)
        pictures=provider()
        if not isinstance(pictures,(str,Path)) or not Path(pictures).is_absolute():
            raise TransferError(unavailable)
        parent=Path(pictures)
        require_media_directory(parent)
        try:
            base=NativeAcceptedDestination.capture(parent)
        except TransferError as error:
            if str(error)!='file_acceptance_unsafe_destination':raise
            # A private primary group can write the standard parent. The
            # actual destination below must still pass the strict leaf check.
            keys=_private_home_parent_keys(parent)
            def verify_parent():
                if _private_home_parent_keys(parent)!=keys:raise TransferError('photo_destination_parent_changed')
        else:
            keys=base.ancestor_keys
            verify_parent=base.verify
        fallback=self._username() if not peer.display_name.strip() else ''
        component=folder_component(peer.display_name,fallback_user_name=fallback)
        self._peer();verify_parent()
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            value=os.fstat(fd)
            if (value.st_dev,value.st_ino)!=keys[0]:raise TransferError('photo_destination_parent_changed')
            self._peer();verify_parent();self._open();action.validate(self)
            try:os.mkdir(component,mode=0o700,dir_fd=fd)
            except FileExistsError:pass # Existing folder is not ours to reset/clear.
            verify_parent()
            destination=NativeAcceptedDestination.capture(parent/component)
            if destination.ancestor_keys[1:]!=keys:raise TransferError('photo_destination_parent_changed')
            self._peer();self._open();action.validate(self)
            return self._choice_type(destination,secrets.token_hex(32),self)
        finally:os.close(fd)
    def choose_custom(self,action,selected_native_directory):
        self._take(action)
        destination=NativeAcceptedDestination.capture(selected_native_directory)
        require_media_directory(destination.path)
        self._peer();self._open();action.validate(self)
        return self._choice_type(destination,secrets.token_hex(32),self)
    def verify_choice(self,choice):
        if type(choice) is not self._choice_type or choice.owner is not self:
            raise TransferError('photo_destination_choice_not_native')
        require_media_directory(choice.destination.path)
        self._peer();choice.destination.verify();self._peer()
        return choice.destination
    def close(self):
        self._closed.set() # Ends folder UI capabilities, not the shared file authority.

class NativeVideoDestinationController(NativePhotoDestinationController):
    """Independent video folder metadata, not enabling video read/synchronization."""
    _choice_type=NativeVideoDestinationChoice
    def choose_default(self,action,*,videos_provider=native_videos_directory):
        return self._choose_default(action,videos_provider,video_folder_component,'video_destination_native_videos_unavailable')
