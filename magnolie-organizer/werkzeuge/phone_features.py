#!/usr/bin/env python3
"""Compose optional desktop phone payloads inside an existing package stage."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
from magnolie_optional_phone import FEATURES, composition, selected_modules


def private_runtime(bindir, data_directory, source, names):
    """Only canonical staged program files move; never account/profile data."""
    runtime = data_directory / 'python'
    if runtime.is_symlink() or runtime.exists() and not runtime.is_dir():
        raise ValueError('invalid private program directory')
    wrapper = (ROOT / 'werkzeuge/program_wrapper.py').read_bytes()
    runtime.mkdir(exist_ok=True)
    for name in sorted(names | {'magnolie-organizer'}):
        original = (source / name).read_bytes(); staged = bindir / name; private = runtime / name
        if private.is_symlink() or private.exists() and (not private.is_file() or private.read_bytes() != original):
            raise ValueError('unfamiliar private program file')
        if staged.is_symlink(): raise ValueError('unfamiliar public program file')
        if staged.exists():
            if not staged.is_file() or staged.read_bytes() not in ((original, wrapper) if name == 'magnolie-organizer' else (original,)):
                raise ValueError('unfamiliar public program file')
            if name == 'magnolie-organizer' and staged.read_bytes() == wrapper and not private.exists():
                raise ValueError('missing private program entry')
        elif not private.exists(): raise ValueError('missing staged program file')
    for name in sorted(names | {'magnolie-organizer'}):
        staged = bindir / name; private = runtime / name
        if staged.exists() and (name != 'magnolie-organizer' or staged.read_bytes() != wrapper):
            if not private.exists(): os.link(staged, private, follow_symlinks=False)
            staged.unlink()
    entry = bindir / 'magnolie-organizer'
    if not entry.exists():
        fd = os.open(entry, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o755)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(wrapper); stream.flush(); os.fsync(stream.fileno())
    entry.chmod(0o755)
    return runtime


def stage(bindir, data_directory, *, selection=None, source=ROOT / 'bin'):
    bindir = Path(bindir); data_directory = Path(data_directory); source = Path(source)
    if bindir.resolve() == source.resolve() or data_directory.resolve() == source.resolve().parent:
        raise ValueError('cannot compose a canonical source tree')
    if bindir.is_symlink() or data_directory.is_symlink() or not bindir.is_dir() or not data_directory.is_dir():
        raise ValueError('invalid desktop package stage')
    config_path = data_directory / 'build-config.json'
    if config_path.is_symlink(): raise ValueError('invalid desktop build composition')
    if config_path.exists() and (not config_path.is_file() or config_path.stat().st_size > 65536):
        raise ValueError('invalid desktop build composition')
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    composition(config) # Reject invalid existing configuration before modifying payloads.
    if selection is not None:
        if type(selection) is not dict or not set(selection) <= FEATURES:
            raise ValueError('invalid desktop build composition')
        config = dict(config, phoneFeatures=selection)
    selected = composition(config)
    modules = {path.name for path in source.glob('*.py')}
    base = selected_modules(modules, {name: False for name in FEATURES})
    optional = modules - base
    wanted = selected_modules(modules, selected)
    runtime = data_directory / 'python'
    if runtime.is_symlink() or runtime.exists() and not runtime.is_dir():
        raise ValueError('invalid private program directory')
    # Stage only exact canonical bytes; unfamiliar files are never overwritten or deleted.
    for name in sorted(optional):
        original = source / name
        if original.is_symlink() or not original.is_file(): raise ValueError('invalid optional source module')
        for target in (bindir / name, runtime / name):
            if target.is_symlink() or target.exists() and (not target.is_file() or target.read_bytes() != original.read_bytes()):
                raise ValueError('unfamiliar optional payload')
    for directory in (bindir, runtime):
        if (directory / '__pycache__').exists() or (directory / '__pycache__').is_symlink():
            raise ValueError('stale compiled package payload')
    for name in sorted(optional):
        target = bindir / name
        if name in wanted:
            if not target.exists() and not (runtime / name).exists():
                shutil.copyfile(source / name, target); target.chmod(0o644)
        else:
            for old in (target, runtime / name):
                if old.exists(): old.unlink()
    private_runtime(bindir, data_directory, source, wanted)
    config = dict(config, phoneFeatures=selected)
    fd, temporary = tempfile.mkstemp(prefix='.phone-composition-', dir=data_directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(config, stream, sort_keys=True, separators=(',', ':')); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno()); os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return selected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bindir', type=Path); parser.add_argument('data_directory', type=Path)
    args = parser.parse_args()
    raw = os.environ.get('MAGNOLIE_PHONE_FEATURES')
    stage(args.bindir, args.data_directory, selection=json.loads(raw) if raw is not None else None)
