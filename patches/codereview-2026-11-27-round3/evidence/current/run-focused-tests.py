#!/usr/bin/env python3
"""Run the six requested groups against the already-built current-source host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

FILTERS = [
    ('restore-identity', 'Additive restore'),
    ('recovery-journal', 'Wiederherstellungsjournal'),
    ('unicode-import', 'UTF-16 import'),
    ('exchange', 'ICS / VCF / LDIF / Claws / Lotus / Thunderbird'),
    ('import-file', 'Import file / native readers'),
    ('lotus-tasks', 'Lotus task CSV'),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root).decode().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True,
                        help='Product checkout containing the already-built CoreTests host.')
    parser.add_argument('--tools', type=Path, required=True,
                        help='Tool directory containing dotnet/dotnet, dotnet-state and nuget.')
    parser.add_argument('--output', type=Path, required=True,
                        help='Evidence directory containing core-build.log; receives test logs and manifest.')
    args = parser.parse_args()
    ROOT = args.checkout.resolve()
    TOOLS = args.tools.resolve()
    OUT = args.output.resolve()
    DOTNET = TOOLS / 'dotnet/dotnet'
    WINDOWS = ROOT / 'magnolie-organizer-windows'
    DLL = WINDOWS / 'tests/bin/Debug/net8.0/CoreTests.dll'
    ENVIRONMENT = {
        'DOTNET_CLI_HOME': str(TOOLS / 'dotnet-state'),
        'NUGET_PACKAGES': str(TOOLS / 'nuget'),
        'DOTNET_CLI_TELEMETRY_OPTOUT': '1',
        'DOTNET_GENERATE_ASPNET_CERTIFICATE': 'false',
        'TZ': 'Europe/Berlin',
        'MAGNOLIE_TEST_SOURCE_ROOT': str(ROOT),
    }
    env = dict(os.environ, **ENVIRONMENT)
    bound_files = [
        DLL, WINDOWS / 'tests/CoreTests.csproj',
        WINDOWS / 'tests/packages.lock.json',
        WINDOWS / 'ExchangeCodec.cs', WINDOWS / 'RestoreSelection.cs',
        WINDOWS / 'tests/ContractGroupTests.cs',
        WINDOWS / 'tests/UnicodeImportTests.cs',
        ROOT / 'contracts/restore-additive-identity-vectors.json',
    ]
    bindings = {str(path.relative_to(ROOT)): sha256(path) for path in bound_files}
    manifest = {
        'source_commit': git(ROOT, 'rev-parse', 'HEAD'),
        'source_tree': git(ROOT, 'rev-parse', 'HEAD^{tree}'),
        'sdk_version': subprocess.check_output([str(DOTNET), '--version'], env=env).decode().strip(),
        'environment': ENVIRONMENT,
        'build_command': [str(DOTNET), 'build', 'tests/CoreTests.csproj', '--nologo',
                          '--verbosity', 'quiet', '-p:RestoreLockedMode=true'],
        'build_command_role': 'Suggested prerequisite command; not executed by this runner.',
        'build_working_directory': str(WINDOWS),
        'build_executed_by_runner': False,
        'build_log': 'core-build.log',
        'build_log_sha256': sha256(OUT / 'core-build.log'),
        'build_log_provenance': 'Pre-existing log supplied by the caller; this runner hashes the log but does not verify its build result.',
        'build_exit_code': None,
        'bindings': bindings,
        'tests': [],
        'scope': 'Actual C# CoreTests source host under .NET 8 on Linux; no native Windows GUI or release-package acceptance.',
    }
    for name, selected in FILTERS:
        log = OUT / (name + '.log')
        command = [str(DOTNET), str(DLL), selected]
        started = time.monotonic()
        with log.open('wb') as output:
            run = subprocess.run(command, cwd=WINDOWS, env=env,
                                 stdout=output, stderr=subprocess.STDOUT, timeout=300)
        text = log.read_text()
        summary = re.search(r'CoreTests: (\d+)/(\d+) Gruppen bestanden\.', text)
        passed = bool(run.returncode == 0 and summary and summary.groups() == ('1', '1'))
        row = {'name': name, 'filter': selected, 'command': command,
               'exit_code': run.returncode, 'passed': passed,
               'elapsed_seconds': round(time.monotonic() - started, 3),
               'groups': summary.group(0) if summary else None,
               'log': log.name, 'log_sha256': sha256(log)}
        manifest['tests'].append(row)
        print(json.dumps(row), flush=True)
    manifest['passed_groups'] = sum(row['passed'] for row in manifest['tests'])
    manifest['expected_groups'] = len(FILTERS)
    manifest['working_tree_clean_after_tests'] = git(ROOT, 'status', '--porcelain') == ''
    manifest['bound_inputs_unchanged_after_tests'] = all(sha256(ROOT / path) == digest for path, digest in bindings.items())
    (OUT / 'core-tests-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    assert manifest['passed_groups'] == len(FILTERS), 'A focused CoreTests group failed.'
    assert manifest['working_tree_clean_after_tests'], 'Product checkout changed during tests.'
    assert manifest['bound_inputs_unchanged_after_tests'], 'A bound input changed during tests.'


if __name__ == '__main__':
    main()
