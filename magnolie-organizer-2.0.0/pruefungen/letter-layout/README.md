# Letter Layout Contract And Verification

## Scope And Compatibility

Updated 2026-09-12 in the canonical published-product source tree only.
Product edits are limited to Linux letter helpers, Windows `CreateLetter`, and
the letter blocks in both `anwendung.js` files. Planner/export functions outside
the letter code and concurrent changes must not be reverted or overwritten.

`einstellungen.adressen.briefLayout` still defaults to `din5008-b`. Explicit
`din5008-a`, `din5008-b`, `din5008` and `compact` selections remain preserved.
The shipped `din5008` ID means B, not A; `kompakt` remains a compact alias.
The UI, native defaults and saved-setting round trips are tested.

Form B now includes the supplied sender as separate paragraphs at the top left,
with the date at the top right. A city is included when a postal-code/city line
is recognizable in the supplied sender text; no sender name is synthesized.
The small return line remains above the recipient in the window field.
An empty sender produces neither a sender block nor return text.
Form A keeps its earlier return-line-only layout and lower date position.
Compact keeps its existing free-flow layout.

The authorized reference is an old paragraph-based letter, not a newly generated
Magnolie template: three sender paragraphs, a tab-aligned date, four blank
paragraphs, then three recipient paragraphs. Read-only ZIP analysis and isolated
LibreOffice rendering confirmed that structure. No reference text, contact data,
reference document or extracted reference XML belongs in this repository.
Only the explicitly authorized reference was read; application data was not read.
No existing user document is rewritten by this template correction.

## Recipient Handling

Both native exporters use the first nonempty structured postal address, falling
back to the flat address fields for older cards. They retain postal additions,
post boxes, street, postal code/city, region and country. Real line endings become
separate ODF paragraphs, not whitespace inside one paragraph.

Display names are retained without splitting or guessing missing first names.
Imported N components and ORG components are retained when their corresponding
editable fields still match; stale raw values must not restore edited names or
organizations. Company-only display-name duplicates are omitted. The UI sends
the contact's normalized address list without mutating the saved contact.

## Geometry And Limits

This is a DIN-5008-oriented private-letter template, not DIN certification.

| Feature | Form B | Form A |
| --- | --- | --- |
| Page | A4, 210 x 297 mm | A4, 210 x 297 mm |
| Sender header | x=20, y=20, width=85, height=25 mm | none |
| Date frame | x=125, y=20, width=65 mm | x=125, y=75.5 mm |
| Address field | x=20, y=45, width=85, height=45 mm | x=20, y=27, width=85, height=45 mm |
| Return line zone | y=57.7, height=5 mm | y=39.7, height=5 mm |
| Recipient zone | y=62.7, height=27.3 mm | y=44.7, height=27.3 mm |
| Fold marks | y=105, 210 mm | y=87, 185 mm |
| Punch mark | y=148.5 mm | y=148.5 mm |

Recipient and sender paragraphs use 10 pt Liberation Sans, reduced to 8 pt when
needed, with 4.55 mm line spacing. Recipient capacity is six rendered lines;
the B header allows five. The return line uses 8/7/6 pt. The conservative width
check rejects excessive addresses rather than truncating them. Explicit line
breaks count toward capacity. Unknown glyphs reserve one em. Printer, font and
window-envelope tolerances still require a physical trial at 100% scaling.

The explicit Writer `Frame` style parent is required: otherwise LibreOffice
can interpret an automatic graphic style as a drawing shape.

## Verification

Run from the canonical release root, sequentially with other heavy native work:

```sh
python3 -m pytest -q -p no:cacheprovider magnolie-organizer-2.0.0/pruefungen/test_letter_layout.py
NODE_PATH="$PWD/magnolie-handbuch-stamm/node_modules" bun magnolie-organizer-2.0.0/pruefungen/letter-layout/web.js
systemd-run --user --scope -p CPUQuota=100% -p MemoryMax=2G env LETTER_DOTNET=/tmp/opencode/fivefixnative/dotnet/dotnet python3 -m pytest -q -s -p no:cacheprovider magnolie-organizer-2.0.0/pruefungen/letter_cross_platform.py
```

The gate compiles the actual Windows export service and native localization in
a .NET 8 probe, not the Windows application or a production package. Only the
startup language-preference reader and GUI process launch are intercepted.
Both real web applications select a synthetic address-book contact and click
Letter. The captured bridge payload feeds Linux `brief_oeffnen` and Windows
`CreateLetter`. LibreOffice saves/reopens ODT and exports PDF with an isolated
HOME, XDG directories and user profile. Nothing accesses real app settings.

`contacts.json` covers company-only, missing first name, multiline company and
street, imported full/structured names, post boxes, complete UTF-8 addresses,
six-line capacity, empty sender/name and subsequently edited imported names.
The gate also covers de-DE/fr-FR, default B, A/B, saved aliases, compact layouts,
long sender/recipient text and yearless birthdays. Raw imported contacts are
checked separately from normalized bridge payloads.

Passing run: `/tmp/opencode/letter-layout-ab1jjojo/`.
25 cases per platform, 50 ODT/PDF files, all one page. Every DIN recipient word
is present, line breaks are visible, the field stays within its bounds, and
Linux/Windows word coordinates agree within 0.2 pt. `coordinates.json`,
`word-boxes.json`, conversion logs and synthetic PNG previews are retained there.
The three-line company example has recipient text tops at 63.13, 67.68 and
72.23 mm; six-line addresses remain below the 90 mm field boundary.
The probe compiled with zero warnings/errors. LibreOffice emitted only the
nonfatal `javaldx` warning; Writer ODT/PDF conversion succeeded.

The pre-change simple-contact rendering gate also passed. That does not prove
the reported user document's cause: the authorized sample is historical, not
the failing generated output. Confirmed defects are the absent multiline sender
header, lost structured postal components, collapsed embedded newlines and
duplicated company display names. Do not claim universal recipient invisibility.

A second pre-change probe reused the already compiled old exporter with the new
synthetic cards: `/tmp/opencode/letter-before-comparison-de5cfngl/`.
The imported postal example had only one recipient paragraph instead of six;
the multiline company example rendered three instead of six separate lines;
the address-only structured card was rejected. `comparison.json` records the
pre-change failures without reference data. All corresponding corrected cases
pass in the evidence directory above.

Authorized reference SHA-256, identical before and after read-only inspection:

```text
before 8ea45238fe00cceb368cc6c7b4b2f82e24d0d07db432795386fdc59b26dd3665
after  8ea45238fe00cceb368cc6c7b4b2f82e24d0d07db432795386fdc59b26dd3665
```

## Localization And Remaining Validation

No new visible msgids were introduced. The inaccurate return-line-only sender
hint was removed from both letter settings blocks; existing translated labels,
multiline placeholder, layout guidance and capacity error are reused.
No 20-language catalog rewrite is needed for these code changes.

The earlier handbook handoff describing B as return-line-only is superseded.
The handbook owner should coordinate a narrowly scoped correction of that
description in all 20 languages, without touching unrelated planner work.

Full Windows application compilation, Windows GUI/save-dialog/file-association
testing and a physical envelope trial remain later validation steps. No VM,
production build, installer, package, publication, commit or push was started.
