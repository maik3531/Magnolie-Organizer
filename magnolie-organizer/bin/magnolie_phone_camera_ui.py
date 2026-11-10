"""Ephemeral native webcam choices for Advanced functions, never preferences.

Inventory is read only AFTER an explicit prepare action. Actual activation opens
and holds one original virtual-video output before asking the phone for capture;
no physical camera is inventoried/opened, driver installed or URL selected.
"""
from pathlib import Path
import os
import secrets
import stat
import threading
import time


def virtual_devices():
    result = []
    root = Path('/sys/class/video4linux')
    if not root.is_dir():
        return result
    for entry in sorted(root.glob('video[0-9]*'))[:32]:
        try:
            target = entry.resolve(strict=True)
            if not str(target).startswith('/sys/devices/virtual/video4linux/'):
                continue
            node = Path('/dev') / entry.name
            info = node.lstat()
            if not stat.S_ISCHR(info.st_mode):
                continue
            label = (entry / 'name').read_text(encoding='utf-8').strip()[:120]
            result.append(dict(path=str(node), label=label or entry.name,
                identity=(info.st_dev, info.st_ino, info.st_rdev), sysfs=str(target)))
        except (OSError, ValueError):
            continue
    return result


def open_video(choice):
    from magnolie_phone_webcam import LinuxVideoOutput
    output = LinuxVideoOutput(choice['path'])  # Real driver/profile validation, not name alone.
    try:
        info = os.fstat(output.fd)
        if (info.st_dev, info.st_ino, info.st_rdev) != choice['identity']:
            raise PermissionError('webcam_original_device_changed')
        return output
    except BaseException:
        output.close()
        raise


class NativeWebcamUi:
    def __init__(self, service, *, inventory=virtual_devices, video_factory=open_video, clock=time.monotonic):
        self.service, self.inventory, self.video_factory, self.clock = service, inventory, video_factory, clock
        self.lock = threading.RLock()
        self.action = None
        self.owner = None
        self.lease = ''

    def status(self):
        owner = self.owner
        if owner is None:
            return dict(included=True, enabled=False, active=False, phase='off', reason='', lease='')
        active = owner.is_streaming()
        pending = owner.done.is_set() and not owner.cleanup_confirmed
        enabled = not owner.stopping.is_set() and not owner.done.is_set()
        reason = ''
        if owner.error is not None:
            value = str(owner.error)
            reason = next((name for name in ('permission_denied', 'foreground_required', 'unsupported', 'original_start_timeout')
                if name in value), 'failed')
        phase = 'shutdown_pending' if pending else 'active' if active else 'starting' if enabled else 'failed' if reason else 'off'
        return dict(included=True, enabled=enabled, active=active, phase=phase, reason=reason,
            lease=self.lease, provider='notes', muted=owner.muted, front=owner.front)

    def _source_current(self, source):
        service = self.service
        peer = next((value for value in service.store.peers if value.get('device_id') == source['peer']), None)
        if (service.store is not source['store'] or service._generation != source['generation'] or
                not service.enabled or service.stop_event.is_set() or not peer or peer.get('state') != 'paired' or
                peer.get('static_public') != source['key'] or service.connections.get(source['peer']) is not source['channel'] or
                service.connection_transports.get(source['peer']) != 'wifi' or
                source['channel'].last_capabilities is not source['capabilities']):
            raise PermissionError('webcam_original_choice_changed')

    def prepare(self, provider):
        if provider not in ('auto', 'notes', 'kdeconnect'):
            raise ValueError('invalid webcam provider')
        with self.lock:
            self.action = None
        if provider == 'kdeconnect':
            return dict(self.status(), choices=[], action='', reason='compatible_extension_required')
        previous = self.service._native_webcam_owner
        if previous is not None and not previous.is_completely_stopped():
            return dict(self.status(), choices=[], action='', reason='owner_busy')
        from magnolie_telefon import SecureChannel
        sources = []
        with self.service.lock:
            if not self.service.enabled or self.service.stop_event.is_set():
                return dict(self.status(), choices=[], action='', reason='phone_unavailable')
            for peer in self.service.store.peers:
                channel = self.service.connections.get(peer.get('device_id'))
                if (peer.get('state') == 'paired' and type(channel) is SecureChannel and channel.last_capabilities is not None and
                        self.service.connection_transports.get(peer['device_id']) == 'wifi'):
                    sources.append(dict(peer=peer['device_id'], key=peer['static_public'], channel=channel,
                        generation=self.service._generation, store=self.service.store, capabilities=channel.last_capabilities,
                        label=str(peer.get('display_name', ''))[:120]))
        if not sources:
            return dict(self.status(), choices=[], action='', reason='phone_unavailable')
        devices = self.inventory()[:8]  # Explicit native action only; no base startup/status probe.
        if not devices:
            return dict(self.status(), choices=[], action='', reason='virtual_camera_missing')
        choices = {}
        for source in sources[:4]:
            for device in devices:
                token = secrets.token_hex(32)
                choices[token] = source, dict(device)
        action = dict(token=secrets.token_hex(32), issued=self.clock(), choices=choices)
        with self.lock:
            self.action = action
        return dict(self.status(), reason='', action=action['token'], choices=[
            dict(token=token, phone=source['label'], device=device['label'], provider='notes')
            for token, (source, device) in choices.items()])

    def start(self, action_token, choice_token, muted, front):
        with self.lock:
            return self._start(action_token, choice_token, muted, front)

    def _start(self, action_token, choice_token, muted, front):
        if type(muted) is not bool or type(front) is not bool:
            raise ValueError('invalid webcam capture choice')
        with self.lock:
            action = self.action
            if (action is None or action['token'] != action_token or choice_token not in action['choices'] or
                    not 0 <= self.clock() - action['issued'] < 60):
                raise PermissionError('webcam_original_choice_expired')
            self.action = None  # Consume before any native IO; never retry an old UI action.
            source, device = action['choices'][choice_token]
        self._source_current(source)
        video = self.video_factory(device)
        claimed = False
        def original_video(path):
            nonlocal claimed
            if claimed or path != device['path']:
                raise PermissionError('webcam_original_video_already_used')
            claimed = True
            return video  # The ORIGINAL held native descriptor; never reopen a path.
        def outputs(path, guard, **settings):
            from magnolie_phone_webcam import NativeWebcamSession
            return NativeWebcamSession(path, guard, video_factory=original_video, **settings)
        try:
            self._source_current(source)
            owner = self.service.begin_native_webcam(source['peer'], device=device['path'], muted=muted, front=front,
                _output_factory=outputs, _prepared_cleanup=video.close,
                _source_guard=lambda: self._source_current(source))
        except BaseException:
            video.close()
            raise
        with self.lock:
            self.owner, self.lease = owner, secrets.token_hex(32)
        return self.status()

    def cancel(self, action_token):
        with self.lock:
            if self.action is None or self.action['token'] != action_token:
                raise PermissionError('webcam_original_choice_expired')
            self.action = None
        return self.status()

    def stop(self, lease):
        with self.lock:
            if type(lease) is not str or not lease or lease != self.lease or self.owner is None:
                raise PermissionError('webcam_original_ui_owner_required')
            owner = self.owner
        if not self.service.end_native_webcam(owner):
            raise PermissionError('webcam_original_ui_owner_retired')
        return self.status()
