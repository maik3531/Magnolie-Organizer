#!/usr/bin/env python3
"""Bind focused, existing and newly reproduced checks to the final review tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--checkout', type=Path, required=True)
p.add_argument('--tools', type=Path, required=True)
p.add_argument('--node', type=Path, required=True)
p.add_argument('--extra-test', action='append', default=[])
a = p.parse_args()
root, prepared, here = a.checkout.resolve(), a.tools.resolve(), Path(__file__).resolve().parent
out = here / 'integration-final-current'
out.mkdir(exist_ok=True)
python = prepared / 'python/bin/python'
dotnet = prepared / 'dotnet/dotnet'
win = root / 'magnolie-organizer-windows'
dll = win / 'tests/bin/Debug/net8.0/CoreTests.dll'
env = dict(os.environ, TZ='Europe/Berlin', NODE_PATH=str(prepared / 'js/node_modules'),
    DOTNET_CLI_HOME=str(prepared / 'dotnet-state'), NUGET_PACKAGES=str(prepared / 'nuget'),
    DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_GENERATE_ASPNET_CERTIFICATE='false')
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
assert not git('status', '--porcelain')
manifest = {'head': head, 'tree': tree, 'base': '7a490dd87e94eec08d7f09cb95a04b34bf4621c2',
    'runs': [], 'manifest_paths': [],
    'scope': 'Focused integration of reviewed patches on a clean frozen tree. Actual codecs, native disk writers and synthetic host UI/transports. No installed product, real device, live server or 30-day native acceptance.'}

def run(name, command, cwd=root, expected_manifest=None, required=True, extra=None, expected_groups=None):
    args = list(map(str, command))
    start = time.monotonic()
    log = out / (name + '.log')
    with log.open('wb') as stream:
        result = subprocess.run(args, cwd=cwd, env={**env, **(extra or {})},
            stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    row = {'name': name, 'command': args, 'cwd': str(cwd), 'exit_code': result.returncode,
        'seconds': round(time.monotonic()-start, 3), 'log': str(log.relative_to(here)),
        'sha256': sha(log), 'required_gate': required}
    if expected_manifest:
        f = here / expected_manifest
        row['manifest'] = expected_manifest
        row['manifest_exists'] = f.is_file()
        if f.is_file():
            row['manifest_sha256'] = sha(f)
            manifest['manifest_paths'].append(expected_manifest)
    match = re.search(r'CoreTests: (\d+)/(\d+) Gruppen bestanden', log.read_text())
    if match:
        row.update(passed_groups=int(match[1]), total_groups=int(match[2]))
    if expected_groups is not None:
        row['expected_groups'] = expected_groups
        row['group_count_matches'] = row.get('passed_groups') == row.get('total_groups') == expected_groups
    manifest['runs'].append(row)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(row), flush=True)
    if required and (result.returncode or row.get('group_count_matches') is False):
        raise RuntimeError(name + ' failed; inspect preserved log')

try:
    run('csv-restore-build', [python, here/'run-validation.py', '--checkout', root,
        '--tools', prepared, '--output', here/'validation/final-current', '--phase', 'after',
        '--base-commit', manifest['base']], expected_manifest='validation/final-current/manifest.json')
    manifest['assembly_sha256'] = sha(dll)
    run('semantic-import-export', [python, here/'run-import-export-checks.py', '--checkout', root,
        '--tools', prepared, '--output', here/'import-export/final-current',
        '--extra-test', 'magnolie-organizer/pruefungen/test_nextcloud_ics_birthdays.py',
        '--extra-test', 'magnolie-organizer/pruefungen/test_nextcloud_anniversary_scope.py',
        *[part for test in a.extra_test for part in ['--extra-test', test]]],
        expected_manifest='import-export/final-current/manifest.json')
    run('desktop-ui', [python, here/'run-final-ui.py', '--checkout', root,
        '--tools', prepared, '--node', a.node.resolve(), '--output', here/'desktop/evidence/final-current',
        '--extra-test', 'calendar-colour-remainders.js', '--extra-test', 'birthday-display.js',
        '--extra-test', 'legacy-android-instance-ui.js', '--extra-test', 'notes-original-fresh-readiness.js'],
        expected_manifest='desktop/evidence/final-current/manifest.json')
    run('actual-color-storage-pipeline', [python, here/'import-export/remainder/run-pipeline.py',
        '--checkout', root, '--tools', prepared, '--output', here/'import-export/final-current-pipeline',
        '--skip-core-build'], expected_manifest='import-export/final-current-pipeline/pipeline-manifest.json')
    for name, term in [('csharp-nextcloud-birthday', 'Nextcloud ICS birthdays'),
                       ('csharp-dav', 'Nextcloud CalDAV'), ('csharp-dav-etag', 'DAV wildcard ETag')]:
        run(name, [dotnet, dll, term], win, extra={'MAGNOLIE_TEST_SOURCE_ROOT': str(win)}, expected_groups=1)
    internet=here/'internet-notes/final-prepared/manifest.json'
    previous=json.loads(internet.read_text())
    assert previous['passed']
    unchanged={name:digest for name,digest in previous['inputs'].items()
        if name.startswith('magnolie-notes/') or name in [
            'magnolie-organizer-windows/MagnolienbaumCoordinator.cs',
            'magnolie-organizer-windows/NextcloudMailbox.cs']}
    assert all(sha(root/name)==digest for name,digest in unchanged.items())
    manifest['internet_protocol_reused']={'path':str(internet.relative_to(here)),
        'sha256':sha(internet),'previous_head':previous['head'],
        'unchanged_transport_inputs':unchanged,
        'boundary':'Previously passed complete C# group on actual unchanged FS1/Notes/mailbox implementation. Current DOM readiness policy rerun in desktop UI group. No new Internet/device claim.'}
finally:
    manifest['head_unchanged'] = git('rev-parse', 'HEAD') == head
    manifest['tree_unchanged'] = git('rev-parse', 'HEAD^{tree}') == tree
    manifest['status_after'] = git('status', '--porcelain')
    manifest['all_required_completed'] = len([r for r in manifest['runs'] if r['required_gate']]) == 7
    manifest['required_passed'] = (manifest['all_required_completed'] and
        all(r['exit_code']==0 and r.get('group_count_matches', True) for r in manifest['runs'] if r['required_gate']) and
        manifest['head_unchanged'] and manifest['tree_unchanged'] and not manifest['status_after'])
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
