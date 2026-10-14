"""KDE Connect SFTP descriptions and the existing desktop's file-manager mount."""
import base64
import hashlib
import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization

PACKET = 'kdeconnect.sftp'
REQUEST = 'kdeconnect.sftp.request'


class FilesystemError(RuntimeError):
    pass


@dataclass(frozen=True)
class SftpDescription:
    port: int
    user: str
    path: str
    password: str = field(repr=False)


def description(body):
    required = {'port', 'user', 'path', 'password'}
    optional = {'ip', 'multiPaths', 'pathNames'}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - required - optional:
        raise FilesystemError('invalid_filesystem_description')
    if type(body['port']) is not int or not 1 <= body['port'] <= 65535:
        raise FilesystemError('invalid_filesystem_description')
    if not isinstance(body['user'], str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', body['user']):
        raise FilesystemError('invalid_filesystem_description')
    if (not isinstance(body['password'], str) or not 1 <= len(body['password']) <= 512 or
            any(not c.isprintable() for c in body['password'])):
        raise FilesystemError('invalid_filesystem_description')
    def path(value):
        return (isinstance(value, str) and 1 <= len(value) <= 4096 and value.startswith('/') and
            all(c.isprintable() for c in value) and '\\' not in value and
            not any(part in ('.', '..') for part in value.split('/')))
    if not path(body['path']):
        raise FilesystemError('invalid_filesystem_description')
    if 'multiPaths' in body:
        paths = body['multiPaths']
        if not isinstance(paths, list) or not 1 <= len(paths) <= 64 or not all(path(value) for value in paths):
            raise FilesystemError('invalid_filesystem_description')
    if 'pathNames' in body:
        names = body['pathNames']
        if (not isinstance(names, list) or 'multiPaths' not in body or len(names) != len(body['multiPaths']) or
                not all(isinstance(value, str) and 1 <= len(value) <= 256 and all(c.isprintable() for c in value) for value in names)):
            raise FilesystemError('invalid_filesystem_description')
    # The address always comes from the authenticated LAN connection, never from body.ip.
    return SftpDescription(body['port'], body['user'], '/' if 'multiPaths' in body else body['path'], body['password'])


def uri(address, report):
    try:
        host = ipaddress.ip_address(address)
    except (ValueError, TypeError) as error:
        raise FilesystemError('filesystem_wifi_unavailable') from error
    if host.is_unspecified or host.is_multicast:
        raise FilesystemError('filesystem_wifi_unavailable')
    hostname = '[' + str(host).replace('%', '%25') + ']' if host.version == 6 else str(host)
    return 'sftp://%s@%s:%d%s' % (quote(report.user, safe=''), hostname, report.port, quote(report.path, safe='/'))


def host_fingerprints(certificate):
    public = certificate.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    blob = base64.b64decode(public.split()[1], validate=True)
    sha = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode('ascii').rstrip('=')
    legacy = ':'.join('%02x' % value for value in hashlib.md5(blob, usedforsecurity=False).digest())
    return sha, legacy


class SshfsBrowser:
    """Own mounts; strict phone-certificate host keys and no password in argv or URI."""
    def __init__(self, directory):
        self.directory = os.path.join(directory, 'filesystem')
        self.lock = threading.RLock()
        self.sessions = {}

    @staticmethod
    def available():
        try:
            from gi.repository import Gio
            return bool(shutil.which('sshfs') and (shutil.which('fusermount3') or shutil.which('fusermount')) and
                Gio.AppInfo.get_default_for_type('inode/directory', False) is not None)
        except (ImportError, RuntimeError):
            return False

    @staticmethod
    def _show(path, current):
        from gi.repository import Gio
        app = Gio.AppInfo.get_default_for_type('inode/directory', False)
        if app is None or not current() or not app.launch_uris([Gio.File.new_for_path(path).get_uri()], None):
            raise FilesystemError('filesystem_file_manager_unavailable')

    def open(self, source, address, report, certificate, current):
        # Validates IP, port, username and path before constructing a native argument list.
        uri(address, report)
        public = certificate.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        endpoint = address, report.port, report.user, report.path, public
        with self.lock:
            if not current() or not self.available():
                raise FilesystemError('filesystem_source_changed')
            previous = self.sessions.get(source)
            if previous and previous['endpoint'] == endpoint and previous['process'].poll() is None and os.path.ismount(previous['mount']):
                self._show(previous['mount'], current)
                return {'ok': True, 'state': 'opened'}
            if previous:
                self._cleanup(previous)
                self.sessions.pop(source, None)
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
            if os.path.islink(self.directory) or not os.path.isdir(self.directory):
                raise FilesystemError('filesystem_mount_unavailable')
            os.chmod(self.directory, 0o700)
            directory = tempfile.mkdtemp(prefix='phone-', dir=self.directory)
            mount = os.path.join(directory, 'files')
            os.mkdir(mount, 0o700)
            known = os.path.join(directory, 'known_hosts')
            host = str(ipaddress.ip_address(address))
            host_entry = host if report.port == 22 else '[%s]:%d' % (host, report.port)
            with open(os.open(known, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
                file.write(host_entry.encode('ascii') + b' ' + public + b'\n')
            remote = report.user + '@' + ('[' + host + ']' if ':' in host else host) + ':' + report.path
            known_option = 'UserKnownHostsFile="' + known.replace('\\', '\\\\').replace('"', '\\"').replace(',', '\\,') + '"'
            arguments = [shutil.which('sshfs'), remote, mount, '-p', str(report.port), '-f', '-s', '-F', '/dev/null',
                '-o', 'password_stdin', '-o', 'StrictHostKeyChecking=yes', '-o', known_option,
                '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'PreferredAuthentications=password',
                '-o', 'PubkeyAuthentication=no', '-o', 'NumberOfPasswordPrompts=1', '-o', 'ConnectTimeout=5',
                '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']
            process = None
            entry = {'directory': directory, 'mount': mount, 'known': known, 'process': None, 'endpoint': endpoint}
            try:
                process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
                entry['process'] = process
                process.stdin.write(report.password.encode('utf-8') + b'\n')
                process.stdin.close()
                deadline = time.monotonic() + 15
                wait = threading.Event()
                while not os.path.ismount(mount):
                    if not current():
                        raise FilesystemError('filesystem_source_changed')
                    if process.poll() is not None:
                        raise FilesystemError('filesystem_mount_failed')
                    if time.monotonic() >= deadline:
                        raise FilesystemError('filesystem_mount_timeout')
                    wait.wait(0.05)
                self._show(mount, current)
                self.sessions[source] = entry
                return {'ok': True, 'state': 'opened'}
            except Exception:
                self._cleanup(entry)
                raise

    @staticmethod
    def _cleanup(entry):
        mount, process = entry['mount'], entry['process']
        if os.path.ismount(mount):
            executable = shutil.which('fusermount3') or shutil.which('fusermount')
            if executable:
                try:
                    subprocess.run([executable, '-u', '-z', mount], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        # Never recursively remove a mount: even a failed unmount must not delete phone files.
        if not os.path.ismount(mount):
            try:
                os.rmdir(mount)
                os.unlink(entry['known'])
                os.rmdir(entry['directory'])
            except OSError:
                pass

    def close(self, source=None):
        with self.lock:
            for key in list(self.sessions):
                if source is None or key == source:
                    self._cleanup(self.sessions.pop(key))
