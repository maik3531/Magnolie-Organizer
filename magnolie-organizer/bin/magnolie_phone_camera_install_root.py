"""Fixed code sent to isolated SYSTEM Python, never a root-imported user file."""

ROOT_PACKAGE = r'''
import threading

def package_api():
    import gi
    gi.require_version('PackageKitGlib', '1.0')
    from gi.repository import PackageKitGlib, Gio
    return PackageKitGlib, Gio

def install_package(current, plan, *, api=package_api, timer=threading.Timer,
                    clock=time.monotonic, register_cancel=None):
    def require_current():
        if current() is False: raise PermissionError('webcam_original_choice_changed')
    require_current()
    if plan != 'v4l2loopback-dkms': return 'driver_installation_unavailable'
    try: pk, gio = api()
    except (ImportError, ValueError): return 'driver_installation_unavailable'
    cancellation = gio.Cancellable()
    expired = threading.Event()
    deadline = clock() + 600
    errors = []
    def timeout():
        expired.set(); cancellation.cancel()
    watchdog = timer(600, timeout)
    watchdog.daemon = True
    def check():
        if clock() >= deadline: timeout()
        if expired.is_set(): raise TimeoutError('driver_installation_pending')
        if errors: raise errors[0]
        require_current()
    def progress(*args):
        try: check()
        except Exception as error:
            errors.append(error); cancellation.cancel()
    if register_cancel is not None: register_cancel(cancellation.cancel)
    watchdog.start()
    try:
        client = pk.Client()
        # The ONE pkexec approval already covers this root operation. PackageKit
        # must fail closed rather than opening a second authorization dialog.
        client.set_interactive(False)
        check()
        filters = sum(1 << int(value) for value in (pk.FilterEnum.NOT_INSTALLED, pk.FilterEnum.ARCH, pk.FilterEnum.NEWEST))
        result = client.resolve(filters, [plan], cancellation, progress, None)
        check()
        if result.get_error_code() is not None or result.get_exit_code() != pk.ExitEnum.SUCCESS:
            return 'driver_installation_failed'
        packages = result.get_package_array()
        if len(packages) != 1 or packages[0].get_name() != plan:
            return 'driver_installation_unavailable'
        package_id = packages[0].get_id()
        check()
        result = client.install_packages(1 << int(pk.TransactionFlagEnum.ONLY_TRUSTED),
            [package_id], cancellation, progress, None)
        check()
        return '' if result.get_error_code() is None and result.get_exit_code() == pk.ExitEnum.SUCCESS else 'driver_installation_failed'
    except PermissionError: raise
    except Exception:
        if expired.is_set(): return 'driver_installation_pending'
        if errors: raise errors[0]
        return 'driver_installation_failed'
    finally:
        watchdog.cancel()
'''

ROOT_LEASE = r'''
import select, struct

def installation_deadline_expired(signum, frame):
    raise TimeoutError('setup_deadline_expired')

class OriginalInstallLease:
    # This input is ONLY fresh binary monotonic heartbeats, never commands,
    # package names, paths, JSON preferences or passwords.
    def __init__(self, deadline, fd=0, *, clock=time.monotonic, interrupt=None, grace=None):
        self.deadline, self.fd, self.clock = deadline, fd, clock
        self.interrupt = interrupt or (lambda: os.kill(os.getpid(), signal.SIGALRM))
        self.grace = grace or (lambda: signal.setitimer(signal.ITIMER_REAL, 5))
        self.latest = None
        self.buffer = b''
        self.lock = threading.RLock()
        self.ended = threading.Event()
        self.revoked = False
        self.configuring = False
        self.callbacks = []
        self.worker = None
        os.set_blocking(fd, False)

    def receive(self, timeout):
        if select.select([self.fd], [], [], timeout)[0]:
            try: data = os.read(self.fd, 4096)
            except BlockingIOError: return
            if not data: raise PermissionError('webcam_installation_parent_closed')
            self.buffer += data
            complete = len(self.buffer) // 8 * 8
            if complete:
                stamp = struct.unpack('!d', self.buffer[complete-8:complete])[0]
                if not math.isfinite(stamp): raise PermissionError('webcam_installation_heartbeat_invalid')
                with self.lock: self.latest = stamp
                self.buffer = self.buffer[complete:]

    def require(self):
        with self.lock:
            now = self.clock()
            if (self.revoked or not math.isfinite(now) or now >= self.deadline or self.latest is None or
                    not -.1 <= now - self.latest <= 1.5):
                raise PermissionError('webcam_original_installation_context_changed')

    def acquire(self):
        # Discard queued OLD heartbeats from the administrator dialog. A fresh
        # caller stamp is required after authorization, before ANY package IO.
        started = time.monotonic()
        while time.monotonic() - started < 2:
            self.receive(.05)
            try: self.require(); return
            except PermissionError:
                if self.clock() >= self.deadline: raise
        raise PermissionError('webcam_installation_parent_not_current')

    def register_cancel(self, callback):
        with self.lock:
            self.callbacks.append(callback)
            revoked = self.revoked
        if revoked: callback()

    def revoke(self):
        with self.lock:
            self.revoked = True
            callbacks = list(self.callbacks)
            configuring = self.configuring
        for callback in callbacks:
            try: callback()
            except Exception: pass
        # During setup, interrupt enable() so its existing exact-owned rollback
        # runs. During PackageKit, native cancellation gets a bounded grace.
        if configuring: self.interrupt()

    def watch(self):
        while not self.ended.is_set():
            try:
                self.receive(.05)
                self.require()
            except Exception:
                if not self.ended.is_set():
                    self.revoke()
                    if not self.configuring:
                        self.grace()
                return

    def start(self):
        self.worker = threading.Thread(target=self.watch, name='Magnolie installation lease', daemon=True)
        self.worker.start()

    def begin_setup(self):
        with self.lock:
            self.require()
            self.configuring = True

    def close(self):
        self.ended.set()
        if self.worker is not None: self.worker.join(1)

def run_combined(lease, *, package=install_package, setup=enable,
                 loaded=lambda: os.path.isdir('/sys/module/v4l2loopback')):
    reason = package(lease.require, 'v4l2loopback-dkms', register_cancel=lease.register_cancel)
    lease.require()
    if reason:
        return {'driver_installation_unavailable': 74, 'driver_installation_pending': 72}.get(reason, 71)
    lease.begin_setup()
    setup()
    lease.require()
    if not loaded(): return 70
    return 0
'''

ROOT_ENTRY = r'''
if __name__ == '__main__':
    if os.geteuid() != 0 or len(sys.argv) != 2: sys.exit(77)
    lease = None
    try:
        deadline = float(sys.argv[1])
        remaining = deadline - time.monotonic()
        if not math.isfinite(deadline) or not 0 < remaining <= 710: raise TimeoutError('setup_deadline_expired')
        signal.signal(signal.SIGALRM, installation_deadline_expired)
        signal.setitimer(signal.ITIMER_REAL, remaining + 5)
        lease = OriginalInstallLease(deadline)
        lease.acquire()
        lease.start()
        result = run_combined(lease)
    except PermissionError: result = 73
    except TimeoutError: result = 72
    except Exception: result = 70
    finally:
        if lease is not None: lease.close()
        signal.setitimer(signal.ITIMER_REAL, 0)
    sys.exit(result)
'''
