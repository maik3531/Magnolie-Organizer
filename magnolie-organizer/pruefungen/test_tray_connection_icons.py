"""Actual native SVG raster and state selection; no real phone or GUI install."""
import base64
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import threading

import pytest
from test_tray_media_activity import product, ROOT, ui_methods


@pytest.mark.parametrize('notes,kde,color', [(False,False,'#d8b25c'), (True,False,'#ffffff'), (False,True,'#f7d777'), (True,True,'#ee9846')])
@pytest.mark.parametrize('sync', [False,True])
def test_native_book_flower_color_is_independent_of_sync_and_preserves_gold_frames(tmp_path, notes, kde, color, sync):
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    logo = ROOT / 'symbole/magnolie-organizer.svg'
    data = product.tray_medien_svg(logo, sync, False, notes, kde)
    root = ET.fromstring(data); ns = {'s':'http://www.w3.org/2000/svg'}
    cover = ET.fromstring(base64.b64decode(root.find('s:image', ns).get('href').split(',')[1]))
    flower = next(node for node in cover if node.get('transform', '').startswith('translate(121,127.5)'))
    assert flower.get('stroke') == color
    assert cover.find('s:rect[@x="42"]', ns).get('stroke') == '#d8b25c'
    assert (root.find('s:g[@id="sync"]', ns) is not None) is sync
    image = tmp_path / 'connection.svg';image.write_bytes(data)
    raster = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(image), 32, 32, True)
    assert (raster.get_width(),raster.get_height()) == (32,32)


def test_phone_replaces_entire_book_camera_replaces_only_flower_and_invalid_truthy_state_rejected():
    ns = {'s':'http://www.w3.org/2000/svg'}
    logo = ROOT / 'symbole/magnolie-organizer.svg'
    root = ET.fromstring(product.tray_medien_svg(logo, True, True, True, False, True))
    cover = ET.fromstring(base64.b64decode(root.find('s:image', ns).get('href').split(',')[1]))
    assert cover.find('s:g[@id="phone"]',ns) is not None
    assert cover.find('s:rect[@x="42"]',ns) is None
    assert root.find('s:g[@id="camera"]',ns) is None
    assert root.find('s:g[@id="sync"]',ns) is not None
    with pytest.raises(ValueError):product.tray_medien_svg(logo, notes='paired')


def test_native_connection_projection_ignores_paired_and_stale_discovery_flags():
    assert product.tray_verbindungsstand({'peers':[{'state':'paired'},{'state':'offline'}]}, {'paired':True,'reachable':True}) == (False,False)
    assert product.tray_verbindungsstand({'peers':[{'state':'online_wifi'}]}, {'connected':True,'count':1}) == (True,True)
    assert product.tray_verbindungsstand({'peers':[{'state':'online_bluetooth'}]}, {'connected':'true','count':1}) == (True,False)
    assert product.tray_verbindungsstand({}, {'connected':True,'count':0}) == (False,False)


def test_native_frontend_uses_live_reports_not_late_event_claims_and_keeps_original_when_disconnected(monkeypatch):
    methods = ui_methods('_tray_medien_aktualisieren', '_tray_medien_symbol_setzen')
    native = {'peers':[{'state':'offline'}], 'media_activity':{}}
    kde = {'connected':False,'count':0}; calls = []
    methods['tray_kde_verbindungsstand'] = lambda:dict(kde)
    methods['magnolie_logo_pfad'] = lambda **_:str(ROOT / 'symbole/magnolie-organizer.svg')
    indicator = SimpleNamespace(set_icon_full=lambda *args:calls.append(args))
    window = SimpleNamespace(_telefon=SimpleNamespace(report=lambda:native), _tray_indikator=indicator, _tray_art='appindicator')
    window._tray_zaehler_anzeigen = lambda:methods['_tray_medien_symbol_setzen'](window,*window._tray_medien)
    try:
        methods['_tray_medien_aktualisieren'](window);assert calls[-1][0] == 'magnolie-organizer'
        native['peers'][0]['state'] = 'online_wifi';methods['_tray_medien_aktualisieren'](window)
        assert window._tray_verbindungen == (True,False) and calls[-1][0].endswith('book-0-0-1-0-0.svg')
        kde.update(connected=True,count=1);methods['_tray_medien_aktualisieren'](window)
        assert calls[-1][0].endswith('book-0-0-1-1-0.svg')
        native['peers'][0]['state'] = 'offline';methods['_tray_medien_aktualisieren'](window)
        assert calls[-1][0].endswith('book-0-0-0-1-0.svg')
        kde.update(connected=False,count=0);methods['_tray_medien_aktualisieren'](window)
        assert calls[-1][0] == 'magnolie-organizer'
    finally:
        if getattr(window,'_tray_medien_ordner',None):window._tray_medien_ordner.cleanup()


def test_kde_connection_events_only_schedule_fresh_native_projection_not_payload_claims():
    methods = ui_methods('_kde_ereignis','_tray_medien_aktualisieren')
    queued = []; observed = []; native = {'connected':False,'count':0}
    methods['GLib'] = SimpleNamespace(idle_add=lambda callback,*args:queued.append((callback,args)))
    methods['tray_kde_verbindungsstand'] = lambda:dict(native)
    window = SimpleNamespace(_telefon=None)
    window._tray_zaehler_anzeigen = lambda:observed.append(window._tray_verbindungen)
    window._tray_medien_aktualisieren = lambda:methods['_tray_medien_aktualisieren'](window)
    methods['_kde_ereignis'](window,'connection_changed',{'connected':False})
    assert not observed
    native.update(connected=True,count=1)
    callback,args = queued.pop();assert callback(*args) is False
    assert observed == [(False,True)], 'A late disconnected event hid the actual current connection'
    methods['_kde_ereignis'](window,'connection_changed',{'connected':True})
    native.update(connected=False,count=0)
    callback,args = queued.pop();callback(*args)
    assert observed[-1] == (False,False), 'A stale event fabricated a connection'


@pytest.mark.parametrize('other_media',[False,True])
def test_actual_calendar_sync_worker_marks_real_activity_until_io_ends_without_hiding_other_owner(other_media):
    methods = ui_methods('_sync_arbeit','_tray_medien_aktualisieren')
    queued = []; observed = []; entered = threading.Event(); release = threading.Event()
    methods['GLib'] = SimpleNamespace(idle_add=lambda callback,*args:queued.append((callback,args)))
    for name in ('debug_einrichten','debug_notiz','debug_ausnahme'):methods[name] = lambda *args,**kwargs:None
    methods['tray_kde_verbindungsstand'] = lambda:{}
    media = {'synchronizing':False}; window = SimpleNamespace(_sync_laeuft=True,
        _telefon=SimpleNamespace(report=lambda:{'media_activity':media}))
    def work(_request):
        entered.set();assert release.wait(5);return {'ok':True}
    window._sync_ausfuehren = work
    window._tray_zaehler_anzeigen = lambda:observed.append(window._tray_medien)
    window._tray_medien_aktualisieren = lambda:methods['_tray_medien_aktualisieren'](window)
    worker = threading.Thread(target=methods['_sync_arbeit'],args=(window,{}))
    worker.start()
    try:
        assert entered.wait(5)
        callback,args = queued.pop(0);callback(*args)
        assert observed[-1] == (True,False)
        media['synchronizing'] = other_media;release.set();worker.join(5);assert not worker.is_alive()
        callback,args = queued.pop(0);callback(*args)
        assert window._sync_laeuft is False and observed[-1] == (other_media,False)
    finally:release.set();worker.join(5)
