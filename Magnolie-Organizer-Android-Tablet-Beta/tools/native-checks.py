#!/usr/bin/env python3
"""Later-only fresh disposable emulator suites, using the existing bounded owner."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)
SUITES = {
    'ui': ['basics', 'restart', 'layout', 'time'],
    'services': ['services'],
    'files': ['calendar-files'],
    'domains': ['domains'],
    'storage': ['basics', 'saf', 'fault', 'print'],
    'notifications': ['notifications'],
}


def technical_failure_log(output):
    # The fresh disposable AVD contains synthetic fixtures only. Emit bounded
    # runtime/crash diagnostics, never the captured DOM, records or full logcat.
    lines = [line for line in output.splitlines()
             if re.search(r'\s[EF]\s+(?:AndroidRuntime|chromium|libc|DEBUG)\s*:', line) or
                re.search(r'\sI\s+TabletNativeTest\s*:\s+(?:START (?:basics|restart|layout|time|navigation|services|calendar-files|domains)\b|PASS |PHASE (?:navigation-fixture-(?:start|ready)|native-touch-probe-connected|trusted-tab-switch-\d+)\b)', line)]
    return '\n'.join(lines[-160:])[-16000:]


def startup_milestones(output):
    phases = ('CREATE_BEGIN', 'WEBVIEW_CREATE_BEGIN', 'WEBVIEW_CREATE_END', 'LOAD_URL',
              'PAGE_STARTED', 'PAGE_VISIBLE', 'PAGE_FINISHED', 'BOOTSTRAP_REQUEST',
              'VAULT_OPEN_BEGIN', 'VAULT_OPEN_END', 'INIT_REPLY', 'PAGE_ACKNOWLEDGED',
              'ACTIVATION_BEGIN', 'ACTIVATION_END', 'NATIVE_READY', 'READY_REPLY')
    pattern = re.compile(r'\sD\s+MagnolieStartup\s*:\s+(event=(?:'+ '|'.join(phases) +
        r') pid=\d+ generation=\d+ elapsedRealtimeMs=\d+ sinceCreateMs=\d+)\s*$')
    lines = [match.group(1) for line in output.splitlines() if (match := pattern.search(line))]
    return '\n'.join(lines[-48:])[-6000:]


def system_dependency_log(output):
    package = re.escape(session.BETA_PACKAGE)
    target = re.compile(r'(?<![A-Za-z0-9_.])'+package+r'(?=[:/\s,})]|$)')
    lines = []
    for line in output.splitlines():
        if re.search(r'\s[IW]\s+ActivityManager\s*:', line) and target.search(line) and re.search(
                r'\b(?:Killing|killed|died|Force stopping|depends on|dependency)\b', line):
            lines.append(line[:700])
        elif re.search(r'\s[IEW]\s+WebViewUpdateService\s*:', line) and re.search(
                r'provider|package|relro|multiprocess|changed|webview', line, re.I):
            lines.append(line[:700])
    return '\n'.join(lines[-40:])[-8000:]


def provider_readiness(output):
    labels = ('Multiprocess enabled:', 'Current WebView package (name, version):',
              'Current WebView package is null', 'Preferred WebView package is null',
              'Preferred WebView package (name, version):', 'Number of relros started:',
              'Number of relros finished:', 'WebView package dirty:', 'Any WebView package installed:')
    return '\n'.join(line.strip()[:300] for line in output.splitlines()
                     if line.strip().startswith(labels))[:2000]


def dependency_exit_descriptions(output):
    summaries = []
    for record in re.split(r'(?=\btimestamp=)', output)[:12]:
        if not re.search(r'\breason=12\b', record):
            continue
        description = re.search(r'\bdescription=([^\n]*)', record)
        if not description:
            continue
        text = description.group(1)
        # Dependency-death descriptions are system metadata. Emit its category
        # and package/component identifiers, not arbitrary description prose.
        packages = sorted(set(re.findall(r'\b[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*){2,}(?:/[A-Za-z0-9_.$]+)?(?::[A-Za-z0-9_.]+)?', text)))[:6]
        summaries.append(json.dumps(dict(dependencyDescription=True,
            provider='provider' in text.lower(), webview='webview' in text.lower(),
            package='package' in text.lower(), packages=packages), sort_keys=True))
    return '\n'.join(summaries)[:2000]


def exit_info_signature(output):
    fields = re.finditer(r'\b(?:timestamp=\d{4}-\d{2}-\d{2}[ T][0-9:.+-]+|'
                         r'(?:pid|reason|status|importance|pss|rss)=\d+(?:[ \t]+\([A-Z_ ]+\))?)', output)
    # dumpsys orders the newest process exits first: retain their correlation.
    return '\n'.join(match.group() for match in list(fields)[:56])[:3000]


def gms_exit_signature(output):
    records = []
    for block in re.split(r'(?=ApplicationExitInfo #\d+:)', output):
        if not re.search(r'\bprocess=com\.google\.android\.gms\.persistent(?=\s|$)', block):
            continue
        timestamp = re.search(r'\btimestamp=(\d{4}-\d{2}-\d{2}[ T][0-9:.+-]+)', block)
        fields = {key: int(value) for key, value in re.findall(r'\b(pid|reason|status)=(-?\d+)', block)}
        if timestamp and set(fields) == {'pid', 'reason', 'status'}:
            records.append(dict(timestamp=timestamp.group(1), **fields))
        if len(records) == 6:
            break
    return json.dumps(dict(process='com.google.android.gms.persistent',
        available='ACTIVITY MANAGER PROCESS EXIT INFO' in output, records=records), sort_keys=True)[:2000]


def gms_process_signature(output):
    lines = [line.split() for line in output.splitlines() if line.strip()]
    valid = bool(lines) and lines[0] in (['PID', 'NAME'], ['PID', 'CMD'])
    pids = sorted({int(row[0]) for row in lines[1:] if len(row) == 2 and row[0].isdigit() and
                   row[1] == 'com.google.android.gms.persistent'}) if valid else []
    return json.dumps(dict(process='com.google.android.gms.persistent', available=valid, pids=pids[:8]), sort_keys=True)


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
    parser.add_argument('--api', type=int, choices=(26,34,35), default=34)
    parser.add_argument('--image', choices=('google_apis', 'default'), default='google_apis')
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
        '--boot-timeout', '180', '--test-timeout', '120', '--progress', '30', '--image', opts.image, '--api', str(opts.api)])
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
                if code:
                    owner.record('native-failure-resources', **session.memory_usage())
                if owner.state.get('booted') and not owner.signal and session.time.monotonic() < owner.deadline:
                    for name, command in {
                        'android-test-log': ['logcat', '-b', 'all', '-d', '-v', 'threadtime', '-s',
                            'AndroidRuntime:E', 'chromium:E', 'libc:F', 'DEBUG:F', 'ActivityManager:I', 'WebViewUpdateService:I', 'TabletNativeTest:I', 'MagnolieStartup:D'],
                        'app-exit-info': ['shell', 'dumpsys', 'activity', 'exit-info',
                            'io.gitlab.maik3531.magnolieorganizer.tablet.beta'],
                        **({'webview-provider-state': ['shell', 'dumpsys', 'webviewupdate'],
                            'gms-exit-info': ['shell', 'dumpsys', 'activity', 'exit-info', 'com.google.android.gms'],
                            'gms-process-state': ['shell', 'ps', '-A', '-o', 'PID,NAME']} if code else {}),
                    }.items():
                        try:
                            output = session.adb(owner, owner.state, command, 15)
                            if name == 'gms-exit-info':
                                output = gms_exit_signature(output)
                            elif name == 'gms-process-state':
                                output = gms_process_signature(output)
                            (Path(owner.state['run']) / 'evidence' / (name+'.txt')).write_text(output)
                            if code and name == 'android-test-log':
                                print('NATIVE_RUNTIME_FAILURE_LOG\n'+technical_failure_log(output), flush=True)
                                print('NATIVE_SYSTEM_DEPENDENCY_LOG\n'+system_dependency_log(output), flush=True)
                                print('NATIVE_STARTUP_MILESTONES\n'+startup_milestones(output), flush=True)
                            elif code and name == 'app-exit-info':
                                print('NATIVE_EXIT_REASON_SIGNATURE\n'+exit_info_signature(output), flush=True)
                                print('NATIVE_DEPENDENCY_DESCRIPTION\n'+dependency_exit_descriptions(output), flush=True)
                            elif code and name == 'webview-provider-state':
                                print('NATIVE_WEBVIEW_PROVIDER_READINESS\n'+provider_readiness(output), flush=True)
                            elif code and name in ('gms-exit-info', 'gms-process-state'):
                                print('NATIVE_GMS_LIFECYCLE '+name+'\n'+output, flush=True)
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
