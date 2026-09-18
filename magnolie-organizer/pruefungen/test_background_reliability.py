"""Private lifecycle regressions; no desktop bus, fixed ports or user profile."""
import json
import multiprocessing
import os
from pathlib import Path
import queue
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest
from modul_laden import quellmodul_laden

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
import magnolie_hintergrund as bg
import magnolie_telefon as phone
from magnolie_setup_state import write_state
app = quellmodul_laden('reliability_app', ROOT / 'bin' / 'magnolie-organizer')
# Cold public-package dependency imports are not a daemon protocol deadline.
PROCESS_START_TIMEOUT = 60


@pytest.fixture
def private(tmp_path, monkeypatch):
    for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME'):
        path = tmp_path / key
        path.mkdir(mode=0o700)
        monkeypatch.setenv(key, str(path))
    with tempfile.TemporaryDirectory(prefix='mo-life-', dir='/tmp') as runtime:
        monkeypatch.setenv('XDG_RUNTIME_DIR', runtime)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS'):
            monkeypatch.setenv(key, 'unix:path=' + runtime + '/absent-bus')
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'APPIMAGE', 'APPDIR'):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(bg, '_', bg._)
        yield tmp_path


def wait(predicate, seconds=5):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('private lifecycle timed out')


def test_busy_eight_handlers_cannot_replace_owner(private):
    path = bg.socket_path()
    owner = bg.IPCServer(None, path).start()
    duplicate = bg.IPCServer(None, path)
    clients = []
    code = """import sys
sys.path.insert(0, sys.argv[1])
from magnolie_hintergrund import IPCServer, AlreadyRunning
print('READY', flush=True)
assert input() == 'TRY'
try:
    IPCServer(None, sys.argv[2]).start()
except AlreadyRunning:
    raise SystemExit(0)
raise SystemExit('second process acquired busy owner socket')
"""
    child = subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT / 'bin'), path],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], PROCESS_START_TIMEOUT)[0], 'child import readiness timed out'
        assert child.stdout.readline().strip() == 'READY'
        inode = os.stat(path).st_ino
        for _ in range(8):
            client = socket.socket(socket.AF_UNIX)
            client.connect(path)
            clients.append(client)
        wait(lambda: owner._handlers._value == 0)
        assert bg.daemon_status(path) == 'starting'
        assert not bg.wait_for_daemon_release(path, timeout=.05)
        with pytest.raises(bg.AlreadyRunning): duplicate.start()
        assert owner._handlers._value == 0
        child.stdin.write('TRY\n'); child.stdin.flush()
        _, errors = child.communicate(timeout=3)
        assert child.returncode == 0 and not errors.strip(), errors
        duplicate.close()
        assert os.stat(path).st_ino == inode and owner.thread.is_alive()
        assert stat.S_IMODE(os.stat(path + '.lock').st_mode) == 0o600
    finally:
        if child.poll() is None: child.kill()
        child.communicate(timeout=5)
        for client in clients: client.close()
        owner.close()
    assert not os.path.exists(path) and os.path.isfile(path + '.lock')


def test_kernel_lease_and_replacement_inode_cleanup(private):
    path = bg.socket_path()
    owner = bg.IPCServer(None, path).start()
    replacement = socket.socket(socket.AF_UNIX)
    try:
        os.unlink(path)
        replacement.bind(path)
        inode = os.stat(path).st_ino
        owner.close()
        assert os.stat(path).st_ino == inode
    finally:
        replacement.close()
        owner.close()


class Backend:
    def __init__(self, *args, **kwargs): pass
    def start(self): return True
    def stop(self): pass
    def configure_receive(self, **kwargs): pass


class Notifications:
    available = actions_supported = False
    def __init__(self, glib): pass


def daemon_process(fail):
    from gi.repository import GLib
    class Selected(Backend):
        def start(self): return not fail
    phone.PORT = 0
    original_bind = socket.socket.bind
    def loopback_bind(sock, address):
        return original_bind(sock, ('::1', 0) if address == ('::', 0) else address)
    socket.socket.bind = loopback_bind
    def phone_factory(root, name, callback):
        service = phone.PhoneService(root, name, callback=callback,
            bluetooth_backend=SimpleNamespace(availability=lambda: (False, 'fixture'), paired_devices=lambda: []))
        service._publish = lambda: None
        service.enabled = True
        return service
    raise SystemExit(bg.daemon_main(glib=GLib, backend_factory=Selected,
                                   notifications_factory=Notifications, phone_factory=phone_factory))


@pytest.mark.parametrize('kde_failure', [False, True])
def test_private_glib_duplicate_stop_crash_restart(private, kde_failure):
    write_state('complete')
    bg.write_settings({'enabled': True, 'phone_setup_services': ['wifi'],
                       'permissions': {'phone_monitor': True}}, update_autostart=False)
    # Collection can initialize GLib/zeroconf threads; never fork that state.
    ctx = multiprocessing.get_context('spawn')
    children = []
    def start():
        process = ctx.Process(target=daemon_process, args=(kde_failure,))
        process.start(); children.append(process)
        wait(bg.daemon_available, seconds=PROCESS_START_TIMEOUT)
        return process
    try:
        first = start()
        settings = bg.ipc_request('get_settings')
        assert bool(settings['kde_transport_error']) == kde_failure
        assert bg.ipc_request('phone_report')['listening']
        duplicate = ctx.Process(target=daemon_process, args=(kde_failure,))
        duplicate.start(); children.append(duplicate); duplicate.join(PROCESS_START_TIMEOUT)
        assert duplicate.exitcode == 0 and first.is_alive()
        first.terminate(); first.join(5)
        assert first.exitcode == 0 and not Path(bg.socket_path()).exists()
        second = start(); second.kill(); second.join(5)
        assert second.exitcode == -signal.SIGKILL
        third = start()
        bg.ipc_request('set_settings', {'settings': {'enabled': False}})
        third.join(5)
        assert third.exitcode == 0 and not Path(bg.socket_path()).exists()
    finally:
        for child in children:
            if child.is_alive(): child.kill()
            child.join(5)


def test_rollback_epoch_keeps_dedupe_without_history_flood(private, monkeypatch):
    clock = [2_000_000]
    monkeypatch.setattr(bg.time, 'time', lambda: clock[0] / 1000)
    path = str(private / 'fresh.json')
    fresh = bg.BackgroundFreshness(path)
    assert fresh.is_fresh('phone', 'sms', {'id': 'seen', 'created_ms': clock[0]}, 'created_ms')
    clock[0] = 1_000_000
    assert fresh.is_fresh('phone', 'sms', {'id': 'new', 'created_ms': clock[0]}, 'created_ms')
    assert not fresh.is_fresh('phone', 'sms', {'id': 'history', 'created_ms': clock[0] - 1}, 'created_ms')
    assert not fresh.is_fresh('phone', 'sms', {'id': 'seen', 'created_ms': clock[0]}, 'created_ms')
    assert not fresh.is_fresh('phone', 'sms', {'id': 'future', 'created_ms': clock[0] + 60001}, 'created_ms')
    restarted = bg.BackgroundFreshness(path)
    assert not restarted.is_fresh('phone', 'sms', {'id': 'new', 'created_ms': clock[0]}, 'created_ms')
    assert restarted.is_fresh('phone', 'sms', {'id': 'after', 'created_ms': clock[0]}, 'created_ms')


def alarm_process(path, ready, release):
    claimed = app.wecker_anmelden(path)
    ready.send(claimed)
    if claimed:
        release.recv()
        app.wecker_abmelden(path)


def test_alarm_start_survives_transient_status_probe(private):
    marker = str(private / 'transient-alarm.pid')
    probe = app.FileLease(marker + '.lock')
    release = threading.Timer(.02, probe.close)
    release.start()
    try:
        assert app.wecker_anmelden(marker)
        assert Path(marker).read_text() == str(os.getpid())
    finally:
        release.join(2)
        probe.close()
        app.wecker_abmelden(marker)


def test_reminder_kernel_lease_stale_pid_and_independent_profile(private):
    ctx = multiprocessing.get_context('spawn')
    marker = str(private / 'alarm.pid')
    Path(marker).write_text(str(os.getpid()))
    assert not app.wecker_lebt(marker)
    ready, child_ready = ctx.Pipe()
    release, child_release = ctx.Pipe()
    child = ctx.Process(target=alarm_process, args=(marker, child_ready, child_release))
    child.start()
    try:
        assert ready.poll(PROCESS_START_TIMEOUT) and ready.recv()
        assert app.wecker_lebt(marker) and not app.wecker_anmelden(marker)
        Path(marker).write_text('999999999')
        assert app.wecker_lebt(marker)
        other = str(private / 'other.pid')
        assert app.wecker_anmelden(other)
        app.wecker_abmelden(other)
        assert stat.S_IMODE(os.stat(marker + '.lock').st_mode) == 0o600
        release.send(True); child.join(5)
        assert child.exitcode == 0 and not app.wecker_lebt(marker)
        assert app.wecker_anmelden(marker)
        replacement = private / 'replacement'
        replacement.write_text('not-owned')
        os.replace(replacement, marker)
        app.wecker_abmelden(marker)
        assert Path(marker).read_text() == 'not-owned'
    finally:
        if child.is_alive(): child.kill()
        child.join(5)
        for conn in (ready, child_ready, release, child_release): conn.close()


def test_backup_remains_unfinished_until_completion(private, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    data = {'version': 6, 'einstellungen': {}}
    def backup(value):
        entered.set()
        assert release.wait(5)
        return {'status': 'success'}
    worker = SimpleNamespace(_speicher_auftraege=queue.Queue(), _daten_sperre=threading.RLock(),
        _aktuelle_daten=data, _kennwort='', _vielleicht_verschluesseln=lambda text: text,
        antwort=lambda *args: None, _cloud_sicherung_nach_speichern=backup)
    monkeypatch.setattr(app, 'daten_datei', lambda: str(private / 'daten.json'))
    monkeypatch.setattr(app, 'erinnerungsdaten_datei', lambda: str(private / 'erinnerungsdaten.json'))
    thread = threading.Thread(target=app.Fenster._speicher_lauf, args=(worker,), daemon=True)
    worker._speicher_auftraege.put(('fixture', json.dumps(data)))
    thread.start()
    try:
        assert entered.wait(3)
        assert worker._speicher_laeuft and worker._speicher_auftraege.unfinished_tasks == 1
    finally:
        release.set(); worker._speicher_auftraege.put(None); thread.join(5)
        assert not thread.is_alive() and worker._speicher_auftraege.unfinished_tasks == 0


def test_phone_pending_socket_stop_and_restart(private, monkeypatch):
    original_bind = socket.socket.bind
    def private_bind(sock, address):
        assert address == ('::', 0)
        return original_bind(sock, ('::1', 0))
    monkeypatch.setattr(phone, 'PORT', 0)
    monkeypatch.setattr(socket.socket, 'bind', private_bind)
    radio = SimpleNamespace(availability=lambda: (False, 'fixture'), paired_devices=lambda: [])
    service = phone.PhoneService(str(private / 'phone'), 'Fixture', bluetooth_backend=radio)
    service._publish = lambda: None
    service.enabled = True
    clients = []
    try:
        for _ in range(3):
            assert service.start() and service.start()
            client = socket.socket(socket.AF_INET6); clients.append(client)
            client.connect(('::1', service.server.getsockname()[1]))
            wait(lambda: bool(service.active_by_ip))
            old = service.thread
            assert service.stop()
            client.settimeout(1)
            assert client.recv(1) == b''
            assert not old.is_alive() and not service._workers and not service._sockets
            assert not service.active_by_ip
    finally:
        for client in clients: client.close()
        service.stop()


def test_alarm_real_cli_duplicate_and_sigterm(private, monkeypatch):
    write_state('complete')
    # Avoid the legacy session-environment scan; this display does not exist.
    monkeypatch.setenv('DISPLAY', ':65530')
    monkeypatch.setenv('XAUTHORITY', str(private / 'absent-xauthority'))
    command = [sys.executable, '-B', str(ROOT / 'bin' / 'magnolie-organizer'), '--wecker']
    # GLib caches XDG paths in this process; the fresh CLI sees the fixture HOME.
    marker = str(Path(os.environ['XDG_DATA_HOME']) / 'magnolie-organizer' / 'wecker.pid')
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait(lambda: app.wecker_lebt(marker) or child.poll() is not None,
             seconds=PROCESS_START_TIMEOUT)
        assert child.poll() is None, child.communicate(timeout=5)
        duplicate = subprocess.run(command, capture_output=True, text=True, timeout=PROCESS_START_TIMEOUT)
        assert duplicate.returncode == 0 and child.poll() is None
        child.terminate()
        output, errors = child.communicate(timeout=10)
        assert child.returncode == 0, errors
        assert not errors.strip(), errors
        assert not Path(marker).exists() and not app.wecker_lebt(marker)
    finally:
        if child.poll() is None: child.kill()
        child.communicate(timeout=5)


def test_backup_shutdown_wait_and_cancel_generation(private, monkeypatch):
    callbacks = []
    monkeypatch.setattr(app, 'GLib', SimpleNamespace(timeout_add_seconds=lambda seconds, callback: callbacks.append(callback)))
    window = SimpleNamespace(_beenden_angefragt=False, sende_js=lambda text: None,
        _wirklich_beenden=False, _speicher_auftraege=queue.Queue(), _speicher_laeuft=True)
    app.Fenster._beenden_anfragen(window)
    first = callbacks[-1]
    window._beenden_bestaetigt = True
    first()
    assert window._beenden_angefragt
    assert app.Fenster._beenden_endgueltig(window) is True and not window._wirklich_beenden
    window._beenden_angefragt = False  # The cancellation branch cancels shutdown, not a saved backup.
    app.Fenster._beenden_anfragen(window)
    first()
    assert window._beenden_angefragt  # An old timeout cannot cancel this new request.
    callbacks[-1]()
    assert not window._beenden_angefragt


def test_phone_refuses_restart_until_old_generation_drains(private, monkeypatch):
    monkeypatch.setattr(phone, 'PORT', 0)
    service = phone.PhoneService(str(private / 'phone'), 'Fixture',
        bluetooth_backend=SimpleNamespace(availability=lambda: (False, 'fixture'), paired_devices=lambda: []))
    service._publish = lambda: None
    service.enabled = True
    entered, release = threading.Event(), threading.Event()
    def delayed_accept():
        entered.set(); release.wait(10)
    monkeypatch.setattr(service, '_accept', delayed_accept)
    try:
        assert service.start() and entered.wait(2)
        # Model a non-draining join without depending on the native audio shutdown budget.
        join_budgets = []
        monkeypatch.setattr(service.thread, 'join', lambda timeout: join_budgets.append(timeout))
        generation = service._generation
        assert not service.stop()
        assert not service.start() and service._generation == generation
        assert join_budgets and all(0 <= timeout <= 15 for timeout in join_budgets)
    finally:
        release.set()
        threading.Thread.join(service.thread, 5)
        assert service.stop()
