"""Native Linux desktop-idle/resource probe for PC backup maintenance (#392).

Missing desktop/session/CPU/memory evidence means no background work. There is
no timer, thread, daemon or file mutation at construction/import time.
"""
import os
import threading
import time

from magnolie_file_transfer import TransferError
from magnolie_media_backup_codec import NativeBackupIdleObservation


def desktop_idle_ms():
    try:
        import dbus
        screen = dbus.SessionBus().get_object('org.freedesktop.ScreenSaver', '/ScreenSaver')
        seconds = int(screen.GetSessionIdleTime(dbus_interface='org.freedesktop.ScreenSaver', timeout=0.25))
        if 0 <= seconds <= 2**32 - 1:
            return seconds * 1000
    except Exception:
        pass
    try:
        import dbus
        session = dbus.SystemBus().get_object('org.freedesktop.login1', '/org/freedesktop/login1/session/auto')
        properties = dbus.Interface(session, 'org.freedesktop.DBus.Properties')
        idle = properties.Get('org.freedesktop.login1.Session', 'IdleHint', timeout=0.25)
        if not bool(idle):
            return 0
        since = int(properties.Get('org.freedesktop.login1.Session', 'IdleSinceHintMonotonic', timeout=0.25))
        now = time.monotonic_ns() // 1000
        if 0 < since <= now:
            return (now - since) // 1000
    except Exception:
        pass
    return None


def cpu_ticks():
    with open('/proc/stat', encoding='ascii') as stream:
        fields = stream.readline().split()
    if len(fields) < 9 or fields[0] != 'cpu':
        raise ValueError('Native CPU counters unavailable')
    values = tuple(int(item) for item in fields[1:9])
    if any(item < 0 for item in values):
        raise ValueError('Native CPU counters invalid')
    # Guest values are already included in user/nice; do not count them twice.
    return sum(values), values[3] + values[4]


def available_bytes():
    with open('/proc/meminfo', encoding='ascii') as stream:
        for line in stream:
            if line.startswith('MemAvailable:'):
                fields = line.split()
                if len(fields) == 3 and fields[2] == 'kB' and int(fields[1]) >= 0:
                    return int(fields[1]) * 1024
    raise ValueError('Native available memory unknown')


class NativeLinuxBackupIdleProbe:
    def __init__(self, *, idle=desktop_idle_ms, cpu=cpu_ticks, memory=available_bytes,
                 clock=time.monotonic_ns, own_cpu=time.thread_time_ns, tick_hz=None):
        self._idle, self._cpu, self._memory = idle, cpu, memory
        self._clock, self._own_cpu = clock, own_cpu
        self._tick_hz = os.sysconf('SC_CLK_TCK') if tick_hz is None else tick_hz
        self._thread = None
        self._sample = None
        self._observation = None

    def observe(self):
        thread = threading.get_native_id()
        if self._thread is None:
            self._thread = thread
        if thread != self._thread:
            return None
        try:
            now = self._clock()
            if self._sample is not None:
                elapsed = now - self._sample[0]
                if elapsed < 0:
                    raise ValueError('Native clock went backwards')
                if elapsed < 500_000_000:
                    return self._observation
            idle = self._idle(); total, waiting = self._cpu(); memory = self._memory(); own = self._own_cpu()
            if (type(idle) is not int or idle < 0 or type(memory) is not int or memory < 0
                    or type(total) is not int or type(waiting) is not int or not 0 <= waiting <= total
                    or type(now) is not int or type(own) is not int or own < 0 or self._tick_hz <= 0):
                raise ValueError('Native observation unavailable')
            previous = self._sample
            self._sample = (now, total, waiting, own)
            if previous is None:
                return None  # A single boot-total value cannot prove current load.
            delta = total - previous[1]; idle_delta = waiting - previous[2]; own_delta = own - previous[3]
            if delta <= 0 or not 0 <= idle_delta <= delta or own_delta < 0:
                raise ValueError('Native CPU counters changed')
            # The low-priority compressor itself is not evidence that somebody
            # started using the PC. Other CPU load still pauses this attempt.
            own_ticks = own_delta * self._tick_hz // 1_000_000_000
            busy = max(0, delta - idle_delta - own_ticks)
            percent = min(100, (busy * 100 + delta - 1) // delta)
            self._observation = NativeBackupIdleObservation(idle, percent, memory)
            return self._observation
        except Exception:
            self._sample = None; self._observation = None
            return None


def lower_current_backup_thread_priority():
    """Only a dedicated worker, never the UI/process or another process/thread.

    The worker keeps this low priority until it exits. Raising nice again would
    require privileges, so it must never be a shared interactive executor.
    """
    if threading.current_thread() is threading.main_thread():
        raise TransferError('media_backup_background_thread_required')
    os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)


class NativeLinuxBackupMaintenanceWorker:
    """One dedicated low-priority bounded pass; native UI owns polling/lifetime."""
    def __init__(self,directory,*,probe=NativeLinuxBackupIdleProbe):
        from magnolie_media_backups import NativeMediaBackupMaintenance
        self.directory=directory;self._maintenance=NativeMediaBackupMaintenance(directory)
        self._probe=probe;self._stop=threading.Event();self._gate=threading.Lock();self._thread=None
        self.last_result=None;self.last_error=None

    def start(self,current):
        if not callable(current):raise TransferError('media_backup_native_idle_required')
        with self._gate:
            if self._stop.is_set() or self._thread is not None and self._thread.is_alive():return False
            self.last_result=self.last_error=None
            def run():
                try:
                    def active():return not self._stop.is_set() and current() is True
                    if not active():return
                    lower_current_backup_thread_priority()
                    probe=self._probe();probe.observe()
                    # Native CPU load needs two real observations. Cancellation
                    # wakes this short sampling wait; never sleep on the UI.
                    if self._stop.wait(0.55) or not active():return
                    from magnolie_media_backup_codec import NativeBackupIdlePermit
                    idle=NativeBackupIdlePermit(probe.observe,active)
                    self.last_result=self._maintenance.run_once(idle,active);self.last_error=None
                except Exception as error:self.last_error=type(error).__name__
            self._thread=threading.Thread(target=run,name='magnolie-backup-maintenance',daemon=True)
            self._thread.start();return True

    def stop(self):self._stop.set()

    def join(self,timeout=None):
        with self._gate:thread=self._thread
        if thread is not None:thread.join(timeout)
        return thread is None or not thread.is_alive()
