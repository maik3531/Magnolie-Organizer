"""Focused existing regressions at an unchanged pinned source checkout.

Usage: python run_checks.py REPO TOOLS OUTPUT {jvm|ui|helper}
No APK, device, Swift, native picker, OS provider, or live account is exercised.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

repo, tools, output = map(lambda value: Path(value).resolve(), sys.argv[1:4])
stage = sys.argv[4]
base = '3f4b69cafeb87b71dc622f0bfa3780e0a6a61b0f'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
assert head == base, (head, base)
output.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env['PATH'] = str(tools / 'gettext/usr/bin') + os.pathsep + env['PATH']
env['LD_LIBRARY_PATH'] = str(tools / 'gettext/usr/lib/x86_64-linux-gnu')
env['NODE_PATH'] = str(tools / 'js/node_modules')
env['MACOS_BETA_JSDOM'] = str(tools / 'js/node_modules/jsdom/lib/api.js')
env['PYTHONPATH'] = str(repo / 'Magnolie-Organizer-macOS-Beta/ImportHelper')
env['PYTHONDONTWRITEBYTECODE'] = '1'
mac = repo / 'Magnolie-Organizer-macOS-Beta'
tablet = repo / 'Magnolie-Organizer-Android-Tablet-Beta'
record = {'base_commit': base, 'stage': stage, 'scope': 'Existing focused host regressions only; no native OS/installed/device acceptance.',
          'source_files': {}, 'runs': [], 'environment': {name: env[name] for name in ['PATH', 'LD_LIBRARY_PATH', 'NODE_PATH', 'MACOS_BETA_JSDOM', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE']}}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def bind(paths):
    for path in paths:
        record['source_files'][str(path.relative_to(repo))] = sha(path)

def save():
    (output / f'{stage}-manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')

def run(name, args, cwd=None):
    started = time.monotonic()
    result = subprocess.run(args, cwd=cwd or repo, env=env, text=True, capture_output=True)
    log = output / (name + '.log')
    log.write_text(result.stdout + result.stderr)
    record['runs'].append({'name': name, 'command': list(map(str, args)), 'cwd': str(cwd or repo),
        'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3), 'log': log.name, 'sha256': sha(log)})
    print(name, 'exit', result.returncode, f'{time.monotonic()-started:.3f}s', flush=True)
    save()
    if result.returncode:
        print((result.stdout + result.stderr)[-12000:], flush=True)
        raise SystemExit(result.returncode)

def prepare_import_dependency():
    spec = importlib.util.spec_from_file_location('current_import_projector', mac / 'tools/project_import_helper.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pin = module.phone_pin((repo / module.PHONE_PIN).read_bytes())
    # Reuse the already verified dependency; acquisition/network is not needed.
    cached = repo.parent / 'round3-final/Magnolie-Organizer-macOS-Beta/.import-dependencies' / pin['filename']
    assert cached.is_file() and sha(cached) == pin['sha256']
    module.prepare_dependencies(repo, wheel=cached)
    record['reused_import_dependency'] = {'filename': pin['filename'], 'sha256': sha(cached)}
    save()

if stage == 'jvm':
    main = tablet / 'app/src/main/java/io/gitlab/maik3531/magnolietabletbeta'
    test = tablet / 'app/src/test/java/io/gitlab/maik3531/magnolietabletbeta/ProviderCodecMigrationTest.kt'
    sources = [main / (name + '.kt') for name in ['ProviderZone', 'TimeZoneExport', 'CalendarIdentity', 'ICalendarImport', 'ICalendarExport']] + [test]
    resources = [repo / 'port-adapters/timezones/tzdb-2026egtz.json', repo / 'port-adapters/timezones/LICENSE-tzdb.txt',
                 tablet / 'app/src/test/resources/calendar-export-system-zone-ui.json', tablet / 'app/build.gradle.kts']
    bind(sources + resources)
    jars = sorted((tools / 'kotlin').glob('*.jar'))
    record['dependencies'] = {path.name: sha(path) for path in jars}
    bp = tools / 'kotlin/threetenbp-1.7.5.jar'
    assert sha(bp) == '58c5593452f871ebf736dfda3bf8f3bc0de4e92cec61bc19c8ad81f9dfb70d72'
    assert sha(resources[0]) == '2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c'
    classes = output / 'provider-codec-classes'
    (classes / 'normative-timezones').mkdir(parents=True, exist_ok=True)
    for path in resources[:2]:
        shutil.copyfile(path, classes / 'normative-timezones' / path.name)
    cp = os.pathsep.join(map(str, jars))
    run('provider-codec-compile', ['java', '-cp', cp, 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-jvm-target', '17',
         '-no-stdlib', '-no-reflect', '-classpath', cp, '-d', str(classes), *map(str, sources)])
    runtime_cp = os.pathsep.join([str(classes), str(tablet / 'app/src/test/resources'), cp])
    run('provider-codec-junit', ['java', '-Xmx512m', '-XX:ActiveProcessorCount=2', '-Dtablet.root=' + str(tablet),
         '-cp', runtime_cp, 'org.junit.runner.JUnitCore', 'io.gitlab.maik3531.magnolietabletbeta.ProviderCodecMigrationTest'])
elif stage == 'ui':
    bind([repo / 'port-adapters/tests/occurrence-identity.cjs', repo / 'port-adapters/tests/fixtures/distinct-rid-same-slot.json',
          repo / 'port-adapters/occurrence-identity.js', repo / 'port-adapters/occurrence-identity-patch.json',
          repo / 'port-adapters/occurrence-identity-projection.cjs', repo / 'magnolie-organizer/web/anwendung.js',
          tablet / 'tools/project-web.cjs', mac / 'tools/project_ui.py'])
    for locale in (repo / 'magnolie-organizer/po/LINGUAS').read_text().split():
        (repo / 'magnolie-organizer/web/i18n').mkdir(exist_ok=True)
        run('catalog-' + locale, [sys.executable, 'magnolie-organizer/werkzeuge/po_zu_js.py', locale,
            'magnolie-organizer/po/' + locale + '.po', 'magnolie-organizer/web/i18n/' + locale + '.js'])
    prepare_import_dependency()
    run('mac-freeze', [sys.executable, str(mac / 'tools/project_ui.py'), 'freeze', '--confirm-desktop-frozen'])
    run('mac-project', [sys.executable, str(mac / 'tools/project_ui.py'), 'generate'])
    run('tablet-project', ['node', str(tablet / 'tools/project-web.cjs')])
    run('occurrence-identity-macos', ['node', 'port-adapters/tests/occurrence-identity.cjs', 'macos', str(mac / 'Generated/web')])
    run('occurrence-identity-tablet', ['node', 'port-adapters/tests/occurrence-identity.cjs', 'tablet', str(tablet / 'app/build/generated/projection/assets/web')])
    manifests = [mac / 'Generated/ProjectionManifest.json', tablet / 'app/build/generated/projection/assets/projection.json']
    record['projection_manifests'] = {str(path.relative_to(repo)): {'sha256': sha(path), 'content': json.loads(path.read_text())}
        for path in manifests if path.is_file()}
    save()
elif stage == 'helper':
    bind([mac / 'tests/test_import_helper.py', mac / 'ImportHelper/helper.py', mac / 'ImportHelper/calendar_evidence.py',
          mac / 'tools/project_import_helper.py', repo / 'magnolie-organizer/pruefungen/fixtures/caldav-series-resource.ics',
          repo / 'magnolie-organizer/bin/magnolie-organizer', repo / 'magnolie-organizer/bin/magnolie_or6.py'])
    prepare_import_dependency()
    run('legacy-sidecar-helper', [sys.executable, str(mac / 'tests/test_import_helper.py'),
         'ImportHelperTests.test_legacy_android_sidecar_is_exact_and_transient', '-v'])
else:
    raise SystemExit('Unknown stage')

for path, expected in record['source_files'].items():
    assert sha(repo / path) == expected, 'Product/test source changed: ' + path
record['source_inputs_unchanged_after_run'] = True
save()
print(stage, 'complete', flush=True)
