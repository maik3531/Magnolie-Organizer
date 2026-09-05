using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record GesamtarchivInfo(
    JsonObject Daten, string Erstellt, string Plattform, string Appversion,
    bool Verschluesselt, IReadOnlyDictionary<string, int> Anzahlen, int Fotos, int Anhaenge);

internal static class GesamtarchivService
{
    internal const string Marker = "magnolie-gesamtarchiv";
    internal const int Fassung = 1;
    internal const int Datenschema = 3;

    internal static bool IsArchivePath(string path) =>
        string.Equals(Path.GetExtension(path), ".magnolie", StringComparison.OrdinalIgnoreCase);

    internal static string Create(JsonObject data, string platform, string appVersion,
        string password = "", DateTimeOffset? created = null)
    {
        data = NormalizeRecurrences(data);
        RejectIntegrationSecrets(data);
        var canonical = MagnolienbaumCrypto.Canonical(data);
        var root = new JsonObject
        {
            ["magnolie"] = Marker,
            ["fassung"] = Fassung,
            ["datenschema"] = Datenschema,
            ["erstellt"] = (created ?? DateTimeOffset.UtcNow).ToUniversalTime().ToString("O"),
            ["plattform"] = platform,
            ["appversion"] = appVersion,
            ["sha256"] = Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant(),
            ["daten"] = data.DeepClone()
        };
        var plain = Encoding.UTF8.GetString(MagnolienbaumCrypto.Canonical(root));
        var result = password.Length == 0 ? plain : new EncryptionService().Enable(plain, password);
        if (Encoding.UTF8.GetByteCount(result) > AtomicStore.MaxArchiveBytes)
            throw new IOException("Das Gesamtarchiv ist größer als 384 MiB.");
        return result;
    }

    internal static GesamtarchivInfo Read(string storedText, string password = "")
    {
        var encrypted = EncryptionService.IsEncrypted(storedText);
        if (encrypted && password.Length == 0)
            throw new CryptographicException("Für dieses Gesamtarchiv ist das Kennwort erforderlich.");
        var plain = encrypted ? new EncryptionService().Unlock(storedText, password) : storedText;
        JsonObject root;
        try { root = JsonNode.Parse(plain) as JsonObject ?? throw new InvalidDataException(); }
        catch (JsonException) { throw new InvalidDataException("Das Gesamtarchiv enthält kein gültiges JSON-Objekt."); }
        if (Text(root, "magnolie") != Marker || Integer(root, "fassung") != Fassung)
            throw new InvalidDataException("Format oder Datenschema des Gesamtarchivs wird nicht unterstützt.");
        var created = Text(root, "erstellt");
        if (!DateTimeOffset.TryParse(created, out _))
            throw new InvalidDataException("Das Erstellungsdatum des Gesamtarchivs ist ungültig.");
        var platform = Text(root, "plattform");
        if (platform is not ("linux" or "windows"))
            throw new InvalidDataException("Die Quellplattform des Gesamtarchivs ist ungültig.");
        var data = root["daten"] as JsonObject
            ?? throw new InvalidDataException("Der Datenbestand des Gesamtarchivs muss ein Objekt sein.");
        var expected = Text(root, "sha256");
        if (expected.Length != 64 || !CryptographicOperations.FixedTimeEquals(
                Encoding.ASCII.GetBytes(expected.ToLowerInvariant()),
                Encoding.ASCII.GetBytes(Convert.ToHexString(SHA256.HashData(
                    MagnolienbaumCrypto.Canonical(data))).ToLowerInvariant())))
            throw new InvalidDataException("Die SHA-256-Prüfsumme des Gesamtarchivs stimmt nicht.");
        if (Integer(root, "datenschema") is not (1 or 2 or Datenschema))
            throw new InvalidDataException("Format oder Datenschema des Gesamtarchivs wird nicht unterstützt.");
        RejectIntegrationSecrets(data);
        data = NormalizeRecurrences(data);
        var names = new[] { "termine", "aufgaben", "kontakte", "notizen", "notizgruppen", "notizbuecher",
            "jahrestage", "feiertage", "urlaube", "muelltermine", "personen", "schichten", "zyklusmarker",
            "tagmarken", "papierkorb", "tombstones" };
        var counts = names.ToDictionary(name => name,
            name => data[name] is JsonArray values ? values.Count : 0, StringComparer.Ordinal);
        var photos = CountDataUrls(data, "foto");
        var attachments = CountDataUrls(data, "daten");
        return new GesamtarchivInfo(data.DeepClone().AsObject(), created, platform,
            Text(root, "appversion"), encrypted, counts, photos, attachments);
    }

    internal static JsonObject PreserveDeviceSettings(JsonObject imported, JsonObject local, bool crossPlatform)
    {
        if (!crossPlatform) return imported.DeepClone().AsObject();
        var result = imported.DeepClone().AsObject();
        CopyPath(local, result, "einstellungen", "allgemein", "tray");
        CopyPath(local, result, "einstellungen", "allgemein", "sicherungsordner");
        CopyPath(local, result, "einstellungen", "sync");
        return result;
    }

    private static void CopyPath(JsonObject source, JsonObject target, params string[] path)
    {
        JsonNode? value = source;
        foreach (var part in path) value = (value as JsonObject)?[part];
        if (value is null) return;
        JsonObject destination = target;
        foreach (var part in path[..^1])
        {
            if (destination[part] is not JsonObject child)
            {
                child = new JsonObject(); destination[part] = child;
            }
            destination = child;
        }
        destination[path[^1]] = value.DeepClone();
    }

    private static void RejectIntegrationSecrets(JsonNode node)
    {
        if (node is JsonObject obj)
        {
            foreach (var pair in obj)
            {
                var key = pair.Key.Replace("_", "", StringComparison.Ordinal).Replace("-", "", StringComparison.Ordinal).ToLowerInvariant();
                if (key is "graphtoken" or "accesstoken" or "refreshtoken" or "clientsecret")
                    throw new InvalidDataException("Externe Integrationstokens dürfen nicht im Gesamtarchiv enthalten sein.");
                if (pair.Value is not null) RejectIntegrationSecrets(pair.Value);
            }
        }
        else if (node is JsonArray array)
            foreach (var value in array) if (value is not null) RejectIntegrationSecrets(value);
    }

    private static JsonObject NormalizeRecurrences(JsonObject data)
    {
        var result = data.DeepClone().AsObject();
        if (result["termine"] is JsonArray appointments)
            foreach (var appointment in appointments.OfType<JsonObject>())
                if (appointment["wiederholung"] is JsonObject recurrence &&
                    string.Equals(recurrence["art"]?.GetValue<string>(), "monthly_weekday", StringComparison.OrdinalIgnoreCase))
                    recurrence["art"] = "monthly";
        if (result["aufgaben"] is JsonArray tasks) NormalizeTaskGraph(tasks);
        result["version"] = Math.Max(7, result["version"]?.GetValue<int>() ?? 0);
        return result;
    }

    internal static void NormalizeTaskGraph(JsonArray tasks)
    {
        var technicalOrder = Comparer<string>.Create((left, right) =>
            Encoding.UTF8.GetBytes(left).AsSpan().SequenceCompareTo(Encoding.UTF8.GetBytes(right)));
        var values = tasks.OfType<JsonObject>().ToArray();
        var old = values.GroupBy(task => task["uid"]?.GetValue<string>()?.Trim() ?? "", StringComparer.Ordinal)
            .Where(group => group.Key.Length > 0).ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.Ordinal);
        var reserved = old.Where(pair => pair.Value.Length == 1).Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal);
        var used = new HashSet<string>(StringComparer.Ordinal);
        var nextAttempt = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var pair in values.Select((task, index) => (Task: task, Index: index))
                     .OrderBy(pair => pair.Task["id"]?.GetValue<string>() ?? "", technicalOrder).ThenBy(pair => pair.Index))
        {
            var uid = pair.Task["uid"]?.GetValue<string>()?.Trim() ?? "";
            if (!reserved.Contains(uid) || !used.Add(uid))
            {
                var id = pair.Task["id"]?.GetValue<string>() ?? "";
                var attempt = nextAttempt.GetValueOrDefault(id);
                do
                {
                    var suffix = attempt == 0 ? "" : (attempt - 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
                    uid = StableTaskUid(id, suffix);
                    attempt++;
                } while (reserved.Contains(uid) || !used.Add(uid));
                nextAttempt[id] = attempt;
            }
            pair.Task["uid"] = uid;
        }
        var byUid = values.ToDictionary(task => task["uid"]!.GetValue<string>(), StringComparer.Ordinal);
        foreach (var pair in values.Select((task, index) => (Task: task, Index: index)))
        {
            var raw = pair.Task["elternUid"]?.GetValue<string>()?.Trim() ?? "";
            byUid.TryGetValue(raw, out var parent);
            if (parent is null && old.TryGetValue(raw, out var matches) && matches.Length == 1) parent = matches[0];
            pair.Task["elternUid"] = parent is not null && !ReferenceEquals(parent, pair.Task) ? parent["uid"]!.GetValue<string>() : "";
            pair.Task["reihenfolge"] = pair.Task["reihenfolge"] is JsonValue order && order.TryGetValue<int>(out var number) && number >= 0 ? number : pair.Index;
        }
        var done = new HashSet<string>(StringComparer.Ordinal);
        foreach (var start in values)
        {
            var path = new List<JsonObject>(); var positions = new Dictionary<string, int>(StringComparer.Ordinal); JsonObject? current = start;
            while (current is not null && !done.Contains(current["uid"]!.GetValue<string>()) && !positions.ContainsKey(current["uid"]!.GetValue<string>()))
            {
                var uid = current["uid"]!.GetValue<string>(); positions[uid] = path.Count; path.Add(current);
                byUid.TryGetValue(current["elternUid"]!.GetValue<string>(), out current);
            }
            if (current is not null && positions.TryGetValue(current["uid"]!.GetValue<string>(), out var at))
                path.Skip(at).MinBy(task => task["uid"]!.GetValue<string>(), technicalOrder)!["elternUid"] = "";
            foreach (var task in path) done.Add(task["uid"]!.GetValue<string>());
        }
        foreach (var group in values.GroupBy(task => task["elternUid"]!.GetValue<string>(), StringComparer.Ordinal))
            foreach (var pair in group.OrderBy(task => task["reihenfolge"]!.GetValue<int>()).ThenBy(task => task["uid"]!.GetValue<string>(), technicalOrder).Select((task, index) => (Task: task, Index: index)))
                pair.Task["reihenfolge"] = pair.Index;
    }

    internal static string StableTaskUid(string id, string salt)
    {
        var bytes = Encoding.UTF8.GetBytes("magnolie-task-v1\0" + id + "\0" + salt);
        uint first = 2166136261, second = 2166136261;
        unchecked
        {
            foreach (var value in bytes) first = (first ^ value) * 16777619;
            for (var index = bytes.Length - 1; index >= 0; index--) second = (second ^ bytes[index]) * 16777619;
        }
        return $"mag-task-{first:x8}{second:x8}@magnolie-organizer";
    }

    private static int CountDataUrls(JsonNode node, string field)
    {
        var count = 0;
        if (node is JsonObject obj)
        {
            foreach (var pair in obj)
            {
                if (pair.Key == field && pair.Value is JsonValue value && value.TryGetValue<string>(out var text) &&
                    text.StartsWith("data:", StringComparison.OrdinalIgnoreCase)) count++;
                if (pair.Value is not null) count += CountDataUrls(pair.Value, field);
            }
        }
        else if (node is JsonArray array)
            foreach (var value in array) if (value is not null) count += CountDataUrls(value, field);
        return count;
    }

    private static string Text(JsonObject root, string name) => root[name]?.GetValue<string>() ?? "";
    private static int Integer(JsonObject root, string name) => root[name]?.GetValue<int>() ?? -1;
}
