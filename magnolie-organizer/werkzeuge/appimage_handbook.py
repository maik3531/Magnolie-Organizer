"""Bundle the canonical handbook with the Organizer's existing GTK/WebKit runtime."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile


PILLOW_VERSION = '12.3.0'
PILLOW_FILENAME = 'pillow-12.3.0-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
PILLOW_URL = ('https://files.pythonhosted.org/packages/4e/89/36f4cd76cf4baf05c50ababb976249153f18c959171c7f6ba09a6f217260/' + PILLOW_FILENAME)
PILLOW_SHA256 = 'f0606c8bf2cdefea14a43530f7657cbbb7ecf1c4222512492ef4a4434a9501ec'


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


def bundle_pillow(appdir, cache=None):
    """Keep the Jammy ABI and provide a supported Pillow for the PDF writer."""
    destination = Path(appdir) / 'usr/lib/python3/dist-packages'
    docs = Path(appdir) / 'usr/share/doc/magnolie-handbuch'
    destination.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    if sys.version_info[:2] == (3, 10):
        if cache is None or not Path(cache).is_dir():
            raise ValueError('The locked Pillow build cache is unavailable')
        wheel = Path(cache) / PILLOW_FILENAME
        if wheel.is_symlink():
            raise ValueError('Pillow cache must not be a symlink')
        if not wheel.exists():
            with urllib.request.urlopen(PILLOW_URL, timeout=90) as response:
                if not response.url.startswith('https://files.pythonhosted.org/'):
                    raise ValueError('Unexpected Pillow download host')
                data = response.read(16 * 1024 * 1024 + 1)
            if hashlib.sha256(data).hexdigest() != PILLOW_SHA256:
                raise ValueError('The downloaded Pillow wheel differs from its lock')
            with open(wheel, 'xb') as stream:
                stream.write(data)
        if wheel.stat().st_size > 16 * 1024 * 1024 or hashlib.sha256(wheel.read_bytes()).hexdigest() != PILLOW_SHA256:
            raise ValueError('The cached Pillow wheel differs from its lock')
        with zipfile.ZipFile(wheel) as archive:
            files = archive.infolist()
            if sum(item.file_size for item in files) > 64 * 1024 * 1024:
                raise ValueError('The extracted Pillow wheel exceeds the size limit')
            licenses = []
            for item in files:
                relative = PurePosixPath(item.filename)
                if (relative.is_absolute() or '..' in relative.parts or '\\' in item.filename or
                        not relative.parts or relative.parts[0] not in {'PIL', 'pillow.libs', 'pillow-12.3.0.dist-info'} or
                        stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError('Unsafe Pillow wheel entry')
                if item.is_dir():
                    continue
                output = destination.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(archive.read(item))
                output.chmod(0o644)
                if '.dist-info' in item.filename and 'license' in relative.name.lower():
                    licenses.append(item.filename)
            if not licenses or not (destination / 'PIL/_imaging.cpython-310-x86_64-linux-gnu.so').is_file():
                raise ValueError('Pillow ABI or original license files are missing')
        for top in ('PIL', 'pillow.libs', 'pillow-12.3.0.dist-info'):
            directory = destination / top
            if directory.is_dir():
                for child in (directory, *(entry for entry in directory.rglob('*') if entry.is_dir())):
                    child.chmod(0o755)
        (docs / 'pillow-runtime.json').write_text(json.dumps({'version': PILLOW_VERSION,
            'filename': PILLOW_FILENAME, 'sha256': PILLOW_SHA256, 'licenses': sorted(licenses)}, sort_keys=True) + '\n')
    else:
        import PIL
        version = re.match(r'^(\d+)\.(\d+)', PIL.__version__)
        if version is None or tuple(map(int, version.groups())) < (9, 1):
            raise ValueError('The handbook PDF runtime requires Pillow >= 9.1')
        package = Path(PIL.__file__).resolve().parent
        shutil.copytree(package, destination / 'PIL', dirs_exist_ok=True)
        if (package.parent / 'pillow.libs').is_dir():
            shutil.copytree(package.parent / 'pillow.libs', destination / 'pillow.libs', dirs_exist_ok=True)
        license_path = Path('/usr/share/doc/python3-pil/copyright')
        if not license_path.is_file():
            raise ValueError('The system Pillow copyright file is unavailable')
        shutil.copy2(license_path, docs / 'pillow-copyright')


def bundle(appdir, source, version, cache=None, runtime_source=None):
    appdir, source = Path(appdir), Path(source)
    if json.loads((source / 'web/version.json').read_text())['version'] != version:
        raise ValueError('Handbook and Organizer versions differ')
    private = appdir / 'usr/lib/magnolie-handbuch'
    web = appdir / 'usr/share/magnolie-handbuch/web'
    private.mkdir(parents=True, exist_ok=True)
    web.parent.mkdir(parents=True, exist_ok=True)
    for name in ('magnolie-handbuch', 'magnolie_asset.py', 'magnolie_crash.py',
                 'magnolie_print_pdf.py', 'magnolie_print_gtk.py', 'magnolie_print_process.py',
                 'magnolie_print_operation.py', 'magnolie_print_portal.py', 'pdf-runtime-lock.json'):
        path = source / 'bin' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing canonical handbook module')
        shutil.copy2(path, private / name)
    runtime = Path(runtime_source) if runtime_source is not None else source / 'bin/pdf-runtime'
    if runtime.is_symlink() or not (runtime / 'runtime-manifest.json').is_file():
        raise ValueError('The locked handbook PDF source runtime is missing')
    for path in runtime.rglob('*'):
        if path.is_symlink():
            raise ValueError('Handbook PDF runtime must not contain symlinks')
    spec = importlib.util.spec_from_file_location('handbook_pdf_dependency_verifier', source / 'bin/magnolie_print_pdf.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    verifier.verify_runtime(runtime)
    shutil.copytree(runtime, private / 'pdf-runtime', dirs_exist_ok=True)
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
    bundle_pillow(appdir, cache)
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
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--pdf-runtime', type=Path)
    args = parser.parse_args()
    bundle(args.appdir, args.source, args.version, args.cache, args.pdf_runtime)
