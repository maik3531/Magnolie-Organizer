#!/usr/bin/env bash
set -euo pipefail
root=${CONTACT_INTEROP_HOME:-$(mktemp -d /tmp/opencode/contact-parser-XXXXXXXX)}
case "$root" in /tmp/opencode/*) ;; *) exit 2 ;; esac
mkdir -p "$root/home" "$root/runtime"
chmod 700 "$root/runtime"
exec bwrap --die-with-parent --unshare-net --unshare-pid --ro-bind / / --tmpfs /tmp --tmpfs /run \
  --ro-bind /tmp/opencode /tmp/opencode --bind "$root" "$root" --proc /proc --dev /dev \
  --setenv HOME "$root/home" --setenv DOTNET_CLI_HOME "$root/home" \
  --setenv CONTACT_INTEROP_HOME "$root" --setenv CONTACT_WINDOWS_DLL "$root/bin/CoreTests.dll" \
  --setenv CONTACT_INTEROP_SANDBOX 1 \
  --setenv DOTNET_SKIP_FIRST_TIME_EXPERIENCE 1 --setenv DOTNET_CLI_TELEMETRY_OPTOUT 1 \
  --setenv DOTNET_GENERATE_ASPNET_CERTIFICATE false --setenv DOTNET_NOLOGO 1 \
  --setenv MSBUILDDISABLENODEREUSE 1 --setenv NUGET_PACKAGES /home/maik3531/.nuget/packages \
  --setenv XDG_CONFIG_HOME "$root/home/config" --setenv XDG_DATA_HOME "$root/home/data" \
  --setenv XDG_CACHE_HOME "$root/home/cache" --setenv XDG_STATE_HOME "$root/home/state" \
  --setenv XDG_RUNTIME_DIR "$root/runtime" --unsetenv DBUS_SESSION_BUS_ADDRESS \
  --unsetenv DBUS_SYSTEM_BUS_ADDRESS --unsetenv DBUS_STARTER_ADDRESS --unsetenv DBUS_STARTER_BUS_TYPE \
  --unsetenv DISPLAY --unsetenv WAYLAND_DISPLAY \
  --setenv TMPDIR "$root" --setenv TMP "$root" --setenv TEMP "$root" \
  --setenv PYTHONDONTWRITEBYTECODE 1 --setenv PYTEST_DISABLE_PLUGIN_AUTOLOAD 1 \
  --setenv TZ Europe/Berlin "$@"
