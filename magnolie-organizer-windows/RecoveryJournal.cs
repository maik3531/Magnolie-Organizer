using System.Security.Cryptography;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal enum SnapshotReason
{
    Periodic, Manual, PreChange, PreSync, PreContact, PreContactImport, PreContactMerge, PreContactDelete, PreRestore
}

internal sealed record SnapshotInfo(
    string Id, DateTimeOffset CreatedUtc, string Reason, long Size, string Hash,
    string SyncEpoch, JsonObject Summary, bool Encrypted, bool Pinned, string Integrity,
    string PayloadFile, string Directory);

internal sealed record RecoverySchedule(string Interval, DateTimeOffset? Last, DateTimeOffset? Next,
    string Mode, int Maximum, int Days, string Status, string Error);

internal sealed class RecoveryJournal
{
    internal const string Marker = "magnolie-snapshot";
    internal const int FormatVersion = 1;
    private const string RestoreLeaseFile = ".restore-lease";
    private const string PayloadFile = "payload.magnolie";
    private const string CompressedPayloadFile = "payload.magnolie.tar.xz";
    private const long OneGiB = 1024L * 1024 * 1024;
    private static readonly JsonSerializerOptions Indented = new() { WriteIndented = true };
    private readonly string root;
    private readonly string settingsPath;
    private readonly AtomicStore store;
    private readonly Func<DateTimeOffset> clock;
    private readonly object gate = new();

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
    {
        lock (gate) return Create(data, reason, appVersion, protect, syncEpoch, restoreLease: false);
    }

    internal static bool HasRecoverableChanges(JsonObject previous, JsonObject proposed)
    {
        // Full snapshots still retain settings and sync state. Only the automatic
        // pre-change trigger ignores bookkeeping that does not change user content.
        foreach (var name in previous.Select(item => item.Key).Union(proposed.Select(item => item.Key)))
        {
            if (name is "einstellungen" or "letzterSync" or "letzteSyncs" or "syncStatus" or
                "syncMetadaten" or "syncEpoch" or "syncNachRestore" or "syncAbgleichBasis" or
                "personalSync" or "baumKontaktBestand" or "baumKontaktErfolgreich" or "baumKontaktLoeschStaende") continue;
            if (name is "kontakte" or "jahrestage" or "notizen" or "aufgaben" or "termine" &&
                previous[name] is JsonArray before && proposed[name] is JsonArray after)
            {
                if (before.Count != after.Count || !before.Zip(after).All(pair => SameContent(pair.First, pair.Second))) return true;
                continue;
            }
            if (!JsonNode.DeepEquals(previous[name], proposed[name])) return true;
        }
        return false;

        static bool SameContent(JsonNode? before, JsonNode? after)
        {
            if (before is not JsonObject left || after is not JsonObject right) return JsonNode.DeepEquals(before, after);
            return left.Select(item => item.Key).Union(right.Select(item => item.Key)).All(field =>
                field is "uid" or "geaendert" or "angelegt" or "personalGeaendert" or "sync" or "syncQuellen" or
                    "syncKalenderUid" or "davHref" or "davEtag" or "baumKontakt" or "baumFreigabe" or
                    "baumVersion" or "baumQuelle" or "baumGeaendert" or "baumInhaltVersion" or "importBindungen" or "importHerkunfte" or
                    "importKonflikt" or "icsSequence" or "icsAenderungszeitFehlt" || JsonNode.DeepEquals(left[field], right[field]));
        }
    }

    internal SnapshotInfo CreateRestorePoint(JsonObject data, string appVersion,
        Func<string, string>? protect = null, string? syncEpoch = null)
    {
        lock (gate) return Create(data, SnapshotReason.PreRestore, appVersion, protect, syncEpoch, restoreLease: true);
    }

    private SnapshotInfo Create(JsonObject data, SnapshotReason reason, string appVersion,
        Func<string, string>? protect, string? syncEpoch, bool restoreLease)
    {
        EnsureSafeRoot();
        var now = clock().ToUniversalTime();
        var reasonText = ReasonText(reason);
        var snapshotData = data.DeepClone().AsObject();
        var archive = GesamtarchivService.Create(snapshotData, "windows", appVersion, created: now);
        // Hash the normalized content, not the archive envelope's changing timestamp.
        var sourceHash = JsonNode.Parse(archive)!["sha256"]!.GetValue<string>();
        SnapshotInfo? duplicate = null;
        foreach (var item in List().Where(item => (item.Reason == reasonText ||
                     reason == SnapshotReason.PreChange && item.Reason is "pre-sync" or "pre-contact" or "pre-contact-import" or "pre-contact-merge" or "pre-contact-delete") &&
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
        var drive = new DriveInfo(Path.GetPathRoot(root)!);
        var protectedBytes = List().Where(item => item.Pinned || item.Integrity != "ok").Sum(item => item.Size);
        if (payloadBytes.LongLength > AtomicStore.MaxArchiveBytes ||
            protectedBytes + payloadBytes.LongLength > Math.Min(OneGiB, drive.TotalSize / 20) ||
            drive.AvailableFreeSpace - payloadBytes.LongLength < OneGiB)
            throw new IOException(NativeLocalization.Gettext("The required recovery snapshot could not be created."));
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
            // Protect the just-created point through pruning, even when all count slots are pinned.
            WriteRestoreLease(temporary);
            Directory.Move(temporary, finalDirectory);
            _ = ParseManifest(finalDirectory, verifyPayload: true);
            Prune();
            if (!restoreLease) File.Delete(Path.Combine(finalDirectory, RestoreLeaseFile));
            return ParseManifest(finalDirectory, verifyPayload: true);
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
        lock (gate) return List(verifyPayload: true);
    }

    private IReadOnlyList<SnapshotInfo> List(bool verifyPayload)
    {
        if (!Directory.Exists(root)) return Array.Empty<SnapshotInfo>();
        RejectReparseTree(root);
        if (verifyPayload) RecoverInterruptedRewrites();
        var result = new List<SnapshotInfo>();
        foreach (var directory in Directory.EnumerateDirectories(root))
        {
            if (Path.GetFileName(directory).StartsWith(".", StringComparison.Ordinal)) continue;
            try
            {
                var item = ParseManifest(directory, verifyPayload: false);
                if (verifyPayload)
                {
                    try { item = ParseManifest(directory, verifyPayload: true); }
                    catch (Exception error) when (error is IOException or InvalidDataException or JsonException or UnauthorizedAccessException)
                    { item = item with { Integrity = "damaged" }; }
                }
                result.Add(item);
            }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException or UnauthorizedAccessException)
            {
                if (Guid.TryParse(Path.GetFileName(directory), out var id))
                    result.Add(new SnapshotInfo(id.ToString(), DateTimeOffset.MinValue, "", 0, "", "",
                        new JsonObject(), false, true, "damaged", PayloadFile, directory));
            }
        }
        return result.OrderByDescending(item => item.CreatedUtc).ToArray();
    }

    internal SnapshotInfo Verify(string id)
    {
        lock (gate) return ParseManifest(Child(ValidId(id)), verifyPayload: true);
    }

    internal string ReadPayload(string id)
    {
        lock (gate)
        {
            var info = Verify(id);
            if (info.PayloadFile == PayloadFile)
                return store.Read(Path.Combine(info.Directory, info.PayloadFile), AtomicStore.MaxArchiveBytes)
                    ?? throw new InvalidDataException("Der Snapshot-Payload fehlt.");
            return ExtractPayload(Path.Combine(info.Directory, info.PayloadFile));
        }
    }

    internal (int Changed, int Failed) RewritePayloads(Func<string, bool, string> rewrite)
    {
        lock (gate) return RewritePayloadsCore(rewrite);
    }

    private (int Changed, int Failed) RewritePayloadsCore(Func<string, bool, string> rewrite)
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
                var manifest = JsonNode.Parse(store.Read(manifestPath, 1024 * 1024)!)!.AsObject();
                var payload = manifest["payload"]!.AsObject();
                payload["encrypted"] = EncryptionService.IsEncrypted(rewritten);
                Directory.CreateDirectory(replacement);
                WritePayload(replacement, manifest, rewritten,
                    payload["compression"]?.GetValue<string>() == "xz");
                if (File.Exists(Path.Combine(item.Directory, RestoreLeaseFile))) WriteRestoreLease(replacement);
                store.Write(Path.Combine(replacement, "manifest.json"), manifest.ToJsonString(Indented), 1024 * 1024);
                Directory.Move(item.Directory, previous);
                Directory.Move(replacement, item.Directory);
                _ = Verify(item.Id);
                Directory.Delete(previous, true);
                changed++;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or
                                           JsonException or CryptographicException or System.ComponentModel.Win32Exception)
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
            if (Guid.TryParse(name[1..^12], out var id)) RecoverInterruptedRewrite(id.ToString());
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
        DeleteMany([id]);
    }

    internal int DeleteMany(IEnumerable<string> ids)
    {
        lock (gate)
        {
            var directories = ids.Select(ValidId).Distinct(StringComparer.Ordinal).Select(Child).ToArray();
            if (directories.Length == 0) throw new InvalidDataException(NativeLocalization.Gettext("Select something first."));
            // Validate the entire selection before deleting its first entry.
            foreach (var directory in directories)
                if (Directory.Exists(directory)) RejectReparseTree(directory);
            var deleted = 0;
            foreach (var directory in directories)
            {
                if (!Directory.Exists(directory)) continue;
                Directory.Delete(directory, true);
                deleted++;
            }
            return deleted;
        }
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
        foreach (var item in List(verifyPayload: false).Where(item => File.Exists(Path.Combine(item.Directory, RestoreLeaseFile))))
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
        var mode = Mode(settings);
        var maximum = Maximum(settings);
        var days = Days(settings);
        var last = ParseDate(settings["last"]?.GetValue<string>());
        DateTimeOffset? next = interval == "off" ? null : (last ?? DateTimeOffset.MinValue) + Duration(interval);
        return new RecoverySchedule(interval, last, next, mode, maximum, days, interval == "off" ? "off" :
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

    internal RecoverySchedule SetMaximum(int maximum)
    {
        var settings = ReadSettings();
        settings["mode"] = "count";
        settings["maximum"] = Math.Clamp(maximum, 1, 100);
        WriteSettings(settings);
        Prune();
        return Schedule();
    }

    internal RecoverySchedule SetRetention(string mode, int maximum, int days)
    {
        var settings = ReadSettings();
        settings["mode"] = mode is "count" or "days" ? mode : "count";
        settings["maximum"] = Math.Clamp(maximum, 1, 100);
        settings["days"] = Math.Clamp(days, 1, 3650);
        WriteSettings(settings);
        Prune();
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
        lock (gate) PruneCore(availableBytes, volumeBytes);
    }

    private void PruneCore(long? availableBytes, long? volumeBytes)
    {
        _ = CompressOld();
        var all = List().OrderByDescending(item => item.CreatedUtc).ToList();
        var settings = ReadSettings();
        var protectedItems = all.Where(item => item.Integrity != "ok" || item.Reason == "manual" ||
            File.Exists(Path.Combine(item.Directory, RestoreLeaseFile))).ToList();
        var keep = new HashSet<string>(protectedItems.Select(item => item.Id));
        if (Mode(settings) == "days")
        {
            var cutoff = clock().ToUniversalTime().AddDays(-Days(settings));
            foreach (var item in all.Where(item => item.CreatedUtc >= cutoff)) keep.Add(item.Id);
            if (keep.Count == 0 && all.Count > 0) keep.Add(all[0].Id);
        }
        else
        {
            var freeSlots = Math.Max(0, Maximum(settings) - keep.Count);
            foreach (var item in all.Where(item => !keep.Contains(item.Id)).Take(freeSlots)) keep.Add(item.Id);
            if (freeSlots == 0 && !all.Any(item => item.Integrity == "ok" &&
                    item.Reason != "manual" && keep.Contains(item.Id)))
            {
                var newestAutomatic = all.FirstOrDefault(item => !keep.Contains(item.Id));
                if (newestAutomatic is not null) keep.Add(newestAutomatic.Id);
            }
        }

        foreach (var item in all.Where(item => !keep.Contains(item.Id))) Delete(item.Id);
        all = List().OrderBy(item => item.CreatedUtc).ToList();
        var drive = new DriveInfo(Path.GetPathRoot(root)!);
        var available = availableBytes ?? drive.AvailableFreeSpace;
        var volume = volumeBytes ?? drive.TotalSize;
        var budget = Math.Min(OneGiB, volume / 20);
        var used = all.Sum(item => item.Size);
        foreach (var item in all.Where(item => item.Integrity == "ok" && item.Reason != "manual" &&
                     !File.Exists(Path.Combine(item.Directory, RestoreLeaseFile))))
        {
            if (used <= budget && available >= OneGiB) break;
            Delete(item.Id); used -= item.Size; available += item.Size;
        }
    }

    internal (int Changed, int Failed) CompressOld()
    {
        lock (gate) return CompressOldCore();
    }

    private (int Changed, int Failed) CompressOldCore()
    {
        EnsureSafeRoot();
        var cutoff = clock().ToUniversalTime().AddDays(-365);
        var changed = 0; var failed = 0;
        foreach (var item in List().Where(item => item.Integrity == "ok" &&
                     item.CreatedUtc < cutoff && !IsCompressed(item.Directory)))
        {
            var replacement = Child($".{item.Id}.rewrite-new");
            var previous = Child($".{item.Id}.rewrite-old");
            try
            {
                var original = ReadPayload(item.Id);
                var manifest = ReadManifest(item.Directory);
                Directory.CreateDirectory(replacement);
                WritePayload(replacement, manifest, original, compressed: true);
                var compressedSize = manifest["payload"]!["size"]!.GetValue<long>();
                if (compressedSize >= item.Size)
                {
                    Directory.Delete(replacement, true);
                    continue;
                }
                if (File.Exists(Path.Combine(item.Directory, RestoreLeaseFile))) WriteRestoreLease(replacement);
                store.Write(Path.Combine(replacement, "manifest.json"), manifest.ToJsonString(Indented), 1024 * 1024);
                Directory.Move(item.Directory, previous);
                Directory.Move(replacement, item.Directory);
                _ = Verify(item.Id);
                Directory.Delete(previous, true);
                changed++;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or
                                           JsonException or CryptographicException or System.ComponentModel.Win32Exception)
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

    private SnapshotInfo ParseManifest(string directory, bool verifyPayload)
    {
        try
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
        var payloadFile = payload["file"]?.GetValue<string>() ?? PayloadFile;
        var compression = payload["compression"]?.GetValue<string>();
        if (payloadFile is not (PayloadFile or CompressedPayloadFile) || compression is not (null or "xz") ||
            (compression == "xz") != (payloadFile == CompressedPayloadFile) ||
            payload["schema"]?.GetValue<int>() is not (1 or 2 or GesamtarchivService.Datenschema))
            throw new InvalidDataException("Das Payload-Schema wird nicht unterstützt.");
        var size = payload["size"]?.GetValue<long>() ?? -1;
        var hash = payload["sha256"]?.GetValue<string>() ?? "";
        if (size < 1 || size > AtomicStore.MaxArchiveBytes || !ValidHash(hash))
            throw new InvalidDataException("Die Payload-Angaben sind ungültig.");
        if (verifyPayload)
        {
            var actual = HashFile(Path.Combine(directory, payloadFile));
            if (actual.Size != size || !FixedHash(hash, actual.Hash)) throw new InvalidDataException("Der Snapshot wurde verändert oder beschädigt.");
        }
        var reason = rootNode["reason"]?.GetValue<string>() ?? "";
        if (reason == "periodic") reason = "weekly";
        return new SnapshotInfo(id, created, reason, size, hash, rootNode["syncEpoch"]?.GetValue<string>() ?? "",
            (rootNode["summary"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject(),
            payload["encrypted"]?.GetValue<bool>() ?? false,
            reason == "manual" || File.Exists(Path.Combine(directory, RestoreLeaseFile)),
            verifyPayload ? "ok" : "unchecked", payloadFile, directory);
        }
        catch (Exception error) when (error is FormatException or InvalidOperationException or OverflowException)
        {
            throw new InvalidDataException("Das Snapshot-Manifest ist ungültig.", error);
        }
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
    private JsonObject ReadManifest(string directory) => JsonNode.Parse(
        store.Read(Path.Combine(directory, "manifest.json"), 1024 * 1024)
            ?? throw new InvalidDataException("Das Snapshot-Manifest fehlt."))!.AsObject();

    private static bool IsCompressed(string directory)
    {
        try { return JsonNode.Parse(File.ReadAllText(Path.Combine(directory, "manifest.json")))?
            ["payload"]?["compression"]?.GetValue<string>() == "xz"; }
        catch { return false; }
    }

    private void WritePayload(string directory, JsonObject manifest, string text, bool compressed)
    {
        var payload = manifest["payload"]!.AsObject();
        var plainPath = Path.Combine(directory, PayloadFile);
        store.Write(plainPath, text, AtomicStore.MaxArchiveBytes);
        var storedPath = plainPath;
        if (compressed)
        {
            storedPath = Path.Combine(directory, CompressedPayloadFile);
            RunTar(directory, "-cJf", storedPath, "-C", directory, "--", PayloadFile);
            File.Delete(plainPath);
            payload["file"] = CompressedPayloadFile;
            payload["compression"] = "xz";
        }
        else
        {
            payload["file"] = PayloadFile;
            payload.Remove("compression");
        }
        var stored = HashFile(storedPath);
        payload["sha256"] = stored.Hash;
        payload["size"] = stored.Size;
    }

    private string ExtractPayload(string archive)
    {
        var temporary = Child($".extract-{Guid.NewGuid():N}");
        Directory.CreateDirectory(temporary);
        try
        {
            var output = Path.Combine(temporary, PayloadFile);
            ExtractTarPayload(temporary, archive, output);
            return store.Read(output, AtomicStore.MaxArchiveBytes)
                ?? throw new InvalidDataException("Der Snapshot-Payload fehlt.");
        }
        finally { if (Directory.Exists(temporary)) Directory.Delete(temporary, true); }
    }

    private static void ExtractTarPayload(string workingDirectory, string archive, string output)
    {
        var start = new ProcessStartInfo(OperatingSystem.IsWindows() ? Path.Combine(Environment.SystemDirectory, "tar.exe") : "/usr/bin/tar") { WorkingDirectory = workingDirectory,
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var argument in new[] { "-xJOf", archive, "--", PayloadFile }) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw new IOException("XZ-Dekomprimierung konnte nicht gestartet werden.");
        var errorTask = process.StandardError.ReadToEndAsync();
        try
        {
            using var target = new FileStream(output, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            var buffer = new byte[64 * 1024];
            long total = 0;
            int read;
            while ((read = process.StandardOutput.BaseStream.Read(buffer, 0, buffer.Length)) > 0)
            {
                total += read;
                if (total > AtomicStore.MaxArchiveBytes)
                {
                    process.Kill(entireProcessTree: true);
                    throw new InvalidDataException("Der dekomprimierte Snapshot-Payload ist zu groß.");
                }
                target.Write(buffer, 0, read);
            }
        }
        finally { process.WaitForExit(); }
        var error = errorTask.GetAwaiter().GetResult();
        if (process.ExitCode != 0) throw new IOException("XZ-Dekomprimierung ist fehlgeschlagen: " + error.Trim());
    }

    private static void RunTar(string workingDirectory, params string[] arguments)
    {
        var start = new ProcessStartInfo(OperatingSystem.IsWindows() ? Path.Combine(Environment.SystemDirectory, "tar.exe") : "/usr/bin/tar") { WorkingDirectory = workingDirectory,
            UseShellExecute = false, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw new IOException("XZ-Komprimierung konnte nicht gestartet werden.");
        var error = process.StandardError.ReadToEnd();
        process.WaitForExit();
        if (process.ExitCode != 0) throw new IOException("XZ-Komprimierung ist fehlgeschlagen: " + error.Trim());
    }
    private static string Mode(JsonObject settings) => settings["mode"] is JsonValue value &&
        value.TryGetValue<string>(out var mode) && mode == "count" ? "count" : "days";
    private static int Maximum(JsonObject settings) => settings["maximum"] is JsonValue value &&
        value.TryGetValue<int>(out var maximum) ? Math.Clamp(maximum, 1, 100) : 20;
    private static int Days(JsonObject settings) => settings["days"] is JsonValue value &&
        value.TryGetValue<int>(out var days) ? Math.Clamp(days, 1, 3650) : 3650;
    private static DateTimeOffset? ParseDate(string? value) => DateTimeOffset.TryParse(value, out var result) ? result.ToUniversalTime() : null;
    private static string Interval(string value) => value is "off" or "6h" or "12h" or "daily" or "weekly" ? value : "weekly";
    private static TimeSpan Duration(string value) => value switch { "6h" => TimeSpan.FromHours(6), "12h" => TimeSpan.FromHours(12), "daily" => TimeSpan.FromDays(1), _ => TimeSpan.FromDays(7) };
    private static string ReasonText(SnapshotReason reason) => reason switch
    {
        SnapshotReason.Periodic => "weekly", SnapshotReason.Manual => "manual", SnapshotReason.PreChange => "pre-change",
        SnapshotReason.PreSync => "pre-sync",
        SnapshotReason.PreContact => "pre-contact", SnapshotReason.PreContactImport => "pre-contact-import",
        SnapshotReason.PreContactMerge => "pre-contact-merge", SnapshotReason.PreContactDelete => "pre-contact-delete",
        _ => "pre-restore"
    };
    private static string ValidId(string value) => Guid.TryParse(value, out var id) ? id.ToString() : throw new InvalidDataException("Die Snapshot-ID ist ungültig.");
    private static string Sha256(string text) => Sha256(Encoding.UTF8.GetBytes(text));
    private static string Sha256(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static (long Size, string Hash) HashFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[64 * 1024];
        long total = 0;
        int read;
        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            total += read;
            if (total > AtomicStore.MaxArchiveBytes)
                throw new InvalidDataException("Der Snapshot-Payload ist zu groß.");
            hash.AppendData(buffer, 0, read);
        }
        return (total, Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant());
    }
    private static bool FixedHash(string left, string right) => left.Length == 64 && CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(left.ToLowerInvariant()), Encoding.ASCII.GetBytes(right));
    private static bool ValidHash(string value) => value.Length == 64 && value.All(character =>
        character is >= '0' and <= '9' or >= 'a' and <= 'f' or >= 'A' and <= 'F');
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
    internal static string Prepare(JsonObject data, DateTimeOffset? now = null, JsonObject? live = null,
        bool restoreSmsPlans = true)
    {
        if (restoreSmsPlans)
        {
            // Outgoing permission is local; archived plans are content, not consent.
            var settings = data["einstellungen"] as JsonObject ?? new JsonObject();
            data["einstellungen"] = settings;
            var addresses = settings["adressen"] as JsonObject ?? new JsonObject();
            settings["adressen"] = addresses;
            addresses["smsSchedulingEnabled"] = live?["einstellungen"]?["adressen"]?["smsSchedulingEnabled"] is JsonValue permission &&
                permission.TryGetValue<bool>(out var enabled) && enabled;
            foreach (var sms in (data["smsPlanung"] as JsonArray)?.OfType<JsonObject>() ?? [])
            {
                if (sms["status"]?.ToString() == "planned") sms["status"] = "paused";
                else if (sms["status"]?.ToString() == "submitting") sms["status"] = "uncertain";
            }
        }
        // Restore content, never the archive's source identity or protocol baseline.
        var personal = data["personalSync"] as JsonObject ?? new JsonObject();
        data["personalSync"] = personal;
        var current = live?["personalSync"] as JsonObject;
        personal["actor_id"] = current?["actor_id"]?.DeepClone() ?? JsonValue.Create("");
        personal["custom_revision"] = current?["custom_revision"]?.DeepClone() ?? JsonValue.Create(0);
        personal["custom_entities"] = current?["custom_entities"]?.DeepClone() ?? new JsonObject();
        personal.Remove("custom_auto_hash");
        var epoch = Guid.NewGuid().ToString();
        data["syncEpoch"] = epoch;
        data.Remove("syncAbgleichBasis");
        data.Remove("syncAbgleichNachweis");
        var metadata = data["syncMetadaten"] as JsonObject ?? new JsonObject();
        data["syncMetadaten"] = metadata;
        metadata["syncEpoch"] = epoch;
        metadata["ersteSyncLoeschungsfrei"] = true;
        if (metadata["nextcloud"] is JsonObject cloud)
        {
            cloud.Remove("ausstehendeTransaktion");
            cloud.Remove("pendingCommitId");
            cloud["transaktionen"] = new JsonObject();
        }
        data["syncNachRestore"] = new JsonObject { ["additiv"] = true, ["loeschungsfrei"] = true,
            ["erstelltUtc"] = (now ?? DateTimeOffset.UtcNow).ToUniversalTime().ToString("O") };
        metadata["quarantinedDeletes"] = new JsonObject {
            ["geloescht"] = data["geloescht"]?.DeepClone() ?? new JsonObject(),
            ["tombstones"] = data["tombstones"]?.DeepClone() ?? new JsonArray(),
            ["baumKontaktGeloescht"] = data["baumKontaktGeloescht"]?.DeepClone() ?? new JsonArray() };
        data["geloescht"] = new JsonObject { ["termine"] = new JsonArray(), ["aufgaben"] = new JsonArray(), ["kontakte"] = new JsonArray() };
        data["tombstones"] = new JsonArray();
        data["baumKontaktGeloescht"] = new JsonArray();
        return epoch;
    }
}
