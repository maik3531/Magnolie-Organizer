using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalChoiceStore
{
    private sealed record ExportProof(NotesOriginalChoiceStore Store, string Identity, string Generation, string Book,
        string Source, JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport);
    internal sealed class ExportNeedsRealSave(ExportBootstrapContext context) : InvalidOperationException("notes_export_real_native_save_required")
    { internal ExportBootstrapContext Context { get; } = context; }
    internal sealed class ExportBootstrapContext(object proof)
    {
        private ExportProof Native() => proof as ExportProof ?? throw new InvalidOperationException("notes_export_private_context_required");
        internal void RequireCurrent() { var native = Native(); native.Store.RequireExport(native); }
        internal NativeActorBookSnapshot? CurrentSaved() { var native = Native(); return native.Store.RequireExport(native).Snapshot; }
        internal string BootstrapText()
        {
            var native = Native(); var observed = native.Store.RequireExport(native);
            if (observed.Snapshot is not null) throw new InvalidOperationException("notes_export_real_save_already_exists");
            var text = native.Store.currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_export_owned_native_model_required");
            if (BaumSyncSnapshot.Hash(text) != observed.Primary.PlainHash || !observed.Same(native.Store.RequireExport(native)))
                throw new InvalidOperationException("notes_export_native_model_changed");
            return text;
        }
        internal NotesOriginalBootstrapSave PrepareBootstrap() => NotesOriginalBootstrapSave.ForExport(this);
        internal NotesOriginalExportChoice Restore()
        {
            var native = Native();
            if (native.Store.RequireExport(native).Snapshot is null) throw new ExportNeedsRealSave(this);
            return native.Store.Restore(native.Body, native.Origin, native.Transport);
        }
    }

    internal ExportBootstrapContext ExportBootstrap(JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport)
    {
        // Deferred native worker only: schema is not consent or a primary witness.
        var owned = body.DeepClone().AsObject(); var pins = origin.RequireCurrent(owned, transport);
        NotesOriginalExportChoice.ValidateExport(owned);
        using var state = Read() ?? throw new InvalidOperationException("notes_export_private_source_required");
        var matches = state.Payload["choices"]!.AsArray().OfType<JsonObject>().Where(source =>
            Text(source, "share_id") == Text(owned, "share_id") && Text(source, "setup_id") == Text(owned, "setup_id") &&
            source["peer"]![0]!.GetValue<string>() == pins.Peer.Id && source["peer"]![1]!.GetValue<string>() == pins.Peer.PublicKey &&
            source["own"]![0]!.GetValue<string>() == pins.Own.Id && source["own"]![1]!.GetValue<string>() == pins.Own.PublicKey).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("notes_export_private_source_changed");
        var proof = new ExportProof(this, state.Identity, Text(state.Payload, "generation"), Text(state.Payload, "book"),
            Canonical(matches[0]), owned, origin, transport);
        RequireExport(proof); return new(proof);
    }

    private Observation RequireExport(ExportProof proof)
    {
        var pins = proof.Origin.RequireCurrent(proof.Body, proof.Transport);
        NotesOriginalExportChoice.ValidateExport(proof.Body);
        using var state = Read() ?? throw new InvalidOperationException("notes_export_private_source_required");
        var source = Parse(proof.Source); var observed = Observe(requireSaved: false);
        if (state.Identity != proof.Identity || Text(state.Payload, "generation") != proof.Generation || Text(state.Payload, "book") != proof.Book ||
            Text(state.Payload, "book") != Tag(state.Key, "book", observed.Binding) || !RecognizesContent(state, observed.Content) ||
            state.Payload["choices"]!.AsArray().OfType<JsonObject>().Count(value => Canonical(value) == proof.Source) != 1 ||
            source["peer"]![0]!.GetValue<string>() != pins.Peer.Id || source["peer"]![1]!.GetValue<string>() != pins.Peer.PublicKey ||
            source["own"]![0]!.GetValue<string>() != pins.Own.Id || source["own"]![1]!.GetValue<string>() != pins.Own.PublicKey)
            throw new InvalidOperationException("notes_export_private_context_changed");
        var model = observed.Snapshot?.Text ?? currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_export_owned_native_model_required");
        var contacts = JsonNode.Parse(model)!["kontakte"] as JsonArray ?? throw new InvalidDataException("notes_export_native_contacts_required");
        var chosen = contacts.OfType<JsonObject>().Where(value => Text(value, "id") == Text(source, "local_id")).ToArray();
        if (chosen.Length != 1 || Text(chosen[0], "uid") != Text(source, "local_uid")) throw new InvalidOperationException("notes_export_private_contact_changed");
        _ = NotesOriginalExportChoice.Project(chosen[0], proof.Body["kontakt"]!.AsObject());
        using var again = Read();
        if (again is null || again.Identity != state.Identity || Canonical(again.Payload) != Canonical(state.Payload) ||
            !observed.Same(Observe(requireSaved: observed.Snapshot is not null))) throw new InvalidOperationException("notes_export_native_context_changed");
        proof.Origin.RequireCurrent(proof.Body, proof.Transport); return observed;
    }

    internal (string Binding, IReadOnlyList<JsonObject> Sources)? DiscoverySources()
    {
        using var state = Read();
        if (state is null || state.Payload["choices"]!.AsArray().Count == 0) return null;
        var observed = Observe(requireSaved: false);
        if (!RecognizesContent(state, observed.Content) || Text(state.Payload, "book") != Tag(state.Key, "book", observed.Binding))
            throw new InvalidOperationException("notes_discovery_known_native_book_required");
        var model = observed.Snapshot?.Text ?? currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_discovery_owned_native_model_required");
        var contacts = JsonNode.Parse(model)!["kontakte"] as JsonArray ?? throw new InvalidDataException("notes_discovery_native_contacts_required");
        var sources = state.Payload["choices"]!.AsArray().OfType<JsonObject>().Where(source =>
        {
            var selected = contacts.OfType<JsonObject>().Where(value => Text(value, "id") == Text(source, "local_id")).ToArray();
            return selected.Length == 1 && Text(selected[0], "uid") == Text(source, "local_uid");
        }).Select(source => source.DeepClone().AsObject()).ToArray(); // Private schema caps total at 256.
        using var again = Read();
        if (again is null || again.Identity != state.Identity || Canonical(again.Payload) != Canonical(state.Payload) ||
            !observed.Same(Observe(requireSaved: observed.Snapshot is not null))) throw new InvalidOperationException("notes_discovery_private_context_changed");
        return (observed.Binding, sources); // Lookup hints only, no provider mutation/ACK authority.
    }
}
