"""Ephemeral real WebKit worker probe, run with xvfb-run, never a user profile."""
import json
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlsplit

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib, Gio

web = Path(__file__).parents[1] / 'web'
context = WebKit2.WebContext.new_ephemeral()
security = context.get_security_manager()
for method in ('register_uri_scheme_as_local', 'register_uri_scheme_as_secure', 'register_uri_scheme_as_display_isolated'):
    getattr(security, method)('magnolie-organizer')


def serve(request):
    path = (web / urlsplit(request.get_uri()).path.lstrip('/')).resolve()
    if not path.is_relative_to(web.resolve()) or not path.is_file():
        request.finish_error(GLib.Error('Missing probe asset'))
        return
    data = path.read_bytes()
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data), mimetypes.guess_type(path)[0] or 'application/octet-stream')


context.register_uri_scheme('magnolie-organizer', serve)
view = WebKit2.WebView.new_with_context(context)
view.get_settings().set_enable_write_console_messages_to_stdout(True)
window = Gtk.Window()
window.set_default_size(980, 720)
window.add(view)
window.show_all()
result = []


def evaluated(obj, task, callback):
    try:
        callback(json.loads(obj.evaluate_javascript_finish(task).to_string()))
    except Exception as error:
        result.append({'error': str(error)})
        Gtk.main_quit()


def evaluate(script, callback):
    view.evaluate_javascript(script, -1, None, None, None, evaluated, callback)


def poll():
    def received(value):
        if value.get('pending'):
            GLib.timeout_add(100, poll)
        else:
            result.append(value)
            Gtk.main_quit()
    evaluate('JSON.stringify({ pending: [...OrganizerTest.icsRuntime.state.jobs.values()].some(v => v.status === "pending"), state: document.body.dataset.recurrenceState, error: OrganizerTest.icsRuntime.lastError, detail:window.probeFailure, ticks: window.probeTicks, jobs: [...OrganizerTest.icsRuntime.state.jobs.values()].map(v => ({ status:v.status, error:v.error, values:(v.result || []).map(v => new Date(v.icsStartUtc).toISOString()) })) })', received)
    return False


def loaded(_view, event):
    if event != WebKit2.LoadEvent.FINISHED:
        return
    evaluate('''(() => {
      App.init({daten:{}, neu:true, regional:{language:"en", timeZone:"UTC"}});
      const NativeWorker = Worker;
      window.Worker = class extends NativeWorker { constructor(...args) { super(...args); this.addEventListener("error", e => { window.probeFailure = [String(e.message), String(e.filename), e.lineno, String(e.error)]; }); } };
      window.probeTicks = 0; setInterval(() => window.probeTicks++, 5);
      OrganizerTest.icsRuntime("expand", {icsRoundtrip:["DTSTART;TZID=Europe/Berlin:20210301T090000", "DURATION:PT1S", "RRULE:FREQ=MINUTELY;INTERVAL=10;COUNT=400000"]}, [Date.parse("2026-09-07T07:00:00Z"), Date.parse("2026-09-07T07:20:00Z")]);
      return JSON.stringify({started:true});
    })()''', lambda _value: GLib.timeout_add(100, poll))


view.connect('load-changed', loaded)
view.load_uri('magnolie-organizer://app/index.html')
GLib.timeout_add_seconds(90, lambda: (result.append({'error': 'timeout'}), Gtk.main_quit(), False)[-1])
Gtk.main()
window.destroy()
print(json.dumps(result))
sys.exit(0 if result and result[0].get('state') == 'ready' and result[0].get('ticks', 0) > 0 and
         result[0]['jobs'][0]['values'] == ['2026-09-07T07:00:00.000Z', '2026-09-07T07:10:00.000Z', '2026-09-07T07:20:00.000Z'] else 1)
