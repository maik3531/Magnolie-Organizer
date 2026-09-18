"""Real GTK controls/loop and offline provider contracts, no host services."""
import ast
import gettext
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import magnolie_setup_ui as ui
import magnolie_setup_state as state_store

QUESTION = "Show school holidays for %(state)s in the calendar?"
UNAVAILABLE = "School holidays are not available for this region."
NOTICE = "The information is retrieved once from the open directory openholidaysapi.org and then kept in the organizer. The application therefore needs an internet connection only once."
LANGUAGES = [code for code, _ in ui.LANGUAGES if code != "system"]


def descendants(widget):
    yield widget
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            yield from descendants(child)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("ending", ["finish", "cancel", "skip"])
def test_actual_gtk_region_consent(tmp_path, monkeypatch, language, ending):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
    assert Gtk.init_check()[0], "Run with xvfb-run for actual GTK setup"
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    monkeypatch.setattr(ui, "_read_language", lambda: language)
    monkeypatch.setattr(ui, "_play_welcome_chime", lambda *_: None)
    monkeypatch.setattr(ui, "_persist_language", lambda *_: None)
    tr = ui._translation(language, str(ROOT / "bin"))
    calls, failures = [], []
    marker = tmp_path / "setup-state.json"

    def save(status, selections):
        calls.append((status, selections))
        state_store.write_state(status, selections, str(marker))

    def drive():
        dialog = next(w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.Dialog))
        try:
            widgets = list(descendants(dialog))
            country = next(w for w in widgets if w.get_name() == "setup-country")
            region = next(w for w in widgets if w.get_name() == "setup-state")
            check = next(w for w in widgets if w.get_name() == "setup-school-holidays")
            assert not check.get_active() and not check.get_visible()
            country.set_active_id("DE")
            assert region.set_active_id("DE-SN")
            assert check.get_visible() and not check.get_active()
            assert check.get_label() == tr(QUESTION) % {"state": tr("Saxony")}
            assert "%(state)s" not in check.get_label()
            check.set_active(True)
            region.set_active_id("DE-BY")
            assert not check.get_active() and tr("Bavaria") in check.get_label()
            region.set_active_id("DE-SN")
            assert not check.get_active(), "Returning to old state needs fresh consent"
            for territory, code, name in (("AT", "AT-9", "Vienna"), ("CH", "CH-ZH", "Zurich")):
                check.set_active(True)
                country.set_active_id(territory)
                assert not check.get_active() and not check.get_visible()
                region.set_active_id(code)
                assert check.get_visible() and check.get_label() == tr(QUESTION) % {"state": tr(name)}
            for territory, typed in (("AT", "DE-SN"), ("DE", "Unknown region"), ("FR", "Paris")):
                country.set_active_id(territory)
                region.set_active(-1)
                region.get_child().set_text(typed)
                assert not check.get_visible() and not check.get_active()
                assert any(isinstance(w, Gtk.Label) and w.get_visible() and w.get_text() == tr(UNAVAILABLE) for w in widgets)
            country.set_active_id("DE")
            region.set_active_id("DE-SN")
            check.set_active(True)
            languages = next(w for w in widgets if w.get_name() == "setup-language")
            alternate = "de" if language != "de" else "en"
            languages.set_active_id(alternate)
            assert check.get_active(), "A language-only refresh must retain consent to the same code"
            other_tr = ui._translation(alternate, str(ROOT / "bin"))
            assert check.get_label() == other_tr(QUESTION) % {"state": other_tr("Saxony")}
            languages.set_active_id(language)
            assert check.get_label() == tr(QUESTION) % {"state": tr("Saxony")}
            assert not calls and not marker.exists(), "Consent is only staged"
            if ending == "cancel": dialog.response(Gtk.ResponseType.CANCEL)
            elif ending == "skip":
                dialog.response(1)
                GLib.idle_add(lambda: (dialog.response(3), False)[1])
            else:
                steps = [0]
                def next_page():
                    steps[0] += 1
                    dialog.response(2)
                    return steps[0] < 6
                GLib.timeout_add(10, next_page)
        except BaseException as error:
            failures.append(error)
            dialog.response(Gtk.ResponseType.CANCEL)
        return False

    def address_page():
        dialog = next(w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.Dialog))
        dialog.response(2)
        GLib.idle_add(drive)
        return False
    GLib.idle_add(address_page)
    result = ui.run_setup(Gtk, Gdk, tr, save, str(ROOT / "bin"))
    if failures: raise failures[0]
    if ending == "cancel":
        assert result is None and not calls and not marker.exists()
    else:
        persisted = json.loads(marker.read_text())["selections"]
        assert len(calls) == 1
        assert persisted["schoolHolidays"] is (ending == "finish")
        assert persisted["schoolHolidayRegion"] == ("DE-SN" if ending == "finish" else "")
        if ending == "skip": assert persisted["setupSkipped"] is True


def test_all_catalog_artifacts_and_placeholders():
    windows = ROOT.parent / "magnolie-organizer-windows"
    native = json.loads((windows / "app/native-i18n.json").read_text())["locales"]
    assert len(LANGUAGES) == 20 and len(native) == 19
    sys.path.insert(0, str(ROOT / "werkzeuge"))
    from po_zu_js import katalog_lesen
    for project, app in ((ROOT, ROOT), (windows, windows / "app")):
        pot = (app / "po/magnolie-organizer.pot").read_text()
        assert QUESTION in pot and UNAVAILABLE in pot
        for language in LANGUAGES:
            if language == "en": continue
            catalog = katalog_lesen(str(app / "po" / (language + ".po")))["messages"]
            web = (app / "web/i18n" / (language + ".js")).read_text()
            for key in (QUESTION, UNAVAILABLE, NOTICE, "The holidays were imported.",
                        "The service returned no entries for this selection."):
                assert catalog[key] and catalog[key] != key, (project, language, key)
                assert re.findall(r"%\([^)]+\)s", catalog[key]) == re.findall(r"%\([^)]+\)s", key)
                assert json.dumps(catalog[key], ensure_ascii=False) in web
                assert native[language][key] == catalog[key]
            with (ROOT / "locale" / language / "LC_MESSAGES/magnolie-organizer.mo").open("rb") as stream:
                mo = gettext.GNUTranslations(stream)
            assert mo.gettext(QUESTION) == catalog[QUESTION]
            for country, regions in ui.REGIONS_BY_COUNTRY.items():
                for code, name in regions:
                    assert ui.school_holiday_region(country, code, mo.gettext) == (code, mo.gettext(name))
                    assert ui.school_holiday_region(country, mo.gettext(name), mo.gettext)[0] == code


@pytest.mark.parametrize("country,region", [("DE", "DE-SN"), ("AT", "AT-9"), ("CH", "CH-ZH")])
def test_actual_provider_url_and_empty_availability(country, region):
    # Compile actual provider functions only: importing the application would initialize host services.
    source = ast.parse((ROOT / "bin/magnolie-organizer").read_text())
    names = {"feiertage_abrufen", "_openholidays_auswerten", "_name_waehlen", "_feiertag_sprache"}
    code = ast.Module(body=[node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    scope = dict(json=json, _=lambda x: x, ngettext=lambda one, many, n: one if n == 1 else many,
                 _REGIONAL={"language": "en"}, _ist_iso=lambda x: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)),
                 FEIERTAG_DIENST="https://openholidaysapi.org", FEIERTAG_ABRUF_MAX=8 * 1024 * 1024,
                 GroessenFehler=type("GroessenFehler", (RuntimeError,), {}), kanonischer_text=str.casefold)
    exec(compile(code, "actual-holiday-provider", "exec"), scope)
    urls = []
    def fetch(url):
        urls.append(url)
        return "[]"  # No invented holiday records: empty/unavailable remains empty.
    result = scope["feiertage_abrufen"](country, region, [2026], True, fetch)
    assert result["feiertage"] == []
    assert result["bericht"] == "The service returned no entries for this selection."
    assert len(urls) == 2 and "/SchoolHolidays?" in urls[1]
    assert all("countryIsoCode=" + country in url and "subdivisionCode=" + region in url for url in urls)
    urls.clear()
    scope["feiertage_abrufen"](country, region, [2026], False, fetch)
    assert len(urls) == 1 and "SchoolHolidays" not in urls[0]
    urls.clear()
    with pytest.raises(RuntimeError, match="not available"):
        scope["feiertage_abrufen"](country, "US-XX", [2026], True, fetch)
    assert not urls
