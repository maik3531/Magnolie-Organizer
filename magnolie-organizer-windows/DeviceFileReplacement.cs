using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native callback only; saved settings or a peer/browser bool cannot create it.
internal sealed class NativeMediaReplacementConsent(Func<bool> current)
{
    private bool revoked; private readonly object gate = new();
    internal void Require()
    {
        lock (gate)
        {
            try { if (revoked || !current()) throw DeviceFileControl.Error("file_receive_replacement_consent_changed"); }
            catch { revoked = true; throw; }
        }
    }
}
internal sealed record NativeMediaReplacementContext(JsonArray Records, NativeMediaReplacementConsent Consent);

internal sealed partial class TelefonStore
{
    // Resolve an immutable replacement chain without deleting any original job.
    // Every ancestor must be a LOCAL Saved+END baseline in this exact namespace.
    private static HashSet<(string Job, string File)> ReplacementAncestors(IReadOnlyList<ReceiveHead> heads, JsonObject body, string fileId)
    {
        var result = new HashSet<(string Job, string File)>(); var current = body; var currentId = fileId;
        while (current["replacements"] is JsonArray records && records.OfType<JsonObject>().SingleOrDefault(item => TelefonMessagingContract.String(item, "file_id") == currentId) is JsonObject link)
        {
            var id = TelefonMessagingContract.String(link, "job_id"); var oldId = TelefonMessagingContract.String(link, "original_file_id");
            if (!result.Add((id, oldId)) || result.Count > NativeReceiveHistoryLimit) throw DeviceFileControl.Error("file_receive_replacement_lineage_invalid");
            var old = heads.SingleOrDefault(head => head.JobId == id && head.Version == TelefonMessagingContract.String(link, "job_version"))
                ?? throw DeviceFileControl.Error("file_receive_replacement_original_required");
            if (!old.Body.ContainsKey("saved") || !old.Body.ContainsKey("source_end") || old.Body["media"] is not JsonObject media ||
                TelefonMessagingContract.String(media, "source_epoch") != TelefonMessagingContract.String(link, "source_epoch") ||
                !media["entries"]!.AsArray().OfType<JsonObject>().Any(entry => TelefonMessagingContract.String(entry, "file_id") == oldId &&
                    TelefonMessagingContract.String(entry, "photo_id") == TelefonMessagingContract.String(link, "photo_id")) ||
                new[] { "destination", "destination_version", "album_root", "media_type" }.Any(key => !JsonNode.DeepEquals(old.Body[key], current[key])))
                throw DeviceFileControl.Error("file_receive_replacement_scope_changed");
            var oldFile = old.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Single(file => TelefonMessagingContract.String(file, "id") == oldId);
            var newFile = current["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Single(file => TelefonMessagingContract.String(file, "id") == currentId);
            if (!JsonNode.DeepEquals(oldFile["path"], newFile["path"]) || current["media"] is JsonObject now &&
                (TelefonMessagingContract.String(now, "source_epoch") != TelefonMessagingContract.String(link, "source_epoch") ||
                 !now["entries"]!.AsArray().OfType<JsonObject>().Any(entry => TelefonMessagingContract.String(entry, "file_id") == currentId &&
                    TelefonMessagingContract.String(entry, "photo_id") == TelefonMessagingContract.String(link, "photo_id"))))
                throw DeviceFileControl.Error("file_receive_replacement_scope_changed");
            current = old.Body; currentId = oldId;
        }
        return result;
    }

    internal NativeMediaReplacementContext CreateNativeMediaReplacements(DeviceFileManifest manifest, IReadOnlyList<DeviceFileMediaPage> pages,
        NativeMediaReconcilePlan plan, NativeMediaReplacementConsent consent)
    {
        consent.Require(); var entries = DeviceFileSources.CorrelateMediaPages(pages, manifest); var records = new JsonArray();
        if (pages[0].SourceEpoch != plan.SourceEpoch || !pages[0].InsertionWitness) throw DeviceFileControl.Error("file_receive_replacement_scope_changed");
        foreach (var (file, entry) in manifest.Files.Zip(entries))
        {
            var member = plan.Members.Single(item => item.FileId == file.Id && item.PhotoId == entry.PhotoId);
            if (member.Action != "replace_managed_desktop") continue;
            if (member.BaselineJob is null || member.BaselineVersion is null || member.OriginalFileId is null)
                throw DeviceFileControl.Error("file_receive_replacement_original_required");
            records.Add(new JsonObject { ["file_id"] = file.Id, ["job_id"] = member.BaselineJob, ["job_version"] = member.BaselineVersion,
                ["original_file_id"] = member.OriginalFileId, ["source_epoch"] = plan.SourceEpoch, ["photo_id"] = entry.PhotoId,
                ["trash_operation"] = Guid.NewGuid().ToString("N") });
        }
        if (records.Count == 0) throw DeviceFileControl.Error("file_receive_replacement_original_required");
        consent.Require(); return new(records, consent);
    }

    internal sealed partial class NativeMediaReceiveJob
    {
        private NativeMediaReplacementConsent? replacementConsent;
        private readonly Dictionary<string, DeviceFileNativeDirectory.DeviceFileNativeStagedFile> replacementArchives = [];
        internal void RenewNativeReplacementConsent(NativeMediaReplacementConsent consent)
        {
            lock (jobGate) { Current(); consent.Require(); replacementConsent = consent; }
        }
        private static void ValidateReplacements(JsonObject body, DeviceFileManifest manifest)
        {
            if (!body.ContainsKey("replacements")) return;
            if (body["replacements"] is not JsonArray records || records.Count is < 1 or > 16) throw DeviceFileControl.Error("file_receive_replacement_invalid");
            var files = new HashSet<string>(StringComparer.Ordinal); var operations = new HashSet<string>(StringComparer.Ordinal);
            foreach (var value in records)
            {
                var link = TelefonProtocolContract.ExactObject(value!, "file_id", "job_id", "job_version", "original_file_id", "source_epoch", "photo_id", "trash_operation");
                string Text(string key) => TelefonMessagingContract.String(link, key);
                foreach (var key in new[] { "file_id", "job_id", "original_file_id", "trash_operation" })
                    if (Text(key).Length != 32 || Text(key).Any(c => !char.IsAsciiHexDigitLower(c))) throw DeviceFileControl.Error("file_receive_replacement_invalid");
                if (new[] { "job_version", "source_epoch", "photo_id" }.Any(key => !DeviceFileControl.Hash(Text(key))) ||
                    !files.Add(Text("file_id")) || !operations.Add(Text("trash_operation")) || !manifest.Files.Any(file => file.Id == Text("file_id")))
                    throw DeviceFileControl.Error("file_receive_replacement_invalid");
                if (body["media"] is JsonObject media && (TelefonMessagingContract.String(media, "source_epoch") != Text("source_epoch") ||
                    media["insertion_witness"] is not JsonValue witness || !witness.TryGetValue<bool>(out var inserted) || !inserted || !media["entries"]!.AsArray().OfType<JsonObject>().Any(entry =>
                        TelefonMessagingContract.String(entry, "file_id") == Text("file_id") && TelefonMessagingContract.String(entry, "photo_id") == Text("photo_id"))))
                    throw DeviceFileControl.Error("file_receive_replacement_scope_changed");
            }
        }

        private void PreserveReplacementOriginal(string fileId)
        {
            if (head!.Body["replacements"] is not JsonArray records || records.OfType<JsonObject>().SingleOrDefault(item => TelefonMessagingContract.String(item, "file_id") == fileId) is not JsonObject link) return;
            var consent = replacementConsent ?? throw DeviceFileControl.Error("file_receive_native_replacement_consent_required");
            bool Permit() { Current(); consent.Require(); return true; }
            _ = store.MoveNativeMediaTrash(peerId, TelefonMessagingContract.String(link, "job_id"), TelefonMessagingContract.String(link, "job_version"),
                TelefonMessagingContract.String(link, "original_file_id"), null, Permit, TelefonMessagingContract.String(link, "trash_operation"));
            // Keep the preserved original open without WRITE/DELETE sharing
            // through new publication AND local Saved. A competing restore or
            // filesystem edit cannot consume/change the recovery copy meanwhile.
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open();
                var old = store.ReceiveHeads(db, null, store.MediaPreferenceScope(peerId)).Single(item => item.JobId == TelefonMessagingContract.String(link, "job_id") &&
                    item.Version == TelefonMessagingContract.String(link, "job_version"));
                var oldId = TelefonMessagingContract.String(link, "original_file_id");
                var file = old.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == oldId);
                var member = old.Body["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == oldId);
                var held = PublicationRoot.OpenOriginalStagedFile(".magnolie-trash-" + TelefonMessagingContract.String(link, "trash_operation"),
                    AlbumIdentity(member["identity"]!.AsObject()), TelefonProtocolContract.Integer(file["size"]), TelefonMessagingContract.String(file, "sha256"));
                try { Current(); consent.Require(); replacementArchives.Add(fileId, held); }
                catch { held.Dispose(); throw; }
            }
            Current(); consent.Require();
        }

        private void RequireReplacementArchives()
        {
            if (head!.Body["replacements"] is not JsonArray records) return;
            foreach (var link in records.OfType<JsonObject>())
            {
                var fileId = TelefonMessagingContract.String(link, "file_id");
                if (!replacementArchives.TryGetValue(fileId, out var held) || PublicationRoot.FileIdentityAt(".magnolie-trash-" +
                    TelefonMessagingContract.String(link, "trash_operation")) != held.Observe().Identity)
                    throw DeviceFileControl.Error("file_receive_replacement_original_not_preserved");
            }
        }
    }
}
