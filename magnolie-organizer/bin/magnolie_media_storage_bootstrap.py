"""Explicit joint native storage binding; never transfer or legacy reconstruction."""
from contextlib import ExitStack
from pathlib import Path
import threading
import time

from magnolie_file_native_authority import NativeDesktopFileAuthority
from magnolie_file_transfer import TransferError
from magnolie_photo_destination import NativePhotoDestinationAction, NativePhotoDestinationController, NativeVideoDestinationController
from magnolie_photo_mappings import ProtectedPhotoMappings
from magnolie_photo_preferences import ProtectedPhotoPreferences,PhotoPreferencesSnapshot
from magnolie_transfer_job_catalog import ProtectedTransferJobCatalog


class NativeMediaStorageBootstrap:
    def __init__(self,authority,*,monotonic_ms=lambda:time.monotonic_ns()//1_000_000):
        if type(authority) is not NativeDesktopFileAuthority or not callable(monotonic_ms):
            raise TransferError('media_storage_native_authority_required')
        self._authority=authority;self._clock=monotonic_ms
        self._closed=threading.Event();self._gate=threading.Lock();self._action=None

    def _open(self):
        if self._closed.is_set():raise TransferError('media_storage_bootstrap_closed')

    def issue_action(self, *, _native_current=None):
        self._open();return NativePhotoDestinationAction(self,self._clock,native_current=_native_current)

    def _guarded_clock(self):
        self._open()
        if self._action is None:raise TransferError('media_storage_bootstrap_action_required')
        # Sub-actions never renew the original user's bounded action lifetime.
        self._action.validate(self);return self._clock()

    def _validate(self,peer):
        self._guarded_clock()
        if self._authority.current_peer()!=peer:raise TransferError('media_storage_bootstrap_authority_changed')
        self._open()

    def prepare(self,action,expected):
        return self._prepare(action,expected)

    def prepare_first_receive(self,action,expected,kinds):
        """Bind selected targets and storage together on an explicit native Start."""
        if (type(action) is not NativePhotoDestinationAction or action._native_current is None
                or type(expected) is not PhotoPreferencesSnapshot
                or kinds not in (('images',),('images','video'))
                or expected.policy is not None and (not expected.policy.staged_receive_targets
                    or not expected.associated or not expected.destination_available)):
            raise TransferError('media_first_receive_original_action_required')
        return self._prepare(action,expected,kinds=kinds)

    def _prepare(self,action,expected,*,kinds=()):
        self._open()
        if type(action) is not NativePhotoDestinationAction:raise TransferError('media_storage_native_action_required')
        action.consume(self)
        if type(expected) is not PhotoPreferencesSnapshot:raise TransferError('media_storage_native_snapshot_required')
        if not self._gate.acquire(blocking=False):raise TransferError('media_storage_bootstrap_busy')
        self._action=action
        try:
            peer=self._authority.current_peer()
            if peer is None:raise TransferError('media_storage_bootstrap_authority_changed')
            self._validate(peer)
            with ExitStack() as owned:
                prefs=ProtectedPhotoPreferences(self._authority,monotonic_ms=self._guarded_clock);owned.callback(prefs.close)
                current=prefs.read()
                if current!=expected:raise TransferError('media_storage_bootstrap_preferences_changed')
                policy=current.policy
                if policy is not None and not current.associated:
                    raise TransferError('media_storage_bootstrap_reassociation_required')
                options={}
                if 'video' in kinds:
                    if not self._authority.video_available():
                        raise TransferError('file_desktop_video_data_join_unavailable')
                    video=NativeVideoDestinationController(self._authority,monotonic_ms=self._guarded_clock)
                    owned.callback(video.close)
                    options.update(include_videos=True,video_destination_choice=video.choose_default(video.issue_action()))
                if kinds and policy is None:
                    photos=NativePhotoDestinationController(self._authority,monotonic_ms=self._guarded_clock)
                    owned.callback(photos.close)
                    options['destination_choice']=photos.choose_default(photos.issue_action())
                mappings=ProtectedPhotoMappings(self._authority,monotonic_ms=self._guarded_clock);owned.callback(mappings.close)
                if policy is not None and policy.mapping_store is not None:
                    mappings.verify_witness(policy.mapping_store)
                parent=Path(self._authority.binding.native_directory)
                try:(parent/ProtectedTransferJobCatalog.NAME).lstat();create=False
                except FileNotFoundError:
                    if policy is not None and policy.job_catalog is not None:
                        raise TransferError('media_storage_bootstrap_expected_catalog_missing')
                    create=True
                self._validate(peer);protection=self._authority.protection
                catalog=ProtectedTransferJobCatalog(parent,self._authority.identity,protection.seal,protection.unseal,create=create)
                owned.callback(catalog.close)
                if policy is not None and policy.job_catalog is not None:catalog.verify_witness(policy.job_catalog)
                catalog_choice=catalog.choice() # Legacy catalogs fail before mapping creation/adoption.
                self._validate(peer)
                mapping_choice=mappings.bootstrap(mappings.issue_action(),mappings.read())
                self._validate(peer)
                result=prefs.configure(prefs.issue_action(),current,enabled=bool(kinds) or (policy is not None and policy.enabled),
                     mode=policy.mode if policy is not None else 'manual',
                     phone_to_pc_delete=policy.phone_to_pc_delete if policy is not None else False,
                     pc_to_phone_delete=policy.pc_to_phone_delete if policy is not None else False,
                     mapping_store_choice=mapping_choice,job_catalog_choice=catalog_choice,**options)
                self._validate(peer)
                if result.policy.mapping_store!=mapping_choice.witness or result.policy.job_catalog!=catalog_choice.witness:
                    raise TransferError('media_storage_bootstrap_joint_readback_failed')
                return result
        finally:
            self._action=None;self._gate.release()

    def close(self):
        self._closed.set() # Do not revoke another feature's shared native owner.
