"""Explicit Nextcloud birthday properties in the actual desktop ICS codec."""
from hashlib import sha256

import pytest
from test_category_colors import codec


@pytest.mark.parametrize("start,end,year_fields,rule,expected", [
    ("19850417", "19850418", ["X-NEXTCLOUD-BC-UNKNOWN-YEAR:0", "X-NEXTCLOUD-BC-YEAR:1985"], "FREQ=YEARLY", "1985-04-17"),
    ("19700417", "19700418", ["X-NEXTCLOUD-BC-UNKNOWN-YEAR:1"], "FREQ=YEARLY", "--04-17"),
    ("19720229", "19720301", ["X-NEXTCLOUD-BC-UNKNOWN-YEAR:1"], "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1", "--02-29"),
    ("19880417", "19880418", ["X-NEXTCLOUD-BC-UNKNOWN-YEAR:1", "X-NEXTCLOUD-BC-YEAR:1988"], "FREQ=YEARLY", None),
])
def test_nextcloud_birthday(codec, start, end, year_fields, rule, expected):
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "COLOR:gold", "BEGIN:VEVENT", "UID:provider-birthday",
        "SUMMARY:Example", f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}", f"RRULE:{rule}",
        "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", *year_fields, "COLOR:turquoise", "X-TEST-PROVIDER:retained",
        "END:VEVENT", "END:VCALENDAR", ""])
    imported = codec.ics_lesen(text, "Nextcloud", "provider-source")
    if expected is None:
        assert not imported["jahrestage"] and len(imported["termine"]) == 1
        return
    assert not imported["termine"] and len(imported["jahrestage"]) == 1
    item = imported["jahrestage"][0]
    assert (item["datum"], item["typ"], item["uid"]) == (expected, "birthday", "provider-birthday")
    assert item["icsQuelleId"] == "ics:" + sha256(b"provider-source\n").hexdigest()
    assert item["icsQuelleName"] == "Nextcloud" and item["akzentFarbe"] == "#40e0d0"
    exported = codec.ics_schreiben_jahrestage([item])
    assert [line for line in exported.splitlines() if line.startswith("RRULE:")] == [f"RRULE:{rule}"]
    assert f"DTSTART;VALUE=DATE:{start}" in exported and f"DTEND;VALUE=DATE:{end}" in exported
    assert "COLOR:gold" in exported and "COLOR:turquoise" in exported and "X-TEST-PROVIDER:retained" in exported
    assert codec.ics_lesen(exported)["jahrestage"][0]["datum"] == expected
    edited = codec.ics_schreiben_jahrestage([{**item, "datum": "--07-12"}])
    assert "X-NEXTCLOUD-BC-UNKNOWN-YEAR:" not in edited and "X-TEST-PROVIDER:retained" in edited
    assert codec.ics_lesen(edited)["jahrestage"][0]["datum"] == "--07-12"


@pytest.mark.parametrize("properties", [
    [], ["X-NEXTCLOUD-BC-FIELD-TYPE:DEATHDATE"], ["X-NEXTCLOUD-BC-FIELD-TYPE:ANNIVERSARY"],
    ["X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "X-NEXTCLOUD-BC-FIELD-TYPE:DEATHDATE"],
    ["X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "X-NEXTCLOUD-BC-YEAR:1986"],
    ["X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "EXDATE;VALUE=DATE:20260417"],
    ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-P1D", "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "END:VALARM"],
])
def test_other_events_keep_their_type(codec, properties):
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:control",
        "SUMMARY:Birthday-looking title", "DTSTART;VALUE=DATE:19850417", "RRULE:FREQ=YEARLY",
        *properties, "END:VEVENT", "END:VCALENDAR", ""])
    parsed = codec.ics_lesen(text)
    assert not parsed["jahrestage"] and len(parsed["termine"]) == 1


def test_nextcloud_marker_cannot_detach_a_series_master_from_its_exception(codec):
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:series",
        "SUMMARY:Master", "DTSTART;VALUE=DATE:19850417", "RRULE:FREQ=YEARLY",
        "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "END:VEVENT", "BEGIN:VEVENT", "UID:series",
        "SUMMARY:Moved", "RECURRENCE-ID;VALUE=DATE:20260417", "DTSTART;VALUE=DATE:20260418",
        "END:VEVENT", "END:VCALENDAR", ""])
    parsed = codec.ics_lesen(text)
    assert not parsed["jahrestage"] and len(parsed["termine"]) == 2


@pytest.mark.parametrize("start,years,date,kind", [
    ("19720229", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1", "--02-29", "wedding-anniversary"),
    ("19880229", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:0\r\nX-NEXTCLOUD-BC-YEAR:1988", "1988-02-29", "wedding-anniversary"),
    ("19720229", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1", "1988-02-29", "birthday"),
    ("19880229", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:0\r\nX-NEXTCLOUD-BC-YEAR:1988", "--02-29", "birthday"),
])
def test_type_or_year_edit_keeps_last_february_recurrence(codec, start, years, date, kind):
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:edited-leap",
        "SUMMARY:Synthetic birthday", f"DTSTART;VALUE=DATE:{start}",
        "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1", "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY",
        years, "X-SYNTHETIC-PRESERVE:keep", "END:VEVENT", "END:VCALENDAR", ""])
    item = codec.ics_lesen(text)["jahrestage"][0]
    item.update(datum=date, typ=kind)
    for _round in range(2):
        exported = codec.ics_schreiben_jahrestage([item])
        assert "X-NEXTCLOUD-BC-" not in exported
        assert "X-SYNTHETIC-PRESERVE:keep" in exported
        assert [line for line in exported.splitlines() if line.startswith("RRULE:")] == [
            "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1"]
        parsed = codec.ics_lesen(exported)
        assert not parsed["termine"] and len(parsed["jahrestage"]) == 1
        item = parsed["jahrestage"][0]
        assert (item["datum"], item["typ"]) == (date, kind)
    exception = "\r\n".join(["BEGIN:VEVENT", "UID:edited-leap", "RECURRENCE-ID;VALUE=DATE:20270228",
        "DTSTART;VALUE=DATE:20270301", "SUMMARY:Moved", "END:VEVENT", ""])
    parsed = codec.ics_lesen(exported.replace("END:VCALENDAR", exception + "END:VCALENDAR"))
    assert not parsed["jahrestage"] and len(parsed["termine"]) == 2


@pytest.mark.parametrize("leap", [False, True])
def test_nextcloud_birthday_scope_is_not_silently_omitted_by_linux_dav(monkeypatch, leap):
    from test_nextcloud import m, nc, SyncDav, run_sync, empty_data
    start = "19720229" if leap else "19700417"
    rule = "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1" if leap else "FREQ=YEARLY"
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:provider-scope",
        f"DTSTART;VALUE=DATE:{start}", f"RRULE:{rule}", "SUMMARY:Synthetic birthday",
        "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1",
        "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER;VALUE=DURATION:PT9H", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])
    assert len(m.ics_lesen(text)["jahrestage"]) == 1
    dav = SyncDav({"calendar": [dict(href="https://cloud.example/calendar/birthday.ics",
                                   etag='"fixture"', data=text)], "addressbook": []})
    data = empty_data()
    import copy
    before = copy.deepcopy(data)
    with pytest.raises(nc.NextcloudError) as failed:
        run_sync(monkeypatch, dav, data)
    assert failed.value.code == "calendar_anniversaries_unsupported"
    assert not dav.puts and not dav.deletes and data == before
