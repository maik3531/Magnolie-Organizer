using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>Correlated content starts; authentication and current ownership remain caller gates.
/// Not advertised before actor-scoped staging/commit is connected.</summary>
internal static class PersonalSyncActorContract
{
    internal const int Version = 12;
    internal const string StartKind = "personal_sync.actor_start";

    internal static JsonObject ValidateStart(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "run_id", "trigger");
        if (TelefonProtocolContract.Integer(body["format"]) != Version ||
            !TelefonProtocolContract.IsUuidV4(body["run_id"]?.GetValue<string>()) || body["trigger"]?.GetValue<string>() != "manual")
            throw new InvalidDataException("Invalid actor-scoped synchronization start.");
        return body;
    }

    internal static JsonObject Start(string runId) => ValidateStart(new JsonObject
    { ["format"] = Version, ["run_id"] = runId, ["trigger"] = "manual" });

    internal static bool Supported(JsonObject local, JsonObject remote) => SharedSyncSettings.Supported(local, remote) &&
        new[] { local, remote }.All(items => new[] { "personal_notes_sync", "personal_tasks_sync" }.All(name =>
            items[name]?["available"] is JsonValue flag && flag.TryGetValue<bool>(out var available) && available &&
            items[name]?["versions"] is JsonArray versions && versions.Any(value =>
                TelefonProtocolContract.TryInteger(value, out var number) && number == Version)));
}
