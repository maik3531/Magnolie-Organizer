namespace MagnolieOrganizer.Windows;

internal static class ContactSourceApprovalDialog
{
    internal static Task<IReadOnlyList<string>?> ChooseAsync(Form owner,
        IReadOnlyList<NextcloudDavSource> sources, IReadOnlyList<string> selected,
        Func<string, string> translate, CancellationToken cancellation)
    {
        var result = new TaskCompletionSource<IReadOnlyList<string>?>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Show()
        {
            try
            {
                cancellation.ThrowIfCancellationRequested();
                using var dialog = new Form { Text = translate("Original contact sources"), Width = 760, Height = 460,
                    StartPosition = FormStartPosition.CenterParent, MinimizeBox = false, MaximizeBox = false,
                    ShowInTaskbar = false };
                var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 1, RowCount = 3 };
                layout.RowStyles.Add(new RowStyle(SizeType.AutoSize)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
                layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                var message = new Label { AutoSize = true, MaximumSize = new Size(700, 0), Text = translate(
                    "Allow updates to selected original address books for this session only. Automatic updates require Wi-Fi and existing contact bindings. No contacts will be created or deleted. Locking or changing accounts requires approval again.") };
                var choices = new CheckedListBox { Dock = DockStyle.Fill, CheckOnClick = true, HorizontalScrollbar = true };
                foreach (var source in sources)
                {
                    // Native text controls only: strip controls/bidi from the
                    // untrusted display name; always show the exact collection.
                    var name = new string(source.Name.Where(value => !char.IsControl(value) &&
                        value is not ('\u061c' or '\u200e' or '\u200f' or >= '\u202a' and <= '\u202e' or >= '\u2066' and <= '\u2069')).Take(256).ToArray());
                    choices.Items.Add(name + " — " + source.Href.AbsoluteUri, selected.Contains(source.Uid, StringComparer.Ordinal));
                }
                var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
                var cancel = new Button { Text = translate("Cancel"), AutoSize = true, DialogResult = DialogResult.Cancel };
                var accept = new Button { Text = translate("Apply"), AutoSize = true, DialogResult = DialogResult.OK };
                buttons.Controls.Add(cancel); buttons.Controls.Add(accept);
                layout.Controls.Add(message); layout.Controls.Add(choices); layout.Controls.Add(buttons); dialog.Controls.Add(layout);
                dialog.AcceptButton = accept; dialog.CancelButton = cancel;
                // Closing/cancelling is not an affirmative permission decision.
                dialog.Shown += (_, _) =>
                {
                    if (cancellation.IsCancellationRequested) { dialog.DialogResult = DialogResult.Cancel; dialog.Close(); }
                    else cancel.Focus();
                };
                using var registration = cancellation.Register(() =>
                {
                    try { if (dialog.IsHandleCreated && !dialog.IsDisposed) dialog.BeginInvoke(() => { dialog.DialogResult = DialogResult.Cancel; dialog.Close(); }); }
                    catch (InvalidOperationException) { }
                });
                var accepted = dialog.ShowDialog(owner) == DialogResult.OK;
                cancellation.ThrowIfCancellationRequested();
                result.TrySetResult(accepted ? choices.CheckedIndices.Cast<int>().Select(index => sources[index].Uid).ToArray() : null);
            }
            catch (OperationCanceledException) { result.TrySetCanceled(cancellation); }
            catch (Exception error) { result.TrySetException(error); }
        }
        try { if (owner.InvokeRequired) owner.BeginInvoke(Show); else Show(); }
        catch (Exception error) { result.TrySetException(error); }
        return result.Task;
    }
}
