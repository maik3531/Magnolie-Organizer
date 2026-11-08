using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class TraySyncFrames
{
    // Existing data/actor frames only. Settings, heartbeat, diagnostics, queued
    // work and timer-control requests are not actual synchronization IO.
    private static readonly HashSet<string> Kinds = new(StringComparer.Ordinal) {
        "personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
        "personal_sync.deletion_proposals", "personal_sync.deletion_decision", "personal_sync.scoped_data",
        "personal_sync.custom_request", "personal_sync.custom_batch",
        "personal_sync.time_request", "personal_sync.time_batch",
        "personal_sync.actor_start", "personal_sync.actor_data", "personal_sync.actor_ack", "personal_sync.actor_cancel"
    };
    internal static bool IsData(JsonObject message) => message["type"] is JsonValue type &&
        type.TryGetValue<string>(out var name) && name == "message" && message["kind"] is JsonValue kind &&
        kind.TryGetValue<string>(out var value) && Kinds.Contains(value);
}
