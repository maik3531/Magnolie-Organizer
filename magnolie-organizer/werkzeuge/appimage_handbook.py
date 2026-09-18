"""Bundle the canonical handbook with the Organizer's existing GTK/WebKit runtime."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


LAUNCHER = '''#!/usr/bin/env python3
import os
from pathlib import Path
import sys

appdir = Path(os.environ.get("APPDIR") or Path(__file__).resolve().parents[2])
image = os.environ.get("APPIMAGE", "")
target = image if os.path.isfile(image) and os.access(image, os.X_OK) else str(appdir / "AppRun")
environment = dict(os.environ)
# The host shell must not load the parent's bundled readline/GTK libraries.
# AppRun constructs a fresh environment for the independently mounted handbook.
for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "PYTHONTZPATH",
             "GI_TYPELIB_PATH", "GIO_MODULE_DIR", "GTK_PATH", "GTK_DATA_PREFIX",
             "GSETTINGS_SCHEMA_DIR", "FONTCONFIG_PATH", "FONTCONFIG_FILE",
             "OPENSSL_CONF", "OPENSSL_MODULES", "GST_PLUGIN_PATH_1_0",
             "GST_PLUGIN_SYSTEM_PATH_1_0", "GST_PLUGIN_SCANNER",
             "WEBKIT_EXEC_PATH", "WEBKIT_INJECTED_BUNDLE_PATH"):
    environment.pop(name, None)
prefix = str(appdir).rstrip("/")
for name in ("PATH", "XDG_DATA_DIRS"):
    if name in environment:
        parts = [part for part in environment[name].split(os.pathsep)
                 if part != prefix and not part.startswith(prefix + "/")]
        if any(parts):
            environment[name] = os.pathsep.join(parts)
        elif name == "PATH":
            environment[name] = os.defpath
        else:
            environment.pop(name, None)
if environment.get("SSL_CERT_FILE", "").startswith(prefix + "/"):
    environment.pop("SSL_CERT_FILE", None)
os.execve(target, [target, "--handbook", *sys.argv[1:]], environment)
'''


def write_launcher(path):
    path.write_text(LAUNCHER)
    path.chmod(0o755)


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
    write_launcher(launcher)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('appdir')
    parser.add_argument('source')
    parser.add_argument('version')
    args = parser.parse_args()
    bundle(args.appdir, args.source, args.version)
