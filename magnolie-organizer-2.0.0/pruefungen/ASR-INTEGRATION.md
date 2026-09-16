# Current ASR regression entry points

All inputs are synthetic. No production build, installed profile or phone is used.

- `test_reminder_projection.py`: ten real Linux profile/crypto/worker tests with
  fsync/rename/delete failures, consent and authenticated profile-byte binding.
  The test environment is class-scoped; importing the collection changes no HOME,
  bus or process resource limit.
- `test_asr_integration.py`: normal pytest collection entry points for
  `asr_sms_restore.py` and `restore-native/phases.py`. Configure `MAGNOLIE_DOTNET`
  and run in the bounded synthetic cross-platform environment. Full mode
  (`MAGNOLIE_VOLLPRUEFUNG=1`) treats missing prerequisites as failures.
- `restore-native/Host.cs.txt`: 63 current C# source/store cases (the 62 ASR
  restore-phase cases plus the complete AUR save-epoch/reopen/negative-control case);
  real fixture files/SQLite/crypto, captured optional OS/transport boundaries.
- Windows `tests/run.js` includes the complete ASR SMS DOM suite. Core's existing
  phone-contract group now executes `OutgoingDialTests` as well. Its explicit
  `--scoped-call-host` entry point accepts fresh Android wire captures for the
  separate `tests/callstate/outgoing.js` UI/note/save replay.
- `context_edit_isolated.sh`: current native context editing, plus explicit
  `--probe-cross-target` and `--probe-contiguous-history` runs. It reuses setup
  only, not the broad historical designer matrix.
- `asr_sms_isolated.sh --web linux|windows`: native preview and per-plan restored
  review at two viewport widths in all 20 languages. Set
  `MAGNOLIE_CONTEXT_EVIDENCE` to an existing private evidence directory. Bridge
  effects and delayed durable-save replies are captured, not sent to a phone.

Native GTK/WebKit exercises of Windows source assets do not prove Windows
WinForms/WebView2 operation. Beta synchronization and native/hardware tests remain
separate work. See `contracts/sms-plan-review-v1.md` and
`contracts/outgoing-call-scope-v2.md` in the canonical repository root.
