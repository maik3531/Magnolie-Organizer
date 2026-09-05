#!/usr/bin/env python3
"""Native GTK3 first-run assistant for Magnolie Organizer."""

import gettext
import json
import os
import shutil
import subprocess
import tempfile


LANGUAGES = (
    ("system", "System"), ("de", "Deutsch"), ("en", "English"),
    ("fr", "Français"), ("es", "Español"), ("it", "Italiano"),
    ("nl", "Nederlands"), ("pt", "Português"), ("ru", "Русский"),
    ("cs", "Čeština"), ("pl", "Polski"), ("hsb", "Hornjoserbsce"),
    ("da", "Dansk"), ("nb", "Norsk"), ("hi", "हिन्दी"),
    ("zh_CN", "简体中文"), ("ja", "日本語"), ("ar", "العربية"),
    ("uk", "Українська"), ("be", "Беларуская"), ("tr", "Türkçe"),
)
LANGUAGE_CODES = frozenset(code for code, _name in LANGUAGES)
REGISTER_IDS = (
    ("tasks", "Tasks"), ("addresses", "Addresses"), ("notes", "Notes"),
    ("anniversaries", "Anniversaries"), ("planner", "Planner"),
    ("health", "Health"),
)
GERMAN_REGIONS = (
    ("DE-BW", "Baden-Württemberg"), ("DE-BY", "Bavaria"),
    ("DE-BE", "Berlin"), ("DE-BB", "Brandenburg"), ("DE-HB", "Bremen"),
    ("DE-HH", "Hamburg"), ("DE-HE", "Hesse"), ("DE-NI", "Lower Saxony"),
    ("DE-MV", "Mecklenburg-Western Pomerania"),
    ("DE-NW", "North Rhine-Westphalia"), ("DE-RP", "Rhineland-Palatinate"),
    ("DE-SL", "Saarland"), ("DE-SN", "Saxony"),
    ("DE-ST", "Saxony-Anhalt"), ("DE-SH", "Schleswig-Holstein"),
    ("DE-TH", "Thuringia"),
)
MAX_ITEM_LENGTH = 80
MAGNOLIE_NOTES_URL = ("https://gitlab.com/maik3531/mint-forgs/-/raw/main/"
                      "Magnolie-Organitzer/Magnolie-Notes-1.0.13.apk")
KDE_CONNECT_URL = ("https://play.google.com/store/apps/details?"
                   "id=org.kde.kdeconnect_tp&hl=de&pli=1")


def N_(message):
    """Mark deferred setup text for gettext extraction."""
    return message


def _config_directory():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "magnolie-organizer")


def _locale_path():
    return os.path.join(_config_directory(), "locale.json")


def _read_locale(path=None):
    try:
        target = path or _locale_path()
        if os.path.getsize(target) > 64 * 1024:
            return {}
        with open(target, "r", encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def _read_language(path=None):
    value = str(_read_locale(path).get("language") or "system").replace("-", "_")
    return value if value in LANGUAGE_CODES else "system"


def _persist_language(language, path=None):
    """Preserve regional settings while atomically updating the language."""
    if language not in LANGUAGE_CODES:
        raise ValueError("unsupported setup language")
    target = path or _locale_path()
    value = _read_locale(target)
    value["language"] = language
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".locale-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def _translation(language, script_directory):
    candidates = (
        os.environ.get("MAGNOLIE_LOCALE_DIR", ""),
        os.path.abspath(os.path.join(script_directory, "..", "share", "locale")),
        os.path.abspath(os.path.join(script_directory, "..", "locale")),
        os.path.abspath(os.path.join(script_directory, "locale")),
        "/usr/share/locale",
    )
    localedir = next((path for path in candidates if path and os.path.isdir(path)),
                    "/usr/share/locale")
    languages = None if language == "system" else [language]
    return gettext.translation("magnolie-organizer", localedir=localedir,
                               languages=languages, fallback=True).gettext


def _default_backup_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.abspath(os.path.join(base, "magnolie-organizer"))


def _default_selections(language="system"):
    return {
        "language": language,
        "address": {
            "firstName": "", "lastName": "", "street": "",
            "postalCode": "", "city": "", "country": "DE", "state": "",
        },
        "addressSource": "own",
        "addressSort": "last-name",
        "calendarUids": [],
        "addressBookUid": "",
        "oneTimeImports": [],
        "phoneActions": [],
        "registers": [key for key, _message in REGISTER_IDS],
        "customTabEnabled": False,
        "customTabName": "",
        "customTabDesignRequested": False,
        "customTabChanged": False,
        "customOrganizerChanged": False,
        "customOrganizer": {"version": 3, "modules": []},
        "autostart": False,
        "tray": False,
        "weather": False,
        "restoreRequest": False,
        "openHandbook": False,
        "backupPath": _default_backup_path(),
        "backupInterval": "manual",
    }


def _skipped_selections(language):
    return _default_selections(language)


def _store_result(write_state, status, selections):
    write_state(status, selections)
    return selections


def _sound_path(script_directory):
    candidates = (
        os.environ.get("MAGNOLIE_ORGANIZER_KLANG", ""),
        "/usr/share/magnolie-organizer/klang/erinnerung.wav",
        os.path.join(script_directory, "..", "share", "magnolie-organizer",
                     "klang", "erinnerung.wav"),
        os.path.join(script_directory, "..", "klang", "erinnerung.wav"),
        os.path.join(script_directory, "klang", "erinnerung.wav"),
    )
    return next((os.path.realpath(path) for path in candidates
                 if path and os.path.isfile(path)), "")


def _sound_commands(path):
    return (
        ["paplay", path], ["pw-play", path], ["aplay", "-q", path],
        ["canberra-gtk-play", "-f", path],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
    )


def _play_welcome_chime(script_directory, finder=None, starter=None):
    """Start the packaged chime once; unavailable audio must never block setup."""
    path = _sound_path(script_directory)
    if not path:
        return ""
    finder = finder or shutil.which
    starter = starter or (lambda argv: subprocess.Popen(
        argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for command in _sound_commands(path):
        executable = finder(command[0])
        if not executable:
            continue
        try:
            starter([executable] + command[1:])
            return command[0]
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _open_handbook():
    executable = shutil.which("magnolie-handbuch")
    if not executable:
        return False
    try:
        subprocess.Popen([executable], start_new_session=True,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _logo_path(script_directory):
    candidates = (
        os.path.join(script_directory, "..", "symbole", "magnolie-organizer.svg"),
        "/usr/share/icons/hicolor/scalable/apps/magnolie-organizer.svg",
        "/app/share/icons/hicolor/scalable/apps/io.gitlab.maik3531.MagnolieOrganizer.svg",
    )
    return next((os.path.abspath(path) for path in candidates if os.path.isfile(path)), "")


def run_setup(Gtk, Gdk, translate, write_state, script_directory,
              read_libreoffice=None, internet_accounts=None):
    language = _read_language()
    translator = [_translation(language, script_directory)]
    if language == "system":
        translator[0] = translate
    localized = []
    dynamic_choices = []

    def tr(message):
        return translator[0](message)

    def bind(widget, message, setter="set_label"):
        getattr(widget, setter)(tr(message))
        localized.append((widget, message, setter))
        return widget

    def label(message, css_class=None):
        widget = bind(Gtk.Label(), message)
        widget.set_halign(Gtk.Align.START)
        widget.set_line_wrap(True)
        widget.set_xalign(0)
        if css_class:
            widget.get_style_context().add_class(css_class)
        return widget

    def check(message, active=False):
        widget = bind(Gtk.CheckButton(), message)
        widget.set_halign(Gtk.Align.START)
        widget.set_active(active)
        return widget

    def page(title, introduction):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        box.pack_start(label(title, "setup-page-title"), False, False, 0)
        box.pack_start(label(introduction, "setup-introduction"), False, False, 4)
        return box

    def section(box, title):
        box.pack_start(label(title, "setup-section"), False, False, 3)

    def entry(placeholder=""):
        widget = Gtk.Entry()
        if placeholder:
            bind(widget, placeholder, "set_placeholder_text")
        widget.set_max_length(160)
        return widget

    def field(grid, row, title, widget, column=0):
        caption = label(title, "setup-field")
        grid.attach(caption, column, row, 1, 1)
        grid.attach(widget, column, row + 1, 1, 1)

    dialog = Gtk.Dialog()
    dialog.set_default_size(900, 680)
    dialog.set_size_request(760, 600)
    dialog.set_resizable(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    bind(dialog, "Set up Magnolie Organizer", "set_title")

    action_area = dialog.get_action_area()
    action_area.get_style_context().add_class("setup-navigation")
    skip_button = bind(Gtk.Button(), "Skip assistant")
    manual_button = bind(Gtk.Button(), "Manual")
    back = bind(Gtk.Button(), "Back")
    next_button = bind(Gtk.Button(), "Next")
    skip_button.get_style_context().add_class("setup-skip")
    next_button.get_style_context().add_class("suggested-action")
    action_area.pack_start(skip_button, False, False, 0)
    action_area.pack_start(manual_button, False, False, 0)
    action_area.pack_end(next_button, False, False, 0)
    action_area.pack_end(back, False, False, 0)
    skip_button.connect("clicked", lambda _button: dialog.response(3))
    manual_button.connect("clicked", lambda _button: _open_handbook())
    back.connect("clicked", lambda _button: dialog.response(1))
    next_button.connect("clicked", lambda _button: dialog.response(2))

    css = Gtk.CssProvider()
    css.load_from_data(b"""
        dialog, .setup-root { background: #f6efdc; color: #3d2b1f; }
        .setup-header { background: #2e3a34; padding: 10px 20px 8px; }
        .setup-brand { color: #f6efdc; font-family: serif; font-size: 18px; font-weight: bold; }
        .setup-gold-line { background: #be9748; min-height: 2px; }
        .setup-paper { background: #f6efdc; padding: 20px 44px; }
        .setup-page-title { color: #3d2b1f; font-family: serif; font-size: 26px; font-weight: bold; }
        .setup-introduction { color: #3d2b1f; font-family: serif; font-size: 16px; padding-bottom: 4px; }
        .setup-section { color: #3d2b1f; font-weight: bold; padding-top: 3px; }
        .setup-field { color: #5a4638; font-size: 12px; }
        .setup-list { background: #fffaf0; border: 1px solid #c7b386; padding: 8px; }
        .setup-note { color: #67584c; font-style: italic; }
        .setup-navigation { background: #ede3c9; padding: 14px 28px; border-top: 1px solid #b5a47e; }
        .setup-skip { background: #e0d5b9; color: #3d2b1f; border-color: #a69066; }
        checkbutton { color: #3d2b1f; padding: 2px; }
        button.suggested-action { background: #2e3a34; color: #f6efdc; border-color: #be9748; }
    """)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    root = dialog.get_content_area()
    root.set_spacing(0)
    root.get_style_context().add_class("setup-root")
    header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    header.get_style_context().add_class("setup-header")
    logo = _logo_path(script_directory)
    if logo:
        from gi.repository import GdkPixbuf
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(logo, 82, 82, True)
        header.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
    brand = Gtk.Label(label="MAGNOLIE ORGANIZER")
    brand.get_style_context().add_class("setup-brand")
    header.pack_start(brand, False, False, 0)
    gold_line = Gtk.Box()
    gold_line.get_style_context().add_class("setup-gold-line")
    header.pack_start(gold_line, False, False, 2)
    progress = Gtk.DrawingArea()
    progress.set_size_request(-1, 40)
    progress_accessible = progress.get_accessible()
    progress_accessible.set_name(tr("Set up Magnolie Organizer"))
    progress_page = [0]

    def draw_progress(widget, context):
        width, gap = widget.get_allocated_width(), 29
        start = (width - gap * 6) / 2
        context.set_line_width(2)
        context.set_source_rgb(190 / 255, 151 / 255, 72 / 255)
        context.move_to(start, 20)
        context.line_to(start + gap * 6, 20)
        context.stroke()
        for index in range(7):
            color = ((190, 151, 72) if index <= progress_page[0]
                     else (246, 239, 220))
            context.set_source_rgb(*(value / 255 for value in color))
            context.arc(start + gap * index, 20, 6, 0, 6.2832)
            context.fill()
        return False

    progress.connect("draw", draw_progress)
    header.pack_start(progress, False, False, 0)
    root.pack_start(header, False, False, 0)
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    stack.set_transition_duration(180)
    stack.get_style_context().add_class("setup-paper")
    root.pack_start(stack, True, True, 0)

    welcome = page(
        "Welcome to your Magnolie Organizer",
        N_("We are delighted that you chose Magnolie. Let us prepare your personal organizer together."))
    language_box = Gtk.ComboBoxText()
    for code, name in LANGUAGES:
        language_box.append(code, name)
    language_box.set_active_id(language)
    welcome.pack_start(language_box, False, False, 0)
    preview = label(
        N_("In this assistant you can prepare:\n• your address for routes and weather\n• synchronization and imports\n• phone connections\n• registers and a custom tab\n• backups, autostart and tray"),
        "setup-list")
    welcome.pack_start(preview, False, False, 8)
    restore_request = [False]
    restore_button = bind(Gtk.Button(), "Restore a Magnolie backup after startup")
    restore_button.set_halign(Gtk.Align.START)
    restore_button.set_margin_top(9)
    restore_status = label(
        "The backup chooser will open after Magnolie has started.", "setup-note")
    restore_status.set_no_show_all(True)

    def request_restore(_button):
        restore_request[0] = True
        restore_button.set_sensitive(False)
        restore_status.show()

    restore_button.connect("clicked", request_restore)
    welcome.pack_start(restore_button, False, False, 0)
    welcome.pack_start(restore_status, False, False, 0)

    address = page(
        "Your home address",
        N_("Magnolie can use this address for route planning and local weather. It is stored with your organizer data and is not sent anywhere by this assistant."))
    address_grid = Gtk.Grid(column_spacing=14, row_spacing=5)
    address_grid.set_column_homogeneous(True)
    first_name, last_name = entry("First name"), entry("Last name")
    street, postal_code = entry("Street and house number"), entry("Postal code")
    city = entry("City")
    country = Gtk.ComboBoxText.new_with_entry()
    country_choices = (("DE", "Germany"), ("AT", "Austria"), ("CH", "Switzerland"),
                       ("FR", "France"), ("NL", "Netherlands"),
                       ("BE", "Belgium"), ("PL", "Poland"), ("other", "Other"))
    for code, name in country_choices:
        country.append(code, tr(name))
    country.set_active_id("DE")
    dynamic_choices.append((country, country_choices))
    state = Gtk.ComboBoxText.new_with_entry()
    for code, name in GERMAN_REGIONS:
        state.append(code, tr(name))
    dynamic_choices.append((state, GERMAN_REGIONS))
    field(address_grid, 0, "First name", first_name, 0)
    field(address_grid, 0, "Last name", last_name, 1)
    field(address_grid, 2, "Street and house number", street, 0)
    field(address_grid, 2, "Postal code", postal_code, 1)
    field(address_grid, 4, "City", city, 0)
    field(address_grid, 4, "Country", country, 1)
    field(address_grid, 6, "State / region", state, 0)
    address_sort = Gtk.ComboBoxText()
    sort_choices = (("last-name", N_("By last name (Müller, Hans)")),
                    ("first-name", N_("By first name (Hans Müller)")))
    for key, message in sort_choices:
        address_sort.append(key, tr(message))
    address_sort.set_active_id("last-name")
    dynamic_choices.append((address_sort, sort_choices))
    field(address_grid, 6, "Sort contacts", address_sort, 1)
    address.pack_start(address_grid, False, False, 0)
    libreoffice_selected = [False]
    libreoffice = bind(Gtk.Button(), "Use address data from LibreOffice")
    libreoffice.set_halign(Gtk.Align.START)
    libreoffice_note = label("LibreOffice is not opened or changed.", "setup-note")

    def select_libreoffice(_button):
        result = read_libreoffice() if read_libreoffice else {"ok": False, "fehler": ""}
        if not result.get("ok"):
            error = Gtk.MessageDialog(transient_for=dialog, modal=True,
                                      message_type=Gtk.MessageType.WARNING,
                                      buttons=Gtk.ButtonsType.CLOSE,
                                      text=tr("No user data has been entered in LibreOffice yet (Tools ▸ Options ▸ User Data)."))
            if result.get("fehler"):
                error.format_secondary_text(str(result["fehler"]))
            error.run()
            error.destroy()
            return
        fields = result.get("felder") or {}
        first_name.set_text(str(fields.get("givenname") or ""))
        last_name.set_text(str(fields.get("sn") or ""))
        street.set_text(str(fields.get("street") or ""))
        postal_code.set_text(str(fields.get("postalcode") or ""))
        city.set_text(str(fields.get("l") or ""))
        country_value = str(fields.get("c") or "").strip()
        country_codes = {"deutschland": "DE", "germany": "DE", "österreich": "AT",
                         "oesterreich": "AT", "austria": "AT", "schweiz": "CH",
                         "switzerland": "CH"}
        country_code = country_codes.get(country_value.casefold(), country_value.upper())
        if len(country_code) == 2:
            country.set_active_id(country_code)
        else:
            country.get_child().set_text(country_value)
        state_text = str(fields.get("st") or "").strip()
        state_aliases = {name.casefold(): code for code, name in GERMAN_REGIONS}
        state_aliases.update({"sachsen": "DE-SN", "mecklenburg-vorpommern": "DE-MV"})
        state_code = state_text.upper() if state_text.upper().startswith("DE-") else \
            state_aliases.get(state_text.casefold(), "")
        if not state_code or not state.set_active_id(state_code):
            state.get_child().set_text(state_text)
        libreoffice_selected[0] = True

    libreoffice.connect("clicked", select_libreoffice)
    address.pack_start(libreoffice, False, False, 5)
    address.pack_start(libreoffice_note, False, False, 0)

    sources = page(
        "Synchronization and imports",
        N_("Choose the calendars and address books to keep synchronized and the local programs to import once."))
    source_scroll = Gtk.ScrolledWindow()
    source_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    source_scroll.set_size_request(-1, 250)
    source_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    source_list.get_style_context().add_class("setup-list")
    section(source_list, "System internet accounts")
    account_checks = []
    for account in (internet_accounts or []):
        kind = account.get("kind")
        if kind not in ("calendar", "addressbook") or not account.get("uid"):
            continue
        caption = "%s · %s" % (account.get("name") or account["uid"],
                                tr("Calendar") if kind == "calendar" else tr("Address book"))
        widget = check(caption)
        account_checks.append((account, widget))
        source_list.pack_start(widget, False, False, 0)
    if not account_checks:
        source_list.pack_start(label("No system internet accounts were found.", "setup-note"),
                               False, False, 0)
    section(source_list, "One-time imports")
    import_checks = {}
    for key, message in (("evolution", "Evolution"), ("thunderbird", "Thunderbird")):
        import_checks[key] = check(message)
        source_list.pack_start(import_checks[key], False, False, 0)
    source_scroll.add_with_viewport(source_list)
    sources.pack_start(source_scroll, True, True, 0)

    phone = page(
        "Apps for your phone",
        N_("Downloads"))
    phone_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    notes_qr = bind(Gtk.Button(), "Magnolie Notes")
    kde_qr = bind(Gtk.Button(), "KDE Connect")
    phone_actions.pack_start(notes_qr, False, False, 0)
    phone_actions.pack_start(kde_qr, False, False, 0)
    phone.pack_start(phone_actions, False, False, 9)

    def show_download_qr(_button, title, url):
        qr_dialog = Gtk.Dialog(title=tr(title),
                               transient_for=dialog, modal=True)
        qr_dialog.add_button(tr("Close"), Gtk.ResponseType.CLOSE)
        area = qr_dialog.get_content_area()
        area.set_spacing(8)
        try:
            import qrcode
            from gi.repository import GdkPixbuf
            descriptor, path = tempfile.mkstemp(prefix="magnolie-download-", suffix=".png")
            os.close(descriptor)
            try:
                qrcode.make(url).save(path)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 260, 260, True)
            finally:
                os.unlink(path)
            area.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 8)
        except (ImportError, OSError):
            pass
        area.pack_start(Gtk.LinkButton.new_with_label(
            url, url), False, False, 8)
        qr_dialog.show_all()
        qr_dialog.run()
        qr_dialog.destroy()

    notes_qr.connect("clicked", show_download_qr, "Magnolie Notes", MAGNOLIE_NOTES_URL)
    kde_qr.connect("clicked", show_download_qr, "KDE Connect", KDE_CONNECT_URL)

    registers = page(
        "Choose your registers",
        N_("Select the sections that should appear as tabs. The predefined calendars remain available independently of these register choices."))
    register_grid = Gtk.Grid(column_spacing=24, row_spacing=2)
    register_grid.set_column_homogeneous(True)
    register_checks = {}
    for index, (key, message) in enumerate(REGISTER_IDS):
        register_checks[key] = check(N_(message), True)
        register_grid.attach(register_checks[key], index % 2, index // 2, 1, 1)
    registers.pack_start(register_grid, False, False, 0)
    custom_enabled = check("Add a custom tab")
    custom_name = entry("Name of the custom tab")
    custom_name.set_sensitive(False)
    custom_tab_changed = [False]

    def custom_tab_toggled(button):
        custom_name.set_sensitive(button.get_active())
        custom_tab_changed[0] = True

    custom_enabled.connect("toggled", custom_tab_toggled)
    custom_name.connect("changed", lambda _entry: custom_tab_changed.__setitem__(0, True))
    registers.pack_start(custom_enabled, False, False, 7)
    registers.pack_start(custom_name, False, False, 0)
    custom_modules = []
    custom_modules_changed = [False]
    design_button = bind(Gtk.Button(), "Customize")
    design_button.set_halign(Gtk.Align.START)

    def request_design(_button):
        designer = Gtk.Dialog(title=tr("Choose your registers"),
                              transient_for=dialog, modal=True)
        designer.add_buttons(tr("Cancel"), Gtk.ResponseType.CANCEL,
                             tr("Apply"), Gtk.ResponseType.OK)
        area = designer.get_content_area()
        area.set_spacing(8)
        design_name = entry("Name of the custom tab")
        design_name.set_text(custom_name.get_text())
        area.pack_start(design_name, False, False, 4)
        block_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        rows = []

        def add_block(_button, block_type, title):
            if any(existing_type == block_type for existing_type, _row in rows):
                return
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
            remove = bind(Gtk.Button(), "Remove")
            row.pack_start(label(title), False, False, 0)
            row.pack_start(remove, False, False, 0)
            rows.append((block_type, row))
            remove.connect("clicked", lambda _widget: (rows.remove(
                (block_type, row)), row.destroy()))
            block_list.pack_start(row, False, False, 0)
            row.show_all()

        choices = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        for block_type, title in (("note", "Note"), ("checklist", "Tasks"),
                                  ("recurrence", "Appointments")):
            button = bind(Gtk.Button(), title)
            button.connect("clicked", add_block, block_type, title)
            choices.pack_start(button, False, False, 0)
        area.pack_start(choices, False, False, 4)
        area.pack_start(block_list, True, True, 0)
        setup_types = {"notes": ("note", "Note"), "tasks": ("checklist", "Tasks"),
                       "appointments": ("recurrence", "Appointments")}
        for module in custom_modules:
            if module.get("type") in setup_types:
                block_type, title = setup_types[module["type"]]
                add_block(None, block_type, title)
        designer.show_all()
        if designer.run() == Gtk.ResponseType.OK:
            custom_enabled.set_active(True)
            custom_name.set_text(design_name.get_text().strip()[:MAX_ITEM_LENGTH])
            custom_modules[:] = [{"id": "setup-%d" % index,
                "type": {"note": "notes", "checklist": "tasks",
                         "recurrence": "appointments"}[block_type],
                "page": "left" if index % 2 == 0 else "right",
                "order": index // 2}
                for index, (block_type, _row) in enumerate(rows)]
            custom_modules_changed[0] = True
        designer.destroy()

    design_button.connect("clicked", request_design)
    registers.pack_start(design_button, False, False, 4)

    backup = page(
        "Backups and recovery",
        N_("Choose safe defaults for future backups. No scheduled job is started by the assistant."))
    section(backup, "Preferred backup folder")
    folder_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    backup_path = entry()
    backup_path.set_text(_default_backup_path())
    folder_row.pack_start(backup_path, True, True, 0)
    browse = bind(Gtk.Button(), "Browse…")
    folder_row.pack_start(browse, False, False, 0)
    backup.pack_start(folder_row, False, False, 0)

    def choose_folder(_button):
        chooser = Gtk.FileChooserDialog(title=tr("Preferred backup folder"), parent=dialog,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons(tr("Cancel"), Gtk.ResponseType.CANCEL,
                            tr("Select"), Gtk.ResponseType.OK)
        current_path = backup_path.get_text().strip()
        if os.path.isdir(current_path):
            chooser.set_current_folder(current_path)
        if chooser.run() == Gtk.ResponseType.OK:
            backup_path.set_text(chooser.get_filename() or _default_backup_path())
        chooser.destroy()

    browse.connect("clicked", choose_folder)
    section(backup, "Backup rhythm")
    rhythm = Gtk.ComboBoxText()
    rhythm_choices = (("manual", N_("Manual only")), ("daily", N_("Daily")),
                      ("weekly", N_("Weekly")), ("monthly", N_("Monthly")))
    for key, message in rhythm_choices:
        rhythm.append(key, tr(message))
    rhythm.set_active_id("manual")
    dynamic_choices.append((rhythm, rhythm_choices))
    backup.pack_start(rhythm, False, False, 0)

    finish = page(
        "Everything is ready",
        N_("We hope you enjoy using Magnolie Organizer. You can change every choice later in Settings."))
    autostart = check("Start Magnolie automatically when I sign in")
    weather = check("Show weather for the next three days")
    finish.pack_start(autostart, False, False, 4)
    finish.pack_start(weather, False, False, 4)
    finish.pack_start(label(N_("Weather requests are sent to wttr.in. Your own address in Contacts is used first, followed by local LibreOffice user data. If neither contains a location and retrieval without one is allowed, wttr.in estimates the location from your internet connection's public IP address."), "setup-note"), False, False, 0)

    pages = (welcome, address, sources, phone, registers, backup, finish)
    names = tuple("page-%d" % index for index in range(7))
    for name, child in zip(names, pages):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add_with_viewport(child)
        stack.add_named(scroll, name)
    current = 0

    def show_page(index):
        stack.set_visible_child_name(names[index])
        progress_page[0] = index
        progress_accessible.set_description("%d / %d" % (index + 1, len(names)))
        progress.queue_draw()
        back.set_visible(index > 0)
        skip_button.set_visible(index == 0)
        manual_button.set_visible(index == 0)
        next_button.set_label(tr("Start Magnolie") if index == 6 else tr("Next"))
        if index == 1:
            first_name.grab_focus()

    def refresh_text():
        for widget, message, setter in localized:
            getattr(widget, setter)(tr(message))
        for combo, choices in dynamic_choices:
            selected = combo.get_active_id()
            combo.remove_all()
            for key, message in choices:
                combo.append(key, tr(message))
            combo.set_active_id(selected)
        show_page(current)

    def language_changed(combo):
        nonlocal language
        selected = combo.get_active_id()
        if selected not in LANGUAGE_CODES or selected == language:
            return
        try:
            _persist_language(selected)
        except OSError:
            combo.set_active_id(language)
            return
        language = selected
        translator[0] = _translation(language, script_directory)
        refresh_text()

    language_box.connect("changed", language_changed)

    def selections():
        country_value = country.get_active_id()
        if not country_value or country_value == "other":
            country_value = country.get_child().get_text().strip()[:80]
        state_value = state.get_active_id() or state.get_child().get_text()
        value = _default_selections(language)
        value.update({
            "address": {
                "firstName": first_name.get_text().strip()[:MAX_ITEM_LENGTH],
                "lastName": last_name.get_text().strip()[:MAX_ITEM_LENGTH],
                "street": street.get_text().strip()[:160],
                "postalCode": postal_code.get_text().strip()[:32],
                "city": city.get_text().strip()[:MAX_ITEM_LENGTH],
                "country": str(country_value).strip()[:80],
                "state": str(state_value or "").strip()[:80],
            },
            "addressSource": "libreoffice" if libreoffice_selected[0] else "own",
            "addressSort": address_sort.get_active_id() or "last-name",
            "calendarUids": [account["uid"] for account, widget in account_checks
                              if widget.get_active() and account["kind"] == "calendar"],
            "addressBookUid": next((account["uid"] for account, widget in account_checks
                                    if widget.get_active() and account["kind"] == "addressbook"), ""),
            "oneTimeImports": [key for key, widget in import_checks.items()
                                if widget.get_active()],
            "registers": [key for key, widget in register_checks.items()
                          if widget.get_active()],
            "customTabEnabled": custom_enabled.get_active(),
            "customTabName": custom_name.get_text().strip()[:MAX_ITEM_LENGTH],
            "customTabChanged": custom_tab_changed[0],
            "customOrganizerChanged": custom_modules_changed[0],
            "customOrganizer": {"version": 3, "modules": list(custom_modules)},
            "autostart": autostart.get_active(),
            "tray": autostart.get_active(),
            "weather": weather.get_active(),
            "restoreRequest": restore_request[0],
            "openHandbook": False,
            "backupPath": backup_path.get_text().strip()[:4096] or _default_backup_path(),
            "backupInterval": rhythm.get_active_id() or "manual",
        })
        return value

    show_page(current)
    dialog.show_all()
    show_page(current)
    _play_welcome_chime(script_directory)
    result = None
    while True:
        response = dialog.run()
        if response == 1 and current > 0:
            current -= 1
            show_page(current)
            continue
        if response == 3 and current == 0:
            result = _store_result(write_state, "skipped", _skipped_selections(language))
            break
        if response != 2:
            break
        if current < 6:
            current += 1
            show_page(current)
            continue
        result = _store_result(write_state, "complete", selections())
        break
    dialog.destroy()
    return result
