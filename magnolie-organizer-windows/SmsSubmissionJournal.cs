using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class SmsSubmissionJournal(string path)
{
    private readonly object gate = new();
    private readonly AtomicStore files = new();
    internal string? Reserve(string clientRef, string number, string text, string country,
        string expectedDeviceId = "", string expectedFingerprint = "")
    {
        if (clientRef.Length is < 1 or > 160) throw new InvalidDataException();
        var id = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(clientRef)));
        var payload = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            new JsonArray(number, text, country, expectedDeviceId, expectedFingerprint).ToJsonString())));
        lock (gate)
        {
            var data = Load();
            if (data[id] is JsonObject old)
            {
                if (old["payload"]?.GetValue<string>() != payload) throw new InvalidDataException();
                return old["state"]?.GetValue<string>() ?? "uncertain";
            }
            // Never evict a submission identity: that would make a late replay send twice.
            if (data.Count >= 10000) throw new IOException(NativeLocalization.Gettext("The SMS submission journal is full. No message was sent."));
            data[id] = new JsonObject { ["payload"] = payload, ["state"] = "uncertain" };
            files.WriteRecoverableJson(path, data.ToJsonString());
            return null;
        }
    }
    internal void Submitted(string clientRef)
    {
        lock (gate)
        {
            var data = Load();
            var id = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(clientRef)));
            if (data[id] is not JsonObject item) throw new InvalidDataException();
            item["state"] = "submitted"; files.WriteRecoverableJson(path, data.ToJsonString());
        }
    }
    private JsonObject Load() => JsonNode.Parse(files.ReadRecoverableJson(path, 4 * 1024 * 1024) ?? "{}")!.AsObject();
}
