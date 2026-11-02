using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeShareTests
{
    internal static async Task RunAsync()
    {
        var bytes = Encoding.UTF8.GetBytes("""
            {"id":1,"type":"kdeconnect.share.request","body":{"filename":"photo.jpg","numberOfFiles":2,"totalPayloadSize":8},"payloadSize":4,"payloadTransferInfo":{"port":1716}}
            """ + "\n");
        var packet = KdeConnectProtocol.Decode(bytes);
        TestAssert.That(packet.Type == "kdeconnect.share.request" && packet.Body["filename"]!.GetValue<string>() == "photo.jpg",
            "Standard KDE file payload announcement could not be decoded.");
        var value = KdeShareProtocol.Parse(packet);
        TestAssert.That(value == new KdeShareAnnouncement("photo.jpg", 4, 1716, 2, 8) &&
            packet.PayloadSize == 4 && packet.PayloadPort == 1716, "Payload metadata was lost or changed.");
        using var stream = new MemoryStream(bytes);
        var streamed = await KdeConnectProtocol.ReadAsync(stream, CancellationToken.None);
        TestAssert.That(KdeShareProtocol.Parse(streamed) == value, "Streaming discarded the file payload envelope.");

        JsonObject Valid() => JsonNode.Parse(Encoding.UTF8.GetString(bytes))!.AsObject();
        KdeConnectPacket Decode(JsonObject root) => KdeConnectProtocol.Decode(Encoding.UTF8.GetBytes(root.ToJsonString() + "\n"));
        void Reject(Action<JsonObject> alter)
        {
            var root = Valid(); alter(root);
            TestAssert.Throws<InvalidDataException>(() => Decode(root), "Malformed file announcement was accepted.");
        }

        var legacy = Valid(); legacy["body"]!.AsObject().Remove("numberOfFiles"); legacy["body"]!.AsObject().Remove("totalPayloadSize");
        TestAssert.That(KdeShareProtocol.Parse(Decode(legacy)) is { NumberOfFiles: null, TotalPayloadSize: null },
            "Optional legacy aggregate hints became mandatory.");
        var empty = Valid(); empty["payloadSize"] = 0;
        TestAssert.That(KdeShareProtocol.Parse(Decode(empty)).Size == 0, "An explicitly announced empty file was rejected.");
        var upper = Valid(); upper["payloadSize"] = KdeShareProtocol.MaxFileBytes;
        upper["payloadTransferInfo"]!["port"] = KdeConnectProtocol.LastPort;
        upper["body"]!["numberOfFiles"] = long.MaxValue; upper["body"]!["totalPayloadSize"] = long.MaxValue;
        TestAssert.That(KdeShareProtocol.Parse(Decode(upper)).TotalPayloadSize == long.MaxValue,
            "Exact optional integer hints were truncated instead of retained for bounded collection.");

        Reject(root => root["extra"] = true);
        Reject(root => root.Remove("payloadSize"));
        Reject(root => root.Remove("payloadTransferInfo"));
        Reject(root => root["payloadTransferInfo"] = new JsonObject { ["port"] = 1716, ["host"] = "other" });
        Reject(root => root["payloadTransferInfo"] = new JsonArray(1716));
        Reject(root => root["type"] = "unrelated.packet");
        Reject(root => root["body"]!["extra"] = true);
        Reject(root => root["body"]!["open"] = "true");
        Reject(root => root["payloadSize"] = KdeShareProtocol.MaxFileBytes + 1);
        Reject(root => root["payloadSize"] = JsonNode.Parse("4.0"));
        Reject(root => root["payloadSize"] = JsonNode.Parse("4e0"));
        Reject(root => root["payloadTransferInfo"]!["port"] = 1715);
        Reject(root => root["payloadTransferInfo"]!["port"] = 1765);
        foreach (var invalid in new JsonNode?[] { null, JsonValue.Create(true), JsonValue.Create(-1),
                     JsonValue.Create("2"), JsonValue.Create(2.5), JsonNode.Parse("9223372036854775808") })
        {
            Reject(root => root["payloadSize"] = invalid?.DeepClone());
            Reject(root => root["payloadTransferInfo"]!["port"] = invalid?.DeepClone());
            foreach (var field in new[] { "creationTime", "lastModified", "numberOfFiles", "totalPayloadSize" })
                Reject(root => root["body"]![field] = invalid?.DeepClone());
        }
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.Decode(Encoding.UTF8.GetBytes(
            "{\"id\":1,\"type\":\"kdeconnect.share.request\",\"body\":{\"filename\":\"a\",\"filename\":\"b\"},\"payloadSize\":1,\"payloadTransferInfo\":{\"port\":1716}}\n")),
            "Duplicate filename metadata bypassed strict duplicate-key detection.");

        foreach (var name in new[] { "photo.jpg", "Urlaub 🌸.jpg", "a..b", ".hidden", "CONSOLE.txt" })
            TestAssert.That(KdeShareProtocol.SafeName(name), "A safe portable Windows file name was rejected: " + name);
        foreach (var name in new[] { "", ".", "..", "../secret", "a/b", "a\\b", "C:relative", "a:b", "a\n.txt",
                     "a\u202e.txt", "a\u0000.txt", "a\ud800.txt", "trailing.", "trailing ", "CON", "con.txt", "COM1.pdf",
                     "LPT9", "COM¹", "NUL.txt", "CON .txt", new string('x', 256) })
        {
            TestAssert.That(!KdeShareProtocol.SafeName(name), "An unsafe Windows file name was accepted.");
            if (!name.Contains('\ud800')) Reject(root => root["body"]!["filename"] = name);
        }

        var update = KdeShareProtocol.ParseUpdate(new JsonObject { ["numberOfFiles"] = 3, ["totalPayloadSize"] = 12 });
        TestAssert.That(update == (3L, 12L), "Typed batch-growth hints changed.");
        var updatePacket = KdeConnectProtocol.Decode(KdeConnectProtocol.Encode(KdeShareProtocol.Update,
            new JsonObject { ["numberOfFiles"] = 3, ["totalPayloadSize"] = 12 }));
        TestAssert.That(KdeShareProtocol.ParseUpdate(updatePacket.Body) == update && updatePacket.PayloadSize is null,
            "A standard metadata-only growth update acquired a payload or lost its hints.");
        TestAssert.Throws<InvalidDataException>(() => KdeShareProtocol.ParseUpdate(new JsonObject {
            ["numberOfFiles"] = true, ["totalPayloadSize"] = 12 }), "Boolean count was accepted as a number.");
        TestAssert.Throws<InvalidDataException>(() => KdeShareProtocol.ParseUpdate(new JsonObject {
            ["numberOfFiles"] = 3, ["totalPayloadSize"] = 12, ["grant"] = true }), "Update could invent an extra grant field.");
        var identity = KdeConnectProtocol.IdentityBody("test-peer", "Parser test", 1716);
        TestAssert.That(!identity["incomingCapabilities"]!.AsArray().Any(item => item?.GetValue<string>() is
            KdeShareProtocol.Request or KdeShareProtocol.Update), "Parser-only work advertised an unimplemented receive capability.");
    }
}
