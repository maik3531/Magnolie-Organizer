# Country-aware contact phone comparisons (#602)

Import and contact synchronization compare dialling representations using the
selected home country. For Germany, `0123456`, `+49123456` and `0049123456`
refer to the same number. This is comparison, not proof that a number is
assigned or reachable: possible numbers need not pass allocation validation.

- Use the actual country context, not the contact's postal address or a guessed
  German prefix. Unknown context does not reinterpret a national number.
- Keep significant national digits (including Italy's zero) and distinguish
  extensions. Different numbers and ambiguous identity candidates remain distinct.
- Keep original stored spelling. Comparison keys do not replace exact content
  hashes, source revisions, source ownership, original provider UIDs or CAS checks.
- In Windows sync, country-aware comparison is separate from persisted
  `windows-contact-2` baseline hashing. Both the initial exact-content adoption
  and bound-source label/value comparisons use this context; the caller passes
  the selected native regional setting. Source-update-only runs can receive the
  same context without granting any new source capability.

Regression coverage exercises the Linux sync planner, actual imports in both
full web frontends, and Windows sync with controlled remote stores, including
repeated and simultaneous equivalent changes. These checks are not live-provider
delivery tests or installation/package-release approval.
