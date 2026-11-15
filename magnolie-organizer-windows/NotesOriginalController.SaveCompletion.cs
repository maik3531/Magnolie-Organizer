using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalController
{
    private sealed class CompletionNative(NotesOriginalController controller, Work work, string text, string token)
    {
        internal readonly NotesOriginalController Controller = controller;
        internal readonly Work Work = work;
        internal readonly string Text = text, Token = token;
        internal int Started, Finished;
    }
    internal sealed class SaveCompletion(object proof)
    {
        private CompletionNative Native() => proof as CompletionNative ?? throw new InvalidOperationException("notes_controller_native_completion_required");
        internal void Begin(string text, string token, NotesOriginalBootstrapSave? bootstrap)
        {
            var native = Native();
            if (Interlocked.CompareExchange(ref native.Started, 1, 0) != 0) throw new InvalidOperationException("notes_controller_save_completion_already_used");
            native.Controller.RequireSaveWork(native.Work);
            if (text != native.Text || token != native.Token ||
                !ReferenceEquals(native.Work.Kind == "bootstrap" ? native.Work.Invocation : null, bootstrap))
                throw new InvalidOperationException("notes_controller_exact_save_work_required");
        }
        internal void Complete()
        {
            var native = Native();
            if (Volatile.Read(ref native.Started) != 1 || Interlocked.CompareExchange(ref native.Finished, 1, 0) != 0)
                throw new InvalidOperationException("notes_controller_save_completion_not_started");
            native.Controller.AfterNativeSave(native.Work); // Actual writer witness, before releasing serial native save gate.
        }
        internal void Failed()
        {
            var native = Native();
            Interlocked.Exchange(ref native.Finished, 1);
            native.Controller.FailSaveWork(native.Work); // Memory lane only. Disk reservation/history survive.
        }
    }

    internal SaveCompletion PrepareSaveCompletion(Work work)
    {
        RequireSaveWork(work);
        if (work.Kind == "bootstrap" && work.Invocation is NotesOriginalBootstrapSave bootstrap)
            return new(new CompletionNative(this, work, bootstrap.Text, ""));
        if (work.Kind == "save" && work.Invocation is NotesOriginalPendingResult.NativeCommit commit)
            return new(new CompletionNative(this, work, commit.Text, commit.Offer.Token));
        throw new InvalidOperationException("notes_controller_native_save_work_required");
    }

    private void RequireSaveWork(Work work)
    {
        lock (gate)
        {
            RequireActive();
            if (work.Kind == "bootstrap")
            {
                if (bootstrap is null || !ReferenceEquals(bootstrap.Invocation, work.Invocation) || (bootstrap.Owner?.Id ?? "") != work.RequestId)
                    throw new InvalidOperationException("notes_controller_owned_bootstrap_required");
            }
            else if (work.Kind != "save" || !owners.Values.Any(owner => !owner.Held && owner.Id == work.RequestId && ReferenceEquals(owner.Commit, work.Invocation)))
                throw new InvalidOperationException("notes_controller_owned_metadata_save_required");
        }
        if (!ready()) throw new InvalidOperationException("notes_controller_native_ui_not_ready"); // Restriction only, never a grant.
    }

    private void FailSaveWork(Work work)
    {
        lock (gate)
        {
            if (work.Kind == "bootstrap" && bootstrap is not null && ReferenceEquals(bootstrap.Invocation, work.Invocation))
            {
                var lease = bootstrap; bootstrap = null; ForgetFrame(lease.Frame);
                if (lease.Owner is not null) Drop(lease.Owner);
                Hold("bootstrap-save");
            }
            else if (work.Kind == "save")
            {
                var owner = owners.Values.SingleOrDefault(value => value.Id == work.RequestId && ReferenceEquals(value.Commit, work.Invocation));
                if (owner is not null) { Drop(owner); Hold("metadata-save"); }
            }
        }
    }
}
