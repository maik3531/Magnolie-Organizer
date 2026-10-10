import copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_calendar_dedup import plan_birthdays, rebind_local


def event(uid, start="19800510", end="19800511", extra="", trigger="-PT10M", created="20200101T000000Z"):
    return ("BEGIN:VEVENT\r\nUID:" + uid + "\r\nDTSTART;VALUE=DATE:" + start + "\r\nDTEND;VALUE=DATE:" + end +
        "\r\nRRULE:FREQ=YEARLY\r\nSUMMARY:Synthetic Person\r\nX-MAGNOLIE-TYP:Geburtstag\r\n"
        "X-MAGNOLIE-TYPE-ID:birthday\r\nCREATED:" + created + "\r\n" + extra +
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nTRIGGER:" + trigger +
        "\r\nX-EVOLUTION-ALARM-UID:alarm-" + uid + "\r\nEND:VALARM\r\nEND:VEVENT\r\n")


def local(uid, date="1980-05-10", contact="person", source="calendar"):
    return {"uid": uid, "icsSerienUid": uid, "kontaktId": contact, "typ": "birthday", "datum": date,
        "name": "Synthetic Person", "syncKalenderUid": source, "icsQuelleId": "eds:" + source,
        "syncQuellen": {"eds:" + source: {"id": uid, "name": "Source", "eigen": False}}}


def plan(items=None, texts=None):
    return plan_birthdays(items or [local("original"), local("copy")], texts or [event("original"), event("copy", created="20260101T000000Z")], "calendar", "eds:calendar")


def test_known_contact_and_exact_remote_semantics_keep_original_uid_and_full_alarm():
    result = plan()
    assert len(result) == 1 and result[0]["keepUid"] == "original" and result[0]["removeUids"] == ["copy"]
    assert set(result[0]["hashes"]) == {"original", "copy"}


def test_known_kcalendarcore_wrapper_preserves_unknown_metadata_barrier():
    def wrapped(uid, marker="X-KDE-ICAL-IMPLEMENTATION-VERSION:1.0"):
        return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + marker + "\r\n" + event(uid) + "END:VCALENDAR\r\n"
    assert len(plan(texts=[wrapped("original"), wrapped("copy")])) == 1
    for marker in ("X-KDE-ICAL-IMPLEMENTATION-VERSION:2.0", "X-KDE-ICAL-IMPLEMENTATION-VERSION;UNKNOWN=1:1.0", "METHOD:PUBLISH"):
        assert plan(texts=[wrapped("original"), wrapped("copy", marker)]) == []


def test_unicode_survivor_order_matches_utf8_contract():
    bmp, supplementary = "\ue000", "\U00010000"
    result = plan(items=[local(supplementary), local(bmp)], texts=[event(supplementary), event(bmp)])
    assert len(result) == 1 and result[0]["keepUid"] == bmp and result[0]["removeUids"] == [supplementary]


def test_yearless_contact_preserves_explicit_unknown_year_annotation():
    items = [local("old-copy", "--05-10"), local("correct", "--05-10")]
    texts = [event("old-copy", "20260510", "20260511"), event("correct", "20000510", "20000511", "X-MAGNOLIE-DATE:--05-10\r\n", created="20260101T000000Z")]
    result = plan(items, texts)
    assert len(result) == 1 and result[0]["keepUid"] == "correct" and result[0]["removeUids"] == ["old-copy"]


def test_matching_name_is_not_identity_and_other_sources_are_not_merged():
    assert plan([local("original", contact="one"), local("copy", contact="two")]) == []
    assert plan([local("original"), local("copy", source="other-calendar")]) == []
    assert plan([local("original", contact=""), local("copy", contact="")]) == []
    assert plan([local("original"), local("copy", date="1990-05-10")]) == []


def test_different_reminders_details_finite_rules_and_exceptions_remain_untouched():
    for changed in (event("copy", trigger="-PT30M"), event("copy", extra="DESCRIPTION:Different personal detail\r\n"),
                    event("copy").replace("FREQ=YEARLY", "FREQ=YEARLY;COUNT=4"),
                    event("copy", extra="RECURRENCE-ID;VALUE=DATE:20260510\r\n"),
                    event("copy", extra="EXDATE;VALUE=DATE:20270510\r\n"),
                    event("copy", extra="X-LIC-ERROR:Unparsed provider field\r\n"),
                    event("copy", extra="ATTENDEE:mailto:fixture@example.invalid\r\n")):
        assert plan(texts=[event("original"), changed]) == []


def test_unmarked_objects_mixed_resources_and_repeated_series_uids_are_protected():
    unmarked = "\r\n".join(line for line in event("copy").split("\r\n") if not line.startswith("X-MAGNOLIE-"))
    assert plan(texts=[event("original"), unmarked]) == []
    mixed = "BEGIN:VCALENDAR\r\n" + event("copy") + "BEGIN:VTODO\r\nUID:task\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    assert plan(texts=[event("original"), mixed]) == []
    assert plan(texts=[event("original"), "BEGIN:VCALENDAR\r\nX-PRIVATE:Preserve whole resource\r\n" + event("copy") + "END:VCALENDAR\r\n"]) == []
    assert plan(texts=[event("original"), event("copy"), event("copy", extra="RECURRENCE-ID;VALUE=DATE:20260510\r\n")]) == []


def test_alias_rebinding_is_target_specific_and_does_not_change_personal_fields():
    items = [local("original"), local("copy")]
    items[1]["notiz"] = "Keep local notes"
    items[1]["syncQuellen"]["eds:other-calendar"] = {"id": "copy", "name": "Other", "eigen": False}
    before = copy.deepcopy(items)
    operation = plan(items)[0]
    rebind_local(items, operation)
    assert items[1]["uid"] == items[1]["icsSerienUid"] == items[1]["syncQuellen"]["eds:calendar"]["id"] == "original"
    assert items[1]["syncQuellen"]["eds:other-calendar"] == before[1]["syncQuellen"]["eds:other-calendar"]
    assert items[1]["notiz"] == before[1]["notiz"]
    assert plan(items, [event("original")]) == []


def test_ambiguous_contact_binding_or_malformed_snapshot_cannot_create_a_delete_plan():
    assert plan([local("original"), local("copy"), local("copy", contact="different-person")]) == []
    assert plan([local("original"), local("copy"), local("copy", date="1990-05-10")]) == []
    assert plan(texts=[event("original"), event("copy"), "BEGIN:VEVENT\r\nUID:broken\r\n"]) == []
