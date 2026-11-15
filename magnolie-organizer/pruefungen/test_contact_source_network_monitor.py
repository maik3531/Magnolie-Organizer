"""Opt-in topology-only monitor lifecycle; no provider IO or real timer left."""
import threading
from types import SimpleNamespace

import pytest

from test_startup_read_failure import native, Host
from test_contact_source_dav_factory import account, Source, saved_book
from magnolie_contact_source_dav import NativeDavApprovalScope
import magnolie_nextcloud as nc


@pytest.mark.parametrize('mode', ['return', 'stable', 'no-grants', 'revoked', 'book-locked',
    'account-changed', 'stale-probe', 'missing-timer-api', 'probe-error', 'closing', 'busy-probe',
    'revoked-during-probe', 'locked-during-probe'])
def test_native_monitor_is_session_only_generation_fenced_and_never_provider_io(native, tmp_path, monkeypatch, mode):
    store, source = account(tmp_path), Source(native)
    owner, data, text, current = saved_book(tmp_path)
    scope = NativeDavApprovalScope(current, store)
    if mode != 'no-grants':
        scope.configure([{'uid': nc.source_id('addressbook', source.href, 'generic-dav'),
            'href': source.href, 'art': 'addressbook', 'canUpdate': True}], lambda choices, selected: [choices[0]['uid']])
    host = Host(native)
    host._kontakt_quellen_freigaben = scope
    host._wirklich_beenden = mode == 'closing'
    timers, removed, idles, threads = [], [], [], []
    def timer(seconds, callback):
        assert seconds == 15; timers.append(callback); return 71
    glib = SimpleNamespace(source_remove=lambda value: removed.append(value),
                           idle_add=lambda fn, *args: idles.append((fn, args)))
    if mode != 'missing-timer-api': glib.timeout_add_seconds = timer
    monkeypatch.setattr(native, 'GLib', glib)
    actual_thread = threading.Thread
    def make_thread(*args, **kwargs):
        thread = actual_thread(*args, **kwargs); threads.append(thread); return thread
    monkeypatch.setattr(native, 'threading', SimpleNamespace(Thread=make_thread))
    state = [False if mode == 'return' else True]
    probes, entered, release = [], threading.Event(), threading.Event()
    def wlan():
        probes.append(True)
        if mode == 'stale-probe': host._kontakt_quellen_netz_stoppen()
        if mode == 'revoked-during-probe': scope.revoke()
        if mode == 'locked-during-probe': owner.set_ready(False)
        if mode == 'probe-error' and len(probes) == 1: raise OSError('Controlled unknown topology')
        if mode == 'busy-probe' and len(probes) == 1:
            entered.set(); assert release.wait(timeout=2)
        return state[0]
    monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', wlan)
    def settle():
        for thread in threads:
            thread.join(timeout=4); assert not thread.is_alive(), 'Owned topology probe did not finish'
        threads.clear()
        for fn, args in idles: fn(*args)
        idles.clear()
    try:
        host._kontakt_quellen_netz_starten()
        if mode == 'busy-probe':
            assert entered.wait(timeout=2)
            assert host._kontakt_quellen_netz_pruefen() is True and len(threads) == 1
            release.set()
        settle()
        if mode in ('revoked', 'book-locked', 'account-changed'):
            if mode == 'revoked': scope.revoke()
            if mode == 'book-locked': owner.set_ready(False)
            if mode == 'account-changed': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed', account_type='generic-dav')
        if mode == 'return': state[0] = True
        if mode != 'missing-timer-api':
            host._kontakt_quellen_netz_pruefen(); settle()
            host._kontakt_quellen_netz_pruefen(); settle()
        values = [value for callback, value in host.responses if callback == 'App.originalKontaktNetz']
        assert all(set(value) == {'wlan'} and type(value['wlan']) is bool for value in values)
        if mode == 'return': assert values == [{'wlan': False}, {'wlan': True}, {'wlan': True}]
        elif mode in ('no-grants', 'closing', 'stale-probe', 'missing-timer-api', 'revoked-during-probe', 'locked-during-probe'):
            assert values == []
        elif mode in ('revoked', 'book-locked', 'account-changed'): assert values == [{'wlan': True}]
        elif mode == 'probe-error': assert values == [{'wlan': True}] * 2
        else: assert values == [{'wlan': True}] * 3
        if mode in ('revoked', 'book-locked', 'account-changed', 'no-grants', 'closing', 'stale-probe',
                    'revoked-during-probe', 'locked-during-probe'):
            assert removed == [71] and host._kontakt_quellen_netz_timer is None
        if mode == 'missing-timer-api': assert not probes and not timers and not threads
        assert source.records == [] and source.writes == 0
    finally:
        release.set(); settle(); host._kontakt_quellen_netz_stoppen()
