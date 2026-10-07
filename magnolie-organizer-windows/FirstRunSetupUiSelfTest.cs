using System.Reflection;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class FirstRunSetupUiSelfTest
{
    internal static int Run()
    {
        if (!OperatingSystem.IsWindows()) return 0;
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-setup-ui-self-test-{Guid.NewGuid():N}");
        try
        {
            ApplicationConfiguration.Initialize();
            VerifySkip(Path.Combine(root, "skip-native"));
            VerifyComplete(Path.Combine(root, "complete-native"));
            VerifyAutomaticPhoneServices(Path.Combine(root, "automatic-phone-services"));
            VerifyOwnPhonePrompt(Path.Combine(root, "own-phone-prompt"));
            VerifyHolidayLanguages(Path.Combine(root, "holidays-native"));
            Console.WriteLine("WINDOWS-FIRST-RUN-UI-OK");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Windows-Ersteinrichtungs-Selbsttest fehlgeschlagen: " + error);
            return 1;
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch (Exception) { }
        }
    }

    private static void VerifySkip(string root)
    {
        var paths = new WindowsPaths(root);
        paths.EnsureDirectories();
        var state = new FirstRunSetupState(paths);
        state.Begin();
        using var form = new FirstRunSetupForm(paths, state);
        Test((string)(form.GetType().GetField("backupInterval", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(form) ?? "") == "weekly",
            "Der normale Assistent schlägt nicht den wöchentlichen Sicherungsrhythmus vor.");
        form.ClientSize = new Size(960, 780);
        form.Show();
        Application.DoEvents();
        VerifyWindow(form);
        var skip = Field<Button>(form, "skip");
        Test(skip.Visible && skip.Enabled, "Ueberspringen ist auf der Willkommensseite nicht erreichbar.");
        Test(TextRenderer.MeasureText(skip.Text, skip.Font).Width <= skip.ClientSize.Width - 12,
            "Die Beschriftung der Ueberspringen-Schaltflaeche ist abgeschnitten.");
        skip.PerformClick();
        Application.DoEvents();
        Test(form.DialogResult == DialogResult.OK && form.Selections is
            { BackupInterval: "manual", OpenHandbook: false },
            "Ueberspringen liefert nicht die sicheren Standardwerte.");
        VerifyMarker(paths, "skipped");
    }

    private static void VerifyComplete(string root)
    {
        var paths = new WindowsPaths(root);
        paths.EnsureDirectories();
        var state = new FirstRunSetupState(paths);
        state.Begin();
        NativeLocalization.SetLanguage("de");
        using var form = new FirstRunSetupForm(paths, state);
        form.ClientSize = new Size(960, 780);
        form.Show();
        Application.DoEvents();
        VerifyWindow(form);

        var next = Field<Button>(form, "next");
        var back = Field<Button>(form, "back");
        var host = Field<Panel>(form, "pageHost");
        SetField(form, "language", "de");
        NativeLocalization.SetLanguage("de");
        for (var expectedPage = 0; expectedPage <= 6; expectedPage++)
        {
            Application.DoEvents();
            Test(IntField(form, "page") == expectedPage, $"Unerwartete Assistentenseite {expectedPage}.");
            Test(host.Controls.Count == 1 && host.Controls[0].Width <= host.ClientSize.Width,
                $"Assistentenseite {expectedPage} ist leer oder horizontal abgeschnitten.");
            Test(host.Controls[0].PreferredSize.Height <= host.ClientSize.Height ||
                 host.AutoScroll && host.VerticalScroll.Visible,
                $"Assistentenseite {expectedPage} ist bei {form.DeviceDpi} DPI nicht scrollbar: " +
                $"Inhalt {host.Controls[0].PreferredSize.Height}, sichtbar {host.ClientSize.Height}.");
            foreach (var button in Descendants(host).OfType<Button>())
                Test(TextRenderer.MeasureText(button.Text, button.Font).Width + 8 <= button.ClientSize.Width,
                    $"Schaltflaechenbeschriftung ist bei {form.DeviceDpi} DPI abgeschnitten: {button.Text}");
            Test(next.Visible && next.Enabled && next.Text.Length > 0,
                $"Weiter-Schaltflaeche fehlt auf Seite {expectedPage}.");
            Test(back.Visible == (expectedPage > 0),
                $"Zurueck-Sichtbarkeit ist auf Seite {expectedPage} falsch.");
            if (expectedPage == 1)
            {
                Test(Descendants(host).OfType<Label>().Any(label => label.Text == "Bundesland / Region"),
                    "Die deutsche Anschriftseite bezeichnet das Bundesland weiterhin als Formatregion.");
                SetField(form, "country", "DE");
                SetField(form, "addressImported", true);
                var render = form.GetType().GetMethod("RenderPage", BindingFlags.Instance | BindingFlags.NonPublic)!;
                render.Invoke(form, null);
                Application.DoEvents();
                var choices = Descendants(host).OfType<ComboBox>().ToArray();
                var hint = Color.FromArgb(228, 224, 199);
                Test(choices.Length == 2 && choices.All(choice => choice.DrawMode == DrawMode.OwnerDrawFixed) &&
                     choices[0].BackColor != hint && choices[1].BackColor == hint,
                    "Imported address hints must be drawable in native country and region selections.");
                choices[1].SelectedIndex = 1;
                Test(choices[1].BackColor != hint, "Selecting an optional region must clear its import hint.");
                SetField(form, "region", "");
                SetField(form, "addressImported", false);
                render.Invoke(form, null);
            }
            if (expectedPage == 4)
                Test(Descendants(host).OfType<TextBox>().Single().AccessibilityObject.Name == NativeLocalization.Gettext("Tab name"),
                    "Das Eingabefeld fuer die eigene Registerkarte hat keinen zugaenglichen Namen.");
            if (expectedPage == 3)
            {
                back.PerformClick();
                Application.DoEvents();
                Test(IntField(form, "page") == 2, "Zurueck navigiert nicht genau eine Seite.");
                next.PerformClick();
                Application.DoEvents();
                Test(IntField(form, "page") == 3, "Weiter stellt die Seite nach Zurueck nicht wieder her.");
            }
            if (expectedPage < 6) next.PerformClick();
        }

        SetField(form, "language", "de");
        SetField(form, "firstName", "  Ada  ");
        SetField(form, "lastName", "Lovelace");
        SetField(form, "country", "DE");
        SetField(form, "region", "Mecklenburg-Vorpommern");
        SetField(form, "addressSort", "first-name");
        SetField(form, "backupInterval", "daily");
        SetField(form, "startWithWindows", true);
        SetField(form, "weatherEnabled", true);
        SetField(form, "restoreRequest", true);
        next.PerformClick();
        Application.DoEvents();

        Test(form.DialogResult == DialogResult.OK && form.Selections is not null,
            "Der vollstaendige Assistent wurde nicht erfolgreich abgeschlossen.");
        var selections = form.Selections!;
        Test(selections.Language == "de" && selections.Address.FirstName == "Ada" &&
             selections.Address.LastName == "Lovelace" && selections.Address.State == "DE-MV" &&
             selections.AddressSort == "first-name" &&
             selections.OneTimeImports.Count == 0 &&
             selections.BackupInterval == "daily" && selections.Autostart && selections.Tray &&
             selections.Weather && selections.RestoreRequest,
            "Die sichtbaren Assistentenentscheidungen wurden nicht normalisiert und weitergegeben.");
        Test(RegionalSettings.Read(paths.RegionalSettings)["language"]?.GetValue<string>() == "de",
            "Die Sprachwahl wurde nicht im isolierten Profil gespeichert.");
        VerifyMarker(paths, "completed");
    }

    private sealed class AutomaticPhoneFixture : IFirstRunSetupPhoneServices
    {
        public IReadOnlyList<SetupPhoneCapability> Capabilities => [
            new("wifi", true, true), new("bluetooth", true, false), new("kdeconnect", false, true)];
        internal IReadOnlyList<string> Committed { get; private set; } = [];
        public Task<SetupPhoneResult> ConnectAsync(string transport, Func<SetupPhonePrompt, Task<string?>> prompt, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("The fixture does not connect to devices.");
        public Task<IReadOnlyList<string>> ConnectedAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<string>>(["wifi", "bluetooth", "kdeconnect"]);
        public Task CommitStartupAsync(IReadOnlyList<string> transports, CancellationToken cancellationToken)
        { Committed = transports.ToArray(); return Task.CompletedTask; }
    }

    private static void VerifyAutomaticPhoneServices(string root)
    {
        var paths = new WindowsPaths(root);
        paths.EnsureDirectories();
        var state = new FirstRunSetupState(paths);
        state.Begin();
        var phone = new AutomaticPhoneFixture();
        using var form = new FirstRunSetupForm(paths, state, phoneServices: phone);
        form.Show();
        Application.DoEvents();
        var connected = Field<Dictionary<string, SetupPhoneResult>>(form, "connectedPhones");
        foreach (var capability in phone.Capabilities)
            connected[capability.Transport] = new(capability.Transport, "fixture-" + capability.Transport, "Fixture phone", true);
        SetField(form, "page", 5);
        Field<Button>(form, "next").PerformClick();
        Application.DoEvents();
        Test(IntField(form, "page") == 6 && !Descendants(Field<Panel>(form, "pageHost")).OfType<CheckBox>()
            .Any(box => box.Text.StartsWith(NativeLocalization.Gettext("Start required phone background services automatically"), StringComparison.Ordinal)),
             "Die Kopplung verlangt noch einen zusätzlichen Dienst-Schalter.");
        var automatic = Descendants(Field<Panel>(form, "pageHost")).OfType<CheckBox>().Single(box =>
            box.Text == NativeLocalization.Gettext("Start Magnolie with Windows in the notification area (tray)"));
        Test(automatic.Checked && !automatic.Enabled,
            "Required phone startup was saved differently from its displayed checkbox.");
        Field<Button>(form, "next").PerformClick();
        Application.DoEvents();
        Test(form.DialogResult == DialogResult.OK && form.Selections?.PhoneBackgroundServices.SequenceEqual(["wifi"]) == true &&
            phone.Committed.SequenceEqual(["wifi"]) && form.Selections.Autostart && form.Selections.Tray,
            "Unterstützte Dienste wurden nicht automatisch übernommen oder eine nicht unterstützte Variante wurde gestartet.");
        Console.WriteLine("WINDOWS-FIRST-RUN-AUTO-SERVICES-OK");
    }

    private static void VerifyOwnPhonePrompt(string root)
    {
        var paths = new WindowsPaths(root);
        paths.EnsureDirectories();
        var state = new FirstRunSetupState(paths);
        state.Begin();
        using var form = new FirstRunSetupForm(paths, state);
        form.Show(); Application.DoEvents();
        var method = typeof(FirstRunSetupForm).GetMethod("ShowPhonePromptAsync",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        foreach (var (canOwn, selected, cancel) in new[] {
                     (true, false, false), (true, true, false), (false, false, false), (true, true, true) })
        {
            Exception? failure = null;
            var handled = false;
            var deadline = DateTime.UtcNow.AddSeconds(8);
            using var timer = new System.Windows.Forms.Timer { Interval = 50 };
            timer.Tick += (_, _) =>
            {
                var dialog = Application.OpenForms.Cast<Form>().FirstOrDefault(window => window != form &&
                    window.Text == NativeLocalization.Gettext("Phone connection"));
                if (dialog is null) return;
                try
                {
                    if (DateTime.UtcNow > deadline) throw new TimeoutException("Phone prompt deadline");
                    var checkbox = Descendants(dialog).OfType<CheckBox>().SingleOrDefault(box => box.Name == "setup-own-phone");
                    Test((checkbox is not null) == canOwn, "Own-device choice did not match the available capability.");
                    if (checkbox is not null)
                    {
                        Test(!checkbox.Checked, "Own-device consent must start unchecked.");
                        checkbox.Checked = selected;
                    }
                    handled = true;
                    dialog.DialogResult = cancel ? DialogResult.Cancel : DialogResult.OK;
                }
                catch (Exception error) { failure = error; dialog.DialogResult = DialogResult.Cancel; }
                timer.Stop(); dialog.Close();
            };
            timer.Start();
            var task = (Task<string?>)method.Invoke(form, [new SetupPhonePrompt("confirm",
                [new SetupSource("synthetic-phone", "Synthetic phone")], "123 456", canOwn)])!;
            timer.Stop();
            if (failure is not null) throw failure;
            Test(handled && task.IsCompletedSuccessfully, "Native phone prompt was not exercised.");
            Test(task.Result == (cancel ? null : canOwn && selected ? "accept-own" : "accept"),
                "Native phone prompt lost the explicit choice or granted it after cancel.");
        }
        form.Close();
        Console.WriteLine("WINDOWS-FIRST-RUN-OWN-PHONE-OK");
    }

    private static void VerifyWindow(FirstRunSetupForm form)
    {
        Test(form.Visible && form.ClientSize.Width >= 900 && form.ClientSize.Height >= 680,
            $"Unerwartete Assistentengroesse: {form.ClientSize.Width}x{form.ClientSize.Height}.");
        Test(!Descendants(form).Any(control => control.GetType().FullName?.Contains("WebView2", StringComparison.Ordinal) == true),
            "Der native Assistent erzeugt vorzeitig eine WebView2-Laufzeit.");
        Test(!Field<Control>(form, "progress").TabStop,
            "Die nicht interaktive Fortschrittsanzeige darf kein leeres Tabulatorziel sein.");
    }

    private static void VerifyHolidayLanguages(string root)
    {
        var elapsed = System.Diagnostics.Stopwatch.StartNew();
        foreach (var language in new[] { "be", "en", "de", "fr", "es", "it", "nl", "pt", "ru", "cs", "pl", "hsb", "da", "nb", "hi", "zh_CN", "ja", "ar", "uk", "tr" })
        {
            Console.WriteLine($"WINDOWS-FIRST-RUN-HOLIDAY-BEGIN {language} elapsedMs={elapsed.ElapsedMilliseconds}");
            var paths = new WindowsPaths(Path.Combine(root, language));
            var state = new FirstRunSetupState(paths);
            state.Begin();
            NativeLocalization.SetLanguage(language);
            using var form = new FirstRunSetupForm(paths, state);
            // Keep this test independent of the welcome sound/device services.
            SetField(form, "welcomeSoundPlayed", true);
            SetField(form, "language", language);
            SetField(form, "page", 1);
            var render = form.GetType().GetMethod("RenderPage", BindingFlags.Instance | BindingFlags.NonPublic)!;
            form.Show();
            foreach (var (country, region, name) in new[] { ("DE", "DE-SN", "Saxony"), ("AT", "AT-9", "Vienna"), ("CH", "CH-ZH", "Zurich") })
            {
                SetField(form, "country", country);
                SetField(form, "region", region);
                render.Invoke(form, null);
                Application.DoEvents();
                var check = Descendants(form).OfType<CheckBox>().Single(c => c.Name == "setup-school-holidays");
                Test(check.Visible && !check.Checked && check.Text == NativeLocalization.Gettext(
                    "Show school holidays for %(state)s in the calendar?").Replace("%(state)s", NativeLocalization.Gettext(name)),
                    "Localized native school-holiday consent must start unchecked and name the selected region.");
                check.Checked = true;
                render.Invoke(form, null);
                Test(Descendants(form).OfType<CheckBox>().Single(c => c.Name == "setup-school-holidays").Checked,
                    "Re-rendering the same selection lost consent.");
            }
            SetField(form, "country", "AT");
            SetField(form, "region", "DE-SN");
            render.Invoke(form, null);
            Test(!Descendants(form).OfType<CheckBox>().Single(c => c.Name == "setup-school-holidays").Visible,
                "A mismatched country must not offer holiday retrieval.");
            form.Close();
            Console.WriteLine($"WINDOWS-FIRST-RUN-HOLIDAY-END {language} elapsedMs={elapsed.ElapsedMilliseconds}");
            Test(!JsonSerializer.Deserialize<FirstRunSetupMarker>(new AtomicStore().ReadRecoverableJson(paths.FirstRunSetup)!)!.Selections.SchoolHolidays,
                "Closing native setup persisted staged consent.");
        }
    }

    private static IEnumerable<Control> Descendants(Control parent)
    {
        foreach (Control control in parent.Controls)
        {
            yield return control;
            foreach (var child in Descendants(control)) yield return child;
        }
    }

    private static void VerifyMarker(WindowsPaths paths, string expectedStatus)
    {
        using var document = JsonDocument.Parse(new AtomicStore().ReadRecoverableJson(paths.FirstRunSetup)!);
        Test(document.RootElement.GetProperty("Status").GetString() == expectedStatus &&
             new FirstRunSetupState(paths).Classify() == FirstRunSetupClassification.Complete,
            $"Setup-Marker wurde nicht als {expectedStatus} atomar gespeichert.");
    }

    private static T Field<T>(object instance, string name) where T : class =>
        (T)(instance.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(instance)
            ?? throw new MissingFieldException(instance.GetType().Name, name));

    private static int IntField(object instance, string name) =>
        (int)(instance.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(instance)
            ?? throw new MissingFieldException(instance.GetType().Name, name));

    private static void SetField(object instance, string name, object value) =>
        (instance.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new MissingFieldException(instance.GetType().Name, name)).SetValue(instance, value);

    private static void Test(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
