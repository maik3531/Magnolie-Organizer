"""#450: actual DAV orchestration against bounded, synthetic in-memory resources."""
import copy

import pytest

from test_nextcloud import m, SyncDav, empty_data, event_ics, task_ics, run_sync


class SavedDav(SyncDav):
    def put(self, href, data, etag=None, create=False):
        super().put(href, data, etag, create)
        saved = next((item for item in self.resources["calendar"] if item["href"] == href), None)
        version = '"saved-%d"' % len(self.puts)
        if saved is None:
            self.resources["calendar"].append(dict(href=href, data=data, etag=version))
        else:
            assert saved["etag"] == etag and not create
            saved.update(data=data, etag=version)
        return version


def initial_snapshot(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    text = event_ics(rrule="") if kind == "termine" else task_ics()
    dav = SavedDav({"calendar": [dict(href="https://cloud.example/calendar/synthetic.ics",
                                   data=text, etag='"v1"')], "addressbook": []})
    data = run_sync(monkeypatch, dav, empty_data()).payload
    assert data["ok"] and len(data[kind]) == 1 and not dav.puts and not dav.deletes
    return dav, data


@pytest.mark.parametrize("kind", ["termine", "aufgaben"])
def test_colour_only_set_change_remove_and_stable_followup(monkeypatch, tmp_path, kind):
    dav, data = initial_snapshot(monkeypatch, tmp_path, kind)
    for colour in ("#112233", "#abcdef", ""):
        data = copy.deepcopy(data)
        data[kind][0]["akzentFarbe"] = colour
        data[kind][0]["geaendert"] += 1000
        before = len(dav.puts)
        data = run_sync(monkeypatch, dav, data).payload
        assert data["ok"] and len(dav.puts) == before + 1
        assert dav.puts[-1][2] and not dav.puts[-1][3]
        parsed = m.ics_lesen(dav.resources["calendar"][0]["data"])[kind][0]
        assert parsed.get("akzentFarbe", "") == colour
        assert data[kind][0].get("akzentFarbe", "") == colour
        for _ in range(3):
            data = run_sync(monkeypatch, dav, data).payload
            assert data["ok"] and len(dav.puts) == before + 1 and not dav.deletes


@pytest.mark.parametrize("kind,legacy", [("termine", "linux-calendar-2"), ("termine", "linux-1"), ("aufgaben", "linux-1")])
@pytest.mark.parametrize("remote_changed", [False, True])
def test_legacy_baseline_preserves_unrepresented_local_colour(monkeypatch, tmp_path, kind, legacy, remote_changed):
    dav, data = initial_snapshot(monkeypatch, tmp_path, kind)
    item = data[kind][0]
    fields = m.TERMIN_FELDER if kind == "termine" else m.AUFGABE_FELDER
    source, baseline = next(iter(item["syncQuellen"].items()))
    baseline.update(inhaltFormat=legacy, inhaltSha256=m._sync_inhalt_hash(item, fields))
    item["akzentFarbe"] = "#112233"
    # This is precisely the shipped blind spot: a formerly clean legacy hash.
    assert baseline["inhaltSha256"] == m._sync_inhalt_hash(item, fields)
    if remote_changed:
        dav.resources["calendar"][0]["etag"] = '"v2"'
    result = run_sync(monkeypatch, dav, data).payload
    assert result["ok"] and not dav.deletes
    assert any(value.get("akzentFarbe") == "#112233" for value in result[kind])
    assert len(result[kind]) == 2, "Legacy disagreement must preserve a separate local variant"
    assert any(not value.get("akzentFarbe") for value in result[kind])


@pytest.mark.parametrize("kind", ["termine", "aufgaben"])
def test_rejected_colour_put_does_not_advance_baseline(monkeypatch, tmp_path, kind):
    dav, data = initial_snapshot(monkeypatch, tmp_path, kind)
    before = copy.deepcopy(data[kind][0]["syncQuellen"])
    data[kind][0]["akzentFarbe"] = "#112233"
    dav.fail_put = True
    result = run_sync(monkeypatch, dav, data).payload
    assert not result["ok"] and dav.puts and not dav.deletes
    assert data[kind][0]["syncQuellen"] == before


@pytest.mark.parametrize("kind", ["termine", "aufgaben"])
def test_remote_colour_is_adopted_without_a_return_put(monkeypatch, tmp_path, kind):
    dav, data = initial_snapshot(monkeypatch, tmp_path, kind)
    uid = data[kind][0]["uid"]
    for colour in ("#112233", "#abcdef", ""):
        original = event_ics(rrule="") if kind == "termine" else task_ics()
        marker = "END:VEVENT" if kind == "termine" else "END:VTODO"
        resource = dav.resources["calendar"][0]
        resource["data"] = original.replace(marker, "X-MAGNOLIE-ACCENT-COLOR:" + colour + "\r\n" + marker) if colour else original
        resource["etag"] += "-remote"
        data = run_sync(monkeypatch, dav, data).payload
        assert data["ok"] and len(data[kind]) == 1
        assert data[kind][0]["uid"] == uid and data[kind][0].get("akzentFarbe", "") == colour
        assert not dav.puts and not dav.deletes


@pytest.mark.parametrize("fields,legacy,vector,current", [
    (m.TERMIN_FELDER, "linux-calendar-2", "0a30a3a485b41501435b5a86297d6414e71a6b5bbdef3cb8ca6347750d78cadd", "linux-calendar-3"),
    (m.AUFGABE_FELDER, "linux-1", "c822818224f6f4282d30cd03ef050a5e6efa2ab7d17251f64fa123be7b02ee5f", "linux-task-2"),
])
def test_explicit_new_formats_do_not_redefine_shipped_hashes(fields, legacy, vector, current):
    assert m._sync_inhalt_format(fields) == legacy
    assert m._sync_inhalt_hash({}, fields) == vector
    assert m._sync_inhalt_hash({"akzentFarbe": "#112233"}, fields) == vector
    assert m._sync_dav_inhalt_format(fields) == current
    blank = m._sync_dav_inhalt_hash({}, fields)
    assert blank == m._sync_dav_inhalt_hash({"akzentFarbe": ""}, fields)
    assert blank == m._sync_dav_inhalt_hash({"akzentFarbe": None, "icsRoundtrip": []}, fields)
    assert blank != m._sync_dav_inhalt_hash({"akzentFarbe": "#112233"}, fields)
    assert m._sync_dav_inhalt_hash({"akzentFarbe": "#abcdef"}, fields) == m._sync_dav_inhalt_hash({"akzentFarbe": "#ABCDEF"}, fields)
    assert m._sync_dav_inhalt_hash({"akzentFarbe": "#112233"}, fields) == m._sync_dav_inhalt_hash(
        {"akzentFarbe": "#112233", "icsRoundtrip": ["X-MAGNOLIE-ACCENT-COLOR:#112233"]}, fields)


def test_task_category_is_also_covered_by_the_export_projection(monkeypatch, tmp_path):
    dav, data = initial_snapshot(monkeypatch, tmp_path, "aufgaben")
    for value in ("Synthetic category", "Changed category", ""):
        data["aufgaben"][0]["kategorien"] = value
        before = len(dav.puts)
        data = run_sync(monkeypatch, dav, data).payload
        assert data["ok"] and len(dav.puts) == before + 1
        assert m.ics_lesen(dav.resources["calendar"][0]["data"])["aufgaben"][0]["kategorien"] == value
        data = run_sync(monkeypatch, dav, data).payload
        assert data["ok"] and len(dav.puts) == before + 1 and not dav.deletes


@pytest.mark.parametrize("kind", ["termine", "aufgaben"])
def test_parameterized_colour_is_preserved_or_explicitly_rejected(kind):
    source = event_ics(rrule="") if kind == "termine" else task_ics()
    marker = "END:VEVENT" if kind == "termine" else "END:VTODO"
    opaque = "X-MAGNOLIE-ACCENT-COLOR;X-SYNTHETIC=keep:#112233"
    source = source.replace(marker, opaque + "\r\n" + marker)
    item = m.ics_lesen(source)[kind][0]
    writer = m.ics_schreiben_termine if kind == "termine" else m.ics_schreiben_aufgaben
    assert opaque in writer([item])
    for colour in ("#abcdef", ""):
        changed = copy.deepcopy(item)
        changed["akzentFarbe"] = colour
        with pytest.raises(RuntimeError):
            writer([changed])
    assert item["akzentFarbe"] == "#112233"


@pytest.mark.parametrize("field,value", [
    ("icsAusnahmen", ["2026-08-20"]), ("icsEndeFehlt", True), ("icsNullDauer", True),
])
def test_additional_event_export_fields_are_not_hash_blind_spots(field, value):
    assert m._sync_dav_inhalt_hash({}, m.TERMIN_FELDER) != m._sync_dav_inhalt_hash({field: value}, m.TERMIN_FELDER)


@pytest.mark.parametrize("kind", ["termine", "aufgaben"])
def test_protected_colour_dav_edit_never_sends_partial_resource(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(m, "daten_verzeichnis", lambda: str(tmp_path))
    text = event_ics(rrule="") if kind == "termine" else task_ics()
    marker = "END:VEVENT" if kind == "termine" else "END:VTODO"
    text = text.replace(marker, "X-MAGNOLIE-ACCENT-COLOR;X-SYNTHETIC=keep:#112233\r\n" + marker)
    dav = SavedDav({"calendar": [dict(href="https://cloud.example/calendar/protected.ics", etag='"v1"', data=text)], "addressbook": []})
    data = run_sync(monkeypatch, dav, empty_data()).payload
    before = copy.deepcopy(data[kind][0]["syncQuellen"])
    data[kind][0]["akzentFarbe"] = "#abcdef"
    result = run_sync(monkeypatch, dav, data).payload
    assert not result["ok"] and not dav.puts and not dav.deletes
    assert dav.resources["calendar"][0]["data"] == text
    assert data[kind][0]["syncQuellen"] == before
