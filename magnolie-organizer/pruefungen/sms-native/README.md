# Isolated SMS Comparator

This test compiles the actual Windows `SmsSubmissionJournal`, `AtomicStore`, and
`PhoneUri` source, not an emulated filesystem or SMS backend. It has no network,
phone, desktop-service or real profile dependency. It uses a caller-supplied local
`PhoneNumbers.dll`; no package download is needed. All product sources stay unchanged.

Run from the canonical repository root. Use a fresh external scratch directory
and isolate the .NET SDK itself, not only the test application:

```sh
export HOME=/tmp/opencode/aur-sms-native/home
export DOTNET_CLI_HOME="$HOME"
export XDG_DATA_HOME="$HOME/data"
export XDG_CONFIG_HOME="$HOME/config"
export XDG_CACHE_HOME="$HOME/cache"
export DOTNET_GENERATE_ASPNET_CERTIFICATE=false
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export NUGET_PACKAGES=/tmp/opencode/aur-sms-native/packages
export TMPDIR=/tmp/opencode
DOTNET=/tmp/opencode/fivefixnative/dotnet/dotnet
"$DOTNET" build magnolie-organizer/pruefungen/sms-native/SmsProbe.csproj \
  -p:BaseIntermediateOutputPath=/tmp/opencode/aur-sms-native/obj/ \
  -p:OutputPath=/tmp/opencode/aur-sms-native/bin/ \
  -p:PhoneNumbersPath="$PWD/magnolie-organizer-windows/tests/bin/Release/net8.0/PhoneNumbers.dll" \
  -p:NuGetAudit=false -p:RestoreSources=
"$DOTNET" /tmp/opencode/aur-sms-native/bin/SmsProbe.dll
```

This is a small test executable, not a Windows product/release build or a native
Windows UI test. Local filesystem semantics are exercised on the test host.
