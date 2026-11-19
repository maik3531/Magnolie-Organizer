using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalChoiceStore
{
    private sealed class SetupProof(NotesOriginalChoiceStore store, RawState expected, NativeActorBookSnapshot snapshot,
        ContactSourcePrimaryBook primary, bool addition, long version)
    {
        internal readonly NotesOriginalChoiceStore Store = store;
        internal readonly RawState Expected = expected;
        internal readonly NativeActorBookSnapshot Snapshot = snapshot;
        internal readonly ContactSourcePrimaryBook Primary = primary;
        internal readonly bool Addition = addition;
        internal readonly long Version = version;
        internal int Used;
    }
    private long setupVersion;
    internal sealed class SetupDecision(object proof)
    {
        private SetupProof Native() => proof as SetupProof ?? throw new InvalidOperationException("notes_setup_native_decision_required");
        internal NativeActorBookSnapshot Snapshot => Native().Snapshot;
        internal bool IsAddition => Native().Addition;
        internal void RequireCurrent(NotesOriginalChoiceStore owner)
        {
            var native = Native();
            if (!ReferenceEquals(native.Store, owner)) throw new InvalidOperationException("notes_setup_decision_owner_changed");
            if (Volatile.Read(ref native.Used) != 0) throw new InvalidOperationException("notes_setup_decision_already_used");
            owner.RequireSetupContext(native);
            if (owner.ReadRaw() != native.Expected) throw new InvalidOperationException("notes_setup_context_changed");
            owner.RequireSetupContext(native);
        }
        internal void Cancel() => Interlocked.Exchange(ref Native().Used, 1); // Memory only, no empty key creation.
        internal void Commit(NotesOriginalExportChoice choice)
        {
            var native = Native();
            if (Interlocked.CompareExchange(ref native.Used, 1, 0) != 0) throw new InvalidOperationException("notes_setup_decision_already_used");
            native.Store.CommitSetup(native, choice);
        }
    }

    // Called under the actual native book gate BEFORE showing the native dialog.
    // Authenticating a private record or capturing a book does not grant a source.
    internal SetupDecision BeginSetupDecision()
    {
        var version = Volatile.Read(ref setupVersion);
        RawState expected; State? observed;
        using (var directory = files.Open())
        {
            expected = directory is null ? new(null, null, null, null) : Raw(directory);
            observed = directory is null ? null : Read(directory);
        }
        using var state = observed;
        if (state?.Intent is not null) throw new InvalidOperationException("notes_setup_pending_book_intent");
        var snapshot = capture() ?? throw new InvalidOperationException("notes_choice_real_saved_book_required");
        var actual = primary(); var nativeBinding = binding();
        if (!Path.IsPathFullyQualified(nativeBinding) || actual.Binding != Path.GetFullPath(nativeBinding) ||
            actual.PlainHash != snapshot.SavedBook.Sha256 || actual.Content != NativeBookJson.Hash(JsonNode.Parse(snapshot.Text)!))
            throw new InvalidOperationException("notes_choice_native_primary_changed");
        var adding = state is not null && state.Payload["choices"]!.AsArray().Count > 0;
        if (adding)
        {
            var known = ReadKnown();
            if (known is null || known.Identity != state!.Identity || Canonical(known.Payload) != Canonical(state.Payload) || known.Snapshot.SavedBook != snapshot.SavedBook)
                throw new InvalidOperationException("notes_choice_recognized_native_book_required");
        }
        if (Volatile.Read(ref setupVersion) != version || ReadRaw() != expected || capture()?.SavedBook != snapshot.SavedBook || !actual.Same(primary()))
            throw new InvalidOperationException("notes_setup_context_changed");
        return new(new SetupProof(this, expected, snapshot, actual, adding, version));
    }
    private void CommitSetup(SetupProof proof, NotesOriginalExportChoice choice)
    {
        if (choice is null || ReadRaw() != proof.Expected)
            throw new InvalidOperationException("notes_setup_context_changed");
        RequireSetupContext(proof);
        // Pass the BEFORE-dialog CAS through to the actual publication, not a
        // Boolean precheck followed by a fresh replacement decision snapshot.
        if (proof.Addition) AddSourcesCore([choice], proof.Expected, () => RequireSetupContext(proof));
        else ApproveCore([choice], proof.Expected, () => RequireSetupContext(proof));
    }
    private void RequireSetupContext(SetupProof proof)
    {
        if (!ReferenceEquals(proof.Store, this) || Volatile.Read(ref setupVersion) != proof.Version ||
            capture()?.SavedBook != proof.Snapshot.SavedBook || !proof.Primary.Same(primary()))
            throw new InvalidOperationException("notes_setup_context_changed");
    }
}
