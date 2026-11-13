using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6ExtensionTests
{
    private static JsonNode Contract() => JsonNode.Parse(File.ReadAllText(Path.Combine(
        TestSource.Root("contracts/or6-native-extensions.json"), "contracts/or6-native-extensions.json")))!;
    private static byte[] Fixture(string name)
    {
        var item = Contract()["files"]![name]!;
        using var input = new MemoryStream(Convert.FromBase64String(item["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var bytes = output.ToArray();
        TestAssert.That(bytes.Length == item["bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == item["sha256"]!.GetValue<string>(), "Independent OR6 extension fixture changed.");
        return bytes;
    }
    internal static Task RunAsync()
    {
        var expected = Contract()["expected"]!;
        var raw = Fixture("weekly-monday-222.or6"); var result = Or6Codec.Read(raw);
        var series = result.Termine.OfType<JsonObject>().Where(item => item["titel"]!.GetValue<string>() == expected["weekly"]!["title"]!.GetValue<string>()).ToArray();
        TestAssert.That(series.Length == 1 && result.Termine.Count == 2 && result.Wiederholend == 0 && result.Uebersprungen == 0,
            "Native linked series was skipped or flattened.");
        var item = series.Single();
        TestAssert.That(item["wiederholung"]!["art"]!.GetValue<string>() == "weekly" &&
            item["wiederholung"]!["intervall"]!.GetValue<int>() == 2 && item["wiederholung"]!["bis"]!.GetValue<string>() == "2026-12-14" &&
            item["zeit"]!.GetValue<string>() == "09:15" && item["endZeit"]!.GetValue<string>() == "10:00", "Native weekly rule/times differ.");
        var contacts = Or6Codec.Read(Fixture("contact-context-222.or6")).Kontakte;
        var contact = contacts.OfType<JsonObject>().Single(entry => entry["vorname"]!.GetValue<string>() == "Grace");
        foreach (var field in new[] { "vorname", "nachname", "firma", "email" })
            TestAssert.That(JsonNode.DeepEquals(contact[field], expected["contact"]![field]), "Original contact field changed: " + field);
        foreach (var phone in contact["telefone"]!.AsArray().OfType<JsonObject>())
            TestAssert.That(JsonNode.DeepEquals(phone["typen"], expected["contact"]!["phoneTypes"]![phone["wert"]!.GetValue<string>()]), "Sparse native phone slot lost context.");
        TestAssert.That(contact["telefone"]!.AsArray().Count == 3 && contact["vcardRoundtrip"]![0]!.GetValue<string>() == "CATEGORIES:OR6-222 Alpha",
            "Original contact category/phones missing.");
        var grouped = Or6Codec.Read(Fixture("group-beta-222.or6"));
        TestAssert.That(grouped.Kontakte.Count == 2 && grouped.Uebersprungen == 0, "Distribution groups became ordinary contacts or were lost.");
        foreach (var member in grouped.Kontakte.OfType<JsonObject>())
        {
            var names = expected["groups"]![member["vorname"]!.GetValue<string>()]!.AsArray().Select(value => value!.GetValue<string>());
            TestAssert.That(member["vcardRoundtrip"]![0]!.GetValue<string>() == "CATEGORIES:" + string.Join(',', names), "Original group membership differs.");
        }
        var deleted = Or6Codec.Read(Fixture("weekly-deleted-222.or6"));
        var retained = deleted.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == expected["weekly"]!["title"]!.GetValue<string>());
        TestAssert.That(deleted.Wiederholend == 0 && deleted.Uebersprungen == 0 && retained["icsKomplex"]!.GetValue<bool>() &&
            retained["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == "EXDATE:20261116T091500"), "Deleted original occurrence was resurrected or series lost.");
        var sections = Or6Codec.Read(Fixture("sections-corrected-222.or6")); var selected = expected["sections"]!;
        var annual = sections.Jahrestage.OfType<JsonObject>().Single();
        TestAssert.That(annual["name"]!.GetValue<string>() == selected["anniversary"]!["title"]!.GetValue<string>() &&
            annual["datum"]!.GetValue<string>() == selected["anniversary"]!["date"]!.GetValue<string>() &&
            annual["typ"]!.GetValue<string>() == "anniversary", "Original annual checkbox/date not retained.");
        var planner = sections.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == selected["planner"]!["title"]!.GetValue<string>());
        TestAssert.That(planner["datum"]!.GetValue<string>() == "2026-11-06" && planner["endDatum"]!.GetValue<string>() == "2026-11-08" &&
            planner["zeit"]!.GetValue<string>() == "" && planner["endZeit"]!.GetValue<string>() == "", "Planner inclusive all-day span changed.");
        var call = sections.Notizen!.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == selected["call"]!["title"]!.GetValue<string>());
        foreach (var value in new[] { "Lotus Organizer: Calls", "Start: 2026-11-09 10:30", "End: 2026-11-09 10:45", "Grace Fixture", "+49305550222", "Synthetic historical record; do not dial", "Completed: true", "Status: Planned" })
            TestAssert.That(call["text"]!.GetValue<string>().Contains(value, StringComparison.Ordinal), "Original call field missing: " + value);
        var web = sections.Notizen!.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == selected["web"]!["title"]!.GetValue<string>());
        TestAssert.That(web["text"]!.GetValue<string>() == "Lotus Organizer: Web\nURL: https://example.test/or6-222\nPreserve source bookmark" &&
            sections.Kontakte.Count == 2 && sections.Termine.Count == 3 && sections.Notizen!.Count == 3 && sections.Uebersprungen == 0,
            "Source sections were lost or became callable contacts/appointments.");
        var once = Or6Codec.Read(Fixture("anniversary-once-222.or6"));
        var oneOff = once.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == annual["name"]!.GetValue<string>());
        TestAssert.That(once.Jahrestage.Count == 0 && once.Uebersprungen == 0 && JsonNode.DeepEquals(oneOff["uid"], annual["uid"]) &&
            oneOff["datum"]!.GetValue<string>() == "2026-11-04" && oneOff["zeit"]!.GetValue<string>() == "" && oneOff["wiederholung"] is null,
            "Unchecked original annual checkbox became a yearly recurrence.");
        CheckPlannerFields();
        CheckTaskStatus();
        return Task.CompletedTask;
    }

    private static void CheckTaskStatus()
    {
        var raw = Or6CodecTests.Fixture(); var original = Or6Codec.Read(raw);
        foreach (var (status, completion, expected) in new (uint Status, bool Completion, bool Expected)[] {
            (1, false, false), (2, false, false), (4, true, true), (1, true, false), (2, true, false) })
        {
            var data = Or6UnsupportedNoteTests.Rotate(raw, true);
            for (int offset = 0; offset < data.Length;)
            {
                var tag = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset));
                var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 8)));
                if (tag == 0x300)
                {
                    var count = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 0x28)));
                    for (var i = 0; i < count; i++)
                    {
                        var entry = offset + 0x34 + i * 8;
                        var field = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(entry));
                        var length = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(entry + 2));
                        if (field == 20)
                        {
                            TestAssert.That(length == 4, "Native task status fixture width changed");
                            BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(entry + 4), status);
                        }
                        else if (field == 19)
                        {
                            TestAssert.That(length == 8, "Native completion fixture width changed");
                            var address = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(entry + 4)));
                            byte[] stamp = completion ? [0xea, 0x07, 11, 13, 12, 0, 0, 0] : [2, 0, 2, 2, 2, 2, 2, 2];
                            stamp.CopyTo(data.AsSpan(offset + address));
                        }
                    }
                }
                offset += size;
            }
            var result = Or6Codec.Read(Or6UnsupportedNoteTests.Rotate(data, false));
            var task = result.Aufgaben.Single()!.DeepClone().AsObject(); var basis = original.Aufgaben.Single()!.DeepClone().AsObject();
            TestAssert.That(task["erledigt"]!.GetValue<bool>() == expected, "Explicit native task status was overridden by an old completion date");
            task.Remove("erledigt"); basis.Remove("erledigt");
            TestAssert.That(JsonNode.DeepEquals(task, basis) && JsonNode.DeepEquals(result.Termine, original.Termine) &&
                JsonNode.DeepEquals(result.Kontakte, original.Kontakte) && JsonNode.DeepEquals(result.Notizen, original.Notizen) &&
                JsonNode.DeepEquals(result.Jahrestage, original.Jahrestage), "Task status correction changed unrelated data");
        }
    }

    private static void CheckPlannerFields()
    {
        var raw = Fixture("sections-corrected-222.or6");
        var original = Or6Codec.Read(raw);
        foreach (var (row, keyId) in new (ushort Row, ushort? KeyId)[] { (1, null), (7, 2), (2, 7), (0, 0) })
        {
            var data = Or6UnsupportedNoteTests.Rotate(raw, true);
            for (int offset = 0; offset < data.Length;)
            {
                var tag = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset));
                var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 8)));
                if (tag == 0x200)
                {
                    var count = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 0x28)));
                    for (var i = 0; i < count; i++)
                    {
                        var entry = offset + 0x34 + i * 8;
                        var field = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(entry));
                        if (field != 18 && !(field == 3 && keyId.HasValue)) continue;
                        BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(entry), field == 18 ? (ushort)18 : (ushort)19);
                        BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(entry + 2), 2);
                        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(entry + 4), field == 18 ? row : keyId!.Value);
                    }
                }
                offset += size;
            }
            var result = Or6Codec.Read(Or6UnsupportedNoteTests.Rotate(data, false));
            var planner = result.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == "OR6-222 Planned span");
            var note = planner["notiz"]!.GetValue<string>();
            TestAssert.That(!note.Contains("event type", StringComparison.Ordinal) && note.Split('\n').Contains("Lotus planner Row: " + row) &&
                (keyId.HasValue ? note.Split('\n').Contains("Lotus planner KeyID: " + keyId.Value) : !note.Contains("KeyID:", StringComparison.Ordinal)),
                "Native planner Row/KeyID were conflated or a missing type reference invented");
            TestAssert.That(!planner.ContainsKey("farbe") && !planner.ContainsKey("kategorie") && !planner.ContainsKey("kategorien"),
                "Unverified native planner numbers became colors/categories");
            var basis = original.Termine.OfType<JsonObject>().Single(value => JsonNode.DeepEquals(value["uid"], planner["uid"])).DeepClone().AsObject();
            var projection = planner.DeepClone().AsObject(); basis.Remove("notiz"); projection.Remove("notiz");
            TestAssert.That(JsonNode.DeepEquals(basis, projection) && JsonNode.DeepEquals(result.Kontakte, original.Kontakte) &&
                JsonNode.DeepEquals(result.Aufgaben, original.Aufgaben) && JsonNode.DeepEquals(result.Notizen, original.Notizen) &&
                JsonNode.DeepEquals(result.Jahrestage, original.Jahrestage), "Planner metadata changed dates, identity or unrelated records");
        }
    }
}
