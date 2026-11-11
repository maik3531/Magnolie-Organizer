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


def probe_virtual_video(node, info):
    from magnolie_phone_webcam import _query_video
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        held = os.fstat(fd)
        if (held.st_dev, held.st_ino, held.st_rdev) != (info.st_dev, info.st_ino, info.st_rdev):
            raise PermissionError('webcam_original_device_changed')
        _query_video(fd)  # QUERYCAP only: no buffers, format changes or capture.
    finally:
        os.close(fd)


def virtual_devices():
    from magnolie_phone_webcam import WebcamUnavailable
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
            probe_virtual_video(node, info)
            label = (entry / 'name').read_text(encoding='utf-8').strip()[:120]
            result.append(dict(path=str(node), label=label or entry.name,
                identity=(info.st_dev, info.st_ino, info.st_rdev), sysfs=str(target)))
        except (OSError, ValueError, WebcamUnavailable):
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
    def __init__(self, service, *, inventory=virtual_devices, video_factory=open_video, clock=time.monotonic, setup=None,
            install_plan=None, installer=None):
        self.service, self.inventory, self.video_factory, self.clock = service, inventory, video_factory, clock
        self.lock = threading.RLock()
        self.action = None
        self.owner = None
        self.lease = ''
        self.setup = setup
        self.setup_gate = threading.Lock()
        self.install_plan, self.installer = install_plan, installer
        self.install_offer = None
        self.installation_pending = False

    def status(self):
        owner = self.owner
        if owner is None:
            return dict(included=True, visible=self.service.webcam_notes_connected(), enabled=False, active=False, phase='off',
                reason='driver_installation_pending' if self.installation_pending else '', lease='')
        active = owner.is_streaming()
        pending = owner.done.is_set() and not owner.cleanup_confirmed
        enabled = not owner.stopping.is_set() and not owner.done.is_set()
        reason = ''
        if owner.error is not None:
            value = str(owner.error)
            reason = next((name for name in ('permission_denied', 'foreground_required', 'unsupported', 'original_start_timeout')
                if name in value), 'failed')
        phase = 'shutdown_pending' if pending else 'active' if active else 'starting' if enabled else 'failed' if reason else 'off'
        return dict(included=True, visible=self.service.webcam_notes_connected(), enabled=enabled, active=active, phase=phase, reason=reason,
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
        if not self.setup_gate.acquire(blocking=False):
            return dict(self.status(), choices=[], action='', reason='driver_setup_busy')
        try:
            return self._prepare(provider)
        finally:
            self.setup_gate.release()

    def _wait_devices(self, current):
        deadline = time.monotonic() + 2
        while True:
            current(); devices = self.inventory()[:8]
            if devices or time.monotonic() >= deadline: return devices
            time.sleep(.05)

    def _prepare(self, provider, original_sources=None, *, setup_allowed=True):
        with self.lock:
            self.action = None
            self.install_offer = None
        if self.installation_pending:
            return dict(self.status(), choices=[], action='', reason='driver_installation_pending')
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
        if original_sources is not None:
            for source in original_sources: self._source_current(source)
            sources = original_sources
        devices = self.inventory()[:8]  # Explicit native action only; no base startup/status probe.
        if not devices and not setup_allowed:
            def current_after_install():
                for source in sources: self._source_current(source)
            devices = self._wait_devices(current_after_install)
            if not devices:
                return dict(self.status(), choices=[], action='', reason='driver_setup_failed')
        if not devices:
            def current():
                for source in sources: self._source_current(source)
            setup = self.setup
            if setup is None:
                from magnolie_phone_camera_setup import prepare_driver
                setup = prepare_driver
            current()
            reason = setup(current)
            current()
            if reason:
                if reason == 'driver_not_installed':
                    from magnolie_phone_camera_install import installation_plan
                    plan = (self.install_plan or installation_plan)()
                    current()
                    if plan is not None:
                        offer = dict(token=secrets.token_hex(32), issued=self.clock(), sources=sources,
                            provider=provider, plan=plan)
                        with self.lock: self.install_offer = offer
                        return dict(self.status(), choices=[], action='', reason=reason, install_token=offer['token'])
                return dict(self.status(), choices=[], action='', reason=reason)
            # udev/logind may publish the new character node/ACL after modprobe.
            devices = self._wait_devices(current)
            if not devices:
                return dict(self.status(), choices=[], action='', reason='driver_setup_failed')
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

    def install_driver(self, install_token):
        if not self.setup_gate.acquire(blocking=False):
            return dict(self.status(), choices=[], action='', reason='driver_setup_busy')
        try:
            with self.lock:
                offer = self.install_offer
                if (offer is None or offer['token'] != install_token or
                        not 0 <= self.clock() - offer['issued'] < 60):
                    raise PermissionError('webcam_original_installation_offer_expired')
                self.install_offer = None  # One use, consumed BEFORE package IO.
            def current():
                for source in offer['sources']: self._source_current(source)
            current()
            from magnolie_phone_camera_install import install_driver
            reason = (self.installer or install_driver)(current, offer['plan'])
            if reason == 'driver_installation_pending': self.installation_pending = True
            current()
            if reason:
                return dict(self.status(), choices=[], action='', reason=reason)
            # The single authorized operation already installed AND configured.
            # Check actual outputs under the SAME parents; a late udev node must
            # never trigger a second setup/polkit dialog.
            return self._prepare(offer['provider'], original_sources=offer['sources'], setup_allowed=False)
        finally:
            self.setup_gate.release()

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
            if self.install_offer is not None and self.install_offer['token'] == action_token:
                self.install_offer = None
                return self.status()
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
