import json
import importlib.machinery
import importlib.util
import io
import os
import stat
import subprocess
import sys

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, BIN)

import magnolie_setup_state as setup
import magnolie_setup_ui as setup_ui


def test_state_classification_distinguishes_fresh_existing_pending_and_damage(tmp_path):
    marker = tmp_path / "config" / "magnolie-organizer" / setup.MARKER_NAME
    evidence = (tmp_path / "data" / "magnolie-organizer", marker.parent)
    marker.parent.mkdir(parents=True)
    assert setup.classify(str(marker), tuple(map(str, evidence))) == "fresh"

    data = evidence[0]
    data.mkdir(parents=True)
    (data / "daten.json").write_text("{broken", encoding="utf-8")
    assert setup.classify(str(marker), tuple(map(str, evidence))) == "existing"
    assert setup.classify_and_adopt(str(marker), tuple(map(str, evidence))) == "ready"
    adopted = json.loads(marker.read_text(encoding="utf-8"))
    assert adopted["status"] == "adopted"
    assert adopted["selections"] == {"reason": "pre-existing-local-state"}

    setup.write_state("pending", path=str(marker))
    assert setup.classify(str(marker), ()) == "pending"
    marker.write_text("not json", encoding="utf-8")
    assert setup.classify(str(marker), ()) == "damaged"
    assert not setup.services_allowed("damaged")


def test_marker_replacement_is_atomic_and_private(tmp_path, monkeypatch):
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    setup.write_state("pending")
    setup.write_state("complete", {"sources": [], "personal": "plain text"})
    marker = setup.marker_path()
    assert stat.S_IMODE(os.stat(marker).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(marker)).st_mode) == 0o700
    assert json.loads(open(marker, encoding="utf-8").read())["selections"]["sources"] == []
    assert not [name for name in os.listdir(os.path.dirname(marker))
                if name.startswith(".setup-")]


def test_setup_defaults_match_the_shared_selection_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    selections = setup_ui._default_selections("de")
    assert list(selections) == [
        "language", "address", "addressSource", "addressSort", "calendarUids",
        "addressBookUid", "oneTimeImports", "phoneActions", "registers", "customTabEnabled",
        "customTabName", "customTabDesignRequested", "customTabChanged", "customOrganizerChanged", "customOrganizer", "autostart", "tray", "weather", "restoreRequest",
        "openHandbook", "backupPath", "backupInterval",
    ]
    assert selections["language"] == "de"
    assert selections["address"] == {
        "firstName": "", "lastName": "", "street": "", "postalCode": "",
        "city": "", "country": "DE", "state": ""}
    assert selections["addressSource"] == "own"
    assert selections["registers"] == [
        "tasks", "addresses", "notes", "anniversaries", "planner",
        "health"]
    assert selections["customTabEnabled"] is False
    assert selections["customTabChanged"] is False
    assert selections["customOrganizerChanged"] is False
    assert selections["addressSort"] == "last-name"
    assert selections["calendarUids"] == [] and selections["addressBookUid"] == ""
    assert selections["phoneActions"] == []
    assert selections["customOrganizer"] == {"version": 3, "modules": []}
    assert selections["autostart"] is False
    assert selections["tray"] is False
    assert selections["weather"] is False
    assert selections["restoreRequest"] is False
    assert selections["openHandbook"] is False
    assert selections["backupPath"] == str(tmp_path / "data" / "magnolie-organizer")
    assert selections["backupInterval"] == "manual"


def test_setup_opens_downloads_without_bluetooth_and_stores_custom_designer_modules():
    source = open(setup_ui.__file__, encoding="utf-8").read()
    assert "KDE_CONNECT_URL" in source and "MAGNOLIE_NOTES_URL" in source
    assert "qrcode.make(url)" in source
    assert '"customOrganizer": {"version": 3, "modules": list(custom_modules)}' in source
    assert "phone_actions_selected" not in source
    assert 'notes_connect' not in source and 'kde_connect' not in source
    assert "bluetooth_button" not in source and "open_bluetooth" not in source
    assert '"tray": autostart.get_active()' in source
    assert 'weather = check("Show weather for the next three days")' in source
    assert 'for module in custom_modules:' in source


def test_damaged_foreground_requires_assistant_but_services_stay_blocked():
    assert setup.assistant_required("damaged")
    assert setup.assistant_required("fresh")
    assert setup.assistant_required("pending")
    assert not setup.assistant_required("ready")
    assert not setup.services_allowed("damaged")
    assert setup.services_allowed("existing")


def test_legacy_data_and_diagnostic_logs_do_not_suppress_fresh_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    legacy = tmp_path / "data" / "organizer-klassik"
    legacy.mkdir(parents=True)
    (legacy / "daten.json").write_text("{}", encoding="utf-8")
    diagnostics = tmp_path / "state" / "magnolie-organizer"
    diagnostics.mkdir(parents=True)
    (diagnostics / "debug.log").write_text("old", encoding="utf-8")
    assert setup.classify() == "fresh"


def test_skip_disables_handbook_and_result_returns_saved_selections():
    writes = []
    skipped = setup_ui._skipped_selections("de")
    result = setup_ui._store_result(
        lambda status, value: writes.append((status, value)), "skipped", skipped)
    assert result is skipped
    assert writes == [("skipped", skipped)]
    assert skipped["openHandbook"] is False
    assert skipped["restoreRequest"] is False


def test_welcome_chime_plays_packaged_sound_once_with_direct_argv(tmp_path, monkeypatch):
    script = tmp_path / "app" / "bin"
    sound = tmp_path / "app" / "klang" / "erinnerung.wav"
    script.mkdir(parents=True)
    sound.parent.mkdir()
    sound.write_bytes(b"RIFF")
    calls = []
    monkeypatch.setenv("MAGNOLIE_ORGANIZER_KLANG", str(sound))

    used = setup_ui._play_welcome_chime(
        str(script), finder=lambda name: "/usr/bin/" + name if name == "paplay" else None,
        starter=lambda argv: calls.append(argv))

    assert used == "paplay"
    assert calls == [["/usr/bin/paplay", str(sound)]]

    assert setup_ui._play_welcome_chime(
        str(script), finder=lambda _name: "/broken/player",
        starter=lambda _argv: (_ for _ in ()).throw(OSError("no audio"))) == ""


def test_linux_setup_has_seven_pages_automatic_chime_and_navigation_contract():
    source = open(setup_ui.__file__, encoding="utf-8").read()
    assert "dialog.set_default_size(900, 680)" in source
    assert "dialog.set_size_request(760, 600)" in source
    assert "Play a short welcome chime" not in source
    assert "_play_welcome_chime(script_directory)" in source
    assert 'skip_button = bind(Gtk.Button(), "Skip assistant")' in source
    assert 'manual_button = bind(Gtk.Button(), "Manual")' in source
    assert "pages = (welcome, address, sources, phone, registers, backup, finish)" in source
    assert 'next_button.set_label(tr("Start Magnolie") if index == 6 else tr("Next"))' in source
    assert 'progress_accessible.set_description' in source
    assert "GdkPixbuf.Pixbuf.new_from_file_at_scale(logo, 82, 82, True)" in source
    assert "image.set_pixel_size" not in source


def test_setup_language_is_validated_and_persisted_without_losing_settings(tmp_path):
    path = tmp_path / "config" / "locale.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"language": "de", "hourCycle": "h23"}),
                    encoding="utf-8")
    setup_ui._persist_language("zh_CN", str(path))
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value == {"hourCycle": "h23", "language": "zh_CN"}
    assert setup_ui._read_language(str(path)) == "zh_CN"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        setup_ui._persist_language("invalid", str(path))


def test_setup_translation_honors_packaged_locale_directories(tmp_path, monkeypatch):
    app_bin = tmp_path / "app" / "bin"
    packaged = tmp_path / "app" / "share" / "locale"
    app_bin.mkdir(parents=True)
    packaged.mkdir(parents=True)
    selected = []

    def translation(_domain, localedir, languages, fallback):
        selected.append((localedir, languages, fallback))
        return type("Translation", (), {"gettext": staticmethod(lambda value: value)})()

    monkeypatch.delenv("MAGNOLIE_LOCALE_DIR", raising=False)
    monkeypatch.setattr(setup_ui.gettext, "translation", translation)
    setup_ui._translation("de", str(app_bin))
    assert selected[-1] == (str(packaged), ["de"], True)

    explicit = tmp_path / "AppDir" / "usr" / "share" / "locale"
    explicit.mkdir(parents=True)
    monkeypatch.setenv("MAGNOLIE_LOCALE_DIR", str(explicit))
    setup_ui._translation("de", str(app_bin))
    assert selected[-1] == (str(explicit), ["de"], True)


def test_linux_setup_declares_all_specified_option_ids():
    source = open(setup_ui.__file__, encoding="utf-8").read()
    for option in (
            "evolution", "thunderbird",
            "tasks", "addresses", "notes", "anniversaries",
            "planner", "health", "manual", "daily", "weekly", "monthly",
            "last-name", "first-name"):
        assert repr(option) in source or ('"%s"' % option) in source


def test_setup_stores_stable_german_region_codes():
    assert [code for code, _name in setup_ui.GERMAN_REGIONS] == [
        "DE-BW", "DE-BY", "DE-BE", "DE-BB", "DE-HB", "DE-HH", "DE-HE", "DE-NI",
        "DE-MV", "DE-NW", "DE-RP", "DE-SL", "DE-SN", "DE-ST", "DE-SH", "DE-TH"]
    source = open(setup_ui.__file__, encoding="utf-8").read()
    assert "state.get_active_id()" in source


def test_failed_adoption_is_not_misclassified_as_fresh(monkeypatch, tmp_path):
    marker = tmp_path / "config" / setup.MARKER_NAME
    evidence = tmp_path / "data"
    evidence.mkdir()
    (evidence / "daten.json").write_text("broken", encoding="utf-8")
    monkeypatch.setattr(setup, "write_state", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(PermissionError("read-only")))
    assert setup.classify_and_adopt(str(marker), (str(evidence),)) == "damaged"
    assert not setup.services_allowed("damaged")


def test_unreadable_existing_directory_is_never_fresh(monkeypatch, tmp_path):
    evidence = tmp_path / "data"
    evidence.mkdir()
    original = os.listdir
    monkeypatch.setattr(os, "listdir", lambda path: (
        (_ for _ in ()).throw(PermissionError("unreadable"))
        if os.fspath(path) == str(evidence) else original(path)))
    assert setup.classify(str(tmp_path / "marker"), (str(evidence),)) == "existing"


@pytest.mark.parametrize("argument", (
    "--background-service", "--tray-start", "--wecker", "--erinnerung"))
def test_background_and_autostart_gate_exit_without_services(tmp_path, argument):
    environment = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "config"),
                       XDG_DATA_HOME=str(tmp_path / "data"),
                       XDG_STATE_HOME=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, os.path.join(BIN, "magnolie-organizer"),
                             argument], env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            timeout=10)
    assert result.returncode == 0
    assert not (tmp_path / "data" / "magnolie-organizer").exists()
    assert not (tmp_path / "state" / "magnolie-organizer").exists()
    assert not (tmp_path / "config" / "magnolie-organizer" /
                setup.MARKER_NAME).exists()


def test_transport_check_precedes_setup_which_precedes_services_and_window():
    source = open(os.path.join(BIN, "magnolie-organizer"), encoding="utf-8").read()
    start = source.index("if setup_assistant_required(_SETUP_STARTZUSTAND):")
    transport = source.index("transport = browser_transport_waehlen(")
    missing = source.index('if transport == "fehlt":', transport)
    assert transport < missing < start
    assert start < source.index("systemkalender_bereinigen()", start)
    assert start < source.index("einzelinstanz_anmelden(", start)
    assert start < source.index("fenster = Fenster(web_verzeichnis,", start)


def test_setup_handbook_is_forwarded_only_to_visible_window_path():
    source = open(os.path.join(BIN, "magnolie-organizer"), encoding="utf-8").read()
    setup_call = source.index("setup_auswahl = run_setup(")
    window = source.index("fenster = Fenster(web_verzeichnis,", setup_call)
    display = source.index("fenster.zeige_wenn_bereit(", window)
    callback = source.index("def setup_aktionen_nach_start():", window)
    handbook = source.index('setup_auswahl.get("openHandbook") is True', callback)
    assert setup_call < window < callback < handbook < display
    assert 'self.connect("map-event", nach_anzeigen_planen)' in source


def test_restore_request_becomes_operational_only_after_window_display():
    source = open(os.path.join(BIN, "magnolie-organizer"), encoding="utf-8").read()
    window = source.index("fenster = Fenster(web_verzeichnis,")
    callback = source.index("def setup_aktionen_nach_start():", window)
    restore = source.index('setup_auswahl.get("restoreRequest") is True', callback)
    display = source.index("fenster.zeige_wenn_bereit(", restore)
    assert window < callback < restore < display
    assert "allgemein-sicherung-wiederherstellen" in source[restore:display]


def _load_launcher(name):
    path = os.path.join(BIN, "magnolie-organizer")
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_missing_transport_exits_before_setup_or_pending_marker(monkeypatch):
    launcher = _load_launcher("magorg_setup_missing_transport")
    calls = []
    monkeypatch.setattr(launcher.sys, "argv",
                        ["magnolie-organizer", "--language", "en"])
    monkeypatch.setattr(launcher.sys, "stderr", io.StringIO())
    monkeypatch.setattr(launcher, "_SETUP_STARTZUSTAND", "fresh")
    monkeypatch.setattr(launcher, "GTK_OK", True)
    monkeypatch.setattr(launcher, "WEBKIT_OK", False)
    monkeypatch.setattr(launcher, "WEBKIT_FEHLER", "missing WebKit transport")
    monkeypatch.setattr(launcher, "chromium_finden", lambda: None)
    monkeypatch.setattr(launcher, "appimage_laufzeit", lambda: False)
    monkeypatch.setattr(launcher, "setup_write_state",
                        lambda *_args: calls.append("pending"))
    monkeypatch.setattr(setup_ui, "run_setup",
                        lambda *_args: calls.append("setup"))
    monkeypatch.setattr(launcher, "systemkalender_bereinigen",
                        lambda: calls.append("cleanup"))

    with pytest.raises(SystemExit) as exit_info:
        launcher.haupt()

    assert exit_info.value.code == 1
    assert calls == []
    assert "Magnolie Organizer requires GTK 3 and WebKit2GTK." in \
        launcher.sys.stderr.getvalue()
    assert "Error: missing WebKit transport" in launcher.sys.stderr.getvalue()


def test_pending_marker_write_failure_is_shown_before_setup(monkeypatch):
    launcher = _load_launcher("magorg_setup_pending_write_failure")
    events = []

    class FakeDialog:
        def __init__(self, **values):
            events.append(("dialog", values["text"]))

        def format_secondary_text(self, text):
            events.append(("detail", text))

        def run(self):
            events.append("run")

        def destroy(self):
            events.append("destroy")

    class FakeGtk:
        MessageDialog = FakeDialog
        MessageType = type("MessageType", (), {"ERROR": "error"})
        ButtonsType = type("ButtonsType", (), {"CLOSE": "close"})

    monkeypatch.setattr(launcher.sys, "argv", ["magnolie-organizer"])
    monkeypatch.setattr(launcher, "setup_classify_and_adopt", lambda: "fresh")
    monkeypatch.setattr(launcher, "GTK_OK", True)
    monkeypatch.setattr(launcher, "WEBKIT_OK", True)
    monkeypatch.setattr(launcher, "Gtk", FakeGtk)
    monkeypatch.setattr(launcher, "setup_write_state",
                        lambda *_args: (_ for _ in ()).throw(PermissionError("read-only")))
    monkeypatch.setattr(setup_ui, "run_setup", lambda *_args: events.append("setup"))

    launcher.haupt()

    assert events == [
        ("dialog", launcher._("Warning: The data could not be saved.")),
        ("detail", "read-only"), "run", "destroy"]


def test_setup_language_reaches_gettext_regional_state_and_web_window_same_session(
        monkeypatch, tmp_path):
    launcher = _load_launcher("magorg_setup_same_session_language")
    events = []
    observed = {}

    class FakeGLib:
        @staticmethod
        def set_prgname(_name):
            pass

        @staticmethod
        def set_application_name(_name):
            pass

    class FakeGtk:
        @staticmethod
        def main():
            events.append("main")

    class FakeApplication:
        def release(self):
            events.append("release")

    class FakeWindow:
        def __init__(self, _web_directory, setup_auswahl=None):
            events.append("window")
            observed["setup"] = setup_auswahl
            observed["language"] = launcher._REGIONAL["language"]
            observed["gettext"] = launcher._("Usage:")

        def zeige_wenn_bereit(self, nach_anzeigen=None):
            observed["after_show"] = nach_anzeigen

    def run_setup(*_args, **_kwargs):
        events.append("setup")
        return {"language": "fr", "openHandbook": False}

    monkeypatch.setattr(launcher.sys, "argv", ["magnolie-organizer"])
    monkeypatch.setattr(launcher, "setup_classify_and_adopt", lambda: "fresh")
    monkeypatch.setattr(launcher, "GTK_OK", True)
    monkeypatch.setattr(launcher, "WEBKIT_OK", True)
    monkeypatch.setattr(launcher, "GLib", FakeGLib)
    monkeypatch.setattr(launcher, "Gtk", FakeGtk)
    monkeypatch.setattr(launcher, "setup_write_state", lambda *_args: None)
    monkeypatch.setattr(setup_ui, "run_setup", run_setup)
    monkeypatch.setattr(launcher, "systemkalender_bereinigen",
                        lambda: events.append("cleanup"))
    monkeypatch.setattr(launcher, "einzelinstanz_anmelden",
                        lambda *_args: (FakeApplication(), False))
    monkeypatch.setattr(launcher, "finde_web_verzeichnis", lambda: str(tmp_path))
    monkeypatch.setattr(launcher, "Fenster", FakeWindow)

    launcher.haupt()

    assert events[:3] == ["setup", "cleanup", "window"]
    assert observed["language"] == "fr"
    assert observed["gettext"] == launcher.gettext_uebersetzung("fr").gettext("Usage:")
    assert observed["gettext"] != "Usage:"
    assert observed["setup"] == {"language": "fr", "openHandbook": False}
