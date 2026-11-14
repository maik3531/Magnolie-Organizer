using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native serial book-worker only; never receive. Physical reservation precedes
// the independent archive. Loaded JSON is history only, not a fresh send proof.
// No production key backend, sender, retirement or restart reauthorization here.
internal sealed partial class NotesOriginalRequestIntents
{
    private const int Limit = 2 * 1024 * 1024;
    private readonly ContactSourcePrivateFiles files;
    private readonly Func<byte[]?> existingKey;
    private readonly Action<string> stage;
    private readonly Dictionary<string, FreshProof> fresh = new(StringComparer.Ordinal);
    private readonly Dictionary<NotesOriginalPendingResult, RecoveryContext> recovered = new();
    private readonly object gate = new();
    private long generation;
    private sealed record FreshProof(NotesOriginalRequestIntents Store, NotesOriginalPendingResult Pending,
        string Key, string Physical, string KeyIdentity, string FrameHash);
    private sealed record QueryProof(NotesOriginalRequestIntents Store, NotesOriginalChoiceStore Consent, string Binding, string LocalId,
        string FrameHash, long Generation);
    internal sealed class UnconfirmedQuery(object proof)
    {
        internal object RequireOwner(NotesOriginalRequestIntents store)
        {
            if (proof is not QueryProof native || !ReferenceEquals(native.Store, store)) throw new InvalidOperationException("notes_request_owned_query_required");
            return native;
        }
        internal JsonObject Request(NotesOriginalNegotiation protocol)
        {
            if (proof is not QueryProof native) throw new InvalidOperationException("notes_request_private_unconfirmed_query_required");
            return native.Store.RequireQuery(native, protocol);
        }
    }
    internal sealed class FreshRequest(object proof)
    {
        internal JsonObject RequireFor(NotesOriginalPendingResult pending, NotesOriginalNegotiation protocol)
        {
            if (proof is not FreshProof native || !ReferenceEquals(native.Pending, pending))
                throw new InvalidOperationException("notes_request_owned_fresh_proof_required");
            return native.Store.RequireFresh(native, protocol);
        }
    }

    internal NotesOriginalRequestIntents(ContactSourcePrivateFiles files, Func<byte[]?> existingKey, Action<string>? stage = null)
    {
        this.files = files ?? throw new ArgumentNullException(nameof(files));
        this.existingKey = existingKey ?? throw new ArgumentNullException(nameof(existingKey));
        this.stage = stage ?? (_ => { });
    }

    private (NotesOriginalJournalCrypto Crypto, string Identity) Crypto()
    {
        var identity = new NotesOriginalJournalCrypto(existingKey).Identity();
        return (new(() =>
        {
            var key = existingKey();
            if (key is null) return null;
            if (key.Length == 32 && Convert.ToHexString(SHA256.HashData(key)).ToLowerInvariant() == identity) return key;
            CryptographicOperations.ZeroMemory(key);
            throw new CryptographicException("notes_request_journal_key_changed");
        }), identity);
    }

    private static void Identity(ContactSourcePrivateFiles.Session directory, string identity, bool initialize)
    {
        var prior = directory.Read(".journal-key", 128);
        if (prior is null && initialize && directory.RootCreated)
        {
            directory.Write(".journal-key", identity + "\n", 128);
            prior = directory.Read(".journal-key", 128);
        }
        if (prior != identity + "\n") throw new InvalidOperationException("notes_request_journal_identity_changed");
    }

    private static string RecordKey(string physical, JsonObject frame) => NotesOriginalSchema.Hash(new JsonObject {
        ["physical"] = physical, ["request_id"] = frame["request"]!["request_id"]!.DeepClone() });

    internal static JsonObject Validate(string key, string physical, JsonObject frame)
    {
        var state = NotesOriginalSchema.Text(frame, "state");
        var fields = new[] { "version", "state", "request", "request_sha256", "source", "source_seal", "export", "local_before", "book_before", "physical" };
        NotesOriginalSchema.Fields(frame, state == "request_settled" ? fields.Concat(["terminal"]).ToArray() : fields);
        if (state == "request_settled")
        {
            var terminal = frame["terminal"] as JsonObject ?? throw new InvalidDataException("notes_request_terminal_marker_required");
            NotesOriginalSchema.Fields(terminal, "key", "sha256");
            if (terminal.Any(pair => !NotesOriginalSchema.Hex(NotesOriginalSchema.String(pair.Value)))) throw new InvalidDataException("notes_request_terminal_marker_invalid");
        }
        if (NotesOriginalSchema.Integer(frame, "version") != 1 || state is not ("request_pending" or "request_settled") ||
            NotesOriginalSchema.Text(frame, "physical") != physical || !NotesOriginalSchema.Hex(physical) ||
            frame["request"] is not JsonObject request || frame["source"] is not JsonObject source || frame["export"] is not JsonObject export ||
            frame["local_before"] is not JsonObject before || frame["source_seal"] is not JsonObject seal ||
            RecordKey(physical, frame) != key || NotesOriginalSchema.Hash(request) != NotesOriginalSchema.Text(frame, "request_sha256"))
            throw new InvalidDataException("notes_request_private_frame_invalid");
        NotesOriginalSchema.Fields(request, "art", "fassung", "request_id", "share_id", "before_basis", "target_sha256", "ziel");
        NotesOriginalSchema.Fields(source, "peer", "own", "share_id", "setup_id", "local_id", "local_uid");
        NotesOriginalSchema.Fields(seal, "key_sha256", "generation", "book", "source_sha256");
        NotesOriginalSchema.Fields(export, "art", "fassung", "share_id", "before_basis", "setup_id", "native_revision", "content_sha256", "kontakt");
        foreach (var name in new[] { "peer", "own" })
            if (source[name] is not JsonArray pins || pins.Count != 2 || pins.Any(value => string.IsNullOrEmpty(NotesOriginalSchema.String(value))))
                throw new InvalidDataException("notes_request_private_pins_invalid");
        if (seal.Any(pair => !NotesOriginalSchema.Hex(NotesOriginalSchema.String(pair.Value))) ||
            !NotesOriginalSchema.Share(NotesOriginalSchema.Text(source, "share_id")) ||
            !NotesOriginalSchema.Uuid(NotesOriginalSchema.Text(source, "setup_id")) ||
            string.IsNullOrEmpty(NotesOriginalSchema.Text(source, "local_id")) || string.IsNullOrEmpty(NotesOriginalSchema.Text(source, "local_uid")) ||
            NotesOriginalSchema.Text(seal, "source_sha256") != NotesOriginalSchema.Hash(source) ||
            NotesOriginalSchema.Text(before, "id") != NotesOriginalSchema.Text(source, "local_id") ||
            NotesOriginalSchema.Text(before, "uid") != NotesOriginalSchema.Text(source, "local_uid") ||
            NotesOriginalSchema.Text(request, "art") != "kontakt_original_anfrage" || NotesOriginalSchema.Integer(request, "fassung") != 1 ||
            !NotesOriginalSchema.Uuid(NotesOriginalSchema.Text(request, "request_id")) ||
            NotesOriginalSchema.Text(request, "share_id") != NotesOriginalSchema.Text(source, "share_id") ||
            NotesOriginalSchema.Text(export, "setup_id") != NotesOriginalSchema.Text(source, "setup_id") ||
            NotesOriginalSchema.Text(export, "share_id") != NotesOriginalSchema.Text(source, "share_id") ||
            NotesOriginalSchema.Text(request, "before_basis") != NotesOriginalSchema.Text(export, "before_basis") ||
            frame["book_before"] is not JsonArray hashes || hashes.Count != 2 || hashes.Any(value => !NotesOriginalSchema.Hex(NotesOriginalSchema.String(value))))
            throw new InvalidDataException("notes_request_private_correlation_invalid");
        if (request["ziel"] is not JsonObject patch || export["kontakt"] is not JsonObject original)
            throw new InvalidDataException("notes_request_exact_target_required");
        if (NotesOriginalSchema.Text(export, "art") != "kontakt_original_export" || NotesOriginalSchema.Integer(export, "fassung") != 1 ||
            NotesOriginalSchema.Integer(export, "native_revision") < 0 || !NotesOriginalSchema.Hex(NotesOriginalSchema.Text(export, "before_basis")) ||
            NotesOriginalReturnHash.ContentHash(original) != NotesOriginalSchema.Text(export, "content_sha256"))
            throw new InvalidDataException("notes_request_private_export_invalid");
        NotesOriginalSchema.Fields(patch, "vorname", "nachname", "firma", "notiz", "geburtstag", "jubilaeum", "anzeigename", "vcardName", "anschriften");
        if (!JsonNode.DeepEquals(NotesOriginalExportChoice.Project(before, original), patch)) throw new InvalidDataException("notes_request_local_target_changed");
        var target = original.DeepClone().AsObject(); foreach (var pair in patch) target[pair.Key] = pair.Value?.DeepClone();
        if (NotesOriginalReturnHash.ContentHash(target) != NotesOriginalSchema.Text(request, "target_sha256"))
            throw new InvalidDataException("notes_request_exact_target_changed");
        return frame;
    }

    private static (string Key, string Encrypted, JsonObject Frame)? Physical(ContactSourcePrivateFiles.Session directory,
        NotesOriginalJournalCrypto crypto, string physical)
    {
        var text = directory.Read("p-" + physical + ".json", Limit);
        if (text is null) return null;
        // The pointer is not authority: the exact ID/AAD, decrypted physical
        // binding and complete record correlation must all verify independently.
        var wrapper = NotesOriginalJournalCrypto.Parse(text);
        NotesOriginalSchema.Fields(wrapper, "key", "encrypted");
        var key = NotesOriginalSchema.Text(wrapper, "key"); var encrypted = NotesOriginalSchema.Text(wrapper, "encrypted");
        return (key, encrypted, Validate(key, physical, crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, key, encrypted)));
    }

    internal FreshRequest Seal(NotesOriginalPendingResult pending, NotesOriginalSavedAckIntents.TerminalProof? previousTerminal = null)
    {
        var release = previousTerminal?.RequireFor(this); // Native callbacks before registry/file locks.
        var captured = pending.CaptureRequestIntention(); var context = Crypto();
        var physical = context.Crypto.Physical(captured.Binding, NotesOriginalSchema.Text(captured.Frame["source"]!.AsObject(), "local_id"));
        var frame = captured.Frame; frame["physical"] = physical; var key = RecordKey(physical, frame);
        Validate(key, physical, frame);
        long started;
        lock (gate)
        {
            started = generation;
            if (fresh.TryGetValue(key, out var owned) && ReferenceEquals(owned.Pending, pending))
            {
                if (NotesOriginalSchema.Hash(frame) != owned.FrameHash) throw new InvalidOperationException("notes_request_native_frame_changed");
                CheckStored(owned, context.Crypto, context.Identity); return new(owned);
            }
            var encrypted = context.Crypto.Seal(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, key, frame);
            using (var directory = files.Open(create: true) ?? throw new IOException("notes_request_private_root_required"))
            {
                Identity(directory, context.Identity, initialize: true);
                var previous = Physical(directory, context.Crypto, physical);
                if (previous is not null && (release is null || !JsonNode.DeepEquals(previous.Value.Frame, release.Settled) ||
                        directory.Read("r-" + previous.Value.Key + ".json", Limit) != previous.Value.Encrypted))
                    throw new InvalidOperationException("notes_request_physical_held");
                if (directory.Read("r-" + key + ".json", Limit) is not null) throw new InvalidOperationException("notes_request_loaded_history_held");
                var wrapper = new JsonObject { ["key"] = key, ["encrypted"] = encrypted }.ToJsonString();
                directory.Write("p-" + physical + ".json", wrapper, Limit); stage("physical-written");
                directory.Write("r-" + key + ".json", encrypted, Limit); stage("archive-written");
                if (Physical(directory, context.Crypto, physical)?.Encrypted != encrypted || directory.Read("r-" + key + ".json", Limit) != encrypted)
                    throw new IOException("notes_request_durability_unconfirmed");
            }
        }
        stage("after-readback");
        var check = pending.CaptureRequestIntention(); check.Frame["physical"] = physical;
        if (check.Binding != captured.Binding || !JsonNode.DeepEquals(check.Frame, frame)) throw new InvalidOperationException("notes_request_native_frame_changed");
        lock (gate)
        {
            if (started != generation) throw new InvalidOperationException("notes_request_process_stopped");
            var proof = new FreshProof(this, pending, key, physical, context.Identity, NotesOriginalSchema.Hash(frame));
            fresh.Add(key, proof); return new(proof);
        }
    }

    private JsonObject CheckStored(FreshProof proof, NotesOriginalJournalCrypto crypto, string identity)
    {
        if (identity != proof.KeyIdentity) throw new InvalidOperationException("notes_request_journal_key_changed");
        using var directory = files.Open() ?? throw new IOException("notes_request_private_history_missing");
        Identity(directory, identity, initialize: false);
        var stored = Physical(directory, crypto, proof.Physical);
        if (stored is null || stored.Value.Key != proof.Key || NotesOriginalSchema.Hash(stored.Value.Frame) != proof.FrameHash ||
            directory.Read("r-" + proof.Key + ".json", Limit) != stored.Value.Encrypted)
            throw new InvalidOperationException("notes_request_physical_history_changed");
        return stored.Value.Frame.DeepClone().AsObject();
    }

    internal (string Key, string KeyIdentity, JsonObject Frame) SavedRequest(NotesOriginalPendingResult pending)
    {
        pending.ConfirmedSave(); // Actual native callback before file/registry locks.
        RecoveryContext? repair;
        lock (gate) recovered.TryGetValue(pending, out repair);
        if (repair is not null) return SavedRecovered(pending, repair);
        var context = Crypto(); JsonObject record; FreshProof proof;
        lock (gate)
        {
            proof = fresh.Values.SingleOrDefault(value => ReferenceEquals(value.Pending, pending)) ??
                throw new InvalidOperationException("notes_request_owned_saved_context_required");
            record = CheckStored(proof, context.Crypto, context.Identity);
        }
        pending.ConfirmedSave();
        return (proof.Key, proof.KeyIdentity, record);
    }

    private JsonObject RequireFresh(FreshProof proof, NotesOriginalNegotiation protocol)
    {
        // No registry/file lock is held across native source/book/tree callbacks.
        var captured = proof.Pending.CaptureRequestIntention(); var context = Crypto();
        var source = captured.Frame["source"]!.AsObject(); var pins = protocol.RequireCurrent();
        if (source["peer"]![0]!.GetValue<string>() != pins.Peer.Id || source["peer"]![1]!.GetValue<string>() != pins.Peer.PublicKey ||
            source["own"]![0]!.GetValue<string>() != pins.Own.Id || source["own"]![1]!.GetValue<string>() != pins.Own.PublicKey)
            throw new InvalidOperationException("notes_request_protocol_pins_changed");
        captured.Frame["physical"] = context.Crypto.Physical(captured.Binding, NotesOriginalSchema.Text(source, "local_id"));
        if (NotesOriginalSchema.Hash(captured.Frame) != proof.FrameHash) throw new InvalidOperationException("notes_request_native_frame_changed");
        lock (gate)
        {
            if (!fresh.TryGetValue(proof.Key, out var owned) || !ReferenceEquals(owned, proof)) throw new InvalidOperationException("notes_request_process_proof_expired");
            CheckStored(proof, context.Crypto, context.Identity);
        }
        var final = proof.Pending.CaptureRequestIntention(); final.Frame["physical"] = proof.Physical;
        if (final.Binding != captured.Binding || NotesOriginalSchema.Hash(final.Frame) != proof.FrameHash)
            throw new InvalidOperationException("notes_request_native_frame_changed");
        protocol.RequireCurrent(); return proof.Pending.Request();
    }

    internal JsonObject? LoadPhysical(string nativeBinding, string localId)
    {
        var context = Crypto(); var physical = context.Crypto.Physical(nativeBinding, localId);
        using var directory = files.Open(); if (directory is null) return null;
        Identity(directory, context.Identity, initialize: false);
        return Physical(directory, context.Crypto, physical)?.Frame.DeepClone().AsObject(); // No fresh proof issued.
    }

    internal UnconfirmedQuery ReadOnlyQuery(string nativeBinding, string localId, NotesOriginalChoiceStore consent, NotesOriginalNegotiation protocol)
    {
        var frame = LoadPhysical(nativeBinding, localId) ?? throw new InvalidOperationException("notes_request_private_history_required");
        if (NotesOriginalSchema.Text(frame, "state") != "request_pending") throw new InvalidOperationException("notes_request_already_settled");
        long epoch; lock (gate) epoch = generation;
        var proof = new QueryProof(this, consent, nativeBinding, localId, NotesOriginalSchema.Hash(frame), epoch);
        RequireQuery(proof, protocol); return new(proof);
    }

    internal void Retire(NotesOriginalSavedAckIntents.TerminalProof terminal)
    {
        var release = terminal.RequireFor(this); var context = Crypto();
        var physical = NotesOriginalSchema.Text(release.Original, "physical"); var key = RecordKey(physical, release.Original);
        var encrypted = context.Crypto.Seal(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, key, release.Settled);
        lock (gate)
        {
            using var directory = files.Open() ?? throw new IOException("notes_request_private_history_missing");
            Identity(directory, context.Identity, initialize: false);
            var current = Physical(directory, context.Crypto, physical) ?? throw new IOException("notes_request_physical_missing");
            var archive = directory.Read("r-" + key + ".json", Limit) ?? throw new IOException("notes_request_archive_missing");
            var decoded = Validate(key, physical, context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, key, archive));
            if (current.Key != key ||
                !JsonNode.DeepEquals(current.Frame, release.Original) && !JsonNode.DeepEquals(current.Frame, release.Settled) ||
                !JsonNode.DeepEquals(decoded, release.Original) && !JsonNode.DeepEquals(decoded, release.Settled))
                throw new InvalidOperationException("notes_request_retirement_history_changed");
            // Archive first, physical slot last. A partial transition remains
            // held; only this exact durable terminal proof can repair it.
            directory.Write("r-" + key + ".json", encrypted, Limit); stage("retired-archive-written");
            directory.Write("p-" + physical + ".json", new JsonObject { ["key"] = key, ["encrypted"] = encrypted }.ToJsonString(), Limit);
            stage("retired-physical-written");
            if (Physical(directory, context.Crypto, physical)?.Encrypted != encrypted || directory.Read("r-" + key + ".json", Limit) != encrypted)
                throw new IOException("notes_request_retirement_unconfirmed");
            fresh.Remove(key);
        }
        terminal.RequireFor(this);
    }

    internal bool RetiredArchiveMatches(JsonObject settled)
    {
        var context = Crypto(); var physical = NotesOriginalSchema.Text(settled, "physical"); var key = RecordKey(physical, settled);
        using var directory = files.Open(); if (directory is null) return false;
        Identity(directory, context.Identity, initialize: false);
        var stored = Physical(directory, context.Crypto, physical);
        return stored is not null && JsonNode.DeepEquals(stored.Value.Frame, settled) &&
            directory.Read("r-" + key + ".json", Limit) == stored.Value.Encrypted;
    }

    private JsonObject RequireQuery(QueryProof proof, NotesOriginalNegotiation protocol)
    {
        lock (gate) if (generation != proof.Generation) throw new InvalidOperationException("notes_request_query_process_expired");
        var pins = protocol.RequireCurrent();
        var frame = LoadPhysical(proof.Binding, proof.LocalId) ?? throw new InvalidOperationException("notes_request_private_history_required");
        if (NotesOriginalSchema.Hash(frame) != proof.FrameHash || proof.Consent.VerifyUnconfirmedHistory(frame) != proof.Binding)
            throw new InvalidOperationException("notes_request_unconfirmed_context_changed");
        var source = frame["source"]!.AsObject();
        if (source["peer"]![0]!.GetValue<string>() != pins.Peer.Id || source["peer"]![1]!.GetValue<string>() != pins.Peer.PublicKey ||
            source["own"]![0]!.GetValue<string>() != pins.Own.Id || source["own"]![1]!.GetValue<string>() != pins.Own.PublicKey)
            throw new InvalidOperationException("notes_request_query_protocol_pins_changed");
        var body = new JsonObject { ["art"] = "kontakt_original_statusanfrage", ["fassung"] = 1, ["request_sha256"] = frame["request_sha256"]!.DeepClone() };
        foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) body[name] = frame["request"]![name]!.DeepClone();
        protocol.RequireCurrent();
        lock (gate) if (generation != proof.Generation) throw new InvalidOperationException("notes_request_query_process_expired");
        return body;
    }

    internal void Stop() { lock (gate) { generation++; fresh.Clear(); recovered.Clear(); } } // Disk holds deliberately survive.
}
