#!/usr/bin/env python3
"""Real SSHFS/SFTP and an owned directory handler; no user phone or user files."""
import io
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import selectors
import re
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


@contextmanager
def windows_forward(port):
    tunnel = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'LogLevel=INFO',
        '-N', '-R', '127.0.0.1:0:127.0.0.1:' + str(port), 'windows'], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        data = b''; deadline = time.monotonic() + 15
        with selectors.DefaultSelector() as events:
            events.register(tunnel.stderr, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if not events.select(max(0, deadline - time.monotonic())): break
                block = os.read(tunnel.stderr.fileno(), 4096)
                if not block: break
                data = (data + block)[-8192:]
                match = re.search(rb'Allocated port (\d+)', data)
                if match:
                    yield int(match[1])
                    return
        raise AssertionError('The owned SSH reverse-forward listener could not be established')
    finally:
        tunnel.terminate()
        try: tunnel.wait(5)
        except subprocess.TimeoutExpired: tunnel.kill(); tunnel.wait(3)
        tunnel.stderr.close()


def windows_probe(address, port, cert, accepted, attempts, transports):
    with windows_forward(port) as forwarded:
        windows_probe_forwarded('127.0.0.1', forwarded, cert, accepted, attempts, transports)


def windows_probe_forwarded(address, port, cert, accepted, attempts, transports):
    def powershell(script, timeout=60):
        return subprocess.run(['ssh', '-o', 'BatchMode=yes', 'windows', 'powershell.exe', '-NoProfile', '-NonInteractive',
            '-Command', '-'], input=script + '\n', capture_output=True, text=True, errors='replace', timeout=timeout)
    created = powershell(r'''
$ErrorActionPreference = 'Stop'
$temp = [IO.Path]::GetTempPath()
if (-not (Get-Item -LiteralPath $temp).PSIsContainer) { throw 'Missing native fixture parent' }
$root = Join-Path $temp ('Magnolie-Kernel171-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
[Console]::WriteLine($root)
''')
    assert created.returncode == 0 and created.stdout.strip(), 'Owned Windows fixture directory could not be created'
    root = created.stdout.strip()
    runner = Path(__file__).resolve().parents[2] / 'magnolie-organizer-windows/tests/bin/Release/net8.0'
    assert (runner / 'CoreTests.dll').is_file(), 'Fresh CoreTests runner required'
    subprocess.run(['scp', '-q', '-r', str(runner), 'windows:' + root.replace('\\', '/') + '/'], check=True, timeout=120)
    config = json.dumps({'host': address, 'port': port,
        'certificate': cert.public_bytes(serialization.Encoding.PEM).decode('ascii')})
    script = r'''
$ErrorActionPreference = 'Stop'
$root = '__ROOT__'
$configuration = Join-Path $root 'configuration.json'
[IO.File]::WriteAllText($configuration, '__CONFIG__', (New-Object Text.UTF8Encoding($false)))
$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = 'dotnet'
$start.Arguments = '"' + (Join-Path $root 'net8.0/CoreTests.dll') + '" --kde-filesystem-native-probe "' + $configuration + '"'
$start.UseShellExecute = $false
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$process = [Diagnostics.Process]::Start($start)
$errors = $process.StandardError.ReadToEndAsync()
$taskName = Split-Path $root -Leaf
try {
    $line = $process.StandardOutput.ReadLineAsync()
    if (-not $line.Wait(45000)) { throw 'Native fixture did not finish its mount wait' }
    $mounted = $line.GetAwaiter().GetResult()
    if (-not $mounted -or -not $mounted.StartsWith('MOUNTED ')) { throw 'Owned native mount failed' }
    $point = ($mounted.Substring(8) | ConvertFrom-Json).point
    if (-not $point.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Foreign mount point returned' }
    [IO.File]::WriteAllText((Join-Path $root 'explorer-request.json'), (@{point=$point} | ConvertTo-Json -Compress))
    $uiScript = @'
$ErrorActionPreference = 'Stop'
$root = '__ROOT__'
$result = Join-Path $root 'explorer-result.json'
$window = $null
try {
    $point = (Get-Content -LiteralPath (Join-Path $root 'explorer-request.json') -Raw | ConvertFrom-Json).point
    if (-not $point.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) { throw 'Foreign directory' }
    $session = [Diagnostics.Process]::GetCurrentProcess().SessionId
    if ($session -eq 0) { throw 'Interactive session required' }
    if ([IO.File]::ReadAllText((Join-Path $point 'fixture.txt')) -ne 'fixture-only') { throw 'Limited-user directory read failed' }
    $shell = New-Object -ComObject Shell.Application
    $before = @{}
    foreach ($item in $shell.Windows()) { try { $before[[long]$item.HWND]=$true } catch {} }
    Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList ('/separate /n,"' + $point + '"') | Out-Null
    $deadline = [datetime]::UtcNow.AddSeconds(12)
    do {
        foreach ($item in $shell.Windows()) {
            try {
                if (-not $before.ContainsKey([long]$item.HWND) -and
                    [string]::Equals([IO.Path]::GetFullPath($item.Document.Folder.Self.Path),[IO.Path]::GetFullPath($point),[StringComparison]::OrdinalIgnoreCase)) {
                    $window=$item; break
                }
            } catch {}
        }
        if (-not $window) { Start-Sleep -Milliseconds 200 }
    } while (-not $window -and [datetime]::UtcNow -lt $deadline)
    if (-not $window) { throw 'New owned Explorer window not found' }
    $window.Quit(); $window=$null
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $admin=(New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    [IO.File]::WriteAllText($result,(@{ok=$true; session=$session; elevated=$admin; fixture_read=$true; owned_window_opened_closed=$true} | ConvertTo-Json -Compress))
} catch {
    [IO.File]::WriteAllText($result,(@{ok=$false; type=$_.Exception.GetType().Name; reason=$_.Exception.Message} | ConvertTo-Json -Compress))
} finally { if ($window) { $window.Quit() } }
'@
    $uiPath = Join-Path $root 'explorer-probe.ps1'
    [IO.File]::WriteAllText($uiPath,$uiScript)
    $action=New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $uiPath + '"')
    $principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $uiResult=Join-Path $root 'explorer-result.json'
    $until=[datetime]::UtcNow.AddSeconds(20)
    while (-not (Test-Path -LiteralPath $uiResult) -and [datetime]::UtcNow -lt $until) { Start-Sleep -Milliseconds 200 }
    if (-not (Test-Path -LiteralPath $uiResult)) { throw 'Interactive Explorer task did not return' }
    $ui=Get-Content -LiteralPath $uiResult -Raw | ConvertFrom-Json
    if (-not $ui.ok) { throw ('Interactive Explorer failed: ' + $ui.reason) }
    $process.StandardInput.WriteLine('CLOSE'); $process.StandardInput.Flush()
    if (-not $process.WaitForExit(15000)) { throw 'Owned kernel mount did not stop within its deadline' }
    $rest = $process.StandardOutput.ReadToEnd()
    if ($process.ExitCode -ne 0 -or -not $rest.Contains('NATIVE FILESYSTEM PASS')) { throw 'Native kernel readback/cleanup failed' }
    @{ passed=$true; kernel_mount_read=$true; explorer=$ui; owned_unmount=$true; fixture=(Split-Path $root -Leaf) } | ConvertTo-Json -Depth 5 -Compress
} catch {
    if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit(5000) | Out-Null }
    $errorText = $errors.GetAwaiter().GetResult()
    @{ passed=$false; diagnostics=$errorText.Substring(0,[Math]::Min(2200,$errorText.Length)); fixture=(Split-Path $root -Leaf) } | ConvertTo-Json -Compress
    exit 1
} finally {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    $tag = Split-Path $root -Leaf
    Get-CimInstance Win32_Process -Filter "Name='sshfs-win.exe' OR Name='sshfs.exe' OR Name='ssh.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine.IndexOf($tag,[StringComparison]::OrdinalIgnoreCase) -ge 0
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}
'''.replace('__ROOT__', root.replace("'", "''")).replace('__CONFIG__', config.replace("'", "''"))
    result = powershell(script, timeout=105)
    print(result.stdout.strip())
    if result.returncode: print('Owned fixture transport/authentication counts:', len(transports), len(accepted), 'attempt metadata:', attempts)
    assert result.returncode == 0, 'See bounded native Windows mount diagnostic'
    assert accepted == ['kdeconnect'], 'Host-key rejection leaked credentials or mounted more than the owned session'


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
        accepted = []; attempts = []
        class Authentication(paramiko.ServerInterface):
            def get_allowed_auths(self, username): return 'password'
            def check_auth_password(self, username, password):
                attempts.append({'length': len(password), 'trailing_cr': password.endswith('\r')})
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
        address = '127.0.0.1'
        listener = socket.socket(); listener.bind((address, 0)); listener.listen(2); listener.settimeout(0.25)
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
            if '--windows' in sys.argv:
                windows_probe(address, port, certificate(key), accepted, attempts, transports)
                return
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
