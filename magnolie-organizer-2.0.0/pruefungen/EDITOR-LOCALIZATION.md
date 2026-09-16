# Editor localization and native Undo/Redo

Canonical root: `/home/maik3531/Downloads/Magnolie-GPT/magnolie-organizer-veroeffentlicht`.

## Implementation

- Both desktop `anwendung.js` sources expose Undo/Redo in `zeigeBearbeitenMenue`.
  Availability comes from the engine's `queryCommandEnabled` after restoring the
  captured editable target and selection. Activation checks availability again.
- Menu history and writing-sheet keyboard history share `nativeTextBearbeitung`.
  They use native `execCommand`, preserve native undo transactions, and feed the
  existing trusted-input/draft/save path. There is no JavaScript history stack.
- ASR05 selection/content/composition/readonly/inert guards and the single
  untagged clipboard-reply slot remain in use. History invalidates captured
  clipboard work, including undo followed by redo to identical content.
- Formatting menu glyphs and names go through gettext, like the toolbar.
- Tab help uses the same actual `MagnolieI18n.gettext` catalog resolution as the
  rest of the interface. Regional `ja-JP`, `de-AT`, `nb-NO`, `zh_CN` and `zh-CN`
  resolve to their supported catalogs. Malformed `zhCN` follows the existing
  English fallback, both explicitly and through mocked system-language input.
- `Regular typeface` replaces the ambiguous UI label `As usual (print)`.
- `WindowsSpellChecker.cs` uses the existing `NativeLocalization` boundary for
  both application-owned errors. Its actual language-selection method is tested
  with an injected support predicate, avoiding COM in the resource fixture.
- Windows help describes Windows language options and Basic typing installation.
  It explicitly states German suggestions for a German interface and English
  otherwise; 20 translated UI languages do not imply 20 suggestion dictionaries.

## Manual translations and regeneration

`tools/editor_locales.json` contains eight manually authored messages for all
20 UI languages: en, de, ar, be, cs, da, es, fr, hi, hsb, it, ja, nb, nl, pl,
pt, ru, tr, uk and zh_CN. English is the canonical source-language branch; the
existing gettext structure has 19 translated PO catalogs.

| Locale | Undo | Redo | Regular typeface |
|---|---|---|---|
| en | Undo | Redo | Regular typeface |
| de | Rückgängig | Wiederholen | Druckschrift |
| nb | Angre | Gjør om | Trykkskrift |
| fr | Annuler | Rétablir | Caractères d’imprimerie |
| es | Deshacer | Rehacer | Letra de imprenta |
| ja | 取り消す | やり直す | 通常の書体 |
| zh_CN | 撤销 | 重做 | 常规字体 |

These typeface labels refer to ordinary printed letterforms, contrasted with
handwriting, rather than sending pages to a printer. Norwegian `Select all` is
`Merk alt` in both desktop catalogs.

Regeneration order, from the canonical root:

```sh
python3 magnolie-organizer-2.0.0/werkzeuge/desktop_pot_merge.py --report-dir /tmp/opencode/editor-localization-merge
python3 tools/editor_locales.py --apply
python3 tools/editor_locales.py --preservation-baseline /tmp/opencode/editor-localization-merge/before.json
```

Use a fresh report directory for a new merge. The merger runs the canonical POT
extractors and `msgmerge --no-fuzzy`. The editor tool applies only the explicit
manual editor keys and Norwegian correction, then invokes the canonical JS and
native JSON compilers. Linux MO files are rebuilt; Windows MO files are tested
as intermediate resources because the native Windows application ships JSON.
All active catalogs are checked for empty/fuzzy entries. New messages are also
checked against accidental English copies and placeholder changes.

The preservation comparison passed for **83,769 pre-existing translated
entries**, including obsolete entries and OpenHolidays work. The two Norwegian
`Select all` corrections are explicitly excluded from that unchanged-value
comparison and separately checked against `Merk alt`.

## Verification commands and scope

Evidence directories must exist before running the isolated WebKit commands:

```sh
sh magnolie-organizer-2.0.0/pruefungen/editor_localization_isolated.sh --web linux --menus-only
sh magnolie-organizer-2.0.0/pruefungen/editor_localization_isolated.sh --web windows --menus-only
sh magnolie-organizer-2.0.0/pruefungen/editor_localization_isolated.sh --web linux --history-only
sh magnolie-organizer-2.0.0/pruefungen/editor_localization_isolated.sh --web windows --history-only
MAGNOLIE_CONTEXT_EVIDENCE=/tmp/opencode/editor-asr05-regression sh magnolie-organizer-2.0.0/pruefungen/context_edit_isolated.sh --web linux
MAGNOLIE_CONTEXT_EVIDENCE=/tmp/opencode/editor-asr05-regression sh magnolie-organizer-2.0.0/pruefungen/context_edit_isolated.sh --web windows
systemd-run --user --scope -p MemoryMax=6G -p CPUQuota=200% timeout --kill-after=5s 240s python3 Magnolie-Organizer-Windows-2.0.0/tests/editor_localization_native.py
python3 -m pytest -q tools/test_editor_localization.py
python3 -m pytest -q magnolie-organizer-2.0.0/pruefungen/test_locale_completeness.py magnolie-organizer-2.0.0/pruefungen/test_pot_source_coverage.py Magnolie-Organizer-Windows-2.0.0/tests/test_windows_pot_source_coverage.py
MAGNOLIE_PYTHON=/usr/bin/python3 /home/maik3531/.local/bin/deno run --unstable-detect-cjs --cached-only --allow-read --allow-write=/tmp --allow-env --allow-run=/usr/bin/python3 Magnolie-Organizer-Windows-2.0.0/tests/localization-completeness.js
```

WebKit tests load each complete production frontend and its actual i18n core.
They inspect all ten rendered menu labels and invoke all ten production click
handlers in all 20 languages. The six common editing actions use real XTest
mouse activation; formatting handlers use DOM `.click()`. Typing and keyboard
history use native XTest. Selection setup, locale/system mocks and negative
composition events are explicitly synthetic. Clipboard reads/writes are
captured in an in-memory bridge fixture, never the host clipboard.

The menu test also checks native Undo/Redo enabled states, focus/selection,
trusted input events, Tab help, typography and Windows help. Geometry is limited
to the actual menus in one desktop viewport for each language. History tests
cover note/custom rich editors, diary textarea and title input, pending cut/paste
invalidation, readonly/inert/composition guards, cancelled `beforeinput`, stale
focus, and keyboard menu activation where the existing modal focus rules allow
it. The diary modal's existing focus trap excludes body-level popup buttons;
diary testing uses mouse menu actions and writing-sheet keyboard history.

Each WebKit invocation has a 240-second deadline, two-CPU affinity, private
Xvfb/D-Bus/home/dev/network namespaces, an ephemeral WebKit context and a 6-GiB
isolated-RSS watchdog. The C# check builds **one** offline net8.0 fixture under a
6-GiB cgroup and two-CPU limit, with a four-minute outer deadline. It links the
actual `WindowsSpellChecker.cs` and `NativeLocalization.cs`; only the persisted
preference reader is stubbed to avoid touching a real profile.

## Executed results — 2026-09-14

All six final focused WebKit invocations exited 0 on **WebKitGTK 2.52.6**:

| Source | Menu/locale groups | Menu runtime | History groups | History runtime | Existing ASR05 cases | ASR05 runtime |
|---|---:|---:|---:|---:|---:|---:|
| Linux | 26 | 211.01 s | 7 | 49.15 s | 91 | 158.29 s |
| Windows | 26 | 214.64 s | 7 | 50.37 s | 91 | 150.46 s |

That is **248 passing focused case groups**, including all ten menu handlers
for all 20 languages on both source trees. The 26 menu/locale groups comprise
20 language cases and six regional cases, each with explicit and mocked-system
resolution. The maximum sampled isolated RSS across these final runs was
734,184 KiB (under 718 MiB). All invocations stayed below four minutes.

- Actual C# spellchecker/localization fixture: **234 assertions passed** for
  20 languages and regional/system cases; one project compiled in 2.14 seconds.
  The portable net8.0 fixture emitted two CA1416 warnings for existing
  Windows-only COM release calls, and zero compiler errors.
- `tools/test_editor_localization.py`: **3 passed**, including a real disposable
  macOS projection and exact shared editor-function parity.
- Existing Linux completeness and both POT extraction/source-coverage tests:
  **21 passed**.
- Existing Windows localization completeness test: **passed under Deno**,
  including complete PO/JS/native resource equality. Its VM catalog payload is
  JSON-normalized before `deepStrictEqual` so cross-realm prototypes do not
  falsely report stale catalog data.
- Preservation check: **83,769 previously translated entries retained**.
- Scoped `git diff --check` and isolated-runner shell syntax check: **passed**.

The broader `pruefungen/test.js` jsdom suite was attempted but could not start:
Node is not installed, and Deno did not resolve its bare `jsdom` dependency via
`NODE_PATH`. It is not counted as a passing suite. Its expected typeface label
and menu-entry list were updated; the actual editor paths are covered by the
native WebKit checks above.

Final report files:

- `/tmp/opencode/editor-localization-webkit/{linux,windows}/editor-localization-menus.json`
- `/tmp/opencode/editor-localization-webkit/{linux,windows}/editor-localization-history.json`
- `/tmp/opencode/editor-asr05-regression/{linux,windows}/context-report.json`
- `/tmp/opencode/editor-localization-merge/before.json` and `missing-new-keys.json`
  (the latter records the merge-time queue, before the manual translations).

The reports' frontend hashes match the final source files:

```text
Linux    9ff373b57eee2ba9ceb3cd93078433dceb844c06d60c30bb0b3bc300e11f5830
Windows  c7b3702f35421ae35e0886c57881a745edb1ed367fc6798016b0acc0e0ce4615
```

## Desktop and Beta qualifications

Native browser evidence uses WebKitGTK for both desktop source trees. It is not
installed Windows/WebView2 or macOS/WKWebView validation. The C# fixture tests
the actual application-owned error paths and resource resolution, not Windows
COM dictionary installation.

The existing macOS native Undo/Redo aliases agree with the common catalogs.
`Resources/native-extra-i18n.json` adds the 19 manually translated `Clipboard
write failed.` aliases. The actual macOS projector is checked in a disposable
directory against current sources; no source freeze or native-validation flag
is recorded. Its shared editor helpers and generated native resources are
verified against the desktop sources and manual translations.

Main integration must regenerate frozen Beta projections after desktop freeze.
The existing Tablet projection is stale and is not qualified by these checks.
No production package/APK, VM, phone, real profile or host clipboard is used.
