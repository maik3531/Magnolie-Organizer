using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ThunderbirdSchema23Tests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-tb23-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "local.sqlite"); using var db = new SqliteConnection("Data Source=" + path); db.Open();
            Execute(db, "CREATE TABLE cal_events (cal_id TEXT,id TEXT,last_modified INTEGER,title TEXT,privacy TEXT,ical_status TEXT,flags INTEGER,event_start INTEGER,event_start_tz TEXT,event_end INTEGER,event_end_tz TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT)");
            Execute(db, "CREATE TABLE cal_properties (cal_id TEXT,item_id TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT,key TEXT,value BLOB)");
            Execute(db, "CREATE TABLE cal_parameters (cal_id TEXT,item_id TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT,key1 TEXT,key2 TEXT,value BLOB)");
            foreach (var table in new[] { "cal_recurrence", "cal_alarms", "cal_attendees", "cal_attachments", "cal_relations" })
                Execute(db, $"CREATE TABLE {table} (cal_id TEXT,item_id TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT,icalString TEXT)");
            var recurrence = Native(2026, 8, 10, 9);
            Insert(db, "INSERT INTO cal_events VALUES ($c,$i,$m,$t,'PUBLIC','CONFIRMED',48,$s,'UTC',$e,'UTC',NULL,NULL)",
                ("$c", "c"), ("$i", "serie"), ("$m", Native(2026, 1, 1)), ("$t", "Wochenserie"), ("$s", Native(2026, 8, 3, 9)), ("$e", Native(2026, 8, 3, 10)));
            Insert(db, "INSERT INTO cal_events VALUES ($c,$i,$m,$t,'PRIVATE','TENTATIVE',0,$s,'UTC',$e,'UTC',$r,'UTC')",
                ("$c", "c"), ("$i", "serie"), ("$m", Native(2026, 1, 2)), ("$t", "Verschoben"), ("$s", Native(2026, 8, 10, 11)), ("$e", Native(2026, 8, 10, 12)), ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','ATTENDEE','mailto:mia@example.org')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','ATTENDEE','mailto:lea@example.org')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','X-OPAQUE','eins')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','X-OPAQUE','zwei')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_parameters VALUES ('c','serie',$r,'UTC','ATTENDEE','CN','Mia Muster')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_parameters VALUES ('c','serie',$r,'UTC','ATTENDEE','MEMBER','team-a')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_parameters VALUES ('c','serie',$r,'UTC','ATTENDEE','MEMBER','team-b')", ("$r", recurrence));
            Execute(db, "INSERT INTO cal_recurrence VALUES ('c','serie',NULL,NULL,'RRULE:FREQ=WEEKLY;BYDAY=MO')");
            Insert(db, "INSERT INTO cal_alarms VALUES ('c','serie',$r,'UTC','BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_attendees VALUES ('c','serie',$r,'UTC','ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:max@example.org')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_attachments VALUES ('c','serie',$r,'UTC','ATTACH;FMTTYPE=application/pdf:https://example.org/a.pdf')", ("$r", recurrence));
            db.Close();

            var parsed = ThunderbirdCalendarImporter.Parse(path); var exception = parsed.Termine.Single(node => node!["titel"]!.GetValue<string>() == "Verschoben")!;
            var roundtrip = exception["icsRoundtrip"]!.AsArray().Select(node => node!.GetValue<string>()).ToArray();
            TestAssert.That(parsed.Termine.Count == 2 && exception["icsKomplex"]!.GetValue<bool>() &&
                exception["uid"]!.GetValue<string>().StartsWith("serie#", StringComparison.Ordinal) &&
                exception["syncKalenderUid"]!.GetValue<string>() == "c" &&
                roundtrip.Contains("RECURRENCE-ID:20260810T090000Z") && roundtrip.Contains("TRIGGER:-PT15M") &&
                roundtrip.Count(line => line.StartsWith("ATTENDEE;", StringComparison.Ordinal)) == 3 &&
                roundtrip.Any(line => line.Contains("MEMBER=team-a;MEMBER=team-b", StringComparison.Ordinal)) &&
                roundtrip.Contains("X-OPAQUE:eins") && roundtrip.Contains("X-OPAQUE:zwei") &&
                roundtrip.Contains("ATTACH;FMTTYPE=application/pdf:https://example.org/a.pdf"),
                "Thunderbird Schema 23 verlor cal_id, Mehrfachwerte, parameterlose Properties, Parameter, Alarm, Teilnehmer oder Anhang.");
            var broken = Path.Combine(root, "broken.sqlite"); File.WriteAllText(broken, "kein sqlite");
            var allProfiles = ThunderbirdCalendarImporter.ParseProfiles(new[] { broken, path }, out var read);
            TestAssert.That(read == 1 && allProfiles.Termine.Count == 2 && allProfiles.Uebersprungen == 1,
                "Ein defektes Thunderbird-Profil blockierte weitere Profile oder wurde nicht gemeldet.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    private static long Native(int year, int month, int day, int hour = 0) => new DateTimeOffset(year, month, day, hour, 0, 0, TimeSpan.Zero).ToUnixTimeMilliseconds() * 1000;
    private static void Execute(SqliteConnection db, string sql) { using var command = db.CreateCommand(); command.CommandText = sql; command.ExecuteNonQuery(); }
    private static void Insert(SqliteConnection db, string sql, params (string Name, object Value)[] values)
    {
        using var command = db.CreateCommand(); command.CommandText = sql;
        foreach (var (name, value) in values) command.Parameters.AddWithValue(name, value); command.ExecuteNonQuery();
    }
}
