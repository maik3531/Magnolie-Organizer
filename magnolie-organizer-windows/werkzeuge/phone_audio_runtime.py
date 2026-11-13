#!/usr/bin/env python3
"""Build only the source-bound worker with the existing installed Windows MSVC/SDK.

Does not execute, download, elevate or install. The setup-helper builder is separate
and deliberately unchanged. Supply this artifact only to the optional runtime target.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

SOURCES = tuple('native/phone-camera/' + name + suffix for name in (
    'PhoneCameraAudioWorker', 'PhoneCameraAudioRender', 'PhoneCameraClock', 'PhoneCameraSamples',
    'PhoneCameraPipe', 'PhoneCameraRelay', 'PhoneCameraOutputLease', 'PhoneCameraOutputPublisher',
    'PhoneCameraRuntimeProcess', 'PhoneCameraRuntimeStatus') for suffix in ('.h', '.cpp')) + (
    'native/phone-camera/PhoneCameraSource.h', 'werkzeuge/phone_audio_runtime.py', 'PhoneCameraAudioRuntime.targets')
NAME = 'Magnolie.PhoneAudioWorker.x64.exe'


def _response_file_text(arguments):
    if arguments.count('/link') != 1:
        raise ValueError('Exactly one linker delimiter is required')
    index = arguments.index('/link')
    # cl.exe forwards only the remainder of THIS response-file line to link.exe.
    return '\n'.join(arguments[:index] + [' '.join(arguments[index:])]) + '\n'


def build(output):
    if os.name != 'nt':
        raise RuntimeError('Use the existing Windows MSVC/SDK environment, not a substitute compiler')
    root = Path(__file__).resolve().parents[1]
    before = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere), '-latest', '-products', 'Microsoft.VisualStudio.Product.BuildTools',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', 'Microsoft.VisualStudio.Component.Windows11SDK.26100',
        '-property', 'installationPath'], text=True, timeout=30).strip()
    if not vs or '\n' in vs:
        raise RuntimeError('The supported installed MSVC/Windows SDK was not found')
    vcvars = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
    if not vcvars.is_file() or any(c in str(vcvars) for c in '\r\n"%'):
        raise RuntimeError('Invalid registered MSVC environment')
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'phone-audio-runtime.manifest'
    if manifest.exists():
        manifest.unlink()  # A stale own success descriptor must not survive a failed rebuild.
    arguments = ['/nologo', '/std:c++17', '/W4', '/WX', '/EHsc', '/MT', '/utf-8', '/Brepro', '/guard:cf',
        '/DUNICODE', '/D_UNICODE', '/DWIN32_LEAN_AND_MEAN', '/DNOMINMAX', '/D_WIN32_WINNT=0x0A00', '/Fe' + NAME]
    for name in SOURCES:
        if name.endswith('.cpp'):
            path = str(root / name)
            if any(c in path for c in '\r\n"'):
                raise RuntimeError('Unsupported source path')
            arguments.append('"' + path + '"')
    arguments += ['/link', '/WX', '/DYNAMICBASE', '/NXCOMPAT', '/guard:cf', '/MACHINE:X64',
        'mfplat.lib', 'mfuuid.lib', 'ole32.lib', 'setupapi.lib', 'cfgmgr32.lib', 'advapi32.lib', 'bcrypt.lib', 'uuid.lib']
    (output / 'phone-audio-runtime.rsp').write_text(_response_file_text(arguments), encoding='utf-8')
    (output / 'phone-audio-runtime-build.cmd').write_text('@echo off\ncall "' + str(vcvars) +
        '"\nif errorlevel 1 exit /b %errorlevel%\ncl.exe @phone-audio-runtime.rsp\nexit /b %errorlevel%\n', encoding='utf-8', newline='\r\n')
    with (output / 'phone-audio-runtime-build.log').open('w', encoding='utf-8') as log:
        subprocess.run([os.environ.get('ComSpec', 'cmd.exe'), '/d', '/c', 'phone-audio-runtime-build.cmd'],
            cwd=output, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != value for name, value in before.items()):
        raise RuntimeError('Runtime sources changed during compilation')
    binary = (output / NAME).read_bytes()
    if len(binary) < 128 or len(binary) > 8 * 1024 * 1024:
        raise RuntimeError('Invalid compiled runtime size')
    pe = int.from_bytes(binary[0x3c:0x40], 'little')
    if binary[:2] != b'MZ' or pe < 64 or pe > len(binary) - 26 or binary[pe:pe + 6] != b'PE\0\0\x64\x86' or int.from_bytes(binary[pe + 22:pe + 24], 'little') & 0x2000:
        raise RuntimeError('The compiled runtime is not a native x64 executable')
    lines = ['magnolie-phone-audio-runtime-v1', 'architecture=x64', 'sha256=' + hashlib.sha256(binary).hexdigest()]
    lines += ['source=' + name + '|' + before[name] for name in SOURCES]
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Built source-bound runtime; no execution, elevation or installation: ' + str(output / NAME))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output.resolve())
