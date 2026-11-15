namespace MagnolieOrganizer.Windows;

internal static class NotesOriginalSetupDialog
{
    internal static string Display(string value) => new(value.Where(character => !char.IsControl(character) &&
        character is not ('\u061c' or '\u200e' or '\u200f' or >= '\u202a' and <= '\u202e' or >= '\u2066' and <= '\u2069')).ToArray());

    internal static Task<string?> ChooseAsync(Form owner, NotesOriginalSetupFlow.View view,
        Func<string, string> translate, CancellationToken cancellation)
    {
        var result = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Show()
        {
            try
            {
                cancellation.ThrowIfCancellationRequested();
                using var dialog = new Form { Text = translate("Notes original source"), Width = 840, Height = 560,
                    StartPosition = FormStartPosition.CenterParent, MinimizeBox = false, MaximizeBox = false, ShowInTaskbar = false };
                var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 1, RowCount = 4 };
                layout.RowStyles.Add(new RowStyle(SizeType.AutoSize)); layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                var explanation = new Label { AutoSize = true, MaximumSize = new Size(780, 0), Text = translate(view.Addition
                    ? "Add this original source without replacing existing permissions. Select the existing organizer contact explicitly. This grants persistent updates; no original contacts will be created or deleted. Automatic updates wait for Wi-Fi."
                    : "Select the existing organizer contact for this Notes original source explicitly. This grants persistent updates; no original contacts will be created or deleted. Automatic updates wait for Wi-Fi.") };
                var source = new TextBox { Dock = DockStyle.Top, ReadOnly = true, Multiline = true, Height = 108, ScrollBars = ScrollBars.Vertical,
                    Text = Display(view.Peer.Id) + Environment.NewLine + Display(view.Peer.PublicKey) + Environment.NewLine +
                        Display(NotesOriginalSchema.Text(view.Export, "share_id")) + Environment.NewLine + Display(NotesOriginalSchema.Text(view.Export, "setup_id")) };
                var contacts = new ListBox { Dock = DockStyle.Fill, SelectionMode = SelectionMode.One, HorizontalScrollbar = true };
                foreach (var contact in view.Contacts)
                    contacts.Items.Add(Display(string.Join(" ", new[] { "vorname", "nachname", "firma" }.Select(field => ContactFields.Text(contact, field)))) + " — " + Display(NotesOriginalSchema.Text(contact, "id")) + " — " +
                        Display(NotesOriginalSchema.Text(contact, "uid")));
                contacts.SelectedIndex = -1; // Never preselect a contact by position/name/default book.
                var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
                var cancel = new Button { Text = translate("Cancel"), AutoSize = true, DialogResult = DialogResult.Cancel };
                var accept = new Button { Text = translate("Allow updates"), AutoSize = true, Enabled = false, DialogResult = DialogResult.OK };
                contacts.SelectedIndexChanged += (_, _) => accept.Enabled = contacts.SelectedIndex >= 0;
                buttons.Controls.Add(cancel); buttons.Controls.Add(accept);
                layout.Controls.Add(explanation); layout.Controls.Add(source); layout.Controls.Add(contacts); layout.Controls.Add(buttons); dialog.Controls.Add(layout);
                dialog.AcceptButton = accept; dialog.CancelButton = cancel;
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
                result.TrySetResult(accepted && contacts.SelectedIndex >= 0
                    ? NotesOriginalSchema.Text(view.Contacts[contacts.SelectedIndex], "id") : null);
            }
            catch (OperationCanceledException) { result.TrySetCanceled(cancellation); }
            catch (Exception error) { result.TrySetException(error); }
        }
        try { if (owner.InvokeRequired) owner.BeginInvoke(Show); else Show(); }
        catch (Exception error) { result.TrySetException(error); }
        return result.Task;
    }
}
