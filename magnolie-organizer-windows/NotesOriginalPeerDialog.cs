namespace MagnolieOrganizer.Windows;

internal static class NotesOriginalPeerDialog
{
    internal static Task<string?> ChooseAsync(Form owner, IReadOnlyList<MagnolienbaumCoordinator.NotesSetupPeerView> peers,
        Func<string, string> translate, CancellationToken cancellation)
    {
        var result = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Show()
        {
            try
            {
                cancellation.ThrowIfCancellationRequested();
                using var dialog = new Form { Text = translate("Notes original source"), Width = 840, Height = 400,
                    StartPosition = FormStartPosition.CenterParent, MinimizeBox = false, MaximizeBox = false, ShowInTaskbar = false };
                var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 1, RowCount = 2 };
                layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                var list = new ListBox { Dock = DockStyle.Fill, SelectionMode = SelectionMode.One, HorizontalScrollbar = true };
                foreach (var peer in peers) list.Items.Add(string.Join(" — ", new[] { peer.Label, peer.Id, peer.PublicKey }.Select(NotesOriginalSetupDialog.Display)));
                list.SelectedIndex = -1;
                var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
                var cancel = new Button { Text = translate("Cancel"), AutoSize = true, DialogResult = DialogResult.Cancel };
                var select = new Button { Text = translate("Select"), AutoSize = true, Enabled = false, DialogResult = DialogResult.OK };
                list.SelectedIndexChanged += (_, _) => select.Enabled = list.SelectedIndex >= 0;
                buttons.Controls.Add(cancel); buttons.Controls.Add(select); layout.Controls.Add(list); layout.Controls.Add(buttons);
                dialog.Controls.Add(layout); dialog.AcceptButton = select; dialog.CancelButton = cancel;
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
                result.TrySetResult(accepted && list.SelectedIndex >= 0 ? peers[list.SelectedIndex].Id : null);
            }
            catch (OperationCanceledException) { result.TrySetCanceled(cancellation); }
            catch (Exception error) { result.TrySetException(error); }
        }
        try { if (owner.InvokeRequired) owner.BeginInvoke(Show); else Show(); }
        catch (Exception error) { result.TrySetException(error); }
        return result.Task;
    }
}
