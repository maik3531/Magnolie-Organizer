"""Actual Linux flow/window entry, controlled native chooser, no GTK display."""
import copy
from pathlib import Path
from types import MethodType
from types import SimpleNamespace

import pytest

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_return import NativeNotesProtocolNegotiation
from magnolie_contact_notes_setup import NativeNotesSetupCollector, NativeNotesSetupFlow
from magnolie_contact_notes_setup import NativeNotesSetupView
from magnolie_contact_notes_consent import NativeNotesSetupDecision


@pytest.mark.parametrize('mode', ['initial', 'addition', 'cancel', 'wrong-id', 'unavailable-after-dialog', 'revoke', 'replace',
    'other-store-revoke', 'native-save', 'stop', 'display-alias', 'empty-revoke', 'revoked-before', 'window-entry',
    'no-gtk', 'window-locked', 'window-busy', 'window-closed', 'forged-candidate'])
def test_actual_native_setup_flow_requires_conscious_choice_and_before_dialog_context(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    protocol = NativeNotesProtocolNegotiation((h.sender['kennung'], h.sender['oeffentlich']),
        (h.receiver['kennung'], h.receiver['oeffentlich']))
    collector = NativeNotesSetupCollector(h.service, protocol)
    try:
        book = copy.deepcopy(h.probe._aktuelle_daten)
        other = copy.deepcopy(book['kontakte'][0]); other.update(id='second-id', uid='second-uid')
        book['kontakte'].append(other)
        assert h.save(monkeypatch, book)['ok']
        adding = mode in ('addition', 'revoke', 'replace', 'other-store-revoke')
        if adding or mode == 'revoked-before': h.configure()
        if mode == 'revoked-before': h.store.revoke()
        collector.attach()
        h.send(dict(protocol.request(), antwort=True))
        h.send(dict(h.export, share_id='setup-flow-share', setup_id='55555555-5555-4555-8555-555555555555'))
        candidate, = collector.candidates()
        h.probe._gesperrt = False
        usable = [True]
        dialogs = []
        before = Path(native.daten_datei()).read_bytes()
        key = Path(h.root, '.key').read_bytes() if adding else None
        def require_usable():
            if not usable[0]: raise PermissionError('synthetic_native_context_unavailable')
        def choose(view):
            nonlocal before
            assert not h.probe._daten_sperre._is_owned(), 'Native chooser ran inside book lock'
            assert view.addition == adding and view.peer == protocol._peer
            h.store.has_desired_consent()  # This must not race a held private file lock.
            dialogs.append(view)
            if mode in ('revoke', 'empty-revoke'): h.store.revoke()
            if mode == 'other-store-revoke': h.new_store().revoke()
            if mode == 'replace': h.store.configure([h.choice])
            if mode == 'unavailable-after-dialog': usable[0] = False
            if mode == 'native-save':
                edit = copy.deepcopy(h.probe._aktuelle_daten); edit['during-dialog'] = 'preserve'
                assert h.save(monkeypatch, edit)['ok']
                before = Path(native.daten_datei()).read_bytes()
            if mode == 'stop': collector.stop()
            if mode == 'display-alias':
                view.contacts[1]['uid'] = 'not-native'; view.export['share_id'] = 'not-a-source-grant'
            return None if mode == 'cancel' else 'foreign-id' if mode == 'wrong-id' else 'second-id'
        flow = NativeNotesSetupFlow(h.store, h.probe._kontakt_quellen_buchaufnahme, lambda: h.probe._daten_sperre, require_usable)
        success = mode in ('initial', 'addition', 'display-alias', 'revoked-before', 'window-entry')
        if mode.startswith('window-') or mode == 'no-gtk':
            h.probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, h.probe)
            if mode == 'window-locked': h.probe._gesperrt = True
            if mode == 'window-closed': h.probe._wirklich_beenden = True
            if mode == 'window-busy': h.probe._notes_original_setup_active = True
            if mode == 'window-entry':
                assert native.Fenster._notes_original_native_setup_candidate(h.probe, candidate, choose)
                assert h.probe._notes_original_setup_active is False
            else:
                monkeypatch.setattr(native, 'Gtk', None)
                with pytest.raises((PermissionError, RuntimeError)):
                    native.Fenster._notes_original_native_setup_candidate(h.probe, candidate, None if mode == 'no-gtk' else choose)
                assert not dialogs
                assert not h.store.has_desired_consent()
                return
        elif mode == 'forged-candidate':
            with pytest.raises(PermissionError): flow.configure({}, choose)
            assert not dialogs
            return
        elif success:
            assert flow.configure(candidate, choose)
        elif mode == 'cancel':
            assert flow.configure(candidate, choose) is False
        else:
            with pytest.raises(PermissionError): flow.configure(candidate, choose)
        assert Path(native.daten_datei()).read_bytes() == before
        if success:
            active = h.store._active_record()
            assert len(active[1]['choices']) == (2 if adding else 1)
            assert any(source['local_id'] == 'second-id' and source['local_uid'] == 'second-uid' and
                source['share_id'] == 'setup-flow-share' for source in active[1]['choices'])
            if adding: assert Path(h.root, '.key').read_bytes() == key
        elif mode in ('revoke', 'other-store-revoke', 'empty-revoke'):
            assert not h.store.has_desired_consent()
        elif mode == 'replace':
            active = h.store._active_record()
            assert len(active[1]['choices']) == 1 and active[1]['choices'][0]['share_id'] == h.export['share_id']
        else:
            assert not Path(h.root, '.key').exists()
    finally:
        collector.stop(); h.service.anhalten()


@pytest.mark.parametrize('mode', ['cancel', 'unselected-apply', 'explicit-first', 'explicit-second', 'literal-display', 'dialog-error'])
def test_actual_gtk_adapter_has_no_default_contact_and_always_destroys_without_opening_gtk(native, monkeypatch, mode):
    labels, combos, dialogs = [], [], []
    response = SimpleNamespace(CANCEL=0, APPLY=1)
    class Label:
        def __init__(self, *, label): labels.append(label)
        def set_line_wrap(self, value): pass
        def set_max_width_chars(self, value): pass
        def set_xalign(self, value): pass
        def set_selectable(self, value): pass
    class Combo:
        def __init__(self): self.items, self.active, self.changed = [], -1, None; combos.append(self)
        def append_text(self, text): self.items.append(text)
        def set_active(self, value):
            self.active = value
            if self.changed: self.changed(self)
        def get_active(self): return self.active
        def connect(self, signal, callback): assert signal == 'changed'; self.changed = callback
    class Button:
        def set_sensitive(self, value): self.sensitive = value
    class Dialog:
        def __init__(self, **kwargs): self.destroyed, self.buttons, self.default = False, {}, None; dialogs.append(self)
        def add_button(self, label, code): self.buttons[code] = Button(); return self.buttons[code]
        def set_default_response(self, value): self.default = value
        def set_default_size(self, *args): pass
        def get_content_area(self): return self
        def set_spacing(self, value): pass
        def set_border_width(self, value): pass
        def pack_start(self, *args): pass
        def show_all(self): pass
        def run(self):
            assert self.default == response.CANCEL and combos[0].active == -1 and self.buttons[response.APPLY].sensitive is False
            if mode == 'dialog-error': raise RuntimeError('synthetic native widget failure')
            if mode in ('explicit-first', 'explicit-second', 'literal-display'):
                combos[0].set_active(1 if mode == 'explicit-second' else 0)
                assert self.buttons[response.APPLY].sensitive is True
            return response.CANCEL if mode == 'cancel' else response.APPLY
        def destroy(self): self.destroyed = True
    monkeypatch.setattr(native, 'Gtk', SimpleNamespace(Dialog=Dialog, Label=Label, ComboBoxText=Combo, ResponseType=response))
    view = NativeNotesSetupView(False, {'share_id': '<literal-source>\u202e', 'setup_id': 'synthetic-setup'},
        ('<literal-peer>\u202e', 'synthetic-pinned-key'), ({'id': 'native-first', 'uid': 'uid-first', 'vorname': '<literal-name>\u202e'},
        {'id': 'native-second', 'uid': 'uid-second', 'vorname': 'Same visible name'}))
    try:
        if mode == 'dialog-error':
            with pytest.raises(RuntimeError): native.notes_original_freigabe_dialog(None, view)
        else:
            result = native.notes_original_freigabe_dialog(None, view)
            assert result == (None if mode in ('cancel', 'unselected-apply') else 'native-second' if mode == 'explicit-second' else 'native-first')
            assert all('\u202e' not in text for text in labels + combos[0].items)
            if mode == 'literal-display': assert any('<literal-peer>' in text for text in labels) and '<literal-name>' in combos[0].items[0]
    finally:
        assert len(dialogs) == 1 and dialogs[0].destroyed


@pytest.mark.parametrize('mode', ['initial', 'addition', 'empty-revoke', 'revoke', 'other-store-revoke', 'replace',
    'native-save', 'foreign-decision', 'forged-decision', 'cancel-before-contact', 'cancel-contact', 'chooser-error', 'replay'])
def test_before_peer_decision_is_carried_through_acquisition_without_recapturing_permission(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    collector = None
    try:
        adding = mode in ('addition', 'revoke', 'other-store-revoke', 'replace')
        if adding:
            book = copy.deepcopy(h.probe._aktuelle_daten)
            other = copy.deepcopy(book['kontakte'][0]); other.update(id='second-peer-id', uid='second-peer-uid')
            book['kontakte'].append(other)
            assert h.save(monkeypatch, book)['ok']
            h.configure()
        flow = NativeNotesSetupFlow(h.store, h.probe._kontakt_quellen_buchaufnahme, lambda: h.probe._daten_sperre)
        decision = flow.begin()  # Before the future peer dialog and any export.
        assert decision.is_addition == adding
        if mode == 'foreign-decision':
            with h.probe._daten_sperre: decision = h.new_store().begin_setup_decision()
        if mode == 'forged-decision': decision = NativeNotesSetupDecision(object())
        if mode in ('empty-revoke', 'revoke'): h.store.revoke()
        if mode == 'other-store-revoke': h.new_store().revoke()
        if mode == 'replace': h.store.configure([h.choice])
        if mode == 'cancel-before-contact': decision.cancel()
        if mode == 'native-save':
            edit = copy.deepcopy(h.probe._aktuelle_daten); edit['between-dialogs'] = 'preserve'
            assert h.save(monkeypatch, edit)['ok']
        protocol = NativeNotesProtocolNegotiation((h.sender['kennung'], h.sender['oeffentlich']),
            (h.receiver['kennung'], h.receiver['oeffentlich']))
        collector = NativeNotesSetupCollector(h.service, protocol); collector.attach()
        h.send(dict(protocol.request(), antwort=True))
        h.send(dict(h.export, share_id='before-peer-source', setup_id='55555555-5555-4555-8555-555555555555'))
        candidate, = collector.candidates()
        dialogs = []
        before = Path(native.daten_datei()).read_bytes()
        def choose(view):
            assert not h.probe._daten_sperre._is_owned()
            assert view.addition == adding
            h.store.has_desired_consent()
            dialogs.append(view)
            if mode == 'chooser-error': raise RuntimeError('synthetic dialog failure')
            return None if mode == 'cancel-contact' else view.contacts[1 if adding else 0]['id']
        if mode in ('initial', 'addition', 'replay'):
            assert flow.configure(candidate, choose, decision=decision)
            assert any(source['share_id'] == 'before-peer-source' for source in h.store._active_record()[1]['choices'])
            if mode == 'replay':
                with pytest.raises(PermissionError): flow.configure(candidate, choose, decision=decision)
            assert len(dialogs) == 1
        elif mode in ('cancel-contact', 'chooser-error'):
            if mode == 'cancel-contact': assert flow.configure(candidate, choose, decision=decision) is False
            else:
                with pytest.raises(RuntimeError): flow.configure(candidate, choose, decision=decision)
            with pytest.raises(PermissionError):
                with h.probe._daten_sperre: decision.require_current(h.store)
            with pytest.raises(PermissionError): flow.configure(candidate, choose, decision=decision)
            assert len(dialogs) == 1 and not h.store.has_desired_consent()
        else:
            with pytest.raises(PermissionError): flow.configure(candidate, choose, decision=decision)
            assert dialogs == []
        assert Path(native.daten_datei()).read_bytes() == before
        if mode in ('empty-revoke', 'cancel-before-contact', 'cancel-contact', 'chooser-error', 'native-save',
                'foreign-decision', 'forged-decision'):
            assert not Path(h.root, '.key').exists()
        if mode in ('revoke', 'other-store-revoke'): assert not h.store.has_desired_consent()
    finally:
        if collector is not None: collector.stop()
        h.service.anhalten()
