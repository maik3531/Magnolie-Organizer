"""Native import preservation; optional actual frontend gate, never expected loss."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = ROOT / "Magnolie-Organizer-Windows-2.0.0"


@pytest.fixture(scope="module")
def native():
    loader = importlib.machinery.SourceFileLoader("native_pathways", str(
        ROOT / "magnolie-organizer-2.0.0/bin/magnolie-organizer"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module._REGIONAL["timeZone"] = "UTC"
    return module


@pytest.fixture(scope="module")
def windows(tmp_path_factory):
    dotnet = os.environ.get("MAGNOLIE_DOTNET") or shutil.which("dotnet")
    if not dotnet:
        pytest.skip("Set MAGNOLIE_DOTNET to run the current Windows native source")
    build = tmp_path_factory.mktemp("native-import-dotnet")
    source = WINDOWS / "tests/native-import"
    for name in ("NativeImportProbe.csproj", "Program.cs.txt"):
        shutil.copyfile(source / name, build / name)
    # Compile the current contact models, not the unrelated online sync engine.
    models = (WINDOWS / "ContactSyncModels.cs").read_text(encoding="utf-8")
    (build / "ContactModels.cs").write_text(models.split("internal sealed class ContactSyncEngine", 1)[0], encoding="utf-8")
    env = dict(os.environ, HOME=str(build), DOTNET_CLI_HOME=str(build),
               DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_CLI_TELEMETRY_OPTOUT="1", TZ="UTC")
    subprocess.run([dotnet, "build", str(build / "NativeImportProbe.csproj"),
                    "--nologo", "-v:q", "-p:SourceRoot=" + str(WINDOWS)], env=env, check=True)

    def invoke(**request):
        result = subprocess.run([dotnet, str(build / "bin/Debug/net8.0/NativeImportProbe.dll")],
                                input=json.dumps(request), text=True, capture_output=True, env=env, check=True)
        return json.loads(result.stdout)
    return invoke


def calendar(body):
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + body + "\nEND:VCALENDAR\n"


OCCASION = calendar("BEGIN:VEVENT\nUID:occasion\nDTSTART;VALUE=DATE:20000607\n"
    "RRULE:FREQ=YEARLY\nX-MAGNOLIE-TYPE-ID:anniversary\nX-MAGNOLIE-DATE:--06-07\n"
    "SUMMARY:Anniversary\nDESCRIPTION:Keep this note\nLOCATION:Keep this room\n"
    "BEGIN:VALARM\nACTION:DISPLAY\nDESCRIPTION:Alarm description\nTRIGGER:-P1D\nEND:VALARM\nEND:VEVENT")
TASKS = calendar("BEGIN:VTODO\nUID:family\nSUMMARY:Master\nDTSTART;VALUE=DATE:20260910\n"
    "DUE;VALUE=DATE:20260910\nRRULE:FREQ=DAILY;COUNT=3\nEND:VTODO\n"
    "BEGIN:VTODO\nUID:family\nRECURRENCE-ID;VALUE=DATE:20260911\nSUMMARY:Moved\n"
    "DTSTART;VALUE=DATE:20260912\nDUE;VALUE=DATE:20260912\nEND:VTODO")
ZONE = calendar("BEGIN:VTIMEZONE\nTZID:Custom/Two\nBEGIN:STANDARD\nDTSTART:19700101T000000\n"
    "TZOFFSETFROM:+0200\nTZOFFSETTO:+0200\nEND:STANDARD\nEND:VTIMEZONE\n"
    "BEGIN:VEVENT\nUID:custom-zone\nDTSTART;TZID=Custom/Two:20260910T100000\n"
    "DTEND;TZID=Custom/Two:20260910T110000\nSUMMARY:Zone event\nEND:VEVENT")


def assert_occasion(text):
    assert text.count("DESCRIPTION:Keep this note") == 1
    assert text.count("LOCATION:Keep this room") == 1
    assert text.count("BEGIN:VALARM") == 1
    assert text.count("DESCRIPTION:Alarm description") == 1


def test_linux_occasion(native):
    item = native.ics_lesen(OCCASION)["jahrestage"][0]
    assert item["notiz"] == "Keep this note"
    assert_occasion(native.ics_schreiben_jahrestage([item]))


def test_linux_task_export_uid(native):
    items = native.ics_lesen(TASKS)["aufgaben"]
    text = native.ics_schreiben_aufgaben(items)
    assert text.count("UID:family\r\n") == 2
    assert text.count("RECURRENCE-ID") == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_linux_thunderbird_task_identity(native, tmp_path, cancelled):
    path = tmp_path / "local.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE cal_todos (cal_id TEXT,id TEXT,title TEXT,todo_entry INTEGER,"
                   "todo_entry_tz TEXT,todo_due INTEGER,todo_due_tz TEXT,flags INTEGER,recurrence_id INTEGER,recurrence_id_tz TEXT)")
        stamp = lambda day: int(native.datetime(2026, 9, day, tzinfo=native.timezone.utc).timestamp() * 1000000)
        db.executemany("INSERT INTO cal_todos VALUES (?,?,?,?,?,?,?,?,?,?)", [
            ("c", "family", "Master", stamp(10), "floating", stamp(10), "floating", 24, None, None),
            ("c", "family", "Moved", stamp(12), "floating", stamp(12), "floating", 520, stamp(11), "floating")])
        if cancelled:
            db.execute("ALTER TABLE cal_todos ADD COLUMN ical_status TEXT")
            db.execute("UPDATE cal_todos SET ical_status='CANCELLED' WHERE title='Moved'")
    items = native._tb_normalisierte_kalenderdaten(str(path))["aufgaben"]
    assert len({item["uid"] for item in items}) == 2
    moved = next(item for item in items if item["titel"] == "Moved")
    assert moved["icsSerienUid"] == "family"
    text = native.ics_schreiben_aufgaben(items)
    assert text.count("UID:family\r\n") == 2
    assert "RECURRENCE-ID;VALUE=DATE:20260911" in text
    if cancelled:
        assert "STATUS:CANCELLED" in moved["icsRoundtrip"]
        assert "STATUS:CANCELLED" in text


def test_linux_thunderbird_anchor(native):
    result = native._tb_jahrestage_klassifizieren(native.ics_lesen(calendar(
        "BEGIN:VEVENT\nUID:b\nDTSTART;VALUE=DATE:20000607\nSUMMARY:Anna Birthday\n"
        "CATEGORIES:Birthday\nRRULE:FREQ=YEARLY\nEND:VEVENT")))
    assert result["jahrestage"][0]["datum"] == "--06-07"


@pytest.mark.parametrize("modern", [False, True])
def test_linux_thunderbird_legacy(native, tmp_path, modern):
    path = tmp_path / "abook.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE properties (card TEXT,name TEXT,value TEXT)")
        db.executemany("INSERT INTO properties VALUES ('c',?,?)", {
            "FirstName": "Anna-Maria", "JobTitle": "Engineer", "Department": "Research",
            "WebPage1": "https://example.test", "WebPage2": "https://home.example.test", "Custom1": "Keep custom"}.items())
        if modern:
            db.execute("INSERT INTO properties VALUES ('c','_vCard',?)", (
                "BEGIN:VCARD\nVERSION:4.0\nN:;Anna-Maria;;;\nFN:Club\nTITLE:Chief\n"
                "URL;TYPE=WORK:https://example.test\nEND:VCARD",))
    text = native.vcf_schreiben(native.vcf_lesen("".join(native._tb_karten_vcards(str(path))))["kontakte"])
    for value in ("TITLE:Chief" if modern else "TITLE:Engineer", "Research", "https://example.test", "https://home.example.test", "Keep custom"):
        assert value in text
    assert text.count("https://example.test") == 1


def test_linux_vcard_no_silent_cap(native):
    text = "BEGIN:VCARD\nVERSION:4.0\nN:Many;Fields;;;\nFN:Many Fields\n" + "".join(
        "URL:https://example.test/%d\n" % n for n in range(260)) + "END:VCARD\n"
    result = native.vcf_lesen(text)
    assert native.vcf_schreiben(result["kontakte"]).count("URL:https://example.test/") == 260


def test_windows_native_fields(windows):
    result = windows(operation="parse", art="ics", text=OCCASION)
    assert result["Jahrestage"][0]["notiz"] == "Keep this note"
    assert_occasion(windows(operation="export", art="ics-jahrestage", data=result["Jahrestage"])["Text"])


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_occasion_core_edits_do_not_replay_stale_raw(native, windows, platform):
    item = native.ics_lesen(OCCASION)["jahrestage"][0] if platform == "linux" else windows(
        operation="parse", art="ics", text=OCCASION)["Jahrestage"][0]
    item.update(name="Changed", datum="--12-31", typ="birthday", notiz="")
    text = native.ics_schreiben_jahrestage([item]) if platform == "linux" else windows(
        operation="export", art="ics-jahrestage", data=[item])["Text"]
    assert text.count("DTSTART;VALUE=DATE:20001231") == 1
    assert text.count("RRULE:FREQ=YEARLY") == 1
    assert text.count("SUMMARY:Changed") == 1
    assert "Keep this note" not in text
    assert "DESCRIPTION:Alarm description" in text
    result = native.ics_lesen(text)["jahrestage"][0]
    assert (result["datum"], result["typ"], result["notiz"]) == ("--12-31", "birthday", "")


@pytest.mark.parametrize("headers,row", [
    ("Subject,Start Date,Start Time,End Date,End Time", "Meeting,2026-09-10,10:00,2026-09-10,11:00"),
    ("Betreff,Startdatum,Startzeit,Enddatum,Endzeit", "Meeting,10.09.2026,10:00,10.09.2026,11:00"),
    ("Subject,Start Date,Start Time,End Time", "Meeting,2026-09-10,10:00,11:00")])
def test_windows_csv_times(windows, headers, row):
    result = windows(operation="parse", art="lotus", text=headers + "\n" + row)
    item = result["Termine"][0]
    assert (item["zeit"], item["endZeit"]) == ("10:00", "11:00")


def test_windows_contact_names(windows):
    xml = '<c:Contact xmlns:c="http://schemas.microsoft.com/Contact"><c:NameCollection><c:Name>' \
        '<c:GivenName>Anna</c:GivenName><c:FamilyName>Berg</c:FamilyName><c:MiddleName>Maria</c:MiddleName>' \
        '<c:FormattedName>Club</c:FormattedName></c:Name></c:NameCollection>' \
        '<c:PhysicalAddressCollection><c:PhysicalAddress><c:Street>Main 1</c:Street><c:Region>Hessen</c:Region>' \
        '</c:PhysicalAddress></c:PhysicalAddressCollection></c:Contact>'
    item = windows(operation="contact", text=xml)
    for _ in range(2):
        item = windows(operation="contactRoundtrip", data=item)
    text = windows(operation="vcf", data=[item])["Text"]
    assert "N:Berg;Anna;Maria;;" in text
    assert "Hessen" in text
    assert item["anzeigename"] == "Club"


def test_windows_claws_birthday(windows):
    text = '<address-book><person first-name="Anna"><attribute-list>' \
        '<attribute name="birthday">--02-29</attribute></attribute-list></person></address-book>'
    result = windows(operation="parse", art="claws", text=text)
    assert result["Kontakte"][0]["geburtstag"] == "--02-29"


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_vcard_oversize_is_whole_import_error(native, windows, platform):
    good = "BEGIN:VCARD\nVERSION:4.0\nFN:Good\nEND:VCARD\n"
    oversized = "BEGIN:VCARD\nVERSION:4.0\nFN:Too large\nX-RAW:" + "x" * 65536 + "\nEND:VCARD\n"
    if platform == "linux":
        with pytest.raises(ValueError):
            native.vcf_lesen(good + oversized)
    else:
        assert windows(operation="parse", art="vcf", text=good + oversized).get("error") == "InvalidDataException"


def test_windows_contact_multipart_and_empty_display(windows):
    text = "BEGIN:VCARD\nVERSION:4.0\nUID:n\nN:Van-Dyke;Anna,Maria;Louise;Dr.;Jr.\nFN:\nBDAY:--0229\nANNIVERSARY:--0607\nEND:VCARD"
    original = windows(operation="parse", art="vcf", text=text)["Kontakte"][0]
    item = original
    for _ in range(2):
        item = windows(operation="contactRoundtrip", data=item)
    export = windows(operation="vcf", data=[item])["Text"]
    assert "N:Van-Dyke;Anna,Maria;Louise;Dr.;Jr." in export
    assert "FN:\r\n" in export
    assert item["geburtstag"] == "--02-29"
    assert item["jubilaeum"] == "--06-07"


@pytest.mark.parametrize("explicit", [False, True])
def test_linux_sqlite_birthday_metadata(native, tmp_path, explicit):
    path = tmp_path / "local.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE cal_events (cal_id TEXT,id TEXT,title TEXT,flags INTEGER,event_start INTEGER,event_start_tz TEXT,event_end INTEGER,event_end_tz TEXT)")
        stamp = lambda day: int(native.datetime(2000, 6, day, tzinfo=native.timezone.utc).timestamp() * 1000000)
        db.execute("INSERT INTO cal_events VALUES ('c','b','Anna Birthday',24,?,'floating',?,'floating')", (stamp(7), stamp(8)))
        db.execute("CREATE TABLE cal_properties (cal_id TEXT,item_id TEXT,key TEXT,value TEXT)")
        db.executemany("INSERT INTO cal_properties VALUES ('c','b',?,?)", [
            ("CATEGORIES", "Birthday"), ("DESCRIPTION", "Keep this note"), ("LOCATION", "Keep this room")]
            + ([("X-MAGNOLIE-TYPE-ID", "birthday")] if explicit else []))
        db.execute("CREATE TABLE cal_recurrence (cal_id TEXT,item_id TEXT,icalString TEXT)")
        db.execute("INSERT INTO cal_recurrence VALUES ('c','b','RRULE:FREQ=YEARLY')")
    item = native._tb_normalisierte_kalenderdaten(str(path))["jahrestage"][0]
    assert item["datum"] == ("2000-06-07" if explicit else "--06-07")
    assert item["notiz"] == "Keep this note"
    assert "LOCATION:Keep this room" in native.ics_schreiben_jahrestage([item])


@pytest.fixture
def web_store(native, windows, tmp_path, monkeypatch):
    node = os.environ.get("MAGNOLIE_BUN") or shutil.which("bun") or shutil.which("node")
    assert node, "A JS runtime is required for the explicitly enabled gate"

    def store(platform, parsed, initial=None):
        def web(**request):
            result = subprocess.run([node, str(WINDOWS / "tests/native-import/frontend.cjs")],
                input=json.dumps(dict(request, platform=platform)), text=True, capture_output=True, check=True)
            return json.loads(result.stdout)

        data = web(payloads=[parsed], initial=initial)
        if platform == "linux":
            monkeypatch.setattr(native, "daten_datei", lambda: str(tmp_path / "linux.json"))
            native.speichere_daten(data)
            data = native.lade_daten()[0]
        else:
            data = windows(operation="persist", file=str(tmp_path / "windows.json"), data=data)
        return web(initial=data)
    return store


@pytest.mark.skipif(os.environ.get("MAGNOLIE_IMPORT_WEB_GATE") != "1",
                    reason="Enable the native/web preservation gate after the parallel frontend fixes")
@pytest.mark.parametrize("parser", ["linux", "windows"])
@pytest.mark.parametrize("platform", ["linux", "windows"])
@pytest.mark.parametrize("kind,text", [("jahrestage", OCCASION), ("aufgaben", TASKS), ("termine", ZONE)])
def test_native_web_persist_export_gate(native, windows, web_store, parser, platform, kind, text):
    parsed = native.ics_lesen(text) if parser == "linux" else {
        key.lower(): value for key, value in windows(operation="parse", art="ics", text=text).items() if isinstance(value, list)}

    data = web_store(platform, parsed)
    for writer in ("linux", "windows"):
        if writer == "linux":
            write = {"jahrestage": native.ics_schreiben_jahrestage, "aufgaben": native.ics_schreiben_aufgaben,
                     "termine": native.ics_schreiben_termine}[kind]
            exported = write(data[kind])
        else:
            result = windows(operation="export", art="ics-" + kind, data=data[kind])
            assert result["Skipped"] == 0
            exported = result["Text"]
        for reader in ("linux", "windows"):
            reread = native.ics_lesen(exported) if reader == "linux" else {
                key.lower(): value for key, value in windows(operation="parse", art="ics", text=exported).items() if isinstance(value, list)}
            if kind == "jahrestage":
                assert_occasion(exported)
                assert len(reread[kind]) == 1
                assert reread[kind][0]["datum"] == "--06-07"
                assert reread[kind][0]["notiz"] == "Keep this note"
            elif kind == "aufgaben":
                assert len(reread[kind]) == 2
                assert exported.count("UID:family\r\n") == 2, (
                    parser, platform, writer, reader,
                    [line for line in exported.splitlines() if line.startswith("UID:")],
                    [(item.get("uid"), item.get("icsSerienUid")) for item in data[kind]])
                assert exported.count("RECURRENCE-ID") == 1
            else:
                assert len(reread[kind]) == 1
                assert reread[kind][0]["zeit"] == "08:00"
                assert len(reread[kind][0]["icsTimezones"]) == 1


@pytest.mark.skipif(os.environ.get("MAGNOLIE_IMPORT_WEB_GATE") != "1", reason="Parallel frontend gate")
@pytest.mark.parametrize("parser", ["linux", "windows"])
@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_contact_web_ldif_gate(native, windows, web_store, parser, platform):
    text = "BEGIN:VCARD\nVERSION:4.0\nUID:contact-gate\nN:Van-Dyke;Anna,Maria;Louise;Dr.;Jr.\nFN:Club\n" \
        "BDAY;X-APPLE-OMIT-YEAR=1604:1604-02-29\nX-ANNIVERSARY:--0607\n" \
        "EMAIL;TYPE=WORK;PREF=1:work@example.test\nEMAIL;TYPE=HOME:home@example.test\n" \
        "TEL;TYPE=WORK:+493012345678\nADR;TYPE=HOME:Box;Floor;Main 1;Berlin;Berlin;10115;DE\nEND:VCARD"
    parsed = native.vcf_lesen(text) if parser == "linux" else {
        key.lower(): value for key, value in windows(operation="parse", art="vcf", text=text).items() if isinstance(value, list)}
    data = web_store(platform, parsed)
    assert len(data["kontakte"]) == 1
    assert len(data["jahrestage"]) == 2
    for writer in ("linux", "windows"):
        exported = native.ldif_schreiben(data["kontakte"]) if writer == "linux" else windows(operation="ldif", data=data["kontakte"])["Text"]
        for reader in ("linux", "windows"):
            item = native.ldif_lesen(exported)["kontakte"][0] if reader == "linux" else windows(operation="parse", art="claws", text=exported)["Kontakte"][0]
            assert item["vorname"] == "Anna Maria" and item["nachname"] == "Van-Dyke"
            assert item["anzeigename"] == "Club"
            assert item["geburtstag"] == "--02-29" and item["jubilaeum"] == "--06-07"
            assert len(item["emails"]) == 2 and len(item["telefone"]) == 1
            assert item["anschriften"][0]["region"] == "Berlin"
            assert item["anschriften"][0]["postfach"] == "Box"
            assert "N:Van-Dyke;Anna,Maria;Louise;Dr.;Jr." in item["vcardRoundtrip"]


@pytest.mark.parametrize("alias", ["X-ANNIVERSARY:--0607", "item1.X-ABDATE:--0607\nitem1.X-ABLabel:Anniversary"])
def test_anniversary_aliases_still_roundtrip(native, windows, alias):
    text = "BEGIN:VCARD\nVERSION:4.0\nN:;Anna;;;\nFN:Anna\nBDAY:1604-02-29\n" + alias + "\nEND:VCARD"
    for item in (native.vcf_lesen(text)["kontakte"][0], windows(operation="parse", art="vcf", text=text)["Kontakte"][0]):
        assert item["geburtstag"] == "1604-02-29"
        assert item["jubilaeum"] == "--06-07"
        exported = native.ldif_schreiben([item])
        assert windows(operation="parse", art="claws", text=exported)["Kontakte"][0]["jubilaeum"] == "--06-07"


@pytest.mark.skipif(os.environ.get("MAGNOLIE_IMPORT_WEB_GATE") != "1", reason="Parallel frontend gate")
@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_task_sources_web_gate(native, web_store, platform):
    tasks = []
    for source in ("A", "B"):
        parsed = native.ics_lesen(calendar("BEGIN:VTODO\nUID:shared\nSUMMARY:Task " + source +
            "\nDUE;VALUE=DATE:20260910\nEND:VTODO"), quellen_id=source)
        tasks.extend(parsed["aufgaben"])
    data = web_store(platform, {"aufgaben": tasks})
    assert len(data["aufgaben"]) == 2
    assert len({item["icsQuelleId"] for item in data["aufgaben"]}) == 2
    assert native.ics_schreiben_aufgaben(data["aufgaben"]).count("BEGIN:VTODO") == 2


@pytest.mark.skipif(os.environ.get("MAGNOLIE_IMPORT_WEB_GATE") != "1", reason="Native task identity gate")
@pytest.mark.parametrize("parser", ["linux", "windows"])
@pytest.mark.parametrize("platform", ["linux", "windows"])
@pytest.mark.parametrize("writer", ["linux", "windows"])
@pytest.mark.parametrize("combined", [False, True])
def test_task_identity_parent_and_reimport(native, windows, web_store, parser, platform, writer, combined):
    def parse(reader, text, source):
        return native.ics_lesen(text, quellen_id=source) if reader == "linux" else {
            k.lower(): v for k, v in windows(operation="parse", art="ics", text=text, file=source).items() if isinstance(v, list)}

    def write(items):
        if writer == "linux":
            return native.ics_schreiben_aufgaben(items)
        result = windows(operation="export", art="ics-aufgaben", data=items)
        assert result["Skipped"] == 0
        return result["Text"]

    items = []
    for source in (["A.ics", "B.ics"] if combined else ["A.ics"]):
        text = TASKS.replace("SUMMARY:Master", "SUMMARY:Master " + source).replace("SUMMARY:Moved", "SUMMARY:Moved " + source)
        child = "BEGIN:VTODO\nUID:child\nSUMMARY:Child " + source + "\nRELATED-TO;RELTYPE=PARENT:family\nEND:VTODO\n"
        legitimate = "BEGIN:VTODO\nUID:mag-task-user-legitimate@magnolie-organizer\nSUMMARY:Legitimate " + source + "\nEND:VTODO\n"
        items.extend(parse(parser, text.replace("END:VCALENDAR", child + legitimate + "END:VCALENDAR"), source)["aufgaben"])
    data = web_store(platform, {"aufgaben": items})

    def state(data):
        result = {}
        for task in data["aufgaben"]:
            source = task["icsQuelleId"]
            result[source, task["titel"]] = (task["id"], task["uid"], task["elternUid"])
            if task["titel"].startswith("Moved"):
                assert task["icsSerienUid"] == "family"
            if task["titel"].startswith("Child"):
                parent = next(p for p in data["aufgaben"] if p["icsQuelleId"] == source and p["titel"].startswith("Master"))
                assert task["elternUid"] == parent["uid"]
                assert task["icsElternUid"] == "family"
        return result

    original = state(data)
    assert len(original) == (8 if combined else 4)
    for task in data["aufgaben"]:
        if task["titel"].startswith("Child"):
            only_child = write([task])
            assert "RELATED-TO;RELTYPE=PARENT:family\r\n" in only_child
    for cycle in range(3):
        exported = write(data["aufgaben"])
        lines = native._entfalte_zeilen(exported)
        wire_uids = [line[4:] for line in lines if line.startswith("UID:")]
        if not combined:
            assert wire_uids.count("family") == 2
            assert wire_uids.count("child") == 1
            assert wire_uids.count("mag-task-user-legitimate@magnolie-organizer") == 1
        else:
            assert len(set(wire_uids)) == 6
            assert all(wire_uids.count(value) <= 2 for value in wire_uids)
            reversed_lines = native._entfalte_zeilen(write(list(reversed(data["aufgaben"]))))
            assert sorted(wire_uids) == sorted(line[4:] for line in reversed_lines if line.startswith("UID:"))
            parents = [line.split(":", 1)[1] for line in lines if line.startswith("RELATED-TO;RELTYPE=PARENT:")]
            assert len(set(parents)) == 2 and all(wire_uids.count(parent) == 2 for parent in parents)
        for reader in ("linux", "windows"):
            parsed = parse(reader, exported, "export-cycle-%d.ics" % cycle)
            assert len(parsed["aufgaben"]) == len(original)
            assert {task["icsQuelleId"] for task in parsed["aufgaben"]} == {key[0] for key in original}
            data = web_store(platform, parsed, initial=data)
            assert state(data) == original


@pytest.mark.parametrize("writer", ["linux", "windows"])
def test_task_export_collision_reserves_legitimate_uids(native, windows, writer):
    alias = native._aufgaben_export_alias("A", "same")
    items = [{"uid": "local-a", "icsImportUid": "same", "icsQuelleId": "A", "titel": "A"},
             {"uid": "local-b", "icsImportUid": "same", "icsQuelleId": "B", "titel": "B"},
             {"uid": alias, "titel": "Legitimate"}]
    text = native.ics_schreiben_aufgaben(items) if writer == "linux" else windows(operation="export", art="ics-aufgaben", data=items)["Text"]
    wire = [line[4:] for line in native._entfalte_zeilen(text) if line.startswith("UID:")]
    assert len(set(wire)) == 3 and alias in wire and alias + "-1" in wire
    for parsed in (native.ics_lesen(text)["aufgaben"], windows(operation="parse", art="ics", text=text)["Aufgaben"]):
        assert {(item["titel"], item["uid"], item["icsQuelleId"]) for item in parsed} == {
            ("A", "same", "A"), ("B", "same", "B"), ("Legitimate", alias, "")}


@pytest.mark.skipif(os.environ.get("MAGNOLIE_IMPORT_WEB_GATE") != "1", reason="Native task identity gate")
@pytest.mark.parametrize("platform", ["linux", "windows"])
@pytest.mark.parametrize("writer", ["linux", "windows"])
def test_explicit_cross_source_parent_and_orphan_relink(native, windows, web_store, platform, writer):
    tasks = [{"id": "pa", "uid": "graph-pa", "icsImportUid": "parent", "icsQuelleId": "A", "titel": "Parent A"},
             {"id": "pb", "uid": "graph-pb", "icsImportUid": "parent", "icsQuelleId": "B", "titel": "Parent B"},
             {"id": "c", "uid": "graph-c", "icsImportUid": "child", "icsQuelleId": "A", "titel": "Child",
              "elternUid": "graph-pb", "icsElternUid": "parent", "icsElternQuelleId": "B"}]

    def write(items):
        return native.ics_schreiben_aufgaben(items) if writer == "linux" else windows(operation="export", art="ics-aufgaben", data=items)["Text"]

    exported = write(tasks)
    expected = native._aufgaben_export_alias("B", "parent")
    assert "RELATED-TO;RELTYPE=PARENT:" + expected in "\n".join(native._entfalte_zeilen(exported))
    ambiguous = [dict(task) for task in tasks]
    ambiguous[0]["uid"] = ambiguous[1]["uid"] = ambiguous[2]["elternUid"] = "parent"
    assert "RELATED-TO;RELTYPE=PARENT:" + expected in "\n".join(native._entfalte_zeilen(write(ambiguous)))
    for reader in ("linux", "windows"):
        parsed = native.ics_lesen(write([tasks[2]])) if reader == "linux" else {
            "aufgaben": windows(operation="parse", art="ics", text=write([tasks[2]]))["Aufgaben"]}
        data = web_store(platform, parsed)
        child = data["aufgaben"][0]
        assert child["elternUid"] == "" and child["icsElternUid"] == "parent" and child["icsElternQuelleId"] == "B"
        identity = child["id"]
        parsed_parents = native.ics_lesen(write(tasks[:2])) if reader == "linux" else {
            "aufgaben": windows(operation="parse", art="ics", text=write(tasks[:2]))["Aufgaben"]}
        data = web_store(platform, parsed_parents, initial=data)
        child = next(t for t in data["aufgaben"] if t["id"] == identity)
        parent = next(t for t in data["aufgaben"] if t["titel"] == "Parent B")
        assert child["elternUid"] == parent["uid"]


@pytest.mark.parametrize("writer", ["linux", "windows"])
def test_task_identity_text_is_lossless(native, windows, writer):
    uid = "mag-task-user;comma,colon:back\\slash"
    tasks = [{"uid": uid, "titel": "Escaped identity", "icsQuelleId": "test-source"}]
    text = native.ics_schreiben_aufgaben(tasks) if writer == "linux" else windows(operation="export", art="ics-aufgaben", data=tasks)["Text"]
    assert native.ics_lesen(text)["aufgaben"][0]["uid"] == uid
    assert windows(operation="parse", art="ics", text=text)["Aufgaben"][0]["uid"] == uid
