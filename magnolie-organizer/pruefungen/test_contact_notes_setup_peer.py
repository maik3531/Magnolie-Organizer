"""Native cached-peer entry -> actual FS1 acquisition -> same before-peer CAS.

Only owned synthetic state and injected HTTP; no GTK, service start or user keys.
"""
import copy
from pathlib import Path
from types import MethodType
from types import SimpleNamespace

import pytest

from test_contact_notes_consent import Harness, native


@pytest.mark.parametrize('mode', ['complete', 'peer-cancel', 'wrong-id', 'display-alias', 'revoke-peer', 'save-peer',
    'epoch-peer', 'key-peer', 'stop-peer', 'missing-service', 'disabled', 'no-cache', 'contact-off', 'wlan-off',
    'epoch-after-acquire', 'revoke-after-acquire', 'save-after-acquire', 'contact-cancel', 'fake-candidate'])
def test_actual_native_peer_entry_never_lazy_loads_or_regrants_after_dialog_or_acquisition(native, monkeypatch, tmp_path, mode):
    h = Harness(native, tmp_path)
    acquisition = None
    sessions = []
    try:
        probe = h.probe
        probe._notes_original_choice_store_hole = MethodType(native.Fenster._notes_original_choice_store_hole, probe)
        probe._baum_sperre, probe._baumdienst, probe._baum = h.service._sperre, h.service, h.receiver
        probe._baum_zustand = lambda: pytest.fail('Setup lazily loaded/migrated native tree state')
        peer = native.baum_partner(h.receiver, h.sender['kennung'])
        peer.update(vertraut=True, kontaktSync=True, protokoll='baum-fs1')
        h.receiver.setdefault('syncEpoch', 'synthetic-native-setup-epoch')
        if mode == 'missing-service': probe._baumdienst = None
        if mode == 'disabled': h.receiver['an'] = False
        if mode == 'no-cache': probe._baum = None
        if mode == 'contact-off': peer['kontaktSync'] = False
        dialogs, calls = [], []
        before_book = Path(native.daten_datei()).read_bytes()
        monkeypatch.setattr(native, 'kontakt_quellen_wlan_verfuegbar', lambda: mode != 'wlan-off')
        def choose(values):
            nonlocal before_book
            assert not probe._daten_sperre._is_owned() and not probe._baum_sperre._is_owned()
            dialogs.append(values)
            assert values[0]['publicKey'] == h.sender['oeffentlich']
            if mode == 'display-alias': values[0]['publicKey'] = 'display-only-not-native-key'
            if mode == 'revoke-peer': h.store.revoke()
            if mode == 'save-peer':
                edit = copy.deepcopy(probe._aktuelle_daten); edit['during-peer-dialog'] = 'preserve'
                assert h.save(monkeypatch, edit)['ok']
                before_book = Path(native.daten_datei()).read_bytes()
            if mode == 'epoch-peer': h.receiver['syncEpoch'] = 'new-synthetic-epoch'
            if mode == 'key-peer': peer['oeffentlich'] = 'changed-not-native-key'
            if mode == 'stop-peer': h.service.anhalten()
            return None if mode == 'peer-cancel' else 'foreign-native-id' if mode == 'wrong-id' else h.sender['kennung']
        def sender(url, body):
            assert not probe._daten_sperre._is_owned() and not probe._baum_sperre._is_owned()
            calls.append(url)
            if url.endswith('/sitzung'):
                answer, session = native.fs_antwort_bauen(h.sender,
                    {'kennung': h.receiver['kennung'], 'oeffentlich': h.receiver['oeffentlich']}, body)
                sessions.append(session)
                return answer
            session = sessions[-1]
            clear, _ = native.umschlag_oeffnen_fs(session, h.sender['kennung'], h.receiver['kennung'], body)
            assert clear['art'] == 'kontakt_original_aushandlung'
            h.send(dict(clear, antwort=True)); h.send(h.export)
            return native.fs_ack_bauen(session, body)
        denied = mode in ('wrong-id', 'revoke-peer', 'save-peer', 'epoch-peer', 'key-peer', 'stop-peer',
            'missing-service', 'disabled', 'no-cache', 'contact-off')
        if denied:
            with pytest.raises(PermissionError): native.Fenster._notes_original_native_setup_acquire(probe, choose, sender)
            if mode in ('missing-service', 'disabled', 'no-cache', 'contact-off'): assert dialogs == []
            assert calls == [] and h.service._notes_setup_collector is None
        else:
            acquisition = native.Fenster._notes_original_native_setup_acquire(probe, choose, sender)
            if mode == 'peer-cancel':
                assert acquisition is None and h.service._notes_setup_collector is None
                return
            assert not h.store.has_desired_consent()
            if mode in ('epoch-after-acquire', 'revoke-after-acquire', 'save-after-acquire'):
                if mode == 'epoch-after-acquire': h.receiver['syncEpoch'] = 'changed-after-acquisition'
                if mode == 'revoke-after-acquire': h.store.revoke()
                if mode == 'save-after-acquire':
                    edit = copy.deepcopy(probe._aktuelle_daten); edit['after-peer'] = 'preserve'
                    assert h.save(monkeypatch, edit)['ok']
                    before_book = Path(native.daten_datei()).read_bytes()
                with pytest.raises(PermissionError): acquisition.probe()
                assert calls == []
                assert h.service._notes_setup_collector is None
            elif mode == 'wlan-off':
                assert acquisition.probe() is False and calls == []
            else:
                context = acquisition._collector._native_context
                def deferred_context():
                    assert not probe._baum_sperre._is_owned(), 'Book/native setup context called under receive/tree gate'
                    context()
                acquisition._collector._native_context = deferred_context
                assert acquisition.probe() is True and len(calls) == 2
                candidate, = acquisition.wait()
                if mode == 'fake-candidate':
                    with pytest.raises(PermissionError): acquisition.configure({}, lambda _: 'anything')
                def contact(view):
                    assert not probe._daten_sperre._is_owned() and not probe._baum_sperre._is_owned()
                    assert view.peer == (h.sender['kennung'], h.sender['oeffentlich'])
                    return None if mode == 'contact-cancel' else view.contacts[0]['id']
                assert acquisition.configure(candidate, contact) is (mode != 'contact-cancel')
                assert h.service._notes_setup_collector is None
                assert h.store.has_desired_consent() is (mode != 'contact-cancel')
                if mode != 'contact-cancel':
                    assert h.store._active_record()[1]['choices'][0]['peer'][1] == h.sender['oeffentlich']
        assert Path(native.daten_datei()).read_bytes() == before_book
        assert not getattr(probe, '_notes_original_peer_prompt', False)
        assert not (tmp_path / 'telefon' / 'phone.db').exists()
        if mode not in ('complete', 'display-alias', 'fake-candidate'): assert not h.store.has_desired_consent()
    finally:
        if acquisition is not None: acquisition.stop()
        for session in sessions: native.fs_sitzung_loeschen(session)
        h.service.anhalten()


@pytest.mark.parametrize('mode', ['cancel', 'no-selection', 'explicit-selection'])
def test_actual_peer_dialog_adapter_uses_explicit_id_with_no_default_or_markup(native, monkeypatch, mode):
    controls = []
    dialogs = []
    response = SimpleNamespace(CANCEL=0, APPLY=1)
    class Combo:
        def __init__(self): self.items, self.active, self.changed = [], -1, None; controls.append(self)
        def append_text(self, text): self.items.append(text)
        def set_active(self, value):
            self.active = value
            if self.changed: self.changed(self)
        def get_active(self): return self.active
        def connect(self, signal, callback): self.changed = callback
    class Button:
        def set_sensitive(self, value): self.sensitive = value
    class Dialog:
        def __init__(self, **kwargs): self.buttons, self.destroyed = {}, False; dialogs.append(self)
        def add_button(self, text, value): self.buttons[value] = Button(); return self.buttons[value]
        def set_default_response(self, value): self.default = value
        def set_default_size(self, *args): pass
        def get_content_area(self): return self
        def set_spacing(self, value): pass
        def set_border_width(self, value): pass
        def pack_start(self, *args): pass
        def show_all(self): pass
        def run(self):
            assert self.default == response.CANCEL and controls[0].active == -1 and not self.buttons[response.APPLY].sensitive
            if mode == 'explicit-selection':
                controls[0].set_active(0)
                assert self.buttons[response.APPLY].sensitive
            return response.CANCEL if mode == 'cancel' else response.APPLY
        def destroy(self): self.destroyed = True
    monkeypatch.setattr(native, 'Gtk', SimpleNamespace(Dialog=Dialog, ComboBoxText=Combo, ResponseType=response))
    result = native.notes_original_peer_dialog(None, ({'id': 'native-pinned-id', 'publicKey': 'native-public-key', 'label': '<literal>\u202e'},))
    assert result == ('native-pinned-id' if mode == 'explicit-selection' else None)
    assert '<literal>' in controls[0].items[0] and '\u202e' not in controls[0].items[0]
    assert dialogs[0].destroyed
