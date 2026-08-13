Name:           magnolie-organizer
Version:        2.0.0
Release:        1%{?dist}
Summary:        Personal organizer with a classic paper appearance

License:        GPL-3.0-or-later AND CC0-1.0
URL:            https://gitlab.com/maik3531/mint-forgs
Source0:        %{name}-%{version}.tar.xz
BuildArch:      noarch

BuildRequires:  appstream
BuildRequires:  desktop-file-utils
BuildRequires:  gettext
BuildRequires:  python3-cryptography
BuildRequires:  python3-devel
BuildRequires:  python3-zeroconf
Requires:       gtk3
Requires:       gettext
Requires:       python3
Requires:       python3-cryptography
Requires:       python3-gobject
Requires:       python3-zeroconf
Requires:       webkit2gtk4.1
Recommends:     evolution-data-server
Recommends:     bluez
Recommends:     firewalld
Recommends:     libcanberra-gtk3
Recommends:     libnotify
Recommends:     python3-enchant
Recommends:     xdg-utils
Suggests:       gnome-shell-extension-appindicator
Suggests:       hunspell-de
Suggests:       hunspell-en-US
Suggests:       libappindicator-gtk3
Suggests:       xapps

%description
Magnolie Organizer combines a calendar, contacts, tasks, notes,
anniversaries, and printable planners in an interface styled like a classic
paper organizer. Data is stored locally. Optional Evolution Data Server
integration and encrypted Magnolienbaum sharing are available.

%prep
%autosetup

%build
set -eu
while read -r language; do
    test -n "$language" || continue
    mkdir -p "locale/$language/LC_MESSAGES" web/i18n
    msgfmt --check --check-format \
        -o "locale/$language/LC_MESSAGES/%{name}.mo" "po/$language.po"
    %{python3} werkzeuge/po_zu_js.py \
        "$language" "po/$language.po" "web/i18n/$language.js"
done < po/LINGUAS
%{python3} werkzeuge/klang.py klang/erinnerung.wav

%check
set -eu
%{python3} -m py_compile bin/%{name} bin/magnolie_telefon.py werkzeuge/*.py pruefungen/*.py
while read -r language; do
    test -n "$language" || continue
    %{python3} werkzeuge/katalog_pruefen.py \
        po/magnolie-organizer.pot "po/$language.po"
    test -s "locale/$language/LC_MESSAGES/%{name}.mo"
    test -s "web/i18n/$language.js"
done < po/LINGUAS
test "$(wc -l < po/LINGUAS)" -eq 19
test "$(find locale -name '%{name}.mo' -type f | wc -l)" -eq 19
test "$(find web/i18n -name '*.js' -type f | wc -l)" -eq 19
test -s klang/erinnerung.wav

test_root="$(pwd)/.rpm-check"
rm -rf "$test_root"
mkdir -p "$test_root/data" "$test_root/config" "$test_root/cache"
trap 'rm -rf "$test_root"' EXIT
DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin \
XDG_DATA_HOME="$test_root/data" XDG_CONFIG_HOME="$test_root/config" \
XDG_CACHE_HOME="$test_root/cache" \
    %{python3} pruefungen/test_parser.py
DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin \
XDG_DATA_HOME="$test_root/data" XDG_CONFIG_HOME="$test_root/config" \
XDG_CACHE_HOME="$test_root/cache" \
    %{python3} pruefungen/test_import_export_vertrag.py
    %{python3} pruefungen/test_gesamtarchiv.py
    %{python3} pruefungen/test_paketinhalt.py

desktop-file-validate io.gitlab.maik3531.MagnolieOrganizer.desktop
appstreamcli validate --no-net \
    io.gitlab.maik3531.MagnolieOrganizer.appdata.xml

if command -v node >/dev/null 2>&1 && \
        node -e 'require("jsdom")' >/dev/null 2>&1; then
    TZ=Europe/Berlin node pruefungen/test.js
else
    echo 'jsdom ist nicht vorhanden; DOM-Test wird ausgelassen.'
fi

%install
install -Dpm 0755 bin/%{name} %{buildroot}%{_bindir}/%{name}
install -Dpm 0644 bin/magnolie_telefon.py %{buildroot}%{_bindir}/magnolie_telefon.py

install -d %{buildroot}%{_datadir}/%{name}/web/i18n
install -pm 0644 web/index.html web/stil.css web/anwendung.js \
    web/i18n.js web/i18n-start.js web/i18n-markers.js \
    %{buildroot}%{_datadir}/%{name}/web/
install -pm 0644 web/i18n/*.js %{buildroot}%{_datadir}/%{name}/web/i18n/
%if "%{?magnolie_contributor_hash}" != ""
printf '{"contributorHash":"%s"}\n' "%{magnolie_contributor_hash}" > \
    %{buildroot}%{_datadir}/%{name}/build-config.json
%endif
install -Dpm 0644 werkzeuge/pot_erzeugen.py \
    %{buildroot}%{_datadir}/%{name}/werkzeuge/pot_erzeugen.py
install -Dpm 0644 klang/erinnerung.wav \
    %{buildroot}%{_datadir}/%{name}/klang/erinnerung.wav

while read -r language; do
    test -n "$language" || continue
    install -Dpm 0644 "locale/$language/LC_MESSAGES/%{name}.mo" \
        "%{buildroot}%{_datadir}/locale/$language/LC_MESSAGES/%{name}.mo"
done < po/LINGUAS

install -Dpm 0644 io.gitlab.maik3531.MagnolieOrganizer.desktop \
    %{buildroot}%{_datadir}/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop
install -Dpm 0644 io.gitlab.maik3531.MagnolieOrganizer.appdata.xml \
    %{buildroot}%{_datadir}/metainfo/io.gitlab.maik3531.MagnolieOrganizer.metainfo.xml
install -Dpm 0644 symbole/magnolie-organizer.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/magnolie-organizer.svg
for size in 48 64 128 256; do
    install -Dpm 0644 "symbole/${size}x${size}/magnolie-organizer.png" \
        "%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/magnolie-organizer.png"
done
install -Dpm 0644 rpm/magnolie-organizer.xml \
    %{buildroot}%{_prefix}/lib/firewalld/services/magnolie-organizer.xml
install -Dpm 0644 man/magnolie-organizer.1 \
    %{buildroot}%{_mandir}/man1/magnolie-organizer.1
while read -r language; do
    test -n "$language" || continue
    test ! -f "man/$language/magnolie-organizer.1" || \
        install -Dpm 0644 "man/$language/magnolie-organizer.1" \
            "%{buildroot}%{_mandir}/$language/man1/magnolie-organizer.1"
done < po/LINGUAS

%find_lang %{name}

%files -f %{name}.lang
%license debian/copyright
%doc LIESMICH.md INTERNATIONALISIERUNG.md
%{_bindir}/%{name}
%{_bindir}/magnolie_telefon.py
%{_datadir}/%{name}/
%{_datadir}/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop
%{_datadir}/metainfo/io.gitlab.maik3531.MagnolieOrganizer.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/magnolie-organizer.*
%{_prefix}/lib/firewalld/services/magnolie-organizer.xml
%{_mandir}/man1/magnolie-organizer.1*
%{_mandir}/*/man1/magnolie-organizer.1*

%changelog
* Wed Aug 12 2026 Maik Walter <maik3531@gmail.com> - 2.0.0-1
- Align all desktop packages and handbooks on version 2.0.0
- Exclude internal working notes from source packages

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.95-1
- Align the compact shared-note status without increasing editor height

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.94-1
- Place the shared-note status below the unchanged toolbar controls

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.93-1
- Align all health notices on the left in the neutral reference style

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.92-1
- Add subtle health reference colors and reposition the medical notice

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.91-1
- Add trusted full synchronization and direct remote partner endpoints

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.90-1
- Restore page-filling medication rows and verify their full-page geometry

* Tue Aug 11 2026 Maik Walter <maik3531@gmail.com> - 1.31.89-1
- Restore the full-width health layout and add real ODS history charts

* Mon Aug 10 2026 Maik Walter <maik3531@gmail.com> - 1.31.88-1
- Add initial Fedora package
