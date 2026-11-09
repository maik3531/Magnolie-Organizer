"""Native-owner status and actual book-icon rendering, not connection timers."""
import ast
import base64
from pathlib import Path
from types import SimpleNamespace
import threading
import sys
import xml.etree.ElementTree as ET

import pytest
from modul_laden import quellmodul_laden
sys.path.insert(0, str(Path(__file__).parents[1] / 'bin'))
import magnolie_telefon as phone
import magnolie_hintergrund as background

ROOT = Path(__file__).parents[1]
product = quellmodul_laden('tray_media_activity', str(ROOT / 'bin/magnolie-organizer'))


def test_service_retains_other_real_owner_and_rejects_foreign_or_late_owner_events():
    service = phone.PhoneService.__new__(phone.PhoneService)
    service.lock = threading.RLock(); service._native_photo_activity = {}
    service._native_file_connections = {}; events = []
    service.callback = lambda kind, payload: events.append((kind, service._native_media_activity()))
    owners = [object(), object()]
    connections = [SimpleNamespace(_channel=object(), _album_worker=owner) for owner in owners]
    for connection in connections: service._native_file_connections[connection._channel] = connection
    service._native_photo_activity_changed(connections[0], object(), True)
    assert not events
    for connection, owner in zip(connections, owners):
        service._native_photo_activity_changed(connection, owner, True)
    service._native_photo_activity_changed(connections[0], owners[1], False)
    assert len(events) == 2
    service._native_photo_activity_changed(connections[0], owners[0], False)
    assert service._native_media_activity()['synchronizing'] is True
    service._native_photo_activity_changed(connections[0], owners[0], False)
    assert len(events) == 3 # A delayed duplicate END cannot clear the other worker.
    service._native_file_connections.clear() # Revocation is not actual I/O END.
    assert service._native_media_activity()['synchronizing'] is True
    service._native_photo_activity_changed(connections[1], owners[1], False)
    assert events[-1] == ('media_activity', {'synchronizing': False, 'camera': False})


@pytest.mark.parametrize('sync,camera', [(False, False), (True, False), (False, True), (True, True)])
def test_real_book_svg_replaces_flower_with_camera_keeps_sync_independent_and_renders(tmp_path, sync, camera):
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    logo = ROOT / 'symbole/magnolie-organizer.svg'
    data = product.tray_medien_svg(logo, sync, camera)
    tree = ET.fromstring(data); ns = {'s': 'http://www.w3.org/2000/svg'}
    image = tree.find('s:image', ns)
    embedded = base64.b64decode(image.attrib['href'].split(',', 1)[1])
    if not camera:assert embedded == logo.read_bytes()
    else:
        cover = ET.fromstring(embedded)
        assert not [node for node in cover if node.get('transform', '').startswith('translate(121,')]
        assert cover.find('s:rect[@x="42"]', ns) is not None, 'Replacing the flower must preserve the actual book frame'
    assert (tree.find('s:g[@id="sync"]', ns) is not None) is sync
    assert (tree.find('s:g[@id="camera"]', ns) is not None) is camera
    target = tmp_path / 'book.svg'; target.write_bytes(data)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(target), 32, 32, True)
    assert pixbuf.get_width() == pixbuf.get_height() == 32
    if sync or camera:
        baseline = tmp_path / 'idle.svg'; baseline.write_bytes(product.tray_medien_svg(logo))
        idle = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(baseline), 32, 32, True)
        assert pixbuf.get_pixels() != idle.get_pixels()


def ui_methods(*names):
    tree = ast.parse((ROOT / 'bin/magnolie-organizer').read_text())
    methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
               for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(methods) == len(names)
    namespace = dict(product.__dict__)
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<actual-tray-methods>', 'exec'), namespace)
    return namespace


@pytest.mark.parametrize('kind', ['appindicator', 'xapp', 'statusicon'])
def test_actual_frontend_reads_current_owner_status_and_preserves_notification_badge(kind, monkeypatch):
    names = ('_tray_medien_aktualisieren', '_tray_zaehler_anzeigen', '_tray_medien_symbol_setzen')
    methods = ui_methods(*names)
    methods['_'] = lambda text: text
    methods['ngettext'] = lambda single, plural, count: single if count == 1 else plural
    methods['magnolie_logo_pfad'] = lambda **_: str(ROOT / 'symbole/magnolie-organizer.svg')
    calls = []
    indicator = SimpleNamespace(**{name: lambda *args, name=name: calls.append((name, args))
        for name in ('set_icon_full', 'set_icon_name', 'set_from_file', 'set_from_icon_name', 'set_label', 'set_tooltip_text')})
    state = {'synchronizing': True, 'camera': True}
    window = SimpleNamespace(_telefon=SimpleNamespace(report=lambda: {'media_activity': dict(state)}),
        _tray_indikator=indicator, _tray_art=kind, _tray_einstellungen={'zaehler': True}, _tray_zaehler=7)
    for name in names: setattr(window, name, lambda *args, name=name: methods[name](window, *args))
    try:
        assert window._tray_medien_aktualisieren() is False
        assert window._tray_medien == (True, True)
        assert any('book-1-1-0-0-0.svg' in str(args) for _, args in calls)
        assert any('Synchronizing …' in str(args) and 'Phone camera active' in str(args) and '7 notifications' in str(args)
                   for name, args in calls if name == 'set_tooltip_text')
        if kind != 'statusicon': assert any(name == 'set_label' and args[0] == '7' for name, args in calls)
        state.update(synchronizing=False) # Stale END refresh still retains live camera.
        window._tray_medien_aktualisieren()
        assert window._tray_medien == (False, True)
        state.update(camera=False)
        window._tray_medien_aktualisieren()
        assert window._tray_medien == (False, False)
        assert any(args[0] == 'magnolie-organizer' for name, args in calls if name in ('set_icon_full', 'set_icon_name', 'set_from_icon_name'))
    finally:
        if getattr(window, '_tray_medien_ordner', None): window._tray_medien_ordner.cleanup()


def test_actual_daemon_ticket_and_frontend_refresh_use_live_state_not_queued_end():
    pending = []; tickets = []; refreshes = []
    glib = SimpleNamespace(idle_add=lambda function, *args: pending.append((function, args)))
    daemon = background.PhoneDaemonEvents(lambda: None, {}, SimpleNamespace(), glib,
        lambda event, payload: tickets.append((event, payload)) or True, lambda: True)
    daemon('media_activity', {})
    function, args = pending.pop(0); assert function(*args) is False
    assert tickets[0][0] == 'phone_event'
    event = daemon.take(tickets[0][1]['ticket'])
    assert event == {'event': 'media_activity', 'payload': {}}
    methods = ui_methods('_telefon_ereignis', '_tray_medien_aktualisieren')
    methods['GLib'] = glib
    state = {'synchronizing': True, 'camera': False}
    window = SimpleNamespace(_telefon=SimpleNamespace(report=lambda: {'media_activity': dict(state)}))
    window._tray_zaehler_anzeigen = lambda: refreshes.append(window._tray_medien)
    window._tray_medien_aktualisieren = lambda: methods['_tray_medien_aktualisieren'](window)
    methods['_telefon_ereignis'](window, event['event'], {'synchronizing': False})
    assert not refreshes # GTK updates are marshalled, never made on the worker lane.
    function, args = pending.pop(0); function(*args)
    assert refreshes == [(True, False)] # Late END did not hide another live owner.


def test_icon_render_failure_does_not_suppress_existing_badge_or_tooltip():
    methods = ui_methods('_tray_zaehler_anzeigen')
    methods['_'] = lambda value: value
    methods['ngettext'] = lambda single, plural, count: plural
    calls = []
    methods['debug_ausnahme'] = lambda *args, **kwargs: calls.append('render-error')
    def unavailable(*args): raise OSError('fixture missing logo')
    window = SimpleNamespace(_tray_indikator=SimpleNamespace(set_label=lambda *args: calls.append(args),
        set_tooltip_text=lambda value: calls.append(value)), _tray_art='appindicator',
        _tray_einstellungen={'zaehler': True}, _tray_zaehler=3, _tray_medien=(True, False),
        _tray_medien_symbol_setzen=unavailable)
    methods['_tray_zaehler_anzeigen'](window)
    assert 'render-error' in calls and ('3', '99+') in calls
    assert any(isinstance(value, str) and '3 notifications' in value for value in calls)


def test_phone_status_refresh_after_service_replacement_does_not_keep_old_activity_icon():
    methods = ui_methods('_telefon_stand_melden', '_tray_medien_aktualisieren')
    queued = []; calls = []
    methods['GLib'] = SimpleNamespace(idle_add=lambda function: queued.append(function))
    methods['_kdeconnect_backend'] = lambda callback: None
    window = SimpleNamespace(_telefon=SimpleNamespace(report=lambda: {'media_activity': {'synchronizing': False, 'camera': False}},
        replay_personal_sync=lambda: None), _tray_medien=(True, False),
        _kde_ereignis=lambda *args: None, _kde_legacy_einstellungen_migrieren=lambda: None,
        antwort=lambda *args: calls.append('status'), _telefon_bericht=lambda: {},
        _tray_telefone_aktualisieren=lambda: calls.append('menu'))
    window._tray_zaehler_anzeigen = lambda: calls.append(window._tray_medien)
    window._tray_medien_aktualisieren = lambda: methods['_tray_medien_aktualisieren'](window)
    methods['_telefon_stand_melden'](window)
    assert window._tray_medien == (True, False)
    assert queued.pop()() is False
    assert window._tray_medien == (False, False) and calls == ['status', 'menu', (False, False)]
