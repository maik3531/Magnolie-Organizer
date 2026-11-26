# Current shared sources for the Mac candidate — #783 / #121

The Mac UI generator reads the current checkout of `magnolie-organizer/web`.
The candidate workflow previously replaced the common product trees with the
published `v2.0.30` commit `067c38934b539943d8e1720abafd8a80b401d797` immediately
after checkout. A newer Mac port commit therefore did not make its bundled
desktop UI current. The visible `2.0.30-beta.1` version did not reveal this.

## Corrected source selection

The Mac job now keeps the selected workflow checkout intact. It records the
exact `GITHUB_SHA` as both `portCommit` and `desktopCommit`, plus the Git blob
identity, executable mode and SHA-256 of every tracked product/adapter/build input covered by
`tools/candidate_sources.py`. A different HEAD, edited or staged source,
untracked non-ignored source, missing input, or changed final proof blocks the
candidate. The check never repairs or replaces the source tree.
Actual file bytes are hashed as Git objects and compared directly to HEAD;
`assume-unchanged` and `skip-worktree` cannot hide stale input. Both SHA-1 and
SHA-256 repositories use their actual object format.

Catalog preparation still runs before the existing explicit freeze. Generated
catalogs and payloads are covered by `SourceFreeze.json` and
`Generated/ProjectionManifest.json`; their reproducibility is checked by
`project_ui.py` and again by the existing native builder. The tracked-source
proof is rechecked before packaging and archived with that freeze and the
existing build/smoke evidence. These are complementary checks: a source commit
does not by itself certify generated output or native behavior.

The Tablet job and its `DESKTOP_COMMIT` stay on their existing reference. Tagged
codec fixtures and narrow historical adapter comparisons keep their original
references. A complete old desktop UI without the common contact-copy contract
introduced for #776 is explicitly unsupported by the current Mac projector;
historical fixtures are not silently upgraded into a current candidate.

## What catches up automatically

The audit compared current main `00776ce70e155c7a607ed55a4502d6fcee5a860c`
with the published reference. The Mac projection already accepts the current
shared tree. Representative current local UI/model changes are:

| Common change | Source commit | Mac handling |
| --- | --- | --- |
| Calendar spread arrow navigation (#744) | `84dd54e8` | Current shared handler; generated-Mac DOM regression included |
| Notes search by actual creation/modification date (#720) | `bcb2b2e4` | Current shared search; all 30 original search assertions run in generated Mac UI |
| Equivalent messenger targets preserve local actions (#757) | `ef14afd0` | Current shared merge logic; launching still uses Mac's separate native policy |
| Note web-link recognition without rewriting stored text (#608) | `9b847b55` | Current shared renderer; native external handlers remain separately bounded |
| Contact email normalization (#603) | `a2055d26` | Current shared model; it does not grant provider write access |
| Opaque DISPLAY alarm preservation (#444) | `f7c94727` | Projector verifies the accepted current helper hash instead of reinstalling the old helper |
| Welcome-note first-save normalization (#437) | `846075c9` | Current canonical normalized form is accepted |
| Drawing pointer ownership/release (#467/#468) | `4f228fc3`, `cbdc0876` | Reviewed current release handler plus existing canonical finish-redraw adapter |
| Normative GUI time-zone runtime (#447/#657) | `f190cc2b` | Already-promoted current hooks are verified and retained; no second legacy runtime is installed |

Occurrence identity, timezone hooks, drawing and display-alarm replacements
remain exact-anchor/hash checked. Source drift fails the build instead of
falling back to a stale generated UI. Startup readiness, ordinary-save and
restore fences remain the Mac implementations; shared frontend presence does
not substitute for their native acceptance.

## Deliberate Mac integration boundary

Mac does not require a separate Magnolie Notes companion app. Its supported
Apple calendar, Contacts, Reminders and Apple Notes paths use Mac-specific
native access and reviewed local copies. Existing KDE Connect clients remain
a valid route for supported phone functions; availability of the external
client and implementation of a particular Magnolie native adapter are separate
facts. This patch adds no new sync transport, pairing, background service or
source-write grant.

`check_current_sources.py` boots the actual newly generated UI and compares its
traffic with the actual Swift `Command` allowlist. Every currently
unimplemented desktop command is rejected before native delivery. Imported
provenance-shaped metadata and a saved automatic-sync preference do not widen
that list. A rejected legacy `sync` request may record its existing local error
diagnostic; this is not a native sync operation. Existing local-copy commands
remain reachable, and the existing copy-import suites separately verify their
actual transactions without acquiring source synchronization/delegation rights.
The new native `CandidateCapabilityTests` also exercise `Request` rejection of
currently missing transports and unauthorized sync fields on ordinary saves.
These are current implementation checks, not a permanent exclusion of KDE
Connect or future explicitly implemented Mac integrations.

The complete handoff now adds #785's current classic-file/OR6 parser path and
#786's separate bounded native field-sync command. They have their own
implementation, authorization and test contracts; #783 alone does not provide
either capability. The legacy desktop `sync` command remains unavailable.
Full archive import, local-program discovery, automatic/native create/delete
sync and Apple Notes writeback remain explicitly open. The final combined
test record supersedes earlier per-patch input hashes only for tests actually
rerun on those combined inputs.

## Evidence and limits

The historical green run
[42562106430](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42562106430)
used Mac/adapter source `cbdc0876` **with published desktop source `067c3893`**.
Earlier runs such as `42506117045` at port source `0c22df32` used the same
published source policy. Their native results must not be presented as tests of
today's shared UI or new #770–#777 imports.

Local checks for this patch passed on Linux with Node 24.22.3 / JSDOM 26.1.0
and synthetic native transport: **7 source-selection tests** in each of actual
SHA-1 and SHA-256 Git repositories; **27 current-source/capability assertions**
plus **30 original date-search assertions**. All **181 currently unavailable
desktop commands** were blocked before native delivery.

```sh
python3 Magnolie-Organizer-macOS-Beta/tests/test_candidate_sources.py
python3 Magnolie-Organizer-macOS-Beta/tools/check_current_sources.py --js-runtime node
```

The first uses actual temporary Git repositories, including the old restore
recipe against a newer commit with the **same visible version**. The second
uses the existing JSDOM installation (`MACOS_BETA_JSDOM` can select it) and
current source inputs. It is wired into the existing Mac workflow before native
tests. The two new Swift test methods are prepared for that workflow; no Swift/macOS
execution, updated native candidate, signing/notarization or release approval
is claimed by these host checks. Both existing macOS architecture jobs and the
real bundle lifecycle must pass again with the new recorded source policy.

## Repeat the exact source record/verify steps

Use a clean reviewed checkout. The workflow binds the selected commit to
`GITHUB_SHA`; the local example below uses the commit that the reviewer has
explicitly selected. Keep the proof outside the source tree and use a new path:

```sh
candidate_commit=$(git rev-parse HEAD)
candidate_proof_dir=$(mktemp -d)
python3 Magnolie-Organizer-macOS-Beta/tools/candidate_sources.py record \
  --expected-commit "$candidate_commit" --proof "$candidate_proof_dir/sources.json"
# Prepare catalogs, freeze/generate, run the checks and native build according
# to .github/workflows/ports-2.0.30.yml. Do not change tracked source inputs.
python3 Magnolie-Organizer-macOS-Beta/tools/candidate_sources.py verify \
  --expected-commit "$candidate_commit" --proof "$candidate_proof_dir/sources.json"
```

The integrated #776 source was checked again: 27 capability/current-UI
assertions, 30 original note-search assertions and 181 unavailable-command
boundaries passed. Its canonical frontend SHA-256 is
`8166790025d0ba8bf4495b73346ba42cbb6eac8dd98c918eea40ec696ef69b63`.
This is a source/UI check, not native execution.
