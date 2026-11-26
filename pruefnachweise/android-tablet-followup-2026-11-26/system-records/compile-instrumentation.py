#!/usr/bin/env python3
"""API/source compile only: real Android artifacts, no APK, device or Gradle-gate substitute."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import xml.etree.ElementTree as ET

BASE = Path('/workspace/scratch/acde70e8594b')
REPO = BASE / 'Magnolie-Organizer'
ROOT = REPO / 'Magnolie-Organizer-Android-Tablet-Beta'
DEPS = BASE / 'tablet-build-dependencies'
OUTPUT = Path(__file__).resolve().parent
RUN = Path(tempfile.mkdtemp(prefix='compile-', dir=OUTPUT))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(label, command):
    command = list(map(str, command))
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
    (RUN / (label + '.log')).write_text('$ ' + shlex.join(command) + '\n' + result.stdout + result.stderr + '\nexit=' + str(result.returncode) + '\n')
    if result.returncode:
        raise SystemExit(f'{label} failed ({result.returncode}); {RUN / (label + ".log")}')


dependencies = {}
for name in ('maven-dependency-manifest.json', 'android-compile-dependency-manifest.json'):
    for row in json.loads((DEPS / name).read_text()):
        dependencies[row['file']] = row['sha256']
        if 'classes_file' in row:
            dependencies[row['classes_file']] = row['classes_sha256']
dependencies['android-37.2.jar'] = json.loads((DEPS / 'android-platform-manifest.json').read_text())['android_jar_sha256']
dependencies['aapt2-36'] = json.loads((DEPS / 'aapt2-manifest.json').read_text())['aapt2_sha256']
for name, digest in dependencies.items():
    if sha(DEPS / name) != digest:
        raise SystemExit('Dependency hash mismatch: ' + name)
jars = sorted(DEPS / name for name in dependencies if name.endswith('.jar'))
compiler_cp = os.pathsep.join(map(str, jars))
platform = DEPS / 'android-37.2.jar'
aapt = DEPS / 'aapt2-36'
build = (ROOT / 'app/build.gradle.kts').read_text()
namespace = re.search(r'namespace\s*=\s*"([^"]+)"', build)[1]
projection = ROOT / 'app/build/generated/projection/res'
resources = [ROOT / 'app/src/main/AndroidManifest.xml'] + sorted(path for base in (ROOT / 'app/src/main/res', projection) for path in base.rglob('*') if path.is_file())
resource_hashes = {str(path.relative_to(REPO)): sha(path) for path in resources}
execute('java-version', ['java', '-version'])
execute('aapt-main', [aapt, 'compile', '--dir', ROOT / 'app/src/main/res', '-o', RUN / 'main-res.zip'])
execute('aapt-projection', [aapt, 'compile', '--dir', projection, '-o', RUN / 'projection-res.zip'])
manifest = ET.parse(ROOT / 'app/src/main/AndroidManifest.xml')
manifest.getroot().set('package', namespace)
manifest.write(RUN / 'AndroidManifest.xml', encoding='utf-8', xml_declaration=True)
execute('aapt-link', [aapt, 'link', '-I', platform, '--manifest', RUN / 'AndroidManifest.xml', '--java', RUN / 'generated',
    '--min-sdk-version', '26', '--target-sdk-version', '35', '--auto-add-overlay', '-R', RUN / 'main-res.zip',
    '-R', RUN / 'projection-res.zip', '-o', RUN / 'resources-only.ap_'])
product = RUN / 'product-classes'
tests = RUN / 'instrumentation-classes'
product.mkdir(); tests.mkdir()
resource_java = sorted((RUN / 'generated').rglob('*.java'))
if len(resource_java) != 1:
    raise SystemExit('Unexpected generated R input')
execute('resource-java', ['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '17', '-target', '17', '-d', product, *resource_java])
native = sorted((ROOT / 'app/src/main/java').rglob('*.kt'))
crypto = REPO / 'magnolie-notes/app/src/main/java/io/gitlab/maik3531/magnolienotes/daten'
native += [crypto / name for name in ('DatenDateiKrypto.kt', 'DateiDauerhaft.kt')]
android_test = sorted((ROOT / 'app/src/androidTest/java').rglob('*.kt'))
android_test += sorted((ROOT / 'tests/input').rglob('*.kt'))  # The actual Gradle androidTest source set.
android_java = sorted((ROOT / 'app/src/androidTest/java').rglob('*.java'))
source_hashes = {str(path.relative_to(REPO)): sha(path) for path in native + android_test + android_java}
cp = compiler_cp + os.pathsep + str(product)
execute('product-kotlin', ['java', '-cp', compiler_cp, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect',
    '-jvm-target', '17', '-classpath', cp, '-d', product, *native])
execute('instrumentation-java', ['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '17', '-target', '17',
    '-classpath', cp, '-d', tests, *android_java])
execute('instrumentation-kotlin', ['java', '-cp', compiler_cp, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect',
    '-jvm-target', '17', '-classpath', cp + os.pathsep + str(tests), '-Xfriend-paths=' + str(product), '-d', tests, *android_test])
for name, digest in (source_hashes | resource_hashes).items():
    if sha(REPO / name) != digest:
        raise SystemExit('Compile input changed: ' + name)
receipt = dict(result='passed', nativeRuntimeTest=False, apkBuild=False, fullGradleGate=False,
    api='37.2', intendedRuntimeApi=34, aapt2='36', kotlin='2.4.21', java='21.0.13.1', jvmTarget=17,
    productKotlinFiles=len(native), instrumentationKotlinFiles=len(android_test), instrumentationJavaFiles=len(android_java),
    generatedResourceJavaFiles=len(resource_java), scriptSha256=sha(Path(__file__)), runDirectory=str(RUN),
    sourceHashes=source_hashes, resourceHashes=resource_hashes, dependencyHashes=dependencies)
(OUTPUT / 'compile-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({key: value for key, value in receipt.items() if not key.endswith('Hashes')}, indent=2))
