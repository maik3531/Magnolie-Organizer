# Explicit e-mail fields and text recognition (#606)

In dedicated contact e-mail fields, a single `(at)` or `[at]` (case-insensitive)
in place of `@` is recognized before address validation, then normalized to an
ordinary lowercase address. Multiple ambiguous substitutions are not guessed.
The Linux/Windows native readers must not discard these addresses before the
frontend can import them. Existing contact/source identity checks still apply.

In notes and messages, stored and visible text remains unchanged. Notes offer
explicit mail actions outside the editor for recognized addresses; the message
renderer links the original visible spelling to its canonical e-mail target.
The existing manual note-link action recognizes these spellings too, preserving
the visible text. None of these recognition steps changes saved note/message
content or creates a contact. Opening the mail application requires a user click.
Address text is inserted as DOM text, never interpreted as HTML.

Read-only contact sources retain their existing access restrictions: recognition
does not acquire a write grant and spelling differences alone are not conflicts.
Canonical source writeback, where supported and already authorized, follows the
same original revision/CAS protections as ordinary e-mail normalization (#603).
