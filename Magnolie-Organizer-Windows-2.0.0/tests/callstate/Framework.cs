using System.Text.Json.Nodes;
// Capture framework only. This is not WinForms, WebView2, or native toast execution.
#pragma warning disable CS0067, CS0649, CS9113
namespace MagnolieOrganizer.Windows {
internal partial class MainForm {
    internal bool InvokeRequired = true, IsDisposed = false, Disposing = false, shutdownStarted = false;
    internal readonly Queue<Action> Queue = new();
    internal void BeginInvoke(Action action) => Queue.Enqueue(action);
    internal void Drain() { InvokeRequired = false; while (Queue.TryDequeue(out var action)) action(); }
    internal readonly CancellationTokenSource closing = new();
    internal readonly FakeWebView webView = new();
    internal TelefonCoordinator? telefonCoordinator;
    internal JsonObject? currentIncomingCall;
    internal long incomingCallGeneration;
    internal readonly object incomingCallGate = new();
    internal string shownCallAlert = "";
    internal Form? callAlert;
    internal readonly FakeNotice callNotifications = new();
    internal object? Icon;
    internal string T(string text) => text;
    internal void ShowNotification(string title, string body) { }
}
internal sealed class FakeWebView { internal FakeCore CoreWebView2 = new(); }
internal sealed class FakeCore {
    internal readonly List<string> Scripts = new();
    internal Task ExecuteScriptAsync(string script) { Scripts.Add(script); return Task.CompletedTask; }
}
internal sealed class FakeNotice {
    internal int Shown, Withdrawn;
    internal IReadOnlyDictionary<string,string> Tokens = new Dictionary<string,string>();
    internal bool Show(string title, string caller, IReadOnlyDictionary<string,string> tokens) { Shown++; Tokens = tokens; return true; }
    internal void Withdraw() { Withdrawn++; }
}
internal enum AccessibleRole { Alert }
internal enum AutoScaleMode { Dpi }
internal enum FormBorderStyle { FixedToolWindow }
internal enum FormStartPosition { Manual }
internal enum DockStyle { Bottom, Fill, Left }
internal enum FlowDirection { LeftToRight }
internal enum PictureBoxSizeMode { CenterImage }
internal record Size(int Width, int Height);
internal record Point(int X, int Y);
internal record Padding(int Value);
internal static class Color { internal static object FromArgb(int r, int g, int b) => new(); }
internal sealed class Screen {
    internal static Screen FromControl(object value) => new();
    internal Screen WorkingArea => this;
    internal int Left => 0; internal int Top => 0; internal int Right => 1000; internal int Bottom => 800;
}
internal class Control {
    internal string Text = "", AccessibleName = "", AccessibleDescription = "";
    internal object? BackColor, ForeColor, Icon;
    internal bool AutoSize, UseMnemonic, ShowInTaskbar, TopMost, Enabled = true, Visible;
    internal int Width, Height;
    internal DockStyle Dock;
    internal readonly List<Control> Controls = new();
}
internal class Form : Control {
    internal static bool Unsupported;
    internal AccessibleRole AccessibleRole; internal AutoScaleMode AutoScaleMode;
    internal Size? ClientSize; internal Padding? Padding; internal Point? Location;
    internal FormBorderStyle FormBorderStyle; internal FormStartPosition StartPosition;
    internal event EventHandler? FormClosed;
    internal void Close() { Visible = false; FormClosed?.Invoke(this, EventArgs.Empty); }
    internal void Show() { if (Unsupported) throw new InvalidOperationException("fixture: unsupported popup"); Visible = true; }
}
internal class Button : Control { internal event EventHandler? Click; }
internal class Label : Control { }
internal class FlowLayoutPanel : Control { internal FlowDirection FlowDirection; }
internal class PictureBox : Control { internal object? Image; internal PictureBoxSizeMode SizeMode; }
internal class Image : IDisposable { internal static Image FromStream(Stream stream) => new(); public void Dispose() { } }
internal class Bitmap(Image image, Size size) : Image { }
}
namespace System.Windows.Forms {
internal sealed class Timer : IDisposable {
    internal static readonly List<Timer> Active = new();
    internal int Interval; internal event EventHandler? Tick;
    internal void Start() { Active.Add(this); } public void Dispose() { Active.Remove(this); }
    internal static void Fire() { foreach (var timer in Active.ToArray()) timer.Tick?.Invoke(timer, EventArgs.Empty); }
}
}
