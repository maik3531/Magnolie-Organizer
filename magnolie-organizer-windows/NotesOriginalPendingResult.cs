using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Native draft building blocks only. No renderer factory, durable source consent,
// provider-send nonce, production sender or ACK-history issuer is supplied here.
internal sealed class NotesOriginalExportChoice
{
    private readonly JsonObject export;
    private readonly MagnolienbaumCoordinator.NativeNotesOrigin origin;
    private readonly string transport, bookSource, localId, localUid;
    private readonly Func<NativeActorBookSnapshot?> capture;
    private readonly Action requireNativeSelection;
    private volatile bool active = true;
    internal sealed record PendingSeed(NotesOriginalExportChoice Choice, NativeActorBookSnapshot Snapshot, JsonObject Request,
        string Id, string Uid, long BeforeRevision, Func<NativeActorBookSnapshot?> Capture);
    private sealed record PendingProof(PendingSeed Seed);

    internal static PendingSeed ReadPendingProof(object proof) => proof is PendingProof native
        ? native.Seed with { Request = native.Seed.Request.DeepClone().AsObject() }
        : throw new InvalidOperationException("notes_original_owned_pending_required");
    internal (MagnolienbaumCoordinator.NotesPins Peer, MagnolienbaumCoordinator.NotesPins Own) Pins { get; }

    internal NotesOriginalExportChoice(JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport,
        NativeActorBookSnapshot snapshot, Func<NativeActorBookSnapshot?> capture,
        Func<IReadOnlyList<JsonObject>, string?> chooseNative, Action requireNativeSelection)
    {
        ArgumentNullException.ThrowIfNull(chooseNative); ArgumentNullException.ThrowIfNull(requireNativeSelection);
        export = body.DeepClone().AsObject(); this.origin = origin; this.transport = transport;
        Pins = origin.RequireCurrent(export, transport);
        NotesOriginalSchema.Fields(export, "art", "fassung", "share_id", "before_basis", "setup_id", "native_revision", "content_sha256", "kontakt");
        if (NotesOriginalSchema.Text(export, "art") != "kontakt_original_export" || NotesOriginalSchema.Integer(export, "fassung") != 1 ||
            !NotesOriginalSchema.Share(NotesOriginalSchema.Text(export, "share_id")) ||
            !NotesOriginalSchema.Hex(NotesOriginalSchema.Text(export, "before_basis")) ||
            !NotesOriginalSchema.Uuid(NotesOriginalSchema.Text(export, "setup_id")) || NotesOriginalSchema.Integer(export, "native_revision") < 0 ||
            export["kontakt"] is not JsonObject contact || NotesOriginalReturnHash.ContentHash(contact) != NotesOriginalSchema.Text(export, "content_sha256"))
            throw new InvalidDataException("notes_original_export_schema");
        this.capture = capture; this.requireNativeSelection = requireNativeSelection;
        bookSource = snapshot.SavedBook.BookSource;
        RequireSnapshot(snapshot);
        var contacts = ContactSourceUpdateRun.SavedContacts(snapshot).OfType<JsonObject>().ToArray();
        var selected = chooseNative(contacts.Select(item => item.DeepClone().AsObject()).ToArray());
        var matches = contacts.Where(item => NotesOriginalSchema.Text(item, "id") == selected).ToArray();
        if (matches.Length != 1 || string.IsNullOrEmpty(selected) || string.IsNullOrEmpty(NotesOriginalSchema.Text(matches[0], "uid")))
            throw new InvalidOperationException("notes_original_native_contact_choice_required");
        localId = selected; localUid = NotesOriginalSchema.Text(matches[0], "uid");
        RequireSnapshot(snapshot); RequireCurrent();
    }

    private void RequireSnapshot(NativeActorBookSnapshot expected)
    {
        var current = capture();
        if (current?.SavedBook != expected.SavedBook || current.Text != expected.Text)
            throw new InvalidOperationException("notes_original_export_book_changed");
    }

    internal void Revoke() => active = false;

    internal void RequireCurrent()
    {
        if (!active) throw new InvalidOperationException("notes_original_native_choice_revoked");
        requireNativeSelection(); origin.RequireCurrent(export, transport);
        var current = capture();
        if (current is null || current.SavedBook.BookSource != bookSource)
            throw new InvalidOperationException("notes_original_export_book_changed");
        var matches = ContactSourceUpdateRun.SavedContacts(current).OfType<JsonObject>()
            .Where(item => NotesOriginalSchema.Text(item, "id") == localId).ToArray();
        if (matches.Length != 1 || NotesOriginalSchema.Text(matches[0], "uid") != localUid)
            throw new InvalidOperationException("notes_original_export_contact_changed");
        origin.RequireCurrent(export, transport); requireNativeSelection();
        if (!active) throw new InvalidOperationException("notes_original_native_choice_revoked");
    }

    internal NotesOriginalPendingResult? CreatePending()
    {
        RequireCurrent();
        var snapshot = capture() ?? throw new InvalidOperationException("notes_original_book_not_saved");
        var local = ContactSourceUpdateRun.SavedContacts(snapshot).OfType<JsonObject>()
            .Single(item => NotesOriginalSchema.Text(item, "id") == localId);
        var before = export["kontakt"]!.AsObject();
        var patch = Project(local, before);
        var changed = patch.Any(pair => !JsonNode.DeepEquals(pair.Value, before[pair.Key] ??
            (pair.Key is "vcardName" or "anschriften" ? new JsonArray() : JsonValue.Create(""))));
        if (!changed) return null;
        var target = before.DeepClone().AsObject();
        foreach (var pair in patch) target[pair.Key] = pair.Value?.DeepClone();
        var request = new JsonObject { ["art"] = "kontakt_original_anfrage", ["fassung"] = 1,
            ["request_id"] = Guid.NewGuid().ToString(), ["share_id"] = export["share_id"]!.DeepClone(),
            ["before_basis"] = export["before_basis"]!.DeepClone(), ["target_sha256"] = NotesOriginalReturnHash.ContentHash(target), ["ziel"] = patch };
        RequireSnapshot(snapshot); RequireCurrent();
        return new(new PendingProof(new(this, snapshot, request, localId, localUid, NotesOriginalSchema.Integer(export, "native_revision"), capture)));
    }

    internal static JsonObject Project(JsonObject contact, JsonObject before)
    {
        var patch = new JsonObject();
        foreach (var name in new[] { "vorname", "nachname", "firma", "notiz", "geburtstag", "jubilaeum", "anzeigename" })
            patch[name] = NotesOriginalSchema.Text(contact, name);
        if (contact["geburtstagJahrUnbekannt"] is JsonValue flag && flag.TryGetValue<bool>(out var unknown) && unknown &&
            Regex.IsMatch(patch["geburtstag"]!.GetValue<string>(), @"^\d{4}-\d{2}-\d{2}$", RegexOptions.CultureInvariant))
            patch["geburtstag"] = "--" + patch["geburtstag"]!.GetValue<string>()[5..];
        var names = contact.ContainsKey("vcardRoundtrip") ? contact["vcardRoundtrip"] as JsonArray : new JsonArray();
        if (names is null) throw new InvalidDataException("notes_original_saved_name_projection");
        var selectedNames = new JsonArray();
        foreach (var node in names)
        {
            var text = NotesOriginalSchema.String(node);
            if (Regex.IsMatch(text, @"^(?:[A-Za-z0-9-]+\.)?(?:N|FN)[;:]", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
                selectedNames.Add(text);
        }
        patch["vcardName"] = selectedNames;
        var rows = contact.ContainsKey("anschriften") ? contact["anschriften"] as JsonArray : new JsonArray();
        if (rows is null) throw new InvalidDataException("notes_original_saved_postal_projection");
        if (rows.Count == 0 && new[] { "strasse", "plz", "ort" }.Any(name => NotesOriginalSchema.Text(contact, name).Length > 0))
        {
            var fallback = new JsonObject();
            foreach (var name in new[] { "strasse", "plz", "ort" }) fallback[name] = NotesOriginalSchema.Text(contact, name);
            rows = new JsonArray(fallback);
        }
        var postal = new JsonArray();
        foreach (var node in rows)
        {
            if (node is not JsonObject row || NotesOriginalSchema.Text(row, "postfach").Length > 0 || NotesOriginalSchema.Text(row, "zusatz").Length > 0)
                throw new InvalidDataException("notes_original_saved_postal_projection");
            var fields = new JsonObject();
            foreach (var name in new[] { "strasse", "plz", "ort", "region", "land" }) fields[name] = NotesOriginalSchema.Text(row, name);
            var types = row.ContainsKey("typen") ? row["typen"] as JsonArray : new JsonArray();
            if (types is null) throw new InvalidDataException("notes_original_saved_postal_projection");
            var labels = types.Select(NotesOriginalSchema.String).ToArray();
            var label = NotesOriginalSchema.Text(row, "label"); string kind;
            if (label.Length > 0)
            {
                var same = (before["anschriften"] as JsonArray ?? new()).OfType<JsonObject>().Where(value =>
                    NotesOriginalSchema.Text(value, "art") == label && fields.All(pair => JsonNode.DeepEquals(pair.Value, value[pair.Key]))).ToArray();
                if (same.Length != 1) throw new InvalidDataException("notes_original_saved_postal_label_not_supported");
                kind = label;
            }
            else if (labels.SequenceEqual(new[] { "HOME" })) kind = "privat";
            else if (labels.SequenceEqual(new[] { "WORK" })) kind = "arbeit";
            else if (labels.Length == 0 || labels.SequenceEqual(new[] { "OTHER" })) kind = "sonstige";
            else throw new InvalidDataException("notes_original_saved_postal_kind_not_supported");
            fields["art"] = kind; postal.Add(fields);
        }
        patch["anschriften"] = postal;
        return patch;
    }
}

internal sealed class NotesOriginalPendingResult
{
    private readonly object gate = new();
    private readonly NotesOriginalExportChoice choice;
    private readonly NativeActorBookSnapshot snapshot;
    private readonly JsonObject request;
    private readonly string id, uid, requestHash;
    private readonly long beforeRevision;
    private readonly Func<NativeActorBookSnapshot?> capture;
    private Result? result;
    private bool held;
    private ContactSourceSavedCommit? commitOwner;
    private NativeCommit? commit;
    private sealed record Result(JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport);
    internal sealed record NativeCommit(ContactSourceCommitOffer Offer, string Text, ContactSourceSavedCommit.SaveInvocation Invocation);

    internal NotesOriginalPendingResult(object proof)
    {
        var seed = NotesOriginalExportChoice.ReadPendingProof(proof);
        choice = seed.Choice; snapshot = seed.Snapshot; request = seed.Request;
        id = seed.Id; uid = seed.Uid; beforeRevision = seed.BeforeRevision; capture = seed.Capture;
        requestHash = NotesOriginalSchema.Hash(request);
    }

    internal JsonObject Request() => request.DeepClone().AsObject(); // No provider-send admission is exposed.

    internal void StageResult(JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport)
    {
        // Receive-only: no book/source callback, writer gate or IO.
        var owned = body.DeepClone().AsObject();
        if (origin.RequireCurrent(owned, transport) != choice.Pins) throw new InvalidOperationException("notes_original_pending_peer_changed");
        NotesOriginalSchema.Fields(owned, "art", "fassung", "request_id", "request_sha256", "share_id", "before_basis", "target_sha256", "receipt_id", "native_revision", "next_basis");
        if (NotesOriginalSchema.Text(owned, "art") != "kontakt_original_ergebnis" || NotesOriginalSchema.Integer(owned, "fassung") != 1 ||
            new[] { "request_id", "share_id", "before_basis", "target_sha256" }.Any(name => NotesOriginalSchema.Text(owned, name) != NotesOriginalSchema.Text(request, name)) ||
            NotesOriginalSchema.Text(owned, "request_sha256") != requestHash || !NotesOriginalSchema.Uuid(NotesOriginalSchema.Text(owned, "receipt_id")) ||
            NotesOriginalSchema.Integer(owned, "native_revision") <= beforeRevision || !NotesOriginalSchema.Hex(NotesOriginalSchema.Text(owned, "next_basis")) ||
            NotesOriginalSchema.Text(owned, "next_basis") == NotesOriginalSchema.Text(request, "before_basis"))
            throw new InvalidDataException("notes_original_pending_result_changed");
        origin.RequireCurrent(owned, transport);
        lock (gate)
        {
            if (result is not null && !MagnolienbaumCrypto.Canonical(result.Body).AsSpan().SequenceEqual(MagnolienbaumCrypto.Canonical(owned)))
            {
                held = true;
                throw new InvalidOperationException("notes_original_pending_result_held");
            }
            result ??= new(owned, origin, transport);
        }
    }

    private Result RequireOrigin()
    {
        choice.RequireCurrent(); Result current;
        lock (gate)
        {
            if (held) throw new InvalidOperationException("notes_original_pending_result_held");
            current = result ?? throw new InvalidOperationException("notes_original_pending_result_required");
        }
        current.Origin.RequireCurrent(current.Body, current.Transport); choice.RequireCurrent();
        return current;
    }

    internal NativeCommit PrepareCommit(ContactSourceSavedCommit nativeCommit)
    {
        // Native worker under its existing mutation gate, never FS1 receive.
        var received = RequireOrigin();
        if (commit is not null)
        {
            if (!ReferenceEquals(commitOwner, nativeCommit)) throw new InvalidOperationException("notes_original_commit_owner_changed");
            return commit;
        }
        var current = capture();
        if (current?.SavedBook != snapshot.SavedBook || current.Text != snapshot.Text)
            throw new InvalidOperationException("notes_original_pending_book_changed");
        var book = JsonNode.Parse(snapshot.Text)!.AsObject();
        var contacts = book["kontakte"]!.AsArray();
        var selected = contacts.OfType<JsonObject>().Where(item => NotesOriginalSchema.Text(item, "id") == id && NotesOriginalSchema.Text(item, "uid") == uid).ToArray();
        if (selected.Length != 1) throw new InvalidOperationException("notes_original_pending_contact_changed");
        var body = received.Body;
        selected[0]["notesOriginalBasis"] = new JsonObject { ["fassung"] = 1, ["share_id"] = body["share_id"]!.DeepClone(),
            ["basis"] = body["next_basis"]!.DeepClone(), ["native_revision"] = NotesOriginalSchema.Integer(body, "native_revision").ToString(CultureInfo.InvariantCulture),
            ["request_id"] = body["request_id"]!.DeepClone(), ["request_sha256"] = body["request_sha256"]!.DeepClone(),
            ["target_sha256"] = body["target_sha256"]!.DeepClone(), ["receipt_id"] = body["receipt_id"]!.DeepClone() };
        var offer = nativeCommit.Stage(snapshot, new(snapshot.SavedBook, contacts, new Dictionary<string, ContactSyncCounts>()), () => { RequireOrigin(); });
        var text = book.ToJsonString();
        commitOwner = nativeCommit;
        return commit = new(offer, text, nativeCommit.Prepare(offer.Token, book));
    }

    internal ContactSourceSavedCommit.SavedWitness ConfirmedSave()
    {
        RequireOrigin();
        if (commit is null || commitOwner is null) throw new InvalidOperationException("notes_original_save_unconfirmed");
        var witness = commitOwner.ConfirmedSave(commit.Offer.Token);
        _ = witness.RequireCurrent(); RequireOrigin(); _ = witness.RequireCurrent();
        return witness; // No wire ACK or durable history is minted here.
    }
}

internal static class NotesOriginalSchema
{
    internal static void Fields(JsonObject value, params string[] names)
    { if (value.Count != names.Length || names.Any(name => !value.ContainsKey(name))) throw new InvalidDataException("notes_original_schema"); }
    internal static string String(JsonNode? value) => value is JsonValue scalar && scalar.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("notes_original_text_required");
    internal static string Text(JsonObject value, string name) => value.ContainsKey(name) ? String(value[name]) : "";
    internal static long Integer(JsonObject value, string name)
    {
        if (value[name] is JsonValue scalar)
        {
            if (scalar.TryGetValue<long>(out var number)) return number;
            if (scalar.TryGetValue<int>(out var integer)) return integer;
        }
        throw new InvalidDataException("notes_original_integer_required");
    }
    internal static bool Hex(string value) => value.Length == 64 && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
    internal static bool Uuid(string value) => Guid.TryParseExact(value, "D", out var parsed) && parsed.ToString() == value;
    internal static bool Share(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Any(char.IsControl)) return false;
        for (var index = 0; index < value.Length; index++)
            if (char.IsSurrogate(value[index]))
            {
                if (!char.IsHighSurrogate(value[index]) || index + 1 >= value.Length || !char.IsLowSurrogate(value[index + 1])) return false;
                index++;
            }
        return value.EnumerateRunes().Count() <= 128;
    }
    internal static string Hash(JsonObject body) => Convert.ToHexString(SHA256.HashData(MagnolienbaumCrypto.Canonical(body))).ToLowerInvariant();
}
