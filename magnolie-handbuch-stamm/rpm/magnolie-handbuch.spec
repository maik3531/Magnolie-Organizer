Name:           magnolie-handbuch
Version:        2.0.6
Release:        1%{?dist}
Summary:        Illustrated user handbook for Magnolie Organizer

License:        GPL-3.0-or-later AND OFL-1.1 AND LicenseRef-Bitstream-Vera AND LicenseRef-Magnolie-photo-permission
URL:            https://github.com/maik3531/Magnolie-Organizer
Source0:        %{name}-%{version}.tar.xz
BuildArch:      noarch

BuildRequires:  desktop-file-utils
BuildRequires:  gettext
BuildRequires:  nodejs
BuildRequires:  python3-devel
Requires:       gettext
Requires:       gtk3
Requires:       python3
Requires:       python3-gobject
Requires:       webkit2gtk4.1
Recommends:     magnolie-organizer >= 2.0.0

%description
Magnolie Handbook is the illustrated, searchable and printable user guide for
Magnolie Organizer. It includes nineteen translated editions and can also be
used independently from the organizer package.

%prep
%autosetup

%build
set -eu
while read -r language; do
    test -n "$language" || continue
    mkdir -p "locale/$language/LC_MESSAGES" web/i18n
    %{python3} werkzeuge/katalog_pruefen.py \
        po/magnolie-handbuch.pot "po/$language.po"
    msgfmt --check --check-format \
        -o "locale/$language/LC_MESSAGES/%{name}.mo" "po/$language.po"
    %{python3} werkzeuge/po_zu_js.py \
        "$language" "po/$language.po" "web/i18n/$language.js"
done < po/LINGUAS

%check
set -eu
%{python3} -m py_compile bin/%{name} werkzeuge/*.py pruefungen/*.py
test "$(find locale -name '%{name}.mo' -type f | wc -l)" -eq 19
test "$(find web/i18n -name '*.js' -type f | wc -l)" -eq 19
for script in web/*.js web/i18n/*.js; do
    node --check "$script"
done
%{python3} pruefungen/druck_test.py --cli-only
desktop-file-validate magnolie-handbuch.desktop

%install
install -Dpm 0755 bin/%{name} %{buildroot}%{_bindir}/%{name}
install -d %{buildroot}%{_datadir}/%{name}/web/i18n
install -pm 0644 web/index.html web/stil.css web/inhalt.js web/platform.js web/handbuch.js \
    web/i18n.js web/i18n-start.js web/i18n-markers.js \
    web/*.png web/*.jpg web/maik-walter-FOTO-NUTZUNG.txt \
    %{buildroot}%{_datadir}/%{name}/web/
cp -a web/schriften %{buildroot}%{_datadir}/%{name}/web/
install -pm 0644 web/i18n/*.js %{buildroot}%{_datadir}/%{name}/web/i18n/
install -Dpm 0644 werkzeuge/pot_erzeugen.py \
    %{buildroot}%{_datadir}/%{name}/werkzeuge/pot_erzeugen.py
while read -r language; do
    test -n "$language" || continue
    install -Dpm 0644 "locale/$language/LC_MESSAGES/%{name}.mo" \
        "%{buildroot}%{_datadir}/locale/$language/LC_MESSAGES/%{name}.mo"
done < po/LINGUAS
install -Dpm 0644 magnolie-handbuch.desktop \
    %{buildroot}%{_datadir}/applications/magnolie-handbuch.desktop
install -Dpm 0644 symbole/magnolie-handbuch.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/magnolie-handbuch.svg
for size in 48 64 128 256; do
    install -Dpm 0644 "symbole/${size}x${size}/magnolie-handbuch.png" \
        "%{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/magnolie-handbuch.png"
done
install -Dpm 0644 man/magnolie-handbuch.1 \
    %{buildroot}%{_mandir}/man1/magnolie-handbuch.1
while read -r language; do
    test ! -f "man/$language/magnolie-handbuch.1" || \
        install -Dpm 0644 "man/$language/magnolie-handbuch.1" \
            "%{buildroot}%{_mandir}/$language/man1/magnolie-handbuch.1"
done < po/LINGUAS
%find_lang %{name}

%files -f %{name}.lang
%license debian/copyright web/maik-walter-FOTO-NUTZUNG.txt
%doc LIESMICH.md
%{_bindir}/%{name}
%{_datadir}/%{name}/
%{_datadir}/applications/magnolie-handbuch.desktop
%{_datadir}/icons/hicolor/*/apps/magnolie-handbuch.*
%{_mandir}/man1/magnolie-handbuch.1*
%{_mandir}/*/man1/magnolie-handbuch.1*

%changelog
* Wed Aug 26 2026 Maik Walter <maik3531@gmail.com> - 2.0.6-1
- Update the complete multilingual handbook and platform copies for Organizer 2.0.6.

* Wed Aug 26 2026 Maik Walter <maik3531@gmail.com> - 2.0.5-1
- Update the complete multilingual handbook for Magnolie Organizer 2.0.5.
- Add standalone localized Windows handbook variants.

* Mon Aug 24 2026 Maik Walter <maik3531@gmail.com> - 2.0.4-1
- Ship the complete handbook for Organizer 2.0.4
- Update all localized package examples, catalogs and platform copies

* Mon Aug 24 2026 Maik Walter <maik3531@gmail.com> - 2.0.3-1
- Ship the complete 154-page handbook for Organizer 2.0.3
- Update all localized package examples and platform copies

* Sat Aug 22 2026 Maik Walter <maik3531@gmail.com> - 2.0.2-1
- Keep resizing responsive while repaginating the handbook
- Build and verify the handbook as an independent Fedora package

* Fri Aug 21 2026 Maik Walter <maik3531@gmail.com> - 2.0.1-1
- Package the illustrated handbook separately for Fedora
