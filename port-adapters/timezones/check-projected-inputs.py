#!/usr/bin/env python3
"""Exercise both real projectors against current and exactly published desktop trees.

All generation and host-test writes stay in disposable copies. No repository
source restore, SourceFreeze rewrite, native build or native acceptance occurs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
PUBLISHED = '067c38934b539943d8e1720abafd8a80b401d797'
DESKTOP = ['magnolie-organizer', 'magnolie-organizer-windows', 'magnolie-handbuch',
           'magnolie-notes', 'contracts', 'PROTECTED-ASSETS-LICENSE.txt']
PORTS = ['Magnolie-Organizer-Android-Tablet-Beta', 'Magnolie-Organizer-macOS-Beta', 'port-adapters']
# Overlay only this checkpoint's runtime transformation sources onto committed
# ports. Unrelated in-flight native codec edits cannot enter this host proof.
OVERLAYS = ['port-adapters/timezones/projection-patches.json',
             'port-adapters/timezones/projection-patches.cjs',
            'port-adapters/timezones/app-hooks.snippets',
            'port-adapters/timezones/promoted-hooks.test.cjs',
            'port-adapters/timezones/app-hook-host.test.cjs',
            'Magnolie-Organizer-Android-Tablet-Beta/tools/project-web.cjs',
            'Magnolie-Organizer-macOS-Beta/tools/project_ui.py']
CANONICAL_UI = ['magnolie-organizer/web/anwendung.js', 'magnolie-organizer/web/index.html',
                'magnolie-organizer-windows/app/web/anwendung.js', 'magnolie-organizer-windows/app/web/index.html']

def run(argv, cwd, env, log=None):
    result = subprocess.run(argv, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    if log:
        log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError('Host check failed: ' + ' '.join(argv) + '\n' + result.stdout[-12000:])
    return result.stdout

def archive(ref, paths, destination, env):
    # Trusted git tree paths only; tar receives an archive emitted by git itself.
    with tempfile.TemporaryFile() as stream:
        subprocess.run(['git', 'archive', ref, *paths], cwd=REPO, env=env, stdout=stream, check=True)
        stream.seek(0)
        subprocess.run(['tar', '-xf', '-', '-C', str(destination)], stdin=stream, check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-canonical', action='store_true',
                        help='Overlay the four current canonical UI files only in the current-input case')
    parser.add_argument('--evidence-directory', type=Path,
                        help='New directory for individual host-check logs; existing directories are refused')
    args = parser.parse_args()
    if args.evidence_directory:
        args.evidence_directory.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node is required for actual projector/UI host checks')
    if not env.get('MACOS_BETA_JSDOM'):
        raise RuntimeError('Set MACOS_BETA_JSDOM to an existing jsdom/lib/api.js; skipped Mac UI checks are not evidence')
    head = run(['git', 'rev-parse', 'HEAD'], REPO, env).strip()
    git_dir = run(['git', 'rev-parse', '--absolute-git-dir'], REPO, env).strip()
    overlays = {name: (REPO / name).read_bytes() for name in OVERLAYS}
    canonical = {name: (REPO / name).read_bytes() for name in CANONICAL_UI} if args.working_canonical else {}
    results = []
    with tempfile.TemporaryDirectory(prefix='magnolie-both-timezone-inputs-') as temporary:
        base = Path(temporary)
        for label, desktop_ref in [('current', head), ('published-v2.0.30', PUBLISHED)]:
            tree = base / label
            tree.mkdir()
            archive(head, PORTS, tree, env)
            # Published desktop trees still use the old notice filename.
            names = run(['git', 'ls-tree', '--name-only', desktop_ref], REPO, env).splitlines()
            notices = [name for name in ('LICENSE.md', 'LICENSING.md', 'LICENSE') if name in names]
            archive(desktop_ref, DESKTOP + notices, tree, env)
            for name, data in overlays.items():
                (tree / name).write_bytes(data)
            if label == 'current':
                for name, data in canonical.items():
                    (tree / name).write_bytes(data)
            # Historical-oracle tests need read-only access to the real Git
            # object history; disposable source archives contain no .git tree.
            case_env = dict(env, GIT_DIR=git_dir, GIT_WORK_TREE=str(tree))
            def check(argv, name):
                log = args.evidence_directory / (label + '-' + name + '.log') if args.evidence_directory else None
                return run(argv, tree, case_env, log)
            # Match native CI's canonical gettext preparation rather than
            # copying ignored catalogs from the developer's current workspace.
            linux = tree / 'magnolie-organizer'
            (linux / 'web/i18n').mkdir(exist_ok=True)
            for language in (linux / 'po/LINGUAS').read_text().split():
                run(['python3', '-B', 'werkzeuge/po_zu_js.py', language,
                     'po/' + language + '.po', 'web/i18n/' + language + '.js'], linux, env)
            generator = linux / 'werkzeuge/zeitzonen_erzeugen.py'
            if generator.is_file():
                check(['python3', '-I', '-B', str(generator)], 'canonical-timezones-linux')
                check(['python3', '-I', '-B', str(generator), '--output',
                       str(tree / 'magnolie-organizer-windows/app/web')], 'canonical-timezones-windows')
            elif b'/*TZ_PORT:' in (linux / 'web/anwendung.js').read_bytes():
                raise RuntimeError('Promoted canonical source lacks its portable timezone recipe')
            tablet = tree / PORTS[0]
            mac = tree / PORTS[1]
            check([node, str(tablet / 'tools/project-web.cjs')], 'tablet-project')
            for name in ['web.test.cjs', 'reminders.test.cjs', 'timezone-interop.test.cjs']:
                check([node, str(tablet / 'tests' / name)], name)
            check([node, str(tree / 'port-adapters/timezones/app-hook-host.test.cjs')], 'app-hook-host')
            check([node, str(tree / 'port-adapters/timezones/port-runtime.test.cjs'), '--projection'], 'port-runtime')
            output = check(['python3', '-B', str(mac / 'tests/test_host.py')], 'mac-host')
            if 'skipped=' in output:
                raise RuntimeError('Mac host gates skipped checks: ' + output[-2000:])
            mac_tests = re.search(r'Ran (\d+) tests?', output)
            if not mac_tests:
                raise RuntimeError('Mac host test count is missing')
            check([node, str(tablet / 'tools/project-web.cjs'), '--check'], 'tablet-final-check')
            source = (tree / 'magnolie-organizer/web/anwendung.js').read_bytes()
            results.append(dict(desktop=label, desktopCommit=desktop_ref,
                workingCanonicalOverlay=bool(canonical) and label == 'current',
                canonicalSHA256=hashlib.sha256(source).hexdigest(), androidWeb=True,
                androidReminders=True, actualApp148=True, isolatedNodeWorker=True,
                projectorPatchByteIdentity=True, macHostTests=int(mac_tests.group(1)), nativeAcceptance=False))
            print(json.dumps(results[-1]), flush=True)
    assert overlays == {name: (REPO / name).read_bytes() for name in OVERLAYS}, 'Transformation source changed during proof'
    assert canonical == ({name: (REPO / name).read_bytes() for name in CANONICAL_UI} if args.working_canonical else {}), 'Canonical UI changed during proof'
    print(json.dumps(dict(portCommit=head, publishedCommit=PUBLISHED, cases=results, nativeAcceptance=False)))

if __name__ == '__main__':
    main()
