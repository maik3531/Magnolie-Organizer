#!/usr/bin/env python3
"""Bounded sole-slot emulator owner. Importing this module starts nothing."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SDK = Path.home() / ".local/share/android-sdk"
STATE = ROOT / "artifacts/emulator-session.json"
RUNTIME = 20 * 60
BOOT = 3 * 60
TEST = 120
PROGRESS = 30
GRACE = 5
STAGES = ('basics', 'restart', 'layout', 'time', 'navigation', 'saf', 'fault', 'print',
          'notifications', 'seed-reboot', 'verify-reboot')


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def identity(pid):
    """Linux boot/start-time/uid identity survives exec, unlike a command-name fence."""
    try:
        base = Path('/proc') / str(pid)
        fields = (base / 'stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, start=fields[19], uid=base.stat().st_uid,
                    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    except FileNotFoundError:
        return None


def exact_signal(expected, sig):
    """Pin PID before checking identity; never signal a recycled PID or process group."""
    if not expected:
        return False
    try:
        fd = os.pidfd_open(expected['pid'])
    except ProcessLookupError:
        return False
    try:
        if identity(expected['pid']) != expected:
            return False
        signal.pidfd_send_signal(fd, sig)
        return True
    except ProcessLookupError:
        return False
    finally:
        os.close(fd)


def zombie(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z'
    except FileNotFoundError:
        return False


def owns_adb_socket(expected):
    if not expected or identity(expected['pid']) != expected or zombie(expected['pid']):
        return False
    try:
        sockets = {os.readlink(fd) for fd in (Path('/proc') / str(expected['pid']) / 'fd').iterdir()}
        for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == '0100007F:13AF' and fields[3] == '0A' and f'socket:[{fields[9]}]' in sockets:
                return True  # 127.0.0.1:5039, LISTEN, owned fd inode
    except (FileNotFoundError, ProcessLookupError):
        pass
    return False


@contextmanager
def locks(paths):
    """Nonblocking, persistent-inode leases. Missing coordination roots fail closed."""
    held = []
    try:
        for path in sorted(set(map(Path, paths))):
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            held.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError(f'Unsafe lock: {path}')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f'Coordination slot busy: {path}') from exc
            current = path.stat(follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError(f'Lock inode changed: {path}')
        yield
    finally:
        for fd in reversed(held):
            os.close(fd)  # Do not unlink: other owners may already hold this inode.


def lock_paths(opts):
    return [opts.vm_root / 'sole-vm.lock', opts.session_root / 'sole-vm.lock',
            Path('/tmp/opencode/android-build.lock'), Path('/tmp/opencode/native-layout.lock'),
            Path('/tmp/opencode/magnolie-global-heavy.lock')]


def pin_two_cpus():
    """Keep the two-logical-CPU limit, preferring different physical cores."""
    allowed = sorted(os.sched_getaffinity(0))
    selected, seen = [], set()
    for cpu in allowed:
        topology = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        try:
            core = ((topology / 'physical_package_id').read_text().strip(),
                    (topology / 'core_id').read_text().strip())
        except OSError:
            core = ('unknown', str(cpu))
        if core not in seen:
            seen.add(core)
            selected.append(cpu)
        if len(selected) == 2:
            break
    selected += [cpu for cpu in allowed if cpu not in selected][:2-len(selected)]
    os.sched_setaffinity(0, selected)
    return selected


def memory_usage():
    try:
        relative = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1].lstrip('/')
        group = Path('/sys/fs/cgroup') / relative
        return {'memoryCurrentBytes': int((group / 'memory.current').read_text()),
                'memoryPeakBytes': int((group / 'memory.peak').read_text()),
                'cpuStat': dict((k, int(v)) for k, v in
                                (line.split() for line in (group / 'cpu.stat').read_text().splitlines())),
                'cpuPressure': (group / 'cpu.pressure').read_text().strip(),
                'hostCpuPressure': Path('/proc/pressure/cpu').read_text().strip()}
    except (OSError, ValueError, IndexError):
        return {}


class Deadline(RuntimeError):
    pass


class Stopped(RuntimeError):
    pass


class Owner:
    def __init__(self, state=None, state_path=None, runtime=RUNTIME, progress=PROGRESS):
        self.start = time.monotonic()
        self.deadline = self.start + runtime
        self.progress = progress
        self.next_progress = self.start
        self.signal = None
        self.children = []
        self.state_path = state_path
        self.state = dict(state or {}, owner=identity(os.getpid()), ownerPid=os.getpid(),
                          startedUtc=stamp(), runtimeSeconds=runtime, children=[], events=[])

    def record(self, phase, **values):
        self.state.update(phase=phase, updatedUtc=stamp(), elapsedSeconds=round(time.monotonic()-self.start, 3), **values)
        event = dict(utc=self.state['updatedUtc'], elapsed=self.state['elapsedSeconds'], phase=phase, **values)
        self.state['events'].append(event)
        self.state['events'] = self.state['events'][-200:]
        if self.state_path:
            # Atomic publication; a reader must never observe half-written JSON.
            temp = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=self.state_path.parent, delete=False) as stream:
                    temp = Path(stream.name)
                    json.dump(self.state, stream, indent=2)
                    stream.write('\n')
                os.replace(temp, self.state_path)
            except OSError as exc:
                # A full disk must not prevent TERM/wait/KILL/reap in a finally block.
                self.state['stateWriteError'] = str(exc)
                print(f'[{stamp()}] state write failed: {exc}', file=sys.stderr, flush=True)
            finally:
                if temp:
                    try:
                        temp.unlink(missing_ok=True)
                    except OSError:
                        pass
        print(f"[{event['utc']}] elapsed={event['elapsed']:.1f}s {phase} {json.dumps(values)}", flush=True)
        self.next_progress = time.monotonic() + self.progress

    @contextmanager
    def signals(self):
        previous = {}
        def stop(sig, _frame):
            self.signal = self.signal or sig  # Do not interrupt spawn/registration or cleanup.
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, stop)
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    def check(self, deadline=None):
        if self.signal:
            raise Stopped(signal.Signals(self.signal).name)
        if time.monotonic() >= min(self.deadline, deadline or self.deadline):
            raise Deadline('Deadline exceeded')
        if time.monotonic() >= self.next_progress:
            self.record(self.state.get('phase', 'running'), progress=True, **memory_usage())

    def spawn(self, args, label, **kwargs):
        self.check()
        child = subprocess.Popen([str(x) for x in args], **kwargs)
        item = dict(label=label, identity=identity(child.pid), pid=child.pid, exit=None)
        self.children.append((child, item))
        self.state['children'].append(item)
        self.record(label + '-started', pid=child.pid)
        return child

    def wait(self, child, timeout):
        deadline = min(self.deadline, time.monotonic() + timeout)
        while True:
            self.check(deadline)
            try:
                code = child.wait(timeout=min(0.25, max(0.001, deadline-time.monotonic())))
                for process, item in self.children:
                    if process is child:
                        item['exit'] = code
                self.record('child-exited', pid=child.pid, actualExit=code)
                return code
            except subprocess.TimeoutExpired:
                pass

    def stop_child(self, child, item):
        # poll()/wait() reap zombies; sending KILL to a zombie cannot reap it.
        if child.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                sent = exact_signal(item['identity'], sig)
                self.record('cleanup', pid=child.pid, signal=signal.Signals(sig).name, identityMatched=sent)
                try:
                    child.wait(timeout=GRACE)
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:
                raise RuntimeError(f"Owned PID {child.pid} did not reap within cleanup deadline")
        item['exit'] = child.wait(timeout=GRACE)
        self.record('child-reaped', pid=child.pid, actualExit=item['exit'])

    def close(self):
        errors = []
        for child, item in reversed(self.children):
            try:
                self.stop_child(child, item)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))

    def command(self, args, timeout=30, env=None, input=None):
        # File-backed output avoids PIPE deadlocks and preserves bounded waits.
        with tempfile.TemporaryFile(mode='w+') as output, tempfile.TemporaryFile(mode='w+') as source:
            if input is not None:
                source.write(input)
                source.seek(0)
            child = self.spawn(args, 'command', env=env, stdin=source, stdout=output, stderr=subprocess.STDOUT)
            try:
                code = self.wait(child, timeout)
            finally:
                self.stop_child(child, next(item for p, item in self.children if p is child))
            output.seek(0)
            text = output.read()
            if code:
                raise subprocess.CalledProcessError(code, args, output=text)
            return text


def idle(owner):
    for scope in ('qemu:///system', 'qemu:///session'):
        result = owner.command(['virsh', '-c', scope, 'list', '--name'], timeout=10)
        if result.strip():
            raise RuntimeError('Another VM is active: ' + result)
    result = owner.command(['ps', '-eo', 'pid=,comm=,args='], timeout=10)
    for line in result.splitlines():
        pid, name, *args = line.split(None, 2)
        if int(pid) == os.getpid():
            continue
        vm = name.startswith(('qemu-system', 'qemu-kvm', 'emulator', 'VBoxHeadless', 'vmware-vmx', 'crosvm'))
        heavy = re.search(r'GradleDaemon|Gradle Test Executor|GradleWrapperMain|KotlinCompileDaemon|dpkg-buildpackage|rpmbuild|flatpak-builder|autopkgtest', ' '.join(args))
        if vm or heavy:
            raise RuntimeError(f'Another VM/compiler is active: {line}')


def environment(run):
    env = os.environ.copy()
    env.update(ANDROID_HOME=str(SDK), ANDROID_SDK_ROOT=str(SDK), HOME=str(run / 'home'),
        ANDROID_USER_HOME=str(run / 'android-user'), ANDROID_AVD_HOME=str(run / 'avds'),
        ANDROID_EMULATOR_HOME=str(run / 'android-user'), ANDROID_ADB_SERVER_PORT='5039',
        ADB_SERVER_SOCKET='tcp:127.0.0.1:5039', ADB_MDNS_AUTO_CONNECT='', ADB_LIBUSB='0',
        JAVA_HOME='/usr/lib/jvm/java-17-openjdk-amd64', LIBGL_ALWAYS_SOFTWARE='1')
    return env


def live_state(path):
    state = json.loads(path.read_text())
    if state.get('phase') in ('finished', 'cleanup-failed') or not state.get('owner') or identity(state['owner']['pid']) != state['owner'] or zombie(state['owner']['pid']):
        raise RuntimeError('No identity-verified live session owner; stale state cannot authorize ADB or stop')
    return state


def adb(owner, state, args, timeout=30):
    server = state.get('adbIdentity')
    if not owns_adb_socket(server) or state.get('adbPort') != 5039:
        raise RuntimeError('The dedicated owned ADB server is absent')
    if not args or args[0] not in ('shell', 'exec-out', 'logcat', 'pull', 'push', 'install', 'get-state'):
        raise RuntimeError('Only device commands are accepted; server/transport overrides are forbidden')
    return owner.command([SDK / 'platform-tools/adb', '-P', '5039', '-s', 'emulator-5580', *args],
                         timeout=timeout, env=environment(Path(state['run'])))


def prepare(owner, opts):
    idle(owner)
    run = Path.home() / '.local/share/magnolie-testing/tablet-beta' / datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    run.mkdir(parents=True, exist_ok=False)
    for name in ('home', 'android-user', 'avds', 'evidence'):
        (run / name).mkdir()
    name = 'Magnolie_Tablet_Beta_' + run.name
    owner.command([SDK / 'cmdline-tools/latest/bin/avdmanager', 'create', 'avd', '--name', name,
        '--package', f'system-images;android-{opts.api};google_apis;x86_64', '--device', 'medium_tablet',
        '--path', run / 'avds' / (name + '.avd')], input='no\n', env=environment(run), timeout=BOOT)
    config = run / 'avds' / (name + '.avd') / 'config.ini'
    entries = dict(line.split('=', 1) for line in config.read_text().splitlines() if '=' in line)
    entries.update({'hw.lcd.width': '1280', 'hw.lcd.height': '800', 'hw.lcd.density': '160',
        'hw.ramSize': '2048', 'hw.cpu.ncore': '2', 'hw.keyboard': 'yes', 'hw.gpu.enabled': 'yes',
        'hw.gpu.mode': 'swiftshader', 'skin.name': '1280x800', 'showDeviceFrame': 'no', 'disk.dataPartition.size': '4G'})
    config.write_text(''.join(f'{k}={v}\n' for k, v in entries.items()))
    versions = {}
    for label, directory in {'systemImage': SDK / f'system-images/android-{opts.api}/google_apis/x86_64',
                             'emulator': SDK / 'emulator', 'platformTools': SDK / 'platform-tools',
                             'commandLineTools': SDK / 'cmdline-tools/latest'}.items():
        data = (directory / 'source.properties').read_bytes()
        versions[label] = dict(sourceProperties=data.decode(), sha256=hashlib.sha256(data).hexdigest())
    (run / 'evidence/sdk-versions.json').write_text(json.dumps(versions, indent=2)+'\n')
    owner.state_path = opts.state
    owner.record('prepared', run=str(run), avd=name, serial='emulator-5580', adbPort=5039,
                 requestedApi=opts.api, compileApi=35, guestRamMiB=2048, cores=2, sdkVersions=versions)


def run_session(owner, opts, after_boot=None, run_tests=None):
    idle(owner)
    state = json.loads(opts.state.read_text())
    if state.get('requestedApi', state.get('runtimeApi')) != opts.api:
        raise RuntimeError('Prepared image API differs from requested API')
    run = Path(state['run'])
    owner.state.update({k: state[k] for k in ('run', 'avd', 'serial', 'adbPort')})
    owner.state.update(requestedApi=opts.api, sdkVersions=state.get('sdkVersions', {}))
    owner.state_path = opts.state
    owner.record('starting', locks=[str(p) for p in lock_paths(opts)], bootSeconds=opts.boot_timeout,
                 testSeconds=opts.test_timeout, permission='main-slot-granted')
    for port in (5039, 5580, 5581):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    env = environment(run)
    # A foreground server is a direct waitable child. Never use global kill-server,
    # start-server, pkill or a server selected by port alone.
    with (run / 'evidence' / ('session-' + str(time.time_ns()) + '.log')).open('w') as log:
        # Server-side -L does not accept a hostname in this SDK. Without -a,
        # tcp:5039 binds loopback; owns_adb_socket still requires 127.0.0.1.
        server = owner.spawn([SDK / 'platform-tools/adb', '-L', 'tcp:5039',
            '--one-device', 'MagnolieTabletSyntheticOnly', 'server', 'nodaemon'], 'adb5039', env=env, stdout=log, stderr=subprocess.STDOUT)
        owner.record('adb-starting', adbIdentity=identity(server.pid))
        ready = time.monotonic() + 15
        while True:
            owner.check(ready)
            if server.poll() is not None:
                raise RuntimeError(f'Owned ADB server exited: {server.returncode}')
            if owns_adb_socket(owner.state['adbIdentity']):
                break
            time.sleep(0.2)
        child = owner.spawn([SDK / 'emulator/emulator', '-avd', state['avd'], '-port', '5580', '-cores', '2',
            '-memory', '2048', '-gpu', 'swangle', '-no-audio', '-no-snapshot', '-no-boot-anim',
            '-no-window', '-no-metrics', '-feature', '-Vulkan', '-camera-back', 'none', '-camera-front', 'none'],
            'emulator', env=env, stdout=log, stderr=subprocess.STDOUT)
        owner.record('booting', emulatorPid=child.pid, emulatorIdentity=identity(child.pid))
        boot_deadline = min(owner.deadline, time.monotonic() + opts.boot_timeout)
        while True:
            owner.check(boot_deadline)
            if child.poll() is not None:
                return child.returncode or 1
            try:
                remaining = boot_deadline - time.monotonic()
                if adb(owner, owner.state, ['shell', 'getprop', 'sys.boot_completed'], min(10, remaining)).strip() == '1':
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(1)
        adb(owner, owner.state, ['shell', 'input', 'keyevent', '82'], timeout=10)
        owner.record('ready', booted=True)
        actual_api = adb(owner, owner.state, ['shell', 'getprop', 'ro.build.version.sdk'], 20).strip()
        webview = adb(owner, owner.state, ['shell', 'dumpsys', 'webviewupdate'], 20)
        properties = adb(owner, owner.state, ['shell', 'getprop'], 20)
        (run / 'evidence/webview-runtime.txt').write_text(webview)
        (run / 'evidence/device-runtime.txt').write_text(properties)
        owner.record('actual-runtime', runtimeApi=int(actual_api), webviewRuntime=webview)
        if int(actual_api) != opts.api:
            raise RuntimeError('Actual runtime API differs from requested API')
        if after_boot:
            after_boot(owner, owner.state)
        if run_tests:
            return run_tests(owner, owner.state)
        if opts.test:
            for selector in opts.test:
                run_test(owner, owner.state, selector, opts.test_timeout)
            return 0
        # External bounded commands may use this session until its hard deadline.
        return owner.wait(child, max(0.001, owner.deadline-time.monotonic()))


def run_test(owner, state, selector, timeout):
    if selector not in STAGES:
        raise ValueError('Select one existing native stage: ' + ', '.join(STAGES))
    owner.record('test', test=selector, testTimeoutSeconds=timeout)
    output = adb(owner, state, ['shell', 'am', 'instrument', '-w', '-r', '-e', 'stage', selector,
        'io.gitlab.maik3531.magnolieorganizer.tablet.beta.test/io.gitlab.maik3531.magnolietabletbeta.NativeTabletInstrumentation'], timeout)
    print(output, flush=True)
    marker = 'INSTRUMENTATION_RESULT: stream='
    try:
        proof, _ = json.JSONDecoder().raw_decode(output.split(marker, 1)[1].lstrip())
    except (ValueError, IndexError) as exc:
        raise RuntimeError('Native stage did not report a JSON result') from exc
    if proof.get('stage') != selector or proof.get('passed') is not True or not re.search(r'INSTRUMENTATION_CODE:\s*-1\b', output):
        raise RuntimeError('Native stage did not report success')
    if state.get('expectedSourceHash') and proof.get('sourceHash') != state['expectedSourceHash']:
        raise RuntimeError('Native stage tested a different source snapshot')
    owner.record('test-passed', test=selector, sourceHash=proof.get('sourceHash'))


def request_stop(state, timeout=30):
    if not exact_signal(state.get('owner'), signal.SIGTERM):
        raise RuntimeError('Owner identity changed; refusing stop')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if identity(state['owner']['pid']) != state['owner'] or zombie(state['owner']['pid']):
            return
        # A caller cannot reap an unrelated parent. The owner reaps its children.
        time.sleep(0.2)
    raise Deadline('Owner did not finish cleanup within stop deadline')


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('Must be a finite positive number')
    return result


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('action', choices=['prepare', 'run', 'wait', 'collect', 'stop', 'adb', 'test'])
    result.add_argument('--state', type=Path, default=STATE)
    result.add_argument('--api', type=int, choices=(34, 35), default=34)
    result.add_argument('--vm-root', type=Path, default=ROOT.parents[1] / 'Test-VMs-20260912')
    result.add_argument('--session-root', type=Path, default=Path(os.environ.get('SESS', str(Path.home() / '.local/share/magnolie-testing/vms/rebuild-20260912'))))
    result.add_argument('--main-slot-granted', action='store_true', help='Only after explicit main-owner sole-slot permission')
    result.add_argument('--runtime', type=positive, default=RUNTIME)
    result.add_argument('--boot-timeout', type=positive, default=BOOT)
    result.add_argument('--test-timeout', type=positive, default=TEST)
    result.add_argument('--progress', type=positive, default=PROGRESS)
    result.add_argument('--test', action='append', default=[])
    result.add_argument('args', nargs='*', help='Use -- before device arguments')
    return result


def main(argv=None):
    opts = parser().parse_args(argv)
    if opts.progress > 60 or opts.runtime > RUNTIME or opts.boot_timeout > BOOT or opts.test_timeout > TEST:
        raise SystemExit('Progress <=60s, runtime <=1200s, boot <=180s and test <=120s required')
    if opts.action == 'run' and not opts.main_slot_granted:
        raise SystemExit('Main-owner sole-slot permission is required; no emulator started')
    owner = Owner(runtime=opts.runtime, progress=opts.progress)
    code = 1
    external = None
    with owner.signals():
        @contextmanager
        def scope():
            if opts.action in ('prepare', 'run'):
                with locks(lock_paths(opts)):
                    yield
            else:
                yield
        # Hold leases through child termination, wait/reap and final state publication.
        with scope():
            try:
                if opts.action == 'prepare':
                    prepare(owner, opts)
                    code = 0
                elif opts.action == 'run':
                    code = run_session(owner, opts)
                else:
                    external = live_state(opts.state)
                    if opts.action == 'stop':
                        request_stop(external)
                    elif opts.action == 'wait':
                        deadline = time.monotonic() + opts.boot_timeout
                        while not live_state(opts.state).get('booted'):
                            owner.check(deadline)
                            time.sleep(0.25)
                    elif opts.action == 'adb':
                        print(adb(owner, external, opts.args, opts.test_timeout), flush=True)
                    elif opts.action == 'test':
                        if not opts.args:
                            raise ValueError('Specify individual native test stages')
                        for selector in opts.args:
                            run_test(owner, external, selector, opts.test_timeout)
                    elif opts.action == 'collect':
                        out = Path(external['run']) / 'evidence'
                        for name, args in {'alarms': ['shell', 'dumpsys', 'alarm'], 'notifications': ['shell', 'dumpsys', 'notification'],
                                           'webview': ['shell', 'dumpsys', 'webviewupdate'], 'logcat': ['logcat', '-d', '-v', 'threadtime']}.items():
                            (out / (name + '.txt')).write_text(adb(owner, external, args, opts.test_timeout))
                        package = 'io.gitlab.maik3531.magnolieorganizer.tablet.beta'
                        print(adb(owner, external, ['pull', '/sdcard/Android/data/' + package + '/files/native-evidence',
                                                  str(out)], opts.test_timeout), flush=True)
                    code = 0
            except Stopped as exc:
                code = 128 + owner.signal
                owner.record('interrupted', reason=str(exc))
            except Deadline as exc:
                code = 124
                owner.record('timeout', reason=str(exc))
            except Exception as exc:
                owner.record('failed', reason=str(exc))
            finally:
                try:
                    owner.close()
                    if external and code and opts.action != 'stop':
                        request_stop(external)
                    owner.record('finished', exitCode=code)
                except Exception as exc:
                    code = 1
                    owner.record('cleanup-failed', reason=str(exc), exitCode=code)
    return code


if __name__ == '__main__':
    sys.exit(main())
