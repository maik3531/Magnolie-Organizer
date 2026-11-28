# OpenHolidays API response fixtures — #854 / #857

Contains information from [OpenHolidays API](https://www.openholidaysapi.org/),
which is made available here under the
[Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
The processed data is provided by OpenPotato;
[data repository](https://github.com/openpotato/openholidaysapi.data),
[licensing FAQ](https://www.openholidaysapi.org/en/faq/).
The upstream data-license text is included in `OPENHOLIDAYS-DATA-LICENSE.txt`.

These are unmodified UTF-8 response bodies captured on 28 November 2026 from
the official HTTPS service: Belgian and Dutch groups, nationwide public and
school holiday queries, and each of the six school-group-specific queries.
`requests.json` records exact URLs, retrieval/server timestamps, status codes,
lengths and SHA-256 values. No provider row, date, title or scope was edited.

The C# regression replays the captured response bytes through the actual
Windows provider methods and parser with a controlled HTTP transport. That
replay does not prove a native Windows GUI, package, current future provider
response or source-calendar completeness. Synthetic negative cases are
defined separately in the test program and are not represented as captured
provider answers.

The six group identifiers are also present in the captured `BE-Groups.json`
and `NL-Groups.json`. The accompanying subdivisions on Dutch school records
are normal provider output: provider import processing can expand group
membership into subdivisions. See the source references in the #857 report;
the mere presence of both arrays does not establish a local exception.
