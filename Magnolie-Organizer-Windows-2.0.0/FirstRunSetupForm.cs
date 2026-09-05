using System.Diagnostics;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class FirstRunSetupForm : Form
{
    internal const string MagnolieNotesUrl = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes-1.0.13.apk";
    internal const string KdeConnectUrl = "https://play.google.com/store/apps/details?id=org.kde.kdeconnect_tp&hl=de&pli=1";
    private static readonly Color Felt = Color.FromArgb(46, 58, 52);
    private static readonly Color FeltLight = Color.FromArgb(63, 77, 69);
    private static readonly Color Paper = Color.FromArgb(246, 239, 220);
    private static readonly Color Ink = Color.FromArgb(61, 43, 31);
    private static readonly Color Gold = Color.FromArgb(190, 151, 72);
    private readonly WindowsPaths paths;
    private readonly FirstRunSetupState setupState;
    private readonly Panel pageHost = new()
    {
        Dock = DockStyle.Fill, BackColor = Paper, AutoScroll = true,
        Padding = new Padding(42, 30, 42, 22)
    };
    private readonly SetupProgress progress = new() { Dock = DockStyle.Top, Height = 46 };
    private readonly Button back = new();
    private readonly Button next = new();
    private readonly Button skip = new();
    private readonly Button welcomeManual = new();
    private readonly HashSet<string> imports = new(StringComparer.Ordinal);
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
    private string country = "DE";
    private string region = "";
    private string addressSort = "last-name";
    private bool customRegisterEnabled;
    private bool customTabChanged;
    private string customRegisterName = "";
    private readonly List<FirstRunSetupCustomModule> customModules = [];
    private bool customOrganizerChanged;
    private string backupPath;
    private string backupInterval = "manual";
    private bool startWithWindows;
    private bool weatherEnabled;
    private bool restoreRequest;
    private bool welcomeSoundPlayed;

    internal FirstRunSetupSelections? Selections { get; private set; }

    internal FirstRunSetupForm(WindowsPaths paths, FirstRunSetupState setupState)
    {
        this.paths = paths;
        this.setupState = setupState;
        backupPath = paths.Backups;
        language = RegionalSettings.Read(paths.RegionalSettings)["language"]?.GetValue<string>() ?? "system";

        Text = T("Set up Magnolie Organizer");
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(760, 600);
        ClientSize = new Size(900, 680);
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
            { Dock = DockStyle.Top, Height = 190, BackColor = Felt, Padding = new Padding(20, 12, 20, 10) };
        var logo = new PictureBox { Dock = DockStyle.Top, Height = 72, SizeMode = PictureBoxSizeMode.Zoom };
        var logoPath = Path.Combine(AppContext.BaseDirectory, "symbole", "256x256", "magnolie-organizer.png");
        if (File.Exists(logoPath))
        {
            using var source = Image.FromFile(logoPath);
            logo.Image = new Bitmap(source);
        }
        else if (Icon is not null) logo.Image = Icon.ToBitmap();
        var title = new Label
        {
            Dock = DockStyle.Top, Height = 42, Text = "MAGNOLIE ORGANIZER", ForeColor = Paper,
            Font = new Font("Georgia", 16, FontStyle.Bold), TextAlign = ContentAlignment.MiddleCenter
        };
        var line = new Panel { Dock = DockStyle.Top, Height = 2, BackColor = Gold };
        progress.BackColor = Felt;
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
        StyleButton(skip, primary: false, width: 150);
        StyleButton(welcomeManual, primary: false);
        back.Click += (_, _) => { if (page > 0) { page--; RenderPage(); } };
        next.Click += (_, _) =>
        {
            if (page < 6) { page++; RenderPage(); }
            else Finish(skipped: false);
        };
        skip.Click += (_, _) => Finish(skipped: true);
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
        pageHost.Controls.Clear();
        progress.Page = page;
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
        area.Controls.Add(Field(T("Country"), country, 280, value => { country = value; addressSource = "own"; }));
        area.Controls.Add(Field(T("State / region"), region, 280, value => { region = value; addressSource = "own"; }));
        panel.Controls.Add(area);
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
        country = Value(result.Felder, "c");
        region = Value(result.Felder, "st");
        addressSource = "libreoffice";
        RenderPage();
    }

    private Control SourcesPage()
    {
        var panel = Page(T("Sources and imports"),
            T("Choose file and Windows contact imports that Magnolie can start directly after opening."));
        panel.Controls.Add(CheckGroup(T("Import once"), new[]
        {
            ("claws", "Claws Mail XML / LDIF"), ("vcard", "vCard / iPhone / iCloud"),
            ("ldif", "LDIF"), ("csv-lotus", "CSV / Lotus Organizer"),
            ("windows-contacts", T("Windows Contacts folder"))
        }, imports));
        panel.Controls.Add(Note(T("Selected imports are started directly after Magnolie opens. Thunderbird contacts are not offered because Windows has no Thunderbird address-book importer.")));
        return panel;
    }

    private Control PhonePage()
    {
        var panel = Page(T("Apps for your phone"),
            T("Downloads"));
        panel.Controls.Add(Label(T("Downloads"), bold: true));
        panel.Controls.Add(LinkButton("Magnolie Notes", MagnolieNotesUrl));
        panel.Controls.Add(LinkButton("KDE Connect", KdeConnectUrl));
        return panel;
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
            { AutoSize = true, Text = T("Add one custom tab"), Checked = customRegisterEnabled, Margin = new Padding(0, 10, 0, 4) };
        var name = new TextBox
            { Width = 390, MaxLength = 120, Text = customRegisterName, Enabled = customRegisterEnabled, Margin = new Padding(0, 0, 0, 10) };
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
            ClientSize = new Size(650, 470), MinimumSize = new Size(570, 410),
            BackColor = Paper, Font = Font, ShowInTaskbar = false
        };
        var content = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, Padding = new Padding(22), ColumnCount = 1, RowCount = 4,
            BackColor = Paper
        };
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        content.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var name = new TextBox { Dock = DockStyle.Top, MaxLength = 120, Text = tabName.Text };
        var choices = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = false };
        var rows = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill, AutoScroll = true, FlowDirection = FlowDirection.TopDown,
            WrapContents = false, Padding = new Padding(0, 8, 0, 8)
        };
        var draft = customModules.Select(module => module.Type).ToList();
        Action redraw = null!;
        redraw = () =>
        {
            rows.SuspendLayout();
            rows.Controls.Clear();
            foreach (var module in draft.ToArray())
            {
                var row = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Width = 570 };
                row.Controls.Add(new Label { AutoSize = false, Width = 100, Height = 30,
                    TextAlign = ContentAlignment.MiddleLeft, Text = T(ModuleLabel(module)) });
                var remove = new Button { Width = 95, Height = 30, Text = T("Remove") };
                remove.Click += (_, _) => { draft.Remove(module); redraw(); };
                row.Controls.Add(remove);
                rows.Controls.Add(row);
            }
            rows.ResumeLayout();
        };
        foreach (var (type, label) in new[] { ("notes", "Notes"), ("tasks", "Tasks"), ("appointments", "Appointments") })
        {
            var add = new Button { Width = 130, Height = 32, Text = T(label) };
            add.Click += (_, _) =>
            {
                if (draft.Count >= 3 || draft.Contains(type)) return;
                draft.Add(type);
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
        customModules.AddRange(draft.Select((type, index) => new FirstRunSetupCustomModule
            { Id = $"setup-{index}", Type = type, Page = index % 2 == 0 ? "left" : "right", Order = index / 2 }));
        customOrganizerChanged = true;
    }

    private static string ModuleLabel(string type) => type switch
    {
        "tasks" => "Tasks",
        "appointments" => "Appointments",
        _ => "Notes"
    };

    private Control BackupPage()
    {
        var panel = Page(T("Backups and recovery"),
            T("Choose safe preferences now. No scheduled backup job is started in the assistant."));
        panel.Controls.Add(Label(T("Preferred backup folder"), bold: true));
        var folderRow = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 2, 0, 12) };
        var folder = new TextBox { Width = 470, Text = backupPath, MaxLength = 4096 };
        folder.TextChanged += (_, _) => backupPath = folder.Text.Trim();
        var browse = new Button { Text = T("Browse..."), Width = 100, Height = 30 };
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
                ("weekly", T("Weekly")), ("monthly", T("Monthly")) },
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
        panel.Controls.Add(Note(T("Weather requests are sent to wttr.in. Your own address in Contacts is used first, followed by local LibreOffice user data. If neither contains a location and retrieval without one is allowed, wttr.in estimates the location from your internet connection's public IP address.")));
        return panel;
    }

    private void Finish(bool skipped)
    {
        var selections = new FirstRunSetupSelections
        {
            Language = language,
            AddressSource = addressSource,
            AddressSort = addressSort,
            Address = new FirstRunSetupAddress { FirstName = firstName, LastName = lastName,
                Street = street, PostalCode = postalCode, City = city, Country = country, State = region },
            OneTimeImports = imports.ToList(),
            PhoneActions = [],
            Registers = registers.ToList(),
            CustomTabEnabled = customRegisterEnabled,
            CustomTabName = customRegisterName,
            CustomTabChanged = customTabChanged,
            CustomOrganizerChanged = customOrganizerChanged,
            CustomOrganizer = new FirstRunSetupCustomOrganizer { Modules = customModules.ToList() },
            OpenHandbook = false,
            BackupPath = backupPath,
            BackupInterval = backupInterval,
            Autostart = startWithWindows,
            Tray = startWithWindows,
            Weather = weatherEnabled,
            RestoreRequest = restoreRequest
        };
        selections = FirstRunSetupSelectionNormalizer.Normalize(selections, paths.Backups, skipped);
        try
        {
            RegionalSettings.WriteLanguage(paths.RegionalSettings, language);
            setupState.Complete(selections, skipped);
            Selections = selections;
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            MessageBox.Show(this, T("The setup state could not be saved.") + Environment.NewLine + error.Message,
                T("Magnolie Organizer"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
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
