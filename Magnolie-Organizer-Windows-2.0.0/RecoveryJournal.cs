using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal enum SnapshotReason
{
    Periodic, Manual, PreSync, PreContact, PreContactImport, PreContactMerge, PreContactDelete, PreRestore
}

internal sealed record SnapshotInfo(
    string Id, DateTimeOffset CreatedUtc, string Reason, long Size, string Hash,
    string SyncEpoch, JsonObject Summary, bool Encrypted, bool Pinned, string Directory);

internal sealed record RecoverySchedule(string Interval, DateTimeOffset? Last, DateTimeOffset? Next,
    string Status, string Error);

internal sealed class RecoveryJournal
{
    internal const string Marker = "magnolie-snapshot";
    internal const int FormatVersion = 1;
    private const string RestoreLeaseFile = ".restore-lease";
    private const long OneGiB = 1024L * 1024 * 1024;
    private static readonly JsonSerializerOptions Indented = new() { WriteIndented = true };
    private readonly string root;
    private readonly string settingsPath;
    private readonly AtomicStore store;
    private readonly Func<DateTimeOffset> clock;

    internal RecoveryJournal(string root, string settingsPath, AtomicStore? store = null,
        Func<DateTimeOffset>? clock = null)
    {
        this.root = Path.GetFullPath(root);
        this.settingsPath = settingsPath;
        this.store = store ?? new AtomicStore();
        this.clock = clock ?? (() => DateTimeOffset.UtcNow);
    }

    internal SnapshotInfo Create(JsonObject data, SnapshotReason reason, string appVersion,
        Func<string, string>? protect = null, string? syncEpoch = null)
        => Create(data, reason, appVersion, protect, syncEpoch, restoreLease: false);

    internal SnapshotInfo CreateRestorePoint(JsonObject data, string appVersion,
        Func<string, string>? protect = null, string? syncEpoch = null)
        => Create(data, SnapshotReason.PreRestore, appVersion, protect, syncEpoch, restoreLease: true);

    private SnapshotInfo Create(JsonObject data, SnapshotReason reason, string appVersion,
        Func<string, string>? protect, string? syncEpoch, bool restoreLease)
    {
        EnsureSafeRoot();
        var now = clock().ToUniversalTime();
        var reasonText = ReasonText(reason);
        var archive = GesamtarchivService.Create(data, "windows", appVersion, created: now);
        var sourceHash = Sha256(archive);
        SnapshotInfo? duplicate = null;
        foreach (var item in List().Where(item => item.Reason == reasonText &&
                     now - item.CreatedUtc <= TimeSpan.FromMinutes(15) && SourceHash(item.Directory) == sourceHash))
        {
            try { duplicate = Verify(item.Id); break; }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException)
            {
                try { Delete(item.Id); }
                catch (Exception deleteError) when (deleteError is IOException or UnauthorizedAccessException) { }
            }
        }
        if (duplicate is not null)
        {
            if (!restoreLease) return duplicate;
            WriteRestoreLease(duplicate.Directory);
            try { return ParseManifest(duplicate.Directory, verifyPayload: true); }
            catch
            {
                File.Delete(Path.Combine(duplicate.Directory, RestoreLeaseFile));
                throw;
            }
        }

        var payload = protect is null ? archive : protect(archive);
        var payloadBytes = Encoding.UTF8.GetBytes(payload);
        var id = Guid.NewGuid().ToString();
        var finalDirectory = Child(id);
        var temporary = Child("." + id + ".tmp");
        Directory.CreateDirectory(temporary);
        try
        {
            RejectReparseTree(temporary);
            WriteNew(Path.Combine(temporary, "payload.magnolie"), payloadBytes);
            var summary = Summary(data);
            var epoch = string.IsNullOrWhiteSpace(syncEpoch) ? DataEpoch(data) : syncEpoch!;
            var manifest = new JsonObject
            {
                ["format"] = Marker, ["version"] = FormatVersion, ["id"] = id,
                ["createdUtc"] = now.ToString("O"), ["platform"] = "windows",
                ["appVersion"] = appVersion, ["reason"] = reasonText,
                ["payload"] = new JsonObject
                {
                    ["file"] = "payload.magnolie", ["sha256"] = Sha256(payloadBytes),
                    ["size"] = payloadBytes.LongLength, ["schema"] = GesamtarchivService.Datenschema,
                    ["encrypted"] = protect is not null, ["sourceSha256"] = sourceHash
                },
                ["summary"] = summary.DeepClone(), ["syncEpoch"] = epoch
            };
            WriteNew(Path.Combine(temporary, "manifest.json"),
                Encoding.UTF8.GetBytes(manifest.ToJsonString(Indented)));
            if (restoreLease) WriteRestoreLease(temporary);
            Directory.Move(temporary, finalDirectory);
            var result = ParseManifest(finalDirectory, verifyPayload: true);
            Prune();
            return result;
        }
        catch
        {
            if (Directory.Exists(temporary)) Directory.Delete(temporary, true);
            if (restoreLease && Directory.Exists(finalDirectory))
                File.Delete(Path.Combine(finalDirectory, RestoreLeaseFile));
            throw;
        }
    }

    internal IReadOnlyList<SnapshotInfo> List()
    {
        if (!Directory.Exists(root)) return Array.Empty<SnapshotInfo>();
        RejectReparseTree(root);
        RecoverInterruptedRewrites();
        var result = new List<SnapshotInfo>();
        foreach (var directory in Directory.EnumerateDirectories(root))
        {
            if (Path.GetFileName(directory).StartsWith(".", StringComparison.Ordinal)) continue;
            try { result.Add(ParseManifest(directory, verifyPayload: false)); }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException) { }
        }
        return result.OrderByDescending(item => item.CreatedUtc).ToArray();
    }

    internal SnapshotInfo Verify(string id) => ParseManifest(Child(ValidId(id)), verifyPayload: true);

    internal string ReadPayload(string id)
    {
        var info = Verify(id);
        return store.Read(Path.Combine(info.Directory, "payload.magnolie"), AtomicStore.MaxArchiveBytes)
            ?? throw new InvalidDataException("Der Snapshot-Payload fehlt.");
    }

    internal (int Changed, int Failed) RewritePayloads(Func<string, bool, string> rewrite)
    {
        EnsureSafeRoot();
        var changed = 0; var failed = 0;
        foreach (var item in List())
        {
            var replacement = Child($".{item.Id}.rewrite-new");
            var previous = Child($".{item.Id}.rewrite-old");
            try
            {
                var manifestPath = Path.Combine(item.Directory, "manifest.json");
                var original = ReadPayload(item.Id);
                var rewritten = rewrite(original, item.Encrypted);
                if (rewritten == original) continue;
                var bytes = Encoding.UTF8.GetBytes(rewritten);
                var manifest = JsonNode.Parse(store.Read(manifestPath, 1024 * 1024)!)!.AsObject();
                var payload = manifest["payload"]!.AsObject();
                payload["sha256"] = Sha256(bytes); payload["size"] = bytes.LongLength;
                payload["encrypted"] = EncryptionService.IsEncrypted(rewritten);
                Directory.CreateDirectory(replacement);
                store.Write(Path.Combine(replacement, "payload.magnolie"), rewritten, AtomicStore.MaxArchiveBytes);
                store.Write(Path.Combine(replacement, "manifest.json"), manifest.ToJsonString(Indented), 1024 * 1024);
                Directory.Move(item.Directory, previous);
                Directory.Move(replacement, item.Directory);
                _ = Verify(item.Id);
                Directory.Delete(previous, true);
                changed++;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or
                                           JsonException or CryptographicException)
            {
                RecoverInterruptedRewrite(item.Id);
                failed++;
            }
            finally
            {
                if (Directory.Exists(replacement)) Directory.Delete(replacement, true);
            }
        }
        return (changed, failed);
    }

    private void RecoverInterruptedRewrites()
    {
        foreach (var previous in Directory.EnumerateDirectories(root, ".*.rewrite-old"))
        {
            var name = Path.GetFileName(previous);
            RecoverInterruptedRewrite(ValidId(name[1..^12]));
        }
    }

    private void RecoverInterruptedRewrite(string id)
    {
        var directory = Child(id);
        var replacement = Child($".{id}.rewrite-new");
        var previous = Child($".{id}.rewrite-old");
        if (Directory.Exists(previous))
        {
            var currentValid = false;
            if (Directory.Exists(directory))
            {
                try { _ = ParseManifest(directory, verifyPayload: true); currentValid = true; }
                catch (Exception error) when (error is IOException or InvalidDataException or JsonException) { }
            }
            if (currentValid) Directory.Delete(previous, true);
            else
            {
                if (Directory.Exists(directory)) Directory.Delete(directory, true);
                Directory.Move(previous, directory);
            }
        }
        if (Directory.Exists(replacement)) Directory.Delete(replacement, true);
    }

    internal void Delete(string id)
    {
        var directory = Child(ValidId(id));
        if (!Directory.Exists(directory)) return;
        RejectReparseTree(directory);
        Directory.Delete(directory, true);
    }

    internal void ReleaseRestoreLease(string id)
    {
        var directory = Child(ValidId(id));
        if (!Directory.Exists(directory)) return;
        RejectReparseTree(directory);
        File.Delete(Path.Combine(directory, RestoreLeaseFile));
    }

    internal int ReleaseAbandonedRestoreLeases()
    {
        var released = 0;
        foreach (var item in List().Where(item => File.Exists(Path.Combine(item.Directory, RestoreLeaseFile))))
        {
            ReleaseRestoreLease(item.Id);
            released++;
        }
        return released;
    }

    internal RecoverySchedule Schedule()
    {
        var settings = ReadSettings();
        var interval = Interval(settings["interval"]?.GetValue<string>() ?? "weekly");
        var last = ParseDate(settings["last"]?.GetValue<string>());
        DateTimeOffset? next = interval == "off" ? null : (last ?? DateTimeOffset.MinValue) + Duration(interval);
        return new RecoverySchedule(interval, last, next, interval == "off" ? "off" :
            next <= clock() ? "due" : "scheduled", settings["error"]?.GetValue<string>() ?? "");
    }

    internal RecoverySchedule SetInterval(string interval)
    {
        interval = Interval(interval);
        var settings = ReadSettings();
        settings["interval"] = interval;
        WriteSettings(settings);
        return Schedule();
    }

    internal bool IsDue() => Schedule() is { Interval: not "off", Next: not null } schedule && schedule.Next.Value <= clock();

    internal void RecordPeriodicResult(bool success, string error = "")
    {
        var settings = ReadSettings();
        if (success) settings["last"] = clock().ToUniversalTime().ToString("O");
        settings["error"] = success ? "" : error;
        WriteSettings(settings);
    }

    internal void Prune(long? availableBytes = null, long? volumeBytes = null)
    {
        var all = List().OrderByDescending(item => item.CreatedUtc).ToList();
        var now = clock();
        var keep = new HashSet<string>(all.Where(item => item.Pinned).Select(item => item.Id));
        foreach (var item in all.Where(item => item.Reason == "pre-sync" || item.Reason.StartsWith("pre-contact", StringComparison.Ordinal))
                     .Where(item => now - item.CreatedUtc <= TimeSpan.FromDays(14)).Take(20)) keep.Add(item.Id);
        foreach (var item in all.Where(item => item.Reason == "pre-restore").Take(5))
            if (now - item.CreatedUtc <= TimeSpan.FromDays(30) || !keep.Any(id => all.Any(x => x.Id == id && x.Reason == "pre-restore"))) keep.Add(item.Id);

        var periodic = all.Where(item => item.Reason == "weekly").ToList();
        foreach (var item in periodic.GroupBy(item => $"{item.CreatedUtc:yyyy}-W{System.Globalization.ISOWeek.GetWeekOfYear(item.CreatedUtc.UtcDateTime):00}")
                     .Select(group => group.First()).Take(8)) keep.Add(item.Id);
        foreach (var item in periodic.GroupBy(item => item.CreatedUtc.ToString("yyyy-MM"))
                     .Select(group => group.First()).Take(6)) keep.Add(item.Id);

        foreach (var item in all.Where(item => !keep.Contains(item.Id))) Delete(item.Id);
        all = List().OrderBy(item => item.CreatedUtc).ToList();
        var drive = new DriveInfo(Path.GetPathRoot(root)!);
        var available = availableBytes ?? drive.AvailableFreeSpace;
        var volume = volumeBytes ?? drive.TotalSize;
        var budget = Math.Min(OneGiB, volume / 20);
        var used = all.Sum(item => item.Size);
        foreach (var item in all.Where(item => !item.Pinned))
        {
            if (used <= budget && available >= OneGiB) break;
            Delete(item.Id); used -= item.Size; available += item.Size;
        }
    }

    private SnapshotInfo ParseManifest(string directory, bool verifyPayload)
    {
        EnsureContained(directory);
        RejectReparseTree(directory);
        var manifestText = store.Read(Path.Combine(directory, "manifest.json"), 1024 * 1024)
            ?? throw new InvalidDataException("Das Snapshot-Manifest fehlt.");
        var rootNode = JsonNode.Parse(manifestText) as JsonObject ?? throw new InvalidDataException("Das Snapshot-Manifest ist ungültig.");
        if (rootNode["format"]?.GetValue<string>() != Marker || rootNode["version"]?.GetValue<int>() != FormatVersion ||
            rootNode["platform"]?.GetValue<string>() != "windows") throw new InvalidDataException("Das Snapshot-Format wird nicht unterstützt.");
        var id = ValidId(rootNode["id"]?.GetValue<string>() ?? "");
        if (!Path.GetFileName(directory).Equals(id, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Snapshot-ID und Verzeichnis stimmen nicht überein.");
        var created = DateTimeOffset.Parse(rootNode["createdUtc"]?.GetValue<string>() ?? "", null,
            System.Globalization.DateTimeStyles.RoundtripKind).ToUniversalTime();
        var payload = rootNode["payload"] as JsonObject ?? throw new InvalidDataException("Die Payload-Angaben fehlen.");
        if (payload["file"]?.GetValue<string>() != "payload.magnolie" || payload["schema"]?.GetValue<int>() != GesamtarchivService.Datenschema)
            throw new InvalidDataException("Das Payload-Schema wird nicht unterstützt.");
        var size = payload["size"]?.GetValue<long>() ?? -1;
        var hash = payload["sha256"]?.GetValue<string>() ?? "";
        if (verifyPayload)
        {
            var bytes = File.ReadAllBytes(Path.Combine(directory, "payload.magnolie"));
            if (bytes.LongLength != size || !FixedHash(hash, Sha256(bytes))) throw new InvalidDataException("Der Snapshot wurde verändert oder beschädigt.");
        }
        var reason = rootNode["reason"]?.GetValue<string>() ?? "";
        if (reason == "periodic") reason = "weekly";
        return new SnapshotInfo(id, created, reason, size, hash, rootNode["syncEpoch"]?.GetValue<string>() ?? "",
            (rootNode["summary"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject(),
            payload["encrypted"]?.GetValue<bool>() ?? false,
            reason == "manual" || File.Exists(Path.Combine(directory, RestoreLeaseFile)), directory);
    }

    private void EnsureSafeRoot()
    {
        Directory.CreateDirectory(root);
        RejectReparseTree(root);
    }

    private string Child(string name)
    {
        var result = Path.GetFullPath(Path.Combine(root, name));
        EnsureContained(result);
        return result;
    }

    private void EnsureContained(string path)
    {
        var prefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!Path.GetFullPath(path).StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Der Snapshot-Pfad verlässt das private App-Verzeichnis.");
    }

    private static void RejectReparseTree(string path)
    {
        for (var current = new DirectoryInfo(Path.GetFullPath(path)); current is not null; current = current.Parent)
            if ((current.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Reparse Points sind im Wiederherstellungsjournal nicht zulässig.");
        if (!Directory.Exists(path)) return;
        foreach (var entry in Directory.EnumerateFileSystemEntries(path, "*", SearchOption.AllDirectories))
            if ((File.GetAttributes(entry) & FileAttributes.ReparsePoint) != 0) throw new IOException("Reparse Points sind im Wiederherstellungsjournal nicht zulässig.");
    }

    private static void WriteNew(string path, byte[] bytes)
    {
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 64 * 1024, FileOptions.WriteThrough);
        stream.Write(bytes); stream.Flush(true);
    }

    private static void WriteRestoreLease(string directory)
    {
        var path = Path.Combine(directory, RestoreLeaseFile);
        if (!File.Exists(path)) WriteNew(path, Encoding.ASCII.GetBytes("restore\n"));
    }

    private JsonObject ReadSettings()
    {
        try { return JsonNode.Parse(store.ReadRecoverableJson(settingsPath, 64 * 1024) ?? "{}") as JsonObject ?? new JsonObject(); }
        catch (Exception error) when (error is JsonException or InvalidDataException or IOException or UnauthorizedAccessException)
        { return new JsonObject { ["interval"] = "off", ["error"] = "Die Einstellungen des Wiederherstellungsjournals sind beschädigt." }; }
    }

    private void WriteSettings(JsonObject settings) => store.WriteRecoverableJson(settingsPath, settings.ToJsonString(Indented), 64 * 1024);
    private static DateTimeOffset? ParseDate(string? value) => DateTimeOffset.TryParse(value, out var result) ? result.ToUniversalTime() : null;
    private static string Interval(string value) => value is "off" or "6h" or "12h" or "daily" or "weekly" ? value : "weekly";
    private static TimeSpan Duration(string value) => value switch { "6h" => TimeSpan.FromHours(6), "12h" => TimeSpan.FromHours(12), "daily" => TimeSpan.FromDays(1), _ => TimeSpan.FromDays(7) };
    private static string ReasonText(SnapshotReason reason) => reason switch
    {
        SnapshotReason.Periodic => "weekly", SnapshotReason.Manual => "manual", SnapshotReason.PreSync => "pre-sync",
        SnapshotReason.PreContact => "pre-contact", SnapshotReason.PreContactImport => "pre-contact-import",
        SnapshotReason.PreContactMerge => "pre-contact-merge", SnapshotReason.PreContactDelete => "pre-contact-delete",
        _ => "pre-restore"
    };
    private static string ValidId(string value) => Guid.TryParse(value, out var id) ? id.ToString() : throw new InvalidDataException("Die Snapshot-ID ist ungültig.");
    private static string Sha256(string text) => Sha256(Encoding.UTF8.GetBytes(text));
    private static string Sha256(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static bool FixedHash(string left, string right) => left.Length == 64 && CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(left.ToLowerInvariant()), Encoding.ASCII.GetBytes(right));
    private static string DataEpoch(JsonObject data) => data["syncEpoch"]?.GetValue<string>() ?? "legacy";
    private static string SourceHash(string directory)
    {
        try { return (JsonNode.Parse(File.ReadAllText(Path.Combine(directory, "manifest.json")))?["payload"]?["sourceSha256"]?.GetValue<string>()) ?? ""; }
        catch { return ""; }
    }

    private static JsonObject Summary(JsonObject data)
    {
        var result = new JsonObject();
        foreach (var name in new[] { "termine", "aufgaben", "kontakte", "notizen", "jahrestage", "papierkorb", "tombstones" })
            result[name] = data[name] is JsonArray values ? values.Count : 0;
        return result;
    }
}

internal static class MutationGate
{
    internal static readonly SemaphoreSlim Global = new(1, 1);
}

internal static class RestoreSyncState
{
    internal static string Prepare(JsonObject data, DateTimeOffset? now = null)
    {
        var epoch = Guid.NewGuid().ToString();
        data["syncEpoch"] = epoch;
        data["syncNachRestore"] = new JsonObject { ["additiv"] = true, ["loeschungsfrei"] = true,
            ["erstelltUtc"] = (now ?? DateTimeOffset.UtcNow).ToUniversalTime().ToString("O") };
        if (data["geloescht"] is JsonObject deleted)
        {
            data["quarantaeneTombstones"] = deleted.DeepClone();
            data["geloescht"] = new JsonObject { ["termine"] = new JsonArray(), ["kontakte"] = new JsonArray() };
        }
        return epoch;
    }
}
