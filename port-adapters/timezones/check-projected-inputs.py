#!/usr/bin/env python3
"""Exercise both real projectors against current and exactly published desktop trees.

All generation and host-test writes stay in disposable copies. No repository
source restore, SourceFreeze rewrite, native build or native acceptance occurs.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
PUBLISHED = '067c38934b539943d8e1720abafd8a80b401d797'
DESKTOP = ['magnolie-organizer', 'magnolie-organizer-windows', 'magnolie-handbuch',
           'magnolie-notes', 'contracts', 'LICENSE.md', 'PROTECTED-ASSETS-LICENSE.txt']
PORTS = ['Magnolie-Organizer-Android-Tablet-Beta', 'Magnolie-Organizer-macOS-Beta', 'port-adapters']
# Overlay only this checkpoint's runtime transformation sources onto committed
# ports. Unrelated in-flight native codec edits cannot enter this host proof.
OVERLAYS = ['port-adapters/timezones/projection-patches.json',
            'port-adapters/timezones/projection-patches.cjs',
            'Magnolie-Organizer-macOS-Beta/tools/project_ui.py']

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
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node is required for actual projector/UI host checks')
    if not env.get('MACOS_BETA_JSDOM'):
        raise RuntimeError('Set MACOS_BETA_JSDOM to an existing jsdom/lib/api.js; skipped Mac UI checks are not evidence')
    head = run(['git', 'rev-parse', 'HEAD'], REPO, env).strip()
    overlays = {name: (REPO / name).read_bytes() for name in OVERLAYS}
    results = []
    with tempfile.TemporaryDirectory(prefix='magnolie-both-timezone-inputs-') as temporary:
        base = Path(temporary)
        for label, desktop_ref in [('current', head), ('published-v2.0.30', PUBLISHED)]:
            tree = base / label
            tree.mkdir()
            archive(head, PORTS, tree, env)
            archive(desktop_ref, DESKTOP, tree, env)
            for name, data in overlays.items():
                (tree / name).write_bytes(data)
            # Match native CI's canonical gettext preparation rather than
            # copying ignored catalogs from the developer's current workspace.
            linux = tree / 'magnolie-organizer'
            (linux / 'web/i18n').mkdir(exist_ok=True)
            for language in (linux / 'po/LINGUAS').read_text().split():
                run(['python3', '-B', 'werkzeuge/po_zu_js.py', language,
                     'po/' + language + '.po', 'web/i18n/' + language + '.js'], linux, env)
            tablet = tree / PORTS[0]
            mac = tree / PORTS[1]
            run([node, str(tablet / 'tools/project-web.cjs')], tree, env)
            for name in ['web.test.cjs', 'reminders.test.cjs', 'timezone-interop.test.cjs']:
                run([node, str(tablet / 'tests' / name)], tree, env)
            run([node, str(tree / 'port-adapters/timezones/app-hook-host.test.cjs')], tree, env)
            run([node, str(tree / 'port-adapters/timezones/port-runtime.test.cjs'), '--projection'], tree, env)
            output = run(['python3', '-B', str(mac / 'tests/test_host.py')], tree, env)
            if 'skipped=' in output:
                raise RuntimeError('Mac host gates skipped checks: ' + output[-2000:])
            run([node, str(tablet / 'tools/project-web.cjs'), '--check'], tree, env)
            source = (tree / 'magnolie-organizer/web/anwendung.js').read_bytes()
            results.append(dict(desktop=label, desktopCommit=desktop_ref,
                canonicalSHA256=hashlib.sha256(source).hexdigest(), androidWeb=True,
                androidReminders=True, actualApp148=True, isolatedNodeWorker=True,
                projectorPatchByteIdentity=True, macHost23=True, nativeAcceptance=False))
            print(json.dumps(results[-1]), flush=True)
    assert overlays == {name: (REPO / name).read_bytes() for name in OVERLAYS}, 'Transformation source changed during proof'
    print(json.dumps(dict(portCommit=head, publishedCommit=PUBLISHED, cases=results, nativeAcceptance=False)))

if __name__ == '__main__':
    main()
