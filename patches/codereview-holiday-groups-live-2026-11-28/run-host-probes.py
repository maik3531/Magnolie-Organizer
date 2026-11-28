#!/usr/bin/env python3
"""Refs #857. Reproduce provider regressions against published/corrected sources.

No network or installation. --toolchain contains Kotlin, Swift, and the exact
project JSON/ThreeTen JARs; --fixtures contains the unchanged captured responses.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--before', type=Path, required=True)
parser.add_argument('--after', type=Path, required=True)
parser.add_argument('--fixtures', type=Path, required=True)
parser.add_argument('--toolchain', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)

def digest(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def execute(label, command):
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True)
    (args.output / (label + '.log')).write_text(result.stdout + result.stderr)
    return result

paths = {
    'linux': Path('magnolie-organizer/bin/magnolie-organizer'),
    'swift': Path('Magnolie-Organizer-macOS-Beta/Sources/BetaCore/HolidayService.swift'),
    'kotlin': Path('Magnolie-Organizer-Android-Tablet-Beta/app/src/main/java/io/gitlab/maik3531/magnolietabletbeta/HolidayService.kt'),
}
linux_probe = args.after / 'magnolie-organizer/pruefungen/holiday_groups_854_probe.py'
swift_tests = args.after / 'Magnolie-Organizer-macOS-Beta/tests/holiday-groups-live'
kotlin_tests = args.after / 'Magnolie-Organizer-Android-Tablet-Beta/tests/holiday-groups-live'
swiftc = args.toolchain / 'swift/swift-6.4.3-RELEASE-debian13/usr/bin/swiftc'
kotlinc = args.toolchain / 'kotlin/kotlinc/bin/kotlinc'
jars = [args.toolchain / 'threetenbp-1.7.5.jar', args.toolchain / 'json-20240303.jar']
cp = ':'.join(str(jar) for jar in jars)
summary = {'sources': {}, 'tests': {}, 'fixtures': {}, 'dependencies': {}, 'runs': {}}
for name, command in [('python', [sys.executable, '--version']), ('java', ['java', '-version']),
                      ('swift', [swiftc, '--version']), ('kotlin', [kotlinc, '-version'])]:
    result = execute('version-' + name, command)
    summary['dependencies'][name] = (result.stdout + result.stderr).strip()
for jar in jars:
    summary['dependencies'][jar.name] = digest(jar)
for file in sorted(args.fixtures.glob('*.json')):
    summary['fixtures'][file.name] = digest(file)
for probe in [linux_probe, swift_tests / 'Doubles.swift', swift_tests / 'Probe.swift', kotlin_tests / 'Doubles.kt', kotlin_tests / 'Probe.kt']:
    summary['tests'][str(probe.relative_to(args.after))] = digest(probe)
for label, root in [('before', args.before), ('after', args.after)]:
    summary['sources'][label] = {str(path): digest(root / path) for path in paths.values()}
    summary['runs'][label] = {}
    result = execute('linux-' + label, [sys.executable, linux_probe, root, args.fixtures])
    parsed = json.loads(result.stdout)
    summary['runs'][label]['linux'] = {'exit': result.returncode, 'passed': parsed['passed'], 'total': parsed['total']}
    swift_program = args.output / ('swift-' + label)
    result = execute('swift-' + label + '-compile', [swiftc, root / paths['swift'], swift_tests / 'Doubles.swift', swift_tests / 'Probe.swift', '-o', swift_program])
    if result.returncode:
        raise SystemExit('Swift compilation failed: ' + label)
    result = execute('swift-' + label, [swift_program, args.fixtures])
    match = re.search(r'RESULT (\d+)/(\d+)', result.stdout)
    summary['runs'][label]['swift'] = {'exit': result.returncode, 'passed': int(match[1]), 'total': int(match[2])}
    kotlin_program = args.output / ('kotlin-' + label + '.jar')
    result = execute('kotlin-' + label + '-compile', [kotlinc, root / paths['kotlin'], kotlin_tests / 'Doubles.kt', kotlin_tests / 'Probe.kt', '-jvm-target', '17', '-cp', cp, '-include-runtime', '-d', kotlin_program])
    if result.returncode:
        raise SystemExit('Kotlin compilation failed: ' + label)
    result = execute('kotlin-' + label, ['java', '-cp', str(kotlin_program) + ':' + cp, 'io.gitlab.maik3531.magnolietabletbeta.ProbeKt', args.fixtures])
    match = re.search(r'^(\d+)/(\d+)$', result.stdout, re.M)
    summary['runs'][label]['kotlin'] = {'exit': result.returncode, 'passed': int(match[1]), 'total': int(match[2])}
(args.output / 'TEST-SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary['runs'], indent=2))
if any(result['exit'] != 0 or result['passed'] != result['total'] for result in summary['runs']['after'].values()):
    raise SystemExit(1)
