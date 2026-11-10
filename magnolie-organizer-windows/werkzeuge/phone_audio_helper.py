#!/usr/bin/env python3
"""Build the exact own x64 setup helper with installed MSVC/SDK; never install it."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess


SOURCES = (
    'native/phone-camera/PhoneCameraCablePackage.h',
    'native/phone-camera/PhoneCameraCablePackage.cpp',
    'native/phone-camera/PhoneCameraCableSetup.h',
    'native/phone-camera/PhoneCameraCableSetup.cpp',
    'native/phone-camera/PhoneCameraCableSetupMain.cpp',
    'werkzeuge/phone_audio_helper.py',
    'PhoneCameraAudioHelper.targets',
)
NAME = 'Magnolie.PhoneAudioSetup.x64.exe'


def build(output):
    if os.name != 'nt':
        raise RuntimeError('Use the existing Windows MSVC/SDK environment, not a substitute compiler')
    root = Path(__file__).resolve().parents[1]
    before = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([
        str(vswhere), '-latest', '-products', 'Microsoft.VisualStudio.Product.BuildTools',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
        'Microsoft.VisualStudio.Component.Windows11SDK.26100', '-property', 'installationPath',
    ], text=True, timeout=30).strip()
    if not vs or '\n' in vs:
        raise RuntimeError('The supported installed MSVC/Windows SDK was not found')
    vcvars = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
    if not vcvars.is_file() or any(c in str(vcvars) for c in '\r\n"%'):
        raise RuntimeError('Invalid registered MSVC environment')
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'phone-audio-helper.manifest'
    # An old success descriptor must not survive a failed rebuild.
    if manifest.exists():
        manifest.unlink()
    arguments = ['/nologo', '/std:c++17', '/W4', '/WX', '/EHsc', '/MT', '/utf-8',
                 '/Brepro', '/guard:cf', '/DUNICODE', '/D_UNICODE', '/DWIN32_LEAN_AND_MEAN',
                 '/DNOMINMAX', '/D_WIN32_WINNT=0x0A00', '/Fe' + NAME]
    for name in SOURCES:
        if name.endswith('.cpp'):
            source = str(root / name)
            if any(c in source for c in '\r\n"'):
                raise RuntimeError('Unsupported source path')
            arguments.append('"' + source + '"')
    arguments += ['/link', '/WX', '/DYNAMICBASE', '/NXCOMPAT', '/guard:cf', '/MACHINE:X64',
                  'bcrypt.lib', 'wintrust.lib', 'crypt32.lib', 'ole32.lib', 'setupapi.lib',
                  'newdev.lib', 'cfgmgr32.lib', 'advapi32.lib', 'shell32.lib', 'uuid.lib']
    (output / 'phone-audio-helper.rsp').write_text('\n'.join(arguments) + '\n', encoding='utf-8')
    (output / 'phone-audio-helper-build.cmd').write_text(
        '@echo off\ncall "' + str(vcvars) + '"\nif errorlevel 1 exit /b %errorlevel%\n'
        'cl.exe @phone-audio-helper.rsp\nexit /b %errorlevel%\n', encoding='utf-8', newline='\r\n')
    with (output / 'phone-audio-helper-build.log').open('w', encoding='utf-8') as log:
        subprocess.run([os.environ.get('ComSpec', 'cmd.exe'), '/d', '/c', 'phone-audio-helper-build.cmd'],
                       cwd=output, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest for name, digest in before.items()):
        raise RuntimeError('Helper sources changed during compilation')
    binary = (output / NAME).read_bytes()
    pe = int.from_bytes(binary[0x3c:0x40], 'little')
    if binary[:2] != b'MZ' or binary[pe:pe + 6] != b'PE\0\0\x64\x86':
        raise RuntimeError('The compiled helper is not a native x64 PE')
    lines = ['magnolie-phone-audio-helper-v1', 'architecture=x64',
             'sha256=' + hashlib.sha256(binary).hexdigest()]
    lines += ['source=' + name + '|' + before[name] for name in SOURCES]
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Built source-bound helper; no execution, elevation or installation: ' + str(output / NAME))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    build(options.output.resolve())
