#!/usr/bin/env python3
"""Explicit host-capacity experiment; APKs, guest configuration and UI tests stay frozen."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)
APK_NAMES = ('Magnolie-Organizer-Android-Tablet-Beta-2.0.18Beta-debug.apk',
             'Magnolie-Organizer-Android-Tablet-Beta-2.0.18Beta-instrumentation.apk')
BINDING_FILE = ROOT / 'artifacts/capacity-apk-binding.json'
BASELINE = Path.home() / '.local/share/magnolie-testing/tablet-beta/20260914T175328/evidence'
FIXTURE = BASELINE / 'native-evidence/legacy/fixture.json'
FIXTURE_SHA = '09932589382928443eb508af92ab2f48fe09aae97ddf4c9d1e0887b67e70e5fa'
PACKAGE = 'io.gitlab.maik3531.magnolieorganizer.tablet.beta'
STAGES = ('basics', 'restart', 'layout', 'time')
TOOLING = ('tools/host-capacity.py', 'tests/test_host_capacity.py')


def sha(path):
    if path.is_symlink():
        raise RuntimeError('Symlink in frozen inputs: '+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_cpus(count, allowed, topology):
    if count not in (2, 4):
        raise ValueError('Host profile must be exactly 2 or 4 CPUs')
    selected, cores = [], set()
    for cpu in sorted(allowed):
        core = topology(cpu)  # A missing topology is not evidence of a distinct core.
        if core not in cores:
            selected.append(cpu)
            cores.add(core)
        if len(selected) == count:
            return selected
    raise RuntimeError('Insufficient verified distinct physical cores in parent affinity')


def topology(cpu):
    path = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
    return (int((path / 'physical_package_id').read_text()), int((path / 'core_id').read_text()))


def validate_limits(count, memory, swap, quota, period, affinity):
    if count not in (2, 4) or len(affinity) != count:
        raise RuntimeError('Affinity does not match selected host profile')
    if memory == 'max' or int(memory) > 6*1024**3 or int(swap) != 0:
        raise RuntimeError('Require MemoryMax <= 6 GiB and MemorySwapMax=0')
    if quota == 'max' or int(quota) != count*int(period):
        raise RuntimeError('CPUQuota must exactly match the explicit host CPU profile')


def configure_capacity(count):
    allowed = sorted(os.sched_getaffinity(0))
    cpus = select_cpus(count, allowed, topology)
    group = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1].lstrip('/')
    quota, period = (group / 'cpu.max').read_text().split()
    memory = (group / 'memory.max').read_text().strip()
    swap = (group / 'memory.swap.max').read_text().strip()
    validate_limits(count, memory, swap, quota, period, cpus)
    os.sched_setaffinity(0, cpus)
    if sorted(os.sched_getaffinity(0)) != cpus:
        raise RuntimeError('Requested affinity was not applied')
    return dict(name=f'host-{count}-physical_guest-2', hostCpus=count, hostAffinity=cpus,
                parentAllowed=allowed, physicalCores=[topology(cpu) for cpu in cpus],
                cpuQuota=quota, cpuPeriod=period, memoryMax=memory, swapMax=swap,
                guestVcpus=2, guestRequestedRamMiB=2048, gpu='swangle',
                bootSeconds=180, stageSeconds=120, rpcSeconds=20, runtimeSeconds=1200)


def validate_package_binding(binding):
    if not isinstance(binding,dict) or not isinstance(binding.get('apks'),dict) or set(binding['apks']) != set(APK_NAMES):
        raise RuntimeError('Binding must name only the two fixed local beta APK filenames')
    for value in [binding.get('appSourceHash'), *binding['apks'].values()]:
        if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
            raise RuntimeError('Binding requires exact SHA-256 values')
    return binding


def bind_current_candidate():
    candidate=json.loads((ROOT/'artifacts/candidate.json').read_text())
    if (candidate.get('stale') is not False or candidate.get('signing')!='debug only' or
        candidate.get('applicationId')!=PACKAGE or candidate.get('apkAssetsVerified') is not True or
        candidate.get('instrumentationTestOnly') is not True or
        candidate.get('name')!=APK_NAMES[0] or candidate.get('testApk')!=APK_NAMES[1]):
        raise RuntimeError('A fresh verified local debug app/test candidate is required')
    proposed=validate_package_binding(dict(appSourceHash=candidate['sourceHash'],apks={
        APK_NAMES[0]:candidate['sha256'],APK_NAMES[1]:candidate['testApkSha256']}))
    # Verify bytes, current source and embedded provenance before publishing a binding.
    frozen_binding(proposed)
    BINDING_FILE.write_text(json.dumps(proposed,indent=2)+'\n')
    return proposed


def frozen_binding(package_binding=None):
    package_binding=validate_package_binding(package_binding or json.loads(BINDING_FILE.read_text()))
    if sha(FIXTURE) != FIXTURE_SHA:
        raise RuntimeError('Original comparison fixture changed')
    manifest = json.loads((ROOT / 'artifacts/projection.json').read_text())
    generated = ROOT / 'app/build/generated/projection'
    if manifest['sourceHash'] != package_binding['appSourceHash'] or manifest != json.loads((generated / 'assets/projection.json').read_text()):
        raise RuntimeError('Frozen projection changed')
    # Every input, including instrumentation and resource tools, must match the
    # freshly verified build. Artifact-only binding avoids self-referential hashes.
    for name, digest in manifest['inputs'].items():
        if sha(ROOT.parent / name) != digest:
            raise RuntimeError('Frozen source changed: '+name)
    for name, digest in manifest['outputs'].items():
        if sha(generated / name) != digest:
            raise RuntimeError('Generated asset/resource changed: '+name)
    for name, digest in package_binding['apks'].items():
        if sha(ROOT / 'artifacts' / name) != digest:
            raise RuntimeError('Frozen APK changed: '+name)
    with zipfile.ZipFile(ROOT/'artifacts'/APK_NAMES[0]) as apk:
        if json.loads(apk.read('assets/projection.json')) != manifest:
            raise RuntimeError('App APK embedded a different source projection')
    return dict(appSourceHash=package_binding['appSourceHash'], apks=package_binding['apks'], fixtureSha256=sha(FIXTURE),
                priorEvidence=str(BASELINE), tooling={name:sha(ROOT / name) for name in TOOLING},
                sourceScope='Current verified app/test build; artifact-only binding avoids circular tool/APK hashes')


class LinuxTasks:
    """Only /proc identity reads and per-owned-task affinity syscalls."""
    parent = staticmethod(session.identity)
    get = staticmethod(os.sched_getaffinity)
    set = staticmethod(os.sched_setaffinity)

    @staticmethod
    def tids(pid):
        return sorted(int(p.name) for p in (Path('/proc') / str(pid) / 'task').iterdir())

    @staticmethod
    def task(pid, tid):
        base = Path('/proc') / str(pid) / 'task' / str(tid)
        raw = (base / 'stat').read_text()
        status = dict(line.split(':', 1) for line in (base / 'status').read_text().splitlines() if ':' in line)
        return dict(tid=int(raw.split(' ', 1)[0]), tgid=int(status['Tgid']),
                    start=raw.rsplit(')', 1)[1].split()[19], uid=base.stat().st_uid)


def audit_process(expected, selected, ops, record, repair=False, deadline=None):
    """Fake-testable identity-fenced audit; repair is permitted only by the pretest caller.

    Linux sched_setaffinity accepts a numeric TID, not a pidfd. Parent and task
    identities are checked immediately before/after affinity syscalls; do not
    describe this as atomic pidfd-based affinity containment.
    """
    pid = expected['pid']
    selected = set(selected)

    def parent():
        actual = ops.parent(pid)
        if actual != expected:
            raise RuntimeError(f'Owned PID identity mismatch: expected={expected}, actual={actual}')

    parent()
    tids = ops.tids(pid)
    if len(tids) > 1024:
        raise RuntimeError('Unexpected SDK task count; refusing unbounded affinity scan')
    results = []
    for tid in tids:
        if deadline is not None and session.time.monotonic() >= deadline:
            raise RuntimeError('Bounded pretest affinity preparation deadline exceeded')
        try:
            parent()
            task = ops.task(pid, tid)
            if task['tid'] != tid or task['tgid'] != pid or task['uid'] != expected['uid']:
                raise RuntimeError(f'Task is not a member of owned PID: pid={pid}, tid={tid}, task={task}')

            def identity_check():
                parent()
                actual = ops.task(pid, tid)
                if actual != task:
                    raise RuntimeError(f'Owned task identity changed: pid={pid}, tid={tid}, expected={task}, actual={actual}')

            identity_check()
            original = set(ops.get(tid))
            identity_check()
            if repair and original != selected:
                record(dict(phase='before-set', pid=pid, tid=tid, processIdentity=expected,
                            taskIdentity=task, original=sorted(original), requested=sorted(selected)))
                identity_check()
                ops.set(tid, selected)
                identity_check()
            # Always re-read the actual mask, including after a supposedly successful set.
            identity_check()
            actual = set(ops.get(tid))
            identity_check()
            row = dict(phase='verified' if actual == selected else 'rejected', pid=pid, tid=tid,
                       taskIdentity=task, original=sorted(original), actual=sorted(actual),
                       requested=sorted(selected), repairAttempted=repair and original != selected,
                       repaired=repair and original != selected and actual == selected)
            record(row)
            if actual != selected:
                raise RuntimeError(f'Owned thread affinity mismatch: pid={pid}, tid={tid}, '
                                   f'actual={sorted(actual)}, expected={sorted(selected)}')
            results.append(row)
        except (ProcessLookupError, FileNotFoundError):
            # Ignore only a vanished task of a still-identical live parent.
            parent()
            try:
                reappeared = ops.task(pid, tid)
            except (ProcessLookupError, FileNotFoundError):
                record(dict(phase='task-exited', pid=pid, tid=tid))
                continue
            raise RuntimeError(f'Task reappeared during affinity operation: pid={pid}, tid={tid}, actual={reappeared}')
    parent()
    return results


def owned_sdk_processes(owner):
    result = []
    for key, label in (('emulatorIdentity', 'emulator'), ('adbIdentity', 'adb5039')):
        expected = owner.state[key]
        matches = [(child, item) for child, item in owner.children
                   if item['label'] == label and item['identity'] == expected and child.pid == expected['pid']]
        if len(matches) != 1 or matches[0][0].poll() is not None:
            raise RuntimeError('SDK process is not a live registered direct child: '+label)
        if session.identity(expected['pid']) != expected:
            raise RuntimeError('SDK process identity changed: '+label)
        result.append((label, expected))
    return result


def verify_children_affinity(owner, profile, phase='stage-boundary'):
    summary = {}
    observed = []
    try:
        for label, expected in owned_sdk_processes(owner):
            rows = audit_process(expected, profile['hostAffinity'], LinuxTasks(), observed.append)
            summary[label] = dict(checked=len(rows), masks=sorted({tuple(r['actual']) for r in rows}))
        if sorted(os.sched_getaffinity(0)) != profile['hostAffinity']:
            raise RuntimeError('Owner host affinity changed')
    except Exception as exc:
        owner.record('host-affinity-rejected', auditPhase=phase, error=str(exc),
                     lastObservation=observed[-1] if observed else None, **session.memory_usage())
        raise
    owner.record('host-affinity-verified', auditPhase=phase, summary=summary,
                 hostAffinity=profile['hostAffinity'], **session.memory_usage())


def correct_owned_affinity(owner, profile):
    if profile['hostCpus'] != 4 or owner.measurement_active or owner.correction_attempted:
        raise RuntimeError('Affinity correction requires the one pre-measurement host-4 phase')
    owner.correction_attempted = True
    records = []
    proof = dict(complete=False, hostAffinity=profile['hostAffinity'], records=records)
    deadline = session.time.monotonic() + 10
    try:
        for label, expected in owned_sdk_processes(owner):
            fd = os.pidfd_open(expected['pid'])
            try:
                # Pin the process handle and recheck its identity before task work.
                if session.identity(expected['pid']) != expected:
                    raise RuntimeError('SDK PID changed after pidfd_open: '+label)
                audit_process(expected, profile['hostAffinity'], LinuxTasks(), records.append,
                              repair=True, deadline=deadline)
            finally:
                os.close(fd)
        # A fresh verification catches tasks created during the single repair pass.
        verify_children_affinity(owner, profile, 'after-pretest-correction')
        proof['complete'] = True
    except Exception as exc:
        proof['error'] = str(exc)
        raise
    finally:
        (Path(owner.state['run']) / 'evidence/affinity-preparation.json').write_text(json.dumps(proof, indent=2)+'\n')
        changed = [r for r in records if r.get('repaired')]
        owner.record('pretest-affinity-correction', complete=proof['complete'], changed=changed,
                     correctedThreads=len(changed), **session.memory_usage())


class CapacityOwner(session.Owner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.measurement_active = False
        self.correction_attempted = False
        self.profile = None
        self.next_affinity_audit = 0.0

    def start_measurement(self, profile):
        self.profile = profile
        self.measurement_active = True
        self.next_affinity_audit = session.time.monotonic() + 30
        self.record('measurement-started', correctionsAllowed=False, auditIntervalSeconds=30)

    def check(self, deadline=None):
        super().check(deadline)
        if self.measurement_active and session.time.monotonic() >= self.next_affinity_audit:
            self.next_affinity_audit = session.time.monotonic() + 30
            verify_children_affinity(self, self.profile, 'periodic-verification-only')


def require_newer_webview(text):
    match=re.search(r'Current WebView package \(name, version\):\s*\([^,]+,\s*(\d+)\.\d+\.\d+\.\d+\)',text)
    if not match or int(match.group(1)) <= 113:
        raise RuntimeError('API35 newer-WebView gate failed; no UI stages run')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-cpus', type=int, choices=(2, 4), default=2)
    parser.add_argument('--api', type=int, choices=(34, 35), default=34)
    parser.add_argument('--main-slot-granted', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--bind-candidate', action='store_true')
    opts = parser.parse_args(argv)
    os.chdir(ROOT)
    os.umask(0o077)
    if opts.bind_candidate:
        print(json.dumps(bind_current_candidate(),indent=2)); return 0
    binding = frozen_binding()
    if opts.verify_only:
        print(json.dumps(binding, indent=2)); return 0
    if not opts.main_slot_granted:
        raise RuntimeError('Explicit main-owner sole-slot grant required')
    profile = configure_capacity(opts.host_cpus)
    profile.update(requestedApi=opts.api, qualification=f'API{opts.api} '+profile['name'],
                   affinityPolicy='Owned pretest repair once; periodic fail-closed audit; user AllowedCPUs ineffective, no kernel cpuset containment claim')
    config = session.parser().parse_args(['run', '--main-slot-granted', '--runtime', '1200',
                                        '--boot-timeout', '180', '--test-timeout', '120', '--progress', '30', '--api', str(opts.api)])
    owner = CapacityOwner(runtime=1200, progress=30)
    report = dict(binding=binding, capacityProfile=profile, nativeUiPassed=False,
                   resultScope=f'API{opts.api} selected capacity profile only', aggregateNativeUiPassed=False,
                   api34HistoricalStatus='failed; preserved in ORACLE-PRECISION-20260914.md',
                   stages={s:dict(status='not-run') for s in STAGES})
    code = 1
    evidence = None
    with owner.signals(), session.locks(session.lock_paths(config)):
        try:
            session.idle(owner)
            owner.record('capacity-profile', capacityProfile=profile, **session.memory_usage())
            session.prepare(owner, config)
            evidence = Path(owner.state['run']) / 'evidence'
            (evidence / 'frozen-binding.json').write_text(json.dumps(binding, indent=2)+'\n')

            def install(owned, state):
                report['runtime']=dict(api=state['runtimeApi'],webview=state['webviewRuntime'])
                if opts.api == 35:
                    require_newer_webview(state['webviewRuntime'])
                provider=re.search(r'Current WebView package \(name, version\):\s*\(([A-Za-z0-9_.]+),\s*([0-9.]+)\)',state['webviewRuntime'])
                if not provider:
                    raise RuntimeError('Missing actual current WebView provider identity')
                report['runtime'].update(webviewPackage=provider[1],webviewVersion=provider[2])
                paths=session.adb(owned,state,['shell','pm','path',provider[1]],20).splitlines()
                if not paths or any(not re.fullmatch(r'package:/[A-Za-z0-9_./+=-]+',p) for p in paths):
                    raise RuntimeError('Unexpected WebView package paths')
                report['runtime']['webviewApkChecksums']=session.adb(owned,state,
                    ['shell','sha256sum',*[p.removeprefix('package:') for p in paths]],20)
                (evidence/'guest-meminfo.txt').write_text(session.adb(owned,state,['shell','cat','/proc/meminfo'],20))
                if frozen_binding() != binding:
                    raise RuntimeError('Binding changed before installation')
                for name in binding['apks']:
                    output = session.adb(owned, state, ['install', '-t', str(ROOT / 'artifacts' / name)], 120)
                    if 'Success' not in output.splitlines():
                        raise RuntimeError('APK install failed: '+output)
                for name, command in {
                    'device-runtime':['shell','getprop'],
                    'webview-runtime':['shell','dumpsys','webviewupdate'],
                }.items():
                    (evidence / (name+'.txt')).write_text(session.adb(owned,state,command,30))
                if profile['hostCpus'] == 4:
                    correct_owned_affinity(owned, profile)
                else:
                    verify_children_affinity(owned, profile, 'pretest-no-correction')
                owned.start_measurement(profile)

            def tests(owned, state):
                for stage in STAGES:
                    # Same test APK, default async injector and same legacy evidence
                    # layout as the main 2-host-CPU run. Restore its exact fixture
                    # bytes just before layout; this is setup, never a click substitute.
                    if stage == 'layout':
                        output = session.adb(owned,state,['push',str(FIXTURE),
                            '/sdcard/Android/data/'+PACKAGE+'/files/input-ab-fixture.json'],30)
                        (evidence / 'fixture-push.txt').write_text(output)
                    verify_children_affinity(owned, profile, 'before-'+stage)
                    owned.record('capacity-stage-start', stage=stage, **session.memory_usage())
                    args=['shell','am','instrument','-w','-r','-e','stage',stage]
                    if stage == 'layout': args += ['-e','fixture','restore']
                    args += [PACKAGE+'.test/io.gitlab.maik3531.magnolietabletbeta.NativeTabletInstrumentation']
                    try:
                        output=session.adb(owned,state,args,120)
                    except Exception as exc:
                        report['stages'][stage]=dict(status='infrastructure-failure-or-deadline', error=str(exc))
                        raise
                    (evidence / (stage+'-instrumentation.txt')).write_text(output)
                    print(output,flush=True)
                    result,_=json.JSONDecoder().raw_decode(output.split('INSTRUMENTATION_RESULT: stream=',1)[1].lstrip())
                    accepted=(result.get('stage')==stage and result.get('sourceHash')==binding['appSourceHash'] and
                              result.get('sdk')==opts.api and
                              result.get('webview')==report['runtime']['webviewVersion'] and
                              result.get('injector')=='async' and result.get('passed') is True and
                              bool(re.search(r'INSTRUMENTATION_CODE:\s*-1\b',output)))
                    report['stages'][stage]=dict(status='passed' if accepted else 'failed', nativeProof=result)
                    verify_children_affinity(owned, profile, 'after-'+stage)
                    owned.record('capacity-stage-end',stage=stage,passed=accepted,**session.memory_usage())
                    if not accepted: return 1
                report['nativeUiPassed']=True
                return 0

            code=session.run_session(owner,config,after_boot=install,run_tests=tests)
        except Exception as exc:
            code=124 if isinstance(exc,session.Deadline) else 1
            report['nativeUiPassed']=False
            report['error']=str(exc)
            owner.record('capacity-failed',error=str(exc))
        finally:
            # Corrections never resume after measurement, including on failure.
            owner.measurement_active = False
            if evidence and owner.state.get('booted') and not owner.signal:
                for name,command in {
                    'native-evidence-pull':['pull','/sdcard/Android/data/'+PACKAGE+'/files/native-evidence',str(evidence)],
                    'android-test-log':['logcat','-b','all','-d','-v','threadtime','-s','AndroidRuntime:E','chromium:E','TabletNativeTest:I'],
                    'app-exit-info':['shell','dumpsys','activity','exit-info',PACKAGE],
                }.items():
                    try: (evidence / (name+'.txt')).write_text(session.adb(owner,owner.state,command,30))
                    except Exception as exc:
                        report.setdefault('collectionErrors',[]).append(name+': '+str(exc)); code=code or 1
                fixture=evidence / 'native-evidence/legacy/fixture.json'
                report['restoredFixtureBytesMatch']=fixture.is_file() and sha(fixture)==binding['fixtureSha256']
                if report['stages']['layout']['status']=='passed' and not report['restoredFixtureBytesMatch']:
                    code=1; report['nativeUiPassed']=False
            report['resourcesAtCleanup'] = session.memory_usage()
            try:
                group = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
                report['memoryEventsAtCleanup'] = dict((k,int(v)) for k,v in
                    (line.split() for line in (group/'memory.events').read_text().splitlines()))
            except OSError as exc:
                report['memoryEventsReadError'] = str(exc)
            owner.close()
            try:
                if frozen_binding()!=binding: raise RuntimeError('Source/APK/tool binding changed during run')
            except Exception as exc:
                code=1; report['nativeUiPassed']=False; report['bindingError']=str(exc)
            report.update(exitCode=code,evidence=str(evidence) if evidence else None,
                          qualifiedResult=('PASS only at '+profile['qualification']) if report['nativeUiPassed'] else 'BLOCKED at '+profile['qualification'])
            owner.record('finished',exitCode=code,capacityProfile=profile)
            if evidence:
                (evidence / 'owner-final.json').write_text(json.dumps(owner.state,indent=2)+'\n')
                (evidence / 'capacity-result.json').write_text(json.dumps(report,indent=2)+'\n')
            (ROOT / 'artifacts/host-capacity.json').write_text(json.dumps(report,indent=2)+'\n')
            (ROOT / f'artifacts/host-capacity-api{opts.api}.json').write_text(json.dumps(report,indent=2)+'\n')
    return code


if __name__=='__main__':
    sys.exit(main())
