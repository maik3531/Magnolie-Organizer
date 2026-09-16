using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class RestoreSelection
{
    internal static JsonObject Select(JsonObject snapshot, JsonObject current,
        IReadOnlyCollection<string> areas, string mode)
    {
        if (areas.Count == 0 || areas.Any(area => area is not ("all" or "contacts" or "calendar" or "notes")) ||
            (areas.Contains("all") && areas.Count != 1) ||
            mode is not ("additive" or "replace"))
            throw new InvalidDataException(NativeLocalization.Gettext("The save request is invalid."));
        var result = areas.Contains("all") ? snapshot.DeepClone().AsObject() : current.DeepClone().AsObject();
        if (areas.Contains("all"))
        {
            PreserveAttachments(result, current);
            return result;
        }
        var groups = new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            ["contacts"] = ["kontakte", "jahrestage"],
            ["calendar"] = ["termine", "aufgaben"],
            ["notes"] = ["notizen", "notizgruppen", "notizbuecher"]
        };
        foreach (var area in areas)
            foreach (var name in groups[area])
                result[name] = mode == "additive"
                    ? AddMissing(result[name] as JsonArray, snapshot[name] as JsonArray)
                    : snapshot[name]?.DeepClone() ?? new JsonArray();
        PreserveAttachments(result, current);
        return result;
    }

    private static void PreserveAttachments(JsonNode restored, JsonNode current)
    {
        var data = new Dictionary<string, string?>(StringComparer.Ordinal);
        string Key(JsonObject value)
        {
            foreach (var field in new[] { "sha256", "attachment_id", "id" })
                if (value[field]?.ToString() is string key && key.Length > 0) return field + "\0" + key;
            return "";
        }
        void WalkCurrent(JsonNode node)
        {
            if (node is JsonObject value)
            {
                var key = Key(value);
                foreach (var name in new[] { "daten", "data" })
                    if (key.Length > 0 && value[name]?.ToString() is string text &&
                        text.StartsWith("data:", StringComparison.OrdinalIgnoreCase))
                    {
                        var identity = name + "\0" + key;
                        data[identity] = data.ContainsKey(identity) ? null : text;
                    }
                foreach (var child in value.Select(pair => pair.Value).OfType<JsonNode>()) WalkCurrent(child);
            }
            else if (node is JsonArray array) foreach (var child in array.OfType<JsonNode>()) WalkCurrent(child);
        }
        void WalkRestored(JsonNode node)
        {
            if (node is JsonObject value)
            {
                var key = Key(value);
                foreach (var name in new[] { "daten", "data" })
                    if (value[name]?.ToString() == "" && (key.Length > 0 || value.ContainsKey("name")))
                    {
                        if (key.Length == 0 || !data.TryGetValue(name + "\0" + key, out var text) || text is null)
                            throw new InvalidDataException(NativeLocalization.Gettext("Attachments") + ": " +
                                NativeLocalization.Gettext("The content is missing."));
                        value[name] = text;
                    }
                foreach (var child in value.Select(pair => pair.Value).OfType<JsonNode>()) WalkRestored(child);
            }
            else if (node is JsonArray array) foreach (var child in array.OfType<JsonNode>()) WalkRestored(child);
        }
        WalkCurrent(current);
        WalkRestored(restored);
    }

    private static JsonArray AddMissing(JsonArray? current, JsonArray? snapshot)
    {
        var result = current?.DeepClone().AsArray() ?? new JsonArray();
        var byId = result.OfType<JsonObject>().Select(item => (Item: item,
            Id: item["uid"]?.ToString() ?? item["id"]?.ToString() ?? ""))
            .Where(pair => pair.Id.Length > 0).ToDictionary(pair => pair.Id, pair => pair.Item, StringComparer.Ordinal);
        foreach (var old in snapshot?.OfType<JsonObject>() ?? [])
        {
            var id = old["uid"]?.ToString() ?? old["id"]?.ToString() ?? "";
            if (id.Length == 0 || !byId.TryGetValue(id, out var existing))
            {
                var copy = old.DeepClone().AsObject();
                result.Add(copy);
                if (id.Length > 0) byId[id] = copy;
                continue;
            }
            foreach (var pair in old)
                if ((existing[pair.Key] is null || existing[pair.Key]!.ToJsonString() is "\"\"" or "[]" or "{}") && pair.Value is not null)
                    existing[pair.Key] = pair.Value.DeepClone();
        }
        return result;
    }
}
