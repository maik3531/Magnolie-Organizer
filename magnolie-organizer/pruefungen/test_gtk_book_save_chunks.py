import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from modul_laden import quellmodul_laden


PROGRAM = Path(__file__).resolve().parents[1] / "bin" / "magnolie-organizer"
m = quellmodul_laden("magnolie_gtk_book_save_chunks", str(PROGRAM))


class Value:
    def __init__(self, value):
        self.value = value

    def object_get_property_at_index(self, index):
        return Value(self.value[index])

    def is_number(self):
        return type(self.value) in (float, int)

    def is_boolean(self):
        return type(self.value) is bool

    def is_string(self):
        return type(self.value) is str

    def to_double(self):
        return float(self.value)

    def to_boolean(self):
        return self.value

    def to_string(self):
        return self.value


class Window:
    _speicher_text_verwerfen = m.Fenster._speicher_text_verwerfen
    _speicher_text_buchbindung = m.Fenster._speicher_text_buchbindung
    _speicher_text_teil = m.Fenster._speicher_text_teil
    _speicher_lauf = m.Fenster._speicher_lauf

    def __init__(self):
        self._gesperrt = False
        self._operation_laeuft = False
        self._ladefehler = ""
        self._daten_dek_kennung = "key"
        self._aktuelle_daten = {"syncEpoch": "original"}
        self._daten_sperre = threading.RLock()
        self._speicher_auftraege = queue.Queue()
        self._speicher_text_eingang = None
        self.messages = []

    def _darf_schreiben(self):
        return not self._gesperrt and not self._operation_laeuft

    def antwort(self, callback, data):
        self.messages.append((callback, data))

    def receive(self, *fields):
        self._speicher_text_teil(Value(fields), len(fields))


@pytest.fixture
def transfer(monkeypatch):
    callbacks = {}

    def timeout(seconds, callback):
        assert seconds == 30
        key = len(callbacks) + 1
        callbacks[key] = callback
        return key

    monkeypatch.setattr(m, "GLib", SimpleNamespace(timeout_add_seconds=timeout, source_remove=callbacks.pop))
    monkeypatch.setattr(m, "daten_datei", lambda: "/fixture/book")
    return Window(), callbacks


def test_only_complete_ordered_text_reaches_the_existing_writer(transfer):
    window, callbacks = transfer
    window.receive(4, 0, '{"text":"日本語', False)
    assert window.messages == [("App.speicherTextTeil", {"id": 4, "index": 0})]
    assert window._speicher_auftraege.empty()
    window.receive(4, 1, ' 🌺"}', True)
    assert window._speicher_auftraege.get_nowait() == (
        4, '{"text":"日本語 🌺"}', None, None, None, None, window._speicher_text_buchbindung())
    assert window._speicher_text_eingang is None
    assert not callbacks
    assert len(window.messages) == 1  # The writer alone sends SaveACK.


@pytest.mark.parametrize("second", [
    (4, 0, "duplicate", False),
    (4, 2, "gap", True),
    (4, 1, "x" * (4 * 1024 * 1024 + 1), True),
    (4, 1, "invalid final flag", 1),
])
def test_invalid_part_cannot_queue_a_write(transfer, second):
    window, callbacks = transfer
    window.receive(4, 0, "start", False)
    window.receive(*second)
    assert window._speicher_auftraege.empty()
    assert window.messages[-1][0] == "App.gespeichert"
    assert window.messages[-1][1]["ok"] is False
    assert window._speicher_text_eingang is None and not callbacks


@pytest.mark.parametrize("change", ["restore", "metadata-restore", "lock", "cancel", "timeout"])
def test_old_final_part_cannot_resume_after_revocation(transfer, change):
    window, callbacks = transfer
    window.receive(4, 0, "start", False)
    if change == "restore":
        window._aktuelle_daten = {"syncEpoch": "replacement"}
    elif change == "metadata-restore":
        window._aktuelle_daten["syncMetadaten"] = {"syncEpoch": "replacement"}
    elif change == "lock":
        window._gesperrt = True
    elif change == "cancel":
        window.receive(4)
    else:
        expiry = callbacks.popitem()[1]
        assert expiry() is False
    window.receive(4, 1, "stale", True)
    assert window._speicher_auftraege.empty()
    assert window.messages[-1][1]["ok"] is False
    assert window._speicher_text_eingang is None and not callbacks


def test_writer_checks_the_restore_epoch_again_after_queueing(transfer, monkeypatch):
    window, _ = transfer
    window.receive(4, 0, '{"syncEpoch":', False)
    window.receive(4, 1, '"original"}', True)
    window._aktuelle_daten["syncMetadaten"] = {"syncEpoch": "replacement"}
    writes = []
    monkeypatch.setattr(m, "speichere_text", lambda *args, **kwargs: writes.append(args))
    window._speicher_auftraege.put(None)
    window._speicher_lauf()
    assert not writes
    assert window.messages[-1][0] == "App.gespeichert"
    assert window.messages[-1][1]["ok"] is False
