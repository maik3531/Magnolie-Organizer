"""Source-bound user integration that survives removal of its AppImage (#163)."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def is_appimage(program):
    value = os.fspath(program)
    return os.path.isabs(value) and (value.lower().endswith('.appimage') or value == os.environ.get('APPIMAGE'))


def _roots():
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    if any(not path.is_absolute() or any(ord(c) < 32 for c in str(path)) for path in (config, data)):
        raise ValueError('invalid_appimage_integration_path')
    return config, data


def launcher(program):
    if not is_appimage(program):
        return os.fspath(program)
    _, data = _roots()
    identity = hashlib.sha256(os.fsencode(program)).hexdigest()[:24]
    return str(data / 'magnolie-organizer/appimage-launchers' / (identity + '.sh'))


def marker(program):
    return '# Magnolie-AppImage-Guard=' + launcher(program) + '\n' if is_appimage(program) else ''


def _write(path, value, mode):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_symlink() and path.is_file() and path.read_text() == value:
        path.chmod(mode)
        return
    fd, temporary = tempfile.mkstemp(prefix='.magnolie-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _run(arguments):
    try:
        return subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=15).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def ensure_installed(program, runner=None):
    """Install only portable integration; no profile or application data is changed."""
    if not is_appimage(program):
        return os.fspath(program)
    if any(ord(char) < 32 for char in os.fspath(program)):
        raise ValueError('invalid_appimage_path')
    config, _ = _roots()
    script = launcher(program)
    identity = Path(script).stem
    name = 'magnolie-appimage-' + identity
    units = config / 'systemd/user'
    own = marker(program).rstrip('\n')
    service_names = ['magnolie-erinnerung.service', name + '.service']
    timer_names = ['magnolie-erinnerung.timer', name + '.path']
    files = [units / value for value in timer_names + service_names]
    files.extend(config / 'autostart' / value for value in
                 ('magnolie-erinnerung.desktop', 'magnolie-organizer-tray.desktop',
                  'io.gitlab.maik3531.MagnolieOrganizer.Background.desktop'))
    # The shell is outside the disappearing image. Fixed names and exact binding
    # markers ensure an old image cannot remove a replacement's integrations.
    body = '#!/bin/sh\nset -u\n'
    body += 'program=' + shlex.quote(os.fspath(program)) + '\n'
    body += 'marker=' + shlex.quote(own) + '\n'
    body += 'owns() { [ ! -L "$1" ] && [ -f "$1" ] && grep -Fqx -- "$marker" "$1"; }\n'
    body += 'if [ -f "$program" ]; then\n'
    body += '  if [ "${1-}" = "--check" ]; then exit 0; fi\n'
    body += '  exec "$program" "$@"\nfi\n'
    for filename in timer_names:
        path = shlex.quote(str(units / filename))
        body += f'if owns {path}; then systemctl --user disable --now {shlex.quote(filename)} >/dev/null 2>&1 || :; fi\n'
    for filename in service_names:
        path = shlex.quote(str(units / filename))
        # Do not synchronously stop our own currently executing oneshot before
        # removing its files and clearing the stale manager definitions.
        body += f'if owns {path}; then systemctl --user disable {shlex.quote(filename)} >/dev/null 2>&1 || :; fi\n'
    body += 'services=""\n'
    for filename in service_names:
        body += f'if owns {shlex.quote(str(units / filename))}; then services="$services {filename}"; fi\n'
    for path in files:
        quoted = shlex.quote(str(path))
        body += f'if owns {quoted}; then rm -f -- {quoted}; fi\n'
    body += 'systemctl --user daemon-reload >/dev/null 2>&1 || :\n'
    body += 'for unit in $services; do systemctl --user reset-failed "$unit" >/dev/null 2>&1 || :; done\n'
    body += 'for unit in $services; do systemctl --user --no-block stop "$unit" >/dev/null 2>&1 || :; done\n'
    body += 'rm -f -- ' + shlex.quote(script) + '\nexit 0\n'
    _write(script, body, 0o700)
    # An inotify path unit catches deletion/moves while the application is open;
    # guarded reminder/autostart launches also clean up after a later login.
    escaped = lambda value: str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
    _write(units / (name + '.service'), own + '\n[Unit]\nDescription=Magnolie AppImage integration cleanup\n'
           '[Service]\nType=oneshot\nExecStart="' + escaped(script).replace('$', '$$') + '" --check\n', 0o600)
    _write(units / (name + '.path'), own + '\n[Unit]\nDescription=Magnolie AppImage presence\n'
           '[Path]\nPathChanged=' + escaped(program) + '\n'
           'Unit=' + name + '.service\n[Install]\nWantedBy=default.target\n', 0o600)
    if runner is not None or shutil.which('systemctl'):
        execute = runner or _run
        execute(['systemctl', '--user', 'daemon-reload'])
        execute(['systemctl', '--user', 'enable', '--now', name + '.path'])
    return script


def cleanup_legacy(runner=None, config=None):
    """Retire only the reported legacy reminder pair pointing to a missing image."""
    config = Path(config) if config else _roots()[0]
    units = config / 'systemd/user'
    service = units / 'magnolie-erinnerung.service'
    if service.is_symlink() or not service.is_file() or service.stat().st_size > 65536:
        return False
    text = service.read_text()
    lines = [line[len('ExecStart='):] for line in text.splitlines() if line.startswith('ExecStart=')]
    if len(lines) != 1 or 'Magnolie' not in text:
        return False
    try:
        command = shlex.split(lines[0])
    except ValueError:
        return False
    if len(command) != 2 or command[1] != '--erinnerung':
        return False
    program = command[0].replace('%%', '%').replace('$$', '$')
    if not is_appimage(program) or Path(program).exists():
        return False
    execute = runner or _run
    execute(['systemctl', '--user', 'disable', '--now', 'magnolie-erinnerung.timer', 'magnolie-erinnerung.service'])
    if service.read_text() != text:
        return False
    service.unlink()
    timer = units / 'magnolie-erinnerung.timer'
    if not timer.is_symlink() and timer.is_file() and '\nUnit=magnolie-erinnerung.service\n' in '\n' + timer.read_text() + '\n':
        timer.unlink()
    for filename in ('magnolie-erinnerung.desktop', 'magnolie-organizer-tray.desktop',
                     'io.gitlab.maik3531.MagnolieOrganizer.Background.desktop'):
        path = config / 'autostart' / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            continue
        contents = path.read_text()
        if any(line.startswith('Exec=') and program in line for line in contents.splitlines()):
            if path.read_text() == contents: path.unlink()
    execute(['systemctl', '--user', 'daemon-reload'])
    execute(['systemctl', '--user', 'reset-failed', 'magnolie-erinnerung.timer', 'magnolie-erinnerung.service'])
    return True
