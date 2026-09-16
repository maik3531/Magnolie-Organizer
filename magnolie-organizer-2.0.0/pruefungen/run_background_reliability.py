#!/usr/bin/env python3
"""Isolated functional test runner; never connects to the user's services."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS = [
    'test_background_reliability.py', 'test_baum_receipts.py',
    'test_hintergrunddienst.py', 'test_phone_setup_sessions.py',
    'test_automatic_cloud_backup.py', 'test_journal_periodisch.py',
    'test_wiederherstellungsjournal.py', 'test_setup_services.py',
    'test_naechster_weckzeitpunkt.py', 'test_phone_bluetooth_setup.py',
    'test_phone_invitation.py', 'test_telefon.py', 'test_native_sync_safety.py',
    'test_nextcloud.py',
]


def main():
    arguments = sys.argv[1:]
    cross = '--cross-windows' in arguments
    arguments = [value for value in arguments if value != '--cross-windows']
    names = arguments or list(DEFAULT_TESTS)
    if cross:
        names += ['background_cross_platform.py', 'receipt-native/cross_receipt.py']
        for variable in ('MAGNOLIE_DOTNET', 'MAGNOLIE_RECEIPT_PROBE'):
            if not os.environ.get(variable) or not Path(os.environ[variable]).is_file():
                raise SystemExit('Explicit cross gate requires ' + variable)
    class NoSkippedChecks:
        def pytest_sessionfinish(self, session, exitstatus):
            reporter = session.config.pluginmanager.getplugin('terminalreporter')
            if reporter and reporter.stats.get('skipped'):
                session.exitstatus = 1
    with tempfile.TemporaryDirectory(prefix='magnolie-background-tests-', dir='/tmp') as root:
        for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME',
                    'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR', 'TMPDIR'):
            folder = Path(root) / key
            folder.mkdir(mode=0o700)
            os.environ[key] = str(folder)
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'APPIMAGE', 'APPDIR', 'FLATPAK_ID', 'SSH_AUTH_SOCK'):
            os.environ.pop(key, None)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS'):
            os.environ[key] = 'unix:path=' + root + '/absent-bus'
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        sys.dont_write_bytecode = True
        tempfile.tempdir = os.environ['TMPDIR']
        sys.path[:0] = [str(ROOT / 'bin'), str(ROOT / 'pruefungen')]
        bind, connect, popen = socket.socket.bind, socket.socket.connect, subprocess.Popen

        def private_bind(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                if address[1] != 0:
                    raise OSError('Test runner blocks fixed network ports')
                address = (('127.0.0.1', 0) if sock.family == socket.AF_INET else
                           ('::ffff:127.0.0.1' if address[0] == '::' else '::1', 0))
            elif sock.family != socket.AF_UNIX or not str(address).startswith('/tmp/'):
                raise OSError('Test runner blocks non-private sockets')
            return bind(sock, address)

        def private_connect(sock, address):
            if sock.family == socket.AF_UNIX:
                allowed = str(address).startswith('/tmp/')
            else:
                allowed = sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] in ('127.0.0.1', '::1')
            if not allowed:
                raise OSError('Test runner blocks external connections')
            return connect(sock, address)

        def no_discovery(*args, **kwargs):
            raise OSError('Test runner blocks discovery datagrams')

        def private_process(args, *pos, **kwargs):
            allowed = {os.path.realpath(sys.executable)}
            dotnet = os.environ.get('MAGNOLIE_DOTNET')
            if dotnet:
                allowed.add(os.path.realpath(dotnet))
            if (kwargs.get('shell') or not isinstance(args, (tuple, list)) or
                    os.path.realpath(str(args[0])) not in allowed):
                raise OSError('Test runner blocks desktop/system subprocesses')
            return popen(args, *pos, **kwargs)

        socket.socket.bind = private_bind
        socket.socket.connect = private_connect
        socket.socket.sendto = no_discovery
        subprocess.Popen = private_process
        import pytest
        print('Isolated test root:', root, flush=True)
        print('Selected suites:', ', '.join(names), flush=True)
        return pytest.main(['-q', '-p', 'no:cacheprovider', '--basetemp=' + root + '/pytest',
                            *[str(ROOT / 'pruefungen' / name) for name in names]], plugins=[NoSkippedChecks()])


if __name__ == '__main__':
    raise SystemExit(main())
