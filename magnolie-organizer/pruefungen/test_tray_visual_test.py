"""Actual native visual lease and GTK glue: no permission/transport mutation."""
from types import SimpleNamespace
import pytest
from test_tray_media_activity import product, ui_methods


def request(**changes):
    return dict(cmd='tray_darstellung_test', connection='both', mode='camera', sync=True, **changes)


def test_saved_developer_gate_typed_state_expiry_and_new_book():
    for data in (None, [], {}, {'einstellungen':[]}, {'einstellungen':{'allgemein':[]}}, {'einstellungen':{'allgemein':{'entwicklermodus':1}}}):
        assert product.tray_entwicklermodus_gespeichert(data,False) is False
    now = [100.0]; owner = {}; test = product.TrayVisualTest(lambda:now[0])
    with pytest.raises(ValueError):test.start(request(), False, owner)
    for connection in ('none', 'notes', 'kde', 'both'):
        for mode in ('flower', 'camera', 'phone'):
            for sync in (False, True):
                value = request();value.update(connection=connection,mode=mode,sync=sync)
                now[0] = 100;test.start(value, True, owner)
                assert test.current(True, owner) == (sync, mode == 'camera', connection in ('notes','both'), connection in ('kde','both'), mode == 'phone')
                now[0] = 159.999;assert test.current(True, owner) is not None
                now[0] = 160;assert test.current(True, owner) is None
    test.start(request(), True, owner);assert test.current(True, {}) is None
    test.start(request(), True, owner);assert test.current(False, owner) is None
    for changes in ({'connection':'paired'},{'mode':'live_camera'},{'sync':1},{'ready':True}):
        value = request();value.update(changes)
        with pytest.raises(ValueError):test.start(value,True,owner)
        assert test.state is None


def test_actual_gtk_gate_uses_native_book_and_never_changes_real_activity_or_connection():
    methods = ui_methods('_tray_test_stand','_tray_test_setzen','_tray_test_tick')
    methods['TrayVisualTest'] = product.TrayVisualTest
    timers = {};removed = [];responses = [];draws = []
    def add(_interval, callback):timers[len(timers)+1]=callback;return len(timers)
    methods['GLib'] = SimpleNamespace(timeout_add=add,source_remove=lambda source:removed.append(source))
    data = {'einstellungen':{'allgemein':{'entwicklermodus':False}}}
    window = SimpleNamespace(_aktuelle_daten=data,_gesperrt=False,_tray_medien=(False,False),_tray_verbindungen=(False,False),
        antwort=lambda *args:responses.append(args),_tray_zaehler_anzeigen=lambda:draws.append(True))
    window._tray_test_stand=lambda:methods['_tray_test_stand'](window)
    window._tray_test_tick=lambda:methods['_tray_test_tick'](window)
    methods['_tray_test_setzen'](window,request())
    assert responses[-1][1]['ok'] is False and not timers
    data['einstellungen']['allgemein']['entwicklermodus']=True
    methods['_tray_test_setzen'](window,request())
    assert responses[-1][1]['active'] is True and len(timers)==1
    assert window._tray_test_stand()==(True,True,True,True,False)
    assert window._tray_medien==(False,False) and window._tray_verbindungen==(False,False)
    window._gesperrt=True
    assert window._tray_test_tick() is False and responses[-1][1]['active'] is False
    window._gesperrt=False;methods['_tray_test_setzen'](window,request())
    methods['_tray_test_setzen'](window,{'cmd':'tray_darstellung_test_ende'},clear=True)
    assert window._tray_test_stand() is None and removed


def test_actual_os_icon_override_restores_current_real_owner_and_keeps_badge():
    from test_tray_media_activity import ROOT
    methods=ui_methods('_tray_test_stand','_tray_medien_symbol_setzen','_tray_zaehler_anzeigen')
    now=[100.0];data={'einstellungen':{'allgemein':{'entwicklermodus':True}}}
    test=product.TrayVisualTest(lambda:now[0]);value=request();value.update(connection='both',mode='phone')
    test.start(value,True,data);calls=[]
    methods['magnolie_logo_pfad']=lambda **_:str(ROOT/'symbole/magnolie-organizer.svg')
    methods['_']=lambda value:value;methods['ngettext']=lambda single,plural,count:plural
    indicator=SimpleNamespace(set_icon_full=lambda *args:calls.append(('icon',args)),
        set_label=lambda *args:calls.append(('label',args)),set_tooltip_text=lambda *args:calls.append(('tooltip',args)))
    window=SimpleNamespace(_aktuelle_daten=data,_gesperrt=False,_tray_darstellung_test=test,_tray_indikator=indicator,
        _tray_art='appindicator',_tray_einstellungen={'zaehler':True},_tray_zaehler=7,
        _tray_verbindungen=(True,False),_tray_medien=(False,False),_tray_spiegelung=False)
    for name in ('_tray_test_stand','_tray_medien_symbol_setzen','_tray_zaehler_anzeigen'):
        setattr(window,name,lambda *args,name=name:methods[name](window,*args))
    try:
        window._tray_zaehler_anzeigen()
        assert any(name=='icon' and args[0].endswith('book-1-0-1-1-1.svg') for name,args in calls)
        assert any(name=='label' and args[0]=='TEST · 7' for name,args in calls)
        assert window._tray_verbindungen==(True,False) and window._tray_medien==(False,False)
        now[0]=160;window._tray_zaehler_anzeigen()
        assert any(name=='icon' and args[0].endswith('book-0-0-1-0-0.svg') for name,args in calls)
        assert calls[-2][1][0]=='7' and calls[-1][1][0].startswith('Magnolie')
    finally:
        if getattr(window,'_tray_medien_ordner',None):window._tray_medien_ordner.cleanup()
