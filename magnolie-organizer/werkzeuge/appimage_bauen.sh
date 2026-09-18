#!/bin/sh
set -eu
umask 022

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
ARCH=$(uname -m)
MULTIARCH=$(gcc -dumpmachine)
PYTHON_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
AUSGABE=${1:-"$WURZEL/../Magnolie-Organizer-$FASSUNG-$ARCH.AppImage"}
ARBEIT=${APPIMAGE_BUILD_DIR:-"$WURZEL/bau/appimage"}
WERKZEUGE=${APPIMAGE_TOOL_DIR:-"$WURZEL/bau/appimage-werkzeuge"}
APPDIR="$ARBEIT/Magnolie-Organizer.AppDir"

CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
if [ -n "$CONTRIBUTOR_HASH" ]; then
    [ "${#CONTRIBUTOR_HASH}" -eq 64 ] || {
        printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2
        exit 2
    }
    case "$CONTRIBUTOR_HASH" in
        *[!0-9a-fA-F]*)
            printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH ist ungueltig.' >&2
            exit 2 ;;
    esac
    CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)
fi

if [ "$ARCH" != "x86_64" ]; then
    printf '%s\n' "Der AppImage-Bau ist derzeit fuer x86_64 festgeschrieben." >&2
    exit 1
fi

LINUXDEPLOY_URL=https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage
LINUXDEPLOY_SHA=c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA=a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0
PHONENUMBERS_URL=https://files.pythonhosted.org/packages/b2/09/6df2574777489592b37e6b9cda72962709af2e121b122bf6aae19bcce7b4/phonenumbers-9.0.38-py2.py3-none-any.whl
PHONENUMBERS_SHA=f3cbeb1a42bf226060c60fc6277f5431755d325eddc23fbf2c72ef7e156113c6
LINUXDEPLOY="$WERKZEUGE/linuxdeploy-x86_64.AppImage"
APPIMAGETOOL="$WERKZEUGE/appimagetool-x86_64.AppImage"
PHONENUMBERS_WHEEL="$WERKZEUGE/phonenumbers-9.0.38-py2.py3-none-any.whl"

holen() {
    ziel=$1
    url=$2
    summe=$3
    if [ ! -f "$ziel" ] || [ "$(sha256sum "$ziel" | cut -d' ' -f1)" != "$summe" ]; then
        rm -f "$ziel"
        curl -L --fail --retry 3 -o "$ziel" "$url"
    fi
    printf '%s  %s\n' "$summe" "$ziel" | sha256sum -c -
    chmod 0755 "$ziel"
}

for befehl in curl cut dpkg-parsechangelog g-ir-inspect gcc gio-querymodules \
    ldd msgfmt nm python3 readelf sha256sum; do
    command -v "$befehl" >/dev/null || {
        printf '%s\n' "Fehlendes Bauwerkzeug: $befehl" >&2
        exit 1
    }
done

if [ -f "/usr/lib/$MULTIARCH/libecal-2.0.so.3" ]; then
    ECAL_SONAME=libecal-2.0.so.3
    EBOOK_SONAME=libebook-1.2.so.21
    EDS_SONAMES="libecal-2.0.so.3 libedataserver-1.2.so.27 libical-glib.so.3 libical.so.3 libcamel-1.2.so.64 libebook-1.2.so.21 libebook-contacts-1.2.so.4 libedata-book-1.2.so.27 libebackend-1.2.so.11"
elif [ -f "/usr/lib/$MULTIARCH/libecal-2.0.so.1" ]; then
    ECAL_SONAME=libecal-2.0.so.1
    EBOOK_SONAME=libebook-1.2.so.20
    EDS_SONAMES="libecal-2.0.so.1 libedataserver-1.2.so.26 libical-glib.so.3 libical.so.3 libcamel-1.2.so.63 libebook-1.2.so.20 libebook-contacts-1.2.so.3 libedata-book-1.2.so.26 libebackend-1.2.so.10"
else
    printf '%s\n' 'Keine unterstuetzte EDS-ABI fuer das AppImage gefunden.' >&2
    exit 1
fi
EDS_BIBLIOTHEKEN=""
for soname in $EDS_SONAMES; do
    EDS_BIBLIOTHEKEN="$EDS_BIBLIOTHEKEN /usr/lib/$MULTIARCH/$soname"
done
EDS_TYPELIBS="Camel-1.2 EDataServer-1.2 ECal-2.0 ICalGLib-3.0 EBookContacts-1.2 EBook-1.2"
APP_TYPELIBS="
GLib-2.0 GObject-2.0 Gio-2.0 GModule-2.0
cairo-1.0 freetype2-2.0 xlib-2.0 HarfBuzz-0.0
Atk-1.0 GdkPixbuf-2.0 Pango-1.0 Gdk-3.0 Gtk-3.0
    JavaScriptCore-4.1 Soup-2.4 Soup-3.0 Json-1.0 libxml2-2.0 WebKit2-4.1
Gst-1.0 AyatanaAppIndicator3-0.1 AppIndicator3-0.1 XApp-1.0 Notify-0.7
    GData-0.0 Goa-1.0 $EDS_TYPELIBS
"

for bibliothek in $EDS_BIBLIOTHEKEN; do
    [ -f "$bibliothek" ] || {
        printf '%s\n' "Fehlende AppImage-Bauvoraussetzung: $bibliothek" >&2
        printf '%s\n' "EDS, Camel und libical muessen aus demselben Buildsystem installiert sein." >&2
        exit 1
    }
done
for typelib in $APP_TYPELIBS; do
    [ -f "/usr/lib/$MULTIARCH/girepository-1.0/$typelib.typelib" ] || {
        # Desktop-Zusatzmodule bleiben optional; die Kern- und EDS-Typelibs nicht.
        case "$typelib" in
            AyatanaAppIndicator3-0.1|AppIndicator3-0.1|XApp-1.0|GData-0.0|Goa-1.0) continue ;;
        esac
        printf '%s\n' "Fehlende AppImage-Bauvoraussetzung: $typelib.typelib" >&2
        exit 1
    }
done
nm -D --defined-only /usr/lib/$MULTIARCH/libical-glib.so.3 | \
    grep -q ' i_cal_component_as_ical_string$' || {
        printf '%s\n' "libical-glib.so.3 exportiert i_cal_component_as_ical_string nicht." >&2
        exit 1
    }
nm -D --undefined-only "/usr/lib/$MULTIARCH/$ECAL_SONAME" | \
    grep -q ' i_cal_component_as_ical_string$' || {
        printf '%s\n' "libecal-2.0.so.3 erwartet nicht die gepruefte libical-glib-ABI." >&2
        exit 1
    }

mkdir -p "$WERKZEUGE" "$ARBEIT"
holen "$LINUXDEPLOY" "$LINUXDEPLOY_URL" "$LINUXDEPLOY_SHA"
holen "$APPIMAGETOOL" "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" \
    "$APPDIR/usr/lib/python3/dist-packages" \
    "$APPDIR/usr/lib/$MULTIARCH/girepository-1.0" \
    "$APPDIR/usr/lib/$MULTIARCH/gio/modules" \
    "$APPDIR/usr/lib/$MULTIARCH/gstreamer-1.0" \
    "$APPDIR/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0" \
    "$APPDIR/usr/share/magnolie-organizer/web/i18n" \
    "$APPDIR/usr/share/magnolie-organizer/klang" \
    "$APPDIR/usr/share/magnolie-organizer/certs" \
    "$APPDIR/usr/share/magnolie-organizer/fontconfig" \
    "$APPDIR/usr/share/magnolie-organizer/werkzeuge" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/doc/magnolie-organizer" \
    "$APPDIR/usr/share/metainfo" \
    "$APPDIR/usr/share/magnolie-organizer/openssl" \
    "$APPDIR/usr/lib/$MULTIARCH/ossl-modules"

python3 "$WURZEL/werkzeuge/klang.py" "$ARBEIT/erinnerung.wav"
while read -r sprache; do
    mkdir -p "$APPDIR/usr/share/locale/$sprache/LC_MESSAGES"
    msgfmt --check --check-format -o "$ARBEIT/$sprache.mo" "$WURZEL/po/$sprache.po"
    python3 "$WURZEL/werkzeuge/po_zu_js.py" "$sprache" \
        "$WURZEL/po/$sprache.po" "$ARBEIT/$sprache.js"
done < "$WURZEL/po/LINGUAS"

install -m 0755 "$WURZEL/bin/magnolie-organizer" "$APPDIR/usr/bin/magnolie-organizer"
install -m 0644 "$WURZEL/bin/magnolie_asset.py" "$APPDIR/usr/bin/magnolie_asset.py"
install -m 0644 "$WURZEL/bin/magnolie_telefon.py" "$APPDIR/usr/bin/magnolie_telefon.py"
install -m 0644 "$WURZEL/bin/magnolie_anruf_audio.py" "$APPDIR/usr/bin/magnolie_anruf_audio.py"
install -m 0644 "$WURZEL/bin/magnolie_phone_region.py" "$APPDIR/usr/bin/magnolie_phone_region.py"
install -m 0644 "$WURZEL/bin/magnolie_recurrence.py" "$APPDIR/usr/bin/magnolie_recurrence.py"
install -m 0644 "$WURZEL/bin/magnolie_kdeconnect.py" "$APPDIR/usr/bin/magnolie_kdeconnect.py"
install -m 0644 "$WURZEL/bin/magnolie_hintergrund.py" "$APPDIR/usr/bin/magnolie_hintergrund.py"
install -m 0644 "$WURZEL/bin/magnolie_personal_sync.py" "$APPDIR/usr/bin/magnolie_personal_sync.py"
install -m 0644 "$WURZEL/bin/magnolie_nextcloud.py" "$APPDIR/usr/bin/magnolie_nextcloud.py"
install -m 0644 "$WURZEL/bin/magnolie_cloud_backup.py" "$APPDIR/usr/bin/magnolie_cloud_backup.py"
install -m 0644 "$WURZEL/bin/magnolie_akonadi.py" "$APPDIR/usr/bin/magnolie_akonadi.py"
install -m 0644 "$WURZEL/bin/magnolie_crash.py" "$APPDIR/usr/bin/magnolie_crash.py"
install -m 0644 "$WURZEL/bin/magnolie_setup_state.py" "$APPDIR/usr/bin/magnolie_setup_state.py"
install -m 0644 "$WURZEL/bin/magnolie_setup_ui.py" "$APPDIR/usr/bin/magnolie_setup_ui.py"
install -m 0755 "$(readlink -f "$(command -v python3)")" "$APPDIR/usr/bin/python$PYTHON_VERSION"
ln -s "python$PYTHON_VERSION" "$APPDIR/usr/bin/python3"
cp -a "/usr/lib/python$PYTHON_VERSION" "$APPDIR/usr/lib/"
find "$APPDIR/usr/lib/python$PYTHON_VERSION" -type f \( -name '*.a' -o -name '*.o' \) -delete
python3 -c 'import gi; gi.require_foreign("cairo")'
for paket in gi cairo cryptography OpenSSL zeroconf ifaddr async_timeout qrcode phonenumbers; do
    quelle="/usr/lib/python3/dist-packages/$paket"
    [ ! -e "$quelle" ] || cp -a "$quelle" "$APPDIR/usr/lib/python3/dist-packages/"
done
if [ ! -e "$APPDIR/usr/lib/python3/dist-packages/phonenumbers" ]; then
    if [ ! -f "$PHONENUMBERS_WHEEL" ] ||
            [ "$(sha256sum "$PHONENUMBERS_WHEEL" | cut -d' ' -f1)" != "$PHONENUMBERS_SHA" ]; then
        rm -f "$PHONENUMBERS_WHEEL"
        curl -L --fail --retry 3 -o "$PHONENUMBERS_WHEEL" "$PHONENUMBERS_URL"
    fi
    printf '%s  %s\n' "$PHONENUMBERS_SHA" "$PHONENUMBERS_WHEEL" | sha256sum -c -
    python3 - "$PHONENUMBERS_WHEEL" "$APPDIR/usr/lib/python3/dist-packages" \
        "$APPDIR/usr/share/doc/magnolie-organizer/phonenumbers-copyright" <<'PY'
import os
import pathlib
import sys
import zipfile

destination = pathlib.Path(sys.argv[2])
license_path = pathlib.Path(sys.argv[3])
with zipfile.ZipFile(sys.argv[1]) as archive:
    members = [member for member in archive.infolist()
               if pathlib.PurePosixPath(member.filename).parts[:1] == ("phonenumbers",)]
    licenses = [member for member in archive.infolist()
                if member.filename == "phonenumbers-9.0.38.dist-info/licenses/LICENSE"]
    if not members or len(licenses) != 1 or any(
            ".." in pathlib.PurePosixPath(member.filename).parts for member in members):
        raise SystemExit("Das phonenumbers-Wheel ist ungueltig.")
    for member in members:
        target = destination.joinpath(*pathlib.PurePosixPath(member.filename).parts)
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            os.chmod(target, 0o755)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            os.chmod(target, 0o644)
    for directory in [destination / "phonenumbers",
                      *(destination / "phonenumbers").rglob("*")]:
        if directory.is_dir():
            os.chmod(directory, 0o755)
    license_path.write_bytes(archive.read(licenses[0]))
    os.chmod(license_path, 0o644)
PY
fi
[ ! -f /usr/share/doc/python3-phonenumbers/copyright ] || install -m 0644 \
    /usr/share/doc/python3-phonenumbers/copyright \
    "$APPDIR/usr/share/doc/magnolie-organizer/phonenumbers-copyright"
[ -e "$APPDIR/usr/lib/python3/dist-packages/phonenumbers" ] || {
    printf '%s\n' 'phonenumbers konnte nicht in das AppImage kopiert werden.' >&2
    exit 1
}
for modul in /usr/lib/python3/dist-packages/_cffi_backend*.so; do
    [ ! -e "$modul" ] || cp -a "$modul" "$APPDIR/usr/lib/python3/dist-packages/"
done
[ ! -f /usr/lib/python3/dist-packages/six.py ] || \
    cp -a /usr/lib/python3/dist-packages/six.py "$APPDIR/usr/lib/python3/dist-packages/"
for typelib in $APP_TYPELIBS; do
    quelle="/usr/lib/$MULTIARCH/girepository-1.0/$typelib.typelib"
    [ ! -f "$quelle" ] || install -m 0644 "$quelle" \
        "$APPDIR/usr/lib/$MULTIARCH/girepository-1.0/$typelib.typelib"
done
[ ! -d /usr/share/glib-2.0/schemas ] || cp -a /usr/share/glib-2.0 "$APPDIR/usr/share/"
test -f /usr/share/zoneinfo/Europe/Berlin
cp -a /usr/share/zoneinfo "$APPDIR/usr/share/"
install -m 0644 /usr/share/doc/tzdata/copyright "$APPDIR/usr/share/doc/magnolie-organizer/tzdata-copyright"
[ ! -d /usr/share/themes/Adwaita ] || {
    mkdir -p "$APPDIR/usr/share/themes"
    cp -a /usr/share/themes/Adwaita "$APPDIR/usr/share/themes/"
}
[ ! -d "/usr/lib/$MULTIARCH/ossl-modules" ] || \
    cp -a "/usr/lib/$MULTIARCH/ossl-modules/." "$APPDIR/usr/lib/$MULTIARCH/ossl-modules/"
cat > "$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf" <<'EOF'
openssl_conf = openssl_init

[openssl_init]
providers = providers

[providers]
default = default_provider

[default_provider]
activate = 1
EOF
[ ! -d /usr/lib/$MULTIARCH/webkit2gtk-4.1 ] || \
    cp -a /usr/lib/$MULTIARCH/webkit2gtk-4.1 "$APPDIR/usr/lib/"

cp -a "$WURZEL/web/." "$APPDIR/usr/share/magnolie-organizer/web/"
HANDBUCH=${MAGNOLIE_HANDBUCH_SOURCE:-"$(dirname "$WURZEL")/magnolie-handbuch-stamm"}
python3 "$WURZEL/werkzeuge/appimage_handbook.py" "$APPDIR" "$HANDBUCH" "$FASSUNG"
printf '{"version":"%s"}\n' "$FASSUNG" > "$APPDIR/usr/share/magnolie-organizer/version.json"
if [ -n "$CONTRIBUTOR_HASH" ]; then
    printf '{"contributorHash":"%s"}\n' "$CONTRIBUTOR_HASH" > \
        "$APPDIR/usr/share/magnolie-organizer/build-config.json"
fi
while read -r sprache; do
    install -m 0644 "$ARBEIT/$sprache.js" \
        "$APPDIR/usr/share/magnolie-organizer/web/i18n/$sprache.js"
    install -m 0644 "$ARBEIT/$sprache.mo" \
        "$APPDIR/usr/share/locale/$sprache/LC_MESSAGES/magnolie-organizer.mo"
done < "$WURZEL/po/LINGUAS"
install -m 0644 "$ARBEIT/erinnerung.wav" \
    "$APPDIR/usr/share/magnolie-organizer/klang/erinnerung.wav"
install -m 0644 "$WURZEL/werkzeuge/pot_erzeugen.py" \
    "$APPDIR/usr/share/magnolie-organizer/werkzeuge/pot_erzeugen.py"
install -m 0644 "$WURZEL/symbole/magnolie-organizer.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/magnolie-organizer.svg"
install -m 0644 "$WURZEL/symbole/256x256/magnolie-organizer.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/magnolie-organizer.png"
install -m 0644 "$WURZEL/io.gitlab.maik3531.MagnolieOrganizer.desktop" \
    "$APPDIR/usr/share/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop"
install -m 0644 "$WURZEL/io.gitlab.maik3531.MagnolieOrganizer.appdata.xml" \
    "$APPDIR/usr/share/metainfo/io.gitlab.maik3531.MagnolieOrganizer.appdata.xml"
install -m 0644 "$WURZEL/debian/copyright" \
    "$APPDIR/usr/share/doc/magnolie-organizer/copyright"
install -m 0644 "$WURZEL/PROTECTED-ASSETS-LICENSE.txt" \
    "$APPDIR/usr/share/doc/magnolie-organizer/PROTECTED-ASSETS-LICENSE.txt"
install -m 0644 /etc/ssl/certs/ca-certificates.crt \
    "$APPDIR/usr/share/magnolie-organizer/certs/ca-certificates.crt"
install -m 0644 "$WURZEL/werkzeuge/appimage-fonts.conf" \
    "$APPDIR/usr/share/magnolie-organizer/fontconfig/fonts.conf"
install -m 0644 "$WURZEL/werkzeuge/appimage_graphics.py" \
    "$APPDIR/usr/share/magnolie-organizer/werkzeuge/appimage_graphics.py"
install -m 0644 "$WURZEL/werkzeuge/appimage_runtime.py" \
    "$APPDIR/usr/share/magnolie-organizer/werkzeuge/appimage_runtime.py"
[ ! -f "/usr/share/doc/python$PYTHON_VERSION/copyright" ] || install -m 0644 \
    "/usr/share/doc/python$PYTHON_VERSION/copyright" \
    "$APPDIR/usr/share/doc/magnolie-organizer/python-copyright"

for bibliothek in $EDS_BIBLIOTHEKEN \
    "/usr/lib/$MULTIARCH/libnotify.so.4" \
    "/usr/lib/$MULTIARCH/libexpat.so.1" \
    "/usr/lib/$MULTIARCH/libfontconfig.so.1" \
    "/usr/lib/$MULTIARCH/libfreetype.so.6" \
    "/usr/lib/$MULTIARCH/libfribidi.so.0" \
    "/usr/lib/$MULTIARCH/libgcc_s.so.1" \
    "/usr/lib/$MULTIARCH/libharfbuzz.so.0" \
    "/usr/lib/$MULTIARCH/libstdc++.so.6" \
    "/usr/lib/$MULTIARCH/libwayland-client.so.0" \
    "/usr/lib/$MULTIARCH/libX11.so.6" \
    "/usr/lib/$MULTIARCH/libxcb.so.1" \
    "/usr/lib/$MULTIARCH/libz.so.1" \
    "/usr/lib/$MULTIARCH/libxapp.so.1" \
    "/usr/lib/$MULTIARCH/libayatana-appindicator3.so.1" \
    "/usr/lib/$MULTIARCH/libappindicator3.so.1" \
    "/usr/lib/$MULTIARCH/gtk-3.0/modules/libxapp-gtk3-module.so" \
    "/usr/lib/$MULTIARCH/gio/modules/libgiognutls.so" \
    "/usr/lib/$MULTIARCH/gstreamer-1.0/libgstapp.so"; do
    [ ! -e "$bibliothek" ] || install -m 0755 "$(readlink -f "$bibliothek")" \
        "$APPDIR/usr/lib/$(basename "$bibliothek")"
done
GST_SCANNER=/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner
if [ -x "$GST_SCANNER" ]; then
    install -m 0755 "$GST_SCANNER" "$APPDIR/usr/bin/gst-plugin-scanner"
fi
install -m 0755 /usr/bin/fc-match "$APPDIR/usr/bin/fc-match"
install -m 0755 /usr/bin/xgettext "$APPDIR/usr/bin/xgettext"
install -m 0755 /usr/bin/bwrap "$APPDIR/usr/bin/bwrap"
install -m 0755 /usr/bin/xdg-dbus-proxy "$APPDIR/usr/bin/xdg-dbus-proxy"
set -- --appdir "$APPDIR" --executable "$APPDIR/usr/bin/python$PYTHON_VERSION" \
    --executable "$APPDIR/usr/bin/bwrap" --executable "$APPDIR/usr/bin/xdg-dbus-proxy" \
    --executable "$APPDIR/usr/bin/xgettext" \
    --desktop-file "$APPDIR/usr/share/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop" \
    --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/magnolie-organizer.png"
"$LINUXDEPLOY" --appimage-extract-and-run "$@"

# Typelibs und die von linuxdeploy erzeugte ELF-Closure muessen dieselbe
# EDS/libical-ABI beschreiben. Host-Fallbacks wuerden Arch mit ABI 4 brechen.
typelib_pfad="$APPDIR/usr/lib/$MULTIARCH/girepository-1.0"
[ "$(GI_TYPELIB_PATH="$typelib_pfad" g-ir-inspect --version=3.0 \
    --print-shlibs ICalGLib)" = "shlib: libical-glib.so.3" ] || {
    printf '%s\n' "ICalGLib-3.0.typelib verweist nicht auf libical-glib.so.3." >&2
    exit 1
}
[ "$(GI_TYPELIB_PATH="$typelib_pfad" g-ir-inspect --version=2.0 \
    --print-shlibs ECal)" = "shlib: $ECAL_SONAME" ] || {
    printf '%s\n' "ECal-2.0.typelib verweist nicht auf $ECAL_SONAME." >&2
    exit 1
}
for soname in $EDS_SONAMES libnotify.so.4; do
    [ -f "$APPDIR/usr/lib/$soname" ] || {
        printf '%s\n' "linuxdeploy-Closure ist unvollstaendig: $soname fehlt." >&2
        exit 1
    }
done
for bibliothek in "$APPDIR/usr/lib/$ECAL_SONAME" \
    "$APPDIR/usr/lib/$EBOOK_SONAME"; do
    if LD_LIBRARY_PATH="$APPDIR/usr/lib/$MULTIARCH:$APPDIR/usr/lib" \
        ldd "$bibliothek" | grep -q 'not found'; then
        printf '%s\n' "Nicht aufgeloeste EDS-Abhaengigkeit in $bibliothek" >&2
        exit 1
    fi
done

# WebKitGTK 4.1 contains an absolute Debian helper-process path and no longer
# honors WEBKIT_EXEC_PATH. AppRun starts in APPDIR, so this equal-length path
# remains valid regardless of the AppImage mount directory.
python3 - "$APPDIR/usr/lib/libwebkit2gtk-4.1.so.0" <<'PY'
import pathlib
import sys

pfad = pathlib.Path(sys.argv[1])
alt = b"/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1"
neu = b"/proc/self/cwd//./usr/lib/webkit2gtk-4.1"
if len(alt) != len(neu):
    raise SystemExit("Interner WebKit-Ersatzpfad hat die falsche Laenge.")
daten = pfad.read_bytes()
anzahl = daten.count(alt)
if not anzahl:
    raise SystemExit("Einkompilierter WebKit-Helferpfad wurde nicht gefunden.")
schalter = b"WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1"
hinweis = b"the explicit unsafe WebKit override".ljust(len(schalter), b" ")
if daten.count(schalter) != 1:
    raise SystemExit("WebKit-Sandbox-Hinweis wurde nicht eindeutig gefunden.")
pfad.write_bytes(daten.replace(alt, neu).replace(schalter, hinweis))
print("WebKit-Helferpfad ersetzt: %d Vorkommen" % anzahl)
PY

if [ -f "$APPDIR/usr/lib/libxapp-gtk3-module.so" ]; then
    mkdir -p "$APPDIR/usr/lib/$MULTIARCH/gtk-3.0/modules"
    cp -a "$APPDIR/usr/lib/libxapp-gtk3-module.so" \
        "$APPDIR/usr/lib/$MULTIARCH/gtk-3.0/modules/"
fi
if [ -f "$APPDIR/usr/lib/libgiognutls.so" ]; then
    cp -a "$APPDIR/usr/lib/libgiognutls.so" \
        "$APPDIR/usr/lib/$MULTIARCH/gio/modules/"
    LD_LIBRARY_PATH="$APPDIR/usr/lib/$MULTIARCH:$APPDIR/usr/lib" \
        gio-querymodules "$APPDIR/usr/lib/$MULTIARCH/gio/modules"
fi
if [ -f "$APPDIR/usr/lib/libgstapp.so" ]; then
    cp -a "$APPDIR/usr/lib/libgstapp.so" \
        "$APPDIR/usr/lib/$MULTIARCH/gstreamer-1.0/"
fi
if [ -x "$APPDIR/usr/bin/gst-plugin-scanner" ]; then
    cp -a "$APPDIR/usr/bin/gst-plugin-scanner" \
        "$APPDIR/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0/"
fi

rm -f "$APPDIR/AppRun"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
set -eu
APPDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MULTIARCH=x86_64-linux-gnu
export PATH="$APPDIR/usr/bin:$PATH"
export PYTHONHOME="$APPDIR/usr"
export PYTHONPATH="$APPDIR/usr/lib/python3/dist-packages"
export PYTHONTZPATH="$APPDIR/usr/share/zoneinfo"
export LD_LIBRARY_PATH="$APPDIR/usr/lib/$MULTIARCH:$APPDIR/usr/lib:${LD_LIBRARY_PATH:-}"
export GI_TYPELIB_PATH="$APPDIR/usr/lib/$MULTIARCH/girepository-1.0"
export GIO_MODULE_DIR="$APPDIR/usr/lib/$MULTIARCH/gio/modules"
export GST_PLUGIN_PATH_1_0="$APPDIR/usr/lib/$MULTIARCH/gstreamer-1.0"
export GST_PLUGIN_SYSTEM_PATH_1_0=
export GST_PLUGIN_SCANNER="$APPDIR/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner"
export OPENSSL_CONF="$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf"
export OPENSSL_MODULES="$APPDIR/usr/lib/$MULTIARCH/ossl-modules"
: "${SSL_CERT_FILE:=$APPDIR/usr/share/magnolie-organizer/certs/ca-certificates.crt}"
export SSL_CERT_FILE
# Desktop modules from the host must not load against the bundled GTK/GLib.
export GTK_MODULES=
export GTK3_MODULES=
export GTK_PATH="$APPDIR/usr/lib/$MULTIARCH/gtk-3.0"
export GTK_DATA_PREFIX="$APPDIR/usr"
export GTK_THEME=Adwaita
export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/share/glib-2.0/schemas"
# Keep host font files, but never parse configuration for a newer fontconfig.
export FONTCONFIG_PATH="$APPDIR/usr/share/magnolie-organizer/fontconfig"
export FONTCONFIG_FILE="$FONTCONFIG_PATH/fonts.conf"
# Native Wayland and DMA-BUF keep interaction fluid. Affected graphics stacks
# can opt into the conservative XWayland/software-transfer fallback.
: "${MAGNOLIE_GRAPHICS_COMPAT:=0}"
export MAGNOLIE_GRAPHICS_COMPAT
export WEBKIT_EXEC_PATH="$APPDIR/usr/lib/webkit2gtk-4.1"
export WEBKIT_INJECTED_BUNDLE_PATH="$APPDIR/usr/lib/webkit2gtk-4.1/injected-bundle"
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export MAGNOLIE_ORGANIZER_WEB="$APPDIR/usr/share/magnolie-organizer/web"
export MAGNOLIE_HANDBUCH_WEB="$APPDIR/usr/share/magnolie-handbuch/web"
export MAGNOLIE_HANDBUCH_LOCALE="$APPDIR/usr/share/locale"
export MAGNOLIE_LOCALE_DIR="$APPDIR/usr/share/locale"
export MAGNOLIE_ORGANIZER_KLANG="$APPDIR/usr/share/magnolie-organizer/klang/erinnerung.wav"
cd "$APPDIR"
PROGRAM="$APPDIR/usr/bin/magnolie-organizer"
if [ "${1:-}" = "--handbook" ]; then
    PROGRAM="$APPDIR/usr/lib/magnolie-handbuch/magnolie-handbuch"
    shift
fi
exec "$APPDIR/usr/bin/python3" -S \
    "$APPDIR/usr/share/magnolie-organizer/werkzeuge/appimage_runtime.py" \
    "$APPDIR" "$PROGRAM" "$@"
EOF
chmod 0755 "$APPDIR/AppRun"
ln -sf usr/share/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop \
    "$APPDIR/io.gitlab.maik3531.MagnolieOrganizer.desktop"
ln -sf usr/share/icons/hicolor/256x256/apps/magnolie-organizer.png \
    "$APPDIR/magnolie-organizer.png"

epoch=${SOURCE_DATE_EPOCH:-$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -STimestamp)}
python3 "$WURZEL/werkzeuge/release_sources.py" binary "$APPDIR/usr/share/magnolie-organizer"
python3 "$WURZEL/werkzeuge/release_sources.py" binary "$APPDIR/usr/share/magnolie-handbuch"
python3 -I -B "$WURZEL/werkzeuge/runtime_pruefen.py" "$APPDIR/usr/bin" --tzpath "$APPDIR/usr/share/zoneinfo"
image_epoch=$((epoch - epoch % 86400))
sitecustomize="$APPDIR/usr/lib/python$PYTHON_VERSION/sitecustomize.py"
if [ -L "$sitecustomize" ]; then
    rm -f "$sitecustomize"
    install -m 0644 "/etc/python$PYTHON_VERSION/sitecustomize.py" "$sitecustomize"
fi
# Normalizing mtimes invalidates distro timestamp-based bytecode. Hash-based
# caches keep cold extracted CLI startup fast without accepting stale source.
python3 -m compileall -q -f --invalidation-mode checked-hash -s "$APPDIR" -p / \
    -x '/tests?/' "$APPDIR/usr/bin" "$APPDIR/usr/lib/python$PYTHON_VERSION" \
    "$APPDIR/usr/lib/python3" "$APPDIR/usr/share/magnolie-organizer/werkzeuge"
find "$APPDIR" -exec touch -h -d "@$image_epoch" {} +
python3 "$WURZEL/werkzeuge/elf_glibc_pruefen.py" "$APPDIR" 2.35
rm -f "$AUSGABE"
ARCH=x86_64 SOURCE_DATE_EPOCH=$image_epoch "$APPIMAGETOOL" --appimage-extract-and-run \
    "$APPDIR" "$AUSGABE"
chmod 0755 "$AUSGABE"
printf '%s\n' "AppImage gebaut: $AUSGABE"
sha256sum "$AUSGABE"
