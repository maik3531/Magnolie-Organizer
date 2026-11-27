#!/usr/bin/env python3
"""#807: compile the actual Android instrumentation source set; no APK/device execution."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

BASE = Path('/workspace/scratch/acde70e8594b')
REPO = BASE / 'Magnolie-Organizer'
ROOT = REPO / 'Magnolie-Organizer-Android-Tablet-Beta'
DEPS = BASE / 'tablet-build-dependencies'
OUT = Path(__file__).resolve().parent
SMOKE = 'Magnolie-Organizer-Android-Tablet-Beta/app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeSystemProviderSmoke.kt'
PREVIOUS = BASE / 'tablet-system-records-checks/compile-receipt-before-isolation.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


previous = json.loads(PREVIOUS.read_text())
for name, digest in previous['sourceHashes'].items():
    if name != SMOKE and sha(REPO / name) != digest:
        raise SystemExit('Unchanged compiled source no longer matches: ' + name)
for name, digest in previous['resourceHashes'].items():
    if sha(REPO / name) != digest:
        raise SystemExit('Unchanged compiled resource no longer matches: ' + name)
for name, digest in previous['dependencyHashes'].items():
    if sha(DEPS / name) != digest:
        raise SystemExit('Dependency hash mismatch: ' + name)
old_run = Path(previous['runDirectory'])
run = Path(tempfile.mkdtemp(prefix='compile-', dir=OUT))
classes = run / 'instrumentation-classes'
classes.mkdir()
jars = sorted(DEPS / name for name in previous['dependencyHashes'] if name.endswith('.jar'))
compiler_cp = os.pathsep.join(map(str, jars))
product = old_run / 'product-classes'
java_classes = old_run / 'instrumentation-classes'
sources = sorted((ROOT / 'app/src/androidTest/java').rglob('*.kt')) + sorted((ROOT / 'tests/input').rglob('*.kt'))
before = {str(path.relative_to(REPO)): sha(path) for path in sources}
command = ['java', '-cp', compiler_cp, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect',
    '-jvm-target', '17', '-classpath', compiler_cp + os.pathsep + str(product) + os.pathsep + str(java_classes),
    '-Xfriend-paths=' + str(product), '-d', str(classes), *map(str, sources)]
result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
(run / 'instrumentation-kotlin.log').write_text('$ ' + shlex.join(command) + '\n' + result.stdout + result.stderr + '\nexit=' + str(result.returncode) + '\n')
if result.returncode:
    raise SystemExit('Instrumentation compile failed: ' + str(run))
for name, digest in before.items():
    if sha(REPO / name) != digest:
        raise SystemExit('Source changed while compiling: ' + name)
native = BASE / 'tablet-followup-actions/run-45817099578-attempt-2-artifact/artifacts/native-evidence/20261126T122015/native-evidence/legacy'
receipt = dict(issue=807, result='passed', nativeRuntimeTest=False, apkBuild=False, fullGradleGate=False,
    api='37.2', intendedRuntimeApi=34, kotlin='2.4.21', java='21.0.13.1', jvmTarget=17,
    instrumentationKotlinFiles=len(sources), productKotlinFilesReused=previous['productKotlinFiles'],
    instrumentationJavaFilesReused=previous['instrumentationJavaFiles'], generatedResourceJavaFilesReused=1,
    localSourceBaseCommit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
    sourceFile=SMOKE, sourceFileSha256=sha(REPO/SMOKE), scriptSha256=sha(Path(__file__)), runDirectory=str(run),
    reusedFullCompileDirectory=str(old_run), reusedFullCompileReceiptSha256=sha(PREVIOUS),
    sourceHashes=previous['sourceHashes'] | before, resourceHashes=previous['resourceHashes'],
    dependencyHashes=previous['dependencyHashes'],
    originalNativeReceiptSha256=sha(native/'system-records-receipt.json'),
    originalNativeStageSha256=sha(native/'system-records.json'),
    originalActualSeriesCountKnown=False, aospSourceManifestSha256=sha(OUT/'aosp-source-manifest.json'),
    recurrenceFixtureUsesSyncMetadata=True, unsyncedLocalRecurrenceExceptionsTested=False)
(OUT/'compile-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({key:value for key,value in receipt.items() if not key.endswith('Hashes')},indent=2))
