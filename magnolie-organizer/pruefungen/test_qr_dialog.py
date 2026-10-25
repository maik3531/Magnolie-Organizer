"""#220: reviewed QR contents, display-only pairing and actual GTK confirmation."""
import hashlib
import re
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'magnolie-organizer/bin'))


def test_coffee_dialog_content_matches_the_reviewed_image_on_all_platforms():
    import cv2
    import numpy
    from magnolie_asset import read_asset
    image_digest = None
    content_digest = None
    for directory in ('magnolie-organizer/web', 'magnolie-organizer-windows/app/web', 'magnolie-handbuch/web'):
        data = read_asset(str(ROOT / directory / 'kaffee-qr.mga'), 1, 1)
        current_image_digest = hashlib.sha256(data).hexdigest()
        image_digest = image_digest or current_image_digest
        assert current_image_digest == image_digest
        image = cv2.imdecode(numpy.frombuffer(data, dtype=numpy.uint8), cv2.IMREAD_COLOR)
        value, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
        assert points is not None and bool(value), 'QR image is unreadable'
        current_content_digest = hashlib.sha256(value.encode('utf-8')).hexdigest()
        content_digest = content_digest or current_content_digest
        assert current_content_digest == content_digest
        assert not (ROOT / directory / 'qr-content.js').exists()
        for name in ('qr-dialog.js', 'qr-dialog.css', 'qr-decoder.js', 'qr-decoder-LICENSE.txt'):
            assert (ROOT / directory / name).read_bytes() == (ROOT / 'magnolie-organizer/web' / name).read_bytes()
    assert not (ROOT / 'contracts/qr-content.json').exists()


def test_native_pairing_qr_does_not_add_plaintext_payload_or_accept_any_pair(monkeypatch):
    from modul_laden import quellmodul_laden
    monkeypatch.setitem(sys.modules, 'gi', None)
    native = quellmodul_laden('qr_dialog_native', ROOT / 'magnolie-organizer/bin/magnolie-organizer')
    document = {'gueltigBis': 1234567, 'owned_fixture': 'display-only'}
    replies, reports = [], []
    fake = SimpleNamespace(_baum_paarungsqr_dokument=lambda *_: (document, 'data:image/svg+xml,owned'),
        antwort=lambda callback, value: replies.append((callback, value)), _baum_stand_melden=lambda: reports.append(True))
    native.Fenster._baum_paarungsqr_erzeugen(fake, 'owned.invalid', 8737)
    assert len(replies) == 1 and reports == [True]
    callback, result = replies[0]
    assert callback == 'App.baumPaarungsdatei' and result['ok'] is True
    assert 'text' not in result and result['gueltigBis'] == document['gueltigBis']
    assert result['bild'] == 'data:image/svg+xml,owned'


def test_account_number_is_not_copied_into_text_sources():
    import cv2
    import numpy
    from magnolie_asset import read_asset
    data = read_asset(str(ROOT / 'magnolie-organizer/web/kaffee-qr.mga'), 1, 1)
    value, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(numpy.frombuffer(data, dtype=numpy.uint8), cv2.IMREAD_COLOR))
    match = re.search(r'IBAN:\s*([A-Z]{2}\d{2}(?:[ \t]*\d){10,30})', value)
    if match is None:
        pytest.fail('The reviewed QR account field could not be identified (content omitted)')
    account = re.sub(r'\s+', '', match[1])
    for directory, patterns in (
        ('contracts', ('*.json', '*.md')), ('tools', ('*.py', '*.json')),
        ('magnolie-organizer/web', ('*.js', '*.html', '*.json')),
        ('magnolie-organizer-windows/app/web', ('*.js', '*.html', '*.json')),
        ('magnolie-handbuch/web', ('*.js', '*.html', '*.json')),
        ('magnolie-organizer-windows', ('*.cs',)),
    ):
        for pattern in patterns:
            for path in (ROOT / directory).glob(pattern):
                if account in re.sub(r'\s+', '', path.read_text()):
                    pytest.fail('Decoded account copied into a text source: ' + str(path.relative_to(ROOT)))


def test_actual_gtk_download_qr_asks_before_opening_the_browser(tmp_path, monkeypatch):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    import magnolie_setup_ui as ui
    assert Gtk.init_check()[0]
    monkeypatch.setattr(ui, '_read_language', lambda: 'en')
    monkeypatch.setattr(ui, '_play_welcome_chime', lambda *_: None)
    monkeypatch.setattr(ui, '_persist_language', lambda *_: None)
    for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        monkeypatch.setenv(key, str(tmp_path))
    opened, failures = [], []
    monkeypatch.setattr(Gtk, 'show_uri_on_window', lambda _parent, url, _time: opened.append(url))

    def descendants(widget):
        yield widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                yield from descendants(child)

    def dismiss_all():
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, Gtk.Dialog): window.response(Gtk.ResponseType.CANCEL)

    def confirmation(response):
        try:
            child = next(window for window in Gtk.Window.list_toplevels() if isinstance(window, Gtk.Dialog) and window.get_title() == 'QR code')
            assert any(isinstance(node, Gtk.Label) and node.get_text() == ui.MAGNOLIE_NOTES_URL for node in descendants(child))
            assert not opened
            child.response(response)
        except BaseException as error:
            failures.append(error); dismiss_all()
        return False

    def qr_page():
        try:
            qr = next(window for window in Gtk.Window.list_toplevels() if isinstance(window, Gtk.Dialog) and window.get_title() == 'Magnolie Notes')
            image = next(node for node in descendants(qr) if node.get_name() == 'setup-download-qr')
            assert image.get_can_focus() and not opened
            assert image.get_tooltip_text() == 'Scan or click'
            for response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.ACCEPT):
                GLib.idle_add(confirmation, response)
                event = Gdk.Event.new(Gdk.EventType.KEY_PRESS); event.keyval = Gdk.KEY_Return
                image.emit('key-press-event', event)
            assert opened == [ui.MAGNOLIE_NOTES_URL]
            qr.response(Gtk.ResponseType.CLOSE)
        except BaseException as error:
            failures.append(error); dismiss_all()
        return False

    def drive():
        try:
            parent = next(window for window in Gtk.Window.list_toplevels() if isinstance(window, Gtk.Dialog))
            button = next(node for node in descendants(parent) if isinstance(node, Gtk.Button) and node.get_label() == 'Magnolie Notes')
            GLib.idle_add(qr_page); button.emit('clicked'); parent.response(Gtk.ResponseType.CANCEL)
        except BaseException as error:
            failures.append(error); dismiss_all()
        return False

    GLib.idle_add(drive)
    ui.run_setup(Gtk, Gdk, lambda value: value, lambda *_: None, str(ROOT / 'magnolie-organizer/bin'))
    if failures: raise failures[0]
    assert opened == [ui.MAGNOLIE_NOTES_URL]
