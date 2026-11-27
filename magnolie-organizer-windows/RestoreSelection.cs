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
                    ? AddMissing(result[name] as JsonArray, snapshot[name] as JsonArray,
                        sourceScoped: name is "termine" or "aufgaben", contacts: name == "kontakte")
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

    private static JsonArray AddMissing(JsonArray? current, JsonArray? snapshot, bool sourceScoped, bool contacts)
    {
        var result = current?.DeepClone().AsArray() ?? new JsonArray();
        string LocalId(JsonObject item) => item["id"]?.ToString() ?? "";
        string Source(JsonObject item)
        {
            var source = item["icsQuelleId"]?.ToString() ?? "";
            if (source.Length == 0) source = item["syncKalenderUid"]?.ToString() ?? "";
            if (source.Length == 0) source = (item["kalenderQuelle"] as JsonObject)?["id"]?.ToString() ?? "";
            return source;
        }
        (string Uid, string IcsSource, string SyncSource, string ObjectSource) Binding(JsonObject item) =>
            (item["uid"]?.ToString() ?? "", item["icsQuelleId"]?.ToString() ?? "", item["syncKalenderUid"]?.ToString() ?? "",
                (item["kalenderQuelle"] as JsonObject)?["id"]?.ToString() ?? "");
        (string Kind, string Source, string Value)? Identity(JsonObject item)
        {
            var uid = item["uid"]?.ToString() ?? "";
            if (uid.Length > 0)
                return ("uid", sourceScoped ? Source(item) : "", uid);
            var localId = LocalId(item);
            return localId.Length > 0 ? ("id", "", localId) : null;
        }
        // A moved record retains its local id, not its old provider bindings.
        // Only known user content can fill gaps across a changed source/UID;
        // unknown future provider metadata must remain excluded too.
        var contentFields = new HashSet<string>(StringComparer.Ordinal) {
            "titel", "notiz", "notizen", "text", "datum", "zeit", "endDatum", "endZeit",
            "kategorien", "ort", "alarme", "organisator", "teilnehmer", "kalenderAnhaenge",
            "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "individuelleErinnerungTage",
            "standardErinnerung", "wiederholung", "prio", "prioritaet", "faellig", "startDatum",
            "startZeit", "faelligZeit", "erledigt", "erinnern", "reihenfolge"
        };
        if (contacts)
        {
            // Imports can assign a UID to an existing local contact. Its old
            // source links and provider round-trip metadata are not content.
            contentFields = new HashSet<string>(StringComparer.Ordinal) {
                "nachname", "vorname", "anzeigename", "firma", "strasse", "plz", "ort", "land",
                "telefon", "mobil", "telefone", "email", "emails", "emailEintraege", "anschriften",
                "geburtstag", "geburtstagJahrUnbekannt", "jubilaeum", "jubilaeumJahrUnbekannt",
                "notiz", "foto", "kontaktpersonName", "kontaktpersonTelefon", "kontaktpersonStatus",
                "kontaktpersonen", "sozialeMedien", "gruppen"
            };
        }
        var preferLocalId = sourceScoped || contacts;
        var byId = new Dictionary<(string Kind, string Source, string Value), List<JsonObject>>();
        var byLocalId = new Dictionary<string, List<JsonObject>>(StringComparer.Ordinal);
        void Remember(JsonObject item)
        {
            if (Identity(item) is { } identity)
            {
                if (!byId.TryGetValue(identity, out var matches)) byId[identity] = matches = [];
                matches.Add(item);
            }
            if (LocalId(item) is { Length: > 0 } local)
            {
                if (!byLocalId.TryGetValue(local, out var matches)) byLocalId[local] = matches = [];
                matches.Add(item);
            }
        }
        foreach (var item in result.OfType<JsonObject>()) Remember(item);
        var oldItems = snapshot?.OfType<JsonObject>().ToArray() ?? [];
        var ambiguousOldIds = oldItems.Where(item => LocalId(item).Length > 0)
            .GroupBy(LocalId, StringComparer.Ordinal)
            .Where(group => group.Skip(1).Any(item => !JsonNode.DeepEquals(item, group.First())))
            .Select(group => group.Key).ToHashSet(StringComparer.Ordinal);
        var oldCounts = new Dictionary<(string Kind, string Source, string Value), int>();
        foreach (var item in oldItems)
            if (Identity(item) is { } key) oldCounts[key] = oldCounts.GetValueOrDefault(key) + 1;
        foreach (var old in oldItems)
        {
            var identity = Identity(old);
            var matches = identity.HasValue && byId.TryGetValue(identity.Value, out var found) ? found : [];
            var existing = matches.Count == 1 ? matches[0] : null;
            var localId = LocalId(old);
            var localMatches = preferLocalId && localId.Length > 0 && byLocalId.TryGetValue(localId, out var localFound) ? localFound : [];
            if (preferLocalId && localId.Length > 0 && (localMatches.Count > 1 || ambiguousOldIds.Contains(localId)))
            {
                if (localMatches.Any(item => JsonNode.DeepEquals(item, old))) continue;
                // Preexisting duplicate local ids need an exact unchanged
                // source match; otherwise hold the entire additive operation.
                var sameSource = matches.Where(item => LocalId(item) == localId).Take(2).ToArray();
                if (ambiguousOldIds.Contains(localId) || sameSource.Length != 1)
                    throw new InvalidDataException(NativeLocalization.Gettext("Conflict"));
                existing = sameSource[0];
            }
            else if (localMatches.Count == 1) existing = localMatches[0];
            else if (matches.Count > 1 || (identity.HasValue && oldCounts.GetValueOrDefault(identity.Value) > 1))
            {
                // A duplicate external identity must not choose an arbitrary record.
                existing = null;
                var sameId = matches.Where(item => localId.Length > 0 && LocalId(item) == localId).Take(2).ToArray();
                if (sameId.Length == 1) existing = sameId[0];
                else if (matches.Any(item => JsonNode.DeepEquals(item, old))) continue;
            }
            if (existing is null)
            {
                var copy = old.DeepClone().AsObject();
                result.Add(copy);
                Remember(copy);
                continue;
            }
            var changedBinding = sourceScoped && Binding(existing) != Binding(old) ||
                contacts && (existing["uid"]?.ToString() ?? "") != (old["uid"]?.ToString() ?? "");
            var previousLocalId = LocalId(existing);
            foreach (var pair in old)
            {
                if (changedBinding && (!contentFields.Contains(pair.Key) || pair.Value is null ||
                    pair.Value.ToJsonString() is "\"\"" or "[]" or "{}")) continue;
                if ((existing[pair.Key] is null || existing[pair.Key]!.ToJsonString() is "\"\"" or "[]" or "{}") && pair.Value is not null)
                    existing[pair.Key] = pair.Value.DeepClone();
            }
            if (previousLocalId.Length == 0 && LocalId(existing) is { Length: > 0 } assignedId)
            {
                if (!byLocalId.TryGetValue(assignedId, out var assignedMatches)) byLocalId[assignedId] = assignedMatches = [];
                assignedMatches.Add(existing);
            }
        }
        return result;
    }
}
