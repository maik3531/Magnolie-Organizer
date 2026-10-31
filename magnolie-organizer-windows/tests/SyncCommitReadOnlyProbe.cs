using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Diagnoses only the already saved product transaction. No provider or journal writes.
internal static class SyncCommitReadOnlyProbe
{
    internal static async Task<int> RunAsync(string transaction, string receipt)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (transaction.Length != 64 || transaction.Any(c => !Uri.IsHexDigit(c)) || File.Exists(receipt))
            throw new ArgumentException("Exact existing transaction and new receipt required.");
        var paths = new WindowsPaths();
        var journal = new NextcloudSyncJournal(paths.NextcloudSyncJournal + "." + transaction).Load();
        var output = new JsonObject { ["writes"] = false, ["journalFound"] = journal is not null,
            ["phase"] = journal?.Phase, ["transactionMatches"] = journal?.Id == transaction };
        if (journal is not null)
        {
            var text = new AtomicStore().Read(paths.Data) ?? throw new InvalidDataException("No saved book.");
            if (EncryptionService.IsEncrypted(text)) throw new InvalidOperationException("Encrypted source requires the existing product session.");
            var saved = JsonNode.Parse(text)!.AsObject(); var result = journal.Value.Payload.DeepClone().AsObject();
            output["containsSavedResult"] = SyncBaseline.ContainsSavedResult(result, saved);
            output["epochMatches"] = JsonNode.DeepEquals(result["syncEpoch"], saved["syncEpoch"]);
            output["handoffBeforePresent"] = result["syncAbgleichBasis"] is JsonObject;
            output["handoffProofPresent"] = saved["syncAbgleichNachweis"] is JsonObject;
            if (result["syncAbgleichBasis"] is JsonObject before && saved["syncAbgleichNachweis"] is JsonObject local)
            {
                output["handoffTransactionMatches"] = JsonNode.DeepEquals(result["transactionId"], local["transactionId"]);
                var reconcile = typeof(SyncBaseline).GetMethod("Reconcile", BindingFlags.Static | BindingFlags.NonPublic)!;
                foreach (var field in new[] { "termine", "aufgaben", "kontakte", "jahrestage" })
                    if (before[field] is JsonArray a && local[field] is JsonArray b && result[field] is JsonArray c)
                        result[field] = (JsonArray)reconcile.Invoke(null, [a, b, c])!;
                foreach (var field in new[] { "termine", "aufgaben", "kontakte" })
                    if (before["geloescht"]?[field] is JsonArray a && local["geloescht"]?[field] is JsonArray b && result["geloescht"]?[field] is JsonArray c)
                        result["geloescht"]![field] = (JsonArray)reconcile.Invoke(null, [a, b, c])!;
            }
            var compare = typeof(SyncBaseline).GetMethods(BindingFlags.Static | BindingFlags.NonPublic)
                .Single(method => method.Name.StartsWith("<ContainsSavedResult>g__Contains|", StringComparison.Ordinal));
            bool Contains(JsonNode? expected, JsonNode? actual) => (bool)compare.Invoke(null, [expected, actual])!;
            var checks = new JsonObject(); var mismatches = new JsonArray();
            foreach (var field in new[] { "termine", "aufgaben", "kontakte", "jahrestage", "geloescht", "letzterSync", "letzteSyncs", "syncMetadaten" })
            {
                var valid = result.ContainsKey(field) && saved.ContainsKey(field) && Contains(result[field], saved[field]);
                checks[field] = valid;
                if (valid) continue;
                void Inspect(JsonNode? expected, JsonNode? actual, string path, int depth)
                {
                    if (mismatches.Count >= 32 || depth > 10 || Contains(expected, actual)) return;
                    if (expected is JsonObject obj && actual is JsonObject other)
                    {
                        foreach (var pair in obj) Inspect(pair.Value, other[pair.Key], path + "." + pair.Key, depth + 1);
                    }
                    else if (expected is JsonArray array && actual is JsonArray otherArray && array.Count == otherArray.Count)
                    {
                        for (var i = 0; i < array.Count; i++) Inspect(array[i], otherArray[i], path + "[" + i + "]", depth + 1);
                    }
                    else mismatches.Add(new JsonObject { ["path"] = path, ["expectedKind"] = expected?.GetValueKind().ToString() ?? "missing",
                        ["actualKind"] = actual?.GetValueKind().ToString() ?? "missing",
                        ["expectedCount"] = (expected as JsonArray)?.Count, ["actualCount"] = (actual as JsonArray)?.Count });
                }
                Inspect(result[field], saved[field], field, 0);
            }
            output["requiredFieldChecks"] = checks; output["mismatchPaths"] = mismatches;
        }
        await File.WriteAllTextAsync(receipt, output.ToJsonString());
        Console.WriteLine(new JsonObject { ["writes"] = false, ["journalFound"] = journal is not null }.ToJsonString());
        return 0;
    }
}
