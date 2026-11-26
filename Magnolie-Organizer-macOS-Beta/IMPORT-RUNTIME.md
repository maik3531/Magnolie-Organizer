# Private import runtime — #785

The Mac file-import adapter reuses a reviewed projection of the current Linux
parsers. Its interpreter belongs inside the application; the user does not
install Python. `/usr/bin/python3`, Homebrew, a user virtual environment and
`/Library/Frameworks/Python.framework` are not runtime fallbacks.

## Source and deployment contract

`Resources/ImportPython.json` pins CPython **3.15.2**, source SHA-256
`8b5536d280142ecf6cdfe15d12a21ba1c65e300bbf7b28a8d0cdb849575797de`.
The [official release page](https://www.python.org/downloads/release/python-3152/)
publishes this checksum and macOS 10.15-or-newer support for its installer.
Our separately built application keeps its existing **macOS 12.7** minimum;
the upstream installer statement does not prove our build works on Monterey.

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

Final paths:

- Interpreter: `Contents/Helpers/ImportPython/bin/python3.15`.
- Standard library: `Contents/Helpers/ImportPython/lib/python3.15`.
- Parser projection and normative zone data: `Contents/Resources/ImportHelper`.

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

The first command explicitly downloads the fixed build source, verifies the
hash before extraction and rejects archive traversal, links, special files,
duplicate members and excessive expansion. An existing wrong archive or
runtime directory is retained and reported, never silently replaced. No source
download or compiler is used by the installed application.

The build directory is removed before the relocation probe. The probe also
uses a foreign working directory and deliberately wrong `PYTHONHOME` and
`PYTHONPATH`; every admitted standard-library search path must remain inside
the private runtime. The packaging step rechecks the complete file inventory,
Mach-O dependencies, signatures and relocated imports after copying the SDK.
Nested binaries are signed before the outer development application.

The existing Mac candidate workflow performs these steps for arm64 and x86_64
and preserves `runtime.json` and the actual build log. It does not silently
produce an ICS-only candidate if the required import runtime is absent.

## Evidence on 26 November 2026

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
