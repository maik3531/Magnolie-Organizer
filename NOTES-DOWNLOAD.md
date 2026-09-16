# Stable Notes Download

## Decision and Activation Status

Canonical URL for new Linux/Windows setup download buttons, their QR codes and
both handbook variants:

`https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes.apk`

This is **prepared source, not an activated or verified public endpoint**.
No publication is authorized by this change. In particular, the unapproved
1.0.14 candidate must not become public latest. Previously released versioned
URLs (including 1.0.13) remain unchanged during preparation. Under the current
user instruction, remove ALL old download packages after verified replacement,
including 2.0.17 and old Notes versions; do not promise permanent old URLs.
Already installed desktop binaries are not modified by download cleanup.
Publish/verify the alias before distributing desktops that contain this URL.

GitLab raw/main is the existing download hosting architecture. The spelling
`Magnolie-Organitzer` is intentional. GitHub releases may mirror the alias, but
`releases/latest` can move with a desktop-only release and is not our canonical
Notes link. No additional hosting service is required.

"Link" here means an additional **byte-identical regular APK file**, not a
filesystem symlink (GitLab raw would return link text), HTML landing page or HTTP
redirect. Android's package identity, versionCode and signing certificate stay
unchanged. The filename carries no version. Browsers and QR readers request
the APK directly; GitLab caches may briefly serve the previous approved bytes.
There is no promise of instantaneous cache invalidation or uninterrupted hosting.

## Single Definition

Only `magnolie-handbuch-stamm/web/mobile-downloads.json` defines download URLs.
Do not add an Android version to this metadata. The handbook deliberately shows
the existing product name and stable filename, not a stale release number; no new
translatable UI text was introduced.

From the canonical repository root, after changing this definition:

```sh
python3 tools/sync_mobile_downloads.py
python3 tools/sync_mobile_downloads.py --check
python3 -m pytest -q tools/test_mobile_downloads.py
```

The generator updates existing inline Linux/Windows constants, handbook JS and
the Windows shared metadata/JS and QR PNGs. Inline constants keep standalone
source archives and installed packages independent of repository-relative data
paths. Generated files are part of the reviewed source snapshot. The test fails
on drift and decodes actual PNG/SVG QR output against click URLs. Test dependencies:
pytest, qrcode, Pillow, cairosvg, numpy and OpenCV. No full product build is needed.
Changing the Android version alone changes none of these desktop outputs.

## Authorized Release Procedure

These steps are instructions for a later explicitly authorized release, not an
instruction to publish the current candidate. Existing FREIGABE.md native tests,
source freeze, certificate pin and signing gates still apply. Authorization is
either unchanged personal v1 acceptance or explicit delegated-conditional v2
authorization as specified in FREIGABE.md. Valid delegation needs no additional
personal approval stop. Further Claude execution is waived for this assignment,
not technical success, native checks or review of existing findings.

1. Finish VM-owner work and obtain native evidence plus personal or delegated
   authorization of the exact candidate SHA-256. For v2 preserve actual user text
   privately and bind the operator record only after successful tests; never claim
   operator/VM tests were personal user tests. Run `release_gate.py verify`. Changed
   sources or bytes invalidate old approval. Never manufacture acceptance.
2. In the separately authorized GitLab publication, first add the immutable
   versioned artifacts and their checksums under `Magnolie-Organitzer/` on `main`.
   Do not change the existing alias yet or overwrite an old versioned APK with
   different bytes. Old package deletion occurs only after verified replacement.
   Check remote raw versioned APK SHA-256 AND size against the approved candidate.
   A successful upload/HTTP 200 alone is insufficient.
3. BEFORE local manifest promotion, prepare the two alias files in a fresh private
   output directory. The existing verification requires the frozen bootstrap
   manifest/source inventory; it intentionally rejects a post-promotion worktree.
   This command
   revalidates exact native evidence and v1/v2 authorization before a read-only HTTPS
   request, hashes the full remote versioned APK against the candidate, stages
   identical bytes and revalidates acceptance again. It does not commit/upload,
   inspect private keys, sign, or overwrite a public worktree:

```sh
python3 tools/prepare_notes_alias.py \
  --candidate KANDIDATENVERZEICHNIS \
  --approval PRIVATER_BELEGORDNER/approval.json \
  --accept-candidate TATSAECHLICHE_KANDIDATEN_SHA256 \
  --destination /tmp/opencode/notes-alias-APPROVED-NEW
```

4. Run the separately authorized `release_bauen.sh --promote` flow. Only after
   approval it copies the verified versioned APK to `Magnolie-Notes.apk`, checks
   byte identity, and adds `Magnolie-Notes-latest-PRUEFSUMMEN.sha256`. Both enter
   the existing rollback transaction and the aggregate `PRUEFSUMMEN.sha256`.
   The original Notes candidate checksum/provenance and versioned APK are retained
   unchanged. Candidate builds never create/replace the alias. Compare these two
   promoted files with the prepared ones before proceeding. If promotion fails,
   leave the public alias unchanged. Retrying preparation must not bypass the
   frozen-source gate; preserve the already verified private set after promotion.
5. In a clean, up-to-date GitLab checkout, copy only the prepared regular alias
   and its checksum to `Magnolie-Organitzer/`. Commit both together, recording the
   approved candidate identity, Notes version and APK hash in the commit message.
   If publishing the aggregate checksum list there, update it in the same commit.
   Do not include approval logs or other private evidence. Recheck the prepared
   hashes before committing. Push normally to `main`, never force-push. The one
   Git ref update makes the alias/checksum repository change atomic. If another
   publisher advanced `main`, stop and reconcile the latest approved release;
   do not blindly rebase an older alias over a newer one.
6. After push, download BOTH the stable URL above and the versioned raw URL to
   private temporary files. Compare their complete SHA-256 and sizes to the exact
   approved APK, and fetch/check `Magnolie-Notes-latest-PRUEFSUMMEN.sha256`. Also
   check the alias at the pushed commit's raw URL (replace `main` by commit SHA).
   Check a normal browser and an actual scanned QR download and Android package
   signature/version. Check GitHub mirrors and the signed desktop update paths
   as before. Do not announce activation until the branch URL returns the approved
   bytes. Never substitute a cache-busting URL in shipped buttons/QRs.
7. Remove all superseded download packages from local and public release locations
   under the current user instruction, including 2.0.17 and old Notes APK/source
   packages. Update download/checksum listings consistently. Keep the NEW approved
   versioned files and alias; do not rewrite Git history or delete private evidence
   and source trees. Retention requirements in older work-status notes are obsolete.

Concrete read-only post-push hash check from the canonical root (set `CANDIDATE`
to the accepted directory and `GITLAB_COMMIT` to the pushed commit SHA):

```sh
python3 - "$CANDIDATE" "$GITLAB_COMMIT" <<'PY'
import json, re, sys
from pathlib import Path
sys.path.insert(0, "tools")
from prepare_notes_alias import remote_hash
candidate = json.loads((Path(sys.argv[1]) / "candidate.json").read_text())
assert re.fullmatch(r"[0-9a-f]{40}", sys.argv[2])
notes = json.loads(Path("magnolie-handbuch-stamm/web/mobile-downloads.json").read_text())["notes"]
name = f"Magnolie-Notes-{candidate['notesVersion']}.apk"
expected = candidate["artifacts"][name]
for url in (notes["url"], notes["url"].rsplit("/", 1)[0] + "/" + name,
            notes["url"].replace("/raw/main/", "/raw/" + sys.argv[2] + "/")):
    remote_hash(url, expected)
    print("Verified SHA-256 and size:", url)
PY
```

This hash check is not new approval and does not replace the checksum/browser/
signature checks above. Keep the original accepted candidate record private and
unchanged. The surrounding handbook's versioned 1.0.13 command examples describe
historical filenames, not a retention promise or the stable card's version.

The preparation gate currently uses the existing combined desktop candidate and
its Android evidence. It does not weaken this into a new Notes-only acceptance
format. Future Notes releases require no desktop source edit merely for a link;
independent Notes-only publication authorization is not invented by this change.

## Failure and Rollback

If versioned upload or remote verification fails, leave the old alias untouched.
If alias push fails, the old ref remains authoritative; retain prepared files and
check remote state before retrying. If post-push raw bytes disagree, stop the
announcement, inspect commit-pinned bytes and caching, and never call the
endpoint verified. Repository atomicity does not make separate HTTP cache reads
atomic. The checksum does not replace Android APK signature validation.

A security rollback requires its own explicit authorization: restore the previous
approved APK bytes and matching alias checksum together in a NEW GitLab commit,
preserve Git history, record the reason, push without force and repeat all
remote hash checks. Android normally refuses versionCode downgrades; moving this
download alias does not silently downgrade installed apps. A revoked vulnerable
release must not be restored merely because it was once approved.
