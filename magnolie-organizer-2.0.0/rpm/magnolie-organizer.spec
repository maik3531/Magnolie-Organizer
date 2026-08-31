%global magnolie_distro @MAGNOLIE_DISTRO@

%if "%{magnolie_distro}" == "fedora"
%global magnolie_deps gtk3 python3-gobject python3-cryptography python3-pyOpenSSL python3-qrcode python3-zeroconf webkit2gtk4.1 libnotify
%global magnolie_build_deps python3-pytest
%else
%if "%{magnolie_distro}" == "opensuse"
%global magnolie_deps gtk3 python3-gobject python3-gobject-Gdk python3-cryptography python3-pyOpenSSL python3-qrcode python3-zeroconf typelib-1_0-WebKit2-4_1 typelib-1_0-Notify-0_7
%global magnolie_build_deps python3-pytest
%else
%if "%{magnolie_distro}" == "mageia"
%global magnolie_deps gtk+3.0 python3-gobject python3-cryptography python3-openssl python3-qrcode python3-zeroconf webkit2gtk4.1 %{_lib}notify-gir0.7
%global magnolie_build_deps python3-pytest
%else
%if "%{magnolie_distro}" == "openmandriva"
%global magnolie_deps gtk+3.0 python-gobject3 python-cryptography python-pyopenssl python-qrcode python-zeroconf %{_lib}webkit2gtk4.1_0 %{_lib}webkit2gtk-gir4.1 %{_lib}notify-gir0.7
%global magnolie_build_deps python-pytest
%else
%if "%{magnolie_distro}" == "pclinuxos"
%global magnolie_deps gtk+3.0 python3-gobject python3-cryptography python3-openssl python3-qrcode python3-zeroconf webkit2gtk4.1 %{_lib}notify-gir0.7
%global magnolie_build_deps python3-pytest
%else
%if "%{magnolie_distro}" == "rosa"
%global magnolie_deps gtk+3.0 python3-gobject python3-cryptography python3-OpenSSL python3-qrcode python3-zeroconf webkit2gtk4.1 %{_lib}webkit2-gir4.1 %{_lib}notify-gir0.7
%global magnolie_build_deps python3-pytest
%else
%{error:Unpinned or unsupported Magnolie RPM distro profile}
%endif
%endif
%endif
%endif
%endif
%endif

Name:           magnolie-organizer
Version:        2.0.14
Release:        1%{?dist}
Summary:        Personal organizer with a classic paper appearance

License:        GPL-3.0-or-later AND CC0-1.0 AND LicenseRef-Magnolie-protected-assets
URL:            https://gitlab.com/maik3531/mint-forgs
Source0:        %{name}-%{version}.tar.xz
BuildArch:      noarch
Provides:       magnolie-rpm-profile(%{magnolie_distro}) = %{version}-%{release}

BuildRequires:  /usr/bin/appstreamcli
BuildRequires:  /usr/bin/desktop-file-validate
BuildRequires:  /usr/bin/msgfmt
BuildRequires:  /usr/bin/node
BuildRequires:  /usr/bin/python3
BuildRequires:  %{magnolie_build_deps}
BuildRequires:  %{magnolie_deps}
Requires:       /usr/bin/python3
Requires:       %{magnolie_deps}

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
    /usr/bin/python3 werkzeuge/po_zu_js.py \
        "$language" "po/$language.po" "web/i18n/$language.js"
done < po/LINGUAS
/usr/bin/python3 werkzeuge/klang.py klang/erinnerung.wav

%check
set -eu
/usr/bin/python3 -m py_compile bin/%{name} bin/magnolie_telefon.py bin/magnolie_kdeconnect.py bin/magnolie_hintergrund.py bin/magnolie_personal_sync.py bin/magnolie_nextcloud.py bin/magnolie_cloud_backup.py bin/magnolie_crash.py bin/magnolie_asset.py werkzeuge/*.py pruefungen/*.py
while read -r language; do
    test -n "$language" || continue
    /usr/bin/python3 werkzeuge/katalog_pruefen.py \
        po/magnolie-organizer.pot "po/$language.po"
    test -s "locale/$language/LC_MESSAGES/%{name}.mo"
    test -s "web/i18n/$language.js"
done < po/LINGUAS
/usr/bin/python3 -m pytest -q pruefungen/test_locale_completeness.py
test "$(wc -l < po/LINGUAS)" -eq 19
test "$(find locale -name '%{name}.mo' -type f | wc -l)" -eq 19
test "$(find web/i18n -name '*.js' -type f | wc -l)" -eq 19
test -s klang/erinnerung.wav

test_root="$(pwd)/.rpm-check"
rm -rf "$test_root"
mkdir -p "$test_root/data" "$test_root/config" "$test_root/cache"
trap 'rm -rf "$test_root"' EXIT
export DISPLAY= WAYLAND_DISPLAY= TZ=Europe/Berlin
export XDG_DATA_HOME="$test_root/data" XDG_CONFIG_HOME="$test_root/config"
export XDG_CACHE_HOME="$test_root/cache"
/usr/bin/python3 pruefungen/test_parser.py
/usr/bin/python3 pruefungen/test_import_export_vertrag.py
/usr/bin/python3 pruefungen/test_gesamtarchiv.py
/usr/bin/python3 pruefungen/test_telefon.py
/usr/bin/python3 -m pytest -q pruefungen/test_kdeconnect.py
/usr/bin/python3 -m pytest -q pruefungen/test_eds_adressbuch_sync.py
/usr/bin/python3 pruefungen/test_wiederherstellungsjournal.py
/usr/bin/python3 pruefungen/test_paketinhalt.py
/usr/bin/python3 -m pytest -q pruefungen/test_personal_sync.py
/usr/bin/python3 -m pytest -q pruefungen/test_nextcloud.py
/usr/bin/python3 -m pytest -q pruefungen/test_crash_reports.py
/usr/bin/python3 -m pytest -q pruefungen/test_hintergrunddienst.py
/usr/bin/python3 pruefungen/test_asset_container.py

desktop-file-validate io.gitlab.maik3531.MagnolieOrganizer.desktop
appstreamcli validate --no-net \
    io.gitlab.maik3531.MagnolieOrganizer.appdata.xml

for script in web/*.js web/i18n/*.js; do
    node --check "$script"
done

%install
install -Dpm 0755 bin/%{name} %{buildroot}%{_bindir}/%{name}
install -Dpm 0644 bin/magnolie_telefon.py %{buildroot}%{_bindir}/magnolie_telefon.py
install -Dpm 0644 bin/magnolie_kdeconnect.py %{buildroot}%{_bindir}/magnolie_kdeconnect.py
install -Dpm 0644 bin/magnolie_hintergrund.py %{buildroot}%{_bindir}/magnolie_hintergrund.py
install -Dpm 0644 bin/magnolie_personal_sync.py %{buildroot}%{_bindir}/magnolie_personal_sync.py
install -Dpm 0644 bin/magnolie_nextcloud.py %{buildroot}%{_bindir}/magnolie_nextcloud.py
install -Dpm 0644 bin/magnolie_cloud_backup.py %{buildroot}%{_bindir}/magnolie_cloud_backup.py
install -Dpm 0644 bin/magnolie_crash.py %{buildroot}%{_bindir}/magnolie_crash.py
install -Dpm 0644 bin/magnolie_asset.py %{buildroot}%{_bindir}/magnolie_asset.py

install -d %{buildroot}%{_datadir}/%{name}/web/i18n
install -pm 0644 web/index.html web/stil.css web/anwendung.js \
    web/i18n.js web/i18n-start.js web/i18n-markers.js \
    web/i18n-en.js \
    %{buildroot}%{_datadir}/%{name}/web/
install -pm 0644 web/kaffee-qr.mga \
    %{buildroot}%{_datadir}/%{name}/web/kaffee-qr.mga
install -pm 0644 web/i18n/*.js %{buildroot}%{_datadir}/%{name}/web/i18n/
hash="${MAGNOLIE_CONTRIBUTOR_HASH:-}"
if test -n "$hash"; then
    test "${#hash}" -eq 64 || { echo 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2; exit 2; }
    case "$hash" in *[!0-9a-fA-F]*) echo 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2; exit 2;; esac
    hash=$(printf '%s' "$hash" | tr A-F a-f)
    printf '{"contributorHash":"%s"}\n' "$hash" > \
        %{buildroot}%{_datadir}/%{name}/build-config.json
fi
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

# %check runs before %install. Validate the installed product here while the
# buildroot exists, without starting the graphical application.
test -x %{buildroot}%{_bindir}/%{name}
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import ast
import pathlib
import sys

root = pathlib.Path(r"%{buildroot}")
bindir = root / "usr/bin"
for name in ("magnolie-organizer", "magnolie_telefon.py",
              "magnolie_kdeconnect.py", "magnolie_hintergrund.py", "magnolie_personal_sync.py",
              "magnolie_nextcloud.py", "magnolie_cloud_backup.py"):
    ast.parse((bindir / name).read_text(encoding="utf-8"), filename=name)
sys.path.insert(0, str(bindir))
import magnolie_personal_sync
import magnolie_nextcloud
import magnolie_cloud_backup
import magnolie_telefon
assert pathlib.Path(magnolie_personal_sync.__file__) == bindir / "magnolie_personal_sync.py"
assert magnolie_telefon.validate_personal_sync_body is magnolie_personal_sync.validate_body
PY
test -s %{buildroot}%{_datadir}/%{name}/web/kaffee-qr.mga
for path in \
    %{buildroot}%{_datadir}/%{name}/web/index.html \
    %{buildroot}%{_datadir}/%{name}/web/anwendung.js \
    %{buildroot}%{_datadir}/%{name}/web/i18n/de.js \
    %{buildroot}%{_datadir}/%{name}/klang/erinnerung.wav \
    %{buildroot}%{_datadir}/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop \
    %{buildroot}%{_datadir}/metainfo/io.gitlab.maik3531.MagnolieOrganizer.metainfo.xml \
    %{buildroot}%{_prefix}/lib/firewalld/services/magnolie-organizer.xml \
    %{buildroot}%{_mandir}/man1/magnolie-organizer.1; do
    test -s "$path"
done

%files -f %{name}.lang
%license debian/copyright PROTECTED-ASSETS-LICENSE.txt
%doc LIESMICH.md INTERNATIONALISIERUNG.md
%{_bindir}/%{name}
%{_bindir}/magnolie_telefon.py
%{_bindir}/magnolie_kdeconnect.py
%{_bindir}/magnolie_hintergrund.py
%{_bindir}/magnolie_personal_sync.py
%{_bindir}/magnolie_nextcloud.py
%{_bindir}/magnolie_cloud_backup.py
%{_bindir}/magnolie_crash.py
%{_bindir}/magnolie_asset.py
%{_datadir}/%{name}/
%{_datadir}/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop
%{_datadir}/metainfo/io.gitlab.maik3531.MagnolieOrganizer.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/magnolie-organizer.*
%{_prefix}/lib/firewalld/services/magnolie-organizer.xml
%{_mandir}/man1/magnolie-organizer.1*
%{_mandir}/*/man1/magnolie-organizer.1*

%changelog
* Mon Aug 31 2026 Maik Walter <maik3531@gmail.com> - 2.0.14-1
- Protect personal assets and harden package and VM release validation.
- Add localized CLI aliases and isolated distribution profiles.

* Sun Aug 30 2026 Maik Walter <maik3531@gmail.com> - 2.0.13-1
- Correct notebook line alignment under system font scaling.
- Improve background-service notifications and harden synchronization.

* Sat Aug 29 2026 Maik Walter <maik3531@gmail.com> - 2.0.11-1
- Improve background-service controls, symlink startup and reminder scheduling.
- Harden Debian/RPM packaging and the real 2.0.10 upgrade gate.

* Sat Aug 29 2026 Maik Walter <maik3531@gmail.com> - 2.0.10-1
- Behebt den Paketdateikonflikt mit dem Handbuch-Absturzmelder.

* Sat Aug 29 2026 Maik Walter <maik3531@gmail.com> - 2.0.9-1
- Add the optional secure background service and local crash reporting.
- Correct calendar, contact and Android connected-device service handling.
- Improve AppImage compatibility and complete translations and handbook.

* Thu Aug 27 2026 Maik Walter <maik3531@gmail.com> - 2.0.8-1
- Harden Thunderbird imports, settings and KDE Connect receive folders.
- Add safe Android call proximity and service lifecycle handling.

* Thu Aug 27 2026 Maik Walter <maik3531@gmail.com> - 2.0.7-1
- Add independent hands-free selection and secure opt-in KDE Connect reception.
- Extend phone status with the backward-compatible Magnolie Notes version.

* Wed Aug 26 2026 Maik Walter <maik3531@gmail.com> - 2.0.6-1
- Store unknown-year birthdays and anniversaries without a placeholder year.
- Preserve genuine 1604, 1900 and 2000 dates and lossless vCard/ICS round trips.
- Keep restored Google birthday calendar imports working.

* Wed Aug 26 2026 Maik Walter <maik3531@gmail.com> - 2.0.5-1
- Add secure QR pairing and harden cross-platform phone communication.
- Preserve complex sync data and strengthen recovery and release checks.

* Mon Aug 24 2026 Maik Walter <maik3531@gmail.com> - 2.0.4-1
- Restore WebKit compositing, page-turn animation and responsive startup
- Run the AppImage through XWayland while retaining the GLIBC 2.35 ceiling
- Keep automatic locale selection without the visible Language & region tab
- Deduplicate matching recurring all-day EDS and ICS events with clearer labels

* Mon Aug 24 2026 Maik Walter <maik3531@gmail.com> - 2.0.3-1
- Keep PulseAudio and PipeWire integrations optional and conflict-free
- Disable affected WebKitGTK accelerated rendering paths by default
- Add a sandboxed GNOME 49 Flatpak build

* Sat Aug 22 2026 Maik Walter <maik3531@gmail.com> - 2.0.2-1
- Load only the active language catalog during startup
- Build against a pinned native Fedora 42 environment
- Verify portable AppImage runtime compatibility on Arch Linux

* Fri Aug 21 2026 Maik Walter <maik3531@gmail.com> - 2.0.1-1
- Scale startup normalization linearly for large data sets
- Add visible search navigation and a bundled cross-platform handwriting font
- Extend startup timing diagnostics

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
