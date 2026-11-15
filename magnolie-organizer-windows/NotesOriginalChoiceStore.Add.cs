using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalChoiceStore
{
    // Additions only. Replace/revoke remain separate epoch-changing decisions.
    // Caller uses the native book mutation lane, as for Approve; raw-state CAS
    // additionally rejects concurrent private decisions across store instances.
    internal void AddSources(IReadOnlyList<NotesOriginalExportChoice> selections)
    {
        var choices = selections.ToArray();
        if (choices.Length == 0 || choices.Length > 256) throw new InvalidDataException("notes_choice_addition_budget");
        if (choices.Any(choice => choice is null)) throw new InvalidOperationException("notes_choice_native_selection_required");
        var expected = ReadRaw();
        using var state = Read();
        var known = ReadKnown();
        if (state is null || known is null || state.Intent is not null || state.Identity != known.Identity ||
            Canonical(state.Payload) != Canonical(known.Payload) || ReadRaw() != expected)
            throw new InvalidOperationException("notes_choice_existing_decision_required");
        var actual = primary();
        if (actual.PlainHash != known.Snapshot.SavedBook.Sha256 || actual.Content != Text(state.Payload, "content"))
            throw new InvalidOperationException("notes_choice_native_primary_changed");
        if (choices.Any(choice => choice.NativeBookSource != known.Snapshot.SavedBook.BookSource))
            throw new InvalidOperationException("notes_choice_native_book_changed");
        var sources = choices.Select(choice => choice.PrivateSourceBinding()).ToArray();
        var payload = state.Payload.DeepClone().AsObject();
        var merged = payload["choices"]!.AsArray();
        foreach (var source in sources)
            if (!merged.OfType<JsonObject>().Any(value => Canonical(value) == Canonical(source))) merged.Add(source.DeepClone());
        Validate(payload); // Existing IDs and (peer, own, share) may not be replaced or collide.
        var changed = Canonical(payload) != Canonical(state.Payload);
        var encoded = changed ? EncodePayload(state.Key, payload) : null;
        foreach (var choice in choices) choice.RequireCurrent();
        if (capture()?.SavedBook != known.Snapshot.SavedBook || !actual.Same(primary()))
            throw new InvalidOperationException("notes_choice_native_book_changed");
        for (var index = 0; index < choices.Length; index++) choices[index].AttachConsent(new(new SealProof(this, choices[index], state.Identity,
            Text(payload, "generation"), Text(payload, "book"), Canonical(sources[index]))));
        RawState published;
        using (var directory = files.Open() ?? throw new InvalidOperationException("notes_choice_existing_decision_required"))
        {
            if (Raw(directory) != expected) throw new InvalidOperationException("notes_choice_newer_private_decision");
            if (changed)
            {
                try
                {
                    directory.Write(".transaction", "pending\n", 32);
                    // Keep the exact key envelope, epoch and known-book content.
                    // Pending native book intents are rejected, never discarded.
                    directory.Write("approval.json", encoded!, Limit);
                    directory.Write(".transaction", "clean\n", 32);
                }
                catch { try { directory.Write(".transaction", "pending\n", 32); } catch { } throw; }
            }
            published = Raw(directory);
        }
        try
        {
            if (capture()?.SavedBook != known.Snapshot.SavedBook || !actual.Same(primary()))
                throw new InvalidOperationException("notes_choice_native_book_changed");
            foreach (var choice in choices) choice.RequireCurrent();
        }
        catch
        {
            if (changed)
            {
                using var directory = files.Open();
                if (directory is not null && Raw(directory) == published) directory.Write(".transaction", "pending\n", 32);
            }
            throw;
        }
    }
}
