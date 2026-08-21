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
        var data = JsonNode.Parse("""{"version":6,"termine":[],"kontakte":[{"foto":"data:image/jpeg;base64,/9j/2Q=="}],"notizen":[{"anhaenge":[{"daten":"data:application/pdf;base64,JVBERi0="}]}],"papierkorb":[],"einstellungen":{}}""")!.AsObject();
        var text = GesamtarchivService.Create(data, "linux", "1.31.7", "Rosenholz1896");
        var read = GesamtarchivService.Read(text, "Rosenholz1896");
        TestAssert.That(read.Fotos == 1 && read.Anhaenge == 1 && JsonNode.DeepEquals(read.Daten, data),
            "Das geschützte Linux/Windows-Gesamtarchiv verlor Foto oder Anhang.");
        var golden = GesamtarchivService.Read(File.ReadAllText(Path.Combine("tests", "fixtures", "linux-ordinal.magnolie")));
        var goldenAppointments = golden.Daten["termine"]!.AsArray();
        TestAssert.That(golden.Plattform == "linux" && goldenAppointments[0]!["wiederholung"]!["art"]!.GetValue<string>() == "monthly" &&
            goldenAppointments[0]!["zeit"]!.GetValue<string>() == "09:15" && goldenAppointments[0]!["endDatum"]!.GetValue<string>() == "2026-01-14" &&
            goldenAppointments[1]!["wiederholung"]!["rruleForm"]!.GetValue<string>() == "bysetpos",
            "Das Linux-Cross-Golden verlor kanonische, zeitgebundene oder zweitägige Serienfelder.");
        var legacy = JsonNode.Parse("""{"termine":[{"wiederholung":{"art":"monthly_weekday","ordinal":2,"wochentag":"TH"}}]}""")!.AsObject();
        var migrated = GesamtarchivService.Create(legacy, "windows", "2.0.0");
        TestAssert.That(!migrated.Contains("monthly_weekday", StringComparison.Ordinal) &&
            GesamtarchivService.Read(migrated).Daten["termine"]![0]!["wiederholung"]!["art"]!.GetValue<string>() == "monthly",
            "Der Windows-Legacy-Alias wurde beim nächsten Speichern nicht kanonisiert.");
        var taskData = JsonNode.Parse("""{"aufgaben":[{"uid":"todo","titel":"Probe","icsRoundtrip":["ATTACH:https://drive.google.com/file/d/1","X-TODO-RAW:opaque"]}]}""")!.AsObject();
        var taskArchive = GesamtarchivService.Read(GesamtarchivService.Create(taskData, "windows", "2.0.0"));
        TestAssert.That(JsonNode.DeepEquals(taskArchive.Daten["aufgaben"]![0]!["icsRoundtrip"], taskData["aufgaben"]![0]!["icsRoundtrip"]),
            "VTODO-ICS-Rohdaten gingen im Gesamtarchiv verloren.");
        return Task.CompletedTask;
    }

    internal static Task ExchangeAsync()
    {
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
        var anniversaryIcs = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:anniversary-rich\r\nDTSTART;VALUE=DATE:19900812\r\nRRULE:FREQ=YEARLY\r\nCATEGORIES:Geburtstag\r\nSUMMARY:Mia\r\nLOCATION:Garten\r\nORGANIZER:mailto:host@example.org\r\nATTENDEE:mailto:mia@example.org\r\nATTACH:https://www.dropbox.com/s/a\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-P1D\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
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
                guarded.Termine[0]!["wiederholung"]!["art"]!.GetValue<string>() == "none",
                $"{property} wurde fälschlich als einfache Serie behandelt.");
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
        var senderStyle = styles.Descendants(style + "style").Single(node => (string?)node.Attribute(style + "name") == "SenderDin");
        var page = styles.Descendants(style + "page-layout-properties").Single();
        TestAssert.That(mimeEntry.FullName == "mimetype" && mimeEntry.CompressedLength == mimeEntry.Length &&
                        mime == "application/vnd.oasis.opendocument.text" && zip.GetEntry("styles.xml") is not null,
            "Der Brief ist kein korrekt gepacktes ODT mit erstem, unkomprimiertem Text-Mimetype-Eintrag.");
        TestAssert.That(content.Contains("Mia Muster") && content.Contains("Gartenweg 1") && content.Contains("SenderDin") &&
                        manifest.Contains("application/vnd.oasis.opendocument.text") &&
                        (string?)senderStyle.Element(style + "paragraph-properties")?.Attribute(fo + "margin-top") == "2.5cm" &&
                        (string?)page.Attribute(fo + "page-width") == "21cm" && (string?)page.Attribute(fo + "margin-left") == "2.5cm" &&
                        DocumentExportService.LetterFileName("Brief.fodt").EndsWith(".odt", StringComparison.OrdinalIgnoreCase),
            "ODT-Inhalt, DIN-5008-Anschrift, Manifest-MIME oder erzwungene .odt-Endung fehlen.");
        return Task.CompletedTask;
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
        var valid = JsonNode.Parse("""{"art":"kontakt_sync","fassung":1,"freigabeId":"alice:42","version":1,"quelle":"alice","geaendert":1770000000000,"kontakt":{"vorname":"Mia","nachname":"Muster","firma":"","notiz":"Zeile 1\nZeile 2","geburtstag":"2000-02-29","foto":"data:image/png;base64,iVBORw0KGgo=","telefone":[{"art":"mobil","wert":"+491701234567"}],"emailEintraege":[{"art":"arbeit","wert":"mia@example.test"}],"anschriften":[{"art":"privat","strasse":"Gartenweg 1","plz":"10115","ort":"Berlin","region":"Berlin","land":"DE"}]}}""")!;
        BaumContactSyncContract.Validate(valid);
        foreach (var invalid in new[]
        {
            """{"art":"kontakt_sync","fassung":2,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","foto":"data:image/gif;base64,R0lGODlh","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","foto":"data:image/png;base64,AA ==","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","foto":"data:text/plain;base64,QQ==","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":0,"quelle":"a","geaendert":1,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","telefone":[],"emailEintraege":[],"anschriften":[]}}""",
            """{"art":"kontakt_sync","fassung":1,"freigabeId":"a","version":1,"quelle":"a","geaendert":1,"geloescht":true,"kontakt":{"vorname":"A","nachname":"","firma":"","notiz":"","geburtstag":"","telefone":[],"emailEintraege":[],"anschriften":[]}}"""
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
