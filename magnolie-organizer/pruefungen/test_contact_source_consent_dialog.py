"""Opt-in actual GTK modal acceptance; isolated synthetic window/catalog only.

Run bounded under the existing Xvfb with MAGNOLIE_NATIVE_GTK_CONTACT_CONSENT=1.
Never starts Organizer, a provider connection, installation or a user profile.
"""
import json
import os
from pathlib import Path

import pytest

from modul_laden import quellmodul_laden


@pytest.mark.skipif(os.environ.get('MAGNOLIE_NATIVE_GTK_CONTACT_CONSENT') != '1',
                    reason='Explicit isolated native GTK modal probe only')
@pytest.mark.parametrize('mode', ['default-cancel', 'apply-empty', 'apply-one',
    'preselected-cancel', 'preselected-change', 'close'])
def test_actual_native_gtk_decision_is_explicit_default_off_without_silent_grants(tmp_path, monkeypatch, mode):
    for key in ('HOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR'):
        directory = tmp_path / key; directory.mkdir(mode=0o700)
        monkeypatch.setenv(key, str(directory))
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/nonexistent-contact-dialog-probe')
    native = quellmodul_laden('contact_source_actual_consent_probe',
        Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')
    assert native.Gtk is not None, 'Actual existing GTK required; no simulated UI acceptance'
    from test_contact_source_dav_factory import account
    from magnolie_contact_source_book import NativeContactSourceBook
    from magnolie_contact_source_dav import NativeDavApprovalScope
    import magnolie_nextcloud as nc
    store = account(tmp_path)
    book = NativeContactSourceBook(); book.set_ready(True)
    data = {'version': 7, 'kontakte': []}
    book.record_saved('synthetic-modal-native-book', True, json.dumps(data))
    scope = NativeDavApprovalScope(lambda: book.current('synthetic-modal-native-book', True, data), store)
    catalog = [{'uid': nc.source_id('addressbook', href, 'generic-dav'), 'href': href,
                'name': name, 'art': 'addressbook', 'canUpdate': True} for href, name in (
        ('https://source.invalid/nc/books/original/', 'Synthetic original one'),
        ('https://source.invalid/nc/books/second/', 'Synthetic original two'))]
    expected_initial = [mode.startswith('preselected'), False]
    if expected_initial[0]: scope.configure(catalog, lambda choices, selected: [choices[0]['uid']])
    owner = native.Gtk.Window(title='Synthetic consent probe owner')
    owner.show_all()
    observed, errors = [], []
    def descendants(widget):
        yield widget
        if isinstance(widget, native.Gtk.Container):
            for child in widget.get_children(): yield from descendants(child)
    def drive_modal():
        dialogs = [widget for widget in native.Gtk.Window.list_toplevels()
                   if isinstance(widget, native.Gtk.Dialog) and widget.get_transient_for() == owner]
        if not dialogs: return True
        dialog, = dialogs
        try:
            buttons = [widget for widget in descendants(dialog) if isinstance(widget, native.Gtk.CheckButton)]
            labels = [widget.get_text() for widget in descendants(dialog) if isinstance(widget, native.Gtk.Label)]
            assert any('including after restarting' in text and 'revoke this permission' in text for text in labels)
            assert len(buttons) == 2
            assert [button.get_active() for button in buttons] == expected_initial
            assert dialog.get_default_widget() == dialog.get_widget_for_response(native.Gtk.ResponseType.CANCEL)
            assert len(scope.capture()) == int(expected_initial[0]), 'Showing dialog silently granted a source'
            observed.append(True)
            if mode in ('apply-one', 'preselected-change'):
                buttons[0].set_active(False); buttons[1].set_active(True)
            if mode.startswith('apply') or mode == 'preselected-change': dialog.response(native.Gtk.ResponseType.APPLY)
            elif mode == 'close': dialog.response(native.Gtk.ResponseType.DELETE_EVENT)
            else: dialog.response(native.Gtk.ResponseType.CANCEL)
        except BaseException as error:
            errors.append(error)
            dialog.response(native.Gtk.ResponseType.CANCEL)
        return False
    timer = native.GLib.timeout_add(25, drive_modal)
    try:
        changed = scope.configure(catalog, lambda choices, selected:
            native.kontakt_quellen_freigabe_dialog(owner, choices, selected))
        assert observed == [True]
        if errors: raise errors[0]
        expected = (catalog[1]['uid'],) if mode in ('apply-one', 'preselected-change') else (
            (catalog[0]['uid'],) if mode == 'preselected-cancel' else ())
        assert tuple(approval.source for approval in scope.capture()) == expected
        assert changed is (mode in ('apply-empty', 'apply-one', 'preselected-change'))
        assert not any(isinstance(widget, native.Gtk.Dialog) for widget in native.Gtk.Window.list_toplevels())
    finally:
        owner.destroy()
