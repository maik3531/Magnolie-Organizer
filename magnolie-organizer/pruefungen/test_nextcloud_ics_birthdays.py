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
