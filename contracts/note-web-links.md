# Note web-link actions (#608)

The Organizer recognizes explicit `http://` and `https://` links in the current
note and offers separate browser actions beside the existing note actions. It
also exposes safe HTTP(S) targets of existing HTML anchors, using the actual
target rather than guessing from their labels. Identical targets are combined.

Recognition does not edit the contenteditable surface, stored note text/HTML,
revision or undo history. It does not fetch, resolve or preview URLs. Opening
requires an explicit link activation through the existing native external-link
route. This is not a new background synchronization or network permission.

## Boundaries and safeguards

- Bare domains and relative URLs are not guessed into web addresses.
- Sentence punctuation and surplus closing brackets are excluded from detected
  plain-text URLs; balanced parentheses and IPv6 host brackets remain intact.
  Explicit existing HTML targets are validated without punctuation trimming.
- Other schemes, missing hosts, embedded credentials, backslashes, control and
  bidirectional-control characters, and ambiguous embedded scheme prefixes are
  not offered as web actions.
- URLs are bounded to 4096 characters and recognition to 32 actions. Target
  validation uses the local URL parser, not a DNS or HTTP request.
- The displayed note and existing anchors are never rewritten by recognition.
  Existing manual link insertion and ordinary note editing remain separate.

## Evidence scope

`magnolie-organizer-windows/tests/note-web-links.js` exercises both complete
source frontends: positive/negative boundaries, original HTML targets, dedup,
explicit activation, invariant stored content/revisions, and typing without
generated anchors. It is registered in the standard frontend test runner.

The existing isolated native editor harness has a `--web-links-only` mode. With
each source frontend, real WebKitGTK keyboard activation yields a user-gesture
navigation to the exact target; the test blocks navigation before any external
launch. Stored content is unchanged, and real typing/undo adds no generated
anchors. The harness is offline with a private X server and no host profile or
devices. Testing Windows source in WebKitGTK is **not** an installed Windows
WebView2 acceptance test or package release approval.
