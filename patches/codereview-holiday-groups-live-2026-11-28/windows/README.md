# #854 / #857 — Windows school groups, verified provider contract

## Delivery and dependency

`be-nl-windows-854-857-after-855-856.patch` is a source patch for the Windows
OpenHolidays provider, its regression program and shared captured-response
fixtures. Apply after **#855 and #856**, or their combined alternative, on
main `1749c92eb42801c38eaba31b272d8c0e27be9164`. It does not apply directly
to unmodified main. The prerequisite artifact is
`a473d769d590cf2a2771f2e890727025230a0f80`,
`patches/codereview-holiday-live-austria-2026-11-28/holiday-cache-855-plus-austria-856.patch`.
Its SHA-256 is `ee7179924bbdb0072259eb9b2f5e1bd14e10df943f458148af2b17ca4e8c5e1e`.

The input Windows blobs after that prerequisite were checked exactly:
`BridgeDispatcher.cs` = `f61ccaa3c0e4b0fe517a448bd829d82b35223820`,
`OpenHolidayData.cs` = `217476e0b67c8d37897e08fda696fd7d88640b6d`.
`SOURCE-MANIFEST.json` binds every changed/new file by SHA-256 and Git blob.
No product-main merge, package release or UI group activation is included.

## Corrected behavior

The six verified school groups are BE-DE, BE-FR, BE-NL, NL-NO, NL-MI and NL-ZU.
School queries use `groupCode`. Selecting groups issues the public-holiday
request once per year, country-wide, with its own empty-region coverage.
It never sends the school group as an administrative subdivision.

Explicit valid `groups` supply school identity. Accompanying valid local
`subdivisions` are normal provider output: the provider can expand its group
membership during import. Their presence alone does not make a record a
municipal exception. Group and subdivision identities are not unioned into
one school scope. Malformed, foreign and unknown group references do not
inherit the requested group. Invalid ancillary subdivision data is rejected.

Explicit `regionalScope: Local` and subdivision-only rows remain local:
country queries may retain valid administrative rows without authorizing
school-wide cache replacement; a group query does not promote them. An
`Exception` tag alone is not treated as a local-scope discriminator. Present
malformed/unknown scope metadata cannot authorize cache replacement. Missing
scope metadata retains compatible explicit-group handling. Nationwide rows
with all three known groups remain accepted, including valid provider
subdivision enumeration; a partial group list contradicts a nationwide claim.

Empty/nationwide-only school replies do not prove group-calendar coverage.
A country school reply must contain all three explicit groups before it may
authorize replacement. DE/AT/CH behavior and the Austrian provider/ISO mapping
remain covered by the existing tests. School group labels are not called
“states” or “cantons”.

## Actual checks

| Program | Exact prerequisite | Final candidate |
| --- | ---: | ---: |
| New provider cases, including captured real HTTP responses | 2/90 | **90/90** |
| Existing #855/#856 coverage and Austrian mapping cases | — | **43/43** |

All runs used SDK **10.0.404**, runtime **10.0.15**, on Linux. The isolated
test target was `net10.0`; no product target was changed. All three C# builds
finished with zero warnings and zero errors. The Python launcher emits exact
production bridge methods, the complete production `OpenHolidayData.cs` and
the real setup-normalizer source. HTTP transport, the form callback and
gettext are controlled doubles. The complete WinForms application was not
built or run. The 88 failing before-cases are unmet test requirements, not
88 independent bugs.

Eight cases replay raw 2026 country/group-specific provider JSON: both
country responses and all six group queries. They compare every resulting
school period's dates, title and explicit group identities, with legitimate
duplicate grouping, plus the returned replacement scopes. Raw response bytes,
request metadata, hashes and data-license attribution are included under
`contracts/fixtures/holiday-groups-2026-11-28/`.

The patch passed `git apply --check`, index application, exact byte comparison,
reverse check/application and restoration of all original bytes; all new files
were removed on reversal. This was an isolated tree containing all participating
exact source blobs, not a full product checkout. See `PATCH-CHECK.json`.

## Important discarded initial assumption

The first Windows candidate copied the earlier strict cross-platform rule
that rejected any school group row with subdivisions. Its 72 synthetic cases
passed, but replay of real provider output disproved that rule: each Dutch
group's six matching periods became zero returned periods. The final code and
tests were corrected against the upstream import and filter contract before
delivery. The initial synthetic success is not claimed as validation of the
final provider contract. Captured-byte inspection and final regression evidence
are kept separately.

## Repeat

After applying the prerequisite and this patch, run from the checkout:

```sh
python3 magnolie-organizer-windows/tests/holiday-school-groups.py \
  --source-root . --build-dir /tmp/magnolie-holiday-groups-854 \
  --dotnet dotnet --framework net10.0
```

The launcher also accepts `net8.0` or `net9.0` when the corresponding SDK and
runtime are already present; those targets were not executed in this run.
It downloads or installs nothing. For a baseline comparison, use the same
launcher/case/fixture files with `--source-root` pointing to the exact
prerequisite tree, and supply `--provider-fixtures` if running a standalone
artifact copy. The expected baseline exit is 1; the candidate exits 0.

## Remaining boundaries

The common GUI/MCP cache contract must explicitly accept nationwide public
coverage while a school group is selected; the earlier frontend does not yet
do so. The group choice is therefore not activated by this provider patch.
Native Windows/GUI/package behavior, ongoing provider availability, official
calendar completeness and the remaining first-run/manual integration are
separate checks. The raw captures prove actual service replies at their
recorded timestamps, not future provider availability or end-user GUI behavior.
