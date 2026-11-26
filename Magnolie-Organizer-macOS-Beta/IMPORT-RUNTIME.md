# Private import runtime — #785

The Mac file-import adapter reuses a reviewed projection of the current Linux
parsers. Its interpreter belongs inside the application; the user does not
install Python. `/usr/bin/python3`, Homebrew, a user virtual environment and
`/Library/Frameworks/Python.framework` are not runtime fallbacks.

## Verification checkpoints — 26 November 2026

The [stability verification report](STABILITY-VERIFICATION-2026-11-26.md) is
the current entry point for #121/#785 and the later #806/#808 corrections.
The published candidate is `3f3ec069895dec254c53660d14e6851cb23077cd`, tree
`176fa7f362227c92ec4d7c4bf08d09b855951ae7`.
[Run #104 / 45827353062](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062)
completed with **`success` on ARM64 and Intel**, running on 26 November 2026
from **14:15:18 to 14:49:42 Europe/Berlin** (13:15:18–13:49:42 UTC). The
[durable #104 record](verification/native-run-104.json) includes the actual
pinned XZ/CPython builds after #808, relocated runtime checks and strict nested
and outer signatures. Each architecture passed 26 runtimebuilder, 27 AirPlay
boundary and 17 ImportHelper/path tests without skips or failures.

The unchanged production Swift process and actual signed packaged helper passed
all nine checks with 22 original OR6 fields in four collections. The separate
app lifecycle passed all seven smoke criteria; each package passed 65 independent
byte checks, including the full 706-file runtime inventory and 52 Mach-O images.
The optimized Swift context has 501 cases: 495 passed, six skipped, no failures.
The package remains Debug/ad-hoc. Picker/editor/imported-data persistence, TCC,
Monterey execution and production-release acceptance remain separate. The
historical #97 result below remains bound to its own commit.

## Source and deployment contract

`Resources/ImportPython.json` pins CPython **3.15.2**, source SHA-256
`8b5536d280142ecf6cdfe15d12a21ba1c65e300bbf7b28a8d0cdb849575797de`.
The [official release page](https://www.python.org/downloads/release/python-3152/)
publishes this checksum and macOS 10.15-or-newer support for its installer.
Our separately built application keeps its existing **macOS 12.7** minimum;
the upstream installer statement does not prove our build works on Monterey.

The same contract pins **XZ Utils / liblzma 5.8.4**, source SHA-256
`4ce24038fd4221e0d13bc1a2de7a4db56e90b92b3bf75321f6c14be73f65de4b`, from
the [official release](https://github.com/tukaani-project/xz/releases/tag/v5.8.4).
The builder compiles only its static library and headers into a temporary
private prefix with the same Apple SDK, architecture and deployment target.
CPython receives the exact include directory and static archive through
`LIBLZMA_CFLAGS` and `LIBLZMA_LIBS`. The installed application does not depend
on a separately installed XZ library. Both original XZ license notices are
included in the hashed runtime inventory; `runtime.json` records the source
and static-library hashes.

`tools/import_python_bundle.py` builds the source on each matching Apple
architecture with the 12.7 deployment target, a static interpreter core and
JIT disabled. Optional SSL, GUI, database and FFI extensions are excluded.
The optional `_zstd` and `_remote_debugging` extensions are excluded too:
CPython's configure can discover and link zstd even with pkg-config disabled.
Otherwise an unrelated installed zstd could make the strict system-library
closure check fail. `zipfile` explicitly supports an absent zstd extension;
the required classic-format compression modules remain in the relocation gate.
Required parsing, compression, hashing, XML and ZoneInfo modules are imported
by the actual relocated interpreter as a build gate. Compiled runtime images
must have the selected architecture, a minimum OS no newer than 12.7 and only
Apple system-library dependencies. A Homebrew-linked extension blocks the
build. The source license travels with the runtime.

#806 binds the deployment version to exactly one macOS load command. The
runtime and outer app require `LC_BUILD_VERSION` with platform `MACOS`/`1`
and use its `minos` field. Compiler/linker `version` fields in that command
are not deployment versions. Foreign platforms, conflicting commands and
multiple deployment declarations are rejected. Only the optional AirPlay
reader permits the legacy `LC_VERSION_MIN_MACOSX` command and its own
`version` field. Architecture, system-library, RPath, inventory and signature
checks remain separate gates. The maximum permitted deployment minimum for
runtime code and the exact outer-app deployment target remain macOS 12.7.
These metadata checks do not establish execution on Monterey.

## Signed helper layout — #802

The interpreter is a complete nested `ImportPython.app`. Its main executable,
Mach-O plug-ins and ordinary resources follow Apple's
[bundle content locations](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)
and [guidance for language runtimes](https://developer.apple.com/documentation/xcode/embedding-nonstandard-code-structures-in-a-bundle).
The former mixed `Helpers/ImportPython/bin` and `lib` tree failed outer signing
in [native run #95](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45799895334):
ARM64 first reported `runtime.json`, Intel the XZ license as unsigned code.
Those files belong in resource directories.

Paths relative to the outer application's `Contents` directory:

| Content | Path |
| --- | --- |
| Interpreter | `Helpers/ImportPython.app/Contents/MacOS/python3.15` |
| Native extension modules | `Helpers/ImportPython.app/Contents/PlugIns/*.so` |
| Standard library | `Helpers/ImportPython.app/Contents/Resources/lib/python3.15` |
| Python and XZ license notices | `Helpers/ImportPython.app/Contents/Resources/` |
| Runtime inventory | `Resources/ImportPython/runtime.json` |
| Parser projection and normative zone data | `Resources/ImportHelper` |

The extensions are Darwin `MH_BUNDLE` images, built by the pinned CPython
configure's `-bundle` rule; they are placed directly in `PlugIns`. The layout
validator checks the main image's `MH_EXECUTE` type and each plug-in's
`MH_BUNDLE` type. It rejects data or subdirectories in these code locations,
Mach-O files in resources, misplaced files, links and special files.

`tools/import_python_main.c` uses CPython's public isolated `PyConfig` API.
The actual executable location determines all four Python prefixes, pointing
to the helper's `Contents`, and exactly two module paths: the private standard
library and the helper's `PlugIns`. No symlink mirror or Python framework is
needed. The builder first completes CPython's ordinary build, then compiles
this entry point with that build's own core and linker variables. The normal
build interpreter is not replaced. The runtime manifest binds the launcher's
source SHA-256 as well as the pinned CPython and XZ sources.

The helper is outside the WKWebView-readable UI directory. Native launch uses
`-I -S -B`, a fixed bundle script and bounded standard streams. There is no shell command,
renderer-specified executable, source-file path or installation operation.

## Reproducible native development build

Use a new private output directory on a Mac with Xcode command-line tools:

```sh
python3 tools/import_python_bundle.py --download \
  --source-archive /absolute/private/build/Python-3.15.2.tar.xz \
  --output /absolute/private/build/import-python
python3 tools/build_dev.py --import-runtime /absolute/private/build/import-python
```

The first command explicitly downloads both fixed build sources, verifies each
hash before extraction and rejects archive traversal, links, special files,
duplicate members and excessive expansion. An existing wrong archive or
runtime directory is retained and reported, never silently replaced. No source
download or compiler is used by the installed application.

#808 preserves each validated regular source member's archive modification
time after copying its bytes. This retains the upstream dependency order
between inputs such as `configure.ac` and distributed outputs such as
`aclocal.m4`; extraction order must not make unchanged inputs appear newer
and trigger an unnecessary `aclocal-1.18` regeneration. Make can still detect
a subsequently modified source input. The pinned archives, normalized file modes,
path/link/size checks and configure/build commands remain unchanged. The
original failure, local reproduction and correction are recorded in the
[stability report](STABILITY-VERIFICATION-2026-11-26.md). The subsequent #104
run completed the actual pinned static XZ/CPython builds and the full defined
native candidate pipeline on both architectures at the checkpoint above.

The XZ archive defaults to `xz-5.8.4.tar.xz` beside the CPython archive.
Use `--liblzma-source-archive /absolute/path/xz-5.8.4.tar.xz` to select another
local location. Without `--download`, both pinned archives must already exist.
CPython's generated `build/lib.*` extension links are accepted only when they
point exactly to the same named regular file in its own `Modules` directory.
The builder copies those bytes; the final runtime remains free of symlinks.

The build directory is removed before the relocation probe. The probe uses a
foreign working directory and deliberately wrong `PYTHONHOME`, `PYTHONPATH`,
`PYTHONEXECUTABLE` and `__PYVENV_LAUNCHER__`. It requires the exact executable,
base executable, four prefixes and two module paths described above, in
addition to the existing isolated flags and required-module imports.

The SDK output contains exactly `ImportPython.app` and a separate
`runtime.json`. Extensions are signed first, then the complete helper once.
Its schema-2 inventory is collected after signing and includes the exact
`Contents/_CodeSignature/CodeResources` seal. The manifest cannot live inside
that signed helper: writing it afterward would invalidate the seal and make
its own inventory circular.

Packaging requires the current pin and launcher source hash, the complete
helper inventory and the expected Mach-O metadata. It copies every helper
byte, including the seal, checks the copied inventory again, verifies strict
nested signatures and repeats relocated imports. It never re-signs the copied
helper. The external manifest goes to the outer application's resources;
the existing outer-app signing and strict/deep verification remain the final
packaging gates. No JSON, license or script is signed as a code object, and
there is no recursive `--deep` signing operation.

The existing Mac candidate workflow performs these steps for arm64 and x86_64
and preserves `runtime.json` and the actual build log. It does not silently
produce an ICS-only candidate if the required import runtime is absent.

The expanded workflow also includes the runtime and AirPlay boundary suites,
with the actual Darwin Mach-O platform probe. After building the signed app,
`tools/check_native_file_import_process.py` links the unchanged production
`FileImportProcess.swift` with the actual BetaCore objects and exercises the
packaged private interpreter with the original OR6 fixture. It checks the
process/protocol/result boundaries; it uses no picker, editor or saved book.
A separate `swift test -c release --jobs 2` gate checks optimized Swift code.
The packaged artifact remains the ad-hoc signed Debug development app.
Both added gates passed in #104 on ARM64 and Intel; the exact result belongs
to `3f3ec069` and the original native logs in the stability report. The process
receipt binds the linked BetaCore objects and compiled probe by hash, but those
binaries are not included in the artifact. The independent Linux audit checks
the supplied receipt and actual packaged bytes; it does not independently
rehash the unshipped objects or repeat native codesign verification.

## Original source-review evidence on 26 November 2026

Executed on the Linux source-review host:

- Seven Python tests, including seven malformed-archive subcases and four
  Mach-O rejection subcases: passed.
- Actual official source download: **27,960,396 bytes**, exact pinned SHA-256.
- Complete extraction through the bounded production extractor: passed.
- Configure flags and the case-insensitive-Mac `python.exe` build-name rule
  checked against the downloaded CPython source.
- Independent review reproduced the optional zstd linkage with the real pinned
  source's configure on Linux. Its actual `Modules/makesetup` then removed both
  optional modules after the two explicit exclusions. This is configuration
  evidence, not a native macOS compilation or a previously observed Mac failure.

Not executed here: native CPython compilation, Apple dynamic-loader tests,
codesigning, Swift/AppKit/WKWebView, Monterey runtime checks or real imports.
The workflow and build gates are prepared evidence producers, not evidence
that those native gates have already passed. The parser/UI pipeline has its
separate #785 tests and contract.

The subsequent real ARM64 and Intel CI runs, their exact commits, the #789
buildlink/liblzma correction, #802 helper-layout correction and expanded tests are tracked separately in
[NATIVE-VERIFICATION-2026-11-26.md](NATIVE-VERIFICATION-2026-11-26.md).
The #802 helper layout first passed its real Darwin build, relocation, strict nested
and outer signatures, application lifecycle and development packaging on both
ARM64 and Intel in
[run #97](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
at `215d89029df02df2dce78f35412785ec9f9b36d8`. Each job passed all 21
runtimebuilder tests and 17 ImportHelper/path tests. The
[durable evidence](verification/native-run-97.json) also records independent
byte inventories of both signed packaged helpers. Earlier native runtime
passes used the former layout. Real selected-file import/persistence through
the production UI and actual Monterey runtime acceptance remain open.
This historical checkpoint does not cover the later #806/#808 source changes
or the added process/optimized-test gates. Their current status is recorded
separately above and in the stability report.
