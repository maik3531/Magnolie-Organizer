# Bound-source German text spelling (#605)

An already uniquely bound source record may represent German `ß` as `ss` or
`ẞ` as `SS`. Contact synchronization treats only these substitutions as
equivalent in contact names/company and postal street/city/region/country text.
It keeps each side's stored spelling instead of repeatedly overwriting either
representation. Read-only sources need no write attempt or conflict.

This comparison is not a new identity key. Initial imports, unbound people,
provider IDs, e-mail addresses, URLs, free notes and field labels do not acquire
this equivalence. Other text differences remain content; no general accent
removal, name guessing or whole-profile case folding is introduced. Persisted
baseline hash algorithms and original source/revision safeguards are unchanged.
