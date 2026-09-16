# Native PDF Text-Layer Investigation

## Status

The Hindi and simplified-Chinese failures are real PDF text-encoding failures in
the tested WebKit/Skia path, not missing translations or a pdftotext normalization
error. No production font, print engine, catalog, package dependency or system
font configuration was changed. The regression probes deliberately fail on the
affected backend; they are not marked as expected successes.

Tested environment:

| Component | Version |
| --- | --- |
| WebKitGTK | 2.52.6 (`2.52.6-0ubuntu0.24.04.1`) |
| Actual PDF producer | Skia/PDF m145 |
| Pango | 1.52.1 |
| Cairo | 1.18.0 |
| HarfBuzz | 8.3.0 |
| FreeType | 2.13.2 |
| Poppler / pdftotext | 24.02.0 |
| Independent extractor | pypdf 4.0.2 |

Cairo is installed but is **not** the producer of WebKit's PDF in this build.
The same-font Pango/Cairo output below is an independent synthetic control, not a
replacement implementation of the handbook layout.

## Reproduction

From `magnolie-handbuch-stamm`, with existing fonts and native GTK/WebKit:

```sh
xvfb-run -a python3 -B pruefungen/pdf_textlayer_probe.py /tmp/opencode/pdf-textlayer-repro
python3 -B -m pytest -q -p no:cacheprovider pruefungen/test_pdf_textlayer.py
xvfb-run -a python3 -B pruefungen/locale_pdf_test.py /tmp/opencode/pdf-textlayer-20-baseline
```

The first command writes synthetic HTML, DOM/font-load evidence, WebKit PDF,
Pango/Cairo PDF, extracted text and `results.json`. It checks that the DOM still
contains the exact input and every explicitly loaded font completed loading.
Font paths and SHA-256 values are recorded. It installs nothing. Optional pypdf
inspection records each font's complete ToUnicode CMap, null mappings and
multi-codepoint mappings; without that diagnostic module the report says that
CMaps were not inspected. It is not an application runtime dependency.

The sample round-trip comparison uses NFC, not NFKC. It must reject missing
Indic clusters, substituted CJK radicals and reversed source characters.
Whitespace is separately reported by `exactIncludingSpaces`. The isolated
unshaped Hindi and disabled-`locl` cases are diagnostic contrasts, not proposed
production workarounds.

## Evidence And Cause

`पत्र लिखना` becomes `प लखना`. In the reduced PDF, the Devanagari font has
ToUnicode entries including `<010D> <0000>` and `<0261> <0000>`. HarfBuzz shaping
of the original string with the installed Noto Sans Devanagari TTF produces:

| Glyph | UTF-8 cluster offset | Meaning | Nominal Unicode mapping |
| --- | ---: | --- | --- |
| `002E` | 0 | `प` | U+092A |
| `010D` | 3 | `त्र` conjunct | none |
| `0261` | 13 | contextual `ि` form before `ल` | none |
| `0036` | 13 | `ल` | U+0932 |

A scan of all Unicode scalar values with HarfBuzz's nominal-glyph API found no
nominal scalar for those shaped glyphs. This is normal for contextual forms and
conjuncts, not evidence of a corrupt font. Their original Unicode clusters must
be supplied to the PDF writer. Switching between installed Noto Sans and Noto
Serif Devanagari, or loading each TTF directly via `@font-face`, did not restore
the missing information. The unshaped control extracts correctly.

For Chinese, the original handbook PDF uses `NotoSansCJKjp-Regular` fallback.
Chinese shaping on the JP face produces localized glyphs `2ADE` (`写`) and
`27D4` (`信`) without nominal mappings in that face. Both acquire nominal mappings
in the SC face. Explicitly selecting Noto Sans CJK SC therefore restores the
title, but **does not fix the complete text layer**:

| Glyph | Possible nominal scalars | Observed PDF substitution |
| --- | --- | --- |
| `AC74` | U+2EDA, U+9875 | `页` becomes `⻚` |
| `AAAB` | U+2FAF, U+9762 | `面` becomes `⾯` |

The SC control `页面 门 贝` extracts as `⻚⾯⻔⻉`. NFKC repairs some compatibility
radicals, but does not repair U+2EDA, U+2ED4 or U+2EC9. Applying more substitutions
in the test would hide a real copy/search problem. The stricter reduced Japanese
control also exposes a compatibility-radical substitution (`手` to `⼿`), even
though the older NFKC-based handbook title check passes Japanese. A passing title
check is not proof of complete text fidelity in the remaining languages.

Poppler drops null mappings; pypdf independently returns U+0000 at the same
positions (61 nulls in the combined reduced WebKit sample, zero in the Cairo
control). Hindi fails in CID TrueType output as well as in the full handbook's
Type 3 output. The issue is therefore not simply "Type 3 is invalid" or "TTC is
unsupported". The Cairo reference preserves every reference sample with the same installed
font families and emits multi-codepoint mappings such as `<0924094d0930>`.

## Upstream Boundary

Inspected upstream sources at tag `webkitgtk-2.52.6`:

- [FontCascadeSkia.cpp](https://github.com/WebKit/WebKit/blob/webkitgtk-2.52.6/Source/WebCore/platform/graphics/skia/FontCascadeSkia.cpp): `FontCascade::drawGlyphs` passes glyphs and advances to `Font::buildTextBlob`.
- [FontSkia.cpp](https://github.com/WebKit/WebKit/blob/webkitgtk-2.52.6/Source/WebCore/platform/graphics/skia/FontSkia.cpp): `Font::buildTextBlob` uses `allocRunPosH`/`allocRunPos`, filling glyph IDs and positions, not original text and clusters.
- [GraphicsContextSkia.cpp](https://github.com/WebKit/WebKit/blob/webkitgtk-2.52.6/Source/WebCore/platform/graphics/skia/GraphicsContextSkia.cpp): `drawSkiaText` forwards that blob to `SkCanvas::drawTextBlob`.
- [SkPDFDevice.cpp](https://github.com/WebKit/WebKit/blob/webkitgtk-2.52.6/Source/ThirdParty/skia/src/pdf/SkPDFDevice.cpp#L1019-L1064): extended Unicode mappings and `/ActualText` for complex or mismatching clusters require `c.fUtf8Text`. Glyph-only runs do not provide it.
- [SkPDFMakeToUnicodeCmap.cpp](https://github.com/WebKit/WebKit/blob/webkitgtk-2.52.6/Source/ThirdParty/skia/src/pdf/SkPDFMakeToUnicodeCmap.cpp): serializes the nominal glyph map and the optional extended map.

The effective defect is loss of original Unicode/cluster information at the
WebKit-to-Skia text boundary. A safe general fix must propagate original text,
cluster boundaries and bidi ordering through the printing glyph runs. Skia can
then associate the correct text with the existing visible glyphs. Proper native
cluster `/ActualText` is not a duplicate invisible text overlay.

The Python/JavaScript handbook cannot recreate this information reliably from
an already emitted glyph-only PDF. Global CMap substitutions are ambiguous when
different source characters share a glyph. No such postprocessor, overlay,
outline-only export, browser fallback, shaping suppression or insecure WebKit
downgrade was introduced.

## Bounded Chinese Workaround Proposal

The already installed `DroidSansFallbackFull.ttf` preserves the reduced Chinese
sample, including spaces, through both system-family selection and direct font
loading. An **in-memory-only** full-handbook experiment preferred this font after
the existing Latin families for Chinese body/headings, SVG text, code/key labels
and the inline Georgia closing paragraph. It kept 115 A4-landscape pages and
removed the null CMaps. All 4,738 Chinese-bearing body text nodes were found with
NFC comparison; one required the existing CSS uppercase transformation
(`Android` to `ANDROID`). This was not a complete reading-order or PDF/UA audit.

This is a corpus-bounded workaround, not a general backend repair. It changes
the CJK typeface, needs visual acceptance, must be checked against future text,
and does not help Hindi. No production font preference was applied.

Any adoption requires coordination with the main packaging owner: the handbook
does not currently guarantee this font on every platform. The installed package
is `fonts-droid-fallback`; its copyright file identifies Google copyright and
Apache License 2.0. Bundling would require the unchanged font and appropriate
license/copyright notices, not a system-font configuration change. No font was
bundled during this investigation.

Preferred resolution remains a security-supported WebKit build with the text
cluster propagation fixed and independently validated, coordinated with the
package/AppImage owners. The Pango/Cairo control is not a drop-in HTML renderer.

## Accessibility Limits

The current handbook PDFs are untagged. Correct Unicode extraction alone does
not establish PDF/UA conformance, image alternatives, logical structure,
two-page reading order, keyboard navigation or screen-reader usability. The
existing 20-language title/layout probe and the stronger synthetic probe retain
their failures; neither result should be presented as an accessible-PDF release
approval or a promise of error-free output.
