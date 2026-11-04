"""#378: actual GTK popup ownership/geometry in an explicitly isolated display."""
import ast
import gc
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('MAGNOLIE_NATIVE_POPUP_TEST')!='1',
    reason='Actual popup probes require the explicit isolated Xvfb lane')


@pytest.fixture
def popup(tmp_path,monkeypatch):
    for key in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
        monkeypatch.setenv(key,str(tmp_path))
    monkeypatch.setenv('GSETTINGS_BACKEND','memory')
    monkeypatch.setenv('NO_AT_BRIDGE','1')
    monkeypatch.delenv('DBUS_SESSION_BUS_ADDRESS',raising=False)
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0');gi.require_version('GdkPixbuf','2.0')
    from gi.repository import Gtk,Gdk,GdkPixbuf,GLib
    assert Gtk.init_check()[0], 'The explicit native lane must have a working isolated display'
    source=Path(__file__).resolve().parents[1]/'bin/magnolie-organizer'
    tree=ast.parse(source.read_text())
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('magnolie_meldung','_meldung_platzieren')]
    css=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='MAGNOLIE_MELDUNG_STIL' for target in node.targets))
    namespace=dict(Gtk=Gtk,Gdk=Gdk,GdkPixbuf=GdkPixbuf,GLib=GLib,FENSTER_TITEL='Magnolie isolated popup fixture',
        MAGNOLIE_MELDUNG_STIL=css,anzeige_bereit=lambda:True,_=lambda value:value,
        organizer_starten=lambda:pytest.fail('The probe must not launch the installed organizer'))
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),namespace)
    add_ms=GLib.timeout_add;add_seconds=GLib.timeout_add_seconds;sources=[];seconds_sources=[]
    def milliseconds(delay,callback,*args):
        result=add_ms(delay,callback,*args);sources.append(result);return result
    def seconds(delay,callback,*args):
        # Only accelerate the ordinary 60-second reminder timeout. It is still
        # a real GLib source/callback and the actual GTK main-loop implementation.
        result=add_ms(2000,callback,*args) if delay==60 else add_seconds(delay,callback,*args)
        sources.append(result);seconds_sources.append(result);return result
    monkeypatch.setattr(GLib,'timeout_add',milliseconds);monkeypatch.setattr(GLib,'timeout_add_seconds',seconds)
    def windows():return [window for window in Gtk.Window.list_toplevels() if window.get_title()==namespace['FENSTER_TITEL']]
    def children(widget):
        yield widget
        for child in widget.get_children() if hasattr(widget,'get_children') else ():
            yield from children(child)
    def close_current():
        visible=[window for window in windows() if window.get_visible()]
        assert len(visible)==1
        next(widget for widget in children(visible[0]) if isinstance(widget,Gtk.Button) and widget.get_label()=='Close').emit('clicked')
        return False
    def pump(ms=30):
        loop=GLib.MainLoop();milliseconds(ms,lambda:(loop.quit(),False)[1]);loop.run()
    namespace['magnolie_meldung'].seconds_sources=seconds_sources
    try:yield namespace['magnolie_meldung'],Gtk,GLib,windows,close_current,pump
    finally:
        for window in windows():window.destroy()
        for identifier in sources:
            if GLib.MainContext.default().find_source_by_id(identifier) is not None:GLib.source_remove(identifier)
        while Gtk.events_pending():Gtk.main_iteration_do(False)


@pytest.mark.parametrize('timeout',[0,60])
def test_embedded_popup_stays_owned_through_python_gc_until_explicit_close(popup,timeout):
    show,Gtk,GLib,windows,close,pump=popup;closed=[]
    assert show('Fixture','Fixture reminder',wartezeit=timeout,eigene_schleife=False,bei_schliessen=lambda:closed.append(True))
    pump()
    for _ in range(3):gc.collect()
    pump(10)
    assert not closed and sum(window.get_visible() for window in windows())==1
    close();assert closed==[True]
    assert all(GLib.MainContext.default().find_source_by_id(identifier) is None for identifier in show.seconds_sources)


def test_old_appointment_timer_cannot_close_following_persistent_anniversary_loop(popup):
    show,Gtk,GLib,windows,close,pump=popup
    GLib.timeout_add(20,close)
    assert show('Appointment fixture','Fixture appointment',wartezeit=60,eigene_schleife=True)
    assert all(GLib.MainContext.default().find_source_by_id(identifier) is None for identifier in show.seconds_sources)
    explicit=[]
    def close_anniversary():explicit.append(True);return close()
    GLib.timeout_add(2300,close_anniversary)
    assert show('Anniversary fixture','Fixture anniversary',wartezeit=0,eigene_schleife=True)
    assert explicit==[True], 'A timer from the closed ordinary popup ended a different persistent popup'


def test_positive_appointment_timeout_still_closes_its_own_popup_and_cleans_sources(popup):
    show,Gtk,GLib,windows,close,pump=popup;closed=[]
    assert show('Appointment fixture','Fixture ordinary timeout',wartezeit=60,eigene_schleife=True,
        bei_schliessen=lambda:closed.append(True))
    assert closed==[True] and not windows()
    assert all(GLib.MainContext.default().find_source_by_id(identifier) is None for identifier in show.seconds_sources)


def test_expiring_outer_popup_does_not_quit_nested_persistent_popup(popup):
    show,Gtk,GLib,windows,close,pump=popup;first=[];second=[];explicit=[];failures=[]
    def widgets(widget):
        yield widget
        for child in widget.get_children() if hasattr(widget,'get_children') else ():
            yield from widgets(child)
    def find(title):
        return next((window for window in windows() if any(isinstance(widget,Gtk.Label) and widget.get_text()==title
            for widget in widgets(window))),None)
    def check_owner():
        if first!=[True] or second or find('Persistent nested fixture') is None:
            failures.append('The timed outer popup affected the persistent nested popup')
        return False
    def close_second():
        window=find('Persistent nested fixture')
        if window is None:failures.append('Persistent popup disappeared without its Close action')
        else:
            explicit.append(True)
            next(widget for widget in widgets(window) if isinstance(widget,Gtk.Button) and widget.get_label()=='Close').emit('clicked')
        return False
    def launch_second():
        show('Persistent nested fixture','Fixture anniversary',wartezeit=0,eigene_schleife=True,bei_schliessen=lambda:second.append(True))
        return False
    def guard():
        failures.append('Bounded native popup guard was needed')
        for window in windows():window.destroy()
        if Gtk.main_level()>0:Gtk.main_quit()
        return True
    GLib.timeout_add(30,launch_second);GLib.timeout_add(2100,check_owner);GLib.timeout_add(2300,close_second)
    GLib.timeout_add(4000,guard)
    assert show('Timed outer fixture','Fixture appointment',wartezeit=60,eigene_schleife=True,bei_schliessen=lambda:first.append(True))
    assert first==second==explicit==[True] and not failures,failures
    assert not windows()


@pytest.mark.parametrize('body',['Fixture appointment','Fixture anniversary\nFixture day\nFixture years'])
def test_actual_magnolie_frame_has_equal_top_and_bottom_after_allocation(popup,body):
    show,Gtk,GLib,windows,close,pump=popup
    assert show('Fixture',body,wartezeit=0,eigene_schleife=False)
    pump();window=windows()[0]
    frame=window.get_child();paper=frame.get_children()[0]
    def borders():
        rect=paper.get_allocation()
        return dict(top=rect.y,bottom=frame.get_allocated_height()-rect.y-rect.height,
            window_height=window.get_allocated_height(),paper_height=rect.height)
    before=borders()
    assert before['top']==before['bottom'],before
    window.resize(window.get_allocated_width(),window.get_allocated_height()+43);pump()
    after=borders()
    assert after['top']==after['bottom'],after
    image=show.__globals__['Gdk'].pixbuf_get_from_window(window.get_window(),0,0,
        window.get_allocated_width(),window.get_allocated_height())
    assert image is not None
    data=image.get_pixels();stride=image.get_rowstride();channels=image.get_n_channels();x=image.get_width()//2
    def color(y):
        offset=y*stride+x*channels
        return tuple(data[offset:offset+3])
    leather=color(1);paper_color=color(5)
    assert leather==color(image.get_height()-2)
    assert paper_color==color(image.get_height()-6)
    assert sum(paper_color)>sum(leather)+300, (leather,paper_color)
    close()
