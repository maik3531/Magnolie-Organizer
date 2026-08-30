using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace MagnolieOrganizer.Windows;

internal sealed class MainForm : Form
{
    private const string VirtualHost = "app.magnolie.invalid";
    private readonly WebView2 webView = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(46, 58, 52) };
    private readonly WindowsPaths paths = new();
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
    private bool reminderAutostart;
    private TelefonCoordinator? telefonCoordinator;
    private JsonObject? pendingTelefonSms;
    private JsonObject? currentIncomingCall;
    private HandbookForm? handbookForm;

    internal void SetTelefonCoordinator(TelefonCoordinator coordinator) => telefonCoordinator = coordinator;

    internal MainForm(bool trayStart = false, bool reminderStart = false)
    {
        Text = "Magnolie Organizer";
        BackColor = Color.FromArgb(46, 58, 52);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(980, 640);
        ClientSize = new Size(1440, 890);
        var iconPath = Path.Combine(AppContext.BaseDirectory, "magnolie-organizer.ico");
        if (File.Exists(iconPath)) Icon = new Icon(iconPath);
        traySettingsService = new TraySettingsService(paths.TraySettings);
        traySettings = traySettingsService.Load(paths.Data);
        reminderAutostart = reminderStart;
        trayIcon = CreateTrayIcon(Icon ?? SystemIcons.Application);
        Controls.Add(webView);
        HandleCreated += (_, _) => NativeMethods.ApplySystemTitleBarTheme(Handle);
        Load += async (_, _) => await InitializeWebViewAsync();
        FormClosing += OnFormClosing;
        FormClosed += (_, _) => { handbookForm?.Close(); dispatcher?.Dispose(); SaveWindowState(); trayIcon.Dispose(); };
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
        traySettings = TraySettings.FromJson(settings);
        var error = "";
        try { traySettingsService.Save(traySettings); }
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

    internal void SetReminderAutostart(bool active)
    {
        reminderAutostart = active;
        _ = ConfigureAutostart();
    }

    private string ConfigureAutostart() => TraySettingsService.ConfigureAutostart(
        reminderAutostart || traySettings.Aktiv && traySettings.Autostart,
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
        if (InvokeRequired) { BeginInvoke(() => TrackIncomingCall(payload)); return; }
        var state = payload["state"]?.GetValue<string>() ?? "";
        if (state == "idle")
        {
            if (currentIncomingCall?["call_ref"]?.GetValue<string>() == payload["call_ref"]?.GetValue<string>())
                currentIncomingCall = null;
            return;
        }
        if (payload["direction"]?.GetValue<string>() == "incoming") currentIncomingCall = payload.DeepClone().AsObject();
    }

    internal void ShowIncomingCall(JsonElement payload)
    {
        if (InvokeRequired) { BeginInvoke(() => ShowIncomingCall(payload)); return; }
        var name = payload.TryGetProperty("name", out var nameNode) ? nameNode.GetString() ?? "" : "";
        var number = payload.TryGetProperty("nummer", out var numberNode) ? numberNode.GetString() ?? "" : "";
        trayIcon.Visible = true;
        ShowNotification(T("Incoming call"), string.IsNullOrWhiteSpace(name) ? number : name);
        HideTemporaryTrayIcon();
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
        if (InvokeRequired) { BeginInvoke(() => ShowReminder(title, message, kind, style)); return; }
        kind = kind is "notification" or "sound" or "both" ? kind : "both";
        if (kind is "sound" or "both")
            NativeMethods.PlaySoundFile(Path.Combine(AppContext.BaseDirectory, "erinnerung.wav"));
        if (kind is not ("notification" or "both")) return;

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

    internal async Task SendAsync(string function, object payload)
    {
        if (IsDisposed || Disposing || shutdownStarted) return;
        if (InvokeRequired)
        {
            var completion = new TaskCompletionSource();
            try { BeginInvoke(async () =>
            {
                try { await SendAsync(function, payload); completion.SetResult(); }
                catch (Exception error) { completion.SetException(error); }
            }); }
            catch (InvalidOperationException) { completion.SetResult(); }
            await completion.Task;
            return;
        }

        if (webView.CoreWebView2 is null) return;
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
            """);
    }

    internal async void CloseAfterSave()
    {
        if (InvokeRequired) { BeginInvoke(CloseAfterSave); return; }
        if (shutdownStarted) return;
        shutdownStarted = true;
        try
        {
            if (dispatcher is not null) await dispatcher.ShutdownAsync();
        }
        catch (Exception error)
        {
            WriteWebViewDiagnostic($"Fehler beim Beenden: {error}");
            shutdownStarted = false;
            closeRequested = false;
            exitFromTray = false;
            ShowSaveWarning();
            return;
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
            dispatcher = new BridgeDispatcher(this, paths);
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
        if (trayEnabled && closeToTray && !exitFromTray)
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
            await webView.CoreWebView2.ExecuteScriptAsync("App.vorBeenden();");
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
