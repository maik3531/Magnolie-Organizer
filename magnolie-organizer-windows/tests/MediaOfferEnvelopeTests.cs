using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class MediaOfferEnvelopeTests
{
    private const string A = "11111111-1111-4111-8111-111111111111", B = "22222222-2222-4222-8222-222222222222";
    private static readonly string FileId = new('1', 32);
    private static JsonObject Vector() => JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/media-offer-v1-vectors.json"), "contracts/media-offer-v1-vectors.json")))!.AsObject();

    internal static Task RunAsync()
    {
        var vector = Vector(); var message = vector["message"]!.AsObject(); var now = vector["now"]!.GetValue<long>();
        var decoded = MediaOfferEnvelope.Validate(message, A, B, now); var bytes = TelefonCrypto.Canonical(message);
        TestAssert.That(bytes.Length == vector["canonical_bytes"]!.GetValue<int>() && Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == vector["canonical_sha256"]!.GetValue<string>() &&
            decoded.Manifest.Fingerprint == DeviceFileOfferEnvelope.Validate(decoded.Offer, A, B, now).Fingerprint && decoded.Offer["message_id"]!.GetValue<string>() == message["message_id"]!.GetValue<string>(),
            "Shared media offer changed standard offer correlation or cross-platform canonical bytes.");
        var created = MediaOfferEnvelope.Create(decoded.Manifest, decoded.Settings, decoded.MediaType, decoded.MimeTypes, decoded.Originals, now, message["message_id"]!.GetValue<string>());
        TestAssert.That(JsonNode.DeepEquals(created, message), "Shared media offer did not roundtrip its full actual context.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileOfferEnvelope.Validate(message, A, B, now), "Media context fell through to ordinary file acceptance.");
        void Reject(Action<JsonObject> change)
        {
            var altered = message.DeepClone().AsObject(); change(altered);
            TestAssert.Throws<InvalidDataException>(() => MediaOfferEnvelope.Validate(altered, A, B, now), "Invalid media metadata admitted before native ownership.");
        }
        Reject(value => value["extra"] = true); Reject(value => value["expires_ms"] = now);
        Reject(value => value["body"]!["confirmed"] = true); Reject(value => value["body"]!["offer"]!["manifest_sha256"] = new string('0', 64));
        Reject(value => value["body"]!["mime_types"]!.AsObject().Clear());
        Reject(value => value["body"]!["mime_types"]![FileId] = "video/mp4");
        Reject(value => value["body"]!["mime_types"]![FileId] = "image/png; charset=utf-8");
        Reject(value => value["body"]!["mime_types"]![new string('f', 32)] = "image/png");
        Reject(value => value["body"]!["originals"]!.AsObject().Clear());
        Reject(value => value["body"]!["originals"]![new string('f', 32)] = decoded.Originals[FileId]!.DeepClone());
        Reject(value => value["body"]!["originals"]![FileId]!["original_size"] = true);
        Reject(value => value["body"]!["originals"]![FileId]!["original_size"] = JsonNode.Parse("123.0"));
        Reject(value => value["body"]!["originals"]![FileId]!["confirmed"] = true);
        Reject(value => value["body"]!["settings"]!["settings"]!.AsObject().Remove("photos_only"));
        foreach (var (field, setting) in new (string, JsonNode)[] { ("enabled", JsonValue.Create(false)!), ("direction", JsonValue.Create("phone_to_pc")!), ("collection_mode", JsonValue.Create("import_only")!) })
            Reject(value => value["body"]!["settings"] = MediaSyncSettings.Change(decoded.Settings, A, B, field, setting));
        TestAssert.Throws<InvalidDataException>(() => MediaOfferEnvelope.Validate(message, B, B, now), "Wire sender supplied its own native peer identity.");
        var entire = message.DeepClone().AsObject(); entire["body"]!["settings"] = MediaSyncSettings.Change(decoded.Settings, A, B, "collection_mode", JsonValue.Create("entire_collection")!);
        entire["body"]!["originals"]!.AsObject().Clear();
        TestAssert.That(MediaOfferEnvelope.Validate(entire, A, B, now).Originals.Count == 0, "Entire collection invented a phone association for a new member.");
        return Task.CompletedTask;
    }
}
