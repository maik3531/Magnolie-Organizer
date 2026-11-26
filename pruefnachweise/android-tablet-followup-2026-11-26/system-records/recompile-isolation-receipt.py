#!/usr/bin/env python3
"""Recompile only androidTest Kotlin after the receipt-only source-isolation clarification.

Reuse the previously compiled, unchanged product and test-Java classes. This is
source/API compilation, not an APK build, Gradle gate or Android runtime test.
"""
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
OUTPUT = Path(__file__).resolve().parent
CHANGED = 'Magnolie-Organizer-Android-Tablet-Beta/app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeSystemProviderSmoke.kt'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


original = OUTPUT / 'compile-receipt-before-isolation.json'
if not original.exists():
    original.write_bytes((OUTPUT / 'compile-receipt.json').read_bytes())
previous = json.loads(original.read_text())
old_run = Path(previous['runDirectory'])
for name, digest in previous['sourceHashes'].items():
    if name != CHANGED and sha(REPO / name) != digest:
        raise SystemExit('Previously compiled source changed: ' + name)
for name, digest in previous['resourceHashes'].items():
    if sha(REPO / name) != digest:
        raise SystemExit('Previously compiled resource changed: ' + name)
for name, digest in previous['dependencyHashes'].items():
    if sha(DEPS / name) != digest:
        raise SystemExit('Dependency changed: ' + name)
run = Path(tempfile.mkdtemp(prefix='compile-isolation-', dir=OUTPUT))
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
        raise SystemExit('Instrumentation source changed while compiling: ' + name)
hashes = previous['sourceHashes'] | before
receipt = dict(result='passed', nativeRuntimeTest=False, apkBuild=False, fullGradleGate=False,
    api='37.2', intendedRuntimeApi=34, kotlin='2.4.21', java='21.0.13.1', jvmTarget=17,
    instrumentationKotlinFiles=len(sources), productKotlinFilesReused=previous['productKotlinFiles'],
    instrumentationJavaFilesReused=previous['instrumentationJavaFiles'], generatedResourceJavaFilesReused=1,
    contactsSourceIsolationTested=False, calendarSourceIsolationPlanned=True,
    change='Receipt metadata only; native checks not executed',
    scriptSha256=sha(Path(__file__)), runDirectory=str(run), reusedFullCompileDirectory=str(old_run),
    reusedFullCompileReceiptSha256=sha(original), sourceHashes=hashes,
    resourceHashes=previous['resourceHashes'], dependencyHashes=previous['dependencyHashes'])
(OUTPUT / 'compile-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
changed = json.loads((OUTPUT / 'changed-source-hashes.json').read_text())
for name, digest in changed.items():
    if name != CHANGED and sha(REPO / name) != digest:
        raise SystemExit('Unrelated owned file changed: ' + name)
changed[CHANGED] = sha(REPO / CHANGED)
(OUTPUT / 'changed-source-hashes.json').write_text(json.dumps(changed, indent=2) + '\n')
print(json.dumps({key: value for key, value in receipt.items() if not key.endswith('Hashes')}, indent=2))
print('NativeSystemProviderSmoke.kt SHA256:', changed[CHANGED])
