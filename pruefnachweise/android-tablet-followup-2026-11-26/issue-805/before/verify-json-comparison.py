#!/usr/bin/env python3
"""Narrow #805 reproduction using the existing manifest-bound native/JVM toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('stage', choices=['before', 'after'])
args = parser.parse_args()
scratch = Path('/workspace/scratch/acde70e8594b')
repo = scratch / 'Magnolie-Organizer'
root = repo / 'Magnolie-Organizer-Android-Tablet-Beta'
deps = scratch / 'tablet-build-dependencies'
output = scratch / 'tablet-native-followup/issue-805' / args.stage
output.mkdir(parents=True, exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
previous_file = scratch / 'tablet-native-followup/full-compile/receipt.json'
previous = json.loads(previous_file.read_text())
for name, digest in previous['sourceHashes'].items():
    assert sha(repo / name) == digest, f'Product source changed: {name}'
expected = {}
for name in ['maven-dependency-manifest.json', 'android-compile-dependency-manifest.json']:
    for entry in json.loads((deps / name).read_text()):
        expected[entry['file']] = entry['sha256']
        if 'classes_file' in entry:
            expected[entry['classes_file']] = entry['classes_sha256']
expected['android-37.2.jar'] = json.loads((deps / 'android-platform-manifest.json').read_text())['android_jar_sha256']
for name, digest in expected.items():
    assert sha(deps / name) == digest, f'Dependency hash mismatch: {name}'
jars = sorted(deps / name for name in expected if name.endswith('.jar') and name != 'android-37.2.jar')
platform = deps / 'android-37.2.jar'
product = Path(previous['runDirectory']) / 'classes'
native_cp = os.pathsep.join(map(str, [platform, *jars, product]))
runtime_cp = os.pathsep.join(map(str, [*jars, product]))
test_dir = root / 'app/src/test/java/io/gitlab/maik3531/magnolietabletbeta'
names = ['DocumentRequestsTest', 'NativeCalendarFileFixtureTest', 'VaultTest', 'VaultJsonTest']
inputs = [test_dir / (name + '.kt') for name in names]
inputs.append(root / 'tests/input/NativeCalendarFileFixture.kt')
if args.stage == 'after':
    names.append('JsonValueComparisonTest')
    inputs += [test_dir / (name + '.kt') for name in ['JsonValueComparison', 'JsonValueComparisonTest']]
input_hashes = {str(p.relative_to(repo)): sha(p) for p in inputs}
for p in inputs:
    dest = output / 'source-inputs' / p.relative_to(repo)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, dest)
classes = output / 'test-classes'
classes.mkdir(exist_ok=True)
commands = []
def run(label, command, env=None):
    result = subprocess.run(list(map(str, command)), cwd=repo, capture_output=True, text=True, env=env)
    log = output / (label + '.log')
    log.write_text('$ ' + shlex.join(list(map(str, command))) + '\n' + result.stdout + result.stderr + f'\nexit={result.returncode}\n')
    commands.append({'name': label, 'command': list(map(str, command)), 'exitCode': result.returncode, 'log': str(log), 'logSha256': sha(log)})
    return result
java = run('java-version', ['java', '-version'])
javap = run('android-json-api', ['java', '-m', 'jdk.jdeps/com.sun.tools.javap.Main', '-classpath', platform, 'org.json.JSONObject'])
assert javap.returncode == 0 and ' similar(' not in javap.stdout
compile_result = run('test-kotlin', ['java', '-XX:ActiveProcessorCount=2', '-Xmx512m', '-cp', native_cp,
    'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect', '-jvm-target', '17',
    '-Xfriend-paths=' + str(product), '-classpath', native_cp, '-d', classes, *inputs])
receipt = {
    'issue': 805, 'stage': args.stage,
    'gitHead': subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip(),
    'scriptSha256': sha(Path(__file__)), 'androidApi': '37.2', 'jvmTarget': 17,
    'compiler': 'Kotlin 2.4.21', 'java': java.stderr.strip(),
    'compileClasspathStartsWithAndroidJar': True,
    'previousProductReceipt': str(previous_file), 'previousProductReceiptSha256': sha(previous_file),
    'sourceHashes': previous['sourceHashes'], 'testInputHashes': input_hashes,
    'productClassHashes': {str(p.relative_to(product)): sha(p) for p in sorted(product.rglob('*')) if p.is_file()},
    'dependencyHashes': expected, 'commands': commands,
    'apkBuild': False, 'gradleFullBuild': False, 'nativeRuntimeTest': False,
}
if args.stage == 'before':
    errors = [line for line in compile_result.stderr.splitlines() if 'error:' in line]
    receipt['expectedFailure'] = compile_result.returncode != 0 and len(errors) == 5 and all("unresolved reference 'similar'" in line.lower() for line in errors)
    receipt['compileErrors'] = errors
    print(compile_result.stdout + compile_result.stderr)
    assert receipt['expectedFailure'], 'Baseline did not reproduce exactly the five similar compiler failures'
else:
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    # Reuse source-bound, actually generated CI vectors; do not recreate or rewrite their contents.
    vectors = scratch / 'tablet-followup-actions/run-45809316206-artifact/artifacts/a3-editor-vectors.json'
    projection = root / 'app/build/generated/projection/assets/projection.json'
    assert json.loads(vectors.read_text())['sourceHash'] == json.loads(projection.read_text())['sourceHash']
    fixture_root = output / 'source-bound-test-input'
    bound_inputs = {'artifacts/a3-editor-vectors.json': vectors,
        'app/build/generated/projection/assets/projection.json': projection}
    for name, p in bound_inputs.items():
        dest = fixture_root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        assert sha(dest) == sha(p)
    resources = root / 'app/src/test/resources'
    receipt['runtimeInputHashes'] = {str(p): sha(p) for p in [vectors, projection, resources / 'calendar-files-native-merge.json']}
    env = dict(os.environ)
    assert 'NATIVE_CALENDAR_MERGE_RECORD' not in env, 'Golden-file recording must be disabled'
    junit = run('junit', ['java', '-XX:ActiveProcessorCount=2', '-Xmx512m', '-Dtablet.root=' + str(fixture_root),
        '-cp', runtime_cp + os.pathsep + str(classes) + os.pathsep + str(resources), 'org.junit.runner.JUnitCore',
        *['io.gitlab.maik3531.magnolietabletbeta.' + name for name in names]], env)
    receipt['junitPassed'] = junit.returncode == 0
    receipt['junitOutput'] = junit.stdout + junit.stderr
    print(junit.stdout + junit.stderr)
for name, digest in input_hashes.items():
    assert sha(repo / name) == digest, f'Test input changed during verification: {name}'
for name, digest in previous['sourceHashes'].items():
    assert sha(repo / name) == digest, f'Product input changed during verification: {name}'
(output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Receipt:', output / 'receipt.json')
if args.stage == 'after':
    assert receipt['junitPassed'], 'JUnit failed; see receipt and log'
