#!/usr/bin/env python3
"""Native GTK3 first-run assistant for Magnolie Organizer."""

import gettext
import json
import locale
import os
import shutil
import subprocess
import tempfile
import threading


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
    ("DE-HH", "Hamburg"), ("DE-HE", "Hesse"),
    ("DE-MV", "Mecklenburg-Western Pomerania"), ("DE-NI", "Lower Saxony"),
    ("DE-NW", "North Rhine-Westphalia"), ("DE-RP", "Rhineland-Palatinate"),
    ("DE-SL", "Saarland"), ("DE-SN", "Saxony"),
    ("DE-ST", "Saxony-Anhalt"), ("DE-SH", "Schleswig-Holstein"),
    ("DE-TH", "Thuringia"),
)
AUSTRIAN_REGIONS = (
    ("AT-1", "Burgenland"), ("AT-2", "Carinthia"),
    ("AT-3", "Lower Austria"), ("AT-4", "Upper Austria"),
    ("AT-5", "Salzburg"), ("AT-6", "Styria"), ("AT-7", "Tyrol"),
    ("AT-8", "Vorarlberg"), ("AT-9", "Vienna"),
)
SWISS_REGIONS = (
    ("CH-AG", "Aargau"), ("CH-AI", "Appenzell Innerrhoden"),
    ("CH-AR", "Appenzell Ausserrhoden"), ("CH-BE", "Bern"),
    ("CH-BL", "Basel-Landschaft"), ("CH-BS", "Basel-Stadt"),
    ("CH-FR", "Fribourg"), ("CH-GE", "Geneva"), ("CH-GL", "Glarus"),
    ("CH-GR", "Grisons"), ("CH-JU", "Jura"), ("CH-LU", "Lucerne"),
    ("CH-NE", "Neuchâtel"), ("CH-NW", "Nidwalden"), ("CH-OW", "Obwalden"),
    ("CH-SG", "St. Gallen"), ("CH-SH", "Schaffhausen"),
    ("CH-SO", "Solothurn"), ("CH-SZ", "Schwyz"), ("CH-TG", "Thurgau"),
    ("CH-TI", "Ticino"), ("CH-UR", "Uri"), ("CH-VD", "Vaud"),
    ("CH-VS", "Valais"), ("CH-ZG", "Zug"), ("CH-ZH", "Zurich"),
)
COUNTRY_CHOICES = (
    ("DE", "Germany"), ("AT", "Austria"), ("CH", "Switzerland"),
    ("LI", "Liechtenstein"), ("LU", "Luxembourg"), ("BE", "Belgium"),
    ("NL", "Netherlands"), ("FR", "France"), ("IT", "Italy"),
    ("PL", "Poland"), ("CZ", "Czechia"), ("ES", "Spain"),
)
REGIONS_BY_COUNTRY = {
    "DE": GERMAN_REGIONS, "AT": AUSTRIAN_REGIONS, "CH": SWISS_REGIONS,
}
MAX_ITEM_LENGTH = 80
# Generated from handbook mobile-downloads.json by tools/sync_mobile_downloads.py.
MAGNOLIE_NOTES_URL = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes.apk"
KDE_CONNECT_URL = "https://play.google.com/store/apps/details?id=org.kde.kdeconnect_tp"


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


def _system_country(environ=None):
    # LANGUAGE controls messages, not the user's address territory.
    env = os.environ if environ is None else environ
    regional = env.get("LC_ALL") or env.get("LC_ADDRESS") or env.get("LANG") or ""
    if not regional and environ is None:
        regional = locale.getlocale()[0] or ""
    parts = regional.split(".")[0].split("@")[0].replace("-", "_").split("_")
    return next((part.upper() for part in parts[1:]
                 if len(part) == 2 and part.isascii() and part.isalpha()), "")


def _default_selections(language="system"):
    return {
        "language": language,
        "address": {
            "firstName": "", "lastName": "", "street": "",
            "postalCode": "", "city": "", "country": _system_country(), "state": "",
        },
        "addressSource": "own",
        "addressChanged": False,
        "schoolHolidays": False,
        "schoolHolidayRegion": "",
        "addressSort": "last-name",
        "calendarUids": [],
        "addressBookUid": "",
        "oneTimeImports": [],
        "stagedImports": [],
        "phoneActions": [],
        "phoneBackgroundServices": [],
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
    return dict(_default_selections(language), setupSkipped=True)


def school_holiday_region(country, state, translate=lambda text: text):
    """Resolve only locally configured OpenHolidays subdivisions; never guess."""
    value = str(state or "").strip().casefold()
    aliases = {"sachsen": "DE-SN", "mecklenburg-vorpommern": "DE-MV"}
    for code, name in REGIONS_BY_COUNTRY.get(str(country or "").strip().upper(), ()):
        if value in (code.casefold(), name.casefold(), translate(name).casefold()) or aliases.get(value) == code:
            return code, translate(name)
    return "", ""


def _store_result(write_state, status, selections):
    write_state(status, selections)
    return selections


def _finish_result(write_state, status, selections):
    _persist_language(selections["language"])
    return _store_result(write_state, status, selections)


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
        os.path.join(script_directory, "..", "share", "icons", "hicolor", "256x256",
                     "apps", "magnolie-organizer.png"),
        os.path.join(script_directory, "..", "share", "icons", "hicolor", "scalable",
                     "apps", "magnolie-organizer.svg"),
        "/usr/share/icons/hicolor/scalable/apps/magnolie-organizer.svg",
        "/app/share/icons/hicolor/scalable/apps/io.gitlab.maik3531.MagnolieOrganizer.svg",
    )
    return next((os.path.abspath(path) for path in candidates if os.path.isfile(path)), "")


def run_setup(Gtk, Gdk, translate, write_state, script_directory,
              read_libreoffice=None, internet_accounts=None, prepare_import=None,
              discover_connection=None, commit_connection=None, phone_services=None):
    from gi.repository import GLib
    language = _read_language()
    translator = [_translation(language, script_directory)]
    if language == "system":
        translator[0] = translate
    localized = []
    dynamic_choices = []
    staged_imports = {}
    connection = {"token": "", "calendarUids": [], "addressBookUid": ""}
    alive = [True]
    busy = [False]
    phone_results = {}
    phone_start_checks = {}

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

    def entry(placeholder=None):
        widget = Gtk.Entry()
        if placeholder:
            bind(widget, placeholder, "set_placeholder_text")
        widget.set_max_length(160)
        return widget

    def field(grid, row, title, widget, column=0, span=1):
        caption = label(title, "setup-field")
        widget.set_hexpand(True)
        grid.attach(caption, column, row, span, 1)
        grid.attach(widget, column, row + 1, span, 1)

    dialog = Gtk.Dialog()
    dialog.connect("destroy", lambda *_: alive.__setitem__(0, False))
    dialog.set_default_size(960, 780)
    dialog.set_size_request(820, 680)
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    if monitor:
        # Leave room for window decorations; page scrolling keeps navigation on-screen.
        available_height = max(1, monitor.get_workarea().height - 48)
        if available_height < 780:
            dialog.set_default_size(960, available_height)
            dialog.set_size_request(820, min(680, available_height))
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

    def set_busy(value):
        busy[0] = value
        stack.set_sensitive(not value)
        for button in (next_button, back, skip_button):
            button.set_sensitive(not value)

    def background(work, done):
        def deliver(result, error):
            if alive[0]:
                done(result, error)
            return False

        def worker():
            try:
                result, error = work(), None
            except Exception as failure:
                result, error = None, failure
            GLib.idle_add(deliver, result, error)
        threading.Thread(target=worker, daemon=True).start()

    def show_error(message, detail="", parent=None):
        error = Gtk.MessageDialog(transient_for=parent or dialog, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.CLOSE, text=tr(message))
        if detail:
            error.format_secondary_text(detail)
        error.run()
        error.destroy()

    css = Gtk.CssProvider()
    css.load_from_data(b"""
        dialog, .setup-root { background: #f6efdc; color: #3d2b1f; }
        .setup-header { background: #2e3a34; padding: 8px 20px 7px; }
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
        from gi.repository import GdkPixbuf, GLib
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(logo, 58, 58, True)
        except GLib.Error:
            pixbuf = None
        if pixbuf:
            header.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
    brand = Gtk.Label(label="MAGNOLIE ORGANIZER")
    brand.get_style_context().add_class("setup-brand")
    header.pack_start(brand, False, False, 0)
    gold_line = Gtk.Box()
    gold_line.get_style_context().add_class("setup-gold-line")
    header.pack_start(gold_line, False, False, 2)
    progress = Gtk.DrawingArea()
    progress.set_size_request(-1, 38)
    progress_accessible = progress.get_accessible()
    progress_accessible.set_name(tr("Set up Magnolie Organizer"))
    progress_page = [0]

    def draw_progress(widget, context):
        width, gap = widget.get_allocated_width(), 29
        start = (width - gap * 6) / 2
        context.set_line_width(2)
        context.set_source_rgb(190 / 255, 151 / 255, 72 / 255)
        context.move_to(start, 19)
        context.line_to(start + gap * 6, 19)
        context.stroke()
        for index in range(7):
            color = ((190, 151, 72) if index <= progress_page[0]
                     else (246, 239, 220))
            context.set_source_rgb(*(value / 255 for value in color))
            context.arc(start + gap * index, 19, 6, 0, 6.2832)
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
    language_box.set_name("setup-language")
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
        "Your address",
        N_("Magnolie can use this information when preparing routes and finding local weather. You can leave every field empty."))
    address_grid = Gtk.Grid(column_spacing=14, row_spacing=5)
    address_grid.set_column_homogeneous(True)
    first_name, last_name = entry("First name"), entry("Last name")
    street, postal_code = entry("Street and house number"), entry("Postal code")
    city = entry("City")
    country = Gtk.ComboBoxText.new_with_entry()
    country.set_name("setup-country")
    country_choices = COUNTRY_CHOICES
    for code, name in country_choices:
        country.append(code, tr(name))
    initial_country = _system_country()
    if not country.set_active_id(initial_country):
        country.get_child().set_text(initial_country)
    dynamic_choices.append((country, country_choices))
    state = Gtk.ComboBoxText.new_with_entry()
    state.set_name("setup-state")
    address_changed = [False]
    refreshing_address = [False]
    holiday_region = [""]
    school_holidays = Gtk.CheckButton(label="")
    school_holidays.set_name("setup-school-holidays")
    school_holidays.set_no_show_all(True)
    school_holidays.get_child().set_line_wrap(True)
    school_holidays.get_child().set_xalign(0)
    holiday_note = label(N_("The information is retrieved once from the open directory openholidaysapi.org and then kept in the organizer. The application therefore needs an internet connection only once."), "setup-note")
    holiday_unavailable = label(N_("School holidays are not available for this region."), "setup-note")
    for widget in (holiday_note, holiday_unavailable):
        widget.set_no_show_all(True)

    def update_school_holidays(*_args):
        if refreshing_address[0]:
            return
        country_value = country.get_active_id() or country.get_child().get_text()
        state_value = state.get_active_id()
        if state_value is None:
            state_value = state.get_child().get_text()
        code, name = school_holiday_region(country_value, state_value, tr)
        if code != holiday_region[0]:
            school_holidays.set_active(False)
        holiday_region[0] = code
        school_holidays.set_label(tr("Show school holidays for %(state)s in the calendar?") % {"state": name})
        school_holidays.set_visible(bool(code))
        holiday_note.set_visible(bool(code))
        holiday_unavailable.set_visible(bool(str(state_value).strip()) and not code)

    state.connect("changed", update_school_holidays)

    def populate_regions(selected=""):
        choices = REGIONS_BY_COUNTRY.get(country.get_active_id(), ())
        state.remove_all()
        state.append("", tr("None"))
        for code, name in choices:
            state.append(code, tr(name))
        if not selected:
            state.set_active_id("")
        elif not state.set_active_id(selected):
            state.set_active(-1)
            state.get_child().set_text(selected)

    populate_regions()
    country.connect("changed", lambda _combo: populate_regions())
    field(address_grid, 0, "First name", first_name, 0, 2)
    field(address_grid, 2, "Last name", last_name, 0, 2)
    field(address_grid, 4, "Street and house number", street, 0, 2)
    field(address_grid, 6, "Postal code", postal_code, 0)
    field(address_grid, 6, "City", city, 1)
    field(address_grid, 8, "Country", country, 0)
    field(address_grid, 8, "State / region", state, 1)
    address_sort = Gtk.ComboBoxText()
    sort_choices = (("last-name", N_("By last name (Müller, Hans)")),
                    ("first-name", N_("By first name (Hans Müller)")))
    for key, message in sort_choices:
        address_sort.append(key, tr(message))
    address_sort.set_active_id("last-name")
    dynamic_choices.append((address_sort, sort_choices))
    address.pack_start(address_grid, False, False, 0)
    address.pack_start(school_holidays, False, False, 0)
    address.pack_start(holiday_note, False, False, 0)
    address.pack_start(holiday_unavailable, False, False, 0)
    section(address, "Sort contacts")
    address.pack_start(address_sort, False, False, 0)
    libreoffice_selected = [False]
    address_inputs = (first_name, last_name, street, postal_code, city, country, state)

    def address_hints(focus=False):
        first_missing = None
        for widget in address_inputs:
            if widget in (country, state):
                value = widget.get_active_id()
                if value is None:
                    value = widget.get_child().get_text()
            else:
                value = widget.get_text()
            missing = libreoffice_selected[0] and not value.strip()
            target = widget.get_child() if widget in (country, state) else widget
            target.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                          "dialog-information-symbolic" if missing else None)
            target.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                tr("Magnolie can use this information when preparing routes and finding local weather. You can leave every field empty.") if missing else None)
            if missing and first_missing is None:
                first_missing = target
        # All setup address fields are optional. Never move focus during typing.
        if focus and first_missing is not None:
            first_missing.grab_focus()

    for widget in address_inputs:
        widget.connect("changed", lambda _widget: address_hints())
        widget.connect("changed", lambda _widget: address_changed.__setitem__(0, True)
                       if not refreshing_address[0] else None)
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
        if country_value:
            if not country.set_active_id(country_code):
                country.set_active(-1)
                country.get_child().set_text(country_value)
        state_text = str(fields.get("st") or "").strip()
        all_regions = GERMAN_REGIONS + AUSTRIAN_REGIONS + SWISS_REGIONS
        state_aliases = {name.casefold(): code for code, name in all_regions}
        state_aliases.update({"sachsen": "DE-SN", "mecklenburg-vorpommern": "DE-MV"})
        state_code = state_text.upper() if len(state_text) >= 4 and state_text[2:3] == "-" else \
            state_aliases.get(state_text.casefold(), "")
        if not state_code or not state.set_active_id(state_code):
            state.set_active(-1)
            state.get_child().set_text(state_text)
        libreoffice_selected[0] = True
        address_hints(focus=True)

    libreoffice.connect("clicked", select_libreoffice)
    address.pack_start(libreoffice, False, False, 5)
    address.pack_start(libreoffice_note, False, False, 0)

    sources = page(
        "Sources and imports",
        N_("Choose sources now. Import previews are kept until you finish the assistant."))
    source_scroll = Gtk.ScrolledWindow()
    source_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    source_scroll.set_size_request(-1, 250)
    source_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    source_list.get_style_context().add_class("setup-list")
    section(source_list, "Synchronization")
    connection_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    connection_status = label("Connection ready")
    connection_status.set_no_show_all(True)

    def configure_connection(_button, kind):
        config = Gtk.Dialog(title=tr("Nextcloud" if kind == "nextcloud" else "CalDAV + CardDAV Server"), transient_for=dialog, modal=True)
        config.set_default_size(620, 550)
        config.add_button(tr("Cancel"), Gtk.ResponseType.CANCEL)
        apply = config.add_button(tr("Apply"), Gtk.ResponseType.OK)
        apply.set_sensitive(False)
        area = config.get_content_area()
        area.set_spacing(8)
        fields = []
        for title in ("Server", "Username", "Application password"):
            area.pack_start(Gtk.Label(label=tr(title), xalign=0), False, False, 0)
            widget = Gtk.Entry()
            widget.get_accessible().set_name(tr(title))
            area.pack_start(widget, False, False, 0)
            fields.append(widget)
        server, user, password = fields
        password.set_visibility(False)
        discover = Gtk.Button(label=tr("Discover"))
        area.pack_start(discover, False, False, 0)
        calendar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        calendar_scroll = Gtk.ScrolledWindow()
        calendar_scroll.set_size_request(-1, 110)
        calendar_scroll.add_with_viewport(calendar_box)
        area.pack_start(Gtk.Label(label=tr("Calendars"), xalign=0), False, False, 0)
        area.pack_start(calendar_scroll, True, True, 0)
        area.pack_start(Gtk.Label(label=tr("Address book"), xalign=0), False, False, 0)
        books = Gtk.ComboBoxText()
        area.pack_start(books, False, False, 0)
        candidate = [None]
        checks = []
        config_alive = [True]
        config.connect("destroy", lambda *_: config_alive.__setitem__(0, False))

        def invalidate(_widget):
            candidate[0] = None
            apply.set_sensitive(False)
        for widget in fields:
            widget.connect("changed", invalidate)

        def discovered(result, error):
            if not config_alive[0]:
                return
            for widget in fields + [discover]:
                widget.set_sensitive(True)
            if error:
                show_error("Connection discovery failed. Check the server and credentials.", parent=config)
                return
            candidate[0] = result
            for widget in calendar_box.get_children():
                widget.destroy()
            checks.clear()
            for source in result["calendars"]:
                widget = Gtk.CheckButton(label=source["name"])
                calendar_box.pack_start(widget, False, False, 0)
                checks.append((source["uid"], widget))
            calendar_box.show_all()
            books.remove_all()
            books.append("", tr("None"))
            for source in result["addressBooks"]:
                books.append(source["uid"], source["name"])
            books.set_active_id("")
            apply.set_sensitive(True)

        def discover_clicked(_widget):
            values = [widget.get_text().strip() if widget is not password else widget.get_text() for widget in fields]
            for widget in fields + [discover, apply]:
                widget.set_sensitive(False)
            background(lambda: discover_connection(kind, *values), discovered)
        discover.connect("clicked", discover_clicked)
        config.show_all()
        if config.run() == Gtk.ResponseType.OK and candidate[0]:
            connection.update(token=candidate[0]["token"], calendarUids=[uid for uid, widget in checks if widget.get_active()],
                              addressBookUid=books.get_active_id() or "")
            if connection["addressBookUid"]:
                for account, widget in account_checks:
                    if account["kind"] == "addressbook":
                        widget.set_active(False)
            connection_status.show()
        password.set_text("")
        config.destroy()

    for kind, title in (("nextcloud", "Nextcloud"), ("generic-dav", "CalDAV + CardDAV Server")):
        button = bind(Gtk.Button(), title)
        button.set_sensitive(discover_connection is not None)
        button.connect("clicked", configure_connection, kind)
        connection_buttons.pack_start(button, False, False, 0)
    source_list.pack_start(connection_buttons, False, False, 0)
    source_list.pack_start(connection_status, False, False, 0)
    section(source_list, "Import once")
    import_checks = {}

    def import_selected(widget, source):
        if not widget.get_active():
            staged_imports.pop(source, None)
            return
        if busy[0] or prepare_import is None:
            widget.set_active(False)
            return
        set_busy(True)

        def finished(result, error):
            if error:
                widget.set_active(False)
                set_busy(False)
                show_error("Import failed.", str(error))
                return
            if result is None:
                choose_file()
                return
            items = [item for key in ("kontakte", "termine", "aufgaben", "jahrestage", "geburtstage", "notizen")
                     for item in (result.get(key) or []) if isinstance(item, dict)]
            if not items:
                widget.set_active(False)
                set_busy(False)
                show_error("No supported data was found.")
                return
            preview = Gtk.MessageDialog(transient_for=dialog, modal=True, message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK_CANCEL, text=tr("Import preview"))
            preview_text = tr("Entries ready to import") + ": " + str(len(items)) + "\n" + \
                "\n".join(str(item.get("name") or item.get("titel") or item.get("nachname") or item.get("vorname") or "")[:160] for item in items[:10])
            if result.get("sourceVersion"):
                preview_text += "\n" + tr("Thunderbird profile version") + ": " + result["sourceVersion"]
            preview.format_secondary_text(preview_text)
            if preview.run() == Gtk.ResponseType.OK:
                staged_imports[source] = result
            else:
                widget.set_active(False)
            preview.destroy()
            set_busy(False)

        def choose_file():
            picker = Gtk.FileChooserDialog(title=tr("Import"), parent=dialog, action=Gtk.FileChooserAction.OPEN)
            picker.add_buttons(tr("Cancel"), Gtk.ResponseType.CANCEL, tr("Select"), Gtk.ResponseType.OK)
            extensions = {"ics": ("ics", "vcs", "lcs", "zip"), "vcard": ("vcf", "csv", "zip"),
                "ldif": ("ldif", "ldi", "zip"), "claws": ("xml", "ldif", "ldi", "zip"),
                "csv-lotus": ("csv", "zip")}.get(source, ("ics", "vcs", "lcs", "vcf", "ldif", "ldi", "xml", "csv"))
            file_filter = Gtk.FileFilter()
            file_filter.set_name(tr("Supported files"))
            for extension in extensions:
                file_filter.add_pattern("*." + extension)
            picker.add_filter(file_filter)
            accepted = picker.run() == Gtk.ResponseType.OK
            path = picker.get_filename() if accepted else None
            picker.destroy()
            if not path:
                widget.set_active(False)
                set_busy(False)
                return
            def file_finished(result, error):
                if result is None and error is None:
                    error = ValueError(tr("No supported data was found."))
                finished(result, error)
            background(lambda: prepare_import(source, path), file_finished)

        if source in ("thunderbird", "evolution"):
            background(lambda: prepare_import(source), finished)
        else:
            choose_file()

    for key, message in (("thunderbird", "Thunderbird"), ("ics", "Calendar (ICS)"), ("vcard", "vCard / iPhone / iCloud"),
                         ("ldif", "LDIF"), ("claws", "Claws Mail XML / LDIF"), ("csv-lotus", "CSV / Lotus Organizer"), ("evolution", "Evolution")):
        widget = check(message)
        widget.set_sensitive(prepare_import is not None)
        widget.connect("toggled", import_selected, key)
        import_checks[key] = widget
        source_list.pack_start(widget, False, False, 0)
    section(source_list, "System internet accounts")
    account_checks = []

    def system_account_toggled(widget, account):
        if widget.get_active() and account["kind"] == "addressbook":
            connection["addressBookUid"] = ""
            for other, choice in account_checks:
                if choice is not widget and other["kind"] == "addressbook":
                    choice.set_active(False)
    for account in (internet_accounts or []):
        kind = account.get("kind")
        if kind not in ("calendar", "addressbook") or not account.get("uid"):
            continue
        caption = "%s · %s" % (account.get("name") or account["uid"],
                                tr("Calendar") if kind == "calendar" else tr("Address book"))
        widget = check(caption)
        account_checks.append((account, widget))
        widget.connect("toggled", system_account_toggled, account)
        source_list.pack_start(widget, False, False, 0)
    if not account_checks:
        source_list.pack_start(label("No system internet accounts were found.", "setup-note"),
                               False, False, 0)
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
    phone_connect_buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    phone_status = label("Choose a connection. Confirm pairing on the phone and this computer.")

    def phone_prompt(request):
        event = threading.Event()
        answer = [None]

        def show():
            if not alive[0]:
                event.set()
                return False
            prompt = Gtk.Dialog(title=tr("Phone connection"), transient_for=dialog, modal=True)
            prompt.add_buttons(tr("Cancel"), Gtk.ResponseType.CANCEL, tr("Confirm"), Gtk.ResponseType.OK)
            area = prompt.get_content_area()
            area.set_spacing(9)
            area.pack_start(Gtk.Label(label=tr("Select your phone" if request["kind"] == "select" else
                "Confirm that the code matches on both devices.")), False, False, 0)
            devices = Gtk.ComboBoxText()
            for device in request["devices"]:
                devices.append(device["uid"], device["name"])
            if request["kind"] != "select":
                devices.set_active(0)
            area.pack_start(devices, False, False, 0)
            area.pack_start(Gtk.Label(label=request.get("code", "")), False, False, 0)
            own = Gtk.CheckButton(label=tr("This is my own phone"))
            if request.get("canMarkOwn"):
                area.pack_start(own, False, False, 0)
            prompt.show_all()
            if prompt.run() == Gtk.ResponseType.OK and devices.get_active_id():
                answer[0] = devices.get_active_id() if request["kind"] == "select" else "accept-own" if own.get_active() else "accept"
            prompt.destroy()
            event.set()
            return False
        GLib.idle_add(show)
        while alive[0] and not event.wait(.1):
            pass
        return answer[0]

    def connect_phone(_button, transport):
        if phone_services is None or busy[0]:
            return
        set_busy(True)
        phone_status.set_text(tr("Waiting for authenticated phone connection..."))

        def connected(result, error):
            set_busy(False)
            if error or not result or result.get("authenticated") is not True:
                phone_results.pop(transport, None)
                phone_status.set_text(tr("Phone connection failed."))
                show_error("Phone connection failed.", str(error) if error else tr("The phone connection was not authenticated."))
                return
            phone_results[transport] = result
            phone_status.set_text(tr("Connected") + ": " + result["name"])
        background(lambda: phone_services.connect(transport, phone_prompt), connected)

    phone_capabilities = phone_services.capabilities() if phone_services else []
    for transport, title in (("wifi", "Connect phone via WLAN"), ("kdeconnect", "Connect via KDE Connect"),
                             ("bluetooth", "Connect via Bluetooth")):
        button = bind(Gtk.Button(), title)
        capability = next((item for item in phone_capabilities if item["transport"] == transport), {})
        button.set_sensitive(capability.get("available") is True)
        if capability.get("available") is not True:
            button.set_tooltip_text(tr(capability.get("reason") or "This phone transport is unavailable."))
        button.connect("clicked", connect_phone, transport)
        phone_connect_buttons.pack_start(button, False, False, 0)
    phone.pack_start(phone_connect_buttons, False, False, 0)
    phone.pack_start(phone_status, False, False, 0)
    phone.pack_start(label("Completed pairings are kept if you cancel setup. No additional phone permissions are granted.", "setup-note"), False, False, 0)

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
        "Choose your organizer tabs",
        N_("These are Magnolie's actual tabs. You can show only the sections that fit your everyday life."))
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
        designer = Gtk.Dialog(title=tr("Choose your organizer tabs"),
                              transient_for=dialog, modal=True)
        designer.add_buttons(tr("Cancel"), Gtk.ResponseType.CANCEL,
                             tr("Apply"), Gtk.ResponseType.OK)
        area = designer.get_content_area()
        area.set_spacing(8)
        design_name = entry("Name of the custom tab")
        design_name.set_text(custom_name.get_text())
        area.pack_start(design_name, False, False, 4)
        block_list = Gtk.Grid(column_spacing=12, row_spacing=6, column_homogeneous=True)
        columns = {}
        for column, (side, title) in enumerate((("left", "Left page"), ("right", "Right page"))):
            block_list.attach(label(title), column, 0, 1, 1)
            columns[side] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            columns[side].set_hexpand(True)
            columns[side].set_valign(Gtk.Align.START)
            block_list.attach(columns[side], column, 1, 1, 1)
        rows = []

        def page_available(block_type, target, excluded=None):
            page_rows = [item for item in rows
                         if item is not excluded and item["page"] == target]
            return len(page_rows) < 2 and (block_type != "notes" or not any(
                item["type"] == "notes" for item in page_rows))

        def add_block(_button, block_type, title, requested_page=None):
            if block_type != "notes" and any(item["type"] == block_type for item in rows):
                return
            target = requested_page if requested_page in ("left", "right") and page_available(
                block_type, requested_page) else next((
                page for page in (("left", "right") if block_type == "notes" else ("right", "left"))
                if page_available(block_type, page)), None)
            if target is None:
                return
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            remove = bind(Gtk.Button(), "Remove")
            row.pack_start(label(title), False, False, 0)
            page_choice = Gtk.ComboBoxText()
            page_choice.append("left", tr("Left page"))
            page_choice.append("right", tr("Right page"))
            page_choice.set_active_id(target)
            page_choice.get_accessible().set_name(tr(title) + ": " + tr("Page"))
            row.pack_start(page_choice, False, False, 0)
            row.pack_start(remove, False, False, 0)
            item = {"type": block_type, "page": target, "row": row, "changing": False}
            rows.append(item)
            dynamic_choices.append((page_choice, (("left", "Left page"),
                                                   ("right", "Right page"))))

            def change_page(combo):
                if item["changing"]:
                    return
                selected = combo.get_active_id()
                if not page_available(block_type, selected, item):
                    item["changing"] = True
                    combo.set_active_id(item["page"])
                    item["changing"] = False
                    return
                item["page"] = selected
                rows.remove(item)
                rows.append(item)
                row.get_parent().remove(row)
                columns[selected].pack_start(row, False, False, 0)
                page_choice.grab_focus()

            page_choice.connect("changed", change_page)
            remove.connect("clicked", lambda _widget: (rows.remove(item), row.destroy()))
            columns[target].pack_start(row, False, False, 0)
            row.show_all()

        choices = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        for block_type, title in (("notes", "Text block"), ("tasks", "Tasks"),
                                  ("appointments", "Appointments")):
            button = bind(Gtk.Button(), title)
            button.connect("clicked", add_block, block_type, title)
            choices.pack_start(button, False, False, 0)
        area.pack_start(choices, False, False, 4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(block_list)
        area.pack_start(scroll, True, True, 0)
        display = designer.get_display()
        monitor = display.get_monitor_at_window(dialog.get_window()) if dialog.get_window() else display.get_primary_monitor()
        bounds = monitor.get_workarea() if monitor else None
        designer.set_default_size(min(760, bounds.width) if bounds else 760,
                                  min(470, bounds.height) if bounds else 470)
        setup_types = {"notes": "Text block", "tasks": "Tasks",
                       "appointments": "Appointments"}
        for module in custom_modules:
            if module.get("type") in setup_types:
                add_block(None, module["type"], setup_types[module["type"]],
                          module.get("page", "left"))
        designer.show_all()
        if designer.run() == Gtk.ResponseType.OK:
            custom_enabled.set_active(True)
            custom_name.set_text(design_name.get_text().strip()[:MAX_ITEM_LENGTH])
            page_counts = {"left": 0, "right": 0}
            custom_modules.clear()
            for index, item in enumerate(rows):
                custom_modules.append({"id": "setup-%d" % index,
                    "type": item["type"], "page": item["page"],
                    "order": page_counts[item["page"]]})
                page_counts[item["page"]] += 1
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
                      ("weekly", N_("Weekly")))
    for key, message in rhythm_choices:
        rhythm.append(key, tr(message))
    rhythm.set_active_id("weekly")
    dynamic_choices.append((rhythm, rhythm_choices))
    backup.pack_start(rhythm, False, False, 0)

    finish = page(
        "Everything is ready",
        N_("We hope you enjoy using Magnolie Organizer. You can change every choice later in Settings."))
    autostart = check("Start Magnolie automatically when I sign in")
    weather = check("Show weather for the next three days")
    finish.pack_start(autostart, False, False, 4)
    finish.pack_start(weather, False, False, 4)
    for capability in phone_capabilities:
        if capability.get("canAutoStart"):
            widget = check("Start required phone background services automatically")
            widget.set_no_show_all(True)
            phone_start_checks[capability["transport"]] = widget
            finish.pack_start(widget, False, False, 4)
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
        if index == 6 and phone_services and phone_results:
            set_busy(True)

            def refresh_connected(live, error):
                set_busy(False)
                for transport, widget in phone_start_checks.items():
                    result = phone_results.get(transport)
                    enabled = not error and transport in (live or []) and result and result.get("authenticated") is True
                    widget.set_visible(bool(enabled))
                    if not enabled:
                        widget.set_active(False)
                    else:
                        widget.set_label(tr("Start required phone background services automatically") + ": " + result["name"])
            background(phone_services.connected, refresh_connected)

    def refresh_text():
        refreshing_address[0] = True
        state_selected = state.get_active_id()
        if state_selected is None:
            state_selected = state.get_child().get_text()
        for widget, message, setter in localized:
            getattr(widget, setter)(tr(message))
        for combo, choices in dynamic_choices:
            selected = combo.get_active_id()
            typed = combo.get_child().get_text() if combo.get_has_entry() and selected is None else None
            combo.remove_all()
            for key, message in choices:
                combo.append(key, tr(message))
            if typed is not None:
                combo.set_active(-1)
                combo.get_child().set_text(typed)
            elif selected is not None:
                combo.set_active_id(selected)
        populate_regions(state_selected)
        refreshing_address[0] = False
        update_school_holidays()
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
        state_value = state.get_active_id()
        if state_value is None:
            state_value = state.get_child().get_text()
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
            "addressChanged": address_changed[0],
            "schoolHolidays": school_holidays.get_active() and bool(holiday_region[0]),
            "schoolHolidayRegion": holiday_region[0] if school_holidays.get_active() else "",
            "addressSort": address_sort.get_active_id() or "last-name",
            "calendarUids": connection["calendarUids"] + [account["uid"] for account, widget in account_checks
                              if widget.get_active() and account["kind"] == "calendar"],
            "addressBookUid": connection["addressBookUid"] or next((account["uid"] for account, widget in account_checks
                                    if widget.get_active() and account["kind"] == "addressbook"), ""),
            "oneTimeImports": [],
            "stagedImports": [{"source": key, "payload": value} for key, value in staged_imports.items()],
            "phoneBackgroundServices": [transport for transport, widget in phone_start_checks.items()
                                        if widget.get_visible() and widget.get_active()],
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
    connection_committed = [False]
    finished_phone_result = [None]
    while True:
        response = dialog.run()
        if response == 4:
            result = finished_phone_result[0]
            break
        if busy[0] and response in (1, 2, 3):
            continue
        if response == 1 and current > 0:
            current -= 1
            show_page(current)
            continue
        if response == 3 and current == 0:
            result = _finish_result(write_state, "skipped", _skipped_selections(language))
            break
        if response != 2:
            break
        if current < 6:
            current += 1
            show_page(current)
            continue
        if connection["token"] and commit_connection and not connection_committed[0]:
            set_busy(True)

            def committed(_result, error):
                set_busy(False)
                if error:
                    show_error("The connection settings could not be saved.")
                else:
                    connection_committed[0] = True
                    dialog.response(2)
            background(lambda: commit_connection(connection["token"]), committed)
            continue
        if phone_services:
            set_busy(True)
            chosen = selections()
            def finish_phone():
                _persist_language(chosen["language"])
                return phone_services.finish_setup(write_state, chosen)

            def phone_committed(value, error):
                set_busy(False)
                if error:
                    show_error("The background settings could not be saved.", str(error))
                else:
                    finished_phone_result[0] = value
                    dialog.response(4)
            background(finish_phone, phone_committed)
            continue
        result = _finish_result(write_state, "complete", selections())
        break
    dialog.destroy()
    return result
