using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>A one-use snapshot handoff from a verified contact cleanup to its following sync.</summary>
internal sealed class ContactCleanupSnapshot
{
    private JsonObject? plan;
    private JsonObject? before;
    private string? readyText;

    internal void Planned(JsonObject value) { plan = value.DeepClone().AsObject(); before = null; readyText = null; }

    internal void Snapshotted(JsonObject data)
    {
        before = null; readyText = null;
        if (plan?["groups"] is not JsonArray { Count: > 0 }) return;
        using var document = System.Text.Json.JsonDocument.Parse(data.ToJsonString());
        var current = ContactCleanupPlan.Create(document.RootElement, ContactFields.Text(plan, "homeCountry"));
        if (JsonNode.DeepEquals(current["groups"], plan["groups"]) && ContactFields.Text(current, "source") == ContactFields.Text(plan, "source"))
            before = data.DeepClone().AsObject();
    }

    internal void Saved(string text)
    {
        if (before is null || plan is null) { readyText = null; return; }
        try
        {
            var after = JsonNode.Parse(text)!.AsObject();
            readyText = AppliedOnlyPlannedChanges(before, after, plan) ? text : null;
        }
        catch (Exception error) when (error is System.Text.Json.JsonException or InvalidOperationException or ArgumentException)
        { readyText = null; }
    }

    internal bool Consume(string text, string source)
    {
        var ready = readyText == text && plan is not null && ContactFields.Text(plan, "source") == source;
        plan = null; before = null; readyText = null;
        return ready;
    }

    internal static bool AppliedOnlyPlannedChanges(JsonObject before, JsonObject after, JsonObject plan)
    {
        var source = ContactFields.Text(plan, "source");
        if (after["einstellungen"]?["sync"]?["adressbuchUid"]?.GetValue<string>() != source) return false;
        var expected = before.DeepClone().AsObject();
        var cards = (expected["kontakte"] as JsonArray ?? []).OfType<JsonObject>().ToDictionary(card => ContactFields.Text(card, "id"), StringComparer.Ordinal);
        var original = cards.ToDictionary(pair => pair.Key, pair => pair.Value.DeepClone().AsObject(), StringComparer.Ordinal);
        var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
        var deletions = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var group in plan["groups"]!.AsArray().OfType<JsonObject>())
        {
            var keepId = ContactFields.Text(group, "keepId");
            if (!cards.TryGetValue(keepId, out var keeper) || !original.TryGetValue(ContactFields.Text(group, "contentFromId"), out var content)) return false;
            foreach (var field in group["contentFields"]!.AsArray().Select(node => node!.GetValue<string>()))
                if (content.ContainsKey(field)) keeper[field] = content[field]?.DeepClone(); else keeper.Remove(field);
            foreach (var pair in group["metadata"]!.AsObject()) keeper[pair.Key] = pair.Value?.DeepClone();
            foreach (var id in group["ids"]!.AsArray().Select(node => node!.GetValue<string>()).Where(id => id != keepId))
            { if (!cards.Remove(id) || !aliases.TryAdd(id, keepId)) return false; }
            foreach (var deletion in group["deletions"]!.AsArray().OfType<JsonObject>())
                if (!deletions.TryAdd(ContactFields.Text(deletion["mapping"]!.AsObject(), "id"), deletion)) return false;
        }
        expected["kontakte"] = new JsonArray(cards.Values.Select(card => card.DeepClone()).ToArray());
        foreach (var field in new[] { "termine", "aufgaben", "jahrestage", "smsVerlauf", "smsPlanung" })
            foreach (var item in (expected[field] as JsonArray ?? []).OfType<JsonObject>())
                if (aliases.TryGetValue(ContactFields.Text(item, "kontaktId"), out var id)) item["kontaktId"] = id;

        var oldTrash = (before["papierkorb"] as JsonArray ?? []).OfType<JsonObject>().ToDictionary(item => ContactFields.Text(item, "id"), StringComparer.Ordinal);
        foreach (var item in (after["papierkorb"] as JsonArray ?? []).OfType<JsonObject>())
        {
            if (oldTrash.Remove(ContactFields.Text(item, "id"), out var old)) { if (!JsonNode.DeepEquals(old, item)) return false; }
            else if (ContactFields.Text(item, "art") != "duplicate" || item["eintrag"] is not JsonObject card ||
                !aliases.ContainsKey(ContactFields.Text(card, "id")) || !JsonNode.DeepEquals(card, original[ContactFields.Text(card, "id")])) return false;
        }
        if (oldTrash.Count > 0) return false;
        expected["papierkorb"] = after["papierkorb"]?.DeepClone();

        var oldDeleted = (before["geloescht"]?["kontakte"] as JsonArray ?? []).OfType<JsonObject>()
            .ToDictionary(item => ContactFields.Text(item, "uid"), StringComparer.Ordinal);
        foreach (var item in (after["geloescht"]?["kontakte"] as JsonArray ?? []).OfType<JsonObject>())
        {
            if (oldDeleted.Remove(ContactFields.Text(item, "uid"), out var old)) { if (!JsonNode.DeepEquals(old, item)) return false; continue; }
            if (item["kontaktDuplikat"] is not JsonObject proof || ContactFields.Text(proof, "source") != source ||
                ContactFields.Source(item, source) is not JsonObject mapping ||
                !deletions.Remove(ContactFields.Text(mapping, "id"), out var deletion) || !JsonNode.DeepEquals(mapping, deletion["mapping"]) ||
                new[] { "keeperId", "contentHash", "keeperHash", "desiredHash" }.Any(field => !JsonNode.DeepEquals(proof[field], deletion[field]))) return false;
        }
        if (oldDeleted.Count > 0 || deletions.Count > 0) return false;
        var deleted = expected["geloescht"] as JsonObject ?? new JsonObject();
        deleted["kontakte"] = after["geloescht"]?["kontakte"]?.DeepClone(); expected["geloescht"] = deleted;
        return !RecoveryJournal.HasRecoverableChanges(expected, after);
    }
}

internal sealed class SyncSnapshotHandoff
{
    private JsonObject? completed;
    private string transaction = "";
    private static readonly HashSet<string> Domains = new(new[] { "termine", "aufgaben", "kontakte", "jahrestage", "geloescht" }, StringComparer.Ordinal);

    internal static JsonObject Content(JsonObject data)
    {
        var result = new JsonObject();
        foreach (var field in Domains) result[field] = data[field]?.DeepClone() ?? (field == "geloescht" ? new JsonObject() : new JsonArray());
        return result;
    }

    internal void Completed(string id, JsonObject result, bool snapshotExists)
    { transaction = snapshotExists ? id : ""; completed = snapshotExists ? result : null; }

    internal bool CoversSave(JsonObject previous, JsonObject proposed)
    {
        if (completed is null || proposed["syncAbgleichNachweis"]?["transactionId"]?.GetValue<string>() != transaction ||
            (previous["syncEpoch"]?.GetValue<string>() ?? "") != (completed["syncEpoch"]?.GetValue<string>() ?? "") ||
            !SyncBaseline.ContainsSavedResult(completed, proposed)) return false;
        JsonObject Outside(JsonObject data) => new(data.Where(pair => !Domains.Contains(pair.Key))
            .Select(pair => new KeyValuePair<string, JsonNode?>(pair.Key, pair.Value?.DeepClone())));
        return !RecoveryJournal.HasRecoverableChanges(Outside(previous), Outside(proposed));
    }

    internal void Saved() { transaction = ""; completed = null; }
}
