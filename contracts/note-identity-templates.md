# Legacy welcome-note identity (issue #22)

`note-identity-templates.json` records the unedited welcome-note templates shipped
with Organizer 2.0.23 in its 20 languages. These historical values are immutable:
changing a translation must not change the recognition of notes already created.

The title and the complete surrounding text must match one recorded template.
Only the single absolute storage path between `before` and `after` is ignored
when comparing identity. The path must be at most 4096 characters, start with a
Unix root or a Windows drive/root separator, and contain neither a line break
nor NUL. `text` is the equivalent welcome template without the storage paragraph.
Line endings are normalized to LF. Different languages are not interchangeable.

The personal-sync comparison applies this rule only to plain notes without wire
attachments. The tree comparison additionally accepts its existing lossless
plain-text HTML wrappers; actual formatting and attachments remain significant.
Arbitrary user notes do not lose path text. Wire values and hash validation remain
unchanged; this is an identity/conflict comparison, not a wire-format migration.

`python3 tools/note_identity_templates.py --check` verifies the embedded Linux,
Windows and Android projections. Running without `--check` refreshes projections
from the contract. `--capture` is only for the initial capture and refuses to
overwrite an existing contract.

This contract does not itself remove existing duplicate records or merge their
sharing relationships, deletion history or attachment identities.
