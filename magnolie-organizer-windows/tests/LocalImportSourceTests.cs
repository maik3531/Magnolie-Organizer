using Microsoft.Data.Sqlite;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class LocalImportSourceTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-local-source-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var contacts = Path.Combine(root, "Contacts"); Directory.CreateDirectory(contacts);
            File.WriteAllText(Path.Combine(contacts, "owned.contact"), WindowsContactStore.Serialize(
                new JsonObject { ["vorname"] = "Owned", ["nachname"] = "Windows", ["notiz"] = "Owned local 🌸 note" }, "owned-windows@example.invalid"));
            var thunderbird = Path.Combine(root, "Thunderbird"); var profile = Path.Combine(thunderbird, "Profiles", "owned.default");
            Directory.CreateDirectory(Path.Combine(profile, "calendar-data"));
            File.WriteAllText(Path.Combine(thunderbird, "profiles.ini"), "[Profile0]\nIsRelative=1\nPath=Profiles/owned.default\n");
            var book = Path.Combine(profile, "abook.sqlite");
            using (var db = new SqliteConnection("Data Source=" + book))
            {
                db.Open(); Execute(db, "CREATE TABLE properties (card TEXT,name TEXT,value TEXT)");
                Execute(db, "INSERT INTO properties VALUES ('owned-card','FirstName','Owned'),('owned-card','LastName','Thunderbird'),('owned-card','PrimaryEmail','owned@example.invalid'),('owned-card','Notes','Owned note')");
            }
            using (var db = new SqliteConnection("Data Source=" + Path.Combine(profile, "calendar-data", "local.sqlite")))
            {
                db.Open(); Execute(db, "CREATE TABLE cal_events (cal_id TEXT,id TEXT,title TEXT,flags INTEGER,event_start INTEGER,event_start_tz TEXT,event_end INTEGER,event_end_tz TEXT,last_modified INTEGER,recurrence_id INTEGER,recurrence_id_tz TEXT,privacy TEXT,ical_status TEXT)");
                var start = new DateTimeOffset(2030, 2, 4, 9, 0, 0, TimeSpan.Zero).ToUnixTimeMilliseconds() * 1000;
                Execute(db, $"INSERT INTO cal_events VALUES ('owned-cal','owned-event','Owned local appointment',0,{start},'UTC',{start + 3600000000},'UTC',0,NULL,NULL,'PUBLIC','CONFIRMED')");
            }
            var first = await LocalImportSource.ReadAsync("thunderbird", false, contacts, thunderbird);
            TestAssert.That(first["kontakte"]!.AsArray().Count == 1 && first["termine"]!.AsArray().Count == 1, "Actual local Thunderbird readers did not return the fixture.");
            LocalImportSource.BindSnapshot(first, "thunderbird", "all"); var revision = first["revision"]!.GetValue<string>();
            var second = await LocalImportSource.ReadAsync("thunderbird", false, contacts, thunderbird);
            LocalImportSource.BindSnapshot(second, "thunderbird", "all", revision);
            second["kontakte"]![0]!["id"] = "different-generated-id";
            LocalImportSource.BindSnapshot(second, "thunderbird", "all", revision);
            var wrongScope = false;
            try { LocalImportSource.BindSnapshot(second, "thunderbird", "contacts", revision); }
            catch (InvalidOperationException error) when (error.Message == "mcp_conflict") { wrongScope = true; }
            TestAssert.That(wrongScope, "Local semantic revision did not bind selected scope.");
            var contactOnly = await LocalImportSource.ReadAsync("thunderbird", true, contacts, thunderbird);
            TestAssert.That(contactOnly["kontakte"]!.AsArray().Count == 1 && contactOnly["termine"]!.AsArray().Count == 0, "Contacts-only selection read calendar stores.");
            var windows = await LocalImportSource.ReadAsync("kontakte", false, contacts, thunderbird);
            TestAssert.That(windows["kontakte"]!.AsArray().Single()!["nachname"]!.GetValue<string>() == "Windows" && windows["termine"]!.AsArray().Count == 0, "Windows Contacts source broadened to Thunderbird.");
            LocalImportSource.BindSnapshot(windows, "windows_contacts", "contacts");
            TestAssert.That(windows["revision"]!.GetValue<string>() != revision && windows["pfad"] is null && windows["bytes"] is null, "Local scan fabricated a file proof or ignored source selection.");
            using (var db = new SqliteConnection("Data Source=" + book)) { db.Open(); Execute(db, "UPDATE properties SET value='Owned corrected note' WHERE name='Notes'"); }
            var changed = await LocalImportSource.ReadAsync("thunderbird", false, contacts, thunderbird); var rejected = false;
            try { LocalImportSource.BindSnapshot(changed, "thunderbird", "all", revision); }
            catch (InvalidOperationException error) when (error.Message == "mcp_conflict") { rejected = true; }
            TestAssert.That(rejected, "Changed actual local records accepted an obsolete snapshot revision.");
        }
        finally { SqliteConnection.ClearAllPools(); Directory.Delete(root, true); }
    }

    private static void Execute(SqliteConnection db, string sql)
    { using var command = db.CreateCommand(); command.CommandText = sql; command.ExecuteNonQuery(); }
}
