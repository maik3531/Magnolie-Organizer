using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed partial class NativeMediaReceiveJob
    {
        private static string Proof(string domain, JsonNode value) => DeviceFileControl.Digest(domain + "\0", value);
        private static JsonObject AcceptanceContext(JsonObject body, string jobId)
        {
            var result = new JsonObject { ["format"] = 1, ["platform"] = "windows", ["job_id"] = jobId,
                ["manifest_sha256"] = ManifestHash(body), ["binding"] = body["binding"]!.DeepClone(),
                ["destination"] = body["destination"]!.DeepClone(), ["destination_version"] = body["destination_version"]!.DeepClone(),
                ["targets"] = new JsonArray(body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Select(file => (JsonNode)new JsonObject
                { ["file_id"] = file["id"]!.DeepClone(), ["path"] = TargetPath(body, file) }).ToArray()) };
            if (body.ContainsKey("media")) result["media"] = body["media"]!.DeepClone();
            if (body.ContainsKey("album_root")) result["album_root"] = body["album_root"]!.DeepClone();
            if (body.ContainsKey("replacements")) result["replacements"] = body["replacements"]!.DeepClone();
            return result;
        }
        private static string TargetPath(JsonObject body, JsonObject file) => body["album_root"] is JsonObject album
            ? TelefonMessagingContract.String(album, "folder") + "/" + TelefonMessagingContract.String(file, "path") : TelefonMessagingContract.String(file, "path");

        private static void ValidateNativeMediaContext(JsonObject body, DeviceFileManifest manifest)
        {
            if (!body.ContainsKey("media")) return; // Legacy history is not silently rewritten/adopted.
            var media = TelefonProtocolContract.ExactObject(body["media"]!, "catalog_id", "album_id", "source_epoch", "media_type", "insertion_witness", "entries");
            if (!TelefonProtocolContract.IsUuidV4(TelefonMessagingContract.String(media, "catalog_id")) || !TelefonProtocolContract.IsUuidV4(TelefonMessagingContract.String(media, "album_id")) ||
                !DeviceFileControl.Hash(TelefonMessagingContract.String(media, "source_epoch")) || !JsonNode.DeepEquals(media["media_type"], body["media_type"]) ||
                media["insertion_witness"] is not JsonValue witness || !witness.TryGetValue<bool>(out _) || media["entries"] is not JsonArray entries || entries.Count != manifest.Files.Count)
                throw DeviceFileControl.Error("file_receive_original_media_invalid");
            var photos = new HashSet<string>(StringComparer.Ordinal);
            for (var index = 0; index < entries.Count; index++)
            {
                var entry = TelefonProtocolContract.ExactObject(entries[index]!, "file_id", "photo_id", "media_kind");
                var photo = TelefonMessagingContract.String(entry, "photo_id"); var kind = TelefonMessagingContract.String(entry, "media_kind");
                if (TelefonMessagingContract.String(entry, "file_id") != manifest.Files[index].Id || !DeviceFileControl.Hash(photo) || !photos.Add(photo) ||
                    (TelefonMessagingContract.String(media, "media_type") == "video" ? kind != "video" : kind is not ("image" or "animation" or "unknown_image")))
                    throw DeviceFileControl.Error("file_receive_original_media_invalid");
            }
        }

        internal void BindNativeMediaContext(string catalogId, string albumId, IReadOnlyList<DeviceFileMediaPage> pages)
        {
            lock (jobGate)
            {
                Current(); var entries = DeviceFileSources.CorrelateMediaPages(pages, Manifest); var first = pages[0];
                var media = new JsonObject { ["catalog_id"] = catalogId, ["album_id"] = albumId, ["source_epoch"] = first.SourceEpoch,
                    ["media_type"] = first.MediaType, ["insertion_witness"] = first.InsertionWitness,
                    ["entries"] = new JsonArray(entries.Select(entry => (JsonNode)new JsonObject
                    { ["file_id"] = entry.FileId, ["photo_id"] = entry.PhotoId, ["media_kind"] = entry.MediaKind }).ToArray()) };
                if (head!.Body["media"] is JsonObject original)
                {
                    // A renewed catalog token is not a new underlying source or
                    // media identity. Retain original provenance, never rewrite it.
                    foreach (var key in new[] { "source_epoch", "media_type", "insertion_witness", "entries" })
                        if (!JsonNode.DeepEquals(original[key], media[key])) throw DeviceFileControl.Error("file_receive_original_media_changed");
                    return;
                }
                if (head.Body.ContainsKey("acceptance")) throw DeviceFileControl.Error("file_receive_legacy_media_reassociation_required");
                var body = Change(); body["media"] = media; Save(body);
            }
        }
        private static string ManifestHash(JsonObject body)
        {
            using var document = System.Text.Json.JsonDocument.Parse(body["manifest"]!.ToJsonString());
            return DeviceFileManifest.Parse(document.RootElement).Fingerprint;
        }
        private static JsonObject AcceptanceRecord(JsonObject body, string jobId)
        {
            var context = AcceptanceContext(body, jobId);
            return new() { ["format"] = 1, ["context"] = context, ["sha256"] = Proof("magnolie-windows-native-acceptance-v1", context) };
        }
        private static JsonObject SavedRecord(JsonObject body, string jobId)
        {
            // This is a LOCAL Windows receipt, not a remote Saved assertion.
            // Original publication identities and flushed checkpoints are bound
            // to the existing protected original job and acceptance context.
            var publication = new JsonObject { ["format"] = 1, ["job_id"] = jobId, ["manifest"] = body["manifest"]!.DeepClone(),
                ["binding"] = body["binding"]!.DeepClone(), ["destination"] = body["destination"]!.DeepClone(),
                ["stage_identity"] = body["stage_identity"]!.DeepClone(), ["files"] = body["files"]!.DeepClone() };
            if (body.ContainsKey("album_root")) publication["album_root"] = body["album_root"]!.DeepClone();
            if (body.ContainsKey("replacements")) publication["replacements"] = body["replacements"]!.DeepClone();
            var publicationHash = Proof("magnolie-windows-native-publication-v1", publication);
            var acceptanceHash = TelefonMessagingContract.String(body["acceptance"]!.AsObject(), "sha256");
            var members = body["files"]!.AsArray().OfType<JsonObject>().ToArray();
            var manifests = body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().ToArray();
            var receipts = new JsonArray();
            for (var index = 0; index < members.Length; index++)
            {
                var file = manifests[index]; var member = members[index];
                if (TelefonMessagingContract.String(member, "phase") != "published" || member["checkpoint"] is not JsonObject checkpoint ||
                    !JsonNode.DeepEquals(checkpoint["size"], file["size"]) || !JsonNode.DeepEquals(checkpoint["sha256"], file["sha256"]))
                    throw DeviceFileControl.Error("file_receive_local_saved_not_proved");
                var receipt = new JsonObject { ["format"] = 1, ["job_id"] = jobId, ["accepted_sha256"] = acceptanceHash,
                    ["publication_sha256"] = publicationHash, ["file_id"] = file["id"]!.DeepClone(), ["path"] = TargetPath(body, file),
                    ["size"] = file["size"]!.DeepClone(), ["sha256"] = file["sha256"]!.DeepClone(), ["identity"] = member["identity"]!.DeepClone(),
                    ["parent_identity"] = (body["album_root"]?["identity"] ?? body["destination"]!["identity"])!.DeepClone(), ["checkpoint"] = checkpoint.DeepClone() };
                receipts.Add(new JsonObject { ["file_id"] = file["id"]!.DeepClone(), ["size"] = file["size"]!.DeepClone(),
                    ["sha256"] = file["sha256"]!.DeepClone(), ["receipt_sha256"] = Proof("magnolie-windows-native-saved-file-v1", receipt) });
            }
            return new() { ["format"] = 1, ["accepted_sha256"] = acceptanceHash, ["publication_sha256"] = publicationHash, ["receipts"] = receipts };
        }

        private static void ValidateReceipts(JsonObject body, string jobId)
        {
            if (body.ContainsKey("acceptance") && !JsonNode.DeepEquals(body["acceptance"], AcceptanceRecord(body, jobId)))
                throw DeviceFileControl.Error("file_receive_acceptance_invalid");
            if (body.ContainsKey("saved") && (TelefonMessagingContract.String(body, "phase") != "published" ||
                !body.ContainsKey("acceptance") || !JsonNode.DeepEquals(body["saved"], SavedRecord(body, jobId))))
                throw DeviceFileControl.Error("file_receive_local_saved_invalid");
            if (body.ContainsKey("source_end"))
            {
                var end = TelefonProtocolContract.ExactObject(body["source_end"]!, "run_id", "operation", "version", "remote_session", "saved_sha256");
                if (!body.ContainsKey("saved") || !TelefonProtocolContract.IsUuidV4(TelefonMessagingContract.String(end, "run_id")) ||
                    TelefonMessagingContract.String(end, "operation") is not ("end_run" or "end_resume") ||
                    !DeviceFileControl.Hash(TelefonMessagingContract.String(end, "version")) || !DeviceFileControl.Hash(TelefonMessagingContract.String(end, "remote_session")) ||
                    TelefonMessagingContract.String(end, "saved_sha256") != Proof("magnolie-windows-native-saved-v1", body["saved"]!))
                    throw DeviceFileControl.Error("file_receive_source_end_invalid");
            }
        }

        internal RemoteFileAcceptance PrepareNativeAcceptance(string offerId)
        {
            lock (jobGate)
            {
                Current();
                if (!TelefonProtocolContract.IsUuidV4(offerId) || TelefonMessagingContract.String(head!.Body, "phase") != "receiving")
                    throw DeviceFileControl.Error("file_receive_acceptance_not_ready");
                if (head.Body.ContainsKey("replacements") && !head.Body.ContainsKey("media"))
                    throw DeviceFileControl.Error("file_receive_replacement_media_required");
                if (!head.Body.ContainsKey("acceptance"))
                {
                    var body = Change(); body["acceptance"] = AcceptanceRecord(body, JobId); Save(body);
                }
                return new(offerId, Manifest.Fingerprint, Manifest.TransferId,
                    TelefonMessagingContract.String(head.Body["acceptance"]!.AsObject(), "sha256"), binding.PermissionEpoch, binding.DestinationToken);
            }
        }

        internal (string FileId, int Index)? NextNativeChunk()
        {
            lock (jobGate)
            {
                Current();
                foreach (var file in Manifest.Files)
                {
                    var missing = ledger.Missing(file.Id); if (missing.Length != 0) return (file.Id, missing[0]);
                }
                return null;
            }
        }

        internal JsonArray CommitNativeSavedReceipts()
        {
            lock (jobGate)
            {
                Current();
                if (TelefonMessagingContract.String(head!.Body, "phase") != "published" || !head.Body.ContainsKey("acceptance"))
                    throw DeviceFileControl.Error("file_receive_local_saved_not_ready");
                RequireReplacementArchives();
                foreach (var file in Manifest.Files)
                {
                    var actual = files[file.Id].Observe();
                    var member = head.Body["files"]!.AsArray().OfType<JsonObject>().Single(value => TelefonMessagingContract.String(value, "id") == file.Id);
                    if (actual.Size != file.Size || !JsonNode.DeepEquals(Key(actual.Identity), member["identity"]) || PublicationRoot.FileIdentityAt(file.Path) != actual.Identity)
                        throw DeviceFileControl.Error("file_receive_local_saved_identity_changed");
                }
                if (!head.Body.ContainsKey("saved"))
                {
                    var body = Change(); body["saved"] = SavedRecord(body, JobId); Save(body);
                }
                return head.Body["saved"]!["receipts"]!.DeepClone().AsArray();
            }
        }

        // Called only by the actual owned source-END reply callback after a
        // confirmed secure Saved output. Metadata-only: no positive data grant,
        // file reopening, stage deletion, history eviction or replacement.
        internal void RecordNativeSavedSourceEnd(NativeFileControlSession.SourceRunLease lease, DeviceFileRunResult ended, Action requireSession)
        {
            lock (jobGate)
            {
                void Metadata()
                {
                    requireSession(); store.RequireNativeMediaStorageKey();
                    var scope = store.MediaPreferenceScope(peerId);
                    if (scope.PeerId != binding.SenderId || scope.LocalId != binding.ReceiverId || scope.PeerKey != binding.SenderIdentitySha256 || scope.LocalKey != binding.ReceiverIdentitySha256)
                        throw DeviceFileControl.Error("file_receive_original_source_end_required");
                }
                Metadata();
                if (!ended.RunEnded || !ended.SourceIoEnded || ended.State != "canceled_held" || ended.RunId != lease.RunId || ended.Version != lease.Version ||
                    ended.MediaType != mediaType || ended.Operation is not ("end_run" or "end_resume") || head?.Body["saved"] is null)
                    throw DeviceFileControl.Error("file_receive_original_source_end_required");
                var body = Change(); body["source_end"] = new JsonObject { ["run_id"] = lease.RunId, ["operation"] = ended.Operation,
                    ["version"] = lease.Version, ["remote_session"] = lease.RemoteSession, ["saved_sha256"] = Proof("magnolie-windows-native-saved-v1", body["saved"]!) };
                head = store.SaveReceiveHead(peerId, JobId, head!.Version, body, Metadata);
            }
        }
    }
}
