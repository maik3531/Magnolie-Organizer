"""Bundle the canonical handbook with the Organizer's existing GTK/WebKit runtime."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


def bundle(appdir, source, version):
    appdir, source = Path(appdir), Path(source)
    if json.loads((source / 'web/version.json').read_text())['version'] != version:
        raise ValueError('Handbook and Organizer versions differ')
    private = appdir / 'usr/lib/magnolie-handbuch'
    web = appdir / 'usr/share/magnolie-handbuch/web'
    private.mkdir(parents=True, exist_ok=True)
    web.parent.mkdir(parents=True, exist_ok=True)
    for name in ('magnolie-handbuch', 'magnolie_asset.py', 'magnolie_crash.py'):
        path = source / 'bin' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing canonical handbook module')
        shutil.copy2(path, private / name)
    for path in (source / 'web').rglob('*'):
        if path.is_symlink():
            raise ValueError('Handbook assets must not be symlinks')
    shutil.copytree(source / 'web', web, dirs_exist_ok=True)
    (web / 'i18n').mkdir(exist_ok=True)
    subprocess.run([sys.executable, str(source / 'werkzeuge/po_zu_js.py'), 'en',
                    str(source / 'po/english/protected.po'), str(web / 'i18n/en.js')], check=True)
    for language in (source / 'po/LINGUAS').read_text().split():
        catalog = source / 'po' / (language + '.po')
        destination = appdir / 'usr/share/locale' / language / 'LC_MESSAGES/magnolie-handbuch.mo'
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['msgfmt', '--check', '--check-format', '-o', str(destination), str(catalog)], check=True)
        subprocess.run([sys.executable, str(source / 'werkzeuge/po_zu_js.py'), language,
                        str(catalog), str(web / 'i18n' / (language + '.js'))], check=True)
    docs = appdir / 'usr/share/doc/magnolie-handbuch'
    tools = web.parent / 'werkzeuge'
    tools.mkdir(exist_ok=True)
    for name in ('pot_erzeugen.py', 'handbook_data.js', 'mobile_downloads_erzeugen.py'):
        shutil.copy2(source / 'werkzeuge' / name, tools / name)
    docs.mkdir(parents=True, exist_ok=True)
    for origin, name in ((source / 'debian/copyright', 'copyright'),
                         (source / 'PROTECTED-ASSETS-LICENSE.txt', 'PROTECTED-ASSETS-LICENSE.txt')):
        shutil.copy2(origin, docs / name)
    icon = appdir / 'usr/share/icons/hicolor/256x256/apps/magnolie-handbuch.png'
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'symbole/256x256/magnolie-handbuch.png', icon)
    launcher = appdir / 'usr/bin/magnolie-handbuch'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('''#!/bin/sh
set -eu
if [ -n "${APPIMAGE:-}" ] && [ -x "$APPIMAGE" ]; then
    exec "$APPIMAGE" --handbook "$@"
fi
APPDIR=${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}
exec "$APPDIR/AppRun" --handbook "$@"
''')
    launcher.chmod(0o755)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('appdir')
    parser.add_argument('source')
    parser.add_argument('version')
    args = parser.parse_args()
    bundle(args.appdir, args.source, args.version)
