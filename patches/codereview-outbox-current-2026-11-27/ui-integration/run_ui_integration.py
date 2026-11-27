#!/usr/bin/env python3
"""Run only the three requested UI integration programs; reuse existing tools."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/workspace/scratch/69a9d769e56f/outbox-latest-current')
OUTPUT = Path(__file__).resolve().parent
ASSETS = Path('/workspace/scratch/7203da5bd564/open-audit-final-source')
NODE = Path('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node')
NODE_PATH = Path('/workspace/scratch/7203da5bd564/round3-tools/js/node_modules')
HEAD = 'da81f594a2709d2c0ba78696b3af4775f38313f8'
PROGRAMS = [
    'appointment-organizer-suggestions.js',
    'calendar-colour-remainders.js',
    'legacy-android-instance-ui.js',
]
WEB_ROOTS = ['magnolie-organizer/web', 'magnolie-organizer-windows/app/web']
TIMEZONE_INPUTS = [
    'projection-assets.cjs', 'resolver.js', 'port-runtime.js',
    'bootstrap.template.js', 'tzdb-2026egtz.json', 'provenance.json', 'LICENSE-tzdb.txt',
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def bind(paths):
    return [{'path': path, 'sha256': sha(ROOT / path), 'bytes': (ROOT / path).stat().st_size}
            for path in sorted(paths)]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assert git('rev-parse', 'HEAD') == HEAD
    assert not git('diff', '--name-only'), 'Unexpected unstaged product-source changes'
    timezone_inputs = []
    for name in TIMEZONE_INPUTS:
        relative = 'port-adapters/timezones/' + name
        assert (ROOT / relative).read_bytes() == (ASSETS / relative).read_bytes(), relative
        timezone_inputs.append({'path': relative, 'sha256': sha(ROOT / relative),
                                'equal_to_asset_source': True})
    env = dict(os.environ)
    # Do not inherit a single-web selector or an optional native-codec fixture.
    for key in list(env):
        if key.startswith('MAGNOLIE_'):
            env.pop(key)
    env.update(NODE_PATH=str(NODE_PATH), PYTHONDONTWRITEBYTECODE='1',
               MAGNOLIE_PYTHON=shutil.which('python3'))
    runtime = {
        'node': str(NODE),
        'node_version': subprocess.check_output([str(NODE), '--version'], text=True).strip(),
        'node_path': str(NODE_PATH),
        'jsdom_version': json.loads((NODE_PATH / 'jsdom/package.json').read_text())['version'],
        'python': env['MAGNOLIE_PYTHON'],
        'python_version': subprocess.check_output([env['MAGNOLIE_PYTHON'], '--version'], text=True).strip(),
        'installed_dependencies': False,
    }
    inputs = {'magnolie-organizer-windows/tests/' + item for item in PROGRAMS + [
        'desktop-state-regressions.js', 'save-custom-regressions.js']}
    inputs.update([
        'contracts/calendar-color-remainders.json',
        'contracts/personal-custom-consent-v4-vectors.json',
        'magnolie-organizer/bin/magnolie-organizer',
        'magnolie-organizer/pruefungen/fixtures/caldav-series-resource.ics',
    ])
    inputs.update('port-adapters/timezones/' + name for name in TIMEZONE_INPUTS)
    inputs.update(str(path.relative_to(ROOT)) for path in (ROOT / 'magnolie-organizer/bin').glob('*.py'))
    for web in WEB_ROOTS:
        inputs.update(web + '/' + name for name in [
            'index.html', 'i18n.js', 'zeichenblatt.js', 'normative-timezones.js', 'anwendung.js'])
        if (ROOT / web / 'appearance.js').exists():
            inputs.add(web + '/appearance.js')

    added, generated = [], []
    try:
        for web in WEB_ROOTS:
            relative = web + '/normative-timezones.js'
            source, destination = ASSETS / relative, ROOT / relative
            if not destination.exists():
                with destination.open('xb') as stream:
                    stream.write(source.read_bytes())
                added.append(destination)
            assert sha(destination) == sha(source)
            generated.append({'path': relative, 'source': str(source), 'sha256': sha(source),
                              'temporary_added_by_runner': destination in added})
        before = bind(inputs)

        def run(program):
            command = [str(NODE), str(ROOT / 'magnolie-organizer-windows/tests' / program)]
            started = time.monotonic()
            timed_out = False
            try:
                process = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                         text=True, timeout=60)
                code, stdout, stderr = process.returncode, process.stdout, process.stderr
            except subprocess.TimeoutExpired as error:
                timed_out = True
                code = 124
                stdout = error.stdout or b''
                stderr = error.stderr or b''
                if isinstance(stdout, bytes):
                    stdout = stdout.decode(errors='replace')
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors='replace')
                stderr += '\nRunner stopped this program at the 60-second bound.\n'
            log = OUTPUT / (program + '.log')
            log.write_text(stdout + stderr)
            result = {'program': program, 'argv': command, 'cwd': str(ROOT),
                      'environment_overrides': {key: env[key] for key in (
                          'NODE_PATH', 'PYTHONDONTWRITEBYTECODE', 'MAGNOLIE_PYTHON')},
                      'unset_inherited_environment': 'All MAGNOLIE_* variables before explicit overrides',
                      'exit_code': code, 'timed_out': timed_out,
                      'seconds': round(time.monotonic() - started, 3),
                      'log': log.name, 'log_sha256': sha(log),
                      'summary_lines': [line for line in stdout.splitlines()
                                        if line.startswith(('PASS ', 'FAIL ')) or 'cases passed' in line],
                      'passed': code == 0 and not timed_out}
            (OUTPUT / (program + '.result.json')).write_text(json.dumps(result, indent=2) + '\n')
            print(program + ': exit=' + str(code) + ', seconds=' + str(result['seconds']), flush=True)
            return result

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(run, PROGRAMS))
        after = bind(inputs)
        inputs_unchanged = before == after
    finally:
        for path in added:
            path.unlink()
    result = {
        'date_utc': datetime.now(timezone.utc).isoformat(),
        'base_commit': HEAD,
        'worktree': str(ROOT),
        'integration': 'Current da81 main plus prepared remainder; product sources bound by per-file hashes.',
        'scope': '#395 organizer suggestions with adopted #844 colors and #846 legacy alias normalization',
        'runtime': runtime,
        'timezone_generator_inputs': timezone_inputs,
        'reused_generated_assets': generated,
        'temporary_assets_removed': all(not path.exists() for path in added),
        'bound_inputs_before': before,
        'bound_inputs_after': after,
        'inputs_unchanged_during_runs': inputs_unchanged,
        'head_after': git('rev-parse', 'HEAD'),
        'unstaged_product_changes_after': git('diff', '--name-only'),
        'results': results,
        'passed': all(item['passed'] for item in results) and inputs_unchanged,
        'limits': [
            'Exactly the three requested programs ran; no full suite or additional product test was executed.',
            'Both actual desktop frontend sources ran in JSDOM; no GTK/WebView native rendering or installed-package acceptance.',
            'Calendar color tests used their built-in synthetic DTO inputs, not native Windows codec outputs.',
            'Legacy alias tests used the actual current Python codec with the repository synthetic ICS fixture; no native Windows codec execution.',
            'Save acknowledgments, timers and bridge behavior are synthetic test harness behavior.',
            'No product source changes, dependency installation, external mutation or release.',
        ],
    }
    (OUTPUT / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print('passed=' + str(result['passed']) + '; inputs_unchanged=' + str(inputs_unchanged), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
