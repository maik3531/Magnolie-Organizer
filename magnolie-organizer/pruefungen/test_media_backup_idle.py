"""Native resource sampling is fail-closed and never lowers UI priority."""
from pathlib import Path
import os
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_media_backup_idle import NativeLinuxBackupIdleProbe, lower_current_backup_thread_priority
from magnolie_media_backup_codec import MIN_IDLE_MS, MIN_AVAILABLE_BYTES, NativeBackupIdlePermit
from magnolie_file_transfer import TransferError


def setup_probe():
    value = dict(now=1_000_000_000, idle=MIN_IDLE_MS, cpu=(1000, 800), memory=MIN_AVAILABLE_BYTES, own=0)
    probe = NativeLinuxBackupIdleProbe(idle=lambda: value['idle'], cpu=lambda: value['cpu'], memory=lambda: value['memory'],
        clock=lambda: value['now'], own_cpu=lambda: value['own'], tick_hz=100)
    return value, probe


def advance(value, *, busy=0, own=0):
    value['now'] += 1_000_000_000
    total, waiting = value['cpu']
    value['cpu'] = total + 100, waiting + 100 - busy
    value['own'] += own


def test_current_native_load_needs_two_observations_and_other_work_pauses_permit():
    value, probe = setup_probe()
    assert probe.observe() is None
    advance(value)
    assert probe.observe().cpu_percent == 0
    permit = NativeBackupIdlePermit(probe.observe, lambda: True)
    advance(value, busy=30)
    with pytest.raises(TransferError): permit.require_current()
    advance(value)
    with pytest.raises(TransferError): permit.require_current()


def test_compressor_own_cpu_is_not_mistaken_for_new_interactive_load():
    value, probe = setup_probe(); assert probe.observe() is None
    advance(value, busy=100, own=1_000_000_000)
    assert probe.observe().cpu_percent == 0
    advance(value, busy=100, own=800_000_000)
    assert probe.observe().cpu_percent == 20


@pytest.mark.parametrize('change', ['unknown-idle', 'low-memory', 'active-user', 'clock', 'counters'])
def test_unknown_or_changed_native_observation_never_grants_idle(change):
    value, probe = setup_probe(); probe.observe(); advance(value); probe.observe()
    permit = NativeBackupIdlePermit(probe.observe, lambda: True)
    advance(value)
    if change == 'unknown-idle': value['idle'] = None
    if change == 'low-memory': value['memory'] -= 1
    if change == 'active-user': value['idle'] = 0
    if change == 'clock': value['now'] = 0
    if change == 'counters': value['cpu'] = (1, 2)
    with pytest.raises(TransferError): permit.require_current()


def test_probe_cannot_be_shared_with_a_different_worker_and_ui_priority_is_unchanged():
    value, probe = setup_probe(); probe.observe(); advance(value); assert probe.observe()
    priority = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())
    with pytest.raises(TransferError): lower_current_backup_thread_priority()
    results = []
    def worker():
        results.append(probe.observe())
        lower_current_backup_thread_priority()
        results.append(os.getpriority(os.PRIO_PROCESS, threading.get_native_id()))
    thread = threading.Thread(target=worker)
    thread.start(); thread.join(5)
    assert not thread.is_alive() and results == [None, 19]
    assert os.getpriority(os.PRIO_PROCESS, threading.get_native_id()) == priority
