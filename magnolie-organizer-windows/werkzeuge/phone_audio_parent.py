#!/usr/bin/env python3
"""Source-bound parent DLL build using the existing installed Windows MSVC/SDK.

No loading, execution, download, elevation or installation. Worker/setup builders
and their immutable inputs remain separate and unchanged.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

SOURCES = tuple('native/phone-camera/' + name + suffix for name in (
    'PhoneCameraAudioParent', 'PhoneCameraClock', 'PhoneCameraPipe', 'PhoneCameraOutputLease',
    'PhoneCameraOutputPublisher', 'PhoneCameraRuntimeProcess', 'PhoneCameraRuntimeStatus', 'PhoneCameraVirtualCamera',
    'PhoneCameraBrokerProtocol', 'PhoneCameraBrokerChannel', 'PhoneCameraFrameServerPeer', 'PhoneCameraSourceBrokerParent', 'PhoneCameraVideoParent')
    for suffix in ('.h', '.cpp')) + ('native/phone-camera/PhoneCameraSamples.h', 'native/phone-camera/PhoneCameraModule.h',
        'werkzeuge/phone_audio_parent.py', 'PhoneCameraAudioParent.targets')
NAME = 'Magnolie.PhoneAudioParent.x64.dll'


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
    manifest = output / 'phone-audio-parent.manifest'
    if manifest.exists():
        manifest.unlink()  # Remove only this builder's stale success descriptor.
    arguments = ['/nologo', '/std:c++17', '/W4', '/WX', '/EHsc', '/MT', '/utf-8', '/Brepro', '/guard:cf', '/LD',
        '/DUNICODE', '/D_UNICODE', '/DWIN32_LEAN_AND_MEAN', '/DNOMINMAX', '/D_WIN32_WINNT=0x0A00',
        '/DMAGNOLIE_PHONE_AUDIO_PARENT_EXPORTS', '/Fe' + NAME]
    for name in SOURCES:
        if name.endswith('.cpp'):
            path = str(root / name)
            if any(c in path for c in '\r\n"'):
                raise RuntimeError('Unsupported source path')
            arguments.append('"' + path + '"')
    arguments += ['/link', '/WX', '/DYNAMICBASE', '/NXCOMPAT', '/guard:cf', '/MACHINE:X64',
        'mfplat.lib', 'mfuuid.lib', 'ole32.lib', 'advapi32.lib', 'bcrypt.lib', 'uuid.lib']
    (output / 'phone-audio-parent.rsp').write_text(_response_file_text(arguments), encoding='utf-8')
    (output / 'phone-audio-parent-build.cmd').write_text('@echo off\ncall "' + str(vcvars) +
        '"\nif errorlevel 1 exit /b %errorlevel%\ncl.exe @phone-audio-parent.rsp\nexit /b %errorlevel%\n', encoding='utf-8', newline='\r\n')
    with (output / 'phone-audio-parent-build.log').open('w', encoding='utf-8') as log:
        subprocess.run([os.environ.get('ComSpec', 'cmd.exe'), '/d', '/c', 'phone-audio-parent-build.cmd'],
            cwd=output, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != value for name, value in before.items()):
        raise RuntimeError('Parent sources changed during compilation')
    binary = (output / NAME).read_bytes()
    if not 128 <= len(binary) <= 8 * 1024 * 1024:
        raise RuntimeError('Invalid compiled parent size')
    pe = int.from_bytes(binary[60:64], 'little')
    if (binary[:2] != b'MZ' or pe < 64 or pe > len(binary) - 26 or
            binary[pe:pe + 6] != b'PE\0\0\x64\x86' or
            int.from_bytes(binary[pe + 22:pe + 24], 'little') & 0x2002 != 0x2002 or
            binary[pe + 24:pe + 26] != b'\x0b\x02'):
        raise RuntimeError('Compiled parent must be an x64 PE32+ DLL')
    lines = ['magnolie-phone-audio-parent-v1', 'architecture=x64', 'sha256=' + hashlib.sha256(binary).hexdigest()]
    lines += ['source=' + name + '|' + before[name] for name in SOURCES]
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Built source-bound parent DLL without loading/execution: ' + str(output / NAME))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output.resolve())
