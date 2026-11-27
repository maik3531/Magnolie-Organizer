using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Refs #330. A local native handoff from the actual, complete original run.
    // Remote DATA, a map, a timestamp or this plan cannot instantiate native
    // READ/END rights. No raw reader or peer grant survives the output drain.
    internal sealed class NativeBatchSourceRetirement
    {
        private readonly TelefonConnection.NativeMediaBatchSendRun run;
        private readonly NativePreparedMediaBatch cache;
        private readonly TelefonStore store;
        private readonly DeviceFileNativeDirectory output;
        private readonly NativeMediaBackupParent parent;
        private readonly Func<bool> nativePermit;
        private readonly Action<string>? boundary;
        private readonly Dictionary<string, NativeMediaBackupVersion> selected;
        private readonly Dictionary<string, JsonObject> expected;
        private readonly string cacheVersion, nonce;
        private readonly JsonObject plan;
        private MediaBackupCatalog? catalog;
        private int thread;
        private bool planned, active, draining, drained, verifiedScope, ended;

        internal NativeBatchSourceRetirement(TelefonConnection.NativeMediaBatchSendRun run, DeviceFileNativeDirectory output,
            IReadOnlyDictionary<string, NativeMediaBackupVersion> selected, Func<bool> nativePermit, Action<string>? boundary)
        {
            ArgumentNullException.ThrowIfNull(output); ArgumentNullException.ThrowIfNull(selected); ArgumentNullException.ThrowIfNull(nativePermit);
            this.run = run; cache = run.Cache; store = cache.OwnerStore; this.output = output;
            this.nativePermit = nativePermit; this.boundary = boundary; run.Require();
            if (!run.Saved.Task.IsCompletedSuccessfully || !run.Readback.Task.IsCompletedSuccessfully || run.OutputDrained ||
                run.Exchange.Phase != "peer_readback" || !selected.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(cache.Manifest.Files.Select(file => file.Id)))
                throw DeviceFileControl.Error("media_source_batch_complete_native_retirement_required");
            this.selected = new(selected, StringComparer.Ordinal); parent = NativeMediaBackupParent.Capture(output);
            cacheVersion = cache.Version; nonce = cache.Nonce; expected = cache.RetirementBackupProvenances();
            var references = new JsonObject();
            foreach (var (fid, value) in this.selected)
                references[fid] = new JsonObject { ["id"] = value.Id, ["object_key"] = value.ObjectKey, ["saved_ms"] = value.SavedMs,
                    ["name"] = value.Name, ["record_sha256"] = value.RecordSha256 };
            plan = new JsonObject { ["format"] = 1, ["job_id"] = cache.JobId, ["cache_version"] = cacheVersion, ["nonce"] = nonce,
                ["manifest_sha256"] = cache.Manifest.Fingerprint, ["storage_parent"] = parent.Wire(), ["backups"] = references,
                ["saved_sha256"] = DeviceFileControl.Digest("magnolie-native-source-batch-saved-v1\0", run.Exchange.Observation["peer_saved"]!),
                ["readback_sha256"] = run.Readback.Task.Result.Body["readback_sha256"]!.DeepClone() };
            if (!nativePermit() || store.RestoreFenced) throw DeviceFileControl.Error("media_backup_native_permit_changed");
        }

        internal bool MatchesOriginalRun(TelefonConnection.NativeMediaBatchSendRun value) => ReferenceEquals(run, value) && !planned;
        internal bool OwnsExchange(NativeMediaBatchSourceExchange value) => active && thread == Environment.CurrentManagedThreadId &&
            ReferenceEquals(value, run.Exchange) && planned && run.OutputDrained;
        internal bool PermitsLocalScopeEntry(NativeCollectionMediaBatch source) => active && thread == Environment.CurrentManagedThreadId &&
            planned && !drained && !ended && catalog is null && run.OutputDrained && cache.HasOriginalSource(source);
        internal bool PermitsOriginalDrain(NativeCollectionMediaBatch source) => active && thread == Environment.CurrentManagedThreadId &&
            verifiedScope && catalog is not null && draining && !drained && !ended && run.OutputDrained && cache.HasOriginalSource(source);
        internal bool PermitsEndedAuthority(NativeCollectionMediaBatch source) => active && thread == Environment.CurrentManagedThreadId &&
            verifiedScope && catalog is not null && drained && run.OutputDrained && cache.HasOriginalSource(source);
        internal bool PermitsTerminalWrite(NativeMediaBatchSourceExchange value) => OwnsExchange(value) && verifiedScope && drained && !ended;

        internal void Plan()
        {
            if (planned || active) throw DeviceFileControl.Error("media_source_batch_retirement_existing_intent_held");
            run.Require(); run.Exchange.PlanRetirement(this, plan); planned = true;
            boundary?.Invoke("source_batch_end_planned");
        }

        internal void Current()
        {
            run.Connection.RequireNativeBatchRetirementLane(this);
            if (!active || thread != Environment.CurrentManagedThreadId || !planned || !run.OutputDrained || store.RestoreFenced ||
                !nativePermit() || NativeMediaBackupParent.Capture(output) != parent)
                throw DeviceFileControl.Error("media_source_batch_original_retirement_owner_required");
            if (drained) cache.RequireEndedRetirement(this); else cache.RequireBackupIdentity(cacheVersion, nonce);
            run.Exchange.RequireLocalRetirementHead(this);
            var body = run.Exchange.Observation;
            if (body["phase"]!.GetValue<string>() is not ("end_planned" or "source_ended") ||
                !JsonNode.DeepEquals(body["source_retirement"], plan) || body["pending_chunk"] is not null ||
                body["cache_version"]!.GetValue<string>() != cacheVersion || body["nonce"]!.GetValue<string>() != nonce ||
                DeviceFileControl.Digest("magnolie-native-source-batch-saved-v1\0", body["peer_saved"]!) != plan["saved_sha256"]!.GetValue<string>() ||
                body["peer_readback"]!["body"]!["readback_sha256"]!.GetValue<string>() != plan["readback_sha256"]!.GetValue<string>())
                throw DeviceFileControl.Error("media_source_batch_original_retirement_intent_required");
        }

        internal void RunAfterOutputDrain()
        {
            if (!planned || active || ended || !run.OutputDrained) throw DeviceFileControl.Error("media_source_batch_actual_output_drain_required");
            active = true; thread = Environment.CurrentManagedThreadId;
            try
            {
                cache.RunRetirementScope(this);
            }
            finally
            {
                // On every failure the old owner is drained, never silently
                // reused. The exact planned intent/backup/cache remain HOLD.
                try { cache.Dispose(); }
                finally { catalog = null; active = false; verifiedScope = false; thread = 0; }
            }
        }

        internal void RunProtectedLocalScope()
        {
            lock (store.gate)
            {
                Current(); cache.VerifyRetirementCiphers(this, ended: false);
                using var heldCatalog = new MediaBackupCatalog(store, parent, Current, false);
                catalog = heldCatalog;
                heldCatalog.VerifyPreparedBatchMap(selected, expected, this);
                if (!ended) throw DeviceFileControl.Error("media_source_batch_complete_native_retirement_required");
            }
        }

        internal void RequireBackupAnchor(Microsoft.Data.Sqlite.SqliteConnection db, Microsoft.Data.Sqlite.SqliteTransaction transaction)
        {
            if (!verifiedScope || catalog is null || !drained) throw DeviceFileControl.Error("media_source_batch_complete_native_retirement_required");
            catalog.RequireOriginalBatchAnchor(db, transaction);
        }

        internal void FinishVerifiedBackupMap(object actualCatalog)
        {
            if (!ReferenceEquals(catalog, actualCatalog) || verifiedScope || ended)
                throw DeviceFileControl.Error("media_source_batch_complete_native_retirement_required");
            verifiedScope = true;
            Current(); boundary?.Invoke("source_batch_end_backups_held"); Current();
            draining = true; cache.DrainForRetirement(this); drained = true; draining = false;
            Current(); boundary?.Invoke("source_batch_end_originals_drained"); Current();
            cache.VerifyRetirementCiphers(this, ended: true); Current();
            run.Exchange.FinishRetirement(this); ended = true;
            boundary?.Invoke("source_batch_end_committed"); Current();
        }
    }
}
