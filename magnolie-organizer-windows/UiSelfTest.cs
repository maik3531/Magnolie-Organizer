using System.Reflection;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class UiSelfTest
{
    internal static int Run()
    {
        if (!OperatingSystem.IsWindows()) return 0;
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-ui-self-test-{Guid.NewGuid():N}");
        Exception? failure = null;
        try
        {
            var paths = new WindowsPaths(root);
            paths.EnsureDirectories();
            Test(ProtectedAssetReader.Read(Path.Combine(AppContext.BaseDirectory, "web", "kaffee-qr.mga"), 1, 1).Length > 0,
                "Der geschützte QR-Code der Organizeroberfläche konnte nicht direkt entschlüsselt werden.");
            Test(ProtectedAssetReader.Read(Path.Combine(AppContext.BaseDirectory, "handbuch", "kaffee-qr.mga"), 1, 1).Length > 0,
                "Der geschützte QR-Code des Handbuchs konnte nicht direkt entschlüsselt werden.");
            Test(ProtectedAssetReader.Read(Path.Combine(AppContext.BaseDirectory, "handbuch", "maik-walter.mga"), 2, 2).Length > 0,
                "Das geschützte Porträt des Handbuchs konnte nicht direkt entschlüsselt werden.");
            new TraySettingsService(paths.TraySettings).Save(new TraySettings(true, true, true, true, false, false, "centered"));

            ApplicationConfiguration.Initialize();
            using var form = new MainForm(true, paths: paths);
            Test(form.ClientSize.Width >= 1200 && form.ClientSize.Height >= 700,
                $"Unerwartete normale Startgröße: {form.ClientSize.Width}x{form.ClientSize.Height}.");
            var originalHandle = nint.Zero;
            var iteration = 0;
            var readinessAttempts = 0;
            var restore = typeof(MainForm).GetMethod("RestoreFromTray", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var hide = typeof(MainForm).GetMethod("HideToTray", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var timer = new System.Windows.Forms.Timer { Interval = 100 };
            timer.Tick += async (_, _) =>
            {
                try
                {
                    if (!form.IsHandleCreated) return;
                    var webView = (Microsoft.Web.WebView2.WinForms.WebView2)typeof(MainForm)
                        .GetField("webView", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(form)!;
                    if (webView.CoreWebView2 is null || webView.Source?.Host != "app.magnolie.invalid")
                    {
                        Test(readinessAttempts++ < 300, "WebView2 lud die Organizeroberfläche nicht rechtzeitig.");
                        return;
                    }
                    originalHandle = originalHandle == nint.Zero ? form.Handle : originalHandle;
                    Test(originalHandle == form.Handle, "Das MainForm-HWND änderte sich beim Hide/Restore.");
                    Test(form.ShowInTaskbar, "Hide/Restore entfernte MainForm aus der Taskleiste.");
                    if (iteration++ < 12)
                    {
                        hide.Invoke(form, null);
                        restore.Invoke(form, null);
                        return;
                    }
                    timer.Stop();

                    var coreWebView = webView.CoreWebView2
                        ?? throw new InvalidOperationException("WebView2 war für den Schriftentest nicht bereit.");
                    var fontDiagnosticResult = await coreWebView.ExecuteScriptAsync("""
                        (() => JSON.stringify({
                          checked: document.fonts.check('15px "DejaVu Sans"', '17.08.2026'),
                          serifChecked: document.fonts.check('15px "Noto Serif"', 'Vitalwerte'),
                          status: document.fonts.status,
                          href: location.href,
                          fonts: [...document.fonts].map(face => ({
                            family: face.family,
                            weight: face.weight,
                            status: face.status
                          }))
                        }))()
                        """);
                    var fontDiagnostic = fontDiagnosticResult.StartsWith('"')
                        ? JsonSerializer.Deserialize<string>(fontDiagnosticResult) ?? "{}"
                        : fontDiagnosticResult;
                    using var fontDocument = JsonDocument.Parse(fontDiagnostic);
                    var fontRoot = fontDocument.RootElement;
                    var fontChecked = fontRoot.TryGetProperty("checked", out var checkedProperty) &&
                        checkedProperty.GetBoolean();
                    var fontLoaded = fontRoot.GetProperty("fonts").EnumerateArray().Any(face =>
                        face.GetProperty("family").GetString() == "DejaVu Sans" &&
                        face.GetProperty("status").GetString() == "loaded");
                    var serifChecked = fontRoot.TryGetProperty("serifChecked", out var serifCheckedProperty) &&
                        serifCheckedProperty.GetBoolean();
                    var serifLoaded = fontRoot.GetProperty("fonts").EnumerateArray().Any(face =>
                        face.GetProperty("family").GetString() == "Noto Serif" &&
                        face.GetProperty("status").GetString() == "loaded");
                    Test(fontChecked && fontLoaded && serifChecked && serifLoaded,
                        "Die eingebettete DejaVu-Sans-Schrift wurde nicht geladen: " + fontDiagnostic);
                    await coreWebView.ExecuteScriptAsync(
                        "document.querySelector('#knopf-einstellungen')?.click(); " +
                        "document.querySelector('#einst-tab-ueber')?.click();");
                    await TestImageAsync(coreWebView, ".kaffee-qr", 266, 266,
                        "QR-Code unter Einstellungen > Über", "https://appassets.magnolie.invalid/kaffee-qr.png");
                    Console.WriteLine("WINDOWS-ORGANIZER-SETTINGS-ABOUT-QR-OK");
                    await coreWebView.ExecuteScriptAsync("document.querySelector('#einstellungen-zu')?.click();");
                    await coreWebView.ExecuteScriptAsync("window.OrganizerTest.wechsel('gesundheit')");
                    await Task.Delay(300);
                    var layoutDiagnosticResult = await coreWebView.ExecuteScriptAsync("""
                        (() => {
                          const date = document.querySelector('.vitalwert-tabelle .datumsfeld');
                          const time = document.querySelector('.vitalwert-tabelle .gesundheit-zeit');
                          if (!date || !time) return JSON.stringify({ error: 'Gesundheitsfelder fehlen.' });
                          const style = getComputedStyle(date);
                          const timeStyle = getComputedStyle(time);
                          const pageWidth = date.closest('.seiten-inhalt').clientWidth;
                          return JSON.stringify({
                            dateFontSize: style.fontSize,
                            dateFontSizeCorrect: style.fontSize === (pageWidth <= 568 ? '12px' : '15px'),
                            dateFontFamily: style.fontFamily,
                            datePaddingLeft: style.paddingLeft,
                            datePaddingRight: style.paddingRight,
                            dateHasList: date.hasAttribute('list'),
                            dateOptions: document.querySelectorAll('#gesundheit-datum-vorschlaege option').length,
                            timeType: time.type,
                            timeChildInputs: time.querySelectorAll('input').length,
                            timeFontFamily: timeStyle.fontFamily,
                            timeAppearance: timeStyle.appearance
                          });
                        })()
                        """);
                    var layoutDiagnostic = layoutDiagnosticResult.StartsWith('"')
                        ? JsonSerializer.Deserialize<string>(layoutDiagnosticResult) ?? "{}"
                        : layoutDiagnosticResult;
                    using var layoutDocument = JsonDocument.Parse(layoutDiagnostic);
                    var layoutRoot = layoutDocument.RootElement;
                    Test(layoutRoot.TryGetProperty("dateFontSizeCorrect", out var dateFontSizeCorrect) &&
                         dateFontSizeCorrect.GetBoolean() &&
                         layoutRoot.TryGetProperty("dateFontFamily", out var dateFontFamily) &&
                         dateFontFamily.GetString()!.Contains("DejaVu Sans", StringComparison.Ordinal) &&
                         layoutRoot.TryGetProperty("datePaddingLeft", out var datePaddingLeft) &&
                         datePaddingLeft.GetString() == "0px" &&
                         layoutRoot.TryGetProperty("datePaddingRight", out var datePaddingRight) &&
                         datePaddingRight.GetString() == "0px" &&
                         layoutRoot.TryGetProperty("dateHasList", out var dateHasList) &&
                         dateHasList.GetBoolean() &&
                         layoutRoot.TryGetProperty("dateOptions", out var dateOptions) &&
                         dateOptions.GetInt32() == 3 &&
                         layoutRoot.TryGetProperty("timeType", out var timeType) && timeType.GetString() == "text" &&
                         layoutRoot.TryGetProperty("timeChildInputs", out var timeChildInputs) &&
                         timeChildInputs.GetInt32() == 0 &&
                         layoutRoot.TryGetProperty("timeFontFamily", out var timeFontFamily) &&
                         timeFontFamily.GetString() == dateFontFamily.GetString(),
                        "Datum oder Zeit verwenden nicht unverändert die Linux-Schrift und Terminsteuerung: " + layoutDiagnostic);
                    NativeMethods.ApplySystemTitleBarTheme(form.Handle);
                    var tray = (NotifyIcon)typeof(MainForm).GetField("trayIcon", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(form)!;
                    var trayMenu = tray.ContextMenuStrip!;
                    Test(trayMenu.Items.OfType<ToolStripMenuItem>().Any(item => item.Text == "Telefone"),
                        "Das dynamische Telefone-Untermenü fehlt.");
                    tray.Visible = false;
                    form.ShowReminder("UI-Selbsttest", "Native Benachrichtigungsprobe bei verborgenem Tray-Symbol.",
                        "notification", "magnolie");
                    Test(tray.BalloonTipTitle == "UI-Selbsttest", "Die native NotifyIcon-Benachrichtigung wurde nicht vorbereitet.");
                    Test(form.OwnedForms.Length == 0, "ShowReminder/Benachrichtigung erzeugte eine eigene Popup-Form.");
                    var manualPath = Path.Combine(AppContext.BaseDirectory, "handbuch", "index.html");
                    Test(await form.OpenHandbookAsync(manualPath), "Das eigene Handbuchfenster konnte nicht geöffnet werden.");
                    Test(form.OwnedForms.Count(owned => owned is HandbookForm) == 1,
                        "Das Handbuch wurde nicht in genau einem eigenen Fenster geöffnet.");
                    var handbook = (HandbookForm)form.OwnedForms.Single(owned => owned is HandbookForm);
                    var handbookWebView = (Microsoft.Web.WebView2.WinForms.WebView2)typeof(HandbookForm)
                        .GetField("webView", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(handbook)!;
                    var handbookCore = handbookWebView.CoreWebView2
                        ?? throw new InvalidOperationException("Die Handbuch-WebView2 war nicht bereit.");
                    await handbookCore.ExecuteScriptAsync(
                        "Handbuch.oeffneBuch(); Handbuch.blaettereZuId('support-with-a-coffee');");
                    await TestImageAsync(handbookCore, "#seiten .kaffee-qr", 266, 266,
                        "QR-Code im Handbuch", "https://handbuchassets.magnolie.invalid/kaffee-qr.png");
                    Console.WriteLine("WINDOWS-HANDBOOK-QR-OK");
                    await handbookCore.ExecuteScriptAsync("Handbuch.blaettereZuId('about-maik-walter');");
                    await TestImageAsync(handbookCore, "#seiten .autorenfoto", 1080, 1074,
                        "Porträt im Handbuch", "https://handbuchassets.magnolie.invalid/maik-walter.jpg");
                    Console.WriteLine("WINDOWS-HANDBOOK-PORTRAIT-OK");
                    Test(await form.OpenHandbookAsync(manualPath) && form.OwnedForms.Count(owned => owned is HandbookForm) == 1,
                        "Erneutes Öffnen erzeugte ein zweites Handbuchfenster.");
                    form.Dispose();
                    Application.ExitThread();
                }
                catch (Exception error)
                {
                    failure = error;
                    timer.Stop();
                    form.Dispose();
                    Application.ExitThread();
                }
            };
            if (form.IsHandleCreated) timer.Start();
            else form.HandleCreated += (_, _) => timer.Start();
            Application.Run(form);
            if (failure is not null) throw failure;
            Test(iteration > 12, "Der Start-hidden/WebView-Lifecycle erreichte den Hide/Restore-Test nicht.");
            Console.WriteLine("WINDOWS-BUNDLED-FONT-OK");
            Console.WriteLine("WINDOWS-HEALTH-LAYOUT-OK");
            Console.WriteLine("REMINDER-NATIVE-WINDOWS-OK");
            return 0;
        }
        catch (Exception error)
        {
            var log = Path.Combine(root, "Logs", "webview.log");
            if (File.Exists(log)) Console.Error.WriteLine(File.ReadAllText(log));
            Console.Error.WriteLine("Windows-UI-Selbsttest fehlgeschlagen: " + error);
            return 1;
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch (Exception) { }
        }
    }

    private static void Test(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static async Task TestImageAsync(Microsoft.Web.WebView2.Core.CoreWebView2 core,
        string selector, int expectedWidth, int expectedHeight, string label, string expectedSource)
    {
        var diagnostic = "{}";
        for (var attempt = 0; attempt < 100; attempt++)
        {
            var result = await core.ExecuteScriptAsync($$"""
                (() => {
                  try {
                    const image = document.querySelector({{JsonSerializer.Serialize(selector)}});
                    const csp = document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content || '';
                    if (!image) return JSON.stringify({ error: 'Bildelement fehlt.', href: location.href, csp });
                    image.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const rect = image.getBoundingClientRect();
                    const visible = image.isConnected && rect.width > 0 && rect.height > 0 &&
                      image.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) &&
                      document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) === image;
                    return JSON.stringify({ complete: image.complete, width: image.naturalWidth,
                      height: image.naturalHeight, source: image.currentSrc, visible,
                      box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                      href: location.href, csp });
                  } catch (error) { return JSON.stringify({ error: String(error) }); }
                })()
                """);
            diagnostic = result.StartsWith('"')
                ? JsonSerializer.Deserialize<string>(result) ?? "{}"
                : result;
            using var document = JsonDocument.Parse(diagnostic);
            var root = document.RootElement;
            if (!root.TryGetProperty("error", out _) &&
                root.TryGetProperty("complete", out var complete) && complete.GetBoolean() &&
                root.TryGetProperty("width", out var width) && width.GetInt32() == expectedWidth &&
                root.TryGetProperty("height", out var height) && height.GetInt32() == expectedHeight &&
                root.TryGetProperty("source", out var source) && source.GetString() == expectedSource &&
                root.TryGetProperty("visible", out var visible) && visible.GetBoolean())
            {
                Console.WriteLine($"WINDOWS-ASSET-DISPLAY {diagnostic}");
                return;
            }
            await Task.Delay(100);
        }
        Test(false, $"{label} wurde nicht vollständig entschlüsselt und dargestellt: {diagnostic}");
    }
}
