"""Actual Linux stores/crypto/worker; synthetic private profiles, no application startup."""
import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import queue
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class Probe:
    def __init__(self, data, password="fixture-password"):
        self._kennwort = password
        self._aktuelle_daten = copy.deepcopy(data)
        self._daten_sperre = threading.RLock()
        self._speicher_auftraege = queue.Queue()
        self.responses = []
        stored, self._daten_dek, self._daten_dek_kennung, self._daten_umschlag = m.daten_huelle_anlegen(json.dumps(data), password)
        m.speichere_text(stored)
        m.erinnerungsdaten_schreiben(kennwort=password)

    def _journal_snapshot(self, reason):
        return m.journal_snapshot_erzeugen(self._aktuelle_daten, reason, kennwort=self._kennwort)

    def antwort(self, callback, value):
        self.responses.append((callback, value))

    def save(self, data):
        self.responses.clear()
        self._speicher_auftraege.put((42, json.dumps(data)))
        self._speicher_auftraege.put(None)
        m.Fenster._speicher_lauf(self)
        return next(value for name, value in self.responses if name == "App.gespeichert")


def data(label="old", consent=True):
    return {"syncEpoch": "fixture-epoch", "termine": [{"id": "appointment", "titel": label,
        "datum": "2026-09-14", "zeit": "12:00", "standardErinnerung": True}],
        "notizen": [{"id": "note", "text": "PRIVATE-NOTE-NEVER-IN-PROJECTION"}],
        "einstellungen": {"sicherheit": {"erinnernTrotzKennwort": consent}, "erinnerung": {"an": True}}}


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Do not alter the surrounding pytest process's HOME, bus or RLIMIT at
        # collection time. Every test uses the actual stores under its own root.
        global WORK, m
        WORK = tempfile.TemporaryDirectory(prefix="asr03-", dir="/tmp/opencode")
        values = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-asr03-bus"}
        for key in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            target = Path(WORK.name) / key
            target.mkdir(mode=0o700)
            values[key] = str(target)
        cls.environment = patch.dict(os.environ, values)
        cls.environment.start()
        loader = importlib.machinery.SourceFileLoader("asr03_native", str(ROOT / "magnolie-organizer-2.0.0/bin/magnolie-organizer"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        m = importlib.util.module_from_spec(spec)
        loader.exec_module(m)
        Probe._vielleicht_verschluesseln = m.Fenster._vielleicht_verschluesseln
        Probe._erinnerungsprojektion_aktualisieren = m.Fenster._erinnerungsprojektion_aktualisieren

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        WORK.cleanup()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=WORK.name))
        self.profile = self.root / "daten.json"
        self.projection = self.root / "erinnerungsdaten.json"
        self.patches = [patch.object(m, "daten_verzeichnis", lambda: str(self.root)),
                        patch.object(m, "daten_datei", lambda: str(self.profile)),
                        patch.object(m, "erinnerungsdaten_datei", lambda: str(self.projection))]
        for p in self.patches: p.start()
        self.probe = Probe(data())
        # Actual snapshot writer, with its explicit fixture root; no GUI method stub.
        self.probe._journal_snapshot = lambda reason: m.journal_snapshot_erzeugen(
            self.probe._aktuelle_daten, reason, kennwort=self.probe._kennwort, basis=str(self.root))

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def stored(self):
        return json.loads(m.entschluesseln(self.profile.read_text(), self.probe._kennwort))

    def assert_warning(self, ack):
        self.assertTrue(ack["ok"])
        self.assertTrue(ack["committed"])
        self.assertTrue(ack["repairPending"])
        self.assertTrue(any(name == "App.erinnerungStand" and not value["ok"] and value["fehler"]
                            for name, value in self.probe.responses))

    def test_committed_source_not_argument_and_explicit_binding(self):
        m.erinnerungsdaten_schreiben(data("UNCOMMITTED"), kennwort=self.probe._kennwort)
        actual = m.erinnerungsdaten_lesen(str(self.projection), profil_pfad=str(self.profile))
        self.assertEqual(actual["termine"][0]["titel"], "old")
        self.assertNotIn("PRIVATE-NOTE", self.projection.read_text())
        self.assertEqual(stat.S_IMODE(self.projection.stat().st_mode), 0o600)
        with self.assertRaises(RuntimeError):
            m.erinnerungsdaten_schreiben(kennwort="wrong-fixture-password")
        self.assertIsNone(m.erinnerungsdaten_lesen(str(self.projection), profil_pfad=str(self.root / "missing.json")))

    def test_profile_rename_failure_keeps_old_generation(self):
        replace = m.os.replace
        def fail(src, dst):
            if str(dst) == str(self.profile): raise OSError("fixture profile rename")
            return replace(src, dst)
        with patch.object(m.os, "replace", fail): ack = self.probe.save(data("new"))
        self.assertFalse(ack["ok"])
        self.assertEqual(self.stored(), data())
        self.assertEqual(m.erinnerungsdaten_lesen()["termine"][0]["titel"], "old")

    def test_profile_file_fsync_failure_keeps_old_generation(self):
        sync = m.os.fsync
        def fail(fd):
            path = os.readlink(f"/proc/self/fd/{fd}")
            if str(self.root / ".magnolie-") in path: raise OSError("fixture file fsync")
            return sync(fd)
        with patch.object(m.os, "fsync", fail): ack = self.probe.save(data("new"))
        self.assertFalse(ack["ok"])
        self.assertEqual(self.stored(), data())

    def test_profile_directory_fsync_failure_reports_actual_new_primary(self):
        sync = m.os.fsync
        def fail(fd):
            if os.readlink(f"/proc/self/fd/{fd}") == str(self.root): raise OSError("fixture directory fsync")
            return sync(fd)
        with patch.object(m.os, "fsync", fail): ack = self.probe.save(data("new"))
        self.assert_warning(ack)
        self.assertEqual(self.stored(), data("new"))
        self.assertEqual(self.probe._aktuelle_daten, data("new"))
        self.assertIsNone(m.erinnerungsdaten_lesen())
        self.assertTrue(self.probe._erinnerungsprojektion_aktualisieren()["ok"])
        self.assertEqual(m.erinnerungsdaten_lesen()["termine"][0]["titel"], "new")

    def test_projection_phase_failures(self):
        for phase in ("source-fsync", "mirror-delete", "withdrawal-fsync", "temp-fsync", "rename", "directory-fsync"):
            with self.subTest(phase=phase):
                source = data("new-" + phase)
                sync, replace, unlink = m.os.fsync, m.os.replace, m.os.unlink
                after_profile = False
                after_projection = False
                def ren(src, dst):
                    nonlocal after_profile, after_projection
                    if str(dst) == str(self.projection) and phase == "rename": raise OSError("fixture projection rename")
                    result = replace(src, dst)
                    if str(dst) == str(self.profile): after_profile = True
                    if str(dst) == str(self.projection): after_projection = True
                    return result
                def fs(fd):
                    path = os.readlink(f"/proc/self/fd/{fd}")
                    if after_profile:
                        if phase == "source-fsync" and path == str(self.profile): raise OSError("fixture source fsync")
                        if phase == "temp-fsync" and str(self.root / ".magnolie-") in path: raise OSError("fixture projection temp fsync")
                        if phase == "withdrawal-fsync" and path == str(self.root):
                            # The first root sync is the profile commit; fail the second.
                            fs.count += 1
                            if fs.count == 3: raise OSError("fixture projection withdrawal fsync")
                        if phase == "directory-fsync" and after_projection and path == str(self.root): raise OSError("fixture projection directory fsync")
                    return sync(fd)
                fs.count = 0
                def delete(path, *args, **kwargs):
                    if phase == "mirror-delete" and str(path) == str(self.projection) + ".bak": raise OSError("fixture mirror deletion")
                    return unlink(path, *args, **kwargs)
                with patch.object(m.os, "replace", ren), patch.object(m.os, "fsync", fs), patch.object(m.os, "unlink", delete):
                    ack = self.probe.save(source)
                self.assert_warning(ack)
                self.assertEqual(self.stored(), source)
                projected = m.erinnerungsdaten_lesen()
                if projected is not None: self.assertEqual(projected["termine"][0]["titel"], source["termine"][0]["titel"])
                self.assertTrue(self.probe._erinnerungsprojektion_aktualisieren()["ok"])

    def test_withdrawal_delete_failures_never_authorize_old_consent(self):
        for suffix in ("", ".bak"):
            with self.subTest(suffix=suffix):
                self.probe.save(data())
                mirror = Path(str(self.projection) + ".bak")
                mirror.write_bytes(self.projection.read_bytes())
                unlink = m.os.unlink
                def fail(path, *args, **kwargs):
                    if str(path) == str(self.projection) + suffix: raise PermissionError("fixture locked projection")
                    return unlink(path, *args, **kwargs)
                with patch.object(m.os, "unlink", fail): ack = self.probe.save(data("withdrawn", False))
                self.assert_warning(ack)
                self.assertEqual(self.stored(), data("withdrawn", False))
                self.assertIsNone(m.erinnerungsdaten_lesen())
                self.assertTrue(Path(str(self.projection) + suffix).exists(), "privacy residue must be honestly observed")
                self.assertTrue(self.probe._erinnerungsprojektion_aktualisieren()["ok"])
                self.assertFalse(self.projection.exists())
                self.assertFalse(mirror.exists())

    def test_actual_reader_requires_primary_even_with_cached_encrypted_sentinel(self):
        real_open = open
        def inaccessible(path, *args, **kwargs):
            if str(path) == str(self.profile): raise PermissionError("fixture primary inaccessible")
            return real_open(path, *args, **kwargs)
        with patch("builtins.open", inaccessible):
            with self.assertRaises(PermissionError):
                m.erinnerungsdaten_lesen(str(self.projection), profil_pfad=str(self.profile))
            with patch.object(m, "daten_lesen_gepuffert", lambda pfad=None: "verschluesselt"), \
                 patch.object(m, "sitzungsumgebung_uebernehmen", lambda: None), patch.object(m, "wecker_notiz", lambda text: None):
                result = m.erinnerungslauf(als_wecker=True)
                self.assertEqual(result["gemeldet"], 0)
                self.assertTrue(result["fehler"])

    def test_legacy_projection_and_changed_bytes_ignored(self):
        value = json.loads(self.projection.read_text())
        value.pop("profilSha256")
        self.projection.write_text(json.dumps(value))
        self.assertIsNone(m.erinnerungsdaten_lesen())
        m.erinnerungsdaten_schreiben(kennwort=self.probe._kennwort)
        self.profile.write_text(self.profile.read_text() + "\n")
        self.assertIsNone(m.erinnerungsdaten_lesen())

    def test_false_return_is_reported_not_ignored(self):
        with patch.object(m, "erinnerungsdaten_schreiben", lambda *args, **kwargs: False):
            ack = self.probe.save(data("committed"))
        self.assert_warning(ack)
        self.assertEqual(self.stored(), data("committed"))

    def test_session_crypto_uses_committed_bytes_and_strict_consent(self):
        with patch.object(m, "entschluesseln", side_effect=AssertionError("Autosave must not repeat password KDF")):
            self.assertTrue(m.erinnerungsdaten_schreiben(data("not-committed"),
                schluessel=(self.probe._daten_dek, self.probe._daten_dek_kennung)))
        self.assertEqual(m.erinnerungsdaten_lesen()["termine"][0]["titel"], "old")
        with self.assertRaises(RuntimeError):
            m.erinnerungsdaten_schreiben(schluessel=(self.probe._daten_dek, b"wrong-session-id"))
        value = data("not-authorized", "false")
        self.assertTrue(self.probe.save(value)["ok"])
        self.assertIsNone(m.erinnerungsdaten_lesen())


if __name__ == "__main__":
    unittest.main(verbosity=2)
