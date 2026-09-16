#!/usr/bin/env python3
"""Offline API-35 call fixtures. EOF stdin, bounded owned processes, no GUI/device.

Requires existing SDK/Gradle/Robolectric caches, bwrap and user systemd/cgroup v2.
No dependencies are installed. Writes only to the selected /tmp/opencode workspace
and the existing Gradle dependency cache under the shared Android build lock.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
MEMORY = 6 * 1024 ** 3


def process(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        return dict(pid=pid, start=fields[19], state=fields[0], name=status['Name'].strip(),
            threads=int(status['Threads']), rss_kib=int(status.get('VmRSS', '0 kB').split()[0]),
            cgroup=Path(f'/proc/{pid}/cgroup').read_text().strip(), wait=Path(f'/proc/{pid}/wchan').read_text().strip())
    except (OSError, KeyError, IndexError):
        return None


def descendants(pid):
    pending, result = [pid], {}
    while pending:
        value = pending.pop()
        if value in result: continue
        item = process(value)
        if item is None: continue
        result[value] = item
        try:
            for children in Path(f'/proc/{value}/task').glob('*/children'):
                pending.extend(int(child) for child in children.read_text().split())
        except OSError: pass
    return result


def alive(known):
    return {pid: current for pid, old in known.items()
        if (current := process(pid)) and current['start'] == old['start']}


def reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if not pid: return
        except ChildProcessError: return


def monitor(command, cwd, output, wall=260, interval=30):
    """Wait for actual process exit, not a success log line; reap only our children."""
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError('Cannot enable child subreaper')
    started = time.monotonic()
    known, milestones = {}, []
    forced, timed_out = False, False
    with (output / 'run.log').open('wb') as log, (output / 'progress.jsonl').open('w') as progress:
        child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
        selector = selectors.DefaultSelector(); selector.register(child.stdout, selectors.EVENT_READ)
        last_progress = started - interval
        line_buffer = ''

        def event(kind, **values):
            item = {'event': kind, 'seconds': round(time.monotonic()-started, 3), **values}
            progress.write(json.dumps(item) + '\n'); progress.flush()
            print(json.dumps(item), flush=True)

        def drain(timeout):
            nonlocal line_buffer
            for key, _ in selector.select(timeout):
                data = os.read(key.fd, 65536)
                if not data: selector.unregister(key.fileobj); continue
                log.write(data); log.flush()
                line_buffer += data.decode(errors='replace')
                while '\n' in line_buffer:
                    line, line_buffer = line_buffer.split('\n', 1)
                    if any(marker in line for marker in ('BUILD SUCCESSFUL', 'BUILD FAILED', ' PASSED', ' FAILED', '> Task :app:testDebugUnitTest')):
                        milestones.append(dict(seconds=round(time.monotonic()-started, 3), text=line.strip()))
                        event('milestone', text=line.strip())

        try:
            while child.poll() is None:
                known.update(descendants(child.pid))
                now = time.monotonic()
                if now - last_progress >= interval:
                    event('progress', owned=list(alive(known).values()))
                    last_progress = now
                if now - started >= wall:
                    timed_out = True; event('deadline'); break
                drain(min(0.25, wall - (now-started)))
        finally:
            if child.poll() is None:
                forced = True
                event('terminate-owned', owned=list(alive(known).values()))
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                until = time.monotonic() + 3
                while child.poll() is None and time.monotonic() < until: drain(0.1)
                if child.poll() is None:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            code = child.wait(timeout=3)
            # Reap adopted namespace/helper children; a surviving helper is a gate failure.
            known.update({pid: item for pid, item in descendants(os.getpid()).items() if pid != os.getpid()})
            until = time.monotonic() + 2
            reap()
            while alive(known) and time.monotonic() < until:
                drain(0.05); reap()
            survivors = alive(known)
            if survivors:
                forced = True
                for pid, old in survivors.items():
                    try:
                        descriptor = os.pidfd_open(pid)
                        try:
                            if (current := process(pid)) and current['start'] == old['start']:
                                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                        finally: os.close(descriptor)
                    except ProcessLookupError: pass
                until = time.monotonic() + 2
                while alive(known) and time.monotonic() < until:
                    drain(0.05); reap()
            drain(0)
            selector.close(); child.stdout.close()
            result = dict(exit_code=code, timed_out=timed_out, forced_cleanup=forced,
                remaining_owned=list(alive(known).values()), seconds=round(time.monotonic()-started, 3),
                milestones=milestones)
            result['clean_exit'] = code == 0 and not timed_out and not forced and not result['remaining_owned']
            event('exit', **{key: value for key, value in result.items() if key != 'milestones'})
            (output / 'process-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def cgroup():
    relative = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    directory = Path('/sys/fs/cgroup') / relative.lstrip('/')
    values = {name: (directory / name).read_text().strip() for name in
        ('memory.max', 'memory.swap.max', 'memory.peak', 'cpu.max', 'cpu.stat', 'memory.events')}
    quota, period = values['cpu.max'].split()
    if values['memory.max'] == 'max' or int(values['memory.max']) > MEMORY or quota == 'max' or int(quota) > 2 * int(period):
        raise RuntimeError('Call fixture gate requires <=6 GiB and <=2 CPUs in its own cgroup')
    return values


def source_hashes():
    files = list((SOURCE / 'app/src/main').rglob('*.kt')) + list((SOURCE / 'app/src/main').rglob('*.xml'))
    files += list((SOURCE / 'app/src/test/java').rglob('*Call*Test.kt'))
    files += list((SOURCE / 'app/src/test/java').rglob('TelefonSitzungTest.kt'))
    files += [SOURCE / 'app/build.gradle.kts', SOURCE / 'gradle.properties', TOOLS / 'call_fixture.gradle',
        TOOLS / 'call_fixture_gate.py', TOOLS / 'test_call_fixture_gate.py']
    return {str(path.relative_to(SOURCE)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}


def worker(args):
    output = args.output
    limits = cgroup()
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    cache_home = args.cache_home
    sdk = cache_home / '.local/share/android-sdk'
    gradle = cache_home / '.gradle/wrapper/dists/gradle-8.13-bin/5xuhj0ry160q40clulazy9h7d/gradle-8.13/bin/gradle'
    required = [sdk, gradle, cache_home / '.gradle/caches', cache_home / '.m2/repository/org/robolectric']
    if any(not path.exists() for path in required): raise RuntimeError('Required offline SDK/Gradle/Robolectric cache is unavailable')
    for name in ('home/.m2/repository', 'gradle', 'app-build', 'root-build', 'cache', 'tmp', 'kotlin', 'trace'):
        (output / name).mkdir(parents=True, exist_ok=True)
    started_wall = time.time()
    before = source_hashes()
    (output / 'sources-before.json').write_text(json.dumps(before, indent=2) + '\n')
    with open('/tmp/opencode/android-build.lock', 'a') as lock:
        deadline = time.monotonic() + 20
        while True:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise RuntimeError('Shared Android slot busy (20-second wait limit)')
                time.sleep(0.2)
        command = ['bwrap', '--die-with-parent', '--unshare-net', '--unshare-pid', '--as-pid-1',
            '--ro-bind', '/', '/', '--tmpfs', '/tmp', '--tmpfs', '/run', '--tmpfs', '/home',
            '--ro-bind', str(SOURCE), str(SOURCE), '--ro-bind', str(sdk), str(sdk),
            '--bind', str(output), str(output),
            '--bind', str(cache_home / '.gradle/caches'), str(output / 'gradle/caches'),
            '--ro-bind', str(cache_home / '.gradle/wrapper'), str(output / 'gradle/wrapper'),
            '--ro-bind', str(cache_home / '.m2/repository/org/robolectric'), str(output / 'home/.m2/repository/org/robolectric'),
            '--bind', str(output / 'app-build'), str(SOURCE / 'app/build'),
            '--bind', str(output / 'root-build'), str(SOURCE / 'build'),
            '--bind', str(output / 'kotlin'), str(SOURCE / '.kotlin'), '--proc', '/proc', '--dev', '/dev', '--clearenv']
        environment = dict(PATH='/usr/bin:/bin', HOME=str(output / 'home'), JAVA_HOME='/usr/lib/jvm/java-17-openjdk-amd64',
            JAVA_TOOL_OPTIONS=f'-Duser.home={output}/home -Djava.io.tmpdir={output}/tmp -XX:ActiveProcessorCount=2 -Djava.awt.headless=true',
            ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk), GRADLE_USER_HOME=str(output / 'gradle'),
            XDG_CONFIG_HOME=str(output / 'home/config'), XDG_DATA_HOME=str(output / 'home/data'),
            XDG_CACHE_HOME=str(output / 'home/cache'), XDG_STATE_HOME=str(output / 'home/state'),
            TMPDIR=str(output / 'tmp'), LANG='C.UTF-8', MAGNOLIE_CALL_TRACE_DIR=str(output / 'trace'),
            MAGNOLIE_SCHLUESSEL_PROPERTIES=str(output / 'absent-signing.properties'), MAGNOLIE_KEYSTORE_FILE=str(output / 'absent-keystore'))
        for key, value in environment.items(): command += ['--setenv', key, value]
        variant = args.variant.capitalize()
        command += ['--chdir', str(SOURCE), str(output / 'gradle/wrapper' / gradle.relative_to(cache_home / '.gradle/wrapper')),
            '--offline', '--no-daemon', '--max-workers=1', '--no-parallel', '--no-build-cache',
            '--project-cache-dir', str(output / 'cache'), '--console=plain',
            '-Dorg.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=384m -XX:ActiveProcessorCount=2 -Dfile.encoding=UTF-8',
            '-Pkotlin.compiler.execution.strategy=in-process', '-I', str(TOOLS / 'call_fixture.gradle'),
            f':app:test{variant}UnitTest', '--tests', '*CallLifecycleTransportTest', '--tests', '*CallControlOriginTrackerTest', '--tests', '*TelefonSitzungTest']
        # Unit classes only: never load a signing key or schedule APK packaging.
        if args.variant == 'release': command += ['-x', ':app:pruefeReleaseSigningKonfiguration']
        result = monitor(command, SOURCE, output)
    suites = []
    for name in ('CallLifecycleTransportTest', 'CallControlOriginTrackerTest', 'TelefonSitzungTest'):
        path = output / f'app-build/test-results/test{variant}UnitTest/TEST-io.gitlab.maik3531.magnolienotes.telefon.{name}.xml'
        if path.exists() and path.stat().st_mtime >= started_wall:
            root = ET.parse(path).getroot()
            suites.append(dict(name=name, **{key: int(root.attrib[key]) for key in ('tests', 'failures', 'errors', 'skipped')}))
    after = source_hashes()
    (output / 'sources-after.json').write_text(json.dumps(after, indent=2) + '\n')
    result.update(suites=suites, sources_unchanged=before == after, limits_before=limits, limits_after=cgroup(),
        affinity=sorted(os.sched_getaffinity(0)), source=str(SOURCE), command=command,
        started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(started_wall)),
        ended_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    expected_tests = {'CallLifecycleTransportTest': 12, 'CallControlOriginTrackerTest': 7, 'TelefonSitzungTest': 8}
    result['passed'] = result['clean_exit'] and {s['name']: s['tests'] for s in suites} == expected_tests and all(
        s['failures'] == s['errors'] == s['skipped'] == 0 for s in suites) and before == after
    (output / 'gate-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=result['passed'], suites=suites, clean_exit=result['clean_exit'], seconds=result['seconds'])), flush=True)
    return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/opencode/latest-call-clean'))
    parser.add_argument('--cache-home', type=Path, default=Path.home())
    parser.add_argument('--variant', choices=('debug', 'release'), default='debug')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output = args.output.resolve(); args.cache_home = args.cache_home.resolve()
    if not args.output.is_relative_to('/tmp/opencode') or args.output == Path('/tmp/opencode'):
        parser.error('Output must be a private child of /tmp/opencode')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.worker:
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        return worker(args)
    unit = 'magnolie-call-fixture-' + uuid.uuid4().hex
    command = ['systemd-run', '--user', '--wait', '--pipe', '--collect', '--unit=' + unit,
        '-p', 'MemoryMax=6G', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=200%', '-p', 'RuntimeMaxSec=285',
        '-p', 'TimeoutStopSec=5', '-p', 'KillMode=control-group', sys.executable, '-B', str(Path(__file__).resolve()),
        '--worker', '--output', str(args.output), '--cache-home', str(args.cache_home), '--variant', args.variant]
    started_ns = time.time_ns()
    try:
        code = subprocess.run(command, stdin=subprocess.DEVNULL, timeout=295).returncode
        if code: return code
        # systemd can classify a SIGINT-terminated worker as successful. Only a
        # fresh worker result proves clean child exit, fresh tests and hash binding.
        record = args.output / 'gate-result.json'
        try:
            value = json.loads(record.read_text())
            if record.stat().st_mtime_ns >= started_ns and isinstance(value, dict) and \
                    value.get('passed') is True and value.get('clean_exit') is True:
                return 0
        except (OSError, ValueError, TypeError):
            pass
        print('Call fixture gate: missing fresh, clean, successful worker result', file=sys.stderr)
        return 1
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        subprocess.run(['systemctl', '--user', 'kill', '--signal=SIGKILL', unit], stdin=subprocess.DEVNULL, timeout=3)
        return 124


if __name__ == '__main__':
    sys.exit(main())
