using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

internal static class NativeInputProbe
{
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] private static extern int GetSystemMetrics(int metric);

    internal static int Run()
    {
        using var done = new ManualResetEventSlim();
        var result = 1;
        Form? window = null;
        var thread = new Thread(() =>
        {
            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
            using var fixture = new Form { Text = "Magnolie isolated input fixture", Width = 440, Height = 240,
                StartPosition = FormStartPosition.CenterScreen, KeyPreview = true };
            window = fixture;
            var text = new TextBox { Text = "Synthetic fixture", Dock = DockStyle.Top, Multiline = true, Height = 100 };
            fixture.Controls.Add(text);
            var keys = new HashSet<Keys>();
            fixture.KeyDown += (_, e) => keys.Add(e.KeyCode);
            using var sink = new KdeWindowsInput();
            var target = new KdeInputTarget(sink);
            var source = new object(); var allowed = true; var phase = 0;
            using var timer = new System.Windows.Forms.Timer { Interval = 150 };
            fixture.Shown += (_, _) => { fixture.Activate(); text.Focus(); timer.Start(); };
            timer.Tick += (_, _) =>
            {
                try
                {
                    // A failed foreground request must not send keys or clicks
                    // into any existing user program. Check again every phase.
                    if (GetForegroundWindow() != fixture.Handle) throw new Exception("Isolated fixture is not foreground; no user input is permitted");
                    switch (phase++)
                    {
                        case 0:
                            if (!sink.Available || !sink.Keyboard) throw new Exception("Native input desktop unavailable");
                            target.Arm(source, Guid.NewGuid().ToString(), () => allowed && GetForegroundWindow() == fixture.Handle);
                            var center = text.PointToScreen(new System.Drawing.Point(30, 20));
                            target.Accept(source, new JsonObject { ["x"] = center.X, ["y"] = center.Y });
                            target.Accept(source, new JsonObject { ["singleclick"] = true });
                            break;
                        case 1:
                            if (!text.Focused) throw new Exception("Native mouse click did not focus fixture text");
                            target.Accept(source, new JsonObject { ["key"] = "a", ["ctrl"] = true });
                            break;
                        case 2:
                            if (text.SelectionLength != text.TextLength) throw new Exception("Native Ctrl+A did not select fixture text");
                            target.Accept(source, new JsonObject { ["key"] = "ä😀" });
                            break;
                        case 3:
                            if (text.Text != "ä😀") throw new Exception("Native Unicode input did not reach fixture");
                            target.Accept(source, new JsonObject { ["specialKey"] = 25 });
                            target.Accept(source, new JsonObject { ["specialKey"] = 9 });
                            break;
                        case 4:
                            if (!keys.Contains(Keys.F5) || !keys.Contains(Keys.Next)) throw new Exception("Native presentation keys did not reach fixture");
                            target.Accept(source, new JsonObject { ["singlehold"] = true });
                            break;
                        case 5:
                            var primary = GetSystemMetrics(23) != 0 ? 2 : 1;
                            if ((GetAsyncKeyState(primary) & 0x8000) == 0) throw new Exception("Native drag was not held");
                            allowed = false;
                            if (!target.Expire()) throw new Exception("Expired input target remained active");
                            break;
                        case 6:
                            if ((GetAsyncKeyState(GetSystemMetrics(23) != 0 ? 2 : 1) & 0x8000) != 0) throw new Exception("Expiry left a held mouse button");
                            if (target.Accept(source, new JsonObject { ["key"] = "stale" }) || text.Text != "ä😀") throw new Exception("Revoked target remained actionable");
                            Console.WriteLine("PASS: native Windows input isolated window / pointer / click / Ctrl+A / Unicode / F5 / PageDown / held drag / expiry");
                            result = 0; timer.Stop(); fixture.Close(); break;
                    }
                }
                catch (Exception error)
                {
                    Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
                    timer.Stop();
                    try { target.Disarm(); } catch (Exception) { }
                    fixture.Close();
                }
            };
            try { Application.Run(fixture); }
            finally { try { target.Disarm(); } finally { done.Set(); } }
        }) { IsBackground = true };
        thread.SetApartmentState(ApartmentState.STA); thread.Start();
        if (!done.Wait(TimeSpan.FromSeconds(20)))
        {
            try { window?.BeginInvoke(new Action(() => window?.Close())); } catch (Exception) { }
            Console.Error.WriteLine("Native input fixture timeout"); return 1;
        }
        thread.Join(1000);
        return result;
    }
}
