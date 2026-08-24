import importlib.machinery
import importlib.util
import os


PROGRAMM = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-organizer")
lader = importlib.machinery.SourceFileLoader("magnolie_eds_calendar_dedup", PROGRAMM)
spec = importlib.util.spec_from_loader("magnolie_eds_calendar_dedup", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


class Quelle:
    def get_display_name(self):
        return "Google birthdays"


class Registry:
    def ref_source(self, uid):
        return Quelle() if uid == "google-calendar" else None


class Probe:
    def antwort(self, funktion, nutzlast):
        self.funktion = funktion
        self.nutzlast = nutzlast


def sync(monkeypatch, lokale_termine, remote_ics):
    monkeypatch.setattr(m, "eds_laden", lambda: True)
    monkeypatch.setattr(m, "eds_registry", Registry)
    monkeypatch.setattr(m, "eds_kalender_client", lambda registry, uid: uid)
    monkeypatch.setattr(m, "eds_events_lesen", lambda client: [remote_ics])
    monkeypatch.setattr(m, "eds_event_anlegen", lambda client, text: None)
    monkeypatch.setattr(m, "eds_event_aendern", lambda client, text: None)
    monkeypatch.setattr(m, "eds_event_loeschen", lambda client, uid: None)
    probe = Probe()
    m.Fenster._sync_ausfuehren(probe, {
        "wahl": {"kalenderUid": "google-calendar",
                 "kalenderUids": ["google-calendar"]},
        "daten": {"termine": lokale_termine, "kontakte": [], "jahrestage": [],
                  "geloescht": {"termine": [], "kontakte": []},
                  "letzterSync": 0, "letzteSyncs": {"kalender": {}}}})
    return probe.nutzlast


def test_yearly_all_day_from_ics_and_eds_is_one_read_only_event(monkeypatch):
    uid = "google-birthday-42@google.com"
    imported = m.ics_lesen(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:%s\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "DTEND;VALUE=DATE:19900518\r\nRRULE:FREQ=YEARLY\r\n"
        "SUMMARY:Alex\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n" % uid,
        quellenname="thunderbird-birthdays.ics")["termine"][0]
    # Some cache readers identify the master by a local row UID while retaining
    # the RFC series UID. EDS returns the authoritative RFC UID.
    imported["uid"] = "thunderbird-row-42"
    imported["icsSerienUid"] = uid
    import_source = imported["icsQuelleId"]

    remote = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:%s\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "DTEND;VALUE=DATE:19900518\r\nRRULE:FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=17\r\n"
        "EXDATE;VALUE=DATE:20900517\r\nSUMMARY:Alex\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n" % uid)

    result = sync(monkeypatch, [imported], remote)

    assert len(result["termine"]) == 1
    event = result["termine"][0]
    assert event["uid"] == uid
    assert event["datum"] == "1990-05-17" and event["zeit"] == ""
    assert event["icsReadOnly"] and event["icsReadOnlyGrund"] == "EDS"
    assert set(event["syncQuellen"]) == {
        import_source, "eds:google-calendar"}
    assert event["syncQuellen"][import_source]["id"] == "thunderbird-row-42"
    assert event["syncQuellen"]["eds:google-calendar"]["id"] == uid
    assert "thunderbird-birthdays.ics" in event["icsQuelleName"]
    assert "Google birthdays" in event["icsQuelleName"]
    assert "Google birthdays" in result["bericht"]


def test_same_yearly_all_day_content_with_distinct_uids_stays_separate(monkeypatch):
    imported = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:family-copy\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "RRULE:FREQ=YEARLY\r\nSUMMARY:Alex\r\nEND:VEVENT\r\n",
        quellenname="family.ics")["termine"][0]
    remote = (
        "BEGIN:VEVENT\r\nUID:work-copy\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "RRULE:FREQ=YEARLY\r\nSUMMARY:Alex\r\nEND:VEVENT\r\n")

    result = sync(monkeypatch, [imported], remote)

    assert {event["uid"] for event in result["termine"]} == {
        "family-copy", "work-copy"}
