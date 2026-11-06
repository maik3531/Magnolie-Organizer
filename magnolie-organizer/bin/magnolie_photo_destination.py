"""Explicit native folder selection only. No preference defaults, scan or sync."""
from dataclasses import dataclass
from pathlib import Path
import os
import secrets
import threading
import time
import unicodedata

from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_transfer import TransferError

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
    import pwd
    try:return pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:return ''

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
    # The phone's native name always wins. Never replace it with the account name.
    safe=_safe_media_name(name)
    if not safe:safe=_safe_media_name(fallback_user_name)
    return (safe or 'Telefon')+suffix

class NativePhotoDestinationAction:
    def __init__(self,owner,clock):
        self._owner=owner;self._clock=clock;self._issued=clock();self._used=False;self._valid=False;self._gate=threading.Lock()
    def consume(self,owner):
        with self._gate:
            if self._used or owner is not self._owner:raise TransferError('photo_destination_action_not_current')
            self._used=True # Failure/clock exceptions do not revive an attempted action.
            now=self._clock()
            if type(now) is not int or type(self._issued) is not int or self._issued<0 or now<self._issued or now-self._issued>=60_000:
                raise TransferError('photo_destination_action_not_current')
            self._valid=True
    def validate(self,owner):
        with self._gate:
            if owner is not self._owner or not self._used or not self._valid:raise TransferError('photo_destination_action_not_current')
            now=self._clock()
            if type(now) is not int or now<self._issued or now-self._issued>=60_000:
                self._valid=False
                raise TransferError('photo_destination_action_not_current')

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
        base=NativeAcceptedDestination.capture(pictures)
        require_media_directory(base.path)
        fallback=self._username() if not _safe_media_name(peer.display_name) else ''
        component=folder_component(peer.display_name,fallback_user_name=fallback)
        self._peer();base.verify()
        fd=os.open(base.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            value=os.fstat(fd)
            if (value.st_dev,value.st_ino)!=base.ancestor_keys[0]:raise TransferError('photo_destination_parent_changed')
            self._peer();base.verify();self._open();action.validate(self)
            try:os.mkdir(component,mode=0o700,dir_fd=fd)
            except FileExistsError:pass # Existing folder is not ours to reset/clear.
            base.verify()
            destination=NativeAcceptedDestination.capture(Path(base.path)/component)
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
