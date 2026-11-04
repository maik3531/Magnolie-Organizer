using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    private static bool ValidPersonalSuccess(JsonObject value)
    {
        if (!value.Select(item => item.Key).ToHashSet(StringComparer.Ordinal).SetEquals(
                ["format", "run_id", "peer_fingerprint", "trigger", "finished_ms"])) return false;
        return value["format"] is JsonValue format && format.TryGetValue<int>(out var version) && version == 1 &&
            value["run_id"] is JsonValue run && run.TryGetValue<string>(out var id) && TelefonProtocolContract.IsUuidV4(id) &&
            value["peer_fingerprint"] is JsonValue fingerprint && fingerprint.TryGetValue<string>(out var key) &&
            key.Length == 64 && key.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f') &&
            value["trigger"] is JsonValue trigger && trigger.TryGetValue<string>(out var mode) && mode is "manual" or "auto_wifi" or "auto_connection" &&
            value["finished_ms"] is JsonValue finished && finished.TryGetValue<long>(out var at) && at is > 0 and <= 253402300799999;
    }

    internal JsonObject? PersonalSuccess(string peerId)
    {
        lock (gate)
        {
            if (RestoreFenced) return null;
            var peers = LoadPeers().Where(peer => peer.Id == peerId && peer.State == "paired").ToArray();
            if (peers.Length != 1) return null;
            var personal = (LoadSettings()["personal_sync"] as JsonObject)?[peerId] as JsonObject;
            var value = personal?["last_success"] as JsonObject;
            if (value is null || !ValidPersonalSuccess(value) || value["peer_fingerprint"]!.GetValue<string>() !=
                    Convert.ToHexString(SHA256.HashData(peers[0].PublicKey)).ToLowerInvariant()) return null;
            return new JsonObject { ["format"] = 1, ["trigger"] = value["trigger"]!.DeepClone(),
                ["finished_ms"] = value["finished_ms"]!.DeepClone() };
        }
    }

    // Internal confirmed-completion sink; neither queueing nor incoming report
    // claims call this method. Display metadata never controls data authority.
    internal bool RememberPersonalSuccess(string peerId, string expectedPublicKey, string runId, string trigger, long finishedMs)
    {
        try
        {
            lock (gate)
            {
                if (RestoreFenced) return false;
                var peers = LoadPeers();
                if (peers.Count != 1 || peers[0].Id != peerId || peers[0].State != "paired" ||
                    Convert.ToBase64String(peers[0].PublicKey) != expectedPublicKey) return false;
                var value = new JsonObject { ["format"] = 1, ["run_id"] = runId, ["trigger"] = trigger,
                    ["finished_ms"] = finishedMs, ["peer_fingerprint"] = Convert.ToHexString(SHA256.HashData(peers[0].PublicKey)).ToLowerInvariant() };
                if (!ValidPersonalSuccess(value)) return false;
                var settings = LoadSettings();
                if (settings["personal_sync"] is not null and not JsonObject) return false;
                var all = settings["personal_sync"] as JsonObject ?? new JsonObject(); settings["personal_sync"] = all;
                if (all[peerId] is not null and not JsonObject) return false;
                var personal = all[peerId] as JsonObject ?? new JsonObject(); all[peerId] = personal;
                if (personal["last_success"] is not null)
                {
                    if (personal["last_success"] is not JsonObject old || !ValidPersonalSuccess(old)) return false;
                    if (old["peer_fingerprint"]!.GetValue<string>() == value["peer_fingerprint"]!.GetValue<string>() &&
                        (old["run_id"]!.GetValue<string>() == runId || old["finished_ms"]!.GetValue<long>() >= finishedMs)) return false;
                }
                personal["last_success"] = value; SaveSettings(settings); return true;
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Text.Json.JsonException or InvalidOperationException or CryptographicException)
        { return false; } // A display metadata failure cannot roll back a completed data run.
    }
}
