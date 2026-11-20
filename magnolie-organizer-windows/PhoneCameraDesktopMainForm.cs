using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

internal sealed partial class MainForm
{
    // Until native consent, lock/exit and actual phone AV are accepted, no
    // product caller (including the web bridge) can start a provider.
    internal static bool NativeWebcamChecked => false;
    private readonly PhoneCameraDesktopSlot webcamSlot = new();
    private PhoneCameraDesktopSlot.Run? webcamRun;
    private IntPtr webcamWtsWindow;
    private long webcamDesktopEpoch;
    private bool webcamConfirming;

    internal bool ConfirmDesktopWebcam(TelefonCoordinator.DesktopWebcamChoice selected, Action requireProfile)
    {
        if (!NativeWebcamChecked || InvokeRequired || !Visible || !IsHandleCreated || shutdownStarted || closeRequested ||
            webcamConfirming || webcamRun is { Drained: false }) return false;
        var hwnd = Handle;
        if (webcamWtsWindow != hwnd)
        {
            if (!PhoneScreenWindow.RegisterSession(hwnd)) return false;
            webcamWtsWindow = hwnd;
        }
        var epoch = Interlocked.Read(ref webcamDesktopEpoch);
        void Current()
        {
            selected.Parent.RequireDesktopWebcamParent();
            requireProfile();
            if (Interlocked.Read(ref webcamDesktopEpoch) != epoch || !PhoneScreenWindow.InteractiveDesktop())
                throw new InvalidOperationException("webcam_original_desktop_retired");
        }
        webcamConfirming = true;
        try
        {
            Current();
            using var dialog = new WebcamConsentDialog(selected.Name, Current);
            if (!dialog.Confirm(this) || shutdownStarted || closeRequested || !Visible) return false;
            Current();
            webcamRun = webcamSlot.StartNative(selected.Parent, Current, dialog.Muted, dialog.Front);
            return true;
        }
        finally { webcamConfirming = false; }
    }

    internal void StopDesktopWebcam() => webcamRun?.Stop();
    internal bool StopDesktopWebcam(string runId)
    {
        if (webcamRun is not { Drained: false } original || original.Id != runId) return false;
        original.Stop();
        return true;
    }
    internal (string Phase, string? Run) DesktopWebcamStatus => webcamRun is not { Drained: false } original
        ? ("off", null) : (original.Stopping ? "stopping" : original.Sending ? "active" : "starting", original.Id);

    partial void ObserveWebcamWindowMessage(Message message)
    {
        if (webcamWtsWindow == IntPtr.Zero || message.HWnd != webcamWtsWindow) return;
        if (message.Msg == 0x0082) // WM_NCDESTROY; a recreated handle cannot revive this grant.
        {
            PhoneScreenWindow.UnregisterSession(webcamWtsWindow);
            webcamWtsWindow = IntPtr.Zero;
        }
        else if (!PhoneScreenWindow.RetiresSession(message)) return;
        Interlocked.Increment(ref webcamDesktopEpoch);
        StopDesktopWebcam();
    }

    partial void RequestWebcamExit(ref Task drained)
    {
        Interlocked.Increment(ref webcamDesktopEpoch);
        if (webcamSlot.Close() is { } original) drained = RequireWebcamDrainAsync(original);
    }

    partial void SignalWebcamExit()
    {
        Interlocked.Increment(ref webcamDesktopEpoch);
        webcamSlot.Close();
    }

    private static async Task RequireWebcamDrainAsync(PhoneCameraDesktopSlot.Run original)
    {
        await original.Completion.ConfigureAwait(false);
        if (!original.Drained) throw new InvalidOperationException("webcam_original_cleanup_unconfirmed");
    }

    private sealed class WebcamConsentDialog : Form
    {
        private readonly Action requireOriginal;
        private readonly long deadline = Stopwatch.GetTimestamp() + 25 * Stopwatch.Frequency;
        private readonly CheckBox muted = new() { Left = 16, Top = 70, Width = 360 };
        private readonly CheckBox front = new() { Left = 16, Top = 99, Width = 360 };
        private bool approved;
        internal bool Muted => muted.Checked;
        internal bool Front => front.Checked;

        internal WebcamConsentDialog(string name, Action requireOriginal)
        {
            this.requireOriginal = requireOriginal;
            Text = T("Phone webcam");
            ClientSize = new(410, 183);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;
            Controls.Add(new Label { Left = 16, Top = 16, Width = 378, Height = 48, AutoEllipsis = true,
                Text = T("Use this phone as a webcam?") + Environment.NewLine + name });
            muted.Text = T("Mute microphone");
            front.Text = T("Use front camera");
            Controls.Add(muted); Controls.Add(front);
            var start = new Button { Text = T("Start"), Left = 169, Top = 134, Width = 105, Height = 32 };
            var cancel = new Button { Text = T("Cancel"), Left = 289, Top = 134, Width = 105, Height = 32, DialogResult = DialogResult.Cancel };
            Controls.Add(start); Controls.Add(cancel);
            AcceptButton = CancelButton = cancel;
            start.Click += (_, _) =>
            {
                approved = Current();
                DialogResult = approved ? DialogResult.OK : DialogResult.Cancel;
            };
        }

        internal bool Confirm(IWin32Window original)
        {
            if (!Current()) return false;
            using var timer = new System.Windows.Forms.Timer { Interval = 50 };
            timer.Tick += (_, _) => { if (!Current()) DialogResult = DialogResult.Cancel; };
            timer.Start();
            return ShowDialog(original) == DialogResult.OK && approved && Current();
        }

        private bool Current()
        {
            if (Stopwatch.GetTimestamp() >= deadline) return false;
            try { requireOriginal(); return true; }
            catch (Exception) { return false; }
        }
    }
}
