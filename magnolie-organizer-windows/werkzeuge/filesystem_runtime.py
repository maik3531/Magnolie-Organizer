#!/usr/bin/env python3
"""Package pinned, unmodified WinFsp/SSHFS-Win setup prerequisites using the existing build cache/downloader."""
import argparse
import json
from pathlib import Path
import shutil

from account_runtime import cached_download


def prepare(output, cache):
    source = Path(__file__).resolve().parents[1] / 'app/filesystem-runtime.json'
    metadata = json.loads(source.read_text(encoding='utf-8'))
    if metadata.get('schema') != 1 or len(metadata.get('packages', [])) != 2:
        raise ValueError('Unexpected filesystem prerequisite metadata')
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    for package in metadata['packages']:
        filename = package['filename']
        if Path(filename).name != filename or not filename.endswith('.msi'):
            raise ValueError('Unexpected prerequisite filename')
        shutil.copyfile(cached_download(package, cache), output / filename)
    (output / 'MAGNOLIE-NOTICES.txt').write_text(
        'Optional Windows phone-filesystem prerequisites, redistributed unmodified.\n'
        'WinFsp 2.1.25156: GPL-3.0 with FLOSS exception.\n'
        'Source/license: https://github.com/winfsp/winfsp/tree/v2.1\n'
        'SSHFS-Win 3.5.20357: GPL-2.0-or-later; Cygwin LGPL-3.0, GLib LGPL-2.0.\n'
        'Source/licenses: https://github.com/winfsp/sshfs-win/tree/v3.5.20357\n'
        'https://github.com/winfsp/sshfs-win/blob/v3.5.20357/License.txt\n'
        'Installing the shared Windows driver/client requires administrator permission.\n'
        'Magnolie never removes these shared prerequisites on application uninstall.\n', encoding='utf-8')
    (output / 'Telefon-Dateisystem vorbereiten.cmd').write_text(
        '@echo off\n'
        'set "MAGNOLIE_FS_EXE=%~dp0..\\Magnolie Organizer.exe"\n'
        'powershell.exe -NoProfile -NonInteractive -Command "$p=Start-Process -FilePath $env:MAGNOLIE_FS_EXE -ArgumentList \'--prepare-phone-filesystem\' -Verb RunAs -Wait -PassThru; exit $p.ExitCode"\n'
        'exit /b %ERRORLEVEL%\n', encoding='utf-8', newline='\r\n')
    print('Prepared pinned optional filesystem prerequisites: ' + str(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cache', type=Path, default=Path.home() / '.local/share/magnolie-release-tools/filesystem-runtime')
    options = parser.parse_args()
    prepare(options.output.resolve(), options.cache.resolve())
