#!/usr/bin/env python3
"""Later-only fresh disposable emulator suites, using the existing bounded owner."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)
SUITES = {
    'ui': ['basics', 'restart', 'layout', 'time'],
    'storage': ['basics', 'saf', 'fault', 'print'],
    'notifications': ['notifications'],
}


def candidate_files(candidate, projection):
    if candidate.get('stale') is not False or candidate.get('signing') != 'debug only' or \
            candidate.get('sourceHash') != projection['sourceHash'] or \
            candidate.get('applicationId') != 'io.gitlab.maik3531.magnolieorganizer.tablet.beta' or \
            not candidate.get('instrumentationTestOnly') or not candidate.get('apkAssetsVerified'):
        raise RuntimeError('A current verified debug app/test candidate is required')
    files = []
    for key, digest in [('name', 'sha256'), ('testApk', 'testApkSha256')]:
        name = candidate[key]
        if Path(name).name != name or not name.endswith('.apk'):
            raise RuntimeError('Candidate must name a local artifact APK')
        apk = ROOT / 'artifacts' / name
        if apk.is_symlink() or hashlib.sha256(apk.read_bytes()).hexdigest() != candidate[digest]:
            raise RuntimeError('Candidate APK hash mismatch: ' + name)
        files.append(apk)
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-slot-granted', action='store_true')
    parser.add_argument('--suite', choices=SUITES, default='ui')
    opts = parser.parse_args(argv)
    if not opts.main_slot_granted:
        raise SystemExit('Main must finish Windows native work and grant the sole slot first')
    os.chdir(ROOT)
    os.umask(0o077)
    cpus = session.pin_two_cpus()
    cgroup = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1].lstrip('/')
    memory = (cgroup / 'memory.max').read_text().strip()
    quota, period = (cgroup / 'cpu.max').read_text().split()
    if memory == 'max' or int(memory) > 6 * 1024**3 or quota == 'max' or int(quota) > 2 * int(period):
        raise SystemExit('Use MemoryMax=6G and CPUQuota=200% as documented')
    config = session.parser().parse_args(['run', '--main-slot-granted', '--runtime', '600',
        '--boot-timeout', '180', '--test-timeout', '120', '--progress', '30'])
    config.test = SUITES[opts.suite]
    owner = session.Owner(runtime=600, progress=30)
    code = 1
    with owner.signals(), session.locks(session.lock_paths(config)):
        try:
            session.idle(owner)
            runtime = os.environ.get('MAGNOLIE_JS_RUNTIME', str(Path.home() / '.bun/bin/bun'))
            print(owner.command([runtime, 'tools/project-web.cjs', '--check'], timeout=60), flush=True)
            candidate = json.loads((ROOT / 'artifacts/candidate.json').read_text())
            projection = json.loads((ROOT / 'artifacts/projection.json').read_text())
            generated = json.loads((ROOT / 'app/build/generated/projection/assets/projection.json').read_text())
            if projection != generated:
                raise RuntimeError('Packaged and current projections differ')
            candidate_files(candidate, projection)
            session.prepare(owner, config)
            owner.record('suite-prepared', suite=opts.suite, cpuAffinity=cpus, expectedSourceHash=projection['sourceHash'])

            def install(owned, state):
                # Check bytes again immediately before installation on our own new AVD.
                for apk in candidate_files(candidate, projection):
                    output = session.adb(owned, state, ['install', '-t', str(apk)], 120)
                    if 'Success' not in output.splitlines():
                        raise RuntimeError('APK installation did not report success: ' + output)
                owned.record('candidate-installed', apk=candidate['name'], sha256=candidate['sha256'])
                for name, command in {
                    'device-runtime': ['shell', 'getprop'],
                    'webview-runtime': ['shell', 'dumpsys', 'webviewupdate'],
                }.items():
                    output = session.adb(owned, state, command, 30)
                    (Path(state['run']) / 'evidence' / (name+'.txt')).write_text(output)

            code = session.run_session(owner, config, after_boot=install)
        except session.Stopped as exc:
            code = 128 + owner.signal
            owner.record('interrupted', reason=str(exc))
        except session.Deadline as exc:
            code = 124
            owner.record('timeout', reason=str(exc))
        except Exception as exc:
            owner.record('failed', reason=str(exc), output=str(getattr(exc, 'output', ''))[-8000:])
        finally:
            try:
                if owner.state.get('booted') and not owner.signal and session.time.monotonic() < owner.deadline:
                    for name, command in {
                        'android-test-log': ['logcat', '-b', 'all', '-d', '-v', 'threadtime', '-s',
                            'AndroidRuntime:E', 'chromium:E', 'libc:F', 'DEBUG:F', 'ActivityManager:W', 'TabletNativeTest:I'],
                        'app-exit-info': ['shell', 'dumpsys', 'activity', 'exit-info',
                            'io.gitlab.maik3531.magnolieorganizer.tablet.beta'],
                    }.items():
                        try:
                            output = session.adb(owner, owner.state, command, 15)
                            (Path(owner.state['run']) / 'evidence' / (name+'.txt')).write_text(output)
                        except Exception as exc:
                            owner.record('diagnostic-collection-failed', name=name, reason=str(exc))
                    try:
                        output = session.adb(owner, owner.state, ['pull',
                            '/sdcard/Android/data/io.gitlab.maik3531.magnolieorganizer.tablet.beta/files/native-evidence',
                            str(Path(owner.state['run']) / 'evidence')], 30)
                        print(output, flush=True)
                    except Exception as exc:
                        code = code or 1
                        owner.record('evidence-collection-failed', reason=str(exc))
                owner.close()
                owner.record('finished', exitCode=code, suite=opts.suite)
                if owner.state.get('run'):
                    (Path(owner.state['run']) / 'evidence' / 'owner-final.json').write_text(json.dumps(owner.state, indent=2)+'\n')
            except Exception as exc:
                code = 1
                owner.record('cleanup-failed', reason=str(exc), exitCode=code)
    return code


if __name__ == '__main__':
    sys.exit(main())
