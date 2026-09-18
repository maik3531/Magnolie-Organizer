#!/bin/sh
set -eu

for befehl in bwrap g-ir-inspect nm timeout xdg-dbus-proxy xvfb-run; do
    command -v "$befehl" >/dev/null || {
        printf '%s\n' "Fehlendes AppImage-Pruefwerkzeug: $befehl" >&2
        exit 1
    }
done

APPIMAGE=$(readlink -f "${1:?Aufruf: pruefungen/test_appimage.sh DATEI.AppImage}")
WURZEL=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ARBEIT=$(mktemp -d)
trap 'rm -rf "$ARBEIT"' EXIT HUP INT TERM
CONTRIBUTOR_HASH=${MAGNOLIE_CONTRIBUTOR_HASH:-}
[ "${#CONTRIBUTOR_HASH}" -eq 64 ]
case "$CONTRIBUTOR_HASH" in *[!0-9a-fA-F]*) exit 2;; esac
CONTRIBUTOR_HASH=$(printf '%s' "$CONTRIBUTOR_HASH" | tr A-F a-f)

test -x "$APPIMAGE"
DISPLAY= WAYLAND_DISPLAY= timeout 20s "$APPIMAGE" --language en --help | \
    grep -q 'Usage:'
DISPLAY= WAYLAND_DISPLAY= timeout 20s "$APPIMAGE" --appimage-extract-and-run \
    --language en --help | grep -q 'Usage:'
(cd "$ARBEIT" && "$APPIMAGE" --appimage-extract >/dev/null)
APPDIR="$ARBEIT/squashfs-root"
test -x "$APPDIR/AppRun"
cmp "$APPDIR/usr/share/doc/magnolie-organizer/PROTECTED-ASSETS-LICENSE.txt" \
    "$(dirname -- "$0")/../PROTECTED-ASSETS-LICENSE.txt"
test -s "$APPDIR/usr/share/magnolie-organizer/web/kaffee-qr.mga"
test ! -e "$APPDIR/usr/share/magnolie-organizer/web/kaffee-qr.png"
grep -Fq ': "${MAGNOLIE_GRAPHICS_COMPAT:=0}"' "$APPDIR/AppRun"
! grep -Fq ': "${WEBKIT_DISABLE_DMABUF_RENDERER:=1}"' "$APPDIR/AppRun"
! grep -Fq 'WEBKIT_DISABLE_COMPOSITING_MODE' "$APPDIR/AppRun"
! grep -Fq ': "${GDK_BACKEND:=x11}"' "$APPDIR/AppRun"
grep -Fq 'export OPENSSL_CONF="$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf"' "$APPDIR/AppRun"
grep -Fq 'export OPENSSL_MODULES="$APPDIR/usr/lib/$MULTIARCH/ossl-modules"' "$APPDIR/AppRun"
grep -Fq 'export GTK3_MODULES=' "$APPDIR/AppRun"
grep -Fq 'export GTK_DATA_PREFIX="$APPDIR/usr"' "$APPDIR/AppRun"
grep -Fq 'export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/share/glib-2.0/schemas"' "$APPDIR/AppRun"
grep -Fq 'export FONTCONFIG_PATH="$APPDIR/usr/share/magnolie-organizer/fontconfig"' "$APPDIR/AppRun"
grep -Fq 'export FONTCONFIG_FILE="$FONTCONFIG_PATH/fonts.conf"' "$APPDIR/AppRun"
if find "$APPDIR" -type f -exec grep -aFl \
    'WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1' {} + | grep -q .; then
    printf '%s\n' 'Das AppImage enthaelt den WebKit-Sandbox-Disable-Schalter.' >&2
    exit 1
fi
test -x "$APPDIR/usr/bin/python3"
test -x "$APPDIR/usr/bin/magnolie-organizer"
test -x "$APPDIR/usr/bin/fc-match"
test -x "$APPDIR/usr/bin/xgettext"
test -x "$APPDIR/usr/bin/bwrap"
test -x "$APPDIR/usr/bin/xdg-dbus-proxy"
test -f "$APPDIR/usr/lib/libnotify.so.4"
PYTHONHOME="$APPDIR/usr" PYTHONPATH="$APPDIR/usr/lib/python3/dist-packages" \
LD_LIBRARY_PATH="$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
GI_TYPELIB_PATH="$APPDIR/usr/lib/x86_64-linux-gnu/girepository-1.0" \
    "$APPDIR/usr/bin/python3" - <<'PY'
import ctypes
import gi
gi.require_foreign('cairo')
gi.require_version('Notify', '0.7')
from gi.repository import Notify
ctypes.CDLL('libnotify.so.4')
assert Notify.init('Magnolie packaging load check')
Notify.uninit()
PY
test -f "$APPDIR/usr/share/magnolie-organizer/werkzeuge/appimage_graphics.py"
test -f "$APPDIR/usr/share/magnolie-organizer/werkzeuge/appimage_runtime.py"
python3 - "$APPDIR" <<'PY'
from pathlib import Path
import sys

appdir = Path(sys.argv[1])
for pattern in ('usr/lib/python*/__pycache__/os.*.pyc',
                'usr/share/magnolie-organizer/werkzeuge/__pycache__/appimage_runtime.*.pyc'):
    caches = list(appdir.glob(pattern))
    assert caches, pattern
    assert all(int.from_bytes(path.read_bytes()[4:8], 'little') == 3 for path in caches), pattern
PY
LD_LIBRARY_PATH="$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
    "$APPDIR/usr/bin/xgettext" --version >/dev/null
! grep -Fq 'HardwareAccelerationPolicy.NEVER' \
    "$APPDIR/usr/bin/magnolie-organizer"
test -f "$APPDIR/usr/bin/magnolie_telefon.py"
test -f "$APPDIR/usr/bin/magnolie_personal_sync.py"
test -f "$APPDIR/usr/bin/magnolie_nextcloud.py"
test -f "$APPDIR/usr/bin/magnolie_cloud_backup.py"
test -f "$APPDIR/usr/bin/magnolie_akonadi.py"
test -f "$APPDIR/usr/bin/magnolie_recurrence.py"
test -f "$APPDIR/usr/share/zoneinfo/Europe/Berlin"
test -s "$APPDIR/usr/share/doc/magnolie-organizer/tzdata-copyright"
test -f "$APPDIR/usr/share/magnolie-organizer/web/index.html"
test "$(cat "$APPDIR/usr/share/magnolie-organizer/build-config.json")" = \
    "{\"contributorHash\":\"$CONTRIBUTOR_HASH\"}"
while read -r sprache; do
    test -f "$APPDIR/usr/share/magnolie-organizer/web/i18n/$sprache.js"
    test -f "$APPDIR/usr/share/locale/$sprache/LC_MESSAGES/magnolie-organizer.mo"
done < "$WURZEL/po/LINGUAS"
test -f "$APPDIR/usr/share/magnolie-organizer/klang/erinnerung.wav"
test -f "$APPDIR/usr/share/metainfo/io.gitlab.maik3531.MagnolieOrganizer.appdata.xml"
test -f "$APPDIR/usr/share/applications/io.gitlab.maik3531.MagnolieOrganizer.desktop"
test -f "$APPDIR/usr/lib/libxapp.so.1"
test -f "$APPDIR/usr/lib/libayatana-appindicator3.so.1"
test -f "$APPDIR/usr/lib/x86_64-linux-gnu/gtk-3.0/modules/libxapp-gtk3-module.so"
test -f "$APPDIR/usr/lib/x86_64-linux-gnu/gio/modules/libgiognutls.so"
test -f "$APPDIR/usr/lib/x86_64-linux-gnu/gio/modules/giomodule.cache"
test -f "$APPDIR/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgstapp.so"
test -x "$APPDIR/usr/lib/x86_64-linux-gnu/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner"
test -f "$APPDIR/usr/share/magnolie-organizer/certs/ca-certificates.crt"
test -f "$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf"
FONTCONFIG_DATEI="$APPDIR/usr/share/magnolie-organizer/fontconfig/fonts.conf"
test -f "$FONTCONFIG_DATEI"
! grep -q '<include' "$FONTCONFIG_DATEI"
test -d "$APPDIR/usr/lib/x86_64-linux-gnu/ossl-modules"
test -n "$(find "$APPDIR/usr/lib/x86_64-linux-gnu/ossl-modules" -type f -print -quit)"
test -f "$APPDIR/usr/share/themes/Adwaita/gtk-3.0/gtk.css"
test -f "$APPDIR/usr/share/glib-2.0/schemas/gschemas.compiled"
test -x "$APPDIR/usr/lib/webkit2gtk-4.1/WebKitNetworkProcess"
test -x "$APPDIR/usr/lib/webkit2gtk-4.1/WebKitWebProcess"
if test -f "$APPDIR/usr/lib/libecal-2.0.so.3"; then
    ECAL_SONAME=libecal-2.0.so.3
    EBOOK_SONAME=libebook-1.2.so.21
    EDS_SONAMES="libecal-2.0.so.3 libedataserver-1.2.so.27 libical-glib.so.3 libical.so.3 libcamel-1.2.so.64 libebook-1.2.so.21 libebook-contacts-1.2.so.4 libedata-book-1.2.so.27 libebackend-1.2.so.11"
else
    ECAL_SONAME=libecal-2.0.so.1
    EBOOK_SONAME=libebook-1.2.so.20
    EDS_SONAMES="libecal-2.0.so.1 libedataserver-1.2.so.26 libical-glib.so.3 libical.so.3 libcamel-1.2.so.63 libebook-1.2.so.20 libebook-contacts-1.2.so.3 libedata-book-1.2.so.26 libebackend-1.2.so.10"
fi
for soname in $EDS_SONAMES; do
    test -f "$APPDIR/usr/lib/$soname"
done
python3 "$WURZEL/werkzeuge/elf_glibc_pruefen.py" "$APPDIR" 2.35
TYPELIB_PFAD="$APPDIR/usr/lib/x86_64-linux-gnu/girepository-1.0"
test "$(GI_TYPELIB_PATH="$TYPELIB_PFAD" g-ir-inspect --version=3.0 \
    --print-shlibs ICalGLib)" = "shlib: libical-glib.so.3"
test "$(GI_TYPELIB_PATH="$TYPELIB_PFAD" g-ir-inspect --version=2.0 \
    --print-shlibs ECal)" = "shlib: $ECAL_SONAME"
nm -D --defined-only "$APPDIR/usr/lib/libical-glib.so.3" | \
    grep -q ' i_cal_component_as_ical_string$'
nm -D --undefined-only "$APPDIR/usr/lib/$ECAL_SONAME" | \
    grep -q ' i_cal_component_as_ical_string$'
for bibliothek in "$APPDIR/usr/lib/$ECAL_SONAME" \
    "$APPDIR/usr/lib/$EBOOK_SONAME"; do
    aufloesung=$(/lib64/ld-linux-x86-64.so.2 --list \
        --library-path "$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
        "$bibliothek")
    ! printf '%s\n' "$aufloesung" | grep -q 'not found'
    ! printf '%s\n' "$aufloesung" | grep -E \
        'lib(ecal|edataserver|ical|camel|ebook|edata-book|ebackend)[^ ]* => /(usr/)?lib/'
done
python3 - "$APPDIR/usr/lib/libwebkit2gtk-4.1.so.0" <<'PY'
import pathlib
import sys

daten = pathlib.Path(sys.argv[1]).read_bytes()
assert b"/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1" not in daten
assert b"/proc/self/cwd//./usr/lib/webkit2gtk-4.1" in daten
PY

# Validate the isolated configuration with the exact bundled fontconfig/expat.
# fc-match is only the CLI front-end; LD_LIBRARY_PATH selects the AppImage ABI.
for familie in sans-serif serif monospace; do
    treffer=$(FONTCONFIG_PATH="$(dirname "$FONTCONFIG_DATEI")" \
        FONTCONFIG_FILE="$FONTCONFIG_DATEI" \
        LD_LIBRARY_PATH="$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
        "$APPDIR/usr/bin/fc-match" -f '%{file}\n' "$familie")
    test -n "$treffer"
    test -f "$treffer"
done

# The native setup dialog must remain readable without host desktop fonts.
mkdir -p "$ARBEIT/fontcheck-home" "$ARBEIT/fontcheck-data"
bwrap --ro-bind / / --dev /dev --proc /proc \
    --tmpfs /usr/share/fonts --tmpfs /usr/local/share/fonts \
    --chdir "$APPDIR" \
    --setenv HOME "$ARBEIT/fontcheck-home" --setenv XDG_DATA_HOME "$ARBEIT/fontcheck-data" \
    --setenv FONTCONFIG_PATH "$(dirname "$FONTCONFIG_DATEI")" \
    --setenv FONTCONFIG_FILE "$FONTCONFIG_DATEI" \
    --setenv LD_LIBRARY_PATH "$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
    "$APPDIR/usr/bin/fc-match" -f '%{file}\n' sans-serif > "$ARBEIT/bundled-font.txt"
IFS= read -r bundled_font < "$ARBEIT/bundled-font.txt"
bundled_font=$(readlink -f "$bundled_font")
case "$bundled_font" in
    "$APPDIR/usr/share/magnolie-handbuch/web/schriften/"*) test -s "$bundled_font" ;;
    *) printf '%s\n' 'Native GTK-Schrift fehlt ohne Wirtsschriften.' >&2; exit 1 ;;
esac

PYTHONHOME="$APPDIR/usr" \
PYTHONPATH="$APPDIR/usr/bin:$APPDIR/usr/lib/python3/dist-packages" \
PYTHONTZPATH="$APPDIR/usr/share/zoneinfo" \
LD_LIBRARY_PATH="$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
GI_TYPELIB_PATH="$APPDIR/usr/lib/x86_64-linux-gnu/girepository-1.0" \
GIO_MODULE_DIR="$APPDIR/usr/lib/x86_64-linux-gnu/gio/modules" \
GST_PLUGIN_PATH_1_0="$APPDIR/usr/lib/x86_64-linux-gnu/gstreamer-1.0" \
GST_PLUGIN_SYSTEM_PATH_1_0= \
GST_PLUGIN_SCANNER="$APPDIR/usr/lib/x86_64-linux-gnu/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner" \
OPENSSL_CONF="$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf" \
OPENSSL_MODULES="$APPDIR/usr/lib/x86_64-linux-gnu/ossl-modules" \
SSL_CERT_FILE="$APPDIR/usr/share/magnolie-organizer/certs/ca-certificates.crt" \
    "$APPDIR/usr/bin/python3" - <<'PY'
import gi
import magnolie_phone_region
import magnolie_personal_sync
import magnolie_telefon
import magnolie_cloud_backup
import magnolie_recurrence
import phonenumbers
import qrcode
import six
import ssl
from OpenSSL import SSL
from cryptography.hazmat.primitives.asymmetric import ec
from qrcode.image.svg import SvgPathImage
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

assert Path(magnolie_recurrence.__file__).parent == Path(magnolie_telefon.__file__).parent
start = datetime(2026, 9, 1, 9, tzinfo=ZoneInfo("Europe/Berlin"))
assert [value.day for value in magnolie_recurrence.Rule("FREQ=DAILY;COUNT=2", start).between(start, start.replace(day=4))] == [1, 2]

gi.require_version("Gio", "2.0")
gi.require_version("Gst", "1.0")
gi.require_version("EDataServer", "1.2")
gi.require_version("ECal", "2.0")
gi.require_version("ICalGLib", "3.0")
from gi.repository import Gio, Gst, EDataServer, ECal, ICalGLib

Gst.init(None)
assert magnolie_telefon.validate_personal_sync_body is \
    magnolie_personal_sync.validate_body
assert magnolie_phone_region.analyze(
    "+4930123456", "available", "DE", "de")["phone_origin_status"] == "known"
assert Gio.TlsBackend.get_default().supports_tls()
assert Gst.ElementFactory.find("appsink") is not None
assert ssl.get_default_verify_paths().cafile.endswith("ca-certificates.crt")
assert SSL.Context(SSL.TLS_METHOD) is not None
assert ec.generate_private_key(ec.SECP256R1()) is not None
qr = qrcode.QRCode()
qr.add_data("magnolie-appimage-probe")
qr.make(fit=True)
assert qr.make_image(image_factory=SvgPathImage).to_string().startswith(b"<svg")
component = ICalGLib.Component.new_from_string(
    "BEGIN:VEVENT\r\nUID:appimage-probe\r\nDTSTAMP:20260101T000000Z\r\nEND:VEVENT\r\n")
assert component is not None
assert component.as_ical_string().startswith("BEGIN:VEVENT")
assert ECal.ClientSourceType.EVENTS is not None
PY
test -s "$APPDIR/usr/share/doc/magnolie-organizer/phonenumbers-copyright"

# Verhindert bei der GI-Probe gezielt jeden Rueckfall auf die gleichnamigen
# EDS/libical-Bibliotheken des Buildhosts, ohne glibc oder den Loader zu sperren.
if command -v bwrap >/dev/null; then
    set -- bwrap --ro-bind / / --dev /dev --proc /proc
    for soname in $EDS_SONAMES; do
        host=$(ldconfig -p 2>/dev/null | grep "[[:space:]]$soname " | \
            sed -n '1s/.* => //p')
        [ -z "$host" ] || set -- "$@" --dev-bind /dev/null "$host"
    done
    "$@" --setenv PYTHONHOME "$APPDIR/usr" \
        --setenv PYTHONPATH "$APPDIR/usr/lib/python3/dist-packages" \
        --setenv LD_LIBRARY_PATH "$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
        --setenv GI_TYPELIB_PATH "$TYPELIB_PFAD" "$APPDIR/usr/bin/python3" - <<'PY'
import gi
gi.require_version("ECal", "2.0")
gi.require_version("ICalGLib", "3.0")
from gi.repository import ECal, ICalGLib
c = ICalGLib.Component.new_from_string(
    "BEGIN:VEVENT\r\nUID:isolated-probe\r\nDTSTAMP:20260101T000000Z\r\nEND:VEVENT\r\n")
assert c.as_ical_string().startswith("BEGIN:VEVENT")
assert ECal.ClientSourceType.EVENTS is not None
PY
fi

mkdir -p "$ARBEIT/host-share/themes/Defektes-Wirtsthema/gtk-3.0"
printf '%s\n' '/* nicht geschlossen' > \
    "$ARBEIT/host-share/themes/Defektes-Wirtsthema/gtk-3.0/gtk.css"
printf '%s\n' '<?xml version="1.0"?>' '<fontconfig>' \
    '  <match><edit name="family"><const>system-ui</const></edit></match>' \
    '</fontconfig>' > "$ARBEIT/host-fonts.conf"

DISPLAY= WAYLAND_DISPLAY= XDG_DATA_HOME="$ARBEIT/data" \
XDG_CONFIG_HOME="$ARBEIT/config" XDG_STATE_HOME="$ARBEIT/state" \
XDG_DATA_DIRS="$ARBEIT/host-share" \
GTK_MODULES=xapp-gtk3-module GTK_THEME=Defektes-Wirtsthema \
GTK3_MODULES=xapp-gtk3-module FONTCONFIG_FILE="$ARBEIT/host-fonts.conf" \
FONTCONFIG_PATH="$ARBEIT" \
OPENSSL_CONF=/nicht/vorhanden/openssl.cnf OPENSSL_MODULES=/nicht/vorhanden \
    "$APPDIR/AppRun" --language en --help | grep -q 'Usage:'
DISPLAY= WAYLAND_DISPLAY= XDG_DATA_HOME="$ARBEIT/data" \
XDG_CONFIG_HOME="$ARBEIT/config" XDG_STATE_HOME="$ARBEIT/state" \
MAGNOLIE_PROGRAMM="$APPDIR/usr/bin/magnolie-organizer" \
PYTHONHOME="$APPDIR/usr" PYTHONPATH="$APPDIR/usr/lib/python3/dist-packages" \
LD_LIBRARY_PATH="$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
GI_TYPELIB_PATH="$APPDIR/usr/lib/x86_64-linux-gnu/girepository-1.0" \
OPENSSL_CONF="$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf" \
OPENSSL_MODULES="$APPDIR/usr/lib/x86_64-linux-gnu/ossl-modules" \
    "$APPDIR/usr/bin/python3" "$WURZEL/pruefungen/test_import_export_vertrag.py"
DISPLAY= WAYLAND_DISPLAY= XDG_DATA_HOME="$ARBEIT/data" \
XDG_CONFIG_HOME="$ARBEIT/config" XDG_STATE_HOME="$ARBEIT/state" \
MAGNOLIE_PROGRAMM="$APPDIR/usr/bin/magnolie-organizer" \
PYTHONHOME="$APPDIR/usr" PYTHONPATH="$APPDIR/usr/lib/python3/dist-packages" \
LD_LIBRARY_PATH="$APPDIR/usr/lib/x86_64-linux-gnu:$APPDIR/usr/lib" \
GI_TYPELIB_PATH="$APPDIR/usr/lib/x86_64-linux-gnu/girepository-1.0" \
OPENSSL_CONF="$APPDIR/usr/share/magnolie-organizer/openssl/openssl.cnf" \
OPENSSL_MODULES="$APPDIR/usr/lib/x86_64-linux-gnu/ossl-modules" \
    "$APPDIR/usr/bin/python3" "$WURZEL/pruefungen/test_gesamtarchiv.py"

appimage_gui_start() {
    if command -v dbus-run-session >/dev/null; then
        env -u WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS \
            NO_AT_BRIDGE=1 dbus-run-session -- \
            timeout 5s xvfb-run -a "$APPDIR/AppRun"
    else
        env -u WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS \
            NO_AT_BRIDGE=1 timeout 5s xvfb-run -a "$APPDIR/AppRun"
    fi
}
set +e
DISPLAY= WAYLAND_DISPLAY= DESKTOPINTEGRATION=1 \
XDG_DATA_DIRS="$ARBEIT/host-share" \
GTK_MODULES=xapp-gtk3-module GTK_THEME=Defektes-Wirtsthema \
GTK3_MODULES=xapp-gtk3-module FONTCONFIG_FILE="$ARBEIT/host-fonts.conf" \
FONTCONFIG_PATH="$ARBEIT" \
OPENSSL_CONF=/nicht/vorhanden/openssl.cnf OPENSSL_MODULES=/nicht/vorhanden \
XDG_DATA_HOME="$ARBEIT/gui-data" XDG_CONFIG_HOME="$ARBEIT/gui-config" \
XDG_STATE_HOME="$ARBEIT/gui-state" \
    appimage_gui_start >"$ARBEIT/gui.log" 2>&1
gui_status=$?
set -e
if [ "$gui_status" -ne 124 ]; then
    printf '%s\n' "WebKit-Sandbox-Smoke-Test fehlgeschlagen (Status $gui_status):" >&2
    cat "$ARBEIT/gui.log" >&2
    exit 1
fi
if grep -Eqi 'Theme parsing error|Fontconfig (error|warning)|Unknown OpenSSL error|could not load the shared library' \
    "$ARBEIT/gui.log"; then
    printf '%s\n' "AppImage verwendet GTK-/OpenSSL-Bestandteile des Wirts:" >&2
    cat "$ARBEIT/gui.log" >&2
    exit 1
fi

appimage_gui_direkt() {
    if command -v dbus-run-session >/dev/null; then
        env -u WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS \
            NO_AT_BRIDGE=1 dbus-run-session -- \
            timeout 5s xvfb-run -a "$APPIMAGE"
    else
        env -u WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS \
            NO_AT_BRIDGE=1 timeout 5s xvfb-run -a "$APPIMAGE"
    fi
}
set +e
DISPLAY= WAYLAND_DISPLAY= DESKTOPINTEGRATION=1 \
XDG_DATA_HOME="$ARBEIT/direct-data" XDG_CONFIG_HOME="$ARBEIT/direct-config" \
XDG_STATE_HOME="$ARBEIT/direct-state" \
    appimage_gui_direkt >"$ARBEIT/direct.log" 2>&1
direkt_status=$?
set -e
if [ "$direkt_status" -ne 124 ]; then
    printf '%s\n' "Direkter AppImage-Smoke-Test fehlgeschlagen (Status $direkt_status):" >&2
    cat "$ARBEIT/direct.log" >&2
    exit 1
fi

# Reuse the exact packaged environment/graphics selector, changing only the
# Python entry point in memory. Process survival alone does not prove rendering.
env -u WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS -u WEBKIT_FORCE_SANDBOX \
    NO_AT_BRIDGE=1 dbus-run-session -- timeout 40s xvfb-run -a \
    python3 - "$APPDIR" "$WURZEL/pruefungen/appimage_render.py" <<'PY'
import os
from pathlib import Path
import subprocess
import sys

appdir = Path(sys.argv[1])
launcher = (appdir / "AppRun").read_text()
old = 'PROGRAM="$APPDIR/usr/bin/magnolie-organizer"'
assert launcher.count(old) == 1
launcher = launcher.replace(old, 'PROGRAM="$MAGNOLIE_APPIMAGE_RENDER_PROBE"')
result = subprocess.run(["/bin/sh", "-c", launcher, str(appdir / "AppRun")],
                        env={**os.environ, "MAGNOLIE_APPIMAGE_RENDER_PROBE": sys.argv[2]})
sys.exit(result.returncode)
PY

printf '%s\n' "APPIMAGE-PRUEFUNG BESTANDEN"
