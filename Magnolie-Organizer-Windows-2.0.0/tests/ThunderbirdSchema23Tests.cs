using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;
using System.Text.Json.Nodes;

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
            Execute(db, File.ReadAllText(Path.Combine(TestSource.Root("MagnolieOrganizer.Windows.csproj"), "tests", "fixtures", "thunderbird-schema23-todos.sql")));
            foreach (var table in new[] { "cal_recurrence", "cal_alarms", "cal_attendees", "cal_attachments", "cal_relations" })
                Execute(db, $"CREATE TABLE {table} (cal_id TEXT,item_id TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT,icalString TEXT)");
            var recurrence = Native(2026, 8, 10, 9);
            Insert(db, "INSERT INTO cal_events VALUES ($c,$i,$m,$t,'PUBLIC','CONFIRMED',48,$s,'UTC',$e,'UTC',NULL,NULL)",
                ("$c", "c"), ("$i", "serie"), ("$m", Native(2026, 1, 1)), ("$t", "Wochenserie"), ("$s", Native(2026, 8, 3, 9)), ("$e", Native(2026, 8, 3, 10)));
            Insert(db, "INSERT INTO cal_events VALUES ($c,$i,$m,$t,'PRIVATE','TENTATIVE',0,$s,'UTC',$e,'UTC',$r,'UTC')",
                ("$c", "c"), ("$i", "serie"), ("$m", Native(2026, 1, 2)), ("$t", "Verschoben"), ("$s", Native(2026, 8, 10, 11)), ("$e", Native(2026, 8, 10, 12)), ("$r", recurrence));
            Execute(db, $"INSERT INTO cal_events VALUES ('c','broken',0,'Kaputt','PUBLIC','CONFIRMED','kein-integer',{Native(2026, 8, 2, 9)},'UTC',{Native(2026, 8, 2, 10)},'UTC',NULL,NULL)");
            Insert(db, "INSERT INTO cal_events VALUES ('c','eiermann-1998',0,'Eiermann','PUBLIC','CONFIRMED',16,$s,'floating',$e,'floating',NULL,NULL)",
                ("$s", Native(1998, 1, 5, 9)), ("$e", Native(1998, 1, 5, 9, 30)));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','ATTENDEE','mailto:mia@example.org')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','ATTENDEE','mailto:lea@example.org')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','X-OPAQUE','eins')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_properties VALUES ('c','serie',$r,'UTC','X-OPAQUE','zwei')", ("$r", recurrence));
            Execute(db, "INSERT INTO cal_properties VALUES ('c','todo-valid',NULL,NULL,'DESCRIPTION','Aufgaben-Notiz')");
            Execute(db, "INSERT INTO cal_properties VALUES ('c','todo-valid',NULL,NULL,'X-TODO-RAW','opak')");
            Insert(db, "INSERT INTO cal_parameters VALUES ('c','serie',$r,'UTC','ATTENDEE','CN','Mia Muster')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_parameters VALUES ('c','serie',$r,'UTC','ATTENDEE','MEMBER','team-a')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_parameters VALUES ('c','serie',$r,'UTC','ATTENDEE','MEMBER','team-b')", ("$r", recurrence));
            Execute(db, "INSERT INTO cal_recurrence VALUES ('c','serie',NULL,NULL,'RRULE:FREQ=WEEKLY;BYDAY=MO')");
            Execute(db, "INSERT INTO cal_recurrence VALUES ('c','serie',NULL,NULL,'EXDATE:20260817T090000Z')");
            Execute(db, "INSERT INTO cal_recurrence VALUES ('c','serie',NULL,NULL,'RDATE:20260824T150000Z')");
            Execute(db, "INSERT INTO cal_recurrence VALUES ('c','eiermann-1998',NULL,NULL,'RRULE:FREQ=WEEKLY;WKST=MO;INTERVAL=2;BYDAY=MO')");
            Insert(db, "INSERT INTO cal_alarms VALUES ('c','serie',$r,'UTC','BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_attendees VALUES ('c','serie',$r,'UTC','ATTENDEE;ROLE=REQ-PARTICIPANT:mailto:max@example.org')", ("$r", recurrence));
            Insert(db, "INSERT INTO cal_attachments VALUES ('c','serie',$r,'UTC','ATTACH;FMTTYPE=application/pdf:https://example.org/a.pdf')", ("$r", recurrence));
            db.Close();

            var parsed = ThunderbirdCalendarImporter.Parse(path); var exception = parsed.Termine.Single(node => node!["titel"]!.GetValue<string>() == "Verschoben")!;
            var master = parsed.Termine.Single(node => node!["titel"]!.GetValue<string>() == "Wochenserie")!;
            var eiermann = parsed.Termine.Single(node => node!["uid"]!.GetValue<string>() == "eiermann-1998")!;
            var source = master["icsQuelleId"]!.GetValue<string>();
            var roundtrip = exception["icsRoundtrip"]!.AsArray().Select(node => node!.GetValue<string>()).ToArray();
            var task = parsed.Aufgaben.Single()!;
            using var taskDocument = System.Text.Json.JsonDocument.Parse(new System.Text.Json.Nodes.JsonArray(task.DeepClone()).ToJsonString());
            var taskRoundtrip = ExchangeCodec.WriteIcs("ics-aufgaben", taskDocument.RootElement).Text;
            TestAssert.That(parsed.Termine.Count == 3 && task["uid"]!.GetValue<string>() == "todo-valid" &&
                task["notiz"]!.GetValue<string>() == "Aufgaben-Notiz" && taskRoundtrip.Contains("BEGIN:VTODO", StringComparison.Ordinal) &&
                taskRoundtrip.Contains("UID:todo-valid", StringComparison.Ordinal) && taskRoundtrip.Contains("X-TODO-RAW:opak", StringComparison.Ordinal) &&
                parsed.Uebersprungen == 2 && exception["icsKomplex"]!.GetValue<bool>() &&
                exception["uid"]!.GetValue<string>().StartsWith("serie#", StringComparison.Ordinal) &&
                source.StartsWith("thunderbird:", StringComparison.Ordinal) && source.EndsWith(":c", StringComparison.Ordinal) &&
                exception["syncKalenderUid"]!.GetValue<string>() == source && exception["icsQuelleName"]!.GetValue<string>() == "Thunderbird: c" &&
                exception["syncQuellen"]![source]!["id"]!.GetValue<string>() == "serie" &&
                roundtrip.Contains("RECURRENCE-ID:20260810T090000Z") && roundtrip.Contains("TRIGGER:-PT15M") &&
                roundtrip.Count(line => line.StartsWith("ATTENDEE;", StringComparison.Ordinal)) == 3 &&
                roundtrip.Any(line => line.Contains("MEMBER=team-a;MEMBER=team-b", StringComparison.Ordinal)) &&
                roundtrip.Contains("X-OPAQUE:eins") && roundtrip.Contains("X-OPAQUE:zwei") &&
                roundtrip.Contains("ATTACH;FMTTYPE=application/pdf:https://example.org/a.pdf"),
                "Thunderbird Schema 23 verlor cal_id, Mehrfachwerte, parameterlose Properties, Parameter, Alarm, Teilnehmer oder Anhang.");
            TestAssert.That(master["wiederholung"]!["art"]!.GetValue<string>() == "weekly" &&
                master["icsAusnahmeTermine"]!.AsArray().Select(node => node!["datum"]!.GetValue<string>()).ToHashSet().SetEquals(["2026-08-10", "2026-08-17"]) &&
                master["icsZusatzTermine"]!.AsArray().Single()!["datum"]!.GetValue<string>() == "2026-08-24" &&
                master["icsZusatzTermine"]!.AsArray().Single()!["zeit"]!.GetValue<string>() == "17:00" &&
                exception["datum"]!.GetValue<string>() == "2026-08-10" && exception["zeit"]!.GetValue<string>() == "13:00",
                "Thunderbird-Override oder strukturierte EXDATE/RDATE wurden nicht mit dem Master verknüpft.");
            TestAssert.That(eiermann["datum"]!.GetValue<string>() == "1998-01-05" &&
                eiermann["wiederholung"]!["art"]!.GetValue<string>() == "weekly" &&
                eiermann["wiederholung"]!["intervall"]!.GetValue<int>() == 2,
                "Thunderbird Schema 23 verlor die 14-Tage-Serie von 1998.");
            var reminderData = new System.Text.Json.Nodes.JsonObject
            {
                ["einstellungen"] = new System.Text.Json.Nodes.JsonObject { ["erinnerung"] = new System.Text.Json.Nodes.JsonObject { ["vorlauf"] = 15, ["verpasste"] = true } },
                ["termine"] = parsed.Termine.DeepClone()
            }.ToJsonString();
            var biweekly = ReminderScheduler.DueAppointments(reminderData, new DateTime(2026, 9, 7, 8, 45, 0));
            var deleted = ReminderScheduler.DueAppointments(reminderData, new DateTime(2026, 8, 10, 10, 45, 0));
            var moved = ReminderScheduler.DueAppointments(reminderData, new DateTime(2026, 8, 10, 12, 45, 0));
            var added = ReminderScheduler.DueAppointments(reminderData, new DateTime(2026, 8, 24, 16, 45, 0));
            TestAssert.That(biweekly.Any(item => item.Key.Contains("eiermann-1998@202609070900", StringComparison.Ordinal)) &&
                !deleted.Any(item => item.Start == new DateTime(2026, 8, 10, 11, 0, 0)) &&
                moved.Any(item => item.Start == new DateTime(2026, 8, 10, 13, 0, 0)) &&
                added.Any(item => item.Start == new DateTime(2026, 8, 24, 17, 0, 0)),
                "Native Erinnerungen expandieren Thunderbird-Serie, Override oder RDATE nicht korrekt.");
            var broken = Path.Combine(root, "broken.sqlite"); File.WriteAllText(broken, "kein sqlite");
            var allProfiles = ThunderbirdCalendarImporter.ParseProfiles(new[] { broken, path }, out var read);
            TestAssert.That(read == 1 && allProfiles.Termine.Count == 3 && allProfiles.Aufgaben.Count == 1 && allProfiles.Uebersprungen == 3,
                "Ein defektes Thunderbird-Profil blockierte weitere Profile oder wurde nicht gemeldet.");
            var secondRoot = Path.Combine(root, "zweites-profil"); Directory.CreateDirectory(secondRoot);
            var secondPath = Path.Combine(secondRoot, "local.sqlite"); File.Copy(path, secondPath);
            var profiles = ThunderbirdCalendarImporter.ParseProfiles(new[] { path, secondPath }, out read);
            var sources = profiles.Termine.Where(node => node!["uid"]!.GetValue<string>() == "eiermann-1998")
                .Select(node => node!["icsQuelleId"]!.GetValue<string>()).ToHashSet();
            TestAssert.That(read == 2 && profiles.Termine.Count == 6 && profiles.Aufgaben.Count == 2 && sources.Count == 2 &&
                profiles.Termine.Where(node => node!["uid"]!.GetValue<string>() == "eiermann-1998")
                    .All(node => node!["syncKalenderUid"]!.GetValue<string>() == node!["icsQuelleId"]!.GetValue<string>()),
                "Gleiche Thunderbird-UIDs aus verschiedenen Profilen teilten eine Quellidentität.");

            var fixturePath = Path.Combine(TestSource.Root(Path.Combine("contracts", "thunderbird-addressbook-fixture.json")),
                "contracts", "thunderbird-addressbook-fixture.json");
            var fixture = JsonNode.Parse(File.ReadAllText(fixturePath))!.AsObject();
            var thunderbirdRoot = Path.Combine(root, "Thunderbird"); var relativeProfile = Path.Combine(thunderbirdRoot, "Profiles", "relative.default");
            var customProfile = Path.Combine(root, "custom profile"); Directory.CreateDirectory(thunderbirdRoot);
            CreateAddressBook(Path.Combine(relativeProfile, "history.sqlite"), fixture);
            CreateAddressBook(Path.Combine(customProfile, "abook-2.sqlite"), fixture);
            File.WriteAllText(Path.Combine(thunderbirdRoot, "profiles.ini"),
                "[Profile0]\nIsRelative=1\nPath=Profiles/relative.default\n[Profile1]\nIsRelative=0\nPath=" + customProfile + "\n");
            var discovered = ThunderbirdCalendarImporter.DiscoverProfiles(thunderbirdRoot);
            var contacts = ThunderbirdCalendarImporter.ParseAddressBooks(discovered, out var books);
            var expected = fixture["expected"]!.AsObject();
            TestAssert.That(discovered.Count == 2 && discovered.ToHashSet().SetEquals([relativeProfile, customProfile]) &&
                books == 2 && contacts.Kontakte.Count == 2 && contacts.Uebersprungen == 0 &&
                contacts.Kontakte.Select(node => node!["uid"]!.GetValue<string>()).Distinct().Count() == 2,
                "Relative/absolute profiles, history.sqlite or namespaced card identity was lost.");
            // The native payload carries BDAY on each contact; the web importer creates its linked birthday.
            TestAssert.That(contacts.Geburtstage.Count == 0, "Contact birthdays must not also be emitted as standalone birthdays.");
            foreach (var book in new[] { Path.Combine(relativeProfile, "history.sqlite"), Path.Combine(customProfile, "abook-2.sqlite") })
            {
                var reimport = ThunderbirdCalendarImporter.ParseAddressBook(book);
                var uid = reimport.Kontakte.Single()!["uid"]!.GetValue<string>();
                TestAssert.That(uid.StartsWith("thunderbird:", StringComparison.Ordinal) &&
                    uid.EndsWith(":" + fixture["card"]!.GetValue<string>(), StringComparison.Ordinal) &&
                    JsonNode.DeepEquals(contacts.Kontakte.Single(node => node!["uid"]!.GetValue<string>() == uid), reimport.Kontakte[0]) &&
                    reimport.Geburtstage.Count == 0, "Each profile/book must retain its stable card identity and complete contact fields.");
            }
            foreach (var node in contacts.Kontakte)
            {
                var contact = node!.AsObject(); var addresses = contact["anschriften"]!.AsArray();
                TestAssert.That(contact["nachname"]!.GetValue<string>() == expected["lastName"]!.GetValue<string>() &&
                    contact["vorname"]!.GetValue<string>() == "" && contact["emailEintraege"]!.AsArray().Count == expected["emailCount"]!.GetValue<int>() &&
                    contact["telefone"]!.AsArray().Count == expected["phoneCount"]!.GetValue<int>() && addresses.Count == 2 &&
                    addresses.Select(address => address!["region"]!.GetValue<string>()).ToHashSet().SetEquals(["Berlin", "Brandenburg"]) &&
                    contact["notiz"]!.GetValue<string>() == "Complete Thunderbird note" && contact["foto"]!.GetValue<string>().StartsWith("data:image/png;base64,") &&
                    contact["geburtstag"]!.GetValue<string>() == expected["birthday"]!.GetValue<string>() &&
                    !contact["geburtstagJahrUnbekannt"]!.GetValue<bool>() &&
                    contact["jubilaeum"]!.GetValue<string>() == expected["anniversary"]!.GetValue<string>(),
                    "Thunderbird contact fields or incomplete _vCard supplements were lost.");
            }
            var occasionPath = Path.Combine(root, "occasions.sqlite");
            using (var occasionDb = new SqliteConnection("Data Source=" + occasionPath))
            {
                occasionDb.Open(); Execute(occasionDb, "CREATE TABLE cal_events (cal_id TEXT,id TEXT,title TEXT,privacy TEXT,ical_status TEXT,flags INTEGER,event_start INTEGER,event_start_tz TEXT,event_end INTEGER,event_end_tz TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT)");
                Execute(occasionDb, "CREATE TABLE cal_properties (cal_id TEXT,item_id TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT,key TEXT,value TEXT)");
                Execute(occasionDb, "CREATE TABLE cal_recurrence (cal_id TEXT,item_id TEXT,recurrence_id INTEGER,recurrence_id_tz TEXT,icalString TEXT)");
                foreach (var item in new[] { ("birthday", "Van Dame Birthday", "Birthday"), ("anniversary", "Van Dame Anniversary", "Anniversary"), ("arbitrary", "Annual planning", "Anniversary") })
                {
                    Insert(occasionDb, "INSERT INTO cal_events VALUES ('c',$i,$t,'PUBLIC','CONFIRMED',24,$s,'floating',$e,'floating',NULL,NULL)",
                        ("$i", item.Item1), ("$t", item.Item2), ("$s", Native(2020, 6, 7)), ("$e", Native(2020, 6, 8)));
                    Insert(occasionDb, "INSERT INTO cal_properties VALUES ('c',$i,NULL,NULL,'CATEGORIES',$v)", ("$i", item.Item1), ("$v", item.Item3));
                    Insert(occasionDb, "INSERT INTO cal_recurrence VALUES ('c',$i,NULL,NULL,'RRULE:FREQ=YEARLY')", ("$i", item.Item1));
                }
            }
            var occasions = ThunderbirdCalendarImporter.Parse(occasionPath);
            TestAssert.That(occasions.Jahrestage.Count == 2 && occasions.Termine.Count == 1 &&
                occasions.Jahrestage.Select(node => node!["typ"]!.GetValue<string>()).ToHashSet().SetEquals(["birthday", "anniversary"]) &&
                occasions.Jahrestage.All(node => node!["datum"]!.ToString() == "--06-07" && node["jahrUnbekannt"]!.GetValue<bool>()) &&
                occasions.Termine[0]!["uid"]!.GetValue<string>() == "arbitrary",
                "Ordinary Thunderbird occasions were missed or an arbitrary yearly event was misclassified.");
            var modernPath = Path.Combine(root, "modern", "history.sqlite");
            var modernCard = "BEGIN:VCARD\r\nVERSION:4.0\r\nN:Van Dame;;;;\r\nFN:Van Dame\r\nORG:Original Company;Department\r\n" +
                "BDAY;X-APPLE-OMIT-YEAR=1604:1604-02-29\r\nANNIVERSARY:--0607\r\nTITLE:Engineer\r\nURL:https://example.test\r\n" +
                "EMAIL;TYPE=HOME:one@example.test\r\nADR;TYPE=WORK:;;Main 1;Berlin;Berlin;10115;Germany\r\nPHOTO;VALUE=uri:" +
                new Uri(Path.Combine(Path.GetDirectoryName(modernPath)!, "Photos", "real.png")).AbsoluteUri + "\r\nEND:VCARD\r\n";
            CreateAddressBook(modernPath, new JsonObject { ["card"] = "equal-card-id", ["properties"] = new JsonArray(
                new JsonArray("_vCard", modernCard), new JsonArray("PrimaryEmail", "one@example.test"), new JsonArray("SecondEmail", "two@example.test"),
                new JsonArray("Company", "Stale Company"), new JsonArray("HomePhone", "+4930111"), new JsonArray("Notes", "Supplemented note")) });
            var firstModern = ThunderbirdCalendarImporter.ParseAddressBook(modernPath).Kontakte;
            var secondModern = ThunderbirdCalendarImporter.ParseAddressBook(modernPath).Kontakte;
            TestAssert.That(firstModern[0]!["uid"]!.ToString() == secondModern[0]!["uid"]!.ToString() && firstModern[0]!["uid"]!.ToString() != contacts.Kontakte[0]!["uid"]!.ToString(),
                "Modern Thunderbird reimport changed its book-scoped identity.");
            var modernUid = firstModern[0]!["uid"]!.GetValue<string>();
            for (var round = 0; round < 2; round++)
            {
                using var saved = System.Text.Json.JsonDocument.Parse(firstModern.ToJsonString());
                var text = ExchangeCodec.WriteVCard(saved.RootElement).Text;
                var modernRoundtrip = ExchangeCodec.ParseVCard(text);
                firstModern = modernRoundtrip.Kontakte;
                var contact = firstModern.Single()!;
                TestAssert.That(contact["uid"]!.GetValue<string>() == modernUid && modernRoundtrip.Geburtstage.Count == 0 &&
                    contact["geburtstagJahrUnbekannt"]!.GetValue<bool>() &&
                    contact["nachname"]!.ToString() == "Van Dame" && contact["vorname"]!.ToString() == "" && contact["firma"]!.ToString() == "Original Company" &&
                    contact["geburtstag"]!.ToString() == "--02-29" && contact["jubilaeum"]!.ToString() == "--06-07" && contact["emails"]!.AsArray().Count == 2 &&
                    contact["telefone"]!.AsArray().Count == 1 && contact["foto"]!.ToString().StartsWith("data:image/png;base64,", StringComparison.Ordinal) &&
                    contact["notiz"]!.ToString() == "Supplemented note" && contact["anschriften"]![0]!["region"]!.ToString() == "Berlin" &&
                    text.Contains("ORG:Original Company;Department", StringComparison.Ordinal) && text.Contains("TITLE:Engineer", StringComparison.Ordinal) && text.Contains("URL:https://example.test", StringComparison.Ordinal),
                    "Modern Thunderbird contact lost a canonical or supplemented field during repeated save/export.");
            }
        }
        finally { SqliteConnection.ClearAllPools(); Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    private static long Native(int year, int month, int day, int hour = 0, int minute = 0) => new DateTimeOffset(year, month, day, hour, minute, 0, TimeSpan.Zero).ToUnixTimeMilliseconds() * 1000;
    private static void Execute(SqliteConnection db, string sql) { using var command = db.CreateCommand(); command.CommandText = sql; command.ExecuteNonQuery(); }
    private static void Insert(SqliteConnection db, string sql, params (string Name, object Value)[] values)
    {
        using var command = db.CreateCommand(); command.CommandText = sql;
        foreach (var (name, value) in values) command.Parameters.AddWithValue(name, value); command.ExecuteNonQuery();
    }

    private static void CreateAddressBook(string path, JsonObject fixture)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!); Directory.CreateDirectory(Path.Combine(Path.GetDirectoryName(path)!, "Photos"));
        File.WriteAllBytes(Path.Combine(Path.GetDirectoryName(path)!, "Photos", "real.png"), Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="));
        using var db = new SqliteConnection("Data Source=" + path); db.Open(); Execute(db, "CREATE TABLE properties (card TEXT,name TEXT,value TEXT)");
        foreach (var property in fixture["properties"]!.AsArray()) Insert(db, "INSERT INTO properties VALUES ($c,$n,$v)",
            ("$c", fixture["card"]!.GetValue<string>()), ("$n", property![0]!.GetValue<string>()), ("$v", property[1]!.GetValue<string>()));
    }

}
