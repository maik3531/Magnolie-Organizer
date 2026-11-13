#!/usr/bin/env python3
"""Build the source-bound camera DLL with the existing Windows MSVC/SDK.

Uses the same toolchain/flags as the audio artifacts. Never loads, registers,
installs or signs the result; this is not a FrameServer/AV acceptance run.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

SOURCES = tuple('native/phone-camera/' + name + suffix for name in (
    'PhoneCameraSamples', 'PhoneCameraClock', 'PhoneCameraSource', 'PhoneCameraActivate',
    'PhoneCameraFactory', 'PhoneCameraDormantSource', 'PhoneCameraModule', 'PhoneCameraPipe', 'PhoneCameraOutputLease',
    'PhoneCameraFrameServerPeer', 'PhoneCameraBrokerProtocol', 'PhoneCameraBrokerChannel', 'PhoneCameraSourceBroker')
    for suffix in ('.h', '.cpp')) + ('native/phone-camera/PhoneCameraModule.def',
        'werkzeuge/phone_camera_source.py', 'PhoneCameraSource.targets')
NAME = 'Magnolie.PhoneCameraSource.x64.dll'
CLASS_ID = 'dab1e726-131a-4a3a-abea-6a8ca1b4f571'


def _response_file_text(arguments):
    if arguments.count('/link') != 1:
        raise ValueError('Exactly one linker delimiter is required')
    index = arguments.index('/link')
    # cl.exe forwards only the remainder of THIS response-file line to link.exe.
    return '\n'.join(arguments[:index] + [' '.join(arguments[index:])]) + '\n'


def build(output):
    if os.name != 'nt':
        raise RuntimeError('Use the existing Windows MSVC/SDK environment')
    root = Path(__file__).resolve().parents[1]
    before = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere), '-latest', '-products', 'Microsoft.VisualStudio.Product.BuildTools',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', 'Microsoft.VisualStudio.Component.Windows11SDK.26100',
        '-property', 'installationPath'], text=True, timeout=30).strip()
    if not vs or '\n' in vs:
        raise RuntimeError('Supported installed MSVC/Windows SDK not found')
    vcvars = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
    if not vcvars.is_file() or any(c in str(vcvars) for c in '\r\n"%'):
        raise RuntimeError('Invalid registered MSVC environment')
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'phone-camera-source.manifest'
    if manifest.exists():
        manifest.unlink()  # Only this builder's stale success descriptor.
    arguments = ['/nologo', '/std:c++17', '/W4', '/WX', '/EHsc', '/MT', '/utf-8', '/Brepro', '/guard:cf', '/LD',
        '/DUNICODE', '/D_UNICODE', '/DWIN32_LEAN_AND_MEAN', '/DNOMINMAX', '/D_WIN32_WINNT=0x0A00', '/Fe' + NAME]
    for name in SOURCES:
        if name.endswith('.cpp'):
            path = str(root / name)
            if any(c in path for c in '\r\n"'):
                raise RuntimeError('Unsupported source path')
            arguments.append('"' + path + '"')
    arguments += ['/link', '/WX', '/DYNAMICBASE', '/NXCOMPAT', '/guard:cf', '/MACHINE:X64',
        '/DEF:"' + str(root / 'native/phone-camera/PhoneCameraModule.def') + '"',
        'mfplat.lib', 'mfuuid.lib', 'ole32.lib', 'mfreadwrite.lib', 'advapi32.lib', 'bcrypt.lib']
    (output / 'phone-camera-source.rsp').write_text(_response_file_text(arguments), encoding='utf-8')
    (output / 'phone-camera-source-build.cmd').write_text('@echo off\ncall "' + str(vcvars) +
        '"\nif errorlevel 1 exit /b %errorlevel%\ncl.exe @phone-camera-source.rsp\nexit /b %errorlevel%\n',
        encoding='utf-8', newline='\r\n')
    with (output / 'phone-camera-source-build.log').open('w', encoding='utf-8') as log:
        subprocess.run([os.environ.get('ComSpec', 'cmd.exe'), '/d', '/c', 'phone-camera-source-build.cmd'],
            cwd=output, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest for name, digest in before.items()):
        raise RuntimeError('Source inputs changed during compilation')
    binary = (output / NAME).read_bytes()
    if not 128 <= len(binary) <= 8 * 1024 * 1024:
        raise RuntimeError('Invalid compiled source size')
    pe = int.from_bytes(binary[60:64], 'little')
    if (binary[:2] != b'MZ' or pe < 64 or pe > len(binary) - 96 or
            binary[pe:pe + 6] != b'PE\0\0\x64\x86' or
            int.from_bytes(binary[pe + 22:pe + 24], 'little') & 0x2002 != 0x2002 or
            binary[pe + 24:pe + 26] != b'\x0b\x02' or
            int.from_bytes(binary[pe + 94:pe + 96], 'little') & 0x4140 != 0x4140):
        raise RuntimeError('Source must be an x64 PE32+ DLL with ASLR/NX/CFG')
    lines = ['magnolie-phone-camera-source-v1', 'architecture=x64', 'classId=' + CLASS_ID,
             'sha256=' + hashlib.sha256(binary).hexdigest()]
    lines += ['source=' + name + '|' + before[name] for name in SOURCES]
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Built source-bound camera DLL without loading/registration: ' + str(output / NAME))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    build(parser.parse_args().output.resolve())
