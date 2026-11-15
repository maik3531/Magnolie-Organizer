# Legacy Organizer JSON backup plausibility

Issue #601. This is a minimum shape check before a positive backup preview or
restore mutation, not a new backup format, required version or full-schema check.

- The root must be an object with at least one recognizable profile collection
  or profile object. An empty object or unrelated JSON is not a verified backup.
- Present non-null `notizen`, `aufgaben`, `termine`, `kontakte`, `jahrestage`,
  `notizgruppen`, `notizbuecher` and `personen` must be arrays.
- Present non-null `einstellungen`, `gesundheit`, `customOrganizer` and
  `zeiterfassung` must be objects.
- Empty known arrays/objects are valid. Older partial profiles remain valid;
  the check does not require every modern field. Optional null values may
  coexist with another recognizable collection/object, but are not evidence
  of a profile by themselves.
- Unknown additional fields and values are not removed, renamed or interpreted.
  This check does not claim to validate every entry's semantics.

Linux uses the same guarded reader for preview and ordinary JSON restore.
Windows invokes the same validation in preview and before the restore phone
fence, mutation lock, pre-restore checkpoint or profile write. Decrypted legacy
profiles receive the same check. File revisions, passwords, restore authority,
automatic pre-restore protection and commit/recovery behavior are unchanged.

The `.magnolie` complete-archive route retains its existing independent
manifest/content/attachment checks; media backups and synchronized Notes
restore authority are separate and are not replaced by this guard.
