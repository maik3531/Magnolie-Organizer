using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace MagnolieOrganizer.Windows;

internal sealed class HandbookForm : Form
{
    internal static string WindowTitle => "Magnolie Organizer - " + T("Manual");
    private const string VirtualHost = "handbuch.magnolie.invalid";
    private readonly string handbookRoot;
    private readonly WindowsPaths paths;
    private readonly WebView2 webView = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(46, 58, 52) };
    private readonly TaskCompletionSource<bool> initialized = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int navigationAttempt;

    internal HandbookForm(string? handbookRoot = null, WindowsPaths? paths = null)
    {
        this.handbookRoot = handbookRoot ?? Path.Combine(AppContext.BaseDirectory, "handbuch");
        this.paths = paths ?? new WindowsPaths();
        Text = WindowTitle;
        BackColor = Color.FromArgb(46, 58, 52);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(900, 600);
        ClientSize = new Size(1280, 820);
        var iconPath = Path.Combine(AppContext.BaseDirectory, "magnolie-organizer.ico");
        if (File.Exists(iconPath)) Icon = new Icon(iconPath);
        Controls.Add(webView);
        HandleCreated += (_, _) => NativeMethods.ApplySystemTitleBarTheme(Handle);
        Load += async (_, _) => await InitializeAsync();
    }

    internal Task<bool> Ready => initialized.Task;

    private async Task InitializeAsync()
    {
        try
        {
            if (!File.Exists(Path.Combine(handbookRoot, "index.html")))
                throw new FileNotFoundException(T("The Magnolie manual is not installed."));
            var environment = await WebViewEnvironmentProvider.GetAsync(paths);
            await webView.EnsureCoreWebView2Async(environment);
            var core = webView.CoreWebView2;
            core.SetVirtualHostNameToFolderMapping(VirtualHost, handbookRoot, CoreWebView2HostResourceAccessKind.DenyCors);
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            var language = NativeLocalization.Language;
            await core.AddScriptToExecuteOnDocumentCreatedAsync($$"""
                (() => {
                  const handlers = { bruecke: { postMessage: value => window.chrome.webview.postMessage(String(value)) } };
                   Object.defineProperty(window, "webkit", { value: { messageHandlers: handlers }, writable: false });
                   window.__MAGNOLIE_SPRACHE__ = {{JsonSerializer.Serialize(language)}};
                 })();
                """);
            core.WebMessageReceived += async (_, eventArgs) =>
            {
                if (!IsInternal(eventArgs.Source)) return;
                await HandleMessageAsync(eventArgs.TryGetWebMessageAsString());
            };
            core.NavigationStarting += (_, eventArgs) =>
            {
                if (IsInternal(eventArgs.Uri)) return;
                eventArgs.Cancel = true;
                if (IsSafeExternal(eventArgs.Uri)) NativeMethods.OpenWithShell(eventArgs.Uri);
            };
            core.NewWindowRequested += (_, eventArgs) =>
            {
                eventArgs.Handled = true;
                if (!IsInternal(eventArgs.Uri) && IsSafeExternal(eventArgs.Uri)) NativeMethods.OpenWithShell(eventArgs.Uri);
            };
            core.PermissionRequested += (_, eventArgs) => eventArgs.State = CoreWebView2PermissionState.Deny;
            core.NavigationCompleted += async (_, eventArgs) => await NavigationCompletedAsync(eventArgs);
            NavigateToHandbook();
            try
            {
                await initialized.Task.WaitAsync(TimeSpan.FromSeconds(20));
            }
            catch (TimeoutException)
            {
                WriteDiagnostic($"Handbuch-Navigation nach {navigationAttempt} Versuch(en) ohne Abschluss.");
                initialized.TrySetResult(false);
            }
        }
        catch (Exception error)
        {
            WriteDiagnostic($"Handbuch-Initialisierung fehlgeschlagen: {error}");
            initialized.TrySetResult(false);
            MessageBox.Show(this, error.Message, WindowTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    private async Task NavigationCompletedAsync(CoreWebView2NavigationCompletedEventArgs eventArgs)
    {
        if (initialized.Task.IsCompleted) return;
        var source = webView.Source?.AbsoluteUri ?? "";
        WriteDiagnostic($"Handbuch-Navigation Versuch {navigationAttempt}: " +
            $"success={eventArgs.IsSuccess}, status={eventArgs.WebErrorStatus}, source={source}");
        if (eventArgs.IsSuccess && IsInternal(source))
        {
            initialized.TrySetResult(true);
            return;
        }
        if (navigationAttempt >= 3 || !IsTransientStartupFailure(eventArgs.WebErrorStatus))
        {
            initialized.TrySetResult(false);
            return;
        }

        await Task.Delay(TimeSpan.FromMilliseconds(250 * navigationAttempt));
        if (!IsDisposed && !Disposing && !initialized.Task.IsCompleted) NavigateToHandbook();
    }

    private void NavigateToHandbook()
    {
        navigationAttempt++;
        var target = $"https://{VirtualHost}/index.html";
        WriteDiagnostic($"Handbuch-Navigation Versuch {navigationAttempt} gestartet: {target}");
        webView.CoreWebView2.Navigate(target);
    }

    private static bool IsTransientStartupFailure(CoreWebView2WebErrorStatus status) => status is
        CoreWebView2WebErrorStatus.Unknown or
        CoreWebView2WebErrorStatus.ServerUnreachable or
        CoreWebView2WebErrorStatus.Timeout or
        CoreWebView2WebErrorStatus.ConnectionAborted or
        CoreWebView2WebErrorStatus.ConnectionReset or
        CoreWebView2WebErrorStatus.Disconnected or
        CoreWebView2WebErrorStatus.CannotConnect or
        CoreWebView2WebErrorStatus.HostNameNotResolved or
        CoreWebView2WebErrorStatus.OperationCanceled or
        CoreWebView2WebErrorStatus.UnexpectedError;

    private void WriteDiagnostic(string message)
    {
        RotatingLog.Append(Path.Combine(paths.Logs, "webview.log"), $"{DateTimeOffset.Now:O} {message}");
    }

    private async Task HandleMessageAsync(string message)
    {
        try
        {
            var value = JsonNode.Parse(message) as JsonObject;
            if (value?["cmd"]?.GetValue<string>() != "drucken" || value["html"] is not JsonValue htmlValue ||
                !htmlValue.TryGetValue<string>(out var html) || html.Length is < 1 or > 8_000_000) return;
            var print = new HtmlPrintForm(html, paths, T("Manual")) { Icon = Icon };
            print.Show(this);
            await print.Ready;
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException)
        {
            MessageBox.Show(this, T("The manual could not be opened.") + " " + error.Message,
                WindowTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static bool IsInternal(string uri) =>
        Uri.TryCreate(uri, UriKind.Absolute, out var parsed) &&
        parsed.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase) &&
        parsed.Host.Equals(VirtualHost, StringComparison.OrdinalIgnoreCase);

    private static bool IsSafeExternal(string uri) =>
        Uri.TryCreate(uri, UriKind.Absolute, out var parsed) &&
        parsed.Scheme is "http" or "https" or "mailto" or "tel";

    private static string T(string message) => NativeLocalization.Gettext(message);
}

internal sealed class HtmlPrintForm : Form
{
    private readonly string html;
    private readonly WindowsPaths paths;
    private readonly WebView2 webView = new() { Dock = DockStyle.Fill };
    private readonly TaskCompletionSource initialized = new(TaskCreationOptions.RunContinuationsAsynchronously);

    internal HtmlPrintForm(string html, WindowsPaths paths, string documentName)
    {
        this.html = html;
        this.paths = paths;
        Text = "Magnolie Organizer - " + NativeLocalization.Gettext("Print") +
            (documentName.Length > 0 ? " - " + documentName : "");
        StartPosition = FormStartPosition.CenterParent;
        ClientSize = new Size(900, 700);
        Controls.Add(webView);
        Load += async (_, _) => await InitializeAsync();
    }

    internal Task Ready => initialized.Task;

    private async Task InitializeAsync()
    {
        try
        {
            var environment = await WebViewEnvironmentProvider.GetAsync(paths);
            await webView.EnsureCoreWebView2Async(environment);
            webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
            webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            webView.CoreWebView2.PermissionRequested += (_, eventArgs) => eventArgs.State = CoreWebView2PermissionState.Deny;
            webView.CoreWebView2.NavigationCompleted += (_, eventArgs) =>
            {
                if (eventArgs.IsSuccess) webView.CoreWebView2.ShowPrintUI(CoreWebView2PrintDialogKind.System);
                initialized.TrySetResult();
            };
            webView.NavigateToString(html);
        }
        catch (Exception error)
        {
            initialized.TrySetException(error);
            Close();
        }
    }
}
