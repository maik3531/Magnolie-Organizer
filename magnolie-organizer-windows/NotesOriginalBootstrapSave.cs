namespace MagnolieOrganizer.Windows;

// Native-only exact first-save invocation. No key, snapshot, saved witness,
// renderer token, timer or queue is manufactured. Dispatch uses actual SaveAsync.
internal sealed class NotesOriginalBootstrapSave(object proof)
{
    private abstract class Authorized
    {
        internal abstract void RequireCurrent();
        internal abstract string BootstrapText();
        internal abstract NativeActorBookSnapshot? CurrentSaved();
    }
    private sealed class Recovery(NotesOriginalRequestIntents.RecoveryContext context) : Authorized
    {
        internal override void RequireCurrent() => context.RequireCurrent();
        internal override string BootstrapText() => context.BootstrapText();
        internal override NativeActorBookSnapshot? CurrentSaved() => context.CurrentSaved();
    }
    private sealed class Export(NotesOriginalChoiceStore.ExportBootstrapContext context) : Authorized
    {
        internal override void RequireCurrent() => context.RequireCurrent();
        internal override string BootstrapText() => context.BootstrapText();
        internal override NativeActorBookSnapshot? CurrentSaved() => context.CurrentSaved();
    }
    private sealed class Native(Authorized context, string text)
    {
        internal readonly Authorized Context = context;
        internal readonly string Text = text;
        internal readonly object Gate = new();
        internal bool Started;
        internal NativeActorBookSnapshot? Saved;
    }
    private Native Owned() => proof as Native ?? throw new InvalidOperationException("notes_bootstrap_native_context_required");

    internal static NotesOriginalBootstrapSave ForRecovery(NotesOriginalRequestIntents.RecoveryContext context) => Create(new Recovery(context));
    internal static NotesOriginalBootstrapSave ForExport(NotesOriginalChoiceStore.ExportBootstrapContext context) => Create(new Export(context));
    private static NotesOriginalBootstrapSave Create(Authorized context)
    {
        context.RequireCurrent(); var text = context.BootstrapText(); context.RequireCurrent();
        return new(new Native(context, text));
    }

    internal string Text
    {
        get
        {
            var native = Owned(); RequireBefore(native);
            lock (native.Gate) if (native.Started) throw new InvalidOperationException("notes_bootstrap_already_used");
            return native.Text;
        }
    }

    private static void RequireBefore(Native native)
    {
        native.Context.RequireCurrent();
        if (native.Context.CurrentSaved() is not null || native.Context.BootstrapText() != native.Text)
            throw new InvalidOperationException("notes_bootstrap_exact_current_model_required");
        native.Context.RequireCurrent();
    }

    internal void Write(string payload, Action<string> actualNativeWriter)
    {
        ArgumentNullException.ThrowIfNull(actualNativeWriter);
        var native = Owned();
        lock (native.Gate)
        {
            if (native.Started) throw new InvalidOperationException("notes_bootstrap_already_used");
            native.Started = true;
        }
        RequireBefore(native);
        if (payload != native.Text) throw new InvalidOperationException("notes_bootstrap_exact_payload_required");
        actualNativeWriter(payload); // Actual encrypted/atomic writer + real RecordSaved only.
        native.Context.RequireCurrent();
        var saved = native.Context.CurrentSaved() ?? throw new InvalidOperationException("notes_bootstrap_real_save_unconfirmed");
        if (saved.Text != native.Text || saved.SavedBook.Sha256 != BaumSyncSnapshot.Hash(native.Text))
            throw new InvalidOperationException("notes_bootstrap_actual_saved_payload_changed");
        lock (native.Gate) native.Saved = saved;
    }

    internal void RequireCompleted()
    {
        var native = Owned(); native.Context.RequireCurrent(); NativeActorBookSnapshot? saved;
        lock (native.Gate) saved = native.Saved;
        var current = native.Context.CurrentSaved();
        if (saved is null || current?.SavedBook != saved.SavedBook || current.Text != saved.Text)
            throw new InvalidOperationException("notes_bootstrap_real_save_unconfirmed");
    } // Correlation only; not a metadata-saved witness or ACK authority.
}
