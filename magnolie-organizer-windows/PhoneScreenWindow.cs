using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace MagnolieOrganizer.Windows;

/// <summary>Independent native view. No owner window, network or stored consent.
/// The worker transfers one already admitted JPEG; Stop revokes this view and
/// signals its exact owner. The owner, not the window, joins capture/IO.</summary>
internal sealed class PhoneScreenWindow : Form
{
    private readonly object gate = new();
    private readonly int uiThread = Environment.CurrentManagedThreadId;
    private readonly int width, height;
    private readonly Func<bool> current;
    private readonly Action requestStop;
    private readonly System.Windows.Forms.Timer poll;
    private Bitmap? pending, displayed;
    private int retired;
    private bool sessionNotifications;
    internal Exception? StopError { get; private set; }
    internal bool Retired => Volatile.Read(ref retired) != 0;

    internal PhoneScreenWindow(string title, int width, int height, Func<bool> current, Action requestStop)
    {
        if (!PhoneScreenJpegHeader.ValidSize(width, height)) throw new ArgumentOutOfRangeException(nameof(width));
        this.width = width;
        this.height = height;
        this.current = current ?? throw new ArgumentNullException(nameof(current));
        this.requestStop = requestStop ?? throw new ArgumentNullException(nameof(requestStop));
        Text = title;
        ClientSize = new Size(480, 640);
        BackColor = Color.Black;
        DoubleBuffered = true;
        poll = new System.Windows.Forms.Timer { Interval = 33 };
        poll.Tick += Tick;
    }

    private bool IsCurrent()
    {
        try { return !Retired && current() && !Retired; }
        catch (Exception) { return false; }
    }

    internal bool ShowOriginal()
    {
        RequireUi();
        if (!IsCurrent() || !InteractiveDesktop()) { Stop(); return false; }
        _ = Handle; // Register for private lock/disconnect events before showing any picture.
        if (!sessionNotifications || !InteractiveDesktop()) { Stop(); return false; }
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        poll.Start();
        return true;
    }

    // Data worker only. No control/window access, no renderer input, no GTK or webcam rights.
    internal bool OfferJpeg(byte[] jpeg)
    {
        if (!IsCurrent()) return false;
        PhoneScreenJpegHeader.Require(jpeg, width, height);
        using var bytes = new MemoryStream(jpeg, writable: false);
        using var decoded = Image.FromStream(bytes, useEmbeddedColorManagement: false, validateImageData: true);
        if (decoded.RawFormat.Guid != ImageFormat.Jpeg.Guid || decoded.Width != width || decoded.Height != height)
            throw new InvalidDataException("screen_jpeg_decode_shape");
        Bitmap? next = new(width, height, PixelFormat.Format24bppRgb);
        try
        {
            using (var g = Graphics.FromImage(next)) g.DrawImageUnscaled(decoded, 0, 0);
            lock (gate)
            {
                if (!IsCurrent()) return false;
                pending?.Dispose();
                pending = next;
                next = null;
                return true;
            }
        }
        finally { next?.Dispose(); }
    }

    private void Tick(object? sender, EventArgs e)
    {
        if (!IsCurrent() || !InteractiveDesktop()) { Stop(); return; }
        lock (gate)
        {
            if (pending is null) return;
            displayed?.Dispose();
            displayed = pending;
            pending = null;
        }
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(Color.Black);
        if (!IsCurrent() || !InteractiveDesktop() || displayed is null || ClientSize.Width <= 0 || ClientSize.Height <= 0) return;
        var scale = Math.Min((float)ClientSize.Width / width, (float)ClientSize.Height / height);
        var picture = new RectangleF((ClientSize.Width - width * scale) / 2, (ClientSize.Height - height * scale) / 2,
            width * scale, height * scale);
        e.Graphics.DrawImage(displayed, picture);
    }

    protected override void OnResize(EventArgs e) { base.OnResize(e); Invalidate(); }
    protected override void OnFormClosing(FormClosingEventArgs e) { Retire(); base.OnFormClosing(e); }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        if (!Retired) sessionNotifications = RegisterSession(Handle);
    }

    protected override void OnHandleDestroyed(EventArgs e)
    {
        if (sessionNotifications)
        {
            sessionNotifications = false;
            UnregisterSession(Handle);
        }
        Retire(); // No resurrection if WinForms replaces the native handle.
        base.OnHandleDestroyed(e);
    }

    protected override void WndProc(ref Message m)
    {
        if (RetiresSession(m))
        {
            // Console/remote disconnect, logoff, lock, or session termination.
            Retire();
            Invalidate();
            if (IsHandleCreated) BeginInvoke((Action)Stop);
        }
        base.WndProc(ref m);
    }

    internal void Stop()
    {
        RequireUi();
        if (!IsDisposed) { Retire(); Close(); Dispose(); }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) Retire();
        base.Dispose(disposing);
    }

    private void Retire()
    {
        if (Interlocked.Exchange(ref retired, 1) != 0) return;
        try
        {
            poll.Dispose();
            lock (gate)
            {
                pending?.Dispose(); pending = null;
                displayed?.Dispose(); displayed = null;
            }
        }
        finally
        {
            try { requestStop(); }
            catch (Exception error) { StopError = error; }
        }
    }

    internal static bool RetiresSession(Message message) => message.Msg == 0x02B1 && (int)message.WParam is 2 or 4 or 6 or 7 or 11;
    internal static bool RegisterSession(IntPtr window) => WTSRegisterSessionNotification(window, 0);
    internal static void UnregisterSession(IntPtr window) => WTSUnRegisterSessionNotification(window);

    internal static bool InteractiveDesktop()
    {
        var desktop = OpenInputDesktop(0, false, 1);
        if (desktop == IntPtr.Zero) return false;
        try
        {
            var name = new StringBuilder(256);
            return GetUserObjectInformation(desktop, 2, name, 512, out _) &&
                name.ToString().Equals("Default", StringComparison.OrdinalIgnoreCase);
        }
        finally { CloseDesktop(desktop); }
    }

    [DllImport("wtsapi32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool WTSRegisterSessionNotification(IntPtr window, uint flags);
    [DllImport("wtsapi32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool WTSUnRegisterSessionNotification(IntPtr window);
    [DllImport("user32.dll")] private static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] private static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool GetUserObjectInformation(IntPtr handle, int index, StringBuilder name, uint length, out uint needed);

    private void RequireUi()
    {
        if (Environment.CurrentManagedThreadId != uiThread)
            throw new InvalidOperationException("screen_view_ui_thread_required");
    }
}
