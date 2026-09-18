#!/bin/sh
set -eu
# Source assets only; synthetic saves, private X server, no host devices/profile.
root=$(realpath "$(dirname "$0")/../..")
evidence=${MAGNOLIE_EDITOR_EVIDENCE:-/tmp/opencode/text-editor-native}
test -d "$evidence"
exec timeout --kill-after=5s 240s bwrap --die-with-parent --ro-bind / / \
  --unshare-net --unshare-ipc --unshare-pid --unshare-uts \
  --dev /dev --proc /proc --tmpfs /home \
  --ro-bind "$root/magnolie-organizer/web" /home/source/linux \
  --ro-bind "$root/magnolie-organizer-windows/app/web" /home/source/windows \
  --ro-bind "$root/magnolie-organizer/pruefungen/text_editor_webkit.py" /home/source/test.py \
  --ro-bind "$root/tools/contact-interop/dbus-session.conf" /home/source/dbus-session.conf \
  --tmpfs /tmp --bind "$evidence" /tmp/evidence --tmpfs /run \
  --setenv HOME /tmp/profile --unsetenv DBUS_SESSION_BUS_ADDRESS --unsetenv DISPLAY \
  --unsetenv XDG_RUNTIME_DIR --setenv GDK_BACKEND x11 \
  --setenv LANG C.UTF-8 --setenv LC_ALL C.UTF-8 --setenv GIO_USE_VFS local \
  --setenv LIBGL_ALWAYS_SOFTWARE 1 --setenv GALLIUM_DRIVER llvmpipe \
  --setenv LP_NUM_THREADS 2 --setenv OMP_NUM_THREADS 2 --setenv GSETTINGS_BACKEND memory \
  --setenv WEBKIT_DISABLE_DMABUF_RENDERER 1 --setenv MAGNOLIE_EDITOR_ISOLATED 1 \
  --setenv __EGL_VENDOR_LIBRARY_FILENAMES /usr/share/glvnd/egl_vendor.d/50_mesa.json \
  --setenv __GLX_VENDOR_LIBRARY_NAME mesa \
  taskset -c 0,1 xvfb-run -a -s '-screen 0 1600x1200x24' -e /tmp/evidence/xvfb.log \
  dbus-run-session --config-file=/home/source/dbus-session.conf -- /usr/bin/python3 /home/source/test.py "$@"
