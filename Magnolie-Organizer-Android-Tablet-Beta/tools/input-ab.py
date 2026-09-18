#!/usr/bin/env python3
"""One frozen-app, test-only-build A/B. Never regenerate the app projection."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)
APP = ROOT / 'artifacts/Magnolie-Organizer-Android-Tablet-Beta-2.0.18Beta-debug.apk'
APP_SHA = 'd9c455c524c8001cb720b4d664071e8fbd01c3079af3f4fdf37cfa4bea269023'
SOURCE = '6562133f90c41c664745e59b4b5e72716b16160606d4266b6edddf1afee0a538'
TEST = ROOT / 'artifacts/input-ab-instrumentation.apk'
MANIFEST = ROOT / 'artifacts/input-ab.json'
PACKAGE = 'io.gitlab.maik3531.magnolieorganizer.tablet.beta'
INCLUDE_CONTROL = True


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_app():
    if digest(APP) != APP_SHA:
        raise RuntimeError('Frozen app APK changed')
    projection = json.loads((ROOT / 'artifacts/projection.json').read_text())
    generated = ROOT / 'app/build/generated/projection'
    if projection['sourceHash'] != SOURCE or projection != json.loads((generated / 'assets/projection.json').read_text()):
        raise RuntimeError('Frozen projection provenance changed')
    for name, sha in projection['outputs'].items():
        if digest(generated / name) != sha:
            raise RuntimeError('Frozen app asset/resource changed: ' + name)
    prefix = ROOT.name + '/'
    for name, sha in projection['inputs'].items():
        if any(name.startswith(prefix + p) for p in ('app/src/androidTest/', 'app/src/test/', 'tests/', 'tools/')):
            continue
        path = ROOT.parent / name
        if name == prefix + 'app/build.gradle.kts':
            original = path.read_text()
            for source in ('androidTest', 'test'):
                original = original.replace('    sourceSets.getByName("'+source+'").kotlin.srcDir(rootProject.file("tests/input"))\n', '')
            actual = hashlib.sha256(original.encode()).hexdigest()
        else:
            actual = digest(path)
        if actual != sha:
            raise RuntimeError('Non-test source changed: ' + name)


def test_inputs():
    files = [ROOT / 'app/build.gradle.kts']
    for name in ('app/src/androidTest', 'app/src/test', 'tests', 'tools'):
        files += [p for p in (ROOT / name).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}


def build(owner):
    frozen_app()
    inputs = test_inputs()
    print(owner.command([sys.executable, '-B', 'tests/test_emulator_session.py'], timeout=30), flush=True)
    print(owner.command([str(Path.home() / '.bun/bin/bun'), 'tests/touch-proof.test.cjs'], timeout=30), flush=True)
    print(owner.command([str(Path.home() / '.bun/bin/bun'), 'tests/touch-channel.test.cjs'], timeout=30), flush=True)
    with tempfile.TemporaryDirectory(prefix='tablet-input-ab-', dir='/tmp/opencode') as temporary:
        env = dict(os.environ, JAVA_HOME='/usr/lib/jvm/java-17-openjdk-amd64',
                   ANDROID_HOME=str(session.SDK), ANDROID_SDK_ROOT=str(session.SDK),
                   JAVA_TOOL_OPTIONS='-Djava.io.tmpdir='+temporary, TMPDIR=temporary)
        command = ['bash', str(ROOT.parent / 'magnolie-notes/gradlew'), '-p', str(ROOT),
                   '--offline', '--console=plain', '--no-daemon', '--max-workers=1',
                   ':app:testDebugUnitTest', ':app:assembleDebugAndroidTest', '-x', ':app:projectDesktop']
        print(owner.command(command, timeout=480, env=env), flush=True)
    reports = [ET.parse(p).getroot() for p in (ROOT / 'app/build/test-results/testDebugUnitTest').glob('TEST-*.xml')]
    if not reports or any(int(r.attrib.get(k, 0)) for r in reports for k in ('failures', 'errors', 'skipped')):
        raise RuntimeError('JVM regression failed or skipped')
    fake = next((r for r in reports if r.attrib['name'].endswith('.AsyncTouchPairTest')), None)
    if fake is None or int(fake.attrib['tests']) != 3:
        raise RuntimeError('Three async scheduling regressions are required')
    frozen_app()
    if inputs != test_inputs():
        raise RuntimeError('Test source changed during build')
    built = ROOT / 'app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk'
    shutil.copyfile(built, TEST)
    proof = dict(app=APP.name, appSha256=APP_SHA, appSourceHash=SOURCE,
                 testApk=TEST.name, testApkSha256=digest(TEST), testInputs=inputs,
                 unitTests=sum(int(r.attrib['tests']) for r in reports),
                 asyncFakeTests=3, touchProofCases=15, touchChannelCases=1, includeShellControl=INCLUDE_CONTROL, nativeUiPassed=False, nativeUiStages={},
                 status='Frozen app; new test-only APK, native A/B not run')
    MANIFEST.write_text(json.dumps(proof, indent=2)+'\n')
    candidate = json.loads((ROOT / 'artifacts/candidate.json').read_text())
    candidate.update(stale=True, nativeUiPassed=False,
                     staleReason='Test/runner sources changed; frozen-app A/B has separate artifacts/input-ab.json provenance')
    (ROOT / 'artifacts/candidate.json').write_text(json.dumps(candidate, indent=2)+'\n')
    owner.record('test-only-build-verified', appSha256=APP_SHA, testSha256=digest(TEST), unitTests=proof['unitTests'])


def run(owner, config):
    frozen_app()
    proof = json.loads(MANIFEST.read_text())
    if proof['testInputs'] != test_inputs() or proof['testApkSha256'] != digest(TEST):
        raise RuntimeError('Test APK is stale')
    session.prepare(owner, config)
    evidence = Path(owner.state['run']) / 'evidence'
    proof.update(nativeUiPassed=False, nativeUiStages={}, control=None, evidence=str(evidence))
    (evidence / 'input-ab-build.json').write_text(json.dumps(proof, indent=2)+'\n')

    def install(owned, state):
        frozen_app()
        for apk in (APP, TEST):
            output = session.adb(owned, state, ['install', '-t', str(apk)], 120)
            if 'Success' not in output.splitlines():
                raise RuntimeError('Install rejected: '+output)
        for name, command in {'device-runtime':['shell','getprop'],
                              'webview-runtime':['shell','dumpsys','webviewupdate']}.items():
            (evidence / (name+'.txt')).write_text(session.adb(owned, state, command, 30))

    def case(stage, injector, fixture=None):
        label = injector+'-'+stage
        owner.record('input-ab-case', case=label, stage=stage, **session.memory_usage())
        args = ['shell','am','instrument','-w','-r','-e','stage',stage,
                '-e','injector',injector,'-e','case',label]
        if fixture:
            args += ['-e','fixture',fixture]
        args += [PACKAGE+'.test/io.gitlab.maik3531.magnolietabletbeta.NativeTabletInstrumentation']
        output = session.adb(owner, owner.state, args, 120)
        (evidence / (label+'-instrumentation.txt')).write_text(output)
        print(output, flush=True)
        result, _ = json.JSONDecoder().raw_decode(output.split('INSTRUMENTATION_RESULT: stream=',1)[1].lstrip())
        if result.get('stage') != stage or result.get('injector') != injector or result.get('sourceHash') != SOURCE:
            raise RuntimeError('Wrong A/B runtime provenance')
        result['instrumentationAccepted'] = bool(re.search(r'INSTRUMENTATION_CODE:\s*-1\b', output))
        owner.record('input-ab-result', case=label, passed=result['passed'], **session.memory_usage())
        return result

    def stages(owned, state):
        for stage in ('basics', 'restart'):
            result = case(stage, 'async', 'capture' if stage == 'basics' else None)
            proof['nativeUiStages'][stage] = result
            if not (result['passed'] is True and result['instrumentationAccepted']):
                return 1
        if INCLUDE_CONTROL:
            control = case('layout', 'shell', 'restore')
            proof['control'] = control
            if control['passed'] and not control['instrumentationAccepted']:
                return 1
            # A failed control stays failed; crashes and missing proofs abort.
            if not control['passed'] and 'Timeout: touch tab ' not in (control.get('error') or ''):
                return 1
        for stage in ('layout', 'time'):
            result = case(stage, 'async', 'restore' if stage == 'layout' else None)
            proof['nativeUiStages'][stage] = result
            if not (result['passed'] is True and result['instrumentationAccepted']):
                return 1
        proof['nativeUiPassed'] = all(proof['nativeUiStages'][s]['passed'] is True and
                                      proof['nativeUiStages'][s]['instrumentationAccepted']
                                      for s in ('basics','restart','layout','time'))
        return 0 if proof['nativeUiPassed'] else 1

    try:
        return session.run_session(owner, config, after_boot=install, run_tests=stages)
    finally:
        proof['status'] = 'Four async UI stages passed' if proof['nativeUiPassed'] else 'Native A/B incomplete or failed; not UI acceptance'
        MANIFEST.write_text(json.dumps(proof, indent=2)+'\n')
        (evidence / 'input-ab-result.json').write_text(json.dumps(proof, indent=2)+'\n')
        if owner.state.get('booted') and not owner.signal:
            for name, command in {
                'native-evidence-pull':['pull','/sdcard/Android/data/'+PACKAGE+'/files/native-evidence',str(evidence)],
                'android-test-log':['logcat','-b','all','-d','-v','threadtime','-s','AndroidRuntime:E','chromium:E','TabletNativeTest:I'],
                'app-exit-info':['shell','dumpsys','activity','exit-info',PACKAGE],
            }.items():
                try:
                    (evidence / (name+'.txt')).write_text(session.adb(owner, owner.state, command, 30))
                except Exception as exc:
                    owner.record('collection-failed', name=name, error=str(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build','run'))
    parser.add_argument('--main-slot-granted', action='store_true', required=True)
    opts = parser.parse_args()
    os.chdir(ROOT)
    os.umask(0o077)
    cpus = session.pin_two_cpus()
    group = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
    memory = (group / 'memory.max').read_text().strip()
    quota, period = (group / 'cpu.max').read_text().split()
    if memory == 'max' or int(memory) > 6*1024**3 or quota == 'max' or int(quota) > 2*int(period):
        raise RuntimeError('6 GiB / 200% cgroup required')
    config = session.parser().parse_args(['run','--main-slot-granted','--runtime','570',
                                        '--boot-timeout','180','--test-timeout','120','--progress','30'])
    owner = session.Owner(runtime=570, progress=30)
    code = 1
    with owner.signals(), session.locks(session.lock_paths(config)):
        try:
            session.idle(owner)
            owner.record('input-ab-'+opts.action, cpuAffinity=cpus)
            if opts.action == 'build':
                build(owner); code = 0
            else:
                code = run(owner, config)
        except Exception as exc:
            code = 124 if isinstance(exc, session.Deadline) else 1
            owner.record('failed', reason=str(exc), output=str(getattr(exc,'output',''))[-12000:])
        finally:
            owner.close()
            owner.record('finished', exitCode=code)
            if owner.state.get('run'):
                (Path(owner.state['run']) / 'evidence/owner-final.json').write_text(json.dumps(owner.state,indent=2)+'\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
