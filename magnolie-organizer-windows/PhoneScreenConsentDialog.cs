using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

/// <summary>One explicit native approval for a selected probe. Neither a
/// browser callback nor an OS unlock may approve/revive this dialog.</summary>
internal sealed class PhoneScreenConsentDialog : Form
{
    private readonly Action requireOriginal;
    private readonly long deadline;
    private readonly System.Windows.Forms.Timer timer;
    private bool registered, retired, approved;

    internal PhoneScreenConsentDialog(string phoneName, long probeDeadline, Action requireOriginal)
    {
        this.requireOriginal = requireOriginal;
        deadline = Math.Min(probeDeadline, Stopwatch.GetTimestamp() + 25 * Stopwatch.Frequency);
        Text = NativeLocalization.Gettext("Phone screen mirroring");
        ClientSize = new System.Drawing.Size(410, 150);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterParent;
        Controls.Add(new Label { AutoEllipsis = true, Location = new(16, 16), Size = new(378, 68),
            Text = NativeLocalization.Gettext("View this phone's screen?") + Environment.NewLine + phoneName });
        var approve = new Button { Text = NativeLocalization.Gettext("View phone screen"), Location = new(126, 101), Size = new(155, 32) };
        var cancel = new Button { Text = NativeLocalization.Gettext("Cancel"), Location = new(289, 101), Size = new(105, 32), DialogResult = DialogResult.Cancel };
        Controls.Add(approve); Controls.Add(cancel);
        CancelButton = AcceptButton = cancel;
        approve.Click += (_, _) =>
        {
            if (!registered || !Current()) { Retire(); return; }
            approved = true;
            DialogResult = DialogResult.OK;
        };
        timer = new System.Windows.Forms.Timer { Interval = 50 };
        timer.Tick += (_, _) => { if (!registered || !Current()) Retire(); };
    }

    internal bool Confirm(IWin32Window original)
    {
        _ = Handle;
        if (!registered || !Current()) return false;
        timer.Start();
        // ShowDialog destroys the modal HWND on normal return. Only an
        // explicit click while that HWND was registered can satisfy this check.
        try { return ShowDialog(original) == DialogResult.OK && approved && Current(); }
        finally { timer.Stop(); }
    }

    private bool Current()
    {
        if (retired || Stopwatch.GetTimestamp() >= deadline || !PhoneScreenWindow.InteractiveDesktop()) return false;
        try { requireOriginal(); return true; }
        catch (Exception) { return false; }
    }

    private void Retire() { retired = true; DialogResult = DialogResult.Cancel; }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        if (!retired) registered = PhoneScreenWindow.RegisterSession(Handle);
    }
    protected override void OnHandleDestroyed(EventArgs e)
    {
        if (!approved || DialogResult != DialogResult.OK) retired = true;
        if (registered) { registered = false; PhoneScreenWindow.UnregisterSession(Handle); }
        base.OnHandleDestroyed(e);
    }
    protected override void WndProc(ref Message m)
    {
        if (PhoneScreenWindow.RetiresSession(m)) Retire();
        base.WndProc(ref m);
    }
    protected override void Dispose(bool disposing) { if (disposing) timer.Dispose(); base.Dispose(disposing); }
}
