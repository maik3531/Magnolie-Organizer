#!/usr/bin/env python3
"""Build and validate the pinned integration with existing repository test hosts.

Usage: python3 run-focused-tests.py --checkout REPO --tools PREPARED_TOOLS --output OUTPUT
Use --contact-only for the red baseline: four Python files and the C# identity group.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

PYTHON_TESTS = [
    'magnolie-organizer/pruefungen/test_restore_identity.py',
    'magnolie-organizer/pruefungen/test_save_restore_boundary.py',
    'magnolie-organizer/pruefungen/test_restore_commit_result.py',
    'magnolie-organizer/pruefungen/test_backup_profile_validation.py',
]
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--contact-only', action='store_true')
    args = parser.parse_args()
    root, tools, out = args.checkout.resolve(), args.tools.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Required by the existing test_restore_commit_result.py fixture.
    Path('/tmp/opencode').mkdir(parents=True, exist_ok=True)
    windows = root / 'magnolie-organizer-windows'
    dotnet = tools / 'dotnet/dotnet'
    python = tools / 'python/bin/python'
    dll = windows / 'tests/bin/Debug/net8.0/CoreTests.dll'
    environment = {
        'DOTNET_CLI_HOME': str(tools / 'dotnet-state'),
        'NUGET_PACKAGES': str(tools / 'nuget'),
        'DOTNET_CLI_TELEMETRY_OPTOUT': '1',
        'DOTNET_GENERATE_ASPNET_CERTIFICATE': 'false',
        'TZ': 'Europe/Berlin',
        'MAGNOLIE_TEST_SOURCE_ROOT': str(root),
    }
    env = dict(os.environ, **environment)

    def git(*values):
        return subprocess.check_output(['git', *values], cwd=root).decode().strip()

    paths = PYTHON_TESTS + [
        'magnolie-organizer/bin/magnolie-organizer',
        'magnolie-organizer-windows/RestoreSelection.cs',
        'magnolie-organizer-windows/ExchangeCodec.cs',
        'magnolie-organizer-windows/tests/CoreTests.csproj',
        'magnolie-organizer-windows/tests/packages.lock.json',
        'magnolie-organizer-windows/tests/RestoreSelectionIdentityTests.cs',
        'magnolie-organizer-windows/tests/ContractGroupTests.cs',
        'contracts/restore-additive-identity-vectors.json',
    ]
    bindings = {path: sha256(root / path) for path in paths}
    vectors = json.loads((root / paths[-1]).read_text())['cases']
    manifest = {
        'checkout_head': git('rev-parse', 'HEAD'),
        'checkout_head_tree': git('rev-parse', 'HEAD^{tree}'),
        'index_tree': git('write-tree'),
        'working_tree_status_before': git('status', '--porcelain'),
        'bindings': bindings,
        'vector_count': len(vectors),
        'environment': environment,
        'contact_only': args.contact_only,
        'build_executed_by_runner': True,
        'runs': [],
        'scope': 'Actual Python and .NET 8 C# repository tests on Linux; no native GUI or release-package acceptance.',
    }

    def run(name, command, cwd, timeout=300):
        command = [str(value) for value in command]
        log = out / (name + '.log')
        start = time.monotonic()
        with log.open('wb') as output:
            process = subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                     stderr=subprocess.STDOUT, timeout=timeout)
        result = {'name': name, 'command': command, 'cwd': str(cwd),
                  'exit_code': process.returncode,
                  'elapsed_seconds': round(time.monotonic() - start, 3),
                  'log': log.name, 'log_sha256': sha256(log)}
        manifest['runs'].append(result)
        print(json.dumps(result), flush=True)
        return result, log.read_text()

    py_result, py_log = run('python-restore', [python, '-m', 'pytest', '-q', *PYTHON_TESTS], root)
    manifest['python_counts'] = {kind: int(count) for count, kind in
        re.findall(r'(\d+) (passed|failed|skipped|errors?)', py_log)}
    build, _ = run('core-build', [dotnet, 'build', 'tests/CoreTests.csproj', '--nologo',
                                '--verbosity', 'quiet', '-p:RestoreLockedMode=true'], windows)
    manifest['build_exit_code'] = build['exit_code']
    if build['exit_code'] == 0:
        manifest['assembly_sha256'] = sha256(dll)
        selected = FILTERS[:1] if args.contact_only else FILTERS
        for name, selected_filter in selected:
            result, text = run(name, [dotnet, dll, selected_filter], windows)
            summary = re.search(r'CoreTests: (\d+)/(\d+) Gruppen bestanden\.', text)
            result['groups_passed'] = int(summary.group(1)) if summary else None
            result['groups_total'] = int(summary.group(2)) if summary else None
            result['passed'] = result['exit_code'] == 0 and summary is not None and summary.groups() == ('1', '1')
    manifest['working_tree_status_after'] = git('status', '--porcelain')
    manifest['bound_inputs_unchanged'] = all(sha256(root / p) == digest for p, digest in bindings.items())
    manifest['passed'] = all(row['exit_code'] == 0 and row.get('passed', True) for row in manifest['runs'])
    (out / 'focused-tests-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    assert manifest['bound_inputs_unchanged'], 'An input changed during validation.'
    return 0 if manifest['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
