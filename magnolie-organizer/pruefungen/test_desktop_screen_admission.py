"""Real GTK approval and signed PhoneService test parent; no compositor capture."""

from threading import Event
from time import time_ns
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_desktop_screen_dispatch import connected, native, ping, request
from test_phone_screen_window import GLib, Gtk, PhoneScreenSessionLock, organizer_hooks, wait_for
import magnolie_desktop_screen_admission as admission
import magnolie_desktop_screen_attempt as runs
import magnolie_desktop_screen_control as control
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


def show(owner, client, wire_mode=2):
    frame = request()
    frame['body']['mode'] = wire_mode
    client.send(frame)
    wait_for(lambda: owner._dialog is not None and owner._dialog.get_visible())
    return frame, owner._dialog


@pytest.mark.parametrize('native', [True], indirect=True)
def test_mirror_organizer_entry_checks_original_after_provider_read(connected, monkeypatch):
    from gi.repository import Gio
    import magnolie_desktop_screen_portal as portal

    service, peer, client = connected
    app = organizer_hooks()
    app._telefon = service
    app._private_desktop_mirror_ui = True
    app._gesperrt = app._beenden_angefragt = app._wirklich_beenden = False
    monitor = app._phone_screen_session_lock = PhoneScreenSessionLock()
    monitor._lease = object()
    replies = []
    app.antwort = lambda target, value: replies.append((target, value))
    bus = object()
    started, resume = Event(), Event()
    factory = Mock()
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', factory)
    monkeypatch.setattr(Gio, 'bus_get_sync', lambda *_: bus)

    def provider(actual_bus, cancellable):
        assert actual_bus is bus and not cancellable.is_cancelled()
        started.set()
        assert resume.wait(2)
        return DesktopScreenProvider(':1.245', MONITOR, False, 0, 6)

    monkeypatch.setattr(portal, 'read_desktop_screen_provider', provider)
    app.show_all()

    def command(action, **extra):
        app._desktop_mirror_ui(dict(cmd=f'telefon_desktop_mirror_{action}', peer=peer['device_id'], requestId=action, **extra))

    try:
        command('stand')
        assert replies[-1][1]['desktopMirror'] == dict(included=True, active=False)
        assert not started.is_set() and service._desktop_screen_draft_dispatch._owner is None
        command('arm')
        assert started.wait(2)
        app.hide(); app.show_all()
        resume.set()
        wait_for(lambda: len(replies) == 2)
        assert not replies[-1][1]['ok'] and service._desktop_screen_draft_dispatch._owner is None

        started.clear(); resume.clear()
        command('arm')
        assert started.wait(2)
        with service.lock:
            service.connection_transports[peer['device_id']] = 'bluetooth'
        try:
            resume.set()
            wait_for(lambda: len(replies) == 3)
            assert not replies[-1][1]['ok'] and service._desktop_screen_draft_dispatch._owner is None
        finally:
            with service.lock:
                service.connection_transports[peer['device_id']] = 'wifi'

        command('arm')
        wait_for(lambda: len(replies) == 4)
        assert replies[-1][1]['ok'] and replies[-1][1]['desktopMirror']['active']
        first_lease = replies[-1][1]['desktopMirror'].get('lease', 'old')
        owner = app._desktop_mirror_owner
        assert owner._original.channel is client.channel
        factory.assert_not_called()
        _, dialog = show(owner, client, 1)
        dialog.response(Gtk.ResponseType.CANCEL)
        wait_for(lambda: app._desktop_mirror_owner is None)
        command('arm')
        wait_for(lambda: len(replies) == 5)
        second = app._desktop_mirror_owner
        assert second is not None and second is not owner
        command('stop', lease=first_lease)
        assert not second._stopping.is_set() and not replies[-1][1]['ok']
        second_lease = replies[4][1]['desktopMirror']['lease']
        assert second_lease and second_lease != first_lease
        command('stop')
        assert not second._stopping.is_set() and not replies[-1][1]['ok']
        command('stop', lease=second_lease)
        assert replies[-1][1]['ok']
        wait_for(lambda: app._desktop_mirror_owner is None)
        factory.assert_not_called()
        ping(client)
    finally:
        resume.set()
        app._desktop_mirror_stop()
        wait_for(lambda: getattr(app, '_desktop_mirror_pending', None) is None and
                 getattr(app, '_desktop_mirror_owner', None) is None)
        app.destroy()
        monitor.close()


@pytest.fixture
def mirror_app(connected, monkeypatch):
    service, peer, _ = connected
    app = organizer_hooks()
    app._telefon = service
    app._private_desktop_mirror_ui = True
    app._gesperrt = app._beenden_angefragt = app._wirklich_beenden = False
    lock = app._phone_screen_session_lock = PhoneScreenSessionLock()
    lock._lease = object()
    replies = []
    app.antwort = lambda target, value: replies.append(value) if target == 'App.kdeMedien' else None
    factory = Mock()
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', factory)
    app.show_all()

    def command(action, **extra):
        count = len(replies)
        app._desktop_mirror_ui(dict(cmd=f'telefon_desktop_mirror_{action}', peer=peer['device_id'], requestId=action, **extra))
        wait_for(lambda: len(replies) > count)
        return replies[-1]

    try:
        yield app, command, factory
    finally:
        app._desktop_mirror_stop()
        if factory.called:
            owner = app._desktop_mirror_owner
            if owner is not None and owner._cleanup is None:
                factory.call_args.kwargs['ended'](DesktopScreenAttemptCleanup(ScreenRunCleanup(True, True, True), True))
            if owner is not None:
                wait_for(lambda: owner._terminal)
        wait_for(lambda: getattr(app, '_desktop_mirror_pending', None) is None)
        app.destroy()
        lock.close()


@pytest.mark.parametrize('native', [True], indirect=True)
@pytest.mark.parametrize('unavailable', [None, DesktopScreenProvider(),
    DesktopScreenProvider(':1.245', MONITOR, False, 0, 2), DesktopScreenProvider(':1.245', WINDOW, True, 0, 6)])
def test_mirror_reports_unavailable_portal_without_arming(connected, mirror_app, monkeypatch, unavailable):
    from gi.repository import Gio
    import magnolie_desktop_screen_portal as portal

    service, _, client = connected
    app, command, factory = mirror_app
    bus = None if unavailable is None else object()
    monkeypatch.setattr(Gio, 'bus_get_sync', lambda *_: bus)
    query = Mock(return_value=unavailable)
    monkeypatch.setattr(portal, 'read_desktop_screen_provider', query)

    assert not command('stand')['desktopMirror']['active']
    query.assert_not_called()
    result = command('arm')
    assert not result['ok'] and result['desktopMirror'] == dict(included=True, active=False, status='portal_unavailable')
    assert getattr(app, '_desktop_mirror_owner', None) is None and app._desktop_mirror_lease is None
    assert service._desktop_screen_draft_dispatch._owner is None
    query.assert_called_once()
    factory.assert_not_called()
    ping(client)


@pytest.mark.parametrize('native', [True], indirect=True)
@pytest.mark.parametrize('transport,local,confirmed', [
    (True, ScreenRunCleanup(True, True, True), True),
    (False, ScreenRunCleanup(True, True, True), False),
    (True, ScreenRunCleanup(False, True, True), False),
    (True, ScreenRunCleanup(True, False, True), False),
    (True, ScreenRunCleanup(True, True, False), False),
])
def test_mirror_stop_reports_drain_and_retains_uncertain_owner(connected, mirror_app, monkeypatch, transport, local, confirmed):
    from gi.repository import Gio
    import magnolie_desktop_screen_portal as portal

    service, _, client = connected
    app, command, factory = mirror_app
    monkeypatch.setattr(Gio, 'bus_get_sync', lambda *_: object())
    query = Mock(return_value=DesktopScreenProvider(':1.245', MONITOR, False, 0, 6))
    monkeypatch.setattr(portal, 'read_desktop_screen_provider', query)
    result = command('arm')
    assert result['ok']
    lease = result['desktopMirror']['lease']
    owner = app._desktop_mirror_owner
    _, dialog = show(owner, client, 1)
    dialog.response(Gtk.ResponseType.ACCEPT)
    factory.return_value.begin.assert_called_once()
    result = command('stop', lease=lease)
    stopping = dict(included=True, active=True, status='stopping')
    assert result['ok'] and result['desktopMirror'] == stopping
    result = command('arm')
    assert not result['ok'] and result['desktopMirror'] == stopping
    factory.return_value.stop.assert_called_once()
    factory.call_args.kwargs['ended'](DesktopScreenAttemptCleanup(local, transport))
    wait_for(lambda: owner._terminal)
    dispatch = service._desktop_screen_draft_dispatch
    if confirmed:
        assert app._desktop_mirror_owner is None and dispatch._owner is None
        assert command('stand')['desktopMirror'] == dict(included=True, active=False)
        assert command('arm')['ok']
    else:
        held = dict(included=True, active=True, status='cleanup_unconfirmed')
        assert app._desktop_mirror_owner is owner and dispatch._owner is owner._original
        assert command('stand')['desktopMirror'] == held
        assert not command('stop', lease=lease)['ok']
        result = command('arm')
        assert not result['ok'] and result['desktopMirror'] == held
        # A replacement service would have a different dispatch slot. The
        # Organizer must still refuse before selecting a reader on that service.
        successor = object.__new__(type(service))
        successor.private_desktop_mirror_candidate = Mock(side_effect=AssertionError('new candidate selected'))
        app._telefon = successor
        try:
            result = command('arm')
            assert not result['ok'] and result['desktopMirror'] == held
            successor.private_desktop_mirror_candidate.assert_not_called()
            assert app._desktop_mirror_owner is owner
        finally:
            app._telefon = service
        query.assert_called_once()
        factory.return_value.stop.assert_called_once()
    ping(client)


@pytest.mark.parametrize('native,private_mirror', [(False, False), (True, True)], indirect=['native'])
def test_private_native_mirror_entry_keeps_consent_and_never_resolves_replacement(connected, monkeypatch, private_mirror):
    service, peer, client = connected
    assert Gtk.init_check()[0], 'run under Xvfb or an isolated GTK display'
    factory = Mock()
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', factory)
    parent = Gtk.Window()
    parent.show_all()
    lock = PhoneScreenSessionLock()
    lock._lease = object()
    ended = []
    peer_id = peer['device_id']
    transport = service.connection_transports
    owner = None

    def begin(selection=None, mode='monitor'):
        return service.begin_private_desktop_mirror(selection, mode=mode,
            provider=DesktopScreenProvider(':1.245', MONITOR | WINDOW, True, 0, 6), bus=object(),
            parent=parent, session_lock=lock, ended=ended.append)

    try:
        assert not service.native_screen_included  # No phone → PC capability change.
        assert (service._desktop_screen_draft_dispatch is not None) == private_mirror
        if not private_mirror:
            with pytest.raises(PermissionError, match='private_mirror_unavailable'):
                service.private_desktop_mirror_candidate(peer_id)
            with pytest.raises(PermissionError, match='private_mirror_unavailable'):
                begin()
            ping(client)
            return
        selection = service.private_desktop_mirror_candidate(peer_id)
        assert selection.channel is client.channel and service._desktop_screen_draft_dispatch._owner is None
        with pytest.raises(PermissionError, match='private_mirror_unavailable'):
            begin(selection, 'extend')
        with pytest.raises(PermissionError, match='original_selection_required'):
            begin()
        with service.lock:
            service.connections[peer_id] = object()  # A different active route, not the selected one.
        try:
            with pytest.raises(PermissionError, match='reader_retired'):
                begin(selection)
        finally:
            with service.lock:
                service.connections[peer_id] = client.channel
        with service.lock:
            transport[peer_id] = 'bluetooth'
        try:
            with pytest.raises(PermissionError, match='reader_retired'):
                begin(selection)
        finally:
            with service.lock:
                transport[peer_id] = 'wifi'
        with service.lock:
            original_generation = service._generation
            service._generation += 1
        try:
            with pytest.raises(PermissionError, match='reader_retired'):
                begin(selection)
            assert service._desktop_screen_draft_dispatch._owner is None
        finally:
            with service.lock:
                service._generation = original_generation
        owner = begin(selection)
        assert owner._parent_handle == f'x11:{parent.get_window().get_xid():x}'
        late = request()
        client.send(dict(late, body=dict(late['body'], op='prepared', mode=1,
            session='12' * 16, transcript='ab' * 32)))
        ping(client)
        assert owner._pending is None and owner._dialog is None
        _, dialog = show(owner, client, 1)
        factory.assert_not_called()
        dialog.get_default_widget().clicked()
        wait_for(lambda: ended == [None])
        factory.assert_not_called()
        ping(client)
    finally:
        if owner is not None:
            owner.close()
            wait_for(lambda: owner._terminal)
        parent.destroy()
        lock.close()


@pytest.mark.parametrize('native', [True], indirect=True)
def test_private_mirror_parent_disappearing_before_accept_never_starts_portal(connected, monkeypatch):
    service, peer, client = connected
    assert Gtk.init_check()[0], 'run under Xvfb or an isolated GTK display'
    factory = Mock()
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', factory)
    parent = Gtk.Window()
    parent.show_all()
    lock = PhoneScreenSessionLock()
    lock._lease = object()
    owner = None
    ended = []

    def begin():
        selection = service.private_desktop_mirror_candidate(peer['device_id'])
        return service.begin_private_desktop_mirror(selection, mode='window',
            provider=DesktopScreenProvider(':1.245', WINDOW, False, 0, 6), bus=object(),
            parent=parent, session_lock=lock, ended=ended.append)

    try:
        owner = begin()
        _, dialog = show(owner, client, 1)
        parent.hide()
        parent.show_all()  # Do not let a quick hide/show resurrect the first request.
        dialog.response(Gtk.ResponseType.ACCEPT)
        wait_for(lambda: owner._terminal)
        assert ended == [None]
        factory.assert_not_called()
        ping(client)
        owner = begin()  # Only a new native action can re-arm.
        assert owner._pending is None
        _, new_dialog = show(owner, client, 1)
        new_dialog.response(Gtk.ResponseType.ACCEPT)
        factory.assert_called_once()
        assert factory.call_args.kwargs['parent_window'] == f'x11:{parent.get_window().get_xid():x}'
        factory.return_value.begin.assert_called_once()
        parent.hide()
        factory.return_value.stop.assert_not_called()  # Hiding is not an active stop.
    finally:
        if owner is not None:
            owner.close()
            if factory.called and owner._cleanup is None:
                factory.call_args.kwargs['ended'](DesktopScreenAttemptCleanup(ScreenRunCleanup(True, True, True), True))
            wait_for(lambda: owner._terminal)
        parent.destroy()
        lock.close()


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


@pytest.mark.parametrize(('mode', 'wire_mode'), [('extend', 2), ('monitor', 1)])
def test_confirm_then_native_stop_waits_for_exact_drain(connected, gtk_owner, mode, wire_mode):
    _, _, client = connected
    arm, _, _, factory, attempt, ended = gtk_owner
    owner = arm(mode)
    frame, dialog = show(owner, client, wire_mode)
    setup = owner._pending[1]
    factory.assert_not_called()
    dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).clicked()
    attempt.begin.assert_called_once()
    call = factory.call_args
    assert call.args[:2] == (client.channel, frame['body'])
    assert call.kwargs['mode'] == mode and call.kwargs['deadline'] == setup.deadline
    assert call.kwargs['setup'] is setup
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


@pytest.mark.parametrize('local', [ScreenRunCleanup(False, True, True),
                                  ScreenRunCleanup(True, True, True, virtual_start_submitted=True)])
def test_exit_with_unconfirmed_portal_or_virtual_output_keeps_slot(connected, gtk_owner, local):
    service, peer, client = connected
    arm, _, parent, factory, attempt, ended = gtk_owner
    owner = arm()
    _, dialog = show(owner, client)
    dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).clicked()
    parent.destroy()
    attempt.stop.assert_called_once()
    assert not dialog.get_visible() and not owner._terminal
    cleanup = DesktopScreenAttemptCleanup(local, True)
    factory.call_args.kwargs['ended'](cleanup)
    wait_for(lambda: ended == [cleanup])
    with pytest.raises(PermissionError, match='reader_busy'):
        service._desktop_screen_draft_dispatch.attach(peer['device_id'], client.channel, lambda *_: None)
    ping(client)


@pytest.mark.parametrize('wall_step', [-60, 0, 60])
def test_local_stop_after_offer_before_phone_approval_is_terminal(connected, gtk_owner, monkeypatch, wall_step):
    _, _, client = connected
    arm, _, _, _, _, ended = gtk_owner
    monkeypatch.setattr(admission, 'DesktopScreenDraftAttempt', runs.DesktopScreenDraftAttempt)
    monkeypatch.setattr(runs, 'DesktopScreenLocalRun', SyntheticLocalRun)
    owner = arm()
    frame, dialog = show(owner, client)
    # Simulate a system clock correction only after the original intake.
    monkeypatch.setattr(control, 'time_ns', lambda: time_ns() + wall_step * 10**9)
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
