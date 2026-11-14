"""Actual Linux bridge -> native catalog -> UI callback -> session approval.

Synthetic transport and decision callback; actual GTK acceptance is separate.
"""
import json
import threading
from types import SimpleNamespace

import pytest

from test_startup_read_failure import native, Host
from test_contact_source_dav_factory import account, Source, saved_book


@pytest.mark.parametrize('mode', ['allow', 'cancel', 'empty', 'unsaved', 'busy', 'book-before-dialog',
    'account-before-dialog', 'revoke-before-dialog', 'account-during-dialog', 'book-during-dialog',
    'renderer-catalog', 'discovery-failed', 'revoke-during-dialog'])
def test_bridge_requires_native_catalog_and_explicit_current_decision(native, tmp_path, monkeypatch, mode):
    store, source = account(tmp_path), Source(native)
    actual_checked = store.checked_client
    clients = []
    def checked(revision, purpose='dav', transport=None, *, interactive=True):
        client = actual_checked(revision, purpose=purpose, transport=source.transport, interactive=interactive)
        clients.append(client)
        return client
    monkeypatch.setattr(store, 'checked_client', checked)
    monkeypatch.setattr(native, 'nextcloud_speicher', lambda: store)
    owner, data, text, current = saved_book(tmp_path)
    host = Host(native)
    host._gesperrt = False
    host._aktuelle_daten = data
    host._kontakt_quellen_buchaufnahme = lambda: owner.capture('native-contact-fixture', True, data)
    host._kontakt_quellen_buchnachweis = current
    host._kontakt_quellen_dialog_aktiv = mode == 'busy'
    if mode == 'unsaved': owner.invalidate_saved()
    if mode == 'discovery-failed':
        source.transport = lambda *_: (_ for _ in ()).throw(OSError('Controlled catalog failure'))
    idles, threads, decisions = [], [], []
    monkeypatch.setattr(native, 'GLib', SimpleNamespace(idle_add=lambda callback, *args: idles.append((callback, args))))
    real_thread = threading.Thread
    def worker(*args, **kwargs):
        thread = real_thread(*args, **kwargs); threads.append(thread); return thread
    monkeypatch.setattr(native, 'threading', SimpleNamespace(Thread=worker))
    def choose(parent, choices, selected):
        decisions.append(tuple(item['uid'] for item in choices))
        assert parent is host and len(choices) == 1 and selected == ()
        assert choices[0]['href'] == source.href
        if mode == 'account-during-dialog': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed', account_type='generic-dav')
        if mode == 'book-during-dialog': data['unsavedEdit'] = True
        if mode == 'revoke-during-dialog': host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen'}))
        return None if mode == 'cancel' else () if mode == 'empty' else (choices[0]['uid'],)
    monkeypatch.setattr(native, 'kontakt_quellen_freigabe_dialog', choose)
    host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_freigabe', 'requestId': 'probe',
        'saved': True, 'canUpdate': True, 'sources': [{'uid': 'forged', 'href': 'https://foreign.invalid/'}],
        'selected': ['forged'], 'sourceAdmissions': ['forged']}))
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), 'Bounded native discovery did not finish'
    assert not decisions, 'Worker called GTK before returning to main-thread idle callback'
    assert all(client.password == '' for client in clients), 'Owned discovery credential copy retained'
    if mode == 'book-before-dialog': data['unsavedEdit'] = True
    if mode == 'account-before-dialog': store.save(True, False, 'https://source.invalid/nc', 'synthetic', 'changed', account_type='generic-dav')
    if mode == 'revoke-before-dialog': host.bei_nachricht(json.dumps({'cmd': 'kontakt_originalquellen_widerrufen'}))
    for callback, args in idles: assert callback(*args) is False
    callback, response = host.responses[-1]
    assert callback == 'App.originalKontaktFreigabe' and response['requestId'] == 'probe'
    success = mode in ('allow', 'cancel', 'empty', 'renderer-catalog')
    assert response['ok'] is success
    assert response.get('freigaben', 0) == (1 if mode in ('allow', 'renderer-catalog') else 0)
    assert bool(decisions) is (success or mode.endswith('-during-dialog'))
    assert source.writes == 0 and not any(method in ('PUT', 'DELETE') for method, *_ in source.records)
    if mode not in ('busy',): assert not host._kontakt_quellen_dialog_aktiv
