# E-mail spelling and source capabilities (#603)

E-mail addresses use lowercase in the Organizer profile, including legacy
`email`/`emails` and structured `emailEintraege`. Both frontend import/edit paths
and native contact synchronization apply this convention. Points, plus-tags,
domain names, field types and unknown labels are not removed or reinterpreted.

Pure case differences are not competing contact edits. Windows comparisons
cover all three field representations without changing persisted baseline hash
algorithms. Linux likewise retains its exact hash algorithms; newly normalized
profile data can legitimately have a different hash.

When a source explicitly supports writing, ordinary authorized synchronization
may write the canonical lowercase address back using the original source record,
revision and existing mutation safeguards. Repeated synchronization must not
repeat the cosmetic write once the source stores lowercase. The technical vCard
EMAIL type INTERNET is not a different HOME/WORK role (#604).

Read-only import/synchronization, including KDE Connect contact import, requires
no write grant and does not acquire one from normalization. It can retain the
source's mixed-case wire spelling while the profile uses lowercase. That case
difference is neither an error nor a conflict. Unknown native write capability
does not authorize an optional cosmetic write. Existing controlled-write/CAS
failures remain genuine failed operations, never fabricated success receipts.

Phone-number presentation remains separate and is preserved (#602). German
text transliterations are a separate bounded comparison topic (#605), not an
e-mail-address identity rule.
