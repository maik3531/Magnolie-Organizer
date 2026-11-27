#!/usr/bin/env python3
"""Run the affected UI programs once against the assembled review patch series."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--checkout', type=Path, required=True)
p.add_argument('--tools', type=Path, required=True)
p.add_argument('--node', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--extra-test', action='append', default=[])
a = p.parse_args()
root, prepared, out = a.checkout.resolve(), a.tools.resolve(), a.output.resolve()
evidence = Path(__file__).resolve().parent
out.mkdir(parents=True, exist_ok=True)
env_values = {'TZ': 'Europe/Berlin', 'NODE_PATH': str(prepared / 'js/node_modules'),
              'MAGNOLIE_TEST_SOURCE_ROOT': str(root)}
env_values['PATH'] = str(prepared / 'gettext/usr/bin') + os.pathsep + os.environ.get('PATH', '')
env_values['LD_LIBRARY_PATH'] = str(prepared / 'gettext/usr/lib/x86_64-linux-gnu')
env = dict(os.environ, **env_values)
sha = lambda b: hashlib.sha256(b).hexdigest()

def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
assert not git('status', '--porcelain'), 'Final integration requires a clean source tree'
tests = ['phone-media-wait-ui.js', 'phone-media-recovery-mount-ui.js',
         'phone-media-ui.js', 'phone-media-source-choice-ui.js',
         'appointment-organizer-suggestions.js', 'structured-appointment-parity.js',
         'recurrence-worker.js', 'calendar-accent-edits.js', 'category-colors.js',
         'kde-contact-import.js', 'note-import-attachments.js'] + a.extra_test
assert len(tests) == len(set(tests))
paths = git('ls-files', 'magnolie-organizer/web', 'magnolie-organizer-windows/app/web',
            'magnolie-organizer-windows/tests', 'port-adapters/timezones',
            'Magnolie-Organizer-macOS-Beta/tools/project_ui.py').splitlines()
paths = [name for name in paths if name.endswith(('.js', '.cjs', '.json', '.html', '.py', '.snippets'))]
inputs = {name: sha((root / name).read_bytes()) for name in paths}
manifest = {'head': head, 'tree': tree, 'environment': env_values,
            'node': subprocess.check_output([str(a.node), '--version'], text=True).strip(),
            'source_inputs': inputs, 'runs': [],
            'limits': 'Real desktop JavaScript in JSDOM with synthetic data and controlled native bridges. No installed Windows/Linux UI, native Notes transfer, package or 30-day acceptance.'}

def run(name, command):
    command = list(map(str, command))
    start = time.monotonic()
    result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=240)
    log = out / (name + '.log')
    log.write_bytes(result.stdout)
    row = {'name': name, 'command': command, 'cwd': str(root), 'exit_code': result.returncode,
           'seconds': round(time.monotonic() - start, 3), 'log': log.name, 'sha256': sha(result.stdout)}
    manifest['runs'].append(row)
    print(json.dumps(row), flush=True)

for web in ['magnolie-organizer/web', 'magnolie-organizer-windows/app/web']:
    run('prepare-' + web.split('/')[0], [prepared / 'python/bin/python',
        'magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py', '--source',
        'port-adapters/timezones', '--output', web])
for language in (root / 'magnolie-organizer/po/LINGUAS').read_text().split():
    run('prepare-locale-' + language, [prepared / 'python/bin/python',
        'magnolie-organizer/werkzeuge/po_zu_js.py', language,
        'magnolie-organizer/po/' + language + '.po',
        'magnolie-organizer/web/i18n/' + language + '.js'])
manifest['generated_assets'] = {str(f.relative_to(root)): sha(f.read_bytes())
    for web in ['magnolie-organizer/web', 'magnolie-organizer-windows/app/web']
    for f in [root / web / 'normative-timezones.js', *sorted((root / web / 'i18n').glob('*.js'))] if f.is_file()}
for test in tests:
    assert (root / 'magnolie-organizer-windows/tests' / test).is_file(), test
    run(test, [a.node, Path('magnolie-organizer-windows/tests') / test])
run('worker-independent-ownership', [a.node, evidence / 'performance/843/independent-ownership-review.cjs',
    root, out / 'worker-independent-ownership.json'])
run('timezone-projection-adapters', [prepared / 'python/bin/python',
    evidence / 'performance/843/check_projection.py', root])
manifest['inputs_unchanged'] = all(sha((root / name).read_bytes()) == digest for name, digest in inputs.items())
manifest['head_unchanged'] = git('rev-parse', 'HEAD') == head
manifest['worktree_status_after'] = git('status', '--porcelain')
manifest['passed'] = (all(r['exit_code'] == 0 for r in manifest['runs'])
    and manifest['inputs_unchanged'] and manifest['head_unchanged']
    and not manifest['worktree_status_after'])
(out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
raise SystemExit(0 if manifest['passed'] else 1)
