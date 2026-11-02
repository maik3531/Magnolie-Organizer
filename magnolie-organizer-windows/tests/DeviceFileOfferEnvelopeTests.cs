using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileOfferEnvelopeTests
{
    private const long Now = 1800000000000;
    private const string MessageId = "00000000-0000-4000-8000-000000000001";
    private static JsonNode Fixture(string name) => JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/" + name), "contracts", name)))!;
    private static DeviceFileManifest Manifest()
    {
        using var document = JsonDocument.Parse(Fixture("file-transfer-manifest-v1-vectors.json")["vectors"]![0]!["manifest"]!.ToJsonString());
        return DeviceFileManifest.Parse(document.RootElement);
    }
    private static DeviceFileManifest Large(int characters, int padding = 0)
    {
        var original = Manifest();
        var files = Enumerable.Range(0, 128).Select(index =>
        {
            var length = characters / 128 + (index < characters % 128 ? 1 : 0);
            var path = string.Join('/', Enumerable.Range(0, (length + 199) / 200).Select(part => new string('界', Math.Min(200, length - part * 200))));
            path += $"/file-{index}" + (index == 0 ? new string('x', padding) : "") + ".jpg";
            return new DeviceManifestFile((index + 1).ToString("x32"), path, 0, Convert.ToHexString(SHA256.HashData([])).ToLowerInvariant());
        }).ToArray();
        return new(original.TransferId, original.SourceId, original.SenderId, original.ReceiverId, files, 0);
    }
    private static JsonObject Raw(DeviceFileManifest value)
    {
        // Reuse actual complete creation for small values, then replace the
        // complete manifest to exercise independent oversize validation.
        var message = DeviceFileOfferEnvelope.Create(Manifest(), Now, MessageId);
        var body = message["body"]!.AsObject();
        var wire = body["manifest"]!.AsObject();
        wire["files"] = new JsonArray(value.Files.Select(file => (JsonNode)new JsonObject
        { ["id"] = file.Id, ["path"] = file.Path, ["size"] = file.Size, ["sha256"] = file.Sha256 }).ToArray());
        wire["total_bytes"] = value.TotalBytes;
        body["manifest_sha256"] = value.Fingerprint;
        return message;
    }
    private static DeviceFileManifest ForBytes(int target)
    {
        var low = 128 * 580; var high = 128 * 700;
        while (low < high)
        {
            var middle = (low + high + 1) / 2;
            if (TelefonCrypto.Canonical(Raw(Large(middle))).Length <= target) low = middle; else high = middle - 1;
        }
        var difference = target - TelefonCrypto.Canonical(Raw(Large(low))).Length;
        TestAssert.That(difference is >= 0 and <= 4, "Unexpected canonical boundary padding.");
        var result = Large(low, difference);
        TestAssert.That(TelefonCrypto.Canonical(Raw(result)).Length == target, "Exact canonical byte boundary not exercised.");
        return result;
    }
    internal static Task RunAsync()
    {
        var manifest = Manifest();
        var vector = Fixture("file-transfer-offer-v1-vectors.json");
        var message = DeviceFileOfferEnvelope.Create(manifest, vector["created_ms"]!.GetValue<long>(), vector["message_id"]!.GetValue<string>(), vector["ttl_ms"]!.GetValue<long>());
        var bytes = TelefonCrypto.Canonical(message);
        TestAssert.That(bytes.Length == vector["canonical_bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == vector["canonical_sha256"]!.GetValue<string>(), "Shared complete Unicode offer encoding differs.");
        TestAssert.That(DeviceFileOfferEnvelope.Validate(message, manifest.SenderId, manifest.ReceiverId, Now).Fingerprint == manifest.Fingerprint, "Full manifest fingerprint changed.");
        var exact = ForBytes(DeviceFileOfferEnvelope.MaximumApplicationBytes);
        var accepted = DeviceFileOfferEnvelope.Create(exact, Now, MessageId);
        TestAssert.That(TelefonCrypto.Canonical(accepted).Length == 262144 && exact.Files.Count == 128, "Exact maximum did not retain complete members.");
        var excess = ForBytes(DeviceFileOfferEnvelope.MaximumApplicationBytes + 1);
        TestAssert.That(TelefonCrypto.Canonical(Raw(excess)["body"]!["manifest"]!).Length < 262144, "Bare manifest should fit while whole envelope does not.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileOfferEnvelope.Create(excess, Now, MessageId), "Oversize offer silently split or accepted.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileOfferEnvelope.Validate(Raw(excess), manifest.SenderId, manifest.ReceiverId, Now), "Oversize receive envelope accepted.");
        void Reject(Action<JsonObject> change)
        {
            var altered = message.DeepClone().AsObject(); change(altered);
            TestAssert.Throws<InvalidDataException>(() => DeviceFileOfferEnvelope.Validate(altered, manifest.SenderId, manifest.ReceiverId, Now), "Invalid offer accepted.");
        }
        Reject(value => value["extra"] = true); Reject(value => value["v"] = true);
        Reject(value => value["message_id"] = "invalid"); Reject(value => value["kind"] = "personal_sync.attachment_request");
        Reject(value => value["expires_ms"] = Now + 60001);
        Reject(value => value["body"]!["version"] = true); Reject(value => value["body"]!["version"] = "1");
        Reject(value => value["body"]!["extra"] = true); Reject(value => value["body"]!["manifest_sha256"] = new string('0', 64));
        Reject(value => value["body"]!["manifest"]!["source_id"] = new string('f', 32));
        TestAssert.Throws<InvalidDataException>(() => DeviceFileOfferEnvelope.Validate(message, "other_sender_0001", manifest.ReceiverId, Now), "Wire sender used as native peer authority.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileOfferEnvelope.Validate(message, manifest.SenderId, "other_receiver_01", Now), "Wire receiver used as native peer authority.");
        TestAssert.Throws<TelefonMessageException>(() => TelefonMessageContract.ValidateMessage(message, Now, true), "Offer kind activated before native handlers/grants.");
        return Task.CompletedTask;
    }
}
