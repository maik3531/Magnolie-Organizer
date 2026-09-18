using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ContractGroupTests
{
    internal static Task EncryptionAsync()
    {
        const string plain = "{\"probe\":\"Grüße\"}";
        var encrypted = new EncryptionService().Enable(plain, "Rosenholz1896");
        var envelope = JsonNode.Parse(encrypted)!.AsObject();
        var bytes = Convert.FromBase64String(envelope["daten"]!.GetValue<string>());
        bytes[^1] ^= 1;
        envelope["daten"] = Convert.ToBase64String(bytes);
        try { _ = new EncryptionService().Unlock(envelope.ToJsonString(), "Rosenholz1896");
            throw new InvalidOperationException("AES-GCM akzeptierte manipulierte Ciphertext-/Tag-Daten."); }
        catch (CryptographicException) { }
        return Task.CompletedTask;
    }

    internal static Task ArchiveAsync()
    {
        TestAssert.That(GesamtarchivService.IsArchivePath(@"C:\Cloud\backup.MAGNOLIE") &&
            !GesamtarchivService.IsArchivePath(@"C:\Cloud\backup.json"),
            "Die Wiederherstellungsroute erkennt .magnolie nicht eindeutig.");
        var data = JsonNode.Parse("""{"version":6,"termine":[],"kontakte":[{"foto":"data:image/jpeg;base64,/9j/2Q=="}],"notizen":[{"anhaenge":[{"daten":"data:application/pdf;base64,JVBERi0="}]}],"papierkorb":[],"einstellungen":{}}""")!.AsObject();
        var text = GesamtarchivService.Create(data, "linux", "1.31.7", "Rosenholz1896");
        var read = GesamtarchivService.Read(text, "Rosenholz1896");
        var expected = data.DeepClone().AsObject(); expected["version"] = 7;
        TestAssert.That(read.Fotos == 1 && read.Anhaenge == 1 && JsonNode.DeepEquals(read.Daten, expected),
            "Das geschützte Linux/Windows-Gesamtarchiv verlor Foto oder Anhang.");
        var schema3 = JsonNode.Parse(GesamtarchivService.Create(data, "windows", "2.0.6"))!.AsObject();
        TestAssert.That(schema3["datenschema"]!.GetValue<int>() == 3,
            "Neue Gesamtarchive verwenden nicht Datenschema 3.");
        schema3["datenschema"] = 1;
        _ = GesamtarchivService.Read(schema3.ToJsonString());
        schema3["datenschema"] = 4;
        TestAssert.Throws<InvalidDataException>(() => GesamtarchivService.Read(schema3.ToJsonString()),
            "Ein unbekanntes Gesamtarchiv-Datenschema wurde angenommen.");
        var golden = GesamtarchivService.Read(File.ReadAllText(Path.Combine("tests", "fixtures", "linux-ordinal.magnolie")));
        var goldenAppointments = golden.Daten["termine"]!.AsArray();
        TestAssert.That(golden.Plattform == "linux" && goldenAppointments[0]!["wiederholung"]!["art"]!.GetValue<string>() == "monthly" &&
            goldenAppointments[0]!["zeit"]!.GetValue<string>() == "09:15" && goldenAppointments[0]!["endDatum"]!.GetValue<string>() == "2026-01-14" &&
            goldenAppointments[1]!["wiederholung"]!["rruleForm"]!.GetValue<string>() == "bysetpos",
            "Das Linux-Cross-Golden verlor kanonische, zeitgebundene oder zweitägige Serienfelder.");
        var legacy = JsonNode.Parse("""{"termine":[{"wiederholung":{"art":"monthly_weekday","ordinal":2,"wochentag":"TH"}}]}""")!.AsObject();
        var migrated = GesamtarchivService.Create(legacy, "windows", "2.0.2");
        TestAssert.That(!migrated.Contains("monthly_weekday", StringComparison.Ordinal) &&
            GesamtarchivService.Read(migrated).Daten["termine"]![0]!["wiederholung"]!["art"]!.GetValue<string>() == "monthly",
            "Der Windows-Legacy-Alias wurde beim nächsten Speichern nicht kanonisiert.");
        var taskData = JsonNode.Parse("""{"aufgaben":[{"uid":"todo","titel":"Probe","icsRoundtrip":["ATTACH:https://drive.google.com/file/d/1","X-TODO-RAW:opaque"]}]}""")!.AsObject();
        var taskArchive = GesamtarchivService.Read(GesamtarchivService.Create(taskData, "windows", "2.0.2"));
        TestAssert.That(JsonNode.DeepEquals(taskArchive.Daten["aufgaben"]![0]!["icsRoundtrip"], taskData["aufgaben"]![0]!["icsRoundtrip"]),
            "VTODO-ICS-Rohdaten gingen im Gesamtarchiv verloren.");
        var missingUid = new JsonArray(new JsonObject { ["id"] = "ä-1" });
        GesamtarchivService.NormalizeTaskGraph(missingUid);
        TestAssert.That(missingUid[0]!["uid"]!.GetValue<string>() == "mag-task-c841a738bc2a124a@magnolie-organizer",
            "Eine Aufgabe ohne UID wurde nicht deterministisch normalisiert.");
        var graph = new JsonArray(new JsonObject { ["id"] = "kind", ["uid"] = "doppelt", ["elternUid"] = "doppelt" },
            new JsonObject { ["id"] = "zweites", ["uid"] = "doppelt", ["elternUid"] = "fehlt" });
        GesamtarchivService.NormalizeTaskGraph(graph);
        TestAssert.That(graph.Select(item => item!["uid"]!.GetValue<string>()).Distinct(StringComparer.Ordinal).Count() == 2 &&
            graph.All(item => item!["elternUid"]!.GetValue<string>().Length == 0),
            "Windows-Aufgabenmigration weicht von Linux/Web ab oder behielt einen beschädigten Graphen.");
        var reservedUid = GesamtarchivService.StableTaskUid("gleich", "");
        var collisions = new JsonArray(
            new JsonObject { ["id"] = "reserved", ["uid"] = reservedUid },
            new JsonObject { ["id"] = "parent", ["uid"] = "parent" },
            new JsonObject { ["id"] = "gleich", ["elternUid"] = "parent" },
            new JsonObject { ["id"] = "gleich", ["elternUid"] = "parent" });
        GesamtarchivService.NormalizeTaskGraph(collisions);
        TestAssert.That(collisions[2]!["uid"]!.GetValue<string>() == GesamtarchivService.StableTaskUid("gleich", "0") &&
            collisions[3]!["uid"]!.GetValue<string>() == GesamtarchivService.StableTaskUid("gleich", "1") &&
            collisions[2]!["elternUid"]!.GetValue<string>() == "parent" && collisions[3]!["elternUid"]!.GetValue<string>() == "parent",
            "Aufgaben-UID-Kollisionen verwendeten nicht die Salt-Folge leer/0/1 oder verloren ihre Eltern.");
        var technicalUids = new[] { "ä", "z", "\U00010000", "a", "é", "e\u0301", "\ue000" };
        var technicalGraph = new JsonArray(technicalUids.Reverse().Select(uid =>
            (JsonNode)new JsonObject { ["id"] = uid, ["uid"] = uid, ["reihenfolge"] = 0 }).ToArray());
        GesamtarchivService.NormalizeTaskGraph(technicalGraph);
        TestAssert.That(technicalGraph.OrderBy(item => item!["reihenfolge"]!.GetValue<int>())
                .Select(item => item!["uid"]!.GetValue<string>()).SequenceEqual(
                    new[] { "a", "e\u0301", "z", "ä", "é", "\ue000", "\U00010000" }),
            "Technische Aufgabenkennungen verwenden nicht plattformuebergreifend UTF-8-Reihenfolge.");
        return Task.CompletedTask;
    }

    internal static Task ExchangeAsync()
    {
        NativeExchangeRegressions();
        foreach (var valid in new[] { "1604-02-29", "1900-02-28", "2000-02-29", "2024-02-29", "--02-29", "--12-31" })
            TestAssert.That(ExchangeCodec.TryParseCanonicalDate(valid, out _, out _, out _),
                $"Das kanonische Datum {valid} wurde abgewiesen.");
        foreach (var invalid in new[] { "2000-02-30", "2023-02-29", "--02-30", "--00-10", "--2-03", "02-03", "1604", "1900", "2000" })
            TestAssert.That(!ExchangeCodec.TryParseCanonicalDate(invalid, out _, out _, out _),
                $"Das ungültige oder nicht kanonische Datum {invalid} wurde angenommen.");

        const string yearlessVcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Probe;Jahrlose;;;\r\nFN:Jahrlose Probe\r\nBDAY:--02-29\r\nEND:VCARD\r\n";
        var yearlessContact = ExchangeCodec.ParseVCard(yearlessVcard);
        using (var yearlessRestart = JsonDocument.Parse(yearlessContact.Kontakte.ToJsonString()))
        {
            var exported = ExchangeCodec.WriteVCard(yearlessRestart.RootElement).Text;
            TestAssert.That(yearlessContact.Kontakte[0]!["geburtstag"]!.GetValue<string>() == "--02-29" &&
                exported.Contains("VERSION:4.0\r\n", StringComparison.Ordinal) &&
                exported.Contains("BDAY:--0229\r\n", StringComparison.Ordinal) &&
                ExchangeCodec.ParseVCard(exported).Kontakte[0]!["geburtstag"]!.GetValue<string>() == "--02-29",
                "Eine jahrlose vCard-BDAY überstand den Rundlauf nicht kanonisch.");
        }
        var genuine2000 = ExchangeCodec.ParseVCard(yearlessVcard.Replace("--02-29", "2000-02-29", StringComparison.Ordinal));
        TestAssert.That(genuine2000.Kontakte[0]!["geburtstag"]!.GetValue<string>() == "2000-02-29" &&
            genuine2000.Kontakte[0]!["geburtstagJahrUnbekannt"]!.GetValue<bool>() == false,
            "Ein echter vCard-Geburtstag aus 2000 wurde als jahrlos interpretiert.");

        var splitLdif = ExchangeCodec.ParseLdif("dn: cn=Jahrlose Probe\ncn: Jahrlose Probe\nbirthMonth: 2\nbirthDay: 29\n\n");
        TestAssert.That(splitLdif.Kontakte[0]!["geburtstag"]!.GetValue<string>() == "--02-29",
            "Getrennte LDIF-Monats-/Tagesfelder erzeugten kein jahrloses Datum.");
        var markerYears = ExchangeCodec.ParseLdif("dn: cn=Marker Probe\ncn: Marker Probe\nbirthMonth: 2\nbirthDay: 28\nbirthYear: 1604\n\n");
        TestAssert.That(markerYears.Kontakte[0]!["geburtstag"]!.GetValue<string>() == "1604-02-28",
            "Ein vorhandenes LDIF-Jahr wurde als unbekannt interpretiert.");
        foreach (var (fields, expected) in new[]
        {
            ("birthMonth: 2\nbirthDay: 29", "--02-29"),
            ("birthMonth: 2\nbirthDay: 29\nbirthYear: 0000", "--02-29"),
            ("mozillaBirthMonth: 2\nmozillaBirthDay: 29", "--02-29"),
            ("BIRTHMONTH: 2\nBIRTHDAY: 29\nBIRTHYEAR: 2000", "2000-02-29"),
            ("birthMonth: 2\nbirthDay: 29\nbirthYear: 1604", "1604-02-29"),
            ("birthday: --02-29", "--02-29"),
            ("birthday: 1980-04-03", "1980-04-03"),
            ("dateOfBirth: 1980-04-03\nbirthMonth: 2\nbirthDay: 29", "1980-04-03"),
            ("birthMonth: 2\nbirthDay: 30", ""),
            ("birthMonth: 2\nbirthDay: 29\nbirthYear: 2023", "")
        })
        {
            var parsed = ExchangeCodec.ParseLdif("dn: cn=Display Only\nuid: split-date\ncn: Display Only\n" + fields + "\n\n");
            var contact = parsed.Kontakte.Single()!;
            TestAssert.That(parsed.Uebersprungen == 0 && contact["uid"]!.GetValue<string>() == "split-date" &&
                contact["anzeigename"]!.GetValue<string>() == "Display Only" && contact["vorname"]!.GetValue<string>() == "" &&
                contact["nachname"]!.GetValue<string>() == "" && contact["geburtstag"]!.GetValue<string>() == expected &&
                (expected.Length == 0 || contact["geburtstagJahrUnbekannt"]!.GetValue<bool>() == expected.StartsWith("--", StringComparison.Ordinal)),
                "LDIF split-day/full-birthday precedence or canonical date validation failed: " + fields);
        }
        using (var ldifDates = JsonDocument.Parse("""[{"nachname":"Jahrlos","geburtstag":"--02-29"},{"nachname":"Echt","geburtstag":"2000-02-29"}]"""))
        {
            var exported = ExchangeCodec.WriteLdif(ldifDates.RootElement).Text;
            var restored = ExchangeCodec.ParseLdif(exported);
            TestAssert.That(restored.Kontakte[0]!["geburtstag"]!.ToString() == "--02-29" &&
                restored.Kontakte[1]!["geburtstag"]!.ToString() == "2000-02-29",
                "LDIF lost a yearless birthday or changed a genuine birth year.");
        }

        using (var anniversaryDates = JsonDocument.Parse("""[{"uid":"partial","name":"Jahrlos","datum":"--02-29","typ":"birthday"},{"uid":"full","name":"Echt","datum":"2000-02-29","typ":"birthday"}]"""))
        {
            var exported = ExchangeCodec.WriteIcs("ics-jahrestage", anniversaryDates.RootElement).Text;
            var imported = ExchangeCodec.ParseIcs(exported);
            TestAssert.That(exported.Contains("DTSTART;VALUE=DATE:20000229", StringComparison.Ordinal) &&
                exported.Contains("X-MAGNOLIE-DATE:--02-29", StringComparison.Ordinal) &&
                imported.Jahrestage.Any(item => item?["uid"]?.ToString() == "partial" && item?["datum"]?.ToString() == "--02-29") &&
                imported.Jahrestage.Any(item => item?["uid"]?.ToString() == "full" && item?["datum"]?.ToString() == "2000-02-29"),
                "ICS unterschied beim Jahrestags-Rundlauf jahrlos und echtes Jahr 2000 nicht.");
        }
        const string invalidExtension = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:external-2000\r\nDTSTART;VALUE=DATE:20000229\r\nRRULE:FREQ=YEARLY\r\nCATEGORIES:Geburtstag\r\nSUMMARY:Echt\r\nX-MAGNOLIE-TYPE-ID:birthday\r\nX-MAGNOLIE-DATE:--02-30\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        TestAssert.That(ExchangeCodec.ParseIcs(invalidExtension).Jahrestage[0]!["datum"]!.GetValue<string>() == "2000-02-29",
            "Eine ungültige Magnolie-ICS-Erweiterung überschrieb das externe echte Jahr 2000.");
        const string externalNamedAnniversaries = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:befreiung\r\nDTSTART;VALUE=DATE:20260508\r\nRRULE:FREQ=YEARLY\r\nCATEGORIES:Regionaler Feiertag\r\nSUMMARY:Jahrestag der Befreiung vom Nationalsozialismus\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:google-birthday\r\nDTSTART;VALUE=DATE:19900826\r\nRRULE:FREQ=YEARLY\r\nCATEGORIES:Birthday\r\nSUMMARY:Herzlichen Glückwunsch zum Geburtstag\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        var externalNamedImport = ExchangeCodec.ParseIcs(externalNamedAnniversaries);
        TestAssert.That(externalNamedImport.Termine.Count == 2 && externalNamedImport.Jahrestage.Count == 0 &&
            externalNamedImport.Termine.All(item => item?["wiederholung"]?["art"]?.ToString() == "yearly"),
            "Titel oder Kategorie wandelten externe Ganztagstermine in Jahrestage um.");

        var fixture = File.ReadAllText(Path.Combine("tests", "fixtures", "golden-komplex.ics"));
        var thunderbird = ExchangeCodec.ParseIcs(fixture);
        TestAssert.That(thunderbird.Termine.Count == 1 && thunderbird.Termine[0]!["icsKomplex"]!.GetValue<bool>(),
            "Die Thunderbird-artige komplexe ICS-Fixture wurde angenähert oder verloren.");
        const string todo = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:todo-roundtrip\r\nSUMMARY:Probe\r\nATTACH:https://drive.google.com/file/d/1\r\nX-TODO-RAW:opaque\r\nEND:VTODO\r\nEND:VCALENDAR\r\n";
        var parsedTodo = ExchangeCodec.ParseIcs(todo);
        using (var todoRestart = JsonDocument.Parse(parsedTodo.Aufgaben.ToJsonString()))
        {
            var exportedTodo = ExchangeCodec.WriteIcs("ics-aufgaben", todoRestart.RootElement).Text;
            TestAssert.That(exportedTodo.Contains("ATTACH:https://drive.google.com/file/d/1", StringComparison.Ordinal) &&
                exportedTodo.Contains("X-TODO-RAW:opaque", StringComparison.Ordinal),
                "VTODO-ICS-Rohdaten überstanden Neustart und Export nicht.");
        }
        const string componentProbe = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTIMEZONE\r\nTZID:UTC\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT\r\nUID:alarm-event\r\nDTSTART:20260818T100000Z\r\nSUMMARY:Alarm\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\nBEGIN:VJOURNAL\r\nUID:j-1\r\nEND:VJOURNAL\r\nBEGIN:VFREEBUSY\r\nUID:f-1\r\nEND:VFREEBUSY\r\nEND:VCALENDAR\r\n";
        var componentImport = ExchangeCodec.ParseIcs(componentProbe);
        TestAssert.That(componentImport.Uebersprungen == 2 &&
            componentImport.Termine[0]!["icsRoundtrip"]!.AsArray().Any(line => line?.ToString() == "BEGIN:VALARM") &&
            componentImport.Termine[0]!["icsRoundtrip"]!.AsArray().Any(line => line?.ToString() == "END:VALARM"),
            "VJOURNAL/VFREEBUSY wurden nicht gemeldet oder VTIMEZONE/VALARM fälschlich als Verlust gezählt.");
        try
        {
            _ = ExchangeCodec.ParseIcs("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260818T100000Z\r\nBEGIN:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n");
            throw new InvalidOperationException("Unvollständige ICS-Verschachtelung wurde akzeptiert.");
        }
        catch (InvalidDataException) { }
        var anniversaryIcs = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:anniversary-rich\r\nDTSTART;VALUE=DATE:19900812\r\nRRULE:FREQ=YEARLY\r\nCATEGORIES:Geburtstag\r\nX-MAGNOLIE-TYPE-ID:birthday\r\nSUMMARY:Mia\r\nLOCATION:Garten\r\nORGANIZER:mailto:host@example.org\r\nATTENDEE:mailto:mia@example.org\r\nATTACH:https://www.dropbox.com/s/a\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-P1D\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        var anniversary = ExchangeCodec.ParseIcs(anniversaryIcs);
        using (var anniversaryRestart = JsonDocument.Parse(anniversary.Jahrestage.ToJsonString()))
        {
            var exported = ExchangeCodec.WriteIcs("ics-jahrestage", anniversaryRestart.RootElement).Text;
            TestAssert.That(new[] { "LOCATION:Garten", "ORGANIZER:mailto:host@example.org", "ATTENDEE:mailto:mia@example.org",
                "ATTACH:https://www.dropbox.com/s/a", "BEGIN:VALARM", "TRIGGER:-P1D" }.All(value => exported.Contains(value, StringComparison.Ordinal)),
                "Jahrestagsreduktion verlor VEVENT-Zusatzdaten.");
        }
        var attachLines = new[]
        {
            "ATTACH:https://drive.google.com/file/d/1", "ATTACH:https://1drv.ms/u/s!abc",
            "ATTACH:https://www.dropbox.com/s/a", "ATTACH:https://cloud.example/remote.php/dav/files/a.pdf",
            "ATTACH:https://example.org/a.pdf", "ATTACH:http://example.org/a.pdf",
            "ATTACH:file:///C:/Users/Mia/a.pdf", "ATTACH:custom+opaque://provider/item"
        };
        var providerIcs = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:providers\r\nDTSTART:20260812T120000\r\nSUMMARY:Provider\r\n" +
            string.Join("\r\n", attachLines) + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        var providerImport = ExchangeCodec.ParseIcs(providerIcs);
        using (var providerRestart = JsonDocument.Parse(providerImport.Termine.ToJsonString()))
        {
            var providerExport = ExchangeCodec.WriteIcs("ics-termine", providerRestart.RootElement).Text;
            TestAssert.That(attachLines.All(line => providerExport.Contains(line, StringComparison.Ordinal)),
                "Die ATTACH-Provider-Matrix wurde nicht opak erhalten.");
        }
        using (var rejectedRaw = JsonDocument.Parse("""[{"uid":"raw","datum":"2026-08-12","titel":"Raw","icsRoundtrip":["X-OK:yes","kein Doppelpunkt",17]}]"""))
        {
            var rejected = ExchangeCodec.WriteIcs("ics-termine", rejectedRaw.RootElement);
            TestAssert.That(rejected.RawOmitted == 2 && rejected.Bericht.Contains("2", StringComparison.Ordinal) &&
                rejected.Text.Contains("X-OK:yes", StringComparison.Ordinal),
                "Verworfenes ICS-Rohmaterial wurde nicht gezählt und gemeldet.");
        }
        foreach (var (rule, form) in new[] { ("FREQ=MONTHLY;BYDAY=2TH", "byday"), ("FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2", "bysetpos") })
        {
            var ordinal = ExchangeCodec.ParseIcs($$"""
                BEGIN:VCALENDAR
                VERSION:2.0
                BEGIN:VEVENT
                UID:ordinal-{{form}}
                DTSTART;VALUE=DATE:20240111
                DTEND;VALUE=DATE:20240112
                RRULE:{{rule}}
                SUMMARY:Forumserie
                END:VEVENT
                END:VCALENDAR
                """);
            var appointment = ordinal.Termine[0]!.AsObject();
            TestAssert.That(!appointment["icsKomplex"]!.GetValue<bool>() &&
                appointment["wiederholung"]!["art"]!.GetValue<string>() == "monthly" &&
                appointment["wiederholung"]!["ordinal"]!.GetValue<int>() == 2 &&
                appointment["wiederholung"]!["wochentag"]!.GetValue<string>() == "TH" &&
                appointment["wiederholung"]!["rruleForm"]!.GetValue<string>() == form,
                $"Die ordinale Monatsserie {rule} wurde nicht persistent abgebildet.");
            appointment.Remove("icsRoundtrip");
            using var restart = JsonDocument.Parse(ordinal.Termine.ToJsonString());
            var roundtrip = ExchangeCodec.WriteIcs("ics-termine", restart.RootElement).Text;
            TestAssert.That(roundtrip.Contains("RRULE:" + rule, StringComparison.Ordinal),
                $"Die RRULE-Schreibform {rule} überstand Neustart/Export nicht.");
        }
        var timed = ExchangeCodec.ParseIcs("""
            BEGIN:VCALENDAR
            VERSION:2.0
            BEGIN:VEVENT
            UID:timed-last-friday
            DTSTART:20260130T091500
            DTEND:20260131T104500
            RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1
            SUMMARY:Zeitserie
            END:VEVENT
            END:VCALENDAR
            """).Termine[0]!.AsObject();
        TestAssert.That(!timed["icsKomplex"]!.GetValue<bool>() && timed["endDatum"]!.GetValue<string>() == "2026-01-31" &&
            timed["wiederholung"]!["ordinal"]!.GetValue<int>() == -1 && timed["wiederholung"]!["wochentag"]!.GetValue<string>() == "FR",
            "Die zeitgebundene zweitägige ordinale Serie wurde nicht exakt importiert.");
        using var timedRestart = JsonDocument.Parse(new JsonArray(timed.DeepClone()).ToJsonString());
        var timedIcs = ExchangeCodec.WriteIcs("ics-termine", timedRestart.RootElement).Text;
        TestAssert.That(timedIcs.Contains("RRULE:FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1", StringComparison.Ordinal) &&
            timedIcs.Contains("DTEND:20260131T104500", StringComparison.Ordinal),
            "Zeit, Mehrtagesdauer oder BYSETPOS gingen beim Neustart/ICS-Export verloren.");
        using (var structuredDates = JsonDocument.Parse("""
            [{"uid":"structured","datum":"2026-09-01","zeit":"09:15","titel":"Strukturserie",
              "wiederholung":{"art":"custom","daten":["2026-09-10"]},
              "icsAusnahmen":["2026-09-08","2026-09-08","ungueltig"],
              "icsZusatzDaten":["2026-09-10","2026-09-10","2026-09-08","ungueltig"]}]
            """))
        {
            var written = ExchangeCodec.WriteIcs("ics-termine", structuredDates.RootElement).Text;
            TestAssert.That(written.Contains("EXDATE:20260908T091500", StringComparison.Ordinal) &&
                written.Split("RDATE:20260910T091500", StringSplitOptions.None).Length - 1 == 1 &&
                !written.Contains("RDATE:20260908T091500", StringComparison.Ordinal),
                "Strukturierte zeitgebundene EXDATE/RDATE wurden nicht kanonisch oder konfliktfrei geschrieben.");
            var parsed = ExchangeCodec.ParseIcs(written).Termine[0]!.AsObject();
            using var restart = JsonDocument.Parse(new JsonArray(parsed.DeepClone()).ToJsonString());
            var reparsed = ExchangeCodec.ParseIcs(ExchangeCodec.WriteIcs("ics-termine", restart.RootElement).Text).Termine[0]!;
            TestAssert.That(parsed["icsAusnahmeTermine"]!.AsArray().Any(value => value?["datum"]?.ToString() == "2026-09-08" && value?["zeit"]?.ToString() == "09:15") &&
                parsed["icsZusatzDaten"]!.AsArray().Any(value => value?.ToString() == "2026-09-10") &&
                JsonNode.DeepEquals(parsed["icsAusnahmeTermine"], reparsed["icsAusnahmeTermine"]) &&
                JsonNode.DeepEquals(parsed["icsZusatzDaten"], reparsed["icsZusatzDaten"]),
                "Strukturierte Serienvorkommen überstanden Parse-/Schreib-/Reparse-Rundlauf nicht.");
        }
        using (var allDayDates = JsonDocument.Parse("""
            [{"uid":"all-day-structured","datum":"2026-10-01","titel":"Ganztag",
              "wiederholung":{"art":"monthly"},"icsAusnahmen":["2026-11-01"],"icsZusatzDaten":["2026-10-15"]}]
            """))
        {
            var written = ExchangeCodec.WriteIcs("ics-termine", allDayDates.RootElement).Text;
            TestAssert.That(written.Contains("EXDATE;VALUE=DATE:20261101", StringComparison.Ordinal) &&
                written.Contains("RDATE;VALUE=DATE:20261015", StringComparison.Ordinal),
                "Strukturierte ganztägige EXDATE/RDATE verloren VALUE=DATE.");
        }
        using (var rawDedupe = JsonDocument.Parse("""
            [{"uid":"raw-dedupe","datum":"2026-09-01","zeit":"09:15","titel":"Rohdaten",
              "wiederholung":{"art":"custom","daten":["2026-09-10"]},
              "icsAusnahmen":["2026-09-08"],"icsZusatzDaten":["2026-09-10"],
              "icsRoundtrip":["RDATE:20260910T091500","EXDATE:20260908T091500"]}]
            """))
        {
            var written = ExchangeCodec.WriteIcs("ics-termine", rawDedupe.RootElement).Text;
            TestAssert.That(written.Split("RDATE:20260910T091500", StringSplitOptions.None).Length - 1 == 1 &&
                written.Split("EXDATE:20260908T091500", StringSplitOptions.None).Length - 1 == 1,
                "Strukturierte, benutzerdefinierte und rohe RDATE/EXDATE wurden dupliziert.");
        }
        using (var mixedRdates = JsonDocument.Parse("""
            [{"uid":"mixed-rdates","datum":"2026-09-01","zeit":"09:15","titel":"Gemischte Zusatztermine",
              "wiederholung":{"art":"weekly"},"icsZusatzDaten":["2026-09-10","2026-09-12"],
              "icsRoundtrip":["RDATE;TZID=Europe/Berlin:20260910T091500"]}]
            """))
        {
            var written = ExchangeCodec.WriteIcs("ics-termine", mixedRdates.RootElement).Text;
            TestAssert.That(written.Contains("RDATE;TZID=Europe/Berlin:20260910T091500", StringComparison.Ordinal) &&
                written.Contains("RDATE:20260912T091500", StringComparison.Ordinal) &&
                written.Split("20260910T091500", StringSplitOptions.None).Length - 1 == 1,
                "Rohe und strukturierte RDATE-Werte überstanden den gemischten Export nicht verlust- und duplikatfrei.");
        }
        using (var mixedExdates = JsonDocument.Parse("""
            [{"uid":"mixed-exdates","datum":"2026-09-01","zeit":"09:15","titel":"Gemischte Ausnahmen",
              "wiederholung":{"art":"weekly"},"icsAusnahmen":["2026-09-08","2026-09-15"],
              "icsRoundtrip":["EXDATE;TZID=Europe/Berlin:20260908T091500"]}]
            """))
        {
            var written = ExchangeCodec.WriteIcs("ics-termine", mixedExdates.RootElement).Text;
            TestAssert.That(written.Contains("EXDATE;TZID=Europe/Berlin:20260908T091500", StringComparison.Ordinal) &&
                written.Contains("EXDATE:20260915T091500", StringComparison.Ordinal) &&
                written.Split("20260908T091500", StringSplitOptions.None).Length - 1 == 1,
                "Rohe und strukturierte EXDATE-Werte überstanden den gemischten Export nicht verlust- und duplikatfrei.");
        }
        using (var crossConflict = JsonDocument.Parse("""
            [{"uid":"cross-conflict","datum":"2026-09-01","zeit":"09:15","titel":"Ausnahmevorrang",
              "wiederholung":{"art":"weekly"},"icsAusnahmen":["2026-09-08"],"icsZusatzDaten":["2026-09-15"],
              "icsRoundtrip":["RDATE:20260908T091500","EXDATE:20260915T091500"]}]
            """))
        {
            var written = ExchangeCodec.WriteIcs("ics-termine", crossConflict.RootElement).Text;
            TestAssert.That(written.Contains("RDATE:20260908T091500", StringComparison.Ordinal) &&
                written.Contains("EXDATE:20260908T091500", StringComparison.Ordinal) &&
                written.Contains("EXDATE:20260915T091500", StringComparison.Ordinal) &&
                !written.Contains("RDATE:20260915T091500", StringComparison.Ordinal),
                "Eine rohe oder strukturierte Ausnahme verlor bei einem RDATE-Konflikt ihren Vorrang.");
        }
        foreach (var property in new[] { "EXDATE;VALUE=DATE:20240208", "RECURRENCE-ID;VALUE=DATE:20240208" })
        {
            var guarded = ExchangeCodec.ParseIcs($$"""
                BEGIN:VCALENDAR
                VERSION:2.0
                BEGIN:VEVENT
                UID:ordinal-guard
                DTSTART;VALUE=DATE:20240111
                RRULE:FREQ=MONTHLY;BYDAY=2TH
                {{property}}
                SUMMARY:Ausnahme
                END:VEVENT
                END:VCALENDAR
                """);
            TestAssert.That(guarded.Termine[0]!["icsKomplex"]!.GetValue<bool>() &&
                guarded.Termine[0]!["wiederholung"]!["art"]!.GetValue<string>() == "monthly",
                $"{property} deaktivierte eine strukturell darstellbare Serie.");
            using var guardedRestart = JsonDocument.Parse(guarded.Termine.ToJsonString());
            var guardedRoundtrip = ExchangeCodec.WriteIcs("ics-termine", guardedRestart.RootElement).Text;
            TestAssert.That(guardedRoundtrip.Contains("RRULE:FREQ=MONTHLY;BYDAY=2TH", StringComparison.Ordinal) &&
                guardedRoundtrip.Contains(property, StringComparison.Ordinal),
                $"{property} überstand Neustart/ICS-Roundtrip nicht.");
        }
        var claws = ExchangeCodec.ParseClawsXml("""<?xml version="1.0"?><address-book><person uid="1" first-name="Änne" last-name="Probe"><address-list><address email="a@example.test"/></address-list></person></address-book>""");
        var ldif = ExchangeCodec.ParseLdif("dn: cn=Änne Probe\ncn: Änne Probe\nmail: a@example.test\n\n");
        TestAssert.That(claws.Kontakte.Count == 1 && ldif.Kontakte.Count == 1,
            "Claws-XML oder LDIF erkannte die realistische Minimal-Fixture nicht.");
        try { _ = ExchangeCodec.ParseClawsXml("<!DOCTYPE x><address-book/>");
            throw new InvalidOperationException("Claws-XML akzeptierte eine DTD."); }
        catch (InvalidDataException) { }
        static byte[] Zip(string name, string content)
        {
            using var output = new MemoryStream();
            using (var archive = new ZipArchive(output, ZipArchiveMode.Create, true))
                using (var writer = new StreamWriter(archive.CreateEntry(name, CompressionLevel.Optimal).Open(), new System.Text.UTF8Encoding(false))) writer.Write(content);
            return output.ToArray();
        }
        var takeoutCalendar = ExchangeCodec.ParseImport(Zip("Takeout/Calendar/Kalender.ics", """
            BEGIN:VCALENDAR
            VERSION:2.0
            BEGIN:VEVENT
            UID:takeout-1
            DTSTART;VALUE=DATE:20260817
            SUMMARY:Takeout
            END:VEVENT
            END:VCALENDAR
            """), "ics", "takeout.zip");
        var takeoutContacts = ExchangeCodec.ParseImport(Zip("Takeout/Contacts/contacts.csv",
            "Given Name,Family Name,E-mail 1 - Value,Phone 1 - Value\r\nMia,Muster,mia@example.org,+49170\r\n"), "vcf", "takeout.zip");
        TestAssert.That(takeoutCalendar.Termine.Count == 1 && takeoutContacts.Kontakte.Count == 1 &&
            takeoutContacts.Kontakte[0]!["vorname"]!.GetValue<string>() == "Mia",
            "Begrenzte Takeout-ZIPs liefern Kalender und Google-CSV-Kontakte plattformgleich.");
        TestAssert.Throws<InvalidDataException>(() => ExchangeCodec.ParseImport(
            Zip("Takeout/Calendar/bombe.ics", new string('0', 100000)), "ics", "bombe.zip"),
            "ZIP mit extremem Kompressionsverhältnis wurde angenommen.");
        return Task.CompletedTask;
    }

    internal static Task OdsAsync()
    {
        using var healthPayload = JsonDocument.Parse("""
            {"tabellen":[
              {"titel":"Vitalwerte","rechtsTitel":"Weitere Vitalwerte",
               "links":["Datum","Gewicht"],"rechts":["Puls","Blutdruck"],
               "zeilen":[["12.08.2026","70,5","62","120/80"]]},
              {"titel":"Verlauf · Blutdruck","rechtsTitel":"Blutdruckdiagramm",
               "links":["Datum","Systolisch","Diastolisch"],"rechts":["Puls","Blutdruck"],
               "diagramm":{"titel":"Blutdruck","serien":[
                 {"name":"Systolisch","farbe":"#a7444e","punkte":[["2026-08-12",124]]},
                 {"name":"Diastolisch","farbe":"#456f91","punkte":[["2026-08-12",79]]}]},
               "zeilen":[["12.08.2026","124","79","",""]]}
            ]}
            """);
        var sheets = DocumentExportService.ReadHealthSheets(healthPayload.RootElement);
        var bytes = DocumentExportService.CreateSpreadsheet(new[]
        {
            new DocumentSheet("Probe", new[] { "Name", "Wert" }, new[] { (IReadOnlyList<string>)new[] { "Änne", "42" } })
        }.Concat(sheets).ToArray());
        using var stream = new MemoryStream(bytes);
        using var zip = new ZipArchive(stream, ZipArchiveMode.Read);
        TestAssert.That(zip.Entries[0].FullName == "mimetype" && zip.Entries[0].CompressedLength == zip.Entries[0].Length,
            "ODS-Mimetype ist nicht erster oder unkomprimierter Paketeintrag.");
        using var content = zip.GetEntry("content.xml")!.Open();
        var xml = XDocument.Load(content);
        XNamespace table = "urn:oasis:names:tc:opendocument:xmlns:table:1.0";
        XNamespace draw = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0";
        XNamespace svg = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0";
        TestAssert.That(xml.Descendants().Any(node => node.Name.LocalName == "table" && (string?)node.Attributes().FirstOrDefault(attribute => attribute.Name.LocalName == "name") == "Probe") &&
            xml.Descendants().Any(node => node.Value == "Änne"), "ODS content.xml verlor Tabelle oder Unicode-Zelle.");
        var vitalTable = xml.Descendants(table + "table").Single(node => (string?)node.Attribute(table + "name") == "Vitalwerte");
        var vitalRows = vitalTable.Elements(table + "table-row").ToArray();
        var completeHeader = vitalRows[2].Elements(table + "table-cell").Select(cell => cell.Value).ToArray();
        TestAssert.That(vitalRows.Length == 4 && completeHeader.SequenceEqual(new[] { "Datum", "Gewicht", "", "Puls", "Blutdruck" }),
            "Die rechte Vitalwerttabelle besitzt nicht dieselbe vollständige Spaltenkopfzeile wie die linke Tabelle.");

        var chartTable = xml.Descendants(table + "table").Single(node => (string?)node.Attribute(table + "name") == "Verlauf · Blutdruck");
        var chartRows = chartTable.Elements(table + "table-row").ToArray();
        var chartArea = chartRows[2].Elements(table + "table-cell").Single(cell => cell.Attribute(table + "number-rows-spanned") is not null);
        var frame = chartArea.Descendants(draw + "frame").Single();
        TestAssert.That((string?)chartArea.Attribute(table + "number-columns-spanned") == "2" &&
                        (string?)chartArea.Attribute(table + "number-rows-spanned") == "20" &&
                        (string?)chartArea.Attribute(table + "style-name") == "ceChartArea" &&
                        chartRows.Skip(3).All(row => row.Elements(table + "covered-table-cell").Count() == 2),
            "Das Diagramm ersetzt nicht den gesamten rechten Tabellenbereich semantisch durch eine verbundene Fläche.");
        TestAssert.That((string?)frame.Attribute(svg + "width") == "12.5cm" && (string?)frame.Attribute(svg + "height") == "11.4cm" &&
                        chartArea.Descendants(table + "table-cell").Count() == 0,
            "Das SVG liegt nicht vollständig innerhalb der 13,2 x 12 cm großen Diagrammfläche oder überdeckt Tabellenzellen.");
        return Task.CompletedTask;
    }

    internal static Task OdtAsync()
    {
        var previousLanguage = NativeLocalization.Language;
        try
        {
            using var namedContact = JsonDocument.Parse("""{"anzeigename":"Van Dame","strasse":"Main 1"}""");
            foreach (var language in new[] { "en", "de", "fr" })
            {
                NativeLocalization.SetLanguage(language);
                using var letter = new ZipArchive(new MemoryStream(DocumentExportService.CreateLetter(namedContact.RootElement, "Sender", "din5008")));
                using var reader = new StreamReader(letter.GetEntry("content.xml")!.Open());
                var xml = XDocument.Parse(reader.ReadToEnd());
                TestAssert.That(new[] { "Dear Sir or Madam,", "Yours sincerely," }.All(key =>
                    xml.Descendants().Any(node => node.Value == NativeLocalization.Gettext(key))) && xml.Root!.Value.Contains("Van Dame", StringComparison.Ordinal),
                    "Letter output did not use the active gettext language and supplied display name.");
            }
        }
        finally { NativeLocalization.SetLanguage(previousLanguage); }
        using var contact = JsonDocument.Parse("""{"vorname":"Mia","nachname":"Muster","strasse":"Gartenweg 1","plz":"10115","ort":"Berlin"}""");
        var bytes = DocumentExportService.CreateLetter(contact.RootElement, "Max Beispiel\nHauptstraße 2", "din5008");
        using var stream = new MemoryStream(bytes);
        using var zip = new ZipArchive(stream, ZipArchiveMode.Read);
        var mimeEntry = zip.Entries[0];
        using var mimeReader = new StreamReader(mimeEntry.Open());
        var mime = mimeReader.ReadToEnd();
        using var contentReader = new StreamReader(zip.GetEntry("content.xml")!.Open());
        var content = contentReader.ReadToEnd();
        XDocument styles;
        using (var stylesStream = zip.GetEntry("styles.xml")!.Open()) styles = XDocument.Load(stylesStream);
        using var manifestReader = new StreamReader(zip.GetEntry("META-INF/manifest.xml")!.Open());
        var manifest = manifestReader.ReadToEnd();
        XNamespace style = "urn:oasis:names:tc:opendocument:xmlns:style:1.0";
        XNamespace fo = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0";
        var senderStyle = styles.Descendants(style + "style").Single(node => (string?)node.Attribute(style + "name") == "Rueckadresse");
        var page = styles.Descendants(style + "page-layout-properties").Single();
        TestAssert.That(mimeEntry.FullName == "mimetype" && mimeEntry.CompressedLength == mimeEntry.Length &&
                        mime == "application/vnd.oasis.opendocument.text" && zip.GetEntry("styles.xml") is not null,
            "Der Brief ist kein korrekt gepacktes ODT mit erstem, unkomprimiertem Text-Mimetype-Eintrag.");
        TestAssert.That(content.Contains("Mia Muster") && content.Contains("Gartenweg 1") && content.Contains("Rueckadresse") &&
                        manifest.Contains("application/vnd.oasis.opendocument.text") &&
                         (string?)senderStyle.Element(style + "paragraph-properties")?.Attribute(fo + "line-height") == "0.5cm" &&
                        (string?)page.Attribute(fo + "page-width") == "21cm" && (string?)page.Attribute(fo + "margin-left") == "2.5cm" &&
                        DocumentExportService.LetterFileName("Brief.fodt").EndsWith(".odt", StringComparison.OrdinalIgnoreCase),
            "ODT-Inhalt, DIN-5008-Anschrift, Manifest-MIME oder erzwungene .odt-Endung fehlen.");
        XNamespace draw = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0";
        XNamespace svg = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0";
        foreach (var layout in new[] { "", "din5008", "din5008-b", "din5008-a" })
        {
            using var letter = new ZipArchive(new MemoryStream(layout.Length == 0
                ? DocumentExportService.CreateLetter(contact.RootElement, "Sender")
                : DocumentExportService.CreateLetter(contact.RootElement, "Sender", layout)));
            using var reader = letter.GetEntry("content.xml")!.Open();
            var xml = XDocument.Load(reader);
            var address = xml.Descendants(draw + "frame").Single(node => (string?)node.Attribute(draw + "name") == "Anschriftfeld");
            TestAssert.That((string?)address.Attribute(svg + "x") == "2cm" &&
                (string?)address.Attribute(svg + "y") == (layout == "din5008-a" ? "2.7cm" : "4.5cm") &&
                (string?)address.Attribute(svg + "width") == "8.5cm" && (string?)address.Attribute(svg + "height") == "4.5cm" &&
                xml.Descendants(draw + "frame").Any(node => (string?)node.Attribute(draw + "name") == "Absenderblock") == (layout != "din5008-a"),
                "Default B, explicit A or left address geometry is incorrect.");
        }
        TestAssert.Throws<ArgumentException>(() => DocumentExportService.CreateLetter(contact.RootElement, new string('W', 1000)),
            "Overlong return addresses must not silently wrap or be clipped.");
        return Task.CompletedTask;
    }

    private static void NativeExchangeRegressions()
    {
        foreach (var name in new[] { "N:Van Dame;;;;\r\nFN:Van Dame", "N:;Anna Maria;;;\r\nFN:Anna Maria",
            "FN:Van Dame", "N:Smith,Jones;Anna,Maria;Grace;Dr.;Jr.\r\nFN:Different display",
            "N:Smith\\,Jones;Anna\\,Maria;;;\r\nFN:Literal commas" })
        {
            var text = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:name-test\r\n" + name +
                "\r\nBDAY;X-APPLE-OMIT-YEAR=1604:1604-02-29\r\nANNIVERSARY:--0607\r\n" +
                "ADR;TYPE=HOME:Box 4;Suite 2;Main 1;Berlin;Berlin;10115;Germany\r\nTITLE:Engineer\r\nEND:VCARD\r\n";
            var contact = ExchangeCodec.ParseVCard(text).Kontakte.Single()!;
            for (var round = 0; round < 2; round++)
            {
                using var saved = JsonDocument.Parse(new JsonArray(contact.DeepClone()).ToJsonString());
                var exported = ExchangeCodec.WriteVCard(saved.RootElement);
                TestAssert.That(exported.Count == 1 && exported.Skipped == 0 && exported.Text.Contains(name, StringComparison.Ordinal) &&
                    exported.Text.Contains(";Berlin;Berlin;10115;Germany", StringComparison.Ordinal) &&
                    exported.Text.Contains("VERSION:4.0\r\n", StringComparison.Ordinal) &&
                    exported.Text.Contains("ANNIVERSARY:--0607\r\n", StringComparison.Ordinal), "Name structure, display name, region or anniversary changed after save/export.");
                contact = ExchangeCodec.ParseVCard(exported.Text).Kontakte.Single()!;
                TestAssert.That(contact["geburtstag"]!.ToString() == "--02-29" && contact["jubilaeum"]!.ToString() == "--06-07",
                    "Explicitly yearless contact dates did not survive repeated exchange.");
            }
            if (name.StartsWith("FN:", StringComparison.Ordinal)) TestAssert.That(contact["vorname"]!.ToString() == "" && contact["nachname"]!.ToString() == "" &&
                contact["anzeigename"]!.ToString() == "Van Dame", "A display-only contact acquired invented structured names.");
        }
        foreach (var year in new[] { "1604", "2000" })
            TestAssert.That(ExchangeCodec.ParseVCard($"BEGIN:VCARD\nVERSION:3.0\nFN:Real\nBDAY:{year}-02-29\nEND:VCARD\n").Kontakte[0]!["geburtstag"]!.ToString() == year + "-02-29",
                "A genuine year was globally reinterpreted as a placeholder.");
        using (var contact = JsonDocument.Parse("""[{"uid":"thunderbird:profile:book:first-only","vorname":"Anna Maria","nachname":"","geburtstag":"--02-29","jubilaeum":"--06-07"}]"""))
        {
            var ldif = ExchangeCodec.WriteLdif(contact.RootElement).Text;
            var restored = ExchangeCodec.ParseLdif(ldif).Kontakte.Single()!;
            TestAssert.That(!ldif.Split('\n').Any(line => line.StartsWith("sn:", StringComparison.Ordinal)) && restored["nachname"]!.ToString() == "" &&
                restored["uid"]!.ToString() == "thunderbird:profile:book:first-only" && restored["vorname"]!.ToString() == "Anna Maria" && restored["geburtstag"]!.ToString() == "--02-29" && restored["jubilaeum"]!.ToString() == "--06-07",
                "LDIF fabricated a surname or lost partial contact dates.");
        }
        foreach (var (start, duration, endDate, endTime) in new[] { (";VALUE=DATE:20260907", "P3D", "2026-09-09", ""),
            (":20260907T233000", "PT2H", "2026-09-08", "01:30") })
        {
            var input = $"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:duration\nSUMMARY:Duration\nDTSTART{start}\nDURATION:{duration}\nRRULE:FREQ=WEEKLY\nEND:VEVENT\nEND:VCALENDAR\n";
            for (var round = 0; round < 2; round++)
            {
                var parsed = ExchangeCodec.ParseIcs(input);
                TestAssert.That(parsed.Termine.Single()!["endDatum"]!.ToString() == endDate && parsed.Termine[0]!["endZeit"]!.ToString() == endTime,
                    "DURATION did not project its complete day/time span.");
                using var saved = JsonDocument.Parse(parsed.Termine.ToJsonString());
                input = ExchangeCodec.WriteIcs("ics-termine", saved.RootElement).Text;
                TestAssert.That(!(input.Contains("DURATION:", StringComparison.Ordinal) && input.Contains("DTEND", StringComparison.Ordinal)), "VEVENT contains mutually exclusive end representations.");
            }
        }
        const string task = "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:independent-start\nSUMMARY:Task\nDTSTART:20260901T090000\nDUE:20260907T170000\nEND:VTODO\nEND:VCALENDAR\n";
        var parsedTask = ExchangeCodec.ParseIcs(task).Aufgaben;
        TestAssert.That(parsedTask[0]!["startDatum"]!.ToString() == "2026-09-01", "Task start date was not preserved.");
        using var savedTask = JsonDocument.Parse(parsedTask.ToJsonString());
        var taskExport = ExchangeCodec.WriteIcs("ics-aufgaben", savedTask.RootElement).Text;
        TestAssert.That(taskExport.Contains("DTSTART:20260901T090000", StringComparison.Ordinal) && taskExport.Contains("DUE:20260907T170000", StringComparison.Ordinal),
            "Task export replaced its independent start with its due date.");
        parsedTask[0]!["faellig"] = "2026-09-08";
        using var changedTask = JsonDocument.Parse(parsedTask.ToJsonString());
        var changedExport = ExchangeCodec.WriteIcs("ics-aufgaben", changedTask.RootElement).Text;
        var changedAgain = ExchangeCodec.ParseIcs(changedExport).Aufgaben.Single()!;
        TestAssert.That(changedAgain["faellig"]!.ToString() == "2026-09-08" && changedAgain["faelligZeit"]!.ToString() == "17:00",
            "Old raw task dates overrode an explicit edit.");
        var dueOnly = ExchangeCodec.ParseIcs("BEGIN:VTODO\nUID:due-only\nSUMMARY:Task\nDUE:20260907T170000\nEND:VTODO\n").Aufgaben;
        dueOnly[0]!["faellig"] = "2026-09-09";
        using var dueOnlySaved = JsonDocument.Parse(dueOnly.ToJsonString());
        TestAssert.That(ExchangeCodec.ParseIcs(ExchangeCodec.WriteIcs("ics-aufgaben", dueOnlySaved.RootElement).Text).Aufgaben[0]!["faellig"]!.ToString() == "2026-09-09",
            "A task without DTSTART retained an obsolete raw DUE after editing.");
        using (var legacy = JsonDocument.Parse("""[{"uid":"legacy-start-time","titel":"Task","faellig":"2026-09-07","startZeit":"09:00"}]"""))
        {
            var legacyText = ExchangeCodec.WriteIcs("ics-aufgaben", legacy.RootElement).Text;
            var restored = ExchangeCodec.ParseIcs(legacyText).Aufgaben.Single()!;
            TestAssert.That(!legacyText.Contains("DTSTART", StringComparison.Ordinal) && restored["startDatum"]!.ToString() == "" && restored["startZeit"]!.ToString() == "09:00",
                "A persisted start time without a start date was lost or given a fabricated date.");
        }
        var alarmDuration = ExchangeCodec.ParseIcs("BEGIN:VEVENT\nUID:alarm-duration\nDTSTART:20260907T090000\nDTEND:20260907T100000\nBEGIN:VALARM\nACTION:DISPLAY\nTRIGGER:-PT15M\nREPEAT:2\nDURATION:PT5M\nEND:VALARM\nEND:VEVENT\n");
        using var alarmSaved = JsonDocument.Parse(alarmDuration.Termine.ToJsonString());
        TestAssert.That(ExchangeCodec.WriteIcs("ics-termine", alarmSaved.RootElement).Text.Contains("DTEND:20260907T100000", StringComparison.Ordinal),
            "VALARM DURATION removed the parent event's end.");
        var previousCulture = System.Globalization.CultureInfo.CurrentCulture;
        try
        {
            System.Globalization.CultureInfo.CurrentCulture = System.Globalization.CultureInfo.GetCultureInfo("ar-SA");
            var parsed = ExchangeCodec.ParseIcs(task);
            using var saved = JsonDocument.Parse(parsed.Aufgaben.ToJsonString());
            TestAssert.That(parsed.Aufgaben[0]!["startDatum"]!.ToString() == "2026-09-01" &&
                ExchangeCodec.WriteIcs("ics-aufgaben", saved.RootElement).Text.Contains("DTSTART:20260901T090000", StringComparison.Ordinal) &&
                System.Globalization.CultureInfo.CurrentCulture.Name == "ar-SA", "Wire dates depended on the display calendar or changed the caller's culture.");
        }
        finally { System.Globalization.CultureInfo.CurrentCulture = previousCulture; }
    }

    internal static Task RemindersAsync()
    {
        var data = """{"einstellungen":{"erinnerung":{"vorlauf":0,"verpasste":true}},"termine":[{"id":"m","datum":"2026-01-31","zeit":"09:00","titel":"Monat","standardErinnerung":true,"wiederholung":{"art":"monthly","bis":"2026-04-30"}}]}""";
        var due = ReminderScheduler.DueAppointments(data, new DateTime(2026, 2, 28, 9, 0, 0));
        TestAssert.That(due.Count == 1 && due[0].Key.Contains("202602280900", StringComparison.Ordinal),
            "Die Monatsserie am Monatsende wurde nicht kalenderrichtig fällig.");
        var ordinalData = """{"einstellungen":{"erinnerung":{"vorlauf":0,"verpasste":true}},"termine":[{"id":"o","datum":"2024-01-26","zeit":"09:15","titel":"Forumserie","standardErinnerung":true,"wiederholung":{"art":"monthly","bis":"","ordinal":-1,"wochentag":"FR","rruleForm":"bysetpos"}}]}""";
        var ordinalDue = ReminderScheduler.DueAppointments(ordinalData, new DateTime(2024, 2, 23, 9, 15, 0));
        TestAssert.That(ordinalDue.Count == 1 && ordinalDue[0].Key.Contains("202402230915", StringComparison.Ordinal),
            "Die zeitgebundene letzte-Freitag-Serie wurde im Hintergrund nicht fällig.");
        using var anniversaryData = JsonDocument.Parse("""{"jahrestage":[{"id":"partial","name":"Jahrlos","datum":"--02-29"},{"id":"full","name":"Echt","datum":"2000-02-29"}]}""");
        using var anniversarySettings = JsonDocument.Parse("""{"jahrestage":{"an":true,"tage":0,"amTag":true,"stunde":8}}""");
        var anniversaryDue = ReminderScheduler.DueAnniversaries(anniversaryData.RootElement,
            anniversarySettings.RootElement, new DateTime(2026, 2, 28, 8, 0, 0));
        TestAssert.That(anniversaryDue.Count == 2 && anniversaryDue.All(item => item.Start == new DateTime(2026, 2, 28, 8, 0, 0)),
            "Jahrlose oder volle Schaltjahr-Jahrestage wurden im Nicht-Schaltjahr nicht auf den 28. Februar gelegt.");
        return Task.CompletedTask;
    }

    internal static Task TrayAsync()
    {
        using var document = JsonDocument.Parse("""{"aktiv":true,"minimierenInTray":false,"schliessenInTray":true,"startMinimiert":true,"autostart":true,"zaehler":true,"oeffnen":"maximiert"}""");
        var settings = TraySettings.FromJson(document.RootElement);
        TestAssert.That(settings is { Aktiv: true, MinimierenInTray: false, SchliessenInTray: true, StartMinimiert: true, Autostart: true, Zaehler: true, Oeffnen: "maximized" } &&
            TraySettingsService.AutostartCommand("C:\\A B\\Magnolie.exe") == "\"C:\\A B\\Magnolie.exe\" --tray-start",
            "Tray-Normalisierung oder sicherer Autostart-Befehl ist fehlerhaft.");
        TestAssert.That(TraySettingsService.BackgroundAutostartCommand("C:\\A B\\Magnolie.exe") ==
                        "\"C:\\A B\\Magnolie.exe\" --tray-start --reminder-start",
            "Der Reminder-Autostart startet nicht im echten Hintergrundmodus.");
        return Task.CompletedTask;
    }

    internal static Task TreeAsync()
    {
        var alicePrivate = Convert.FromHexString("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a");
        var bobPublic = Convert.FromHexString("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f");
        TestAssert.That(Convert.ToHexString(MagnolienbaumCrypto.X25519(alicePrivate, bobPublic)).ToLowerInvariant() ==
            "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742",
            "Magnolienbaum X25519 wich vom RFC/Python-Golden ab.");
        return Task.CompletedTask;
    }

    internal static Task TreeContactsAsync()
    {
        var contractPath = Path.Combine(AppContext.BaseDirectory, "resources", "kontakt-sync-contract.json");
        TestAssert.That(File.Exists(contractPath), "Gemeinsamer Kontaktvertrag fehlt im Testlauf.");
        var vectors = JsonNode.Parse(File.ReadAllText(contractPath))!.AsObject();
        var limits = vectors["limits"]!.AsObject();
        var contractBase = vectors["base"]!.AsObject();
        JsonObject WithContact(string name, JsonNode? value)
        {
            var result = contractBase.DeepClone().AsObject();
            result["kontakt"]![name] = value;
            return result;
        }
        JsonObject WithRoot(string name, JsonNode? value)
        {
            var result = contractBase.DeepClone().AsObject();
            result[name] = value;
            return result;
        }
        JsonObject WithVector(JsonObject vector)
        {
            var result = contractBase.DeepClone().AsObject();
            var path = vector["path"]!.AsArray().Select(item => item!.GetValue<string>()).ToArray();
            if (path.Length == 1) result[path[0]] = vector["value"]!.DeepClone();
            else if (path.Length == 2 && path[0] == "kontakt")
                result["kontakt"]![path[1]] = vector["value"]!.DeepClone();
            else throw new InvalidDataException("Unbekannter Kontaktvertragspfad.");
            return result;
        }
        BaumContactSyncContract.Validate(contractBase);
        foreach (var birthday in vectors["accepted_birthdays"]!.AsArray())
            BaumContactSyncContract.Validate(WithContact("geburtstag", birthday!.DeepClone()));
        foreach (var birthday in vectors["rejected_birthdays"]!.AsArray())
            TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(
                WithContact("geburtstag", birthday!.DeepClone())), "Ungültiges Golden-Geburtsdatum wurde angenommen.");
        BaumContactSyncContract.Validate(WithContact("foto", vectors["opaque_photo"]!.DeepClone()));
        foreach (var vector in vectors["accepted_vectors"]!.AsArray().Select(item => item!.AsObject()))
            BaumContactSyncContract.Validate(WithVector(vector));
        foreach (var vector in vectors["rejected_vectors"]!.AsArray().Select(item => item!.AsObject()))
            TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(WithVector(vector)),
                $"Ungültiger gemeinsamer Vektor wurde angenommen: {vector["name"]!.GetValue<string>()}");

        var maxRoot = limits["root_id_code_points"]!.GetValue<int>();
        var maxText = limits["text_code_points"]!.GetValue<int>();
        var maxNote = limits["note_code_points"]!.GetValue<int>();
        var maxList = limits["list_items"]!.GetValue<int>();
        var maxPhoto = limits["photo_text_code_points"]!.GetValue<int>();
        var emojiBoundary = string.Concat(Enumerable.Repeat("\U0001F600", maxText));
        BaumContactSyncContract.Validate(WithRoot("freigabeId",
            string.Concat(Enumerable.Repeat("\U0001F600", maxRoot))));
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(
            WithRoot("freigabeId", string.Concat(Enumerable.Repeat("\U0001F600", maxRoot)) + "a")),
            "Root-ID wurde nicht nach Unicode-Codepoints begrenzt.");
        BaumContactSyncContract.Validate(WithContact("vorname", emojiBoundary));
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(
            WithContact("vorname", emojiBoundary + "a")), "UTF-16-Einheiten statt Unicode-Codepoints begrenzen Kontakttext.");
        BaumContactSyncContract.Validate(WithContact("notiz", new string('n', maxNote)));
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(
            WithContact("notiz", new string('n', maxNote + 1))), "Überlange Kontaktnotiz wurde angenommen.");

        JsonObject EmptyValue() => new() { ["art"] = "", ["wert"] = "" };
        BaumContactSyncContract.Validate(WithContact("telefone", new JsonArray(
            Enumerable.Range(0, maxList).Select(_ => (JsonNode?)EmptyValue()).ToArray())));
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(WithContact("telefone", new JsonArray(
            Enumerable.Range(0, maxList + 1).Select(_ => (JsonNode?)EmptyValue()).ToArray()))),
            "Überlange Kontaktliste wurde angenommen.");
        JsonObject BoundaryValue(string type, string value) => new() { ["art"] = type, ["wert"] = value };
        BaumContactSyncContract.Validate(WithContact("telefone", new JsonArray(BoundaryValue(
            emojiBoundary, new string('w', maxText)))));
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(WithContact("telefone",
            new JsonArray(BoundaryValue(emojiBoundary + "a", "w")))), "Überlange Kontaktart wurde angenommen.");
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(WithContact("telefone",
            new JsonArray(BoundaryValue("", new string('w', maxText + 1))))), "Überlanger Kontaktwert wurde angenommen.");
        JsonObject EmptyAddress() => new()
        {
            ["art"] = "", ["strasse"] = "", ["plz"] = "", ["ort"] = "", ["region"] = "", ["land"] = ""
        };
        BaumContactSyncContract.Validate(WithContact("anschriften", new JsonArray(
            Enumerable.Range(0, maxList).Select(_ => (JsonNode?)EmptyAddress()).ToArray())));

        const string photoPrefix = "data:image/png;base64,";
        var encodedPhotoLength = (maxPhoto - photoPrefix.Length) / 4 * 4;
        BaumContactSyncContract.Validate(WithContact("foto", photoPrefix + new string('A', encodedPhotoLength)));
        TestAssert.Throws<InvalidDataException>(() => BaumContactSyncContract.Validate(
            WithContact("foto", photoPrefix + new string('A', encodedPhotoLength + 4))), "Überlanger Fototext wurde angenommen.");

        var valid = JsonNode.Parse("""{"art":"kontakt_sync","fassung":1,"freigabeId":"alice:42","version":1,"quelle":"alice","geaendert":1770000000000,"kontakt":{"vorname":"Mia","nachname":"Muster","firma":"","notiz":"Zeile 1\nZeile 2","geburtstag":"2000-02-29","foto":"data:image/png;base64,iVBORw0KGgo=","telefone":[{"art":"mobil","wert":"+491701234567"}],"emailEintraege":[{"art":"arbeit","wert":"mia@example.test"}],"anschriften":[{"art":"privat","strasse":"Gartenweg 1","plz":"10115","ort":"Berlin","region":"Berlin","land":"DE"}]}}""")!;
        BaumContactSyncContract.Validate(valid);
        var yearless = valid.DeepClone(); yearless["kontakt"]!["geburtstag"] = "--02-29";
        BaumContactSyncContract.Validate(yearless);
        foreach (var invalid in new[]
        {
            """{"art":"kontakt_sync","fassung":2,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","foto":"data:image/gif;base64,R0lGODlh","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","foto":"data:image/png;base64,AA ==","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","foto":"data:text/plain;base64,QQ==","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":0,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"geloescht":true,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"--02-30","telefone":[],"emailEintraege":[],"anschriften":[]}}"""
        })
        {
            try { BaumContactSyncContract.Validate(JsonNode.Parse(invalid)!);
                throw new InvalidOperationException("Ein ungültiger kontakt_sync-Vertrag wurde angenommen."); }
            catch (InvalidDataException) { }
        }
        var oversized = valid.DeepClone();
        oversized["kontakt"]!["foto"] = "data:image/jpeg;base64," + new string('A', 2_800_000);
        try { BaumContactSyncContract.Validate(oversized);
            throw new InvalidOperationException("Ein überlanges Kontaktfoto wurde angenommen."); }
        catch (InvalidDataException) { }
        TestAssert.That(valid["kontakt"]!["foto"]!.GetValue<string>() == "data:image/png;base64,iVBORw0KGgo=" &&
                        valid["kontakt"]!["id"] is null,
            "Der interoperable Kontaktvertrag verliert das Foto oder enthält eine technische ID.");
        var deletion = JsonNode.Parse("""{"art":"kontakt_loeschen","fassung":1,"freigabeId":"alice:42","version":2,"quelle":"alice","geaendert":1770000000001}""")!;
        BaumContactSyncContract.ValidateDelete(deletion);
        deletion["geaendert"] = 0L;
        BaumContactSyncContract.ValidateDelete(deletion);
        foreach (var invalidDelete in new[]
        {
            """{"art":"kontakt_loeschen","fassung":1,"freigabeId":"alice:42","version":0,"quelle":"alice","geaendert":1}""",
            """{"art":"kontakt_loeschen","fassung":1,"freigabeId":"alice:42","version":2,"quelle":"alice","geaendert":1,"kontakt":{}}""",
            """{"art":"kontakt_loeschen","fassung":1,"freigabeId":"","version":2,"quelle":"alice","geaendert":1}""",
            """{"art":"kontakt_loeschen","fassung":1,"freigabeId":"alice:42","version":2,"quelle":"alice","geaendert":1,"alle":true}"""
        })
        {
            try { BaumContactSyncContract.ValidateDelete(JsonNode.Parse(invalidDelete)!);
                throw new InvalidOperationException("Ein ungültiger kontakt_loeschen-Vertrag wurde angenommen."); }
            catch (InvalidDataException) { }
        }
        return Task.CompletedTask;
    }
}
