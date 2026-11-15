"""Actual native GTK adapter functions, bounded controlled widgets only."""
import threading
from types import SimpleNamespace

import pytest

from test_contact_notes_consent import native
from magnolie_contact_notes_setup import NativeNotesSetupView
from magnolie_contact_notes_setup_run import NativeNotesSetupSelectionView


@pytest.mark.parametrize('kind', ['peer', 'source', 'contact'])
@pytest.mark.parametrize('mode', ['before', 'during', 'after-selection', 'second', 'unselected', 'dialog-error', 'timer-error', 'predicate-error'])
def test_owned_native_dialog_cancel_is_not_another_modal_or_selection(native, monkeypatch, kind, mode):
    dialogs, combos, labels, timers, removed = [], [], [], [], []
    event = threading.Event()
    response = SimpleNamespace(CANCEL=0, APPLY=1)
    class Button:
        def set_sensitive(self, value): self.sensitive = value
    class Label:
        def __init__(self, *, label): labels.append(label)
        def set_line_wrap(self, value): pass
        def set_max_width_chars(self, value): pass
        def set_xalign(self, value): pass
        def set_selectable(self, value): pass
    class Combo:
        def __init__(self): self.items, self.active, self.changed = [], -1, None; combos.append(self)
        def append_text(self, value): self.items.append(value)
        def set_active(self, value):
            self.active = value
            if self.changed: self.changed(self)
        def connect(self, signal, callback): assert signal == 'changed'; self.changed = callback
        def get_active(self): return self.active
    class Dialog:
        def __init__(self, **kwargs): self.buttons, self.destroyed, self.responses = {}, False, []; dialogs.append(self)
        def add_button(self, label, code): self.buttons[code] = Button(); return self.buttons[code]
        def set_default_response(self, value): self.default = value
        def set_default_size(self, *args): pass
        def get_content_area(self): return self
        def set_spacing(self, value): pass
        def set_border_width(self, value): pass
        def pack_start(self, *args): pass
        def show_all(self): pass
        def response(self, value): self.responses.append(value)
        def run(self):
            assert self.default == response.CANCEL and combos[0].active == -1 and not self.buttons[response.APPLY].sensitive
            if mode == 'dialog-error': raise RuntimeError('synthetic own modal failure')
            if mode in ('during', 'predicate-error'):
                event.set()
                assert timers[0]() is False and self.responses == [response.CANCEL]
            if mode == 'second': combos[0].set_active(1)
            if mode == 'after-selection': combos[0].set_active(1); event.set()
            return response.APPLY  # A stale APPLY cannot override owned cancellation.
        def destroy(self): self.destroyed = True
    foreign = SimpleNamespace(destroyed=False, responses=[])
    monkeypatch.setattr(native, 'Gtk', SimpleNamespace(Dialog=Dialog, Label=Label, ComboBoxText=Combo, ResponseType=response))
    def schedule(milliseconds, callback):
        assert milliseconds == 50
        if mode == 'timer-error': raise RuntimeError('synthetic unavailable UI timer')
        timers.append(callback); return len(timers)
    monkeypatch.setattr(native.GLib, 'timeout_add', schedule, raising=False)
    monkeypatch.setattr(native.GLib, 'source_remove', lambda identifier: removed.append(identifier), raising=False)
    def cancelled():
        if mode == 'predicate-error' and event.is_set(): raise RuntimeError('synthetic native owner unavailable')
        return event.is_set()
    if mode == 'before': event.set()
    peers = ({'id': 'peer-first', 'publicKey': '<key>\u202e', 'label': 'Same label'},
        {'id': 'peer-second', 'publicKey': 'key-second', 'label': 'Same label'})
    export = {'share_id': '<share>\u202e', 'setup_id': 'setup-first'}
    sources = (NativeNotesSetupSelectionView(('peer-first', '<key>\u202e'), export),
        NativeNotesSetupSelectionView(('peer-second', 'key-second'), dict(export, setup_id='setup-second')))
    view = NativeNotesSetupView(False, export, ('peer-first', '<key>\u202e'),
        ({'id': 'contact-first', 'uid': 'uid-first', 'vorname': 'Same label'},
         {'id': 'contact-second', 'uid': 'uid-second', 'vorname': 'Same label'}))
    def invoke():
        if kind == 'peer': return native.notes_original_peer_dialog(None, peers, cancelled=cancelled)
        if kind == 'source': return native.notes_original_source_dialog(None, sources, cancelled=cancelled)
        return native.notes_original_freigabe_dialog(None, view, cancelled=cancelled)
    if mode in ('dialog-error', 'timer-error', 'predicate-error'):
        with pytest.raises(RuntimeError): invoke()
    else:
        result = invoke()
        assert result == (('peer-second' if kind == 'peer' else 1 if kind == 'source' else 'contact-second') if mode == 'second' else None)
    assert not foreign.destroyed and not foreign.responses
    if mode == 'before': assert not dialogs and not timers
    else:
        assert len(dialogs) == 1 and dialogs[0].destroyed
        assert removed == ([] if mode in ('during', 'predicate-error', 'timer-error') else [1])
        assert all('\u202e' not in text for text in labels + combos[0].items)
