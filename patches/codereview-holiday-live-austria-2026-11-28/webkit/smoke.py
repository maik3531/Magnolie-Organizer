import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk,WebKit2,GLib
print("ENGINE",WebKit2.get_major_version(),WebKit2.get_minor_version(),WebKit2.get_micro_version(),flush=True)
v=WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral())
v.get_settings().set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
w=Gtk.Window();w.set_default_size(800,600);w.add(v);w.show_all()
def loaded(view,event):
 if event == WebKit2.LoadEvent.FINISHED:
  print("LOADED",flush=True);Gtk.main_quit()
v.connect("load-changed",loaded)
v.load_html("<!doctype html><title>Owned probe</title><p>WebKit isolated test</p>",None)
GLib.timeout_add_seconds(15,lambda:(Gtk.main_quit(),False)[1]);Gtk.main()
