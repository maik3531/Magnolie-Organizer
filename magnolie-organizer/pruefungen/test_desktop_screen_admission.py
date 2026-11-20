"""Real GTK approval and signed PhoneService test parent; no compositor capture."""

from time import time_ns
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_desktop_screen_dispatch import connected, native, ping, request
from test_phone_screen_window import GLib, Gtk, PhoneScreenSessionLock, wait_for
import magnolie_desktop_screen_admission as admission
import magnolie_desktop_screen_attempt as runs
from desktop_screen_draft_interop_peer import SyntheticLocalRun
from magnolie_desktop_screen_attempt import DesktopScreenAttemptCleanup, ScreenRunCleanup
from magnolie_desktop_screen_dispatch import DesktopScreenDraftDispatch
from magnolie_desktop_screen_portal import DesktopScreenProvider, MONITOR, WINDOW


@pytest.fixture
def gtk_owner(connected, monkeypatch):
    assert Gtk.init_check()[0], 'run under Xvfb or an isolated GTK display'
    service, peer, client = connected
    dispatch = service._desktop_screen_draft_dispatch = DesktopScreenDraftDispatch(service)
    attempt = Mock()
    factory = Mock(return_value=attempt)
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', factory)
    parent = Gtk.Window()
    parent.show_all()
    lock = PhoneScreenSessionLock()
    lock._lease = object()  # Controlled logind witness; no real lock changes.
    ended = []
    owners = []

    def arm(mode='extend', provider=DesktopScreenProvider(':1.245', MONITOR | WINDOW, True, 0, 6)):
        owner = admission.DesktopScreenDraftAdmission(dispatch, peer['device_id'], client.channel,
            mode=mode, provider=provider, bus=object(), parent=parent, parent_handle='x11:245',
            session_lock=lock, ended=ended.append)
        owners.append(owner)
        return owner

    try:
        yield arm, lock, parent, factory, attempt, ended
    finally:
        for owner in owners:
            owner.close()
            if factory.called and owner._attempt is attempt and owner._cleanup is None:
                factory.call_args.kwargs['ended'](DesktopScreenAttemptCleanup(ScreenRunCleanup(True, True, True), True))
            wait_for(lambda: owner._terminal)
        parent.destroy()
        lock.close()


def show(owner, client):
    frame = request()
    client.send(frame)
    wait_for(lambda: owner._dialog is not None and owner._dialog.get_visible())
    return frame, owner._dialog


def test_wrong_mode_expiry_and_denial_never_start_portal(connected, gtk_owner):
    _, _, client = connected
    arm, _, _, factory, _, ended = gtk_owner
    with pytest.raises(PermissionError):
        arm(provider=DesktopScreenProvider(':1.245', MONITOR, False, 0, 6))
    owner = arm()
    for fields in ({'mode': 1}, {'setup_until_ms': time_ns() // 1_000_000 - 1}):
        frame = request()
        client.send(dict(frame, body=dict(frame['body'], **fields)))
    ping(client)
    assert owner._pending is None and owner._dialog is None
    _, dialog = show(owner, client)
    assert 'zusätzlichen Monitor' in dialog.get_property('text')
    assert 'Gekoppeltes Gerät: Telefon' == dialog.get_property('secondary-text')
    assert dialog.get_default_widget() is dialog.get_widget_for_response(Gtk.ResponseType.CANCEL)
    dialog.get_default_widget().clicked()
    wait_for(lambda: ended == [None])
    assert not dialog.get_visible()
    factory.assert_not_called()
    arm()  # The denied attempt created no portal and has released its slot.
    ping(client)


def test_confirm_then_native_stop_waits_for_exact_drain(connected, gtk_owner):
    _, _, client = connected
    arm, _, _, factory, attempt, ended = gtk_owner
    owner = arm()
    frame, dialog = show(owner, client)
    deadline = owner._pending[1]
    factory.assert_not_called()
    dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).clicked()
    attempt.begin.assert_called_once()
    call = factory.call_args
    assert call.args[:2] == (client.channel, frame['body'])
    assert call.kwargs['mode'] == 'extend' and call.kwargs['deadline'] == deadline
    call.args[2]()
    stop = dict(frame, body=dict(frame['body'], op='stop', session='12' * 16))
    client.send(stop)
    ping(client)
    attempt.receive.assert_called_once_with(client.channel, stop)
    dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).clicked()
    attempt.stop.assert_called_once()
    assert not dialog.get_visible()
    with pytest.raises(PermissionError):
        call.args[2]()
    assert not ended
    with pytest.raises(PermissionError):
        arm()
    cleanup = DesktopScreenAttemptCleanup(ScreenRunCleanup(True, True, True), True)
    call.kwargs['ended'](cleanup)
    wait_for(lambda: ended == [cleanup])
    arm()


def test_lock_then_unlock_cannot_reuse_pending_confirmation(connected, gtk_owner):
    _, _, client = connected
    arm, lock, _, factory, _, ended = gtk_owner
    props = {'LockedHint': GLib.Variant('b', False), 'Active': GLib.Variant('b', True)}
    proxy = SimpleNamespace(get_name_owner=lambda: ':1.245', get_cached_property=props.get)
    lock._proxy = proxy
    try:
        owner = arm()
        _, dialog = show(owner, client)
        stale_confirm = dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT)
        lock._signal(proxy, ':1.245', 'Lock', None)
        lock._signal(proxy, ':1.245', 'Unlock', None)
        stale_confirm.clicked()
        wait_for(lambda: ended == [None])
        with pytest.raises(PermissionError, match='lock_state_unavailable'):
            arm()
        for locked in (True, False):
            props['LockedHint'] = GLib.Variant('b', locked)
            lock._properties(proxy, GLib.Variant('a{sv}', {'LockedHint': props['LockedHint']}), [])
        arm()  # A new local admission, after native confirmation of unlock.
        stale_confirm.clicked()
        factory.assert_not_called()
        assert not dialog.get_visible()
        ping(client)
    finally:
        lock._proxy = None


def test_exit_and_failed_portal_cleanup_do_not_free_slot(connected, gtk_owner):
    service, peer, client = connected
    arm, _, parent, factory, attempt, ended = gtk_owner
    owner = arm()
    _, dialog = show(owner, client)
    dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).clicked()
    parent.destroy()
    attempt.stop.assert_called_once()
    assert not dialog.get_visible() and not owner._terminal
    cleanup = DesktopScreenAttemptCleanup(ScreenRunCleanup(False, True, True), True)
    factory.call_args.kwargs['ended'](cleanup)
    wait_for(lambda: ended == [cleanup])
    with pytest.raises(PermissionError, match='reader_busy'):
        service._desktop_screen_draft_dispatch.attach(peer['device_id'], client.channel, lambda *_: None)
    ping(client)


def test_local_stop_after_offer_before_phone_approval_is_terminal(connected, gtk_owner, monkeypatch):
    _, _, client = connected
    arm, _, _, _, _, ended = gtk_owner
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', runs.DesktopScreenDraftAttempt)
    monkeypatch.setattr(runs, 'DesktopScreenLocalRun', SyntheticLocalRun)
    owner = arm()
    frame, dialog = show(owner, client)
    dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).clicked()
    wait_for(lambda: owner._attempt is not None and owner._attempt._media_ready.is_set())
    offer = client.receive()
    assert offer['type'] == 'desktop_screen_draft' and offer['body']['op'] == 'offer'
    dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).clicked()
    stop = client.receive()
    assert stop == dict(frame, body=dict(frame['body'], op='stop', session=offer['body']['session']))
    wait_for(lambda: ended == [DesktopScreenAttemptCleanup(ScreenRunCleanup(True, True, True), True)])
    assert not dialog.get_visible()
    ping(client)  # Exactly one terminal frame, no SEND and no parent loss.
