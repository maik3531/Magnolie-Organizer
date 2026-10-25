"""Real ephemeral WebKit canvas/QR dialog probe; no decoded content is logged."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import cv2
import numpy
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib, Gio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'magnolie-organizer/bin'))
from magnolie_asset import read_asset

web = ROOT / (sys.argv[1] if len(sys.argv) == 2 else 'magnolie-organizer/web')
image = read_asset(str(web / 'kaffee-qr.mga'), 1, 1)
value, points, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(numpy.frombuffer(image, dtype=numpy.uint8), cv2.IMREAD_COLOR))
if points is None or not value:
    raise SystemExit('Native QR reference image unreadable')
expected = hashlib.sha256(value.encode('utf-8')).hexdigest()
value = None
context = WebKit2.WebContext.new_ephemeral()
security = context.get_security_manager()
for method in ('register_uri_scheme_as_secure', 'register_uri_scheme_as_display_isolated'):
    getattr(security, method)('magnolie-qr-probe')


def serve(request):
    path = urlsplit(request.get_uri()).path
    if path == '/index.html':
        data = b'''<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'"><link rel="stylesheet" href="qr-dialog.css"></head><body><img id="qr" src="kaffee-qr.png" alt="QR"><script src="qr-decoder.js"></script><script src="qr-dialog.js"></script></body></html>'''
        mime = 'text/html'
    elif path == '/kaffee-qr.png':
        data, mime = image, 'image/png'
    elif path in ('/qr-decoder.js', '/qr-dialog.js', '/qr-dialog.css'):
        data = (web / path.lstrip('/')).read_bytes()
        mime = 'text/css' if path.endswith('.css') else 'application/javascript'
    else:
        request.finish_error(GLib.Error('Unknown owned QR probe resource')); return
    request.finish(Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data)), len(data), mime)


context.register_uri_scheme('magnolie-qr-probe', serve)
view = WebKit2.WebView.new_with_context(context)
window = Gtk.Window()
window.set_default_size(650, 500)
window.add(view)
result = []


def evaluated(obj, task, callback):
    try:
        callback(json.loads(obj.evaluate_javascript_finish(task).to_string()))
    except Exception:
        result.append({'failed': True}); Gtk.main_quit()


def evaluate(script, callback):
    view.evaluate_javascript(script, -1, None, None, None, evaluated, callback)


def poll():
    def received(data):
        if data.get('pending'):
            GLib.timeout_add(50, poll)
        else:
            result.append(data); Gtk.main_quit()
    evaluate('JSON.stringify(window.qrProof)', received)
    return False


def loaded(_view, event):
    if event != WebKit2.LoadEvent.FINISHED:
        return
    evaluate('''(() => {
      window.qrProof = { pending: true };
      const image = document.getElementById('qr');
      MagnolieQr.bind(image, () => ({coffee:true}), {title:'QR',close:'Close',open:'Open',coffeeHint:'Owned notice',readError:'Unreadable'});
      image.click();
      (async () => {
        while (!document.querySelector('.magnolie-qr-text')) await new Promise(resolve => setTimeout(resolve, 10));
        const text = document.querySelector('.magnolie-qr-text').textContent;
        const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
        const sha256 = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2,'0')).join('');
        const textOnly = !document.querySelector('.magnolie-qr-open');
        document.querySelector('.magnolie-qr-dialog button').click();
        window.qrProof = {sha256, textOnly, closed: !document.querySelector('.magnolie-qr-dialog')};
      })().catch(() => { window.qrProof = {failed:true}; });
      return JSON.stringify({started:true});
    })()''', lambda _value: GLib.timeout_add(50, poll))


view.connect('load-changed', loaded)
window.show_all()
view.load_uri('magnolie-qr-probe://app/index.html')
GLib.timeout_add_seconds(30, lambda: (result.append({'failed': True}), Gtk.main_quit(), False)[-1])
Gtk.main()
window.destroy()
if len(result) != 1 or result[0].get('sha256') != expected or not result[0].get('textOnly') or not result[0].get('closed'):
    raise SystemExit('Native QR canvas/dialog verification failed (content omitted)')
print('NATIVE QR DECODE PASS: real WebKit canvas, local decoder, exact image content, text-only dialog and close; no plaintext fixture')
