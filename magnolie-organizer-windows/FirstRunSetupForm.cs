using System.Diagnostics;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class FirstRunSetupForm : Form
{
    // Generated from handbook mobile-downloads.json by tools/sync_mobile_downloads.py.
    internal const string MagnolieNotesUrl = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes.apk";
    internal const string KdeConnectUrl = "https://play.google.com/store/apps/details?id=org.kde.kdeconnect_tp";
    private static readonly Color Felt = Color.FromArgb(46, 58, 52);
    private static readonly Color FeltLight = Color.FromArgb(63, 77, 69);
    private static readonly Color Paper = Color.FromArgb(246, 239, 220);
    private static readonly Color Ink = Color.FromArgb(61, 43, 31);
    private static readonly Color Gold = Color.FromArgb(190, 151, 72);
    private static readonly CountryChoice[] Countries =
    [
        new("DE", "Germany"), new("AT", "Austria"), new("CH", "Switzerland"),
        new("LI", "Liechtenstein"), new("LU", "Luxembourg"), new("BE", "Belgium"),
        new("NL", "Netherlands"), new("FR", "France"), new("IT", "Italy"),
        new("PL", "Poland"), new("CZ", "Czechia"), new("ES", "Spain")
    ];
    private static readonly RegionChoice[] Regions =
    [
        new("DE", "DE-BW", "Baden-Württemberg"), new("DE", "DE-BY", "Bavaria"),
        new("DE", "DE-BE", "Berlin"), new("DE", "DE-BB", "Brandenburg"), new("DE", "DE-HB", "Bremen"),
        new("DE", "DE-HH", "Hamburg"), new("DE", "DE-HE", "Hesse"),
        new("DE", "DE-MV", "Mecklenburg-Western Pomerania"), new("DE", "DE-NI", "Lower Saxony"),
        new("DE", "DE-NW", "North Rhine-Westphalia"), new("DE", "DE-RP", "Rhineland-Palatinate"),
        new("DE", "DE-SL", "Saarland"), new("DE", "DE-SN", "Saxony"),
        new("DE", "DE-ST", "Saxony-Anhalt"), new("DE", "DE-SH", "Schleswig-Holstein"),
        new("DE", "DE-TH", "Thuringia"), new("AT", "AT-1", "Burgenland"),
        new("AT", "AT-2", "Carinthia"), new("AT", "AT-3", "Lower Austria"),
        new("AT", "AT-4", "Upper Austria"), new("AT", "AT-5", "Salzburg"),
        new("AT", "AT-6", "Styria"), new("AT", "AT-7", "Tyrol"), new("AT", "AT-8", "Vorarlberg"),
        new("AT", "AT-9", "Vienna"), new("CH", "CH-AG", "Aargau"),
        new("CH", "CH-AI", "Appenzell Innerrhoden"), new("CH", "CH-AR", "Appenzell Ausserrhoden"),
        new("CH", "CH-BE", "Bern"), new("CH", "CH-BL", "Basel-Landschaft"),
        new("CH", "CH-BS", "Basel-Stadt"), new("CH", "CH-FR", "Fribourg"),
        new("CH", "CH-GE", "Geneva"), new("CH", "CH-GL", "Glarus"), new("CH", "CH-GR", "Grisons"),
        new("CH", "CH-JU", "Jura"), new("CH", "CH-LU", "Lucerne"), new("CH", "CH-NE", "Neuchâtel"),
        new("CH", "CH-NW", "Nidwalden"), new("CH", "CH-OW", "Obwalden"),
        new("CH", "CH-SG", "St. Gallen"), new("CH", "CH-SH", "Schaffhausen"),
        new("CH", "CH-SO", "Solothurn"), new("CH", "CH-SZ", "Schwyz"),
        new("CH", "CH-TG", "Thurgau"), new("CH", "CH-TI", "Ticino"), new("CH", "CH-UR", "Uri"),
        new("CH", "CH-VD", "Vaud"), new("CH", "CH-VS", "Valais"), new("CH", "CH-ZG", "Zug"),
        new("CH", "CH-ZH", "Zurich")
    ];
    private readonly WindowsPaths paths;
    private readonly FirstRunSetupState setupState;
    private readonly IFirstRunSetupServices? setupServices;
    private readonly Func<OpenFileDialog, IWin32Window, DialogResult>? importDialog;
    private readonly IFirstRunSetupPhoneServices? phoneServices;
    private readonly Dictionary<string, SetupPhoneResult> connectedPhones = new(StringComparer.Ordinal);
    private readonly Dictionary<string, CheckBox> phoneStartupChecks = new(StringComparer.Ordinal);
    private readonly CancellationTokenSource setupCancellation = new();
    private readonly Dictionary<string, JsonObject> stagedImports = new(StringComparer.Ordinal);
    private readonly List<string> calendarUids = [];
    private string addressBookUid = "";
    private string connectionToken = "";
    private bool setupBusy;
    private readonly Panel pageHost = new()
    {
        Dock = DockStyle.Fill, BackColor = Paper, AutoScroll = true,
        Padding = new Padding(42, 30, 42, 22)
    };
    private readonly SetupProgress progress = new()
        { Dock = DockStyle.Top, Height = 46, TabStop = false, AccessibleRole = AccessibleRole.ProgressBar };
    private readonly Button back = new();
    private readonly Button next = new();
    private readonly Button skip = new();
    private readonly Button welcomeManual = new();
    private readonly HashSet<string> registers = new(StringComparer.Ordinal)
        { "tasks", "addresses", "notes", "anniversaries", "planner", "health" };
    private int page;
    private string language = "system";
    private string addressSource = "later";
    private string firstName = "";
    private string lastName = "";
    private string street = "";
    private string postalCode = "";
    private string city = "";
    private string country = FirstRunSetupAddress.SystemCountry(System.Globalization.CultureInfo.CurrentCulture.Name);
    private bool addressImported;
    private Control? firstMissingAddress;
    private string region = "";
    private bool schoolHolidays;
    private string schoolHolidayRegion = "";
    private string addressSort = "last-name";
    private bool customRegisterEnabled;
    private bool customTabChanged;
    private string customRegisterName = "";
    private readonly List<FirstRunSetupCustomModule> customModules = [];
    private bool customOrganizerChanged;
    private string backupPath;
    private string backupInterval = "weekly";
    private bool startWithWindows;
    private bool weatherEnabled;
    private bool restoreRequest;
    private bool welcomeSoundPlayed;

    internal FirstRunSetupSelections? Selections { get; private set; }

    internal FirstRunSetupForm(WindowsPaths paths, FirstRunSetupState setupState,
        IFirstRunSetupServices? setupServices = null,
        Func<OpenFileDialog, IWin32Window, DialogResult>? importDialog = null,
        IFirstRunSetupPhoneServices? phoneServices = null)
    {
        this.paths = paths;
        this.setupState = setupState;
        this.setupServices = setupServices;
        this.importDialog = importDialog;
        this.phoneServices = phoneServices;
        FormClosed += (_, _) => { setupCancellation.Cancel(); stagedImports.Clear(); };
        backupPath = paths.Backups;
        language = RegionalSettings.Read(paths.RegionalSettings)["language"]?.GetValue<string>() ?? "system";

        Text = T("Set up Magnolie Organizer");
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(820, 680);
        ClientSize = new Size(960, 780);
        BackColor = Felt;
        Font = new Font("Segoe UI", 10);
        FormBorderStyle = FormBorderStyle.Sizable;
        var iconPath = Path.Combine(AppContext.BaseDirectory, "magnolie-organizer.ico");
        if (File.Exists(iconPath)) Icon = new Icon(iconPath);
        HandleCreated += (_, _) => NativeMethods.ApplySystemTitleBarTheme(Handle);
        Shown += (_, _) => PlayWelcomeSound();

        var header = BuildHeader();
        var paper = new Panel { Dock = DockStyle.Fill, BackColor = Paper, Padding = new Padding(1) };
        paper.Paint += (_, eventArgs) =>
        {
            using var pen = new Pen(Color.FromArgb(181, 164, 126));
            eventArgs.Graphics.DrawRectangle(pen, 0, 0, paper.Width - 1, paper.Height - 1);
        };
        paper.Controls.Add(pageHost);
        paper.Controls.Add(BuildNavigation());
        Controls.Add(paper);
        Controls.Add(header);
        RenderPage();
    }

    private void PlayWelcomeSound()
    {
        if (welcomeSoundPlayed) return;
        welcomeSoundPlayed = true;
        try { NativeMethods.PlaySoundFile(Path.Combine(AppContext.BaseDirectory, "erinnerung.wav")); }
        catch (Exception) { }
    }

    private Control BuildHeader()
    {
        var panel = new Panel
            { Dock = DockStyle.Top, Height = 165, BackColor = Felt, Padding = new Padding(20, 8, 20, 7) };
        var logo = new PictureBox { Dock = DockStyle.Top, Height = 58, SizeMode = PictureBoxSizeMode.Zoom };
        var logoPath = Path.Combine(AppContext.BaseDirectory, "symbole", "256x256", "magnolie-organizer.png");
        if (File.Exists(logoPath))
        {
            using var source = Image.FromFile(logoPath);
            logo.Image = new Bitmap(source);
        }
        else if (Icon is not null) logo.Image = Icon.ToBitmap();
        var title = new Label
        {
            Dock = DockStyle.Top, Height = 38, Text = "MAGNOLIE ORGANIZER", ForeColor = Paper,
            Font = new Font("Georgia", 16, FontStyle.Bold), TextAlign = ContentAlignment.MiddleCenter
        };
        var line = new Panel { Dock = DockStyle.Top, Height = 2, BackColor = Gold };
        progress.BackColor = Felt;
        progress.Height = 38;
        panel.Controls.Add(progress);
        panel.Controls.Add(line);
        panel.Controls.Add(title);
        panel.Controls.Add(logo);
        return panel;
    }

    private Control BuildNavigation()
    {
        var panel = new Panel
            { Dock = DockStyle.Bottom, Height = 74, BackColor = Color.FromArgb(237, 227, 201), Padding = new Padding(30, 16, 30, 16) };
        var left = new FlowLayoutPanel
            { Dock = DockStyle.Left, AutoSize = true, WrapContents = false, FlowDirection = FlowDirection.LeftToRight };
        var right = new FlowLayoutPanel
            { Dock = DockStyle.Right, AutoSize = true, WrapContents = false, FlowDirection = FlowDirection.LeftToRight };
        back.Text = T("Back");
        next.Text = T("Next");
        skip.Text = T("Skip assistant");
        welcomeManual.Text = T("Manual");
        StyleButton(back, primary: false);
        StyleButton(next, primary: true, width: 150);
        StyleButton(skip, primary: false, width: 220);
        StyleButton(welcomeManual, primary: false);
        back.Click += (_, _) => { if (page > 0) { page--; RenderPage(); } };
        next.Click += async (_, _) =>
        {
            if (page < 6)
            {
                if (page == 5 && phoneServices is not null && connectedPhones.Count > 0)
                {
                    SetSetupBusy(true);
                    try
                    {
                        var live = await phoneServices.ConnectedAsync(setupCancellation.Token);
                        foreach (var transport in connectedPhones.Keys.Where(t => !live.Contains(t)).ToArray()) connectedPhones.Remove(transport);
                    }
                    catch (Exception) { connectedPhones.Clear(); }
                    finally { if (!IsDisposed) SetSetupBusy(false); }
                    if (IsDisposed) return;
                }
                page++; RenderPage();
            }
            else await FinishAsync(skipped: false);
        };
        skip.Click += async (_, _) => await FinishAsync(skipped: true);
        welcomeManual.Click += (_, _) => OpenManualNow();
        left.Controls.Add(back);
        left.Controls.Add(skip);
        left.Controls.Add(welcomeManual);
        right.Controls.Add(next);
        panel.Controls.Add(left);
        panel.Controls.Add(right);
        return panel;
    }

    private void RenderPage()
    {
        pageHost.SuspendLayout();
        pageHost.AutoScrollPosition = Point.Empty;
        pageHost.Controls.Clear();
        progress.Page = page;
        progress.AccessibleName = T("Set up Magnolie Organizer");
        progress.AccessibleDescription = $"{page + 1} / 7";
        progress.Invalidate();
        back.Visible = page > 0;
        skip.Visible = page == 0;
        welcomeManual.Visible = page == 0;
        next.Text = page == 6 ? T("Start Magnolie") : T("Next");
        back.Text = T("Back");
        skip.Text = T("Skip assistant");
        welcomeManual.Text = T("Manual");
        Text = T("Set up Magnolie Organizer");
        var body = page switch
        {
            0 => WelcomePage(),
            1 => AddressPage(),
            2 => SourcesPage(),
            3 => PhonePage(),
            4 => RegistersPage(),
            5 => BackupPage(),
            _ => FinishPage()
        };
        body.Dock = DockStyle.Top;
        pageHost.Controls.Add(body);
        pageHost.ResumeLayout();
        pageHost.AutoScrollPosition = Point.Empty;
    }

    private Control WelcomePage()
    {
        var panel = Page(T("How lovely that you chose Magnolie"),
            T("We are delighted to welcome you. This short assistant prepares Magnolie Organizer around your wishes."));
        panel.Controls.Add(Note(T("The assistant covers your address for routes and weather, data sources, phone connections, organizer tabs, backups, and startup behavior.")));
        panel.Controls.Add(Label(T("Language"), bold: true));
        var languages = new LanguageChoice[]
        {
            new("system", "System"), new("de", "Deutsch"), new("en", "English"), new("fr", "Français"),
            new("es", "Español"), new("it", "Italiano"), new("nl", "Nederlands"), new("pt", "Português"),
            new("ru", "Русский"), new("cs", "Čeština"), new("pl", "Polski"), new("hsb", "Hornjoserbsce"),
            new("da", "Dansk"), new("nb", "Norsk"), new("hi", "हिन्दी"), new("zh_CN", "简体中文"),
            new("ja", "日本語"), new("ar", "العربية"), new("uk", "Українська"), new("be", "Беларуская"), new("tr", "Türkçe")
        };
        var languageBox = new ComboBox
            { Width = 330, DropDownStyle = ComboBoxStyle.DropDownList, DisplayMember = "Name", ValueMember = "Code" };
        languageBox.Items.AddRange(languages.Cast<object>().ToArray());
        languageBox.SelectedIndex = Math.Max(0, Array.FindIndex(languages, item => item.Code == language));
        languageBox.SelectedIndexChanged += (_, _) => ChangeLanguage(languageBox, languages);
        panel.Controls.Add(languageBox);
        var restore = new Button { Text = T("Restore a Magnolie backup after startup"), Width = 330, Height = 36 };
        StyleButton(restore, primary: false, width: 330);
        restore.Enabled = !restoreRequest;
        restore.Click += (_, _) => { restoreRequest = true; restore.Enabled = false; };
        panel.Controls.Add(restore);
        panel.Controls.Add(Note(T("The backup chooser will open after Magnolie has started.")));

        return panel;
    }

    private void ChangeLanguage(ComboBox languageBox, LanguageChoice[] languages)
    {
        if (languageBox.SelectedItem is not LanguageChoice selected || selected.Code == language) return;
        var previousLanguage = language;
        try
        {
            RegionalSettings.WriteLanguage(paths.RegionalSettings, selected.Code);
            language = selected.Code;
            NativeLocalization.SetLanguage(language);
            BeginInvoke(RenderPage);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            language = previousLanguage;
            NativeLocalization.SetLanguage(previousLanguage);
            languageBox.SelectedIndex = Array.FindIndex(languages, item => item.Code == previousLanguage);
            MessageBox.Show(this, T("The language setting could not be saved.") + Environment.NewLine + error.Message,
                T("Magnolie Organizer"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private Control AddressPage()
    {
        var matchedRegion = Regions.FirstOrDefault(item => item.Country == country &&
            (item.Code.Equals(region, StringComparison.OrdinalIgnoreCase) || item.Name.Equals(region, StringComparison.OrdinalIgnoreCase) ||
             T(item.Name).Equals(region, StringComparison.CurrentCultureIgnoreCase) ||
             item.Code == FirstRunSetupSelectionNormalizer.SchoolHolidayRegion(country, region)));
        if (matchedRegion is not null) region = matchedRegion.Code;
        var holidayCheck = new CheckBox { AutoSize = true, MaximumSize = new Size(640, 0), Name = "setup-school-holidays" };
        var holidayNote = Note(T("The information is retrieved once from the open directory openholidaysapi.org and then kept in the organizer. The application therefore needs an internet connection only once."));
        var holidayUnavailable = Note(T("School holidays are not available for this region."));
        void UpdateSchoolHolidays()
        {
            var selected = Regions.FirstOrDefault(item => item.Country == country && item.Code == region);
            var code = selected?.Code ?? "";
            if (schoolHolidayRegion != code) schoolHolidays = false;
            schoolHolidayRegion = code;
            holidayCheck.Text = T("Show school holidays for %(state)s in the calendar?").Replace("%(state)s", selected is null ? "" : T(selected.Name));
            holidayCheck.Checked = schoolHolidays;
            holidayCheck.Visible = holidayNote.Visible = code.Length > 0;
            holidayUnavailable.Visible = region.Length > 0 && code.Length == 0;
        }
        holidayCheck.CheckedChanged += (_, _) => schoolHolidays = holidayCheck.Checked;
        UpdateSchoolHolidays();
        var panel = Page(T("Your address"),
            T("Magnolie can use this information when preparing routes and finding local weather. You can leave every field empty."));
        AddField(panel, T("First name"), firstName, value => { firstName = value; addressSource = "own"; });
        AddField(panel, T("Last name"), lastName, value => { lastName = value; addressSource = "own"; });
        AddField(panel, T("Street and house number"), street, value => { street = value; addressSource = "own"; });
        var place = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 0, 0, 2) };
        place.Controls.Add(Field(T("Postal code"), postalCode, 150, value => { postalCode = value; addressSource = "own"; }));
        place.Controls.Add(Field(T("City"), city, 410, value => { city = value; addressSource = "own"; }));
        panel.Controls.Add(place);
        var area = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 0, 0, 8) };
        var countryChoices = Countries.ToList();
        if (country.Length > 0 && !countryChoices.Any(item => item.Code.Equals(country, StringComparison.OrdinalIgnoreCase)))
            countryChoices.Add(new CountryChoice(country, country));
        area.Controls.Add(ChoiceField(T("Country"), new[] { ("", T("None")) }.Concat(countryChoices.Select(item => (item.Code, T(item.Name)))),
            country, 280, value =>
            {
                country = value;
                if (!Regions.Any(item => item.Country == country && item.Code == region)) region = "";
                UpdateSchoolHolidays();
                addressSource = "own";
                BeginInvoke(RenderPage);
            }));
        var regionChoices = Regions.Where(item => item.Country == country).ToList();
        if (region.Length > 0 && !regionChoices.Any(item => item.Code == region))
            regionChoices.Add(new RegionChoice(country, region, region));
        area.Controls.Add(ChoiceField(T("State / region"),
            new[] { ("", T("None")) }.Concat(regionChoices.Select(item => (item.Code, T(item.Name)))),
            region, 280, value => { region = value; addressSource = "own"; UpdateSchoolHolidays(); }));
        panel.Controls.Add(area);
        panel.Controls.Add(holidayCheck);
        panel.Controls.Add(holidayNote);
        panel.Controls.Add(holidayUnavailable);
        firstMissingAddress = null;
        void AddressHints(Control parent)
        {
            foreach (Control input in parent.Controls)
            {
                if (input is TextBox || input is ComboBox)
                {
                    var normal = input.BackColor;
                    if (addressImported && input is ComboBox choice)
                    {
                        // The themed DropDownList ignores BackColor for its closed selection.
                        choice.DrawMode = DrawMode.OwnerDrawFixed;
                        choice.DrawItem += (_, e) =>
                        {
                            var selected = (e.State & DrawItemState.Selected) != 0;
                            using var background = new SolidBrush(selected ? SystemColors.Highlight : choice.BackColor);
                            e.Graphics.FillRectangle(background, e.Bounds);
                            var text = e.Index >= 0 ? choice.GetItemText(choice.Items[e.Index]) : choice.Text;
                            TextRenderer.DrawText(e.Graphics, text, choice.Font, e.Bounds,
                                selected ? SystemColors.HighlightText : choice.ForeColor,
                                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
                            e.DrawFocusRectangle();
                        };
                    }
                    void RefreshHint()
                    {
                        var missing = addressImported && (input is ComboBox combo
                            ? combo.SelectedIndex == 0 : string.IsNullOrWhiteSpace(input.Text));
                        input.BackColor = missing ? Color.FromArgb(228, 224, 199) : normal;
                        input.AccessibleDescription = missing ? T("Magnolie can use this information when preparing routes and finding local weather. You can leave every field empty.") : "";
                        if (missing) firstMissingAddress ??= input;
                    }
                    RefreshHint();
                    input.TextChanged += (_, _) => RefreshHint();
                }
                else AddressHints(input);
            }
        }
        AddressHints(panel);
        panel.Controls.Add(Label(T("Sort contacts"), bold: true));
        AddRadios(panel, new[]
        {
            ("last-name", T("By last name (Müller, Hans)")),
            ("first-name", T("By first name (Hans Müller)"))
        }, addressSort, value => addressSort = value, horizontal: true);
        var libreOffice = new Button { Text = T("Use LibreOffice address"), Height = 36, Width = 250 };
        StyleButton(libreOffice, primary: false, width: 250);
        libreOffice.Click += (_, _) => LoadLibreOfficeAddress();
        panel.Controls.Add(libreOffice);
        panel.Controls.Add(Note(T("LibreOffice is only read when you press the button. Its settings are not modified.")));
        return panel;
    }

    private void LoadLibreOfficeAddress()
    {
        var result = LibreOfficeUserData.Read();
        if (!result.Ok)
        {
            MessageBox.Show(this, result.Fehler, T("Magnolie Organizer"), MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        firstName = Value(result.Felder, "givenname");
        lastName = Value(result.Felder, "sn");
        street = Value(result.Felder, "street");
        postalCode = Value(result.Felder, "postalcode");
        city = Value(result.Felder, "l");
        var importedCountry = Value(result.Felder, "c");
        if (importedCountry.Length > 0)
            country = Countries.FirstOrDefault(item => item.Code.Equals(importedCountry, StringComparison.OrdinalIgnoreCase) ||
                item.Name.Equals(importedCountry, StringComparison.OrdinalIgnoreCase) ||
                T(item.Name).Equals(importedCountry, StringComparison.CurrentCultureIgnoreCase))?.Code ?? importedCountry;
        region = Value(result.Felder, "st");
        addressSource = "libreoffice";
        addressImported = true;
        RenderPage();
        firstMissingAddress?.Select();
    }

    private Control SourcesPage()
    {
        var panel = Page(T("Sources and imports"),
            T("Choose sources now. Import previews are kept until you finish the assistant."));
        panel.Controls.Add(Label(T("Synchronization"), bold: true));
        var connections = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
        foreach (var (kind, caption) in new[] { ("nextcloud", "Nextcloud"), ("generic-dav", "CalDAV + CardDAV Server") })
        {
            var button = new Button { Text = T(caption), AutoSize = true, Enabled = setupServices is not null };
            button.Click += (_, _) => ConfigureConnection(kind);
            connections.Controls.Add(button);
        }
        panel.Controls.Add(connections);
        if (connectionToken.Length > 0) panel.Controls.Add(Label(T("Connection ready")));
        panel.Controls.Add(Label(T("Import once"), bold: true));
        foreach (var (source, caption) in new[] { ("thunderbird", "Thunderbird"), ("ics", "Calendar (ICS)"),
                     ("vcard", "vCard / iPhone / iCloud"), ("ldif", "LDIF"), ("claws", "Claws Mail XML / LDIF"), ("csv-lotus", "CSV / Lotus Organizer"),
                     ("windows-contacts", "Windows Contacts folder") })
        {
            var option = new CheckBox { Text = T(caption), AutoSize = true, Checked = stagedImports.ContainsKey(source),
                Tag = source, Enabled = setupServices is not null, Margin = new Padding(3, 4, 0, 4) };
            option.CheckedChanged += async (_, _) =>
            {
                if (!option.Checked) { stagedImports.Remove(source); return; }
                await PrepareImportAsync(option, source);
            };
            panel.Controls.Add(option);
        }
        return panel;
    }

    private void SetSetupBusy(bool busy)
    {
        setupBusy = busy;
        pageHost.Enabled = next.Enabled = back.Enabled = skip.Enabled = !busy;
        UseWaitCursor = busy;
    }

    private async Task PrepareImportAsync(CheckBox option, string source)
    {
        if (setupServices is null || setupBusy) return;
        SetSetupBusy(true);
        try
        {
            JsonObject? payload = null;
            if (source is "thunderbird" or "windows-contacts")
                payload = await setupServices.PrepareImportAsync(source, null, setupCancellation.Token);
            if (IsDisposed) return;
            if (payload is null)
            {
                var extensions = source switch
                {
                    "ics" => "*.ics;*.vcs;*.lcs;*.zip", "vcard" => "*.vcf;*.csv;*.zip",
                    "csv-lotus" => "*.csv;*.zip", "ldif" => "*.ldif;*.ldi;*.zip",
                    "claws" => "*.xml;*.ldif;*.ldi;*.zip",
                    _ => "*.ics;*.vcs;*.lcs;*.vcf;*.ldif;*.ldi;*.xml;*.csv"
                };
                using var picker = new OpenFileDialog { Title = T("Import"), CheckFileExists = true,
                    Filter = T("Supported files") + "|" + extensions, Multiselect = false, RestoreDirectory = true,
                    AddToRecent = false };
                if ((importDialog?.Invoke(picker, this) ?? picker.ShowDialog(this)) != DialogResult.OK)
                { option.Checked = false; return; }
                payload = await setupServices.PrepareImportAsync(source, picker.FileName, setupCancellation.Token);
            }
            if (IsDisposed) return;
            var keys = new[] { "kontakte", "termine", "aufgaben", "jahrestage", "geburtstage", "notizen" };
            var entries = keys.SelectMany(key => payload?[key] as JsonArray ?? []).OfType<JsonObject>().ToArray();
            if (entries.Length == 0) throw new InvalidDataException(T("No supported data was found."));
            var preview = T("Entries ready to import") + ": " + entries.Length + Environment.NewLine +
                string.Join(Environment.NewLine, entries.Take(10).Select(item =>
                {
                    var text = (item["name"] ?? item["titel"] ?? item["nachname"] ?? item["vorname"])?.ToString() ?? "";
                    return text[..Math.Min(160, text.Length)];
                }));
            if (payload?["sourceVersion"]?.GetValue<string>() is { Length: > 0 } version)
                preview += Environment.NewLine + T("Thunderbird profile version") + ": " + version;
            if (MessageBox.Show(this, preview, T("Import preview"), MessageBoxButtons.OKCancel,
                    MessageBoxIcon.Information) != DialogResult.OK) { option.Checked = false; return; }
            stagedImports[source] = payload!;
        }
        catch (OperationCanceledException) { if (!IsDisposed) option.Checked = false; }
        catch (Exception error)
        {
            if (!IsDisposed)
            {
                option.Checked = false;
                MessageBox.Show(this, T("Import failed.") + Environment.NewLine + error.Message,
                    T("Import"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
        finally { if (!IsDisposed) SetSetupBusy(false); }
    }

    private void ConfigureConnection(string kind)
    {
        if (setupServices is null || setupBusy) return;
        using var dialog = new Form { Text = T(kind == "nextcloud" ? "Nextcloud" : "CalDAV + CardDAV Server"),
            ClientSize = new Size(650, 540), StartPosition = FormStartPosition.CenterParent, BackColor = Paper, Font = Font };
        var body = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown,
            WrapContents = false, AutoScroll = true, Padding = new Padding(20) };
        var server = new TextBox { Width = 570, AccessibleName = T("Server") };
        var user = new TextBox { Width = 570, AccessibleName = T("Username") };
        var password = new TextBox { Width = 570, UseSystemPasswordChar = true, AccessibleName = T("Application password") };
        foreach (var (caption, input) in new[] { ("Server", server), ("Username", user), ("Application password", password) })
        { body.Controls.Add(Label(T(caption))); body.Controls.Add(input); }
        var discover = new Button { Text = T("Discover"), AutoSize = true };
        var calendars = new CheckedListBox { Width = 570, Height = 110, CheckOnClick = true, DisplayMember = "Name" };
        var books = new ComboBox { Width = 570, DropDownStyle = ComboBoxStyle.DropDownList, DisplayMember = "Name" };
        var apply = new Button { Text = T("Apply"), AutoSize = true, Enabled = false };
        SetupConnection? candidate = null;
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(setupCancellation.Token);
        dialog.FormClosed += (_, _) => cancellation.Cancel();
        void InvalidateCandidate(object? _, EventArgs e) { candidate = null; apply.Enabled = false; }
        server.TextChanged += InvalidateCandidate; user.TextChanged += InvalidateCandidate; password.TextChanged += InvalidateCandidate;
        discover.Click += async (_, _) =>
        {
            discover.Enabled = server.Enabled = user.Enabled = password.Enabled = apply.Enabled = false;
            try
            {
                candidate = await setupServices.DiscoverAsync(new SetupConnectionRequest(kind, server.Text.Trim(), user.Text.Trim(), password.Text), cancellation.Token);
                if (dialog.IsDisposed) return;
                calendars.Items.Clear(); books.Items.Clear();
                foreach (var source in candidate.Calendars) calendars.Items.Add(source);
                books.Items.Add(new SetupSource("", T("None")));
                foreach (var source in candidate.AddressBooks) books.Items.Add(source);
                books.SelectedIndex = 0;
                apply.Enabled = true;
            }
            catch (OperationCanceledException) { }
            catch (Exception)
            {
                candidate = null;
                if (!dialog.IsDisposed) MessageBox.Show(dialog, T("Connection discovery failed. Check the server and credentials."),
                    T("Synchronization"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally { if (!dialog.IsDisposed) discover.Enabled = server.Enabled = user.Enabled = password.Enabled = true; }
        };
        apply.Click += (_, _) =>
        {
            if (candidate is null) return;
            connectionToken = candidate.Token;
            calendarUids.Clear(); calendarUids.AddRange(calendars.CheckedItems.Cast<SetupSource>().Select(s => s.Uid));
            addressBookUid = (books.SelectedItem as SetupSource)?.Uid ?? "";
            dialog.DialogResult = DialogResult.OK;
        };
        body.Controls.Add(discover); body.Controls.Add(Label(T("Calendars"))); body.Controls.Add(calendars);
        body.Controls.Add(Label(T("Address book"))); body.Controls.Add(books); body.Controls.Add(apply);
        dialog.Controls.Add(body);
        if (dialog.ShowDialog(this) == DialogResult.OK) RenderPage();
        password.Clear();
    }

    private Control PhonePage()
    {
        var panel = Page(T("Apps for your phone"),
            T("Downloads"));
        var downloads = new FlowLayoutPanel { AutoSize = true, WrapContents = false,
            FlowDirection = FlowDirection.LeftToRight, Margin = new Padding(0, 4, 0, 8) };
        downloads.Controls.Add(PhoneDownload("Magnolie Notes", MagnolieNotesUrl, "phone-notes-qr.png"));
        downloads.Controls.Add(PhoneDownload("KDE Connect", KdeConnectUrl, "phone-kde-connect-qr.png"));
        panel.Controls.Add(downloads);
        var connections = new FlowLayoutPanel { AutoSize = true, WrapContents = true, Width = 650 };
        var status = Label(T("Choose a connection. Confirm pairing on the phone and this computer."));
        foreach (var (transport, caption) in new[] { ("wifi", "Connect phone via WLAN"),
                     ("kdeconnect", "Connect via KDE Connect"), ("bluetooth", "Connect via Bluetooth") })
        {
            var capability = phoneServices?.Capabilities.FirstOrDefault(c => c.Transport == transport);
            var connect = new Button { Text = T(caption), AutoSize = true, Enabled = capability?.Available == true };
            connect.Click += async (_, _) =>
            {
                if (phoneServices is null || setupBusy) return;
                SetSetupBusy(true);
                status.Text = T("Waiting for authenticated phone connection...");
                try
                {
                    var result = await phoneServices.ConnectAsync(transport, ShowPhonePromptAsync, setupCancellation.Token);
                    if (IsDisposed) return;
                    if (!result.Authenticated) throw new InvalidOperationException(T("The phone connection was not authenticated."));
                    connectedPhones[transport] = result;
                    status.Text = T("Connected") + ": " + result.Name;
                }
                catch (OperationCanceledException) { if (!IsDisposed) status.Text = T("Phone connection cancelled or timed out."); }
                catch (Exception error)
                {
                    if (!IsDisposed) { connectedPhones.Remove(transport); status.Text = T("Phone connection failed.");
                        MessageBox.Show(this, status.Text + Environment.NewLine + error.Message, T("Phone connection"), MessageBoxButtons.OK, MessageBoxIcon.Warning); }
                }
                finally { if (!IsDisposed) SetSetupBusy(false); }
            };
            connections.Controls.Add(connect);
        }
        panel.Controls.Add(connections);
        panel.Controls.Add(status);
        panel.Controls.Add(Note(T("Completed pairings are kept if you cancel setup. No additional phone permissions are granted.")));
        return panel;
    }

    private Task<string?> ShowPhonePromptAsync(SetupPhonePrompt prompt)
    {
        var completion = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Show()
        {
            if (IsDisposed || setupCancellation.IsCancellationRequested) { completion.TrySetResult(null); return; }
            using var dialog = new Form { Text = T("Phone connection"), ClientSize = new Size(580, 340),
                StartPosition = FormStartPosition.CenterParent, BackColor = Paper, Font = Font };
            var body = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoScroll = true, WrapContents = false,
                FlowDirection = FlowDirection.TopDown, Padding = new Padding(20) };
            body.Controls.Add(Label(T(prompt.Kind == "select" ? "Select your phone" : "Confirm that the code matches on both devices.")));
            var devices = new ComboBox { Width = 510, DropDownStyle = ComboBoxStyle.DropDownList, DisplayMember = "Name" };
            devices.Items.AddRange(prompt.Devices.Cast<object>().ToArray());
            devices.SelectedIndex = prompt.Kind == "select" ? -1 : 0;
            body.Controls.Add(devices);
            if (prompt.Code.Length > 0) body.Controls.Add(Label(prompt.Code, bold: true));
            if (prompt.CanMarkOwn) body.Controls.Add(Label(T("Personal synchronization") + "\n" +
                T("Synchronize notes and notebooks") + "\n" + T("Synchronize tasks") + "\n" + T("Automatically synchronize over Wi-Fi")));
            var accept = new Button { Text = T("Confirm"), AutoSize = true, DialogResult = DialogResult.OK };
            var cancel = new Button { Text = T("Cancel"), AutoSize = true, DialogResult = DialogResult.Cancel };
            body.Controls.Add(accept); body.Controls.Add(cancel); dialog.Controls.Add(body);
            dialog.CancelButton = cancel;
            var result = dialog.ShowDialog(this);
            completion.TrySetResult(result != DialogResult.OK || devices.SelectedItem is not SetupSource selected ? null :
                prompt.Kind == "select" ? selected.Uid : "accept");
        }
        if (InvokeRequired) BeginInvoke((Action)Show); else Show();
        return completion.Task;
    }

    private static Control PhoneDownload(string text, string target, string qrFile)
    {
        var card = new FlowLayoutPanel { AutoSize = true, Width = 290, FlowDirection = FlowDirection.TopDown,
            WrapContents = false, Margin = new Padding(0, 0, 20, 0), Padding = new Padding(10) };
        card.Controls.Add(Label(text, bold: true));
        var picture = new PictureBox { Width = 170, Height = 170, SizeMode = PictureBoxSizeMode.Zoom,
            AccessibleName = text + " " + T("QR code"), Margin = new Padding(0, 4, 0, 7) };
        var path = Path.Combine(AppContext.BaseDirectory, "symbole", qrFile);
        if (File.Exists(path))
        {
            using var source = Image.FromFile(path);
            picture.Image = new Bitmap(source);
        }
        card.Controls.Add(picture);
        card.Controls.Add(LinkButton(text, target));
        return card;
    }

    private static LinkLabel LinkButton(string text, string target)
    {
        var link = new LinkLabel { AutoSize = true, Text = text, Tag = target, Margin = new Padding(0, 5, 0, 5) };
        link.LinkClicked += (_, _) => ShellLauncher.OpenWebUri((string)link.Tag);
        return link;
    }

    private Control RegistersPage()
    {
        var panel = Page(T("Choose your organizer tabs"),
            T("These are Magnolie's actual tabs. You can show only the sections that fit your everyday life."));
        panel.Controls.Add(CheckGroup(T("Tabs"), new[]
        {
            ("tasks", T("Tasks")), ("addresses", T("Addresses")),
            ("notes", T("Notes")), ("anniversaries", T("Anniversaries")), ("planner", T("Planner")),
            ("health", T("Health"))
        }, registers));
        var custom = new CheckBox
            { AutoSize = true, Text = T("Add one custom tab"), Checked = customRegisterEnabled, Margin = new Padding(3, 10, 0, 4) };
        var name = new TextBox
            { Width = 390, MaxLength = 120, Text = customRegisterName, Enabled = customRegisterEnabled,
                AccessibleName = T("Tab name"), Margin = new Padding(3, 0, 3, 10) };
        custom.CheckedChanged += (_, _) => { customRegisterEnabled = custom.Checked; name.Enabled = custom.Checked; customTabChanged = true; };
        name.TextChanged += (_, _) => { customRegisterName = name.Text; customTabChanged = true; };
        panel.Controls.Add(custom);
        panel.Controls.Add(name);
        var design = new Button
            { Text = T("Customize"), Height = 36, Width = 280 };
        StyleButton(design, primary: false, width: 280);
        design.Click += (_, _) => DesignCustomTab(name, custom);
        panel.Controls.Add(design);
        return panel;
    }

    private void DesignCustomTab(TextBox tabName, CheckBox customEnabled)
    {
        using var designer = new Form
        {
            Text = T("Choose your organizer tabs"), StartPosition = FormStartPosition.CenterParent,
            ClientSize = new Size(760, 470),
            BackColor = Paper, Font = Font, ShowInTaskbar = false
        };
        var workArea = Screen.FromControl(this).WorkingArea;
        designer.Size = new Size(Math.Min(designer.Width, workArea.Width), Math.Min(designer.Height, workArea.Height));
        var content = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, Padding = new Padding(22), ColumnCount = 1, RowCount = 4,
            BackColor = Paper
        };
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        content.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var name = new TextBox { Dock = DockStyle.Top, MaxLength = 120, Text = tabName.Text,
            AccessibleName = T("Tab name") };
        var choices = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        var rows = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, AutoScroll = true, ColumnCount = 2, RowCount = 3,
            Padding = new Padding(0, 8, 0, 8)
        };
        rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        for (var i = 0; i < 3; i++) rows.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var draft = customModules.Select(module => module with { }).ToList();
        Action redraw = null!;
        redraw = () =>
        {
            rows.SuspendLayout();
            while (rows.Controls.Count > 0) rows.Controls[0].Dispose();
            rows.Controls.Add(new Label { AutoSize = true, Text = T("Left page") }, 0, 0);
            rows.Controls.Add(new Label { AutoSize = true, Text = T("Right page") }, 1, 0);
            var pageRows = new[] { 1, 1 };
            foreach (var module in draft.OrderBy(item => item.Order).ToArray())
            {
                var row = new TableLayoutPanel { AutoSize = true, Dock = DockStyle.Top, ColumnCount = 1,
                    Padding = new Padding(4), Margin = new Padding(3, 3, 3, 10) };
                row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
                row.Controls.Add(new Label { AutoSize = true, Dock = DockStyle.Top,
                    TextAlign = ContentAlignment.MiddleLeft, Text = T(ModuleLabel(module.Type)) });
                var pageChoice = new ComboBox { Dock = DockStyle.Top, DropDownStyle = ComboBoxStyle.DropDownList,
                    AccessibleName = T(ModuleLabel(module.Type)) + ": " + T("Page"), Tag = module.Id };
                pageChoice.Items.AddRange([T("Left page"), T("Right page")]);
                pageChoice.SelectedIndex = module.Page == "right" ? 1 : 0;
                pageChoice.SelectedIndexChanged += (_, _) =>
                {
                    var target = pageChoice.SelectedIndex == 1 ? "right" : "left";
                    if (target == module.Page) return;
                    var others = draft.Where(item => !ReferenceEquals(item, module)).ToList();
                    if (others.Count(item => item.Page == target) >= 2 ||
                        module.Type == "notes" && others.Any(item => item.Type == "notes" && item.Page == target))
                    {
                        pageChoice.SelectedIndex = module.Page == "right" ? 1 : 0;
                        return;
                    }
                    var index = draft.IndexOf(module);
                    draft[index] = module with { Page = target, Order = 1 + others.Where(item => item.Page == target).Select(item => item.Order).DefaultIfEmpty(-1).Max() };
                    redraw();
                    foreach (Control card in rows.Controls)
                        foreach (Control control in card.Controls)
                            if (control is ComboBox && Equals(control.Tag, module.Id)) control.Focus();
                };
                row.Controls.Add(pageChoice);
                var remove = new Button { Width = 95, Height = 30, Text = T("Remove") };
                remove.Click += (_, _) => { draft.Remove(module); redraw(); };
                row.Controls.Add(remove);
                var column = module.Page == "right" ? 1 : 0;
                rows.Controls.Add(row, column, pageRows[column]++);
            }
            rows.ResumeLayout();
        };
        foreach (var (type, label) in new[] { ("notes", "Text block"), ("tasks", "Tasks"), ("appointments", "Appointments") })
        {
            var add = new Button { Width = 130, Height = 32, Text = T(label) };
            add.Click += (_, _) =>
            {
                if (draft.Count >= 4 || type != "notes" && draft.Any(module => module.Type == type)) return;
                var page = (type == "notes" ? new[] { "left", "right" } : new[] { "right", "left" }).FirstOrDefault(candidate =>
                    draft.Count(module => module.Page == candidate) < 2 &&
                    (type != "notes" || !draft.Any(module => module.Type == "notes" && module.Page == candidate)));
                if (page is null) return;
                draft.Add(new FirstRunSetupCustomModule { Id = $"setup-{Guid.NewGuid():N}", Type = type,
                    Page = page, Order = 1 + draft.Where(module => module.Page == page).Select(module => module.Order).DefaultIfEmpty(-1).Max() });
                redraw();
            };
            choices.Controls.Add(add);
        }
        var actions = new FlowLayoutPanel
            { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.RightToLeft, WrapContents = false };
        var apply = new Button { Width = 110, Height = 34, Text = T("Apply"), DialogResult = DialogResult.OK };
        var cancel = new Button { Width = 110, Height = 34, Text = T("Cancel"), DialogResult = DialogResult.Cancel };
        actions.Controls.Add(apply);
        actions.Controls.Add(cancel);
        content.Controls.Add(name);
        content.Controls.Add(choices);
        content.Controls.Add(rows);
        content.Controls.Add(actions);
        designer.Controls.Add(content);
        designer.AcceptButton = apply;
        designer.CancelButton = cancel;
        redraw();
        if (designer.ShowDialog(this) != DialogResult.OK) return;
        customRegisterName = name.Text.Trim();
        tabName.Text = customRegisterName;
        customRegisterEnabled = true;
        customEnabled.Checked = true;
        customModules.Clear();
        customModules.AddRange(draft.Select((module, index) => module with { Id = $"setup-{index}" }));
        customOrganizerChanged = true;
    }

    private static string ModuleLabel(string type) => type switch
    {
        "tasks" => "Tasks",
        "appointments" => "Appointments",
        _ => "Text block"
    };

    private Control BackupPage()
    {
        var panel = Page(T("Backups and recovery"),
            T("Choose safe preferences now. No scheduled backup job is started in the assistant."));
        panel.Controls.Add(Label(T("Preferred backup folder"), bold: true));
        var folderRow = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 2, 0, 12) };
        var folder = new TextBox { Width = 470, Text = backupPath, MaxLength = 4096 };
        folder.TextChanged += (_, _) => backupPath = folder.Text.Trim();
        var browse = new Button { Text = T("Browse..."), AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink, MinimumSize = new Size(100, 30) };
        browse.Click += (_, _) =>
        {
            using var dialog = new FolderBrowserDialog
                { InitialDirectory = Directory.Exists(backupPath) ? backupPath : paths.Backups };
            if (dialog.ShowDialog(this) == DialogResult.OK) folder.Text = dialog.SelectedPath;
        };
        folderRow.Controls.Add(folder);
        folderRow.Controls.Add(browse);
        panel.Controls.Add(folderRow);
        panel.Controls.Add(Label(T("Backup rhythm"), bold: true));
        AddRadios(panel, new[] { ("manual", T("Manual only")), ("daily", T("Daily")),
                ("weekly", T("Weekly")) },
            backupInterval, value => backupInterval = value, horizontal: true);
        return panel;
    }

    private Control FinishPage()
    {
        var panel = Page(T("Everything is ready"),
            T("Enjoy organizing with Magnolie. Your choices stay under your control and can be changed later in Settings."));
        var autostart = new CheckBox
            { AutoSize = true, Text = T("Start Magnolie with Windows in the notification area (tray)"), Checked = startWithWindows, Margin = new Padding(0, 8, 0, 6) };
        autostart.CheckedChanged += (_, _) => startWithWindows = autostart.Checked;
        var weather = new CheckBox
            { AutoSize = true, Text = T("Show weather for the next three days"), Checked = weatherEnabled, Margin = new Padding(0, 6, 0, 6) };
        weather.CheckedChanged += (_, _) => weatherEnabled = weather.Checked;
        panel.Controls.Add(autostart);
        panel.Controls.Add(weather);
        var previousPhoneStartup = phoneStartupChecks.Where(item => item.Value.Checked).Select(item => item.Key).ToHashSet(StringComparer.Ordinal);
        phoneStartupChecks.Clear();
        foreach (var (transport, result) in connectedPhones)
        {
            if (!result.Authenticated || phoneServices?.Capabilities.Any(c => c.Transport == transport && c.CanAutoStart) != true) continue;
            var start = new CheckBox { AutoSize = true, Text = T("Start required phone background services automatically") + ": " + result.Name,
                Tag = transport, Checked = previousPhoneStartup.Contains(transport), MaximumSize = new Size(640, 0), Margin = new Padding(3, 6, 3, 6) };
            phoneStartupChecks[transport] = start;
            panel.Controls.Add(start);
        }
        panel.Controls.Add(Note(T("Weather requests are sent to wttr.in. Your own address in Contacts is used first, followed by local LibreOffice user data. If neither contains a location and retrieval without one is allowed, wttr.in estimates the location from your internet connection's public IP address.")));
        return panel;
    }

    private async Task FinishAsync(bool skipped)
    {
        if (setupBusy) return;
        var phoneStartup = phoneStartupChecks.Where(item => item.Value.Checked && connectedPhones.ContainsKey(item.Key))
            .Select(item => item.Key).ToList();
        var selections = new FirstRunSetupSelections
        {
            Language = language,
            AddressSource = addressSource,
            AddressChanged = addressSource != "later",
            SchoolHolidays = schoolHolidays,
            SchoolHolidayRegion = schoolHolidays ? schoolHolidayRegion : "",
            AddressSort = addressSort,
            Address = new FirstRunSetupAddress { FirstName = firstName, LastName = lastName,
                Street = street, PostalCode = postalCode, City = city, Country = country, State = region },
            OneTimeImports = [],
            StagedImports = stagedImports.Select(item => new FirstRunSetupImport(item.Key, item.Value.DeepClone().AsObject())).ToList(),
            CalendarUids = calendarUids.ToList(),
            AddressBookUid = addressBookUid,
            PhoneActions = [],
            PhoneBackgroundServices = phoneStartup,
            Registers = registers.ToList(),
            CustomTabEnabled = customRegisterEnabled,
            CustomTabName = customRegisterName,
            CustomTabChanged = customTabChanged,
            CustomOrganizerChanged = customOrganizerChanged,
            CustomOrganizer = new FirstRunSetupCustomOrganizer { Modules = customModules.ToList() },
            OpenHandbook = false,
            BackupPath = backupPath,
            BackupInterval = backupInterval,
            Autostart = startWithWindows || phoneStartup.Count > 0,
            Tray = startWithWindows || phoneStartup.Count > 0,
            Weather = weatherEnabled,
            RestoreRequest = restoreRequest
        };
        selections = FirstRunSetupSelectionNormalizer.Normalize(selections, paths.Backups, skipped);
        try
        {
            if (!skipped && connectionToken.Length > 0 && setupServices is not null)
            {
                SetSetupBusy(true);
                await setupServices.CommitConnectionAsync(connectionToken, setupCancellation.Token);
                if (IsDisposed) return;
            }
            RegionalSettings.WriteLanguage(paths.RegionalSettings, language);
            SetSetupBusy(true);
            selections = await FirstRunPhoneFinish.CompleteAsync(setupState, selections, skipped, phoneServices, setupCancellation.Token);
            Selections = selections;
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            MessageBox.Show(this, T("The setup state could not be saved.") + Environment.NewLine + error.Message,
                T("Magnolie Organizer"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { if (!IsDisposed) SetSetupBusy(false); }
    }

    private void OpenManualNow()
    {
        try
        {
            Process.Start(new ProcessStartInfo(Application.ExecutablePath, "--handbook") { UseShellExecute = true });
        }
        catch (Exception error)
        {
            MessageBox.Show(this, T("The manual could not be opened.") + Environment.NewLine + error.Message,
                T("Magnolie Organizer"), MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    private static FlowLayoutPanel Page(string title, string introduction)
    {
        var panel = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink, Width = 700
        };
        panel.Controls.Add(new Label
        {
            AutoSize = true, MaximumSize = new Size(680, 0), Text = title, ForeColor = Ink,
            Font = new Font("Georgia", 22, FontStyle.Bold), Margin = new Padding(0, 0, 0, 10)
        });
        panel.Controls.Add(new Label
        {
            AutoSize = true, MaximumSize = new Size(680, 0), Text = introduction, ForeColor = Ink,
            Font = new Font("Georgia", 11), Margin = new Padding(0, 0, 0, 20)
        });
        return panel;
    }

    private static void AddField(FlowLayoutPanel panel, string title, string text, Action<string> changed) =>
        panel.Controls.Add(Field(title, text, 580, changed));

    private static Control Field(string title, string text, int width, Action<string> changed)
    {
        var field = new FlowLayoutPanel
            { FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoSize = true, Width = width, Margin = new Padding(0, 0, 10, 3) };
        field.Controls.Add(Label(title, bold: true));
        var input = new TextBox { Width = width - 10, Text = text, MaxLength = 120 };
        input.TextChanged += (_, _) => changed(input.Text);
        field.Controls.Add(input);
        return field;
    }

    private static Control ChoiceField(string title, IEnumerable<(string Value, string Text)> choices,
        string selected, int width, Action<string> changed)
    {
        var values = choices.ToArray();
        var field = new FlowLayoutPanel
            { FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoSize = true, Width = width, Margin = new Padding(0, 0, 10, 3) };
        field.Controls.Add(Label(title, bold: true));
        var input = new ComboBox { Width = width - 10, DropDownStyle = ComboBoxStyle.DropDownList };
        input.Items.AddRange(values.Select(item => item.Text).Cast<object>().ToArray());
        input.SelectedIndex = Math.Max(0, Array.FindIndex(values, item => item.Value.Equals(selected, StringComparison.OrdinalIgnoreCase)));
        input.SelectedIndexChanged += (_, _) => { if (input.SelectedIndex >= 0) changed(values[input.SelectedIndex].Value); };
        field.Controls.Add(input);
        return field;
    }

    private static Label Label(string text, bool bold = false) => new()
    {
        AutoSize = true, MaximumSize = new Size(680, 0), Text = text, ForeColor = Ink,
        Font = new Font("Segoe UI", 10, bold ? FontStyle.Bold : FontStyle.Regular), Margin = new Padding(0, 7, 0, 5)
    };

    private static Label Note(string text) => new()
    {
        AutoSize = true, MaximumSize = new Size(660, 0), Text = text, ForeColor = Color.FromArgb(73, 88, 78),
        BackColor = Color.FromArgb(228, 224, 199), Padding = new Padding(12), Margin = new Padding(0, 16, 0, 8)
    };

    private static Control CheckGroup(string title, IEnumerable<(string Value, string Text)> choices,
        HashSet<string> selected)
    {
        var group = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoSize = true,
            Width = 650, Margin = new Padding(0, 3, 0, 12)
        };
        if (title.Length > 0) group.Controls.Add(Label(title, bold: true));
        foreach (var choice in choices)
        {
            var check = new CheckBox
            {
                AutoSize = true, Text = choice.Text, Checked = selected.Contains(choice.Value),
                Tag = choice.Value, Margin = new Padding(0, 4, 0, 4)
            };
            check.CheckedChanged += (_, _) =>
            {
                if (check.Checked) selected.Add((string)check.Tag);
                else selected.Remove((string)check.Tag);
            };
            group.Controls.Add(check);
        }
        return group;
    }

    private static void AddRadios(FlowLayoutPanel panel, IEnumerable<(string Value, string Text)> choices,
        string selected, Action<string> changed, bool horizontal = false)
    {
        var group = new FlowLayoutPanel
        {
            FlowDirection = horizontal ? FlowDirection.LeftToRight : FlowDirection.TopDown,
            WrapContents = false, AutoSize = true, Width = 650, Margin = new Padding(0, 2, 0, 12)
        };
        foreach (var choice in choices)
        {
            var radio = new RadioButton
            {
                AutoSize = true, Text = choice.Text, Checked = choice.Value == selected,
                Tag = choice.Value, Margin = new Padding(0, 5, 20, 5)
            };
            radio.CheckedChanged += (_, _) => { if (radio.Checked) changed((string)radio.Tag); };
            group.Controls.Add(radio);
        }
        panel.Controls.Add(group);
    }

    private static void StyleButton(Button button, bool primary, int width = 126)
    {
        button.Width = width;
        button.Height = 38;
        button.MinimumSize = new Size(width, 38);
        button.AutoSize = true;
        button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        button.FlatStyle = FlatStyle.Flat;
        button.BackColor = primary ? FeltLight : Color.FromArgb(224, 213, 185);
        button.ForeColor = primary ? Color.White : Ink;
        button.FlatAppearance.BorderColor = primary ? Gold : Color.FromArgb(166, 144, 102);
        button.Margin = new Padding(0, 0, 10, 0);
    }

    private static string Value(IReadOnlyDictionary<string, string> values, string name) =>
        values.TryGetValue(name, out var value) ? value : "";

    private static string T(string message) => NativeLocalization.Gettext(message);

    private sealed record LanguageChoice(string Code, string Name);
    private sealed record CountryChoice(string Code, string Name);
    private sealed record RegionChoice(string Country, string Code, string Name);

    private sealed class SetupProgress : Control
    {
        internal int Page { get; set; }

        protected override void OnPaint(PaintEventArgs eventArgs)
        {
            base.OnPaint(eventArgs);
            eventArgs.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            const int count = 7;
            const int gap = 29;
            var start = (Width - (count - 1) * gap) / 2;
            using var line = new Pen(Gold, 2);
            eventArgs.Graphics.DrawLine(line, start, 23, start + (count - 1) * gap, 23);
            for (var index = 0; index < count; index++)
            {
                var color = index <= Page ? Gold : Color.FromArgb(218, 207, 178);
                using var brush = new SolidBrush(color);
                eventArgs.Graphics.FillEllipse(brush, start + index * gap - 6, 17, 12, 12);
            }
        }
    }
}
