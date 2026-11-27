# Magnolie AirPlay receiver — source and notices

This component belongs to Magnolie Organizer issue [#721](https://github.com/maik3531/Magnolie-Organizer/issues/721).
The source is compiled into Magnolie's private `magnolie-airplay-receiver`
helper. End users do not install or launch an external UxPlay application.
The helper still contains third-party open-source code, with its notices,
license obligations and corresponding source preserved here.

## Upstream code

* **UxPlay 1.73.7**, upstream [FDH2/UxPlay](https://github.com/FDH2/UxPlay),
  tag `v1.73.7`, exact revision
  `df67c212a433cf6dda3676dd40c097900d24e645`.
* `vendor/UxPlay/uxplay.cpp` and the renderer/library sources retain their
  original copyright headers, including Florian Draschbacher, F. Duncanh,
  Juho Vähä-Herttua and other named contributors.
* UxPlay's main program is **GPL-3.0-or-later**. The full GPLv3 text is
  `vendor/UxPlay/LICENSE`. The `lib/playfair` component retains its upstream
  `LICENSE.md` (GPLv3); the `lib/llhttp` component retains `LICENSE-MIT`.
* ShairPlay/AirplayServer-derived library files retain their
  **LGPL-2.1-or-later** notices; a full LGPLv2.1 copy is also provided as
  `Licenses/LGPL-2.1.txt`. File-level notices remain authoritative.
* `UPSTREAM.json` records SHA-256 hashes of every copied upstream file,
  hashes of the current vendored files, and the locally changed paths.
  `UPSTREAM.patch` is the focused source delta; it applies with `git apply -p1`
  in an unmodified checkout of the exact pinned UxPlay revision. The new
  `receiver_protocol.*`/`receiver_registration.*` and enclosing CMake source
  in this directory are also required to build the resulting Magnolie helper.
  The unused upstream library CMake files remain as reference; only the
  enclosing `Receiver/CMakeLists.txt` defines the Magnolie build.

The source subset contains the receiver, protocol/parser and media-renderer
sources needed by that build, upstream README/manual and license files. It
does not contain Bluetooth beacon scripts, prebuilt binaries, a system service,
or a downloader. Upstream's source and retained README describe additional
options that the Magnolie host does not enable.

## Magnolie changes

The new `receiver_protocol.*`, `receiver_registration.*`, CMake file and
portable tests are licensed **GPL-3.0-or-later**. The vendored changes are:

1. Initialize the private JSONL event channel before the GStreamer macOS
   main-thread wrapper. Redirect ordinary upstream output to stderr; only
   fixed event names/codes and four ASCII PIN digits enter the event channel.
   The application discards raw stderr rather than storing it.
2. Require an explicit empty configuration file. No `UXPLAYRC`, home rc file,
   dump/recording or arbitrary pipeline settings are imported by the host.
3. Require PIN pairing with an explicit private registration file and key
   file. Read registrations with bounded bytes, lines and key counts;
   reject malformed/truncated records, symlinks, hardlinks and public file
   permissions. Persist only validated public keys, without phone names or IDs,
   and grant remembered trust only after a successful durable write.
4. Report readiness after the HTTP listener has started and the Bonjour
   registration calls have succeeded. Report media after its first received
   packet. On the final stream of a media kind ending, emit a media-snapshot
   reset followed by any surviving audio/video kind; close the session when
   neither remains. An abandoned PIN is cleared after the last control
   connection closes with no live media. Counts and sets are mutex-protected.
   A received packet is not a decoded/displayed-frame or latency measurement.
5. Relay media-runtime initialization and GStreamer bus errors as fixed codes.
   Use a strict parent-owned stdin pipe; EOF stops only this helper, with a
   three-second process-local exit fallback. Create private files under
   `umask(0077)`. Fail closed if secure random PIN generation fails.
6. Before listener startup, verify that the factories required by the fixed
   audio/video profile can actually load, including `avdec_aac`, `avdec_alac`,
   `h264parse`, `decodebin`, conversion/scaling and automatic sink factories.
   Require a loadable decoder with eligible rank and H.264 sink capabilities;
   no particular hardware decoder or native sink is forced. Missing required
   factories produce `media_runtime` and prevent `ready`. These checks do not
   prove decoding or output on a real Mac/iPhone.

The original `gst_macos_main` wrapper is preserved. Magnolie does not execute
the receiver in its Swift process, install a service, or change a system
AirPlay receiver. Screen mirroring supplies display and audio; this component
does not implement iPhone touch/keyboard remote control or Apple video DRM.

## External libraries in a deliverable

The native build requires CMake >=3.18 (for its OpenSSL-3-aware finder),
the native macOS SDK, GStreamer >=1.22, libplist >=2.0 and OpenSSL >=3.0.
OpenSSL/libplist/GStreamer must be dynamically linked from the explicitly
staged SDK. No `-march=native` is used. Bonjour comes from macOS.

The package builder must bundle the exact linked libraries and plugin scanner,
relocate their dependency paths, sign nested code, and include the actual
dependency versions, all applicable license texts, corresponding sources
and build information. This source tree does not certify an arbitrary SDK's
license completeness or a native package's signatures. In particular, copying
only this UxPlay notice is insufficient for GStreamer and its codec/plugins,
OpenSSL and libplist. Consult the exact supplied SDK's source/license manifest.

Primary upstream build references:

* [UxPlay macOS build and packaging notes](https://github.com/FDH2/UxPlay/blob/v1.73.7/README.md)
* [GStreamer private macOS deployment](https://gstreamer.freedesktop.org/documentation/deploying/mac-osx.html)
* [CMake FindOpenSSL version support](https://cmake.org/cmake/help/latest/module/FindOpenSSL.html)

## Validation boundary

`python3 Receiver/tests/test_receiver.py` compiles and exercises the actual
portable C++ event and registration code. It checks protocol framing,
redaction, media lifecycle, parent disappearance, and malformed/private
registration files. It does not compile the macOS receiver or verify AirPlay.

The native build and device acceptance must cover Intel and Apple Silicon,
PIN pairing and remembered registration, image/audio/rotation, closing and
restarting, app exit and session lock, connection loss, longer sessions,
CPU/memory and measured frame/latency behavior. Until those pass, no native
build, real iPhone connection or installable release is claimed.
