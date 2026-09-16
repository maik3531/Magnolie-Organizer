"""Real geometry and DOM tests of both source frontends; no native bridge or profile."""
import json
import sys
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib

root = Path(__file__).resolve().parents[2]
script = Path(__file__).with_name('custom-designer-render.js').read_text()
results = []
for web in (root / 'magnolie-organizer-2.0.0/web', root / 'Magnolie-Organizer-Windows-2.0.0/app/web'):
    for width, height in ((1920, 1080), (1024, 768), (390, 844), (640, 480)):
        view = WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral())
        window = Gtk.Window()
        window.set_default_size(width, height)
        window.add(view)
        window.show_all()
        result = {'web': str(web), 'size': [width, height]}

        def evaluated(obj, task, _data):
            try:
                result.update(json.loads(obj.evaluate_javascript_finish(task).to_string()))
            except Exception as error:
                result['error'] = str(error)
            Gtk.main_quit()

        def loaded(_view, event):
            if event == WebKit2.LoadEvent.FINISHED:
                view.evaluate_javascript(script + '\nJSON.stringify(pruefeCustomDesigner())',
                                         -1, None, None, None, evaluated, None)

        view.connect('load-changed', loaded)
        view.load_uri((web / 'index.html').as_uri())
        timeout = GLib.timeout_add_seconds(30, lambda: (result.update(error='timeout'), Gtk.main_quit(), False)[-1])
        Gtk.main()
        GLib.source_remove(timeout)
        window.destroy()
        results.append(result)
print(json.dumps(results, indent=2))
sys.exit(int(any('error' in result for result in results)))
