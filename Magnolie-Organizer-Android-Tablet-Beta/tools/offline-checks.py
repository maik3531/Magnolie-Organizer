#!/usr/bin/env python3
"""Bounded offline checks; run inside the resource-limited user service in README."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--jvm', action='store_true', help='Only offline unit tests; no APK, signing or install tasks')
    mode.add_argument('--build', action='store_true', help='Offline tests, then debug app and test-only instrumentation APKs')
    opts = parser.parse_args()
    os.chdir(ROOT)
    cpus = session.pin_two_cpus()
    cgroup = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1].lstrip('/')
    memory = (cgroup / 'memory.max').read_text().strip()
    quota, period = (cgroup / 'cpu.max').read_text().split()
    if memory == 'max' or int(memory) > 6 * 1024**3 or quota == 'max' or int(quota) > 2 * int(period):
        raise SystemExit('Run inside a service with MemoryMax=6G and CPUQuota=200% (README)')
    owner = session.Owner(runtime=870 if opts.build else 540,
                          state_path=ROOT / ('artifacts/debug-build.json' if opts.build else 'artifacts/offline-checks.json'))
    config = session.parser().parse_args(['prepare'])
    runtime = os.environ.get('MAGNOLIE_JS_RUNTIME', 'bun')
    env = dict(os.environ, JAVA_HOME=os.environ.get('JAVA_HOME', '/usr/lib/jvm/java-17-openjdk-amd64'),
               ANDROID_HOME=str(session.SDK), ANDROID_SDK_ROOT=str(session.SDK),
               MAGNOLIE_JS_RUNTIME=runtime, PYTHONDONTWRITEBYTECODE='1')
    code = 1
    with owner.signals(), session.locks(session.lock_paths(config)), tempfile.TemporaryDirectory(prefix='tablet-beta-', dir='/tmp/opencode') as temporary:
        env.update(TMPDIR=temporary, JAVA_TOOL_OPTIONS='-Djava.io.tmpdir='+temporary)
        try:
            session.idle(owner)
            owner.record('offline-checks', jvm=opts.jvm or opts.build, build=opts.build,
                         memoryMax=memory, cpuQuota=quota, cpuPeriod=period, cpuAffinity=cpus, temporaryResources=temporary)
            for command, timeout in [([sys.executable, '-B', 'tests/test_emulator_session.py'], 30),
                                     ([sys.executable, '-B', 'tests/test_host_capacity.py'], 30),
                                     ([runtime, 'tests/touch-proof.test.cjs'], 30),
                                     ([runtime, 'tests/touch-channel.test.cjs'], 30),
                                     ([runtime, 'tools/project-web.cjs'], 60),
                                      ([runtime, 'tests/web.test.cjs'], 120),
                                      ([runtime, str(ROOT.parent / 'Magnolie-Organizer-Windows-2.0.0/tests/setup-holidays.js')], 120),
                                      ([runtime, 'tests/reminders.test.cjs'], 120)]:
                owner.record('check', command=command)
                output = owner.command(command, timeout=timeout, env=env)
                print(output, flush=True)
                if command[-1].endswith('test_emulator_session.py'):
                    count = re.search(r'Ran (\d+) tests', output)
                    if not count:
                        raise RuntimeError('Missing runner test count')
                    owner.record('runner-tests-passed', runnerTests=int(count[1]))
                elif command[-1].endswith('setup-holidays.js'):
                    count = re.search(r'Setup holidays: (\d+) cross-desktop cases passed; (\d+) languages', output)
                    if not count:
                        raise RuntimeError('Missing setup-holiday test count')
                    owner.record('setup-tests-passed', setupHolidayCases=int(count[1]), setupLocales=int(count[2]))
            if opts.jvm or opts.build:
                command = ['bash', str(ROOT.parent / 'magnolie-notes-1.0.13/gradlew'), '-p', str(ROOT),
                           '--offline', '--console=plain', '--no-daemon', '--max-workers=1', '--rerun-tasks', ':app:testDebugUnitTest']
                owner.record('offline-jvm', command=command)
                print(owner.command(command, timeout=300, env=env), flush=True)
            if opts.build:
                command = ['bash', str(ROOT.parent / 'magnolie-notes-1.0.13/gradlew'), '-p', str(ROOT),
                           '--offline', '--console=plain', '--no-daemon', '--max-workers=1',
                           ':app:assembleDebug', ':app:assembleDebugAndroidTest']
                owner.record('offline-debug-build', command=command)
                print(owner.command(command, timeout=600, env=env), flush=True)
            print(owner.command([runtime, 'tools/project-web.cjs', '--check'], timeout=60, env=env), flush=True)
            if opts.build:
                print(owner.command([runtime, 'tools/artifacts.cjs'], timeout=120, env=env), flush=True)
            manifest = json.loads((ROOT / 'app/build/generated/projection/assets/projection.json').read_text())
            owner.record('validated-snapshot', sourceHash=manifest['sourceHash'], emulator=False,
                         scope='debug app/test APKs verified; native acceptance pending' if opts.build else
                               'offline snapshot checks only; existing APK stays stale; shared sources may change later')
            code = 0
        except Exception as exc:
            code = 124 if isinstance(exc, session.Deadline) else 1
            owner.record('failed', reason=str(exc), output=str(getattr(exc, 'output', ''))[-8000:])
        finally:
            owner.close()
            owner.record('finished', exitCode=code)
    return code


if __name__ == '__main__':
    sys.exit(main())
