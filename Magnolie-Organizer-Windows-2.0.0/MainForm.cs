using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace MagnolieOrganizer.Windows;

internal sealed class MainForm : Form
{
    private const string VirtualHost = "app.magnolie.invalid";
    private readonly WebView2 webView = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(46, 58, 52) };
    private readonly WindowsPaths paths;
    private readonly string bridgeName = $"bridge_{Guid.NewGuid():N}";
    private readonly NotifyIcon trayIcon;
    private readonly TraySettingsService traySettingsService;
    private TraySettings traySettings;
    private BridgeDispatcher? dispatcher;
    private bool allowClose;
    private bool closeRequested;
    private bool trayEnabled;
    private bool closeToTray;
    private bool minimizeToTray;
    private bool exitFromTray;
    private bool lastMaximized;
    private bool fullscreen;
    private bool fullscreenTransition;
    private bool restoreFullscreen;
    private FormBorderStyle fullscreenRestoreBorderStyle;
    private FormWindowState fullscreenRestoreWindowState;
    private Rectangle fullscreenRestoreBounds;
    private Size fullscreenRestoreClientSize;
    private bool shutdownStarted;
    private readonly CancellationTokenSource closing = new();
    private bool reminderAutostart;
    private TelefonCoordinator? telefonCoordinator;
    private JsonObject? pendingTelefonSms;
    private JsonObject? currentIncomingCall;
    private long incomingCallGeneration;
    private readonly object incomingCallGate = new();
    private Form? callAlert;
    private string shownCallAlert = "";
    private readonly WindowsCallNotifications callNotifications;
    private HandbookForm? handbookForm;
    private readonly FirstRunSetupSelections? setupSelections;

    internal void SetTelefonCoordinator(TelefonCoordinator coordinator) => telefonCoordinator = coordinator;

    internal MainForm(bool trayStart = false, bool reminderStart = false,
        FirstRunSetupSelections? setupSelections = null, WindowsPaths? paths = null,
        WindowsCallNotifications? notifications = null)
    {
        this.paths = paths ?? new WindowsPaths();
        this.setupSelections = setupSelections;
        Text = "Magnolie Organizer";
        BackColor = Color.FromArgb(46, 58, 52);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(980, 640);
        ClientSize = new Size(1440, 890);
        var iconPath = Path.Combine(AppContext.BaseDirectory, "magnolie-organizer.ico");
        if (File.Exists(iconPath)) Icon = new Icon(iconPath);
        traySettingsService = new TraySettingsService(this.paths.TraySettings);
        traySettings = traySettingsService.Load(this.paths.Data);
        reminderAutostart = reminderStart;
        trayIcon = CreateTrayIcon(Icon ?? SystemIcons.Application);
        callNotifications = notifications ?? new WindowsCallNotifications(async token =>
        {
            var accepted = telefonCoordinator is not null && await telefonCoordinator.ExecuteCallActionAsync(token);
            if (accepted && !IsDisposed && !Disposing) BeginInvoke(RestoreFromTray);
            return accepted;
        });
        Controls.Add(webView);
        HandleCreated += (_, _) => NativeMethods.ApplySystemTitleBarTheme(Handle);
        Load += async (_, _) => await InitializeWebViewAsync();
        if (setupSelections?.OpenHandbook == true) Shown += async (_, _) =>
        {
            var manual = Path.Combine(AppContext.BaseDirectory, "handbuch", "index.html");
            await OpenHandbookAsync(manual);
        };
        FormClosing += OnFormClosing;
        FormClosed += (_, _) => { closing.Cancel(); callAlert?.Close(); callNotifications.Dispose(); handbookForm?.Close(); dispatcher?.Dispose(); SaveWindowState(); trayIcon.Dispose(); };
        Resize += (_, _) =>
        {
            if (!fullscreen && !fullscreenTransition && WindowState != FormWindowState.Minimized)
                lastMaximized = WindowState == FormWindowState.Maximized;
            if (trayEnabled && minimizeToTray && WindowState == FormWindowState.Minimized) HideToTray();
        };
        RestoreWindowState();
        ApplyTraySettingsNative(traySettings);
        ApplyOpeningPreference();
        var startHidden = reminderStart || trayEnabled && (traySettings.StartMinimiert || trayStart);
        if (startHidden)
        {
            WindowState = FormWindowState.Minimized;
            Shown += (_, _) => HideToTray();
        }
        if (!traySettingsService.LoadFailed) _ = ConfigureAutostart();
    }

    internal async Task ApplyTraySettingsAsync(JsonElement settings)
    {
        var previousEnabled = trayEnabled;
        var requested = TraySettings.FromJson(settings);
        var error = "";
        try { traySettingsService.Save(requested); traySettings = requested; }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            error = T("Warning: The data could not be saved.") + " " + exception.Message;
        }
        var autostartError = ConfigureAutostart();
        ApplyTraySettingsNative(traySettings);
        if (previousEnabled && !trayEnabled && !Visible) RestoreFromTray();
        await SendAsync("App.trayStand", new
        {
            ok = error.Length == 0 && autostartError.Length == 0,
            verfuegbar = true,
            aktiv = trayEnabled,
            fehler = error.Length > 0 ? error : autostartError
        });
    }

    internal TraySettings CurrentTraySettings => traySettings;

    internal string SetReminderAutostart(bool active)
    {
        reminderAutostart = active;
        return traySettingsService.LoadFailed ? T("The background settings could not be saved.") : ConfigureAutostart();
    }

    private string ConfigureAutostart() => TraySettingsService.ConfigureAutostart(
        traySettings.Aktiv && traySettings.Autostart,
        Application.ExecutablePath, reminderAutostart);

    internal void UpdateTrayCounter(int count)
    {
        trayIcon.Text = count > 0
            ? $"Magnolie Organizer – {Math.Min(count, 999)}"
            : "Magnolie Organizer";
    }

    internal void ShowNotification(string title, string message)
    {
        trayIcon.BalloonTipTitle = string.IsNullOrWhiteSpace(title) ? "Magnolie Organizer" : title;
        trayIcon.BalloonTipText = message;
        trayIcon.BalloonTipIcon = ToolTipIcon.Info;
        trayIcon.ShowBalloonTip(8000);
    }

    internal void ShowTelefonMessage(string title, string message, JsonObject payload)
    {
        if (InvokeRequired) { BeginInvoke(() => ShowTelefonMessage(title, message, payload)); return; }
        pendingTelefonSms = payload.DeepClone().AsObject(); trayIcon.Visible = true;
        ShowNotification(T("SMS from %(name)s").Replace("%(name)s", title, StringComparison.Ordinal),
            message + "\n" + T("Open Magnolie Organizer"));
        HideTemporaryTrayIcon();
    }

    internal void TrackIncomingCall(JsonObject payload)
    {
        // Invalidate queued presentation before entering the UI queue.
        long generation;
        lock (incomingCallGate)
        {
            if (telefonCoordinator?.CallEventCurrent(payload) != true) return;
            generation = Interlocked.Increment(ref incomingCallGeneration);
            Volatile.Write(ref currentIncomingCall, TelefonCallActions.IsRinging(payload) ? payload.DeepClone().AsObject() : null);
        }
        void Withdraw()
        {
            if (generation != Volatile.Read(ref incomingCallGeneration)) return;
            callAlert?.Close(); callNotifications.Withdraw();
        }
        if (InvokeRequired) BeginInvoke(Withdraw); else Withdraw();
    }

    internal void ShowIncomingCall(JsonElement payload)
    {
        var generation = Volatile.Read(ref incomingCallGeneration);
        if (InvokeRequired) { BeginInvoke(() => { if (generation == Volatile.Read(ref incomingCallGeneration)) ShowIncomingCall(payload); }); return; }
        var callRef = payload.TryGetProperty("callRef", out var callNode) ? callNode.GetString() ?? "" : "";
        var id = payload.TryGetProperty("kennung", out var peerNode) ? peerNode.GetString() ?? "" : "";
        var revision = payload.TryGetProperty("revision", out var revNode) && revNode.TryGetInt64(out var rev) ? rev : 0;
        var current = Volatile.Read(ref currentIncomingCall);
        bool Current() => generation == Volatile.Read(ref incomingCallGeneration) &&
            telefonCoordinator?.IncomingCallCurrent(id, callRef, revision) == true;
        if (current is null || current["call_ref"]?.GetValue<string>() != callRef || current["device_id"]?.GetValue<string>() != id ||
            current["revision"]?.GetValue<long>() != revision || !TelefonCallActions.IsRinging(current) ||
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - (current["occurred_ms"]?.GetValue<long>() ?? 0) is < 0 or > 60_000 ||
            !Current() || shownCallAlert == id + ":" + callRef + ":" + revision) return;
        shownCallAlert = id + ":" + callRef + ":" + revision;
        var number = current["number_status"]?.GetValue<string>() == "available" ? current["number"]?.GetValue<string>() ?? "" : "";
        var name = current["kontaktName"]?.GetValue<string>() ?? "";
        var caller = name.Length > 0 ? name : number.Length > 0 ? number : T("Unknown caller");
        var tokens = payload.TryGetProperty("annehmen", out var answer) && answer.ValueKind == JsonValueKind.True
            ? telefonCoordinator?.CallActionTokens(id, callRef, revision) ?? [] : new Dictionary<string, string>();
        if (tokens.Count < 2) caller += "\n" + T("Call controls unavailable. Check Android call permission; no dialer role is requested automatically.");
        async Task Run(string token)
        {
            if (!Current()) return;
            callAlert?.Close(); callNotifications.Withdraw();
            try { if (telefonCoordinator is null || !await telefonCoordinator.ExecuteCallActionAsync(token)) throw new InvalidOperationException(); }
            catch (Exception) { if (generation == Volatile.Read(ref incomingCallGeneration)) ShowNotification(T("Incoming call"), T("The call action expired or is no longer permitted.")); }
        }
        var monitor = new System.Windows.Forms.Timer { Interval = 300 };
        monitor.Tick += (_, _) =>
        {
            if (Current()) return;
            monitor.Dispose();
            if (generation == Volatile.Read(ref incomingCallGeneration)) { callAlert?.Close(); callNotifications.Withdraw(); }
        };
        monitor.Start();
        void Present()
        {
            // A small native surface, never restoring or opening the organizer book.
            var area = Screen.FromControl(this).WorkingArea;
            var panel = new Form { Text = T("Incoming call"), AccessibleName = T("Incoming call"), AccessibleRole = AccessibleRole.Alert,
                BackColor = Color.FromArgb(246, 239, 220), ForeColor = Color.FromArgb(58, 49, 40),
                AutoScaleMode = AutoScaleMode.Dpi, ClientSize = new Size(390, 210), Padding = new Padding(16),
                FormBorderStyle = FormBorderStyle.FixedToolWindow, ShowInTaskbar = false, TopMost = true, StartPosition = FormStartPosition.Manual, Icon = Icon };
            callAlert = panel;
            panel.Location = new Point(Math.Max(area.Left, area.Right - panel.Width - 20), Math.Max(area.Top, area.Bottom - panel.Height - 30));
            var actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 48, FlowDirection = FlowDirection.LeftToRight };
            foreach (var action in new[] { "answer", "reject" })
            {
                var label = T(action == "answer" ? "Answer" : "Reject");
                var supported = tokens.TryGetValue(action, out var token);
                var button = new Button { Text = action == "answer" ? "\u260e" : "\u2715", AccessibleName = label, Enabled = supported,
                    AccessibleDescription = label, Width = 64, Height = 38, BackColor = Color.FromArgb(230, 222, 199) };
                button.Click += async (_, _) => { if (token is not null) await Run(token); }; actions.Controls.Add(button);
            }
            var mute = new Button { Text = "\U0001f515", AccessibleName = T("Silence this alert"), AccessibleDescription = T("Silence this alert"), Width = 64, Height = 38 };
            mute.Click += (_, _) => panel.Close(); actions.Controls.Add(mute);
            var text = new Label { Text = caller, Dock = DockStyle.Fill, AutoSize = false, UseMnemonic = false };
            panel.Controls.Add(text); panel.Controls.Add(actions);
            if (current["kontaktFoto"]?.GetValue<string>() is { Length: > 0 and <= 2097152 } photo && photo.StartsWith("data:image/", StringComparison.Ordinal))
            {
                try
                {
                    using var stream = new MemoryStream(Convert.FromBase64String(photo[(photo.IndexOf(',') + 1)..]));
                    using var source = Image.FromStream(stream);
                    var image = new Bitmap(source, new Size(56, 56));
                    var picture = new PictureBox { Image = image, Dock = DockStyle.Left, Width = 68, SizeMode = PictureBoxSizeMode.CenterImage };
                    panel.Controls.Add(picture); panel.FormClosed += (_, _) => image.Dispose();
                }
                catch (Exception error) when (error is ArgumentException or FormatException or OutOfMemoryException) { }
            }
            var expiry = new System.Windows.Forms.Timer { Interval = 60_000 };
            expiry.Tick += (_, _) => panel.Close();
            panel.FormClosed += (_, _) => { expiry.Dispose(); if (callAlert == panel) callAlert = null; };
            expiry.Start(); panel.Show();
            if (!panel.Visible) throw new InvalidOperationException("Call surface unavailable");
        }
        try { Present(); }
        catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception or System.Runtime.InteropServices.COMException)
        {
            callAlert?.Close(); callAlert = null;
            if (Current()) callNotifications.Show(T("Incoming call"), caller, tokens);
        }
    }

    internal void ShowTelefonNotification(string title, string message)
    {
        if (InvokeRequired) { BeginInvoke(() => ShowTelefonNotification(title, message)); return; }
        trayIcon.Visible = true; ShowNotification(title, message);
        HideTemporaryTrayIcon();
    }

    private void HideTemporaryTrayIcon()
    {
        if (trayEnabled) return;
        var hideTimer = new System.Windows.Forms.Timer { Interval = 10_000 };
        hideTimer.Tick += (_, _) => { hideTimer.Stop(); hideTimer.Dispose(); if (!trayEnabled) trayIcon.Visible = false; };
        hideTimer.Start();
    }

    internal void ShowReminder(string title, string message, string kind, string style)
    {
        if (IsDisposed || Disposing || shutdownStarted) return;
        if (InvokeRequired) { BeginInvoke(() => ShowReminder(title, message, kind, style)); return; }
        kind = kind is "notification" or "sound" or "both" ? kind : "both";
        if (kind is "sound" or "both")
            NativeMethods.PlaySoundFile(Path.Combine(AppContext.BaseDirectory, "erinnerung.wav"));
        if (kind is not ("notification" or "both")) return;

        if (style == "magnolie")
        {
            var area = Screen.FromControl(this).WorkingArea;
            var bodyFont = new Font("Segoe UI", 11);
            var headingFont = new Font("Georgia", 15, FontStyle.Bold);
            var paper = new Form
            {
                Text = string.IsNullOrWhiteSpace(title) ? "Magnolie Organizer" : title,
                AccessibleName = title, AccessibleDescription = message, AccessibleRole = AccessibleRole.Alert,
                AutoScaleDimensions = new SizeF(96, 96), AutoScaleMode = AutoScaleMode.Dpi,
                BackColor = Color.FromArgb(85, 41, 28), ForeColor = Color.FromArgb(58, 49, 40),
                Font = bodyFont, FormBorderStyle = FormBorderStyle.None,
                StartPosition = FormStartPosition.Manual, ShowInTaskbar = false, TopMost = true,
                ClientSize = new Size(Math.Min(380, area.Width - 56), Math.Min(250, area.Height - 88)),
                Padding = new Padding(3), Icon = Icon
            };
            var content = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(246, 239, 220),
                Padding = new Padding(18, 14, 18, 15) };
            content.Paint += (_, eventArgs) =>
            {
                using var pen = new Pen(Color.FromArgb(165, 145, 106));
                eventArgs.Graphics.DrawRectangle(pen, 0, 0, content.Width - 1, content.Height - 1);
            };
            var close = new Button { Text = T("Close"), Dock = DockStyle.Right, FlatStyle = FlatStyle.Flat,
                AutoSize = true, MinimumSize = new Size(90, 34), DialogResult = DialogResult.Cancel,
                BackColor = Color.FromArgb(230, 222, 199) };
            close.FlatAppearance.BorderColor = Color.FromArgb(171, 148, 104);
            var actions = new Panel { Dock = DockStyle.Bottom, Height = 44, Padding = new Padding(0, 7, 0, 0) };
            actions.Controls.Add(close);
            var heading = new Label { Text = title, AutoSize = true, Dock = DockStyle.Top,
                Font = headingFont, Padding = new Padding(0, 0, 0, 7), UseMnemonic = false };
            var gold = new Panel { Dock = DockStyle.Top, Height = 2, BackColor = Color.FromArgb(216, 178, 92) };
            var textArea = new Panel { Dock = DockStyle.Fill, Padding = new Padding(0, 7, 0, 0) };
            var body = new TextBox { Text = message, Dock = DockStyle.Fill, Multiline = true,
                ReadOnly = true, BorderStyle = BorderStyle.None, ScrollBars = ScrollBars.Vertical,
                BackColor = content.BackColor, ForeColor = Color.FromArgb(90, 70, 48), AccessibleName = title };
            textArea.Controls.Add(body);
            content.Controls.Add(textArea); content.Controls.Add(gold);
            content.Controls.Add(heading); content.Controls.Add(actions);
            content.SizeChanged += (_, _) =>
            {
                heading.MaximumSize = new Size(Math.Max(80, content.ClientSize.Width - content.Padding.Horizontal), 0);
            };
            paper.Controls.Add(content);
            paper.AcceptButton = close; paper.CancelButton = close;
            close.Click += (_, _) => paper.Close();
            Action position = () =>
            {
                var work = Screen.FromControl(this).WorkingArea;
                var size = new Size(Math.Min(paper.Width, Math.Max(120, work.Width - 56)),
                    Math.Min(paper.Height, Math.Max(120, work.Height - 88)));
                if (paper.Size != size) paper.Size = size;
                paper.Location = new Point(Math.Max(work.Left, work.Right - paper.Width - 28),
                    Math.Max(work.Top, Math.Min(work.Top + 44, work.Bottom - paper.Height)));
            };
            paper.SizeChanged += (_, _) => position();
            paper.Shown += (_, _) =>
            {
                position();
                close.Focus();
            };
            var dismiss = new System.Windows.Forms.Timer { Interval = 45_000 };
            dismiss.Tick += (_, _) =>
            {
                if (!paper.ContainsFocus && !paper.Bounds.Contains(Cursor.Position)) paper.Close();
            };
            paper.FormClosed += (_, _) =>
            {
                dismiss.Stop(); dismiss.Dispose(); paper.Dispose();
                headingFont.Dispose(); bodyFont.Dispose();
            };
            paper.Show(); dismiss.Start();
            return;
        }

        trayIcon.Visible = true;
        ShowNotification(title, message);
        var hideTimer = new System.Windows.Forms.Timer { Interval = 10_000 };
        hideTimer.Tick += (_, _) =>
        {
            hideTimer.Stop();
            hideTimer.Dispose();
            if (!trayEnabled) trayIcon.Visible = false;
        };
        hideTimer.Start();
    }

    internal Task SendAsync(string function, object payload) => SendAsync(function, payload, null);

    internal async Task SendAsync(string function, object payload, Func<object>? currentPayload)
    {
        if (IsDisposed || Disposing || shutdownStarted) return;
        if (InvokeRequired)
        {
            var completion = new TaskCompletionSource();
            try { BeginInvoke(async () =>
            {
                try { await SendAsync(function, payload, currentPayload); completion.SetResult(); }
                catch (Exception error) { completion.SetException(error); }
            }); }
            catch (InvalidOperationException) { completion.SetResult(); }
            await completion.Task.WaitAsync(TimeSpan.FromSeconds(5), closing.Token);
            return;
        }

        if (webView.CoreWebView2 is null) return;
        if (currentPayload is not null) payload = currentPayload();
        var json = JsonSerializer.Serialize(payload, JsonOptions.Default);
        var argument = JsonSerializer.Serialize(json);
        var callback = JsonSerializer.Serialize(function);
        await webView.CoreWebView2.ExecuteScriptAsync($$"""
            (() => {
              const path = {{callback}}.split(".");
              let owner = window;
              for (let index = 0; index < path.length - 1; index++) owner = owner && owner[path[index]];
              const handler = owner && owner[path[path.length - 1]];
              if (typeof handler === "function") handler.call(owner, JSON.parse({{argument}}));
            })();
            """).WaitAsync(TimeSpan.FromSeconds(5), closing.Token);
    }

    internal async void CloseAfterSave()
    {
        if (InvokeRequired) { BeginInvoke(CloseAfterSave); return; }
        if (shutdownStarted) return;
        shutdownStarted = true;
        closing.Cancel();
        try
        {
            if (dispatcher is not null) await dispatcher.ShutdownAsync().WaitAsync(TimeSpan.FromSeconds(10));
        }
        catch (TimeoutException error)
        {
            WriteWebViewDiagnostic($"Shutdown deadline: {error.Message}");
        }
        catch (Exception error)
        {
            WriteWebViewDiagnostic($"Fehler beim Beenden: {error}");
        }
        allowClose = true;
        Close();
    }

    internal void RequestClose()
    {
        if (InvokeRequired) { BeginInvoke(RequestClose); return; }
        exitFromTray = true;
        Close();
    }

    internal void CancelClose()
    {
        if (InvokeRequired) { BeginInvoke(CancelClose); return; }
        closeRequested = false;
        exitFromTray = false;
    }

    internal async void ShowPrintDialog(string html)
    {
        if (InvokeRequired) { BeginInvoke(() => ShowPrintDialog(html)); return; }
        if (string.IsNullOrWhiteSpace(html) || html.Length > 8_000_000) return;
        var print = new HtmlPrintForm(html, paths, "") { Icon = Icon };
        print.Show(this);
        try { await print.Ready; }
        catch (Exception error)
        {
            WriteWebViewDiagnostic($"Fehler beim Öffnen der Druckansicht: {error.Message}");
        }
    }

    internal async Task<bool> OpenHandbookAsync(string manualPath)
    {
        if (InvokeRequired)
        {
            var completion = new TaskCompletionSource<bool>();
            BeginInvoke(async () =>
            {
                try { completion.SetResult(await OpenHandbookAsync(manualPath)); }
                catch (Exception error) { completion.SetException(error); }
            });
            return await completion.Task;
        }
        if (!File.Exists(manualPath)) return false;
        if (handbookForm is { IsDisposed: false })
        {
            if (handbookForm.WindowState == FormWindowState.Minimized) handbookForm.WindowState = FormWindowState.Normal;
            handbookForm.Show(); handbookForm.Activate(); handbookForm.BringToFront();
            return await handbookForm.Ready;
        }
        handbookForm = new HandbookForm(Path.GetDirectoryName(manualPath), paths);
        handbookForm.FormClosed += (_, _) => handbookForm = null;
        handbookForm.Show(this);
        return await handbookForm.Ready;
    }

    protected override void WndProc(ref Message message)
    {
        if ((uint)message.Msg == NativeMethods.ExitMessage)
        {
            BeginInvoke(RequestClose);
            return;
        }
        if ((uint)message.Msg == NativeMethods.ActivationMessage)
        {
            RestoreFromTray();
            return;
        }
        base.WndProc(ref message);
        if (message.Msg == NativeMethods.SettingChangeMessage)
            NativeMethods.ApplySystemTitleBarTheme(Handle);
    }

    private async Task InitializeWebViewAsync()
    {
        try
        {
            paths.EnsureDirectories();
            var environment = await WebViewEnvironmentProvider.GetAsync(paths);
            await webView.EnsureCoreWebView2Async(environment);
            await ConfigureWebViewAsync();
            dispatcher = new BridgeDispatcher(this, paths, setupSelections);
            webView.CoreWebView2.WebMessageReceived += async (_, eventArgs) =>
            {
                try
                {
                    if (!Uri.TryCreate(eventArgs.Source, UriKind.Absolute, out var source) ||
                        !source.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase) ||
                        !source.Host.Equals(VirtualHost, StringComparison.OrdinalIgnoreCase)) return;
                    await dispatcher.HandleAsync(eventArgs.TryGetWebMessageAsString());
                }
                catch (Exception error)
                {
                    WriteWebViewDiagnostic($"Bridge-Fehler: {error}");
                }
            };
            webView.CoreWebView2.NavigationCompleted += (_, eventArgs) =>
                WriteWebViewDiagnostic(eventArgs.IsSuccess
                    ? "Navigation abgeschlossen."
                    : $"Navigation fehlgeschlagen: {eventArgs.WebErrorStatus}");
            webView.CoreWebView2.ProcessFailed += (_, eventArgs) =>
                WriteWebViewDiagnostic($"WebView2-Prozessfehler: {eventArgs.ProcessFailedKind}");
            webView.Source = new Uri($"https://{VirtualHost}/index.html");
        }
        catch (WebView2RuntimeNotFoundException error)
        {
            WriteWebViewDiagnostic($"WebView2-Start fehlgeschlagen: {error}");
            MessageBox.Show(this,
                T("Magnolie Organizer is not completely installed.") + " Microsoft Edge WebView2.",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            allowClose = true;
            Close();
        }
        catch (Exception error)
        {
            WriteWebViewDiagnostic($"WebView2-Start fehlgeschlagen: {error}");
            MessageBox.Show(this, error.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            allowClose = true;
            Close();
        }
    }

    private void WriteWebViewDiagnostic(string message)
    {
        RotatingLog.Append(Path.Combine(paths.Logs, "webview.log"), $"{DateTimeOffset.Now:O} {message}");
    }

    private async Task ConfigureWebViewAsync()
    {
        var core = webView.CoreWebView2;
        var webRoot = Path.Combine(AppContext.BaseDirectory, "web");
        if (!File.Exists(Path.Combine(webRoot, "index.html")))
            throw new FileNotFoundException(T("Magnolie Organizer is not completely installed."));

        core.SetVirtualHostNameToFolderMapping(VirtualHost, webRoot,
            CoreWebView2HostResourceAccessKind.DenyCors);
        ProtectedAssetReader.Register(core, "appassets.magnolie.invalid", webRoot,
            new Dictionary<string, (string, byte, byte, string)>
            {
                ["/kaffee-qr.png"] = ("kaffee-qr.mga", 1, 1, "image/png")
            }, WriteWebViewDiagnostic);
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.AreBrowserAcceleratorKeysEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.IsZoomControlEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        // The pinned WinForms wrapper does not publicly expose its CoreWebView2Controller.
        var controller = typeof(WebView2).GetField("_coreWebView2Controller",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)?
            .GetValue(webView) as CoreWebView2Controller
            ?? throw new InvalidOperationException("WebView2 controller is unavailable.");
        controller.AcceleratorKeyPressed += (_, eventArgs) =>
        {
            if (eventArgs.VirtualKey != (uint)Keys.F11 ||
                eventArgs.KeyEventKind is not CoreWebView2KeyEventKind.KeyDown and
                    not CoreWebView2KeyEventKind.SystemKeyDown) return;
            eventArgs.Handled = true;
            if (eventArgs.PhysicalKeyStatus.WasKeyDown != 0) return;
            BeginInvoke(ToggleFullscreen);
        };

        var language = NativeLocalization.Language;
        var shim = $$"""
            (() => {
              const name = {{JsonSerializer.Serialize(bridgeName)}};
              window.__MAGNOLIE_BRUECKE__ = name;
              window.__MAGNOLIE_SPRACHE__ = {{JsonSerializer.Serialize(language)}};
              const handlers = {};
              handlers[name] = { postMessage: value => window.chrome.webview.postMessage(String(value)) };
              Object.defineProperty(window, "webkit", { value: { messageHandlers: handlers }, writable: false });
            })();
            """;
        await core.AddScriptToExecuteOnDocumentCreatedAsync(shim);

        core.NavigationStarting += (_, eventArgs) =>
        {
            if (IsInternal(eventArgs.Uri)) return;
            eventArgs.Cancel = true;
                ShellLauncher.OpenExternalUri(eventArgs.Uri);
        };
        core.NewWindowRequested += (_, eventArgs) =>
        {
            eventArgs.Handled = true;
            if (!IsInternal(eventArgs.Uri)) ShellLauncher.OpenExternalUri(eventArgs.Uri);
        };
        core.PermissionRequested += (_, eventArgs) => eventArgs.State = CoreWebView2PermissionState.Deny;
    }

    private static bool IsInternal(string uri) =>
        Uri.TryCreate(uri, UriKind.Absolute, out var parsed) &&
        parsed.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase) &&
        parsed.Host.Equals(VirtualHost, StringComparison.OrdinalIgnoreCase);

    private async void OnFormClosing(object? sender, FormClosingEventArgs eventArgs)
    {
        if (allowClose || webView.CoreWebView2 is null) return;
        if (eventArgs.CloseReason is CloseReason.WindowsShutDown or CloseReason.TaskManagerClosing)
        {
            shutdownStarted = true;
            closing.Cancel();
            try { dispatcher?.ShutdownAsync().Wait(TimeSpan.FromSeconds(3)); }
            catch (Exception error) { WriteWebViewDiagnostic(error.Message); }
            allowClose = true;
            return;
        }
        if (eventArgs.CloseReason == CloseReason.UserClosing && trayEnabled && closeToTray && !exitFromTray)
        {
            eventArgs.Cancel = true;
            HideToTray();
            return;
        }
        eventArgs.Cancel = true;
        if (closeRequested) return;
        closeRequested = true;
        try
        {
            await webView.CoreWebView2.ExecuteScriptAsync("App.vorBeenden();").WaitAsync(TimeSpan.FromSeconds(5));
        }
        catch (Exception error)
        {
            WriteWebViewDiagnostic($"Beenden konnte nicht angefordert werden: {error}");
            closeRequested = false;
            ShowSaveWarning();
        }
    }

    private void ShowSaveWarning() => MessageBox.Show(this,
        T("Warning: The data could not be saved."),
        Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);

    private NotifyIcon CreateTrayIcon(Icon icon)
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add(T("Open"), null, (_, _) => RestoreFromTray());
        var connectPhone = new ToolStripMenuItem(T("Connect phone via WLAN"), null, async (_, _) =>
        {
            RestoreFromTray();
            if (telefonCoordinator is not null) await telefonCoordinator.StartPairingAsync();
        });
        menu.Items.Add(connectPhone);
        var phones = new ToolStripMenuItem(T("Phones"));
        menu.Items.Add(phones);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(T("Quit"), null, (_, _) =>
        {
            exitFromTray = true;
            Close();
        });
        menu.Opening += (_, _) =>
        {
            phones.DropDownItems.Clear();
            var phoneEnabled = telefonCoordinator?.Enabled == true;
            connectPhone.Visible = phoneEnabled;
            phones.Visible = phoneEnabled;
            var partners = dispatcher?.ConfirmedDevicePartners() ?? [];
            /* Ohne gepaartes Telefon ganz ausblenden statt nur ausgrauen: Ein
               dauerhaft sichtbarer, nicht benutzbarer Eintrag legt eine
               Funktion nahe, die es gerade nicht gibt. */
            phones.Visible = phoneEnabled && partners.Length > 0;
            foreach (var partner in partners)
            {
                var id = partner.Id;
                phones.DropDownItems.Add(partner.Name, null, async (_, _) =>
                {
                    RestoreFromTray();
                    if (dispatcher is not null) await dispatcher.OpenDeviceAsync(id);
                });
            }
        };
        var result = new NotifyIcon
        {
            Icon = icon,
            Text = "Magnolie Organizer",
            ContextMenuStrip = menu,
            Visible = false
        };
        result.MouseClick += (_, eventArgs) =>
        {
            if (eventArgs.Button == MouseButtons.Left)
            {
                RestoreFromTray();
                if (currentIncomingCall is not null)
                    _ = SendAsync("App.telefonEingehenderAnruf", currentIncomingCall.DeepClone());
                else if (pendingTelefonSms is not null)
                {
                    var payload = pendingTelefonSms; pendingTelefonSms = null;
                    _ = SendAsync("App.telefonAntwort", payload);
                }
            }
        };
        result.BalloonTipClicked += (_, _) =>
        {
            RestoreFromTray();
            if (currentIncomingCall is not null)
                _ = SendAsync("App.telefonEingehenderAnruf", currentIncomingCall.DeepClone());
            else if (pendingTelefonSms is not null)
            {
                var payload = pendingTelefonSms; pendingTelefonSms = null;
                _ = SendAsync("App.telefonAntwort", payload);
            }
        };
        return result;
    }

    private static string T(string message) => NativeLocalization.Gettext(message);

    private void HideToTray()
    {
        Hide();
    }

    private void RestoreFromTray()
    {
        if (IsDisposed || Disposing || shutdownStarted) return;
        ApplyOpeningPreference();
        Show();
        Activate();
    }

    internal void ShowPairingRequest()
    {
        if (InvokeRequired) { BeginInvoke(ShowPairingRequest); return; }
        RestoreFromTray();
    }

    private void ApplyTraySettingsNative(TraySettings settings)
    {
        trayEnabled = settings.Aktiv;
        closeToTray = settings.SchliessenInTray;
        minimizeToTray = settings.MinimierenInTray;
        trayIcon.Visible = trayEnabled;
    }

    private void ApplyOpeningPreference()
    {
        switch (traySettings.Oeffnen)
        {
            case "maximized":
                restoreFullscreen = false;
                if (fullscreen) ExitFullscreen();
                WindowState = FormWindowState.Maximized;
                break;
            case "centered":
                restoreFullscreen = false;
                if (fullscreen) ExitFullscreen();
                WindowState = FormWindowState.Normal;
                CenterToScreen();
                break;
            default:
                if (fullscreen || restoreFullscreen)
                {
                    restoreFullscreen = false;
                    EnterFullscreen();
                }
                else WindowState = lastMaximized ? FormWindowState.Maximized : FormWindowState.Normal;
                break;
        }
    }

    private void ToggleFullscreen()
    {
        if (fullscreen) ExitFullscreen();
        else EnterFullscreen();
    }

    private void EnterFullscreen()
    {
        if (fullscreen)
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Bounds = Screen.FromControl(this).Bounds;
            return;
        }

        fullscreenTransition = true;
        try
        {
            fullscreenRestoreBorderStyle = FormBorderStyle;
            fullscreenRestoreWindowState = WindowState;
            fullscreenRestoreBounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            if (WindowState != FormWindowState.Normal) WindowState = FormWindowState.Normal;
            fullscreenRestoreClientSize = ClientSize;
            fullscreen = true;
            FormBorderStyle = FormBorderStyle.None;
            Bounds = Screen.FromControl(this).Bounds;
        }
        finally { fullscreenTransition = false; }
    }

    private void ExitFullscreen()
    {
        if (!fullscreen) return;
        fullscreenTransition = true;
        try
        {
            WindowState = FormWindowState.Normal;
            FormBorderStyle = fullscreenRestoreBorderStyle;
            Bounds = fullscreenRestoreBounds;
            ClientSize = fullscreenRestoreClientSize;
            fullscreen = false;
            WindowState = fullscreenRestoreWindowState;
        }
        finally { fullscreenTransition = false; }
    }

    private void RestoreWindowState()
    {
        try
        {
            var text = new AtomicStore().Read(paths.Settings, 64 * 1024);
            var state = text is null ? null : JsonSerializer.Deserialize<SavedWindowState>(text, JsonOptions.Default);
            if (state is null) return;
            var width = state.Width;
            var height = state.Height;
            if (width == 1400 && height == 850)
            {
                width = 1440;
                height = 890;
            }
            ClientSize = new Size(Math.Max(980, width), Math.Max(640, height));
            lastMaximized = state.Maximized;
            if (lastMaximized) WindowState = FormWindowState.Maximized;
            restoreFullscreen = state.Fullscreen;
        }
        catch (Exception) { }
    }

    private void SaveWindowState()
    {
        try
        {
            var size = fullscreen
                ? fullscreenRestoreClientSize
                : WindowState == FormWindowState.Normal ? ClientSize : RestoreBounds.Size;
            var maximized = fullscreen
                ? fullscreenRestoreWindowState == FormWindowState.Maximized
                : lastMaximized;
            var state = new SavedWindowState(size.Width, size.Height, maximized, fullscreen);
            new AtomicStore().Write(paths.Settings, JsonSerializer.Serialize(state, JsonOptions.Default));
        }
        catch (Exception) { }
    }

    private sealed record SavedWindowState(int Width, int Height, bool Maximized, bool Fullscreen = false);
}

internal static class JsonOptions
{
    internal static readonly JsonSerializerOptions Default = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = false
    };
}
