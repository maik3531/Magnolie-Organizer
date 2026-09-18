import base64
import importlib.machinery
import importlib.util
import json
import sqlite3
from pathlib import Path


PROGRAM = Path(__file__).parents[1] / "bin" / "magnolie-organizer"
loader = importlib.machinery.SourceFileLoader("magnolie_tb_contacts", str(PROGRAM))
spec = importlib.util.spec_from_loader("magnolie_tb_contacts", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
FIXTURE = Path(__file__).parents[2] / "contracts" / "thunderbird-addressbook-fixture.json"
if not FIXTURE.is_file():
    FIXTURE = Path(__file__).parents[1] / "contracts" / "thunderbird-addressbook-fixture.json"


def make_book(path, fixture):
    path.parent.mkdir(parents=True, exist_ok=True)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    (path.parent / "Photos").mkdir(exist_ok=True)
    (path.parent / "Photos" / "real.png").write_bytes(png)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE properties (card TEXT, name TEXT, value TEXT)")
        db.executemany("INSERT INTO properties VALUES (?,?,?)",
                       [(fixture["card"], name, value)
                        for name, value in fixture["properties"]])


def test_profiles_history_complete_fields_and_namespaced_identity(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    root = tmp_path / ".thunderbird"
    relative = root / "Profiles" / "relative.default"
    absolute = tmp_path / "custom profile"
    make_book(relative / "history.sqlite", fixture)
    make_book(absolute / "abook-2.sqlite", fixture)
    root.mkdir(exist_ok=True)
    (root / "profiles.ini").write_text(
        "[Profile0]\nIsRelative=1\nPath=Profiles/relative.default\n"
        f"[Profile1]\nIsRelative=0\nPath={absolute}\n", encoding="utf-8")

    assert m._thunderbird_profile(tmp_path) == [str(relative), str(absolute)]
    result = m.lokal_scannen(tmp_path, True, "thunderbird")
    assert result["geburtstage"] == []
    assert len(result["kontakte"]) == 2
    assert len({contact["uid"] for contact in result["kontakte"]}) == 2
    expected = fixture["expected"]
    for contact in result["kontakte"]:
        assert contact["nachname"] == expected["lastName"]
        assert contact["vorname"] == expected["firstName"]
        assert len(contact["emailEintraege"]) == expected["emailCount"]
        assert len(contact["telefone"]) == expected["phoneCount"]
        assert len(contact["anschriften"]) == expected["addressCount"]
        assert {address["region"] for address in contact["anschriften"]} == {"Berlin", "Brandenburg"}
        assert {address["land"] for address in contact["anschriften"]} == {"Germany"}
        assert contact["notiz"] == "Complete Thunderbird note"
        assert contact["foto"].startswith("data:image/png;base64,")
        assert contact["geburtstag"] == expected["birthday"]
        assert contact["jubilaeum"] == expected["anniversary"]


def test_unknown_source_never_broadens_import(tmp_path):
    try:
        m.lokal_scannen(tmp_path, True, "unknown")
    except ValueError:
        return
    raise AssertionError("unknown source broadened local import")


def test_yearly_thunderbird_occasion_classification_is_conservative():
    def event(uid, title, category):
        return ("BEGIN:VEVENT\r\nUID:%s\r\nDTSTART;VALUE=DATE:20200607\r\n"
                "DTEND;VALUE=DATE:20200608\r\nSUMMARY:%s\r\nCATEGORIES:%s\r\n"
                "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\n" % (uid, title, category))
    text = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + \
        event("birthday", "Van Dame Birthday", "Birthday") + \
        event("anniversary", "Van Dame Anniversary", "Anniversary") + \
        event("arbitrary", "Annual planning", "Anniversary") + "END:VCALENDAR\r\n"
    result = m._tb_jahrestage_klassifizieren(m.ics_lesen(text, "Thunderbird"))
    assert {(item["uid"], item["typ"]) for item in result["jahrestage"]} == {
        ("birthday", "birthday"), ("anniversary", "anniversary")}
    assert [item["uid"] for item in result["termine"]] == ["arbitrary"]
