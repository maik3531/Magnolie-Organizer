#!/bin/sh
set -eu

WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FASSUNG=$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -SVersion)
ARCH=$(uname -m)
MULTIARCH=$(gcc -dumpmachine)
AUSGABE=${1:-"$WURZEL/../Magnolie-Organizer-$FASSUNG-$ARCH.AppImage"}
ARBEIT=${APPIMAGE_BUILD_DIR:-"$WURZEL/bau/appimage"}
WERKZEUGE=${APPIMAGE_TOOL_DIR:-"$WURZEL/bau/appimage-werkzeuge"}
APPDIR="$ARBEIT/Magnolie-Organizer.AppDir"

if [ "$ARCH" != "x86_64" ]; then
    printf '%s\n' "Der AppImage-Bau ist derzeit fuer x86_64 festgeschrieben." >&2
    exit 1
fi

LINUXDEPLOY_URL=https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage
LINUXDEPLOY_SHA=c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA=a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0
LINUXDEPLOY="$WERKZEUGE/linuxdeploy-x86_64.AppImage"
APPIMAGETOOL="$WERKZEUGE/appimagetool-x86_64.AppImage"

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

EDS_BIBLIOTHEKEN="
/usr/lib/$MULTIARCH/libecal-2.0.so.3
/usr/lib/$MULTIARCH/libedataserver-1.2.so.27
/usr/lib/$MULTIARCH/libical-glib.so.3
/usr/lib/$MULTIARCH/libical.so.3
/usr/lib/$MULTIARCH/libcamel-1.2.so.64
/usr/lib/$MULTIARCH/libebook-1.2.so.21
/usr/lib/$MULTIARCH/libebook-contacts-1.2.so.4
/usr/lib/$MULTIARCH/libedata-book-1.2.so.27
"
EDS_TYPELIBS="Camel-1.2 EDataServer-1.2 ECal-2.0 ICalGLib-3.0 EBookContacts-1.2 EBook-1.2"
APP_TYPELIBS="
GLib-2.0 GObject-2.0 Gio-2.0 GModule-2.0
cairo-1.0 freetype2-2.0 xlib-2.0 HarfBuzz-0.0
Atk-1.0 GdkPixbuf-2.0 Pango-1.0 Gdk-3.0 Gtk-3.0
JavaScriptCore-4.1 Soup-3.0 Json-1.0 libxml2-2.0 WebKit2-4.1
Gst-1.0 AyatanaAppIndicator3-0.1 AppIndicator3-0.1 XApp-1.0 Notify-0.7
$EDS_TYPELIBS
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
            AyatanaAppIndicator3-0.1|AppIndicator3-0.1|XApp-1.0|Notify-0.7) continue ;;
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
nm -D --undefined-only /usr/lib/$MULTIARCH/libecal-2.0.so.3 | \
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
    "$APPDIR/usr/share/magnolie-organizer/werkzeuge" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/doc/magnolie-organizer" \
    "$APPDIR/usr/share/metainfo"

python3 "$WURZEL/werkzeuge/klang.py" "$ARBEIT/erinnerung.wav"
while read -r sprache; do
    mkdir -p "$APPDIR/usr/share/locale/$sprache/LC_MESSAGES"
    msgfmt --check --check-format -o "$ARBEIT/$sprache.mo" "$WURZEL/po/$sprache.po"
    python3 "$WURZEL/werkzeuge/po_zu_js.py" "$sprache" \
        "$WURZEL/po/$sprache.po" "$ARBEIT/$sprache.js"
done < "$WURZEL/po/LINGUAS"

install -m 0755 "$WURZEL/bin/magnolie-organizer" "$APPDIR/usr/bin/magnolie-organizer"
install -m 0644 "$WURZEL/bin/magnolie_telefon.py" "$APPDIR/usr/bin/magnolie_telefon.py"
install -m 0755 "$(readlink -f "$(command -v python3)")" "$APPDIR/usr/bin/python3.12"
ln -s python3.12 "$APPDIR/usr/bin/python3"
cp -a /usr/lib/python3.12 "$APPDIR/usr/lib/"
find "$APPDIR/usr/lib/python3.12" -type f \( -name '*.a' -o -name '*.o' \) -delete
for paket in gi cryptography zeroconf ifaddr; do
    quelle="/usr/lib/python3/dist-packages/$paket"
    [ ! -e "$quelle" ] || cp -a "$quelle" "$APPDIR/usr/lib/python3/dist-packages/"
done
for modul in /usr/lib/python3/dist-packages/_cffi_backend*.so; do
    [ ! -e "$modul" ] || cp -a "$modul" "$APPDIR/usr/lib/python3/dist-packages/"
done
for typelib in $APP_TYPELIBS; do
    quelle="/usr/lib/$MULTIARCH/girepository-1.0/$typelib.typelib"
    [ ! -f "$quelle" ] || install -m 0644 "$quelle" \
        "$APPDIR/usr/lib/$MULTIARCH/girepository-1.0/$typelib.typelib"
done
[ ! -d /usr/share/glib-2.0/schemas ] || cp -a /usr/share/glib-2.0 "$APPDIR/usr/share/"
[ ! -d /usr/lib/$MULTIARCH/webkit2gtk-4.1 ] || \
    cp -a /usr/lib/$MULTIARCH/webkit2gtk-4.1 "$APPDIR/usr/lib/"

cp -a "$WURZEL/web/." "$APPDIR/usr/share/magnolie-organizer/web/"
CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
if [ -n "$CONTRIBUTOR_HASH" ]; then
    [ "${#CONTRIBUTOR_HASH}" -eq 64 ] || {
        printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH muss eine SHA-256-Hexfolge sein.' >&2
        exit 2
    }
    case "$CONTRIBUTOR_HASH" in
        *[!0-9a-fA-F]*)
            printf '%s\n' 'MAGNOLIE_CONTRIBUTOR_HASH muss eine SHA-256-Hexfolge sein.' >&2
            exit 2 ;;
    esac
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
install -m 0644 /etc/ssl/certs/ca-certificates.crt \
    "$APPDIR/usr/share/magnolie-organizer/certs/ca-certificates.crt"
[ ! -f /usr/share/doc/python3.12/copyright ] || install -m 0644 \
    /usr/share/doc/python3.12/copyright "$APPDIR/usr/share/doc/magnolie-organizer/python3.12-copyright"

set -- --appdir "$APPDIR" --executable "$APPDIR/usr/bin/python3.12" \
    --desktop-file "$APPDIR/usr/share/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop" \
    --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/magnolie-organizer.png" \
    --library "/usr/lib/$MULTIARCH/libgtk-3.so.0" \
    --library "/usr/lib/$MULTIARCH/libwebkit2gtk-4.1.so.0"
for bibliothek in $EDS_BIBLIOTHEKEN; do
    set -- "$@" --library "$bibliothek"
done
for bibliothek in "/usr/lib/$MULTIARCH/libxapp.so.1" \
    "/usr/lib/$MULTIARCH/libayatana-appindicator3.so.1" \
    "/usr/lib/$MULTIARCH/libappindicator3.so.1" \
    "/usr/lib/$MULTIARCH/gtk-3.0/modules/libxapp-gtk3-module.so" \
    "/usr/lib/$MULTIARCH/gio/modules/libgiognutls.so" \
    "/usr/lib/$MULTIARCH/gstreamer-1.0/libgstapp.so"; do
    [ ! -e "$bibliothek" ] || set -- "$@" --library "$bibliothek"
done
GST_SCANNER=/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner
[ ! -x "$GST_SCANNER" ] || set -- "$@" --executable "$GST_SCANNER"
for helfer in "$APPDIR/usr/lib/webkit2gtk-4.1/MiniBrowser" \
    "$APPDIR/usr/lib/webkit2gtk-4.1/WebKitGPUProcess" \
    "$APPDIR/usr/lib/webkit2gtk-4.1/WebKitNetworkProcess" \
    "$APPDIR/usr/lib/webkit2gtk-4.1/WebKitWebProcess"; do
    [ ! -x "$helfer" ] || set -- "$@" --executable "$helfer"
done
for bibliothek in $(find "$APPDIR/usr/lib/python3.12" \
    "$APPDIR/usr/lib/python3/dist-packages" \
    "$APPDIR/usr/lib/webkit2gtk-4.1/injected-bundle" \
    -type f -name '*.so'); do
    set -- "$@" --library "$bibliothek"
done
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
    --print-shlibs ECal)" = "shlib: libecal-2.0.so.3" ] || {
    printf '%s\n' "ECal-2.0.typelib verweist nicht auf libecal-2.0.so.3." >&2
    exit 1
}
for soname in libecal-2.0.so.3 libedataserver-1.2.so.27 libical-glib.so.3 \
    libical.so.3 libcamel-1.2.so.64 libebook-1.2.so.21 \
    libebook-contacts-1.2.so.4 libedata-book-1.2.so.27 libebackend-1.2.so.11; do
    [ -f "$APPDIR/usr/lib/$soname" ] || {
        printf '%s\n' "linuxdeploy-Closure ist unvollstaendig: $soname fehlt." >&2
        exit 1
    }
done
for bibliothek in "$APPDIR/usr/lib/libecal-2.0.so.3" \
    "$APPDIR/usr/lib/libebook-1.2.so.21"; do
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
pfad.write_bytes(daten.replace(alt, neu))
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
export LD_LIBRARY_PATH="$APPDIR/usr/lib/$MULTIARCH:$APPDIR/usr/lib:${LD_LIBRARY_PATH:-}"
export GI_TYPELIB_PATH="$APPDIR/usr/lib/$MULTIARCH/girepository-1.0"
export GIO_MODULE_DIR="$APPDIR/usr/lib/$MULTIARCH/gio/modules"
export GST_PLUGIN_PATH_1_0="$APPDIR/usr/lib/$MULTIARCH/gstreamer-1.0"
export GST_PLUGIN_SYSTEM_PATH_1_0=
export GST_PLUGIN_SCANNER="$APPDIR/usr/lib/$MULTIARCH/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner"
: "${SSL_CERT_FILE:=$APPDIR/usr/share/magnolie-organizer/certs/ca-certificates.crt}"
export SSL_CERT_FILE
# Desktop modules from the host must not load against the bundled GTK/GLib.
export GTK_MODULES=
export GTK_PATH="$APPDIR/usr/lib/$MULTIARCH/gtk-3.0"
export GTK_THEME=Adwaita
export WEBKIT_EXEC_PATH="$APPDIR/usr/lib/webkit2gtk-4.1"
export WEBKIT_INJECTED_BUNDLE_PATH="$APPDIR/usr/lib/webkit2gtk-4.1/injected-bundle"
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export MAGNOLIE_ORGANIZER_WEB="$APPDIR/usr/share/magnolie-organizer/web"
export MAGNOLIE_LOCALE_DIR="$APPDIR/usr/share/locale"
export MAGNOLIE_ORGANIZER_KLANG="$APPDIR/usr/share/magnolie-organizer/klang/erinnerung.wav"
cd "$APPDIR"
exec "$APPDIR/usr/bin/python3" "$APPDIR/usr/bin/magnolie-organizer" "$@"
EOF
chmod 0755 "$APPDIR/AppRun"
ln -sf usr/share/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop \
    "$APPDIR/io.gitlab.maik3531.MagnolieOrganizer.desktop"
ln -sf usr/share/icons/hicolor/256x256/apps/magnolie-organizer.png \
    "$APPDIR/magnolie-organizer.png"

epoch=${SOURCE_DATE_EPOCH:-$(dpkg-parsechangelog -l"$WURZEL/debian/changelog" -STimestamp)}
image_epoch=$((epoch - epoch % 86400))
find "$APPDIR" -exec touch -h -d "@$image_epoch" {} +
rm -f "$AUSGABE"
ARCH=x86_64 SOURCE_DATE_EPOCH=$image_epoch "$APPIMAGETOOL" --appimage-extract-and-run \
    "$APPDIR" "$AUSGABE"
chmod 0755 "$AUSGABE"
printf '%s\n' "AppImage gebaut: $AUSGABE"
sha256sum "$AUSGABE"
