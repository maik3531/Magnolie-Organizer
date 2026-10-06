"""Delta decoder for KDE Connect's authenticated drawing-tablet packets."""
import math
import threading
import uuid

SESSION_PACKET = 'kdeconnect.digitizer.session'
EVENT_PACKET = 'kdeconnect.digitizer'


class DigitizerState:
    def __init__(self):
        self.diagnostics = dict(events=0, explicit_contact=0, positive_pressure=0,
                                pressure_updates=0, rejected=0)
        self.reset()

    def reset(self):
        self.width = self.height = 0
        self.x = self.y = None
        self.active = self.touching = False
        self.tool = 'Pen'
        self.pressure = 0.0

    @staticmethod
    def integer(body, name, minimum, maximum):
        value = body.get(name)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('invalid_digitizer_field')
        return value

    def sample(self):
        return dict(active=self.active and self.width > 0,
                    touching=self.active and self.touching and self.x is not None and self.y is not None,
                    tool=self.tool, x=self.x / self.width if self.x is not None and self.width else 0,
                    y=self.y / self.height if self.y is not None and self.height else 0, pressure=self.pressure)

    def accept(self, kind, body):
        try:
            if not isinstance(body, dict):
                raise ValueError('invalid_digitizer_packet')
            if kind == SESSION_PACKET:
                if body.get('action') == 'end':
                    self.reset()
                    return self.sample()
                if body.get('action') != 'start' or set(body) - {'action', 'width', 'height', 'resolutionX', 'resolutionY'}:
                    raise ValueError('invalid_digitizer_session')
                width = self.integer(body, 'width', 1, 32768)
                height = self.integer(body, 'height', 1, 32768)
                self.integer(body, 'resolutionX', 0, 100000)
                self.integer(body, 'resolutionY', 0, 100000)
                self.reset()
                self.width, self.height = width, height
                return self.sample()
            if kind != EVENT_PACKET or not self.width or not body or set(body) - {'active', 'touching', 'tool', 'x', 'y', 'pressure'}:
                raise ValueError('invalid_digitizer_event')
            active = body.get('active', self.active)
            touching = body.get('touching', self.touching)
            tool = body.get('tool', self.tool)
            if type(active) is not bool or type(touching) is not bool or tool not in ('Pen', 'Rubber'):
                raise ValueError('invalid_digitizer_state')
            x = self.integer(body, 'x', -1000000, 1000000) if 'x' in body else self.x
            y = self.integer(body, 'y', -1000000, 1000000) if 'y' in body else self.y
            pressure = body.get('pressure', self.pressure)
            if type(pressure) not in (int, float) or not math.isfinite(pressure) or not 0 <= pressure <= 8:
                raise ValueError('invalid_digitizer_pressure')
            self.diagnostics['events'] += 1
            self.diagnostics['explicit_contact'] += int(body.get('touching') is True)
            self.diagnostics['pressure_updates'] += int('pressure' in body)
            self.diagnostics['positive_pressure'] += int('pressure' in body and pressure > 0)
            # Android finger drawing sends pressure deltas while its draw
            # button is held, without a new touching=True packet. Explicit
            # release/proximity-exit still wins over any retained pressure.
            if 'active' in body and not active or 'touching' in body and not touching:
                touching, pressure = False, 0.0
            elif 'touching' not in body and 'pressure' in body:
                touching = pressure > 0
            self.active, self.touching, self.tool = active, active and touching, tool
            self.x, self.y, self.pressure = x, y, max(0, min(1, pressure))
            return self.sample()
        except (ValueError, TypeError, OverflowError):
            self.diagnostics['rejected'] += 1
            self.reset()
            raise ValueError('invalid_digitizer_packet') from None


class DigitizerRelay:
    """A bounded, transient foreground subscription; never stores drawn paths."""
    def __init__(self, publish):
        self.publish = publish
        self.lock = threading.RLock()
        self.owner = None
        self.token = ''
        self.device_id = ''
        self.samples = []
        self.stop = threading.Event()

    def arm(self, owner, device_id, token, permitted):
        uuid.UUID(token)
        if owner is None or not permitted():
            raise ValueError('digitizer_unavailable')
        self.disarm()
        with self.lock:
            self.owner, self.device_id, self.token = owner, device_id, token
            stop = threading.Event()
            self.stop = stop
        threading.Thread(target=self._drain, args=(stop, owner, device_id, token, permitted),
                         daemon=True, name='magnolie-digitizer').start()

    def disarm(self, token=None, owner=None):
        with self.lock:
            if token is not None and token != self.token or owner is not None and owner is not self.owner:
                return
            if self.owner is None:
                return
            device_id, old_token = self.device_id, self.token
            self.stop.set(); self.owner = None; self.token = ''; self.samples.clear()
        self.publish('digitizer', dict(device_id=device_id, token=old_token, stopped=True,
                                      events=[dict(active=False, touching=False)]))

    def push(self, owner, sample):
        overflow = False
        with self.lock:
            if owner is not self.owner or self.stop.is_set():
                return
            if len(self.samples) >= 128:
                overflow = True
            else:
                self.samples.append(dict(sample))
        if overflow:
            self.disarm(owner=owner)

    def _drain(self, stop, owner, device_id, token, permitted):
        try:
            while not stop.wait(0.016):
                if not permitted():
                    self.disarm(token=token, owner=owner)
                    return
                with self.lock:
                    if owner is not self.owner or token != self.token:
                        return
                    samples, self.samples = self.samples, []
                if samples:
                    self.publish('digitizer', dict(device_id=device_id, token=token, stopped=False, events=samples))
        except Exception:
            self.disarm(token=token, owner=owner)
