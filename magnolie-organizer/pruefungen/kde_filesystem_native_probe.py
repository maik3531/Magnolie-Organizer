#!/usr/bin/env python3
"""Real SSHFS/SFTP and an owned directory handler; no user phone or user files."""
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

if os.environ.get('MAGNOLIE_SFTP_TEST_DEPS'):
    sys.path.insert(0, os.environ['MAGNOLIE_SFTP_TEST_DEPS'])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import paramiko
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from magnolie_kde_filesystem import SshfsBrowser, FilesystemError, description


def certificate(key):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'a' * 32)])
    now = datetime.now(timezone.utc)
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))


def main():
    with tempfile.TemporaryDirectory(prefix='kde fs,native-') as temporary:
        root = Path(temporary); remote = root / 'remote'; remote.mkdir()
        (remote / 'fixture.txt').write_text('fixture-only', encoding='utf-8')
        data = root / 'data'; config = root / 'config'; applications = data / 'applications'
        applications.mkdir(parents=True); config.mkdir()
        marker = root / 'opened.json'; helper = root / 'directory-handler.py'
        helper.write_text('import json,sys\nfrom pathlib import Path\nfrom urllib.parse import urlparse,unquote\n'
            'folder=Path(unquote(urlparse(sys.argv[1]).path))\n'
            'Path(' + repr(str(marker)) + ').write_text(json.dumps({"contents":(folder/"fixture.txt").read_text(),'
            '"directory":str(folder)}))\n', encoding='utf-8')
        (applications / 'fixture-directory.desktop').write_text('[Desktop Entry]\nType=Application\nName=Owned directory fixture\n'
            'Exec=/usr/bin/python3 "' + str(helper) + '" %U\nMimeType=inode/directory;\nNoDisplay=true\n', encoding='utf-8')
        (config / 'mimeapps.list').write_text('[Default Applications]\ninode/directory=fixture-directory.desktop\n', encoding='utf-8')
        os.environ['XDG_CONFIG_HOME'] = str(config); os.environ['XDG_DATA_HOME'] = str(data)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        host = paramiko.RSAKey.from_private_key(io.StringIO(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode('ascii')))
        accepted = []
        class Authentication(paramiko.ServerInterface):
            def get_allowed_auths(self, username): return 'password'
            def check_auth_password(self, username, password):
                if username == 'kdeconnect' and password == 'native-fixture-password':
                    accepted.append(username); return paramiko.AUTH_SUCCESSFUL
                return paramiko.AUTH_FAILED
            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        class Files(paramiko.SFTPServerInterface):
            def local(self, value):
                candidate = (remote / value.lstrip('/')).resolve()
                candidate.relative_to(remote.resolve())
                return candidate
            def canonicalize(self, value): return '/' + str(Path(value)).lstrip('./') if value != '.' else '/'
            def stat(self, value):
                try: return paramiko.SFTPAttributes.from_stat(self.local(value).stat())
                except (ValueError, OSError): return paramiko.SFTP_NO_SUCH_FILE
            lstat = stat
            def list_folder(self, value):
                result = []
                for path in self.local(value).iterdir():
                    entry = paramiko.SFTPAttributes.from_stat(path.stat()); entry.filename = path.name; result.append(entry)
                return result
            def open(self, value, flags, attr):
                try:
                    handle = paramiko.SFTPHandle(flags); handle.readfile = open(self.local(value), 'rb'); return handle
                except (ValueError, OSError): return paramiko.SFTP_NO_SUCH_FILE
        stop = threading.Event(); transports = []
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(2); listener.settimeout(0.25)
        port = listener.getsockname()[1]
        def serve():
            while not stop.is_set():
                try: client, _address = listener.accept()
                except socket.timeout: continue
                except OSError: return
                transport = paramiko.Transport(client); transports.append(transport)
                transport.add_server_key(host); transport.set_subsystem_handler('sftp', paramiko.SFTPServer, Files)
                try: transport.start_server(server=Authentication())
                except (paramiko.SSHException, EOFError): transport.close()
        server = threading.Thread(target=serve, daemon=True); server.start()
        browser = SshfsBrowser(str(root / 'mounts'))
        try:
            assert browser.available(), 'SSHFS, fusermount and owned directory handler are required'
            report = description({'port': port, 'user': 'kdeconnect', 'path': '/', 'password': 'native-fixture-password'})
            try:
                browser.open('wrong-key', '127.0.0.1', report, certificate(rsa.generate_private_key(public_exponent=65537, key_size=2048)), lambda: True)
            except FilesystemError: pass
            else: raise AssertionError('Wrong SSH host key was accepted')
            assert not accepted and not marker.exists(), 'Credentials or directory reached the wrong host key'
            assert browser.open('fixture', '127.0.0.1', report, certificate(key), lambda: True)['ok']
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: stop.wait(0.05)
            result = json.loads(marker.read_text())
            assert result['contents'] == 'fixture-only' and accepted == ['kdeconnect']
            mount = result['directory']; assert os.path.ismount(mount)
            browser.close('fixture')
            assert not os.path.ismount(mount) and not Path(mount).exists() and not browser.sessions
            print('Native SSHFS host-key rejection, real SFTP read, owned directory handler and unmount/process cleanup: PASS')
        finally:
            browser.close(); stop.set(); listener.close()
            for transport in transports: transport.close()
            server.join(3)
            assert not server.is_alive()


if __name__ == '__main__': main()
