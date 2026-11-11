using MagnolieOrganizer.Windows.Tests;
if (args.Length == 3 && args[0] == "--phone-audio-parent-product")
    return PhoneCameraAudioParentPayloadTests.InspectProduct(args[1], bool.Parse(args[2]));
if (args.Length == 3 && args[0] == "--phone-audio-runtime-product")
    return PhoneCameraAudioRuntimeTests.InspectProduct(args[1], bool.Parse(args[2]));
if (args.Length == 1 && args[0] == "--phone-audio-protected-preparation-probe")
{
    if (!OperatingSystem.IsWindows()) return 77;
    return await PhoneCameraAudioProtectedPreparationTests.RunAsync();
}
if (args.Length == 2 && args[0] == "--desktop-helper-readonly")
    return DesktopPhoneCompositionTests.HelperReadOnly(args[1]);
if (args.Length == 4 && args[0] == "--desktop-composition-readonly")
    return DesktopPhoneCompositionTests.ReadOnly(args[1], bool.Parse(args[2]), bool.Parse(args[3]));
if (args.Length == 1 && args[0] == "--phone-webcam-media-host") return await PhoneCameraMediaChannelTests.HostAsync();
if (args.Length == 1 && args[0] == "--tray-drawing") { await TrayAppearanceTests.DrawingAsync(); Console.WriteLine("Tray drawing PASS"); return 0; }
if (args.Length == 1 && args[0] == "--tray-visual-test") { await TrayAppearanceTests.VisualLeaseAsync(); Console.WriteLine("Tray visual lease PASS"); return 0; }
if (args.Length == 1 && args[0] == "--tray-sync-io") { await TraySyncActivityTests.WriterAsync(); Console.WriteLine("Tray sync IO PASS"); return 0; }
// Refs #432: individually bounded native projection and activity checks.
if (args.Length == 1 && args[0] == "--tray-owners") { await TrayAppearanceTests.OwnersAsync(); Console.WriteLine("Tray owners PASS"); return 0; }
if (args.Length == 1 && args[0] == "--tray-kde") { await KdeConnectTests.TrayProjectionAsync(); Console.WriteLine("Tray KDE TLS PASS"); return 0; }
if (args.Length == 2 && args[0] == "--mcp-stdio-fixture")
    return await MagnolieOrganizer.Windows.McpLocalServer.RunStdioAsync(args[1], Console.OpenStandardInput(), Console.OpenStandardOutput(), CancellationToken.None);

if (args.FirstOrDefault() == "--dav-live") return await NextcloudDavLiveTests.RunAsync();
if (args.FirstOrDefault() == "--thunderbird-live") return await NextcloudDavLiveTests.RunAsync(thunderbird: true);
if (args.Length == 2 && args[0] == "--readonly-calendar-fixture") return await NextcloudDavTests.ReadOnlyCalendarFixtureAsync(args[1]);
if (args.FirstOrDefault() == "--birthday-thunderbird-live") return await CalendarBirthdayCleanupTests.RunBridgeLiveAsync();
if (args.FirstOrDefault() == "--thunderbird-readonly") return await NextcloudDavLiveTests.ReadOnlyAsync();
if (args.FirstOrDefault() == "--managed-accounts-readonly") return await NextcloudDavLiveTests.ReadOnlyAsync(managed: true);
if (args.FirstOrDefault() == "--calendar-plan-readonly" && args.Length == 3)
    return await CalendarSyncReadOnlyProbe.RunAsync(args[1], args[2]);
if (args.FirstOrDefault() == "--sync-commit-readonly" && args.Length == 3)
    return await SyncCommitReadOnlyProbe.RunAsync(args[1], args[2]);
if (args.FirstOrDefault() == "--contact-conflicts-readonly" && args.Length == 2)
    return await ContactConflictReadOnlyProbe.RunAsync(args[1]);
if (args.FirstOrDefault() == "--profile-backup-native" && args.Length == 2)
    return await AtomicStoreTests.NativeProfileBackupAsync(args[1]);
if (args.Length == 1 && args[0] == "--peer-content-readonly") return PeerContentReadOnlyProbe.Run();
if (args.Length == 1 && args[0] == "--peer-media-readonly") return PeerContentReadOnlyProbe.MediaReadiness();
if (args.Length == 1 && args[0] == "--peer-change-readonly") return PeerContentReadOnlyProbe.ObserveChanges();
if (args.FirstOrDefault() == "--notes-state-readonly" && args.Length == 2)
    return await NotesStateReadOnlyProbe.RunAsync(args[1]);
if (args.FirstOrDefault() == "--notes-batch-copy-readonly" && args.Length == 3)
    return await NotesStateReadOnlyProbe.RunAsync(args[1], args[2]);
if (args.FirstOrDefault() == "--managed-runtime-policy-probe" && args.Length == 3)
    return ManagedAccountRuntimePolicyTests.NativeProbe(args[1], args[2]);
if (args.FirstOrDefault() == "--managed-runtime-update-probe" && args.Length == 4)
    return await ManagedAccountRuntimePolicyTests.NativeUpdateProbeAsync(args[1], args[2], args[3]);
if (args.FirstOrDefault() == "--kde-filesystem-native-probe" && args.Length == 2)
    return await KdeFilesystemTests.NativeProbeAsync(args[1]);
if (args.FirstOrDefault() == "--filesystem-prerequisite-probe" && args.Length == 2)
{
    MagnolieOrganizer.Windows.FilesystemRuntimeSetup.ValidatePackages(args[1]);
    Console.WriteLine("NATIVE PREREQUISITES PASS: embedded hashes and Authenticode publisher validated; no installation performed");
    return 0;
}
if (args.FirstOrDefault() == "--contact-identity-audit" && args.Length == 2) return await WindowsContactGraphTests.AuditIdentityAsync(args[1]);
if (args.FirstOrDefault() == "--contact-cleanup-fixture")
{
    using var fixture = System.Text.Json.JsonDocument.Parse(await Console.In.ReadToEndAsync());
    Console.WriteLine(MagnolieOrganizer.Windows.ContactCleanupPlan.Create(fixture.RootElement).ToJsonString());
    return 0;
}
if (args.FirstOrDefault() == "--managed-account-host" && args.Length == 4)
    return await ManagedInternetAccountsTests.ProbeAsync(args[1], args[2], args[3]);
if (args.FirstOrDefault() == "--managed-account-restart" && args.Length == 4)
    return await ManagedInternetAccountsTests.ProbeAsync(args[1], args[2], args[3], restart: true);
if (args.FirstOrDefault() == "--managed-account-lifecycle" && args.Length == 4)
    return await ManagedInternetAccountsTests.ProbeAsync(args[1], args[2], args[3], lifecycle: true);

if (args.FirstOrDefault() == "--scoped-call-host") return await OutgoingDialTests.RunAsync(args.ElementAtOrDefault(1), args.ElementAtOrDefault(2));

if (args.FirstOrDefault() == "--personal-custom-host") return await PersonalCustomTransportTests.HostAsync();
if (args.FirstOrDefault() == "--personal-note-mode-host") return await PersonalNoteModeTransportHost.RunAsync();
if (args.Length == 3 && args[0] == "--personal-actor-host") return await PersonalSyncActorTransportHost.RunAsync(args[1], args[2]);
if (args.FirstOrDefault() == "--time-sync-host") return await TimeSyncTransportHost.RunAsync(args.ElementAtOrDefault(1));
if (args.Length == 2 && args[0] == "--time-control-host") return await TimeSyncTransportHost.RunAsync(args[1], true);
if (args.FirstOrDefault() == "--phone-contact-read-host") return await PhoneContactReadTests.HostAsync();
if (args.FirstOrDefault() == "--phone-developer-read-host") return await DeveloperDiagnosticsTests.HostAsync();
if (args.FirstOrDefault() == "--waste-import-fixture")
{
    var fixture = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(
        TestSource.Root("contracts/waste-calendar-v1.json"), "contracts", "waste-calendar-v1.json")))!;
    Console.WriteLine(MagnolieOrganizer.Windows.ExchangeCodec.ParseWasteImport(
        System.Text.Encoding.UTF8.GetBytes(fixture["ics"]!.GetValue<string>()), "waste.ics").ToJsonString());
    return 0;
}
if (args.FirstOrDefault() == "--or6-json")
{
    if (args.Length is not (1 or 2)) throw new ArgumentException("--or6-json accepts at most one explicit fixture file.");
    var data = Or6CodecTests.Fixture();
    var name = "known-values.or6";
    if (args.Length == 2)
    {
        var file = new FileInfo(args[1]);
        if (file.Length > MagnolieOrganizer.Windows.ExchangeCodec.MaxImportBytes) throw new InvalidDataException("Fixture is too large.");
        data = File.ReadAllBytes(file.FullName); name = file.Name;
    }
    Console.WriteLine(MagnolieOrganizer.Windows.ExchangeCodec.ParseImport(
        data, "lotus", name).ToPayload("lotus", name).ToJsonString());
    return 0;
}

if (args.FirstOrDefault() == "--phone-bt-native-probe") return await TelefonBluetoothNativeProbe.RunAsync();

if (args.FirstOrDefault() == "--phone-bt-host" && args.Length == 3) return await TelefonBluetoothSetupTests.HostAsync(int.Parse(args[1]), args[2]);

if (args.FirstOrDefault() == "--phone-invite-host" && args.Length == 2) return await TelefonInvitationTests.HostAsync(args[1]);

if (args.FirstOrDefault() == "--recurrence-json") { RecurrenceIntegrationTests.Probe(); return 0; }
if (args.FirstOrDefault() == "--published-release-audit")
{
    if (args.Length > 2) { Console.Error.WriteLine("Usage: --published-release-audit [release-root]"); return 2; }
    try
    {
        var root = args.Length == 2 ? Path.GetFullPath(args[1]) : TestSource.Root("update.xml");
        WindowsReleaseAuditTests.Audit(root);
        Console.WriteLine("Published release audit passed: " + root);
        return 0;
    }
    catch (Exception error) { Console.Error.WriteLine("Published release audit FAILED: " + error); return 1; }
}

var runner = new TestRunner();
runner.Add("Phone webcam parent / strict ephemeral schema and roles", PhoneCameraParentTests.SchemaAsync);
runner.Add("Phone webcam parent / actual original encrypted writer and ordinary sequence", PhoneCameraParentTests.OriginalWriterAsync);
runner.Add("Phone webcam parent / bounded original writer admission without parent loss", PhoneCameraParentTests.BoundedAdmissionAsync);
runner.Add("Phone webcam parent / post-encryption guard and immutable control snapshot", PhoneCameraParentTests.RevocationAndSnapshotAsync);
runner.Add("Phone webcam parent / actual post-write revocation and desktop role", PhoneCameraParentTests.PostWriteRevocationAsync);
runner.Add("Phone webcam parent / authenticated reserved incoming TCP dispatcher", PhoneCameraParentTests.AuthenticatedIncomingAsync);
runner.Add("Phone webcam parent / reserved rejection and no durable controls", PhoneCameraParentTests.ReservedRejectionAndStorageAsync);
runner.Add("Phone webcam parent / bounded native control inbox", PhoneCameraParentTests.BoundedInboxAsync);
runner.Add("Phone webcam parent / replay and old owner isolation", PhoneCameraParentTests.ReplayAndOldOwnerAsync);
runner.Add("Phone webcam parent / owner revocation and bounded ACK", PhoneCameraParentTests.OwnerRevocationAndBoundedAckAsync);
runner.Add("Phone webcam parent / broken native retirement cannot block parent cleanup", PhoneCameraParentTests.BrokenRetirementCallbackAsync);
runner.Add("Phone webcam session / original encrypted control and joined binary AV pacing", PhoneCameraSessionTests.JoinedEncryptedAvAsync);
runner.Add("Phone webcam session / required microphone prevents SEND fallback", PhoneCameraSessionTests.MissingMicrophonePreventsSendAsync);
runner.Add("Phone webcam session / explicit native mute only", PhoneCameraSessionTests.ExplicitMuteAsync);
runner.Add("Phone webcam session / unpublished SEND never reads media", PhoneCameraSessionTests.FailedSendNeverReadsMediaAsync);
runner.Add("Phone webcam session / original revocation interrupts pending input", PhoneCameraSessionTests.RevocationStopsPendingInputAsync);
runner.Add("Phone webcam session / track gap retires joined output", PhoneCameraSessionTests.TrackGapRetiresBothAsync);
runner.Add("Phone webcam session / unconfirmed cleanup remains pending", PhoneCameraSessionTests.CleanupFailureRemainsPendingAsync);
runner.Add("Phone webcam session / missing initial track retires active joined audio", PhoneCameraSessionTests.MissingInitialTrackAsync);
runner.Add("Phone webcam session / muted session refuses audio packets", PhoneCameraSessionTests.MutedAudioRejectedAsync);
runner.Add("Phone webcam session / original revocation interrupts native output write", PhoneCameraSessionTests.RevocationInterruptsNativeWriteAsync);
runner.Add("Phone webcam audio package / closed named trust boundary", PhoneCameraAudioPackageTests.ClosedTrustBoundaryAsync);
runner.Add("Phone webcam native video record / exact relay header and owned I420 copy", PhoneCameraVideoPacketTests.NativeRecordAsync);
runner.Add("Phone webcam native video record / invalid input never changes output bytes", PhoneCameraVideoPacketTests.InvalidRecordIsAtomicAsync);
runner.Add("Phone webcam native audio record / exact header and unchanged PCM16LE copy", PhoneCameraAudioPacketTests.NativeRecordAsync);
runner.Add("Phone webcam native audio record / invalid input never changes output bytes", PhoneCameraAudioPacketTests.InvalidRecordIsAtomicAsync);
runner.Add("Phone webcam audio helper / immutable resource snapshot and no external fallback", PhoneCameraAudioHelperTests.ImmutableSnapshotAsync);
runner.Add("Phone webcam audio helper / checksum and native executable rejection", PhoneCameraAudioHelperTests.TamperAndPeAsync);
runner.Add("Phone webcam audio helper / strict embedded source descriptor", PhoneCameraAudioHelperTests.StrictSourceDescriptorAsync);
runner.Add("Phone webcam audio runtime / immutable resource snapshot and absent fallback", PhoneCameraAudioRuntimeTests.ImmutableResourceAsync);
runner.Add("Phone webcam audio runtime / exact x64 PE and digest", PhoneCameraAudioRuntimeTests.PeAndDigestAsync);
runner.Add("Phone webcam audio runtime / strict source manifest", PhoneCameraAudioRuntimeTests.StrictManifestAsync);
runner.Add("Phone webcam parent payload / immutable snapshot and absent external fallback", PhoneCameraAudioParentPayloadTests.ImmutableSnapshotAsync);
runner.Add("Phone webcam parent payload / exact x64 DLL and digest", PhoneCameraAudioParentPayloadTests.PeAndDigestAsync);
runner.Add("Phone webcam parent payload / strict fixed source descriptor", PhoneCameraAudioParentPayloadTests.StrictDescriptorAsync);
runner.Add("Phone webcam output authority / prepared current before actual SEND", PhoneCameraSessionTests.AuthorityPrepareThenActualSendAsync);
runner.Add("Phone webcam output authority / exact original object and independent replacement owner", PhoneCameraSessionTests.AuthorityCannotBeReplacedAsync);
runner.Add("Phone webcam output authority / original loss permanently rejects resurrection", PhoneCameraSessionTests.AuthorityOriginalLossCannotReviveAsync);
runner.Add("Phone webcam output authority / backend failure retires original joined owner", PhoneCameraSessionTests.AuthorityBackendFailureRetiresJoinedAsync);
runner.Add("Phone webcam output authority / immutable original explicit mute", PhoneCameraSessionTests.AuthorityExplicitMuteIsOriginalAsync);
runner.Add("Phone webcam SEND publication / backend failure during original writer wait", PhoneCameraSessionTests.BackendFailureBlocksWaitingSendAsync);
runner.Add("Phone webcam SEND publication / readiness loss during original writer wait", PhoneCameraSessionTests.ReadinessLossBlocksWaitingSendAsync);
runner.Add("Phone webcam publication API / bare SEND and direct parent cannot bypass typed authority", PhoneCameraParentTests.BareSendRequiresTypedPublicationAsync);
runner.Add("Phone webcam publication API / substitute authority and binding rejected without harming genuine owner", PhoneCameraSessionTests.PublicationRejectsSubstituteAuthorityAsync);
runner.Add("Phone webcam audio setup / strict original read-only plan", PhoneCameraAudioSetupTests.StrictPlanAsync);
runner.Add("Phone webcam audio setup / reboot result never claims endpoint readiness", PhoneCameraAudioSetupTests.RebootIsNotReadinessAsync);
runner.Add("Phone webcam audio setup / bounded wire and cancellation", PhoneCameraAudioSetupTests.OriginalBoundedWireAsync);
if (OperatingSystem.IsWindows())
    runner.Add("Phone webcam audio setup / bounded original invocation shape only", PhoneCameraAudioSetupTests.ArgumentBoundaryAsync);
if (OperatingSystem.IsWindows())
    runner.Add("Phone webcam audio setup / actual first-instance pipe and original PID only", PhoneCameraAudioSetupTests.ActualLocalPipeIdentityAsync);
if (OperatingSystem.IsWindows())
    runner.Add("Phone webcam audio setup / exact original User SID ACL across elevation design", PhoneCameraAudioSetupTests.OriginalUserAclAsync);
if (OperatingSystem.IsWindows())
    runner.Add("Phone webcam audio setup / actual wrong original parent birth-time rejected before preparation", PhoneCameraAudioSetupTests.OriginalParentStartMismatchAsync);
if (OperatingSystem.IsWindows())
    runner.Add("Phone webcam audio bootstrap / protected managed inputs and apphost gate only", PhoneCameraAudioBootstrapTests.ProtectedManagedInputsAsync);
if (OperatingSystem.IsWindows())
    runner.Add("Phone webcam audio staging / in-memory protected ACL policy only", PhoneCameraAudioStagingTests.ProtectedAclPolicyAsync);
if (Environment.GetEnvironmentVariable("MAGNOLIE_CABLE_PACKAGE_FIXTURE") is not null)
{
    // Explicit existing read-only publisher fixture, never CI auto-download or
    // redistribution of vendor bytes in the ordinary source test suite.
    runner.Add("Phone webcam audio package / original bytes and complete as-is extraction", PhoneCameraAudioPackageTests.OriginalSnapshotAndExtractionAsync);
    runner.Add("Phone webcam audio package / changed archive and allocation bound", PhoneCameraAudioPackageTests.ChangedArchiveRejectedAsync);
    runner.Add("Phone webcam audio package / existing destination preserved", PhoneCameraAudioPackageTests.ExistingDestinationPreservedAsync);
    runner.Add("Phone webcam audio package / verified fixed-origin download", PhoneCameraAudioPackageTests.VerifiedDownloadAsync);
    runner.Add("Phone webcam audio package / redirect origin and budget", PhoneCameraAudioPackageTests.RedirectOriginAndBudgetAsync);
    runner.Add("Phone webcam audio package / download limits and cancellation", PhoneCameraAudioPackageTests.DownloadLimitsAndCancellationAsync);
}
if (Environment.GetEnvironmentVariable("MAGNOLIE_CABLE_PACKAGE_LIVE_DOWNLOAD") == "1")
    runner.Add("Phone webcam audio package / actual Windows HTTPS verified download only", PhoneCameraAudioPackageTests.LiveOfficialDownloadAsync);
runner.Add("Phone webcam media / original binary AV socket and Python goldens", PhoneCameraMediaChannelTests.GoldensAsync);
runner.Add("Phone webcam media / bounded envelope tamper replay and EOF", PhoneCameraMediaChannelTests.RejectionsAsync);
runner.Add("Phone webcam media / authenticated packet grammar", PhoneCameraMediaChannelTests.PacketGrammarAsync);
runner.Add("Phone webcam media / original secret session and unrelated connection isolation", PhoneCameraMediaChannelTests.ContextIsolationAsync);
runner.Add("Phone webcam media / original guard idle revoke and stop", PhoneCameraMediaChannelTests.OriginalGuardAndStopAsync);
runner.Add("Phone webcam media / original secret ownership and packet deadline", PhoneCameraMediaChannelTests.TimeoutAndSecretAsync);
runner.Add("Tray appearance / passive owners and independent activity", TrayAppearanceTests.OwnersAsync);
runner.Add("Tray appearance / actual encrypted personal time actor IO", TraySyncActivityTests.WriterAsync);
runner.Add("Tray appearance / native visual lease and saved developer gate", TrayAppearanceTests.VisualLeaseAsync);
runner.Add("Tray appearance / actual KDE TLS without SMS", KdeConnectTests.TrayProjectionAsync);
runner.Add("Personal synchronization confirmed-success metadata / identity / no grants", PersonalSyncSuccessTests.RunAsync);
runner.Add("Media shared preferences / independent registers safe defaults replay and actor guards", MediaSyncSettingsTests.RunAsync);
runner.Add("Video preview container / bounded memory input refuses external references", DeviceFileVideoPreviewTests.ContainerAsync);
runner.Add("Media photo metadata / bounded actual TIFF JPEG PNG tags / unknown exclusion", PhotoCaptureMetadataTests.RunAsync);
runner.Add("Media backup exclusions / recursive independent native component classifier", DeviceFileBackupExclusionTests.ClassifierAsync);
runner.Add("Personal synchronization confirmed-success actual ACK / stale channel / failure", PersonalSyncSuccessTests.AcknowledgmentsAsync);
runner.Add("Shared synchronization settings / one choice / peer scope / convergence", SharedSyncSettingsTests.RunAsync);
runner.Add("Notes contact group title / strict preparation and saved identity", PhoneContactGroupTitleWriteTests.RunAsync);
runner.Add("Shared preference storage / encryption / binding / restore", SharedSyncStorageTests.RunAsync);
runner.Add("Shared preference transport / fresh controls / replay / reconnect", SharedSyncTransportTests.RunAsync);
runner.Add("Phone content scope / subset updates / removal / bounded manifests", PhoneContentScopeTests.RunAsync);
runner.Add("Scoped run storage / immutable membership / separate time choice", ScopedRunStorageTests.RunAsync);
runner.Add("Baum synchronization snapshot continuity", BaumSyncSnapshotTests.RunAsync);
runner.Add("Background lifecycle regressions", BackgroundLifecycleTests.RunAsync);
runner.Add("Native sync safety / baselines / mailbox / recovery", NativeSyncSafetyTests.RunAsync);
runner.Add("AtomicStore / Dateisicherheit", AtomicStoreTests.RunAsync);
runner.Add("MCP local pipe / correlation / strict framing / cleanup", McpTransportTests.RunAsync);
runner.Add("MCP tree / native store / revision / scoped GUI emissions", McpTreeActionsTests.RunAsync);
runner.Add("MCP phone / public control snapshot / native revision", McpPhoneStatusTests.RunAsync);
runner.Add("MCP calls / current-session provenance / redacted observations", McpCallContextTests.RunAsync);
runner.Add("Call command origin / persisted metadata / private reply routing", CallCommandOriginTests.RunAsync);
runner.Add("MCP call actors / owner admission / correlated native commands", McpCallActorTests.RunAsync);
runner.Add("MCP device status / explicit identifiers / ephemeral source", McpDeviceStatusTests.RunAsync);
runner.Add("MCP Notes settings / consent / shared preference store", McpNotesSettingsTests.RunAsync);
runner.Add("Notes actor start / shared strict contract vectors", PersonalSyncActorContractTests.RunAsync);
runner.Add("Personal batch byte boundaries / shared UTF-8 / actor envelope", PersonalBatchBoundaryTests.RunAsync);
runner.Add("Notes actor atomic batch and deletion-intent core commit", PersonalActorCommitTests.RunAsync);
runner.Add("Notes actor completion metadata / closed data / native guards", PersonalActorCompletionTests.RunAsync);
runner.Add("Notes actor historical writer gate / volatile retirement / fresh save guard", PersonalActorCompletionTests.HistoricalWriterGateAsync);
runner.Add("Notes actor current local restore source / actual GUI projection parity", PersonalActorLocalRestoreSourceTests.RunAsync);
runner.Add("Notes actor historical source review / authenticated origin / no save", PersonalActorLocalRestoreSourceTests.HistoricalReviewAsync);
runner.Add("Notes actor exact historical candidate delta / no caller hash authority", PersonalActorRestoreCandidateTests.RunAsync);
runner.Add("Notes actor historical native prepare / closed data / exact writer payload", PersonalActorLocalRestoreSourceTests.HistoricalPrepareAsync);
runner.Add("Notes actor historical native confirm / exact SaveACK / terminal receipt", PersonalActorLocalRestoreSourceTests.HistoricalConfirmAsync);
runner.Add("Notes actor historical encrypted native file writer / exact receipt", PersonalActorLocalRestoreSourceTests.HistoricalFileWriterAsync);
runner.Add("Notes actor historical uncertain file write / no replay or false receipt", PersonalActorLocalRestoreSourceTests.HistoricalUncertainWriterAsync);
runner.Add("Notes actor actual Windows SaveAsync / historical native job / file receipt", PersonalActorLocalRestoreSourceTests.HistoricalBridgeSaveAsync);
runner.Add("Actual Windows SaveAsync / ordinary encryption / epoch and id fence", PersonalActorLocalRestoreSourceTests.ActualOrdinarySaveAsync);
runner.Add("Historical restore preserves unrelated fractional drawing / wire remains integer", PersonalActorRestoreCandidateTests.FractionalDrawingAsync);
runner.Add("Actual historical SaveAsync with fractional drawing / private data preserved", PersonalActorLocalRestoreSourceTests.HistoricalBridgeDrawingSaveAsync);
runner.Add("Actual historical SaveAsync preserves independently saved user edits", PersonalActorLocalRestoreSourceTests.HistoricalBridgeIndependentSaveAsync);
runner.Add("Historical metadata-only script review / no save route", PersonalActorLocalRestoreSourceTests.HistoricalScriptReviewAsync);
runner.Add("Notes actor post-data review / separate SaveACK claim / native handoff", PersonalActorPostDataReviewTests.RunAsync);
runner.Add("Notes actor mixed late review / fixed choices / scope union", PersonalActorMixedLateReviewTests.RunAsync);
runner.Add("Notes actor fixed decision groups / atomic native claim / protected replay", PersonalActorFixedDecisionGroupTests.RunAsync);
runner.Add("Notes actor outbox / encrypted wire retention", PersonalSyncActorStoreTests.RunAsync);
runner.Add("Notes actor registry / protected ownership / raw inbox", PersonalSyncActorRegistryTests.RunAsync);
runner.Add("Notes actor native source / fresh controls / book ownership", PersonalSyncActorSourceTests.RunAsync);
runner.Add("Notes actor native book / lifecycle ownership fence", NativeBookOwnerScopeTests.RunAsync);
runner.Add("Notes actor native producer preparation / scoped tombstones / fresh writer", PersonalActorOutgoingProducerTests.RunAsync);
runner.Add("Notes actor native target observations / current owner / no action rights", PersonalActorTargetObserverRuntimeTests.RunAsync);
runner.Add("Notes actor explicit historical target choice draft / no action rights", PersonalActorTargetChoiceReviewTests.RunAsync);
runner.Add("Notes actor historical result membership / separate receipt union", PersonalActorHistoricalResultScopeTests.RunAsync);
runner.Add("MCP KDE / existing integration / no implicit listener", McpKdeLifecycleTests.RunAsync);
runner.Add("Category colors / native categories and accent interchange", CategoryColorTests.RunAsync);
runner.Add("Contact group exclusions / identity / reminder privacy", ContactGroupExclusionTests.RunAsync);
runner.Add("Note send / selected PDF / explicit adapter handoff", NoteSendTests.RunAsync);
runner.Add("Wiederherstellungsjournal / Manifest / Tamper / Retention / Scheduler", RecoveryJournalTests.RunAsync);
runner.Add("Cloud-Ordner-Sicherung / Policy / Retention / DPAPI", CloudBackupTests.RunAsync);
runner.Add("Loganzeige / Contributor-Marker", LogPresentationTests.RunAsync);
runner.Add("Lokale Absturzberichte / Format / Rotation / Parallelität", CrashReportTests.RunAsync);
runner.Add("Encryption / Python-Goldens / Manipulation", ContractGroupTests.EncryptionAsync);
runner.Add("Password / native source / revisions / authenticated readback", PasswordSourceTests.RunAsync);
runner.Add("Record export / native codecs / actual files / guards", RecordExportFileTests.RunAsync);
runner.Add("Import file / native readers / source CAS / archive limits", ImportFileSourceTests.RunAsync);
runner.Add("OR6 import / native fixtures / freed storage / corrupt boundaries", Or6CodecTests.RunAsync);
runner.Add("OR6 extension / original recurring set / categories / sparse phone contexts", Or6ExtensionTests.RunAsync);
runner.Add("Country flags / local ISO artwork / native setup coordinates", CountryFlagsTests.RunAsync);
runner.Add("Local import / native readers / semantic snapshot CAS", LocalImportSourceTests.RunAsync);
runner.Add("Document export / actual ODS / readback / target guards", VerifiedDocumentFileTests.RunAsync);
runner.Add(".magnolie Gesamtarchiv / Cross-Platform / Anhänge / Fehler", ContractGroupTests.ArchiveAsync);
runner.Add("Notizanhänge / Data-URL / Dateinamen", AttachmentFileTests.RunAsync);
runner.Add("ICS / VCF / LDIF / Claws / Lotus / Thunderbird", ContractGroupTests.ExchangeAsync);
runner.Add("Calendar source case / Windows mixed component and property names roundtrip", CalendarSourceTimezoneCaseTests.RunAsync);
runner.Add("Thunderbird local.sqlite Schema 23", ThunderbirdSchema23Tests.RunAsync);
runner.Add("ODS Paket / XML / Styles / Geometrie / Chart", ContractGroupTests.OdsAsync);
runner.Add("Time sync / v7 consent and strict records", TimeSyncContractTests.RunAsync);
runner.Add("Time control / v13 native timer command contract", TimeControlContractTests.RunAsync);
runner.Add("Time control / source-bound ephemeral requests", TimeControlTransportTests.RunAsync);
runner.Add("Time sync / encrypted staging and durable receipts", TimeSyncStoreTests.RunAsync);
        runner.Add("Time sheet / formulas and regional layout", TimeSheetExportTests.RunAsync);
        runner.Add("Holiday scope / country and subdivision metadata", OpenHolidayDataTests.RunAsync);
runner.Add("ODT Brief / MIME / Paket / Dateiendung", ContractGroupTests.OdtAsync);
runner.Add("Windows Contacts / Graph / OAuth / Token", WindowsContactGraphTests.RunAsync);
runner.Add("Microsoft device-code sign-in / persistence / cancellation", GraphDeviceSignInTests.RunAsync);
runner.Add("Reminder / Serien", ContractGroupTests.RemindersAsync);
runner.Add("Cycle calendar / explicit markers and optional forecasts", CycleCalendarTests.RunAsync);
runner.Add("Reminder / Neustart / Kennwort / DST", ReminderPersistenceTests.RunAsync);
runner.Add("Anniversary reminder / text / independent dismissal", AnniversaryReminderTests.RunAsync);
runner.Add("Tray-Persistenz / Autostart", ContractGroupTests.TrayAsync);
runner.Add("Wetterstandort / LibreOffice / Datenschutz", WeatherLocationTests.RunAsync);
runner.Add("Magnolienbaum Crypto / Pairing / FS1 / Replay / Queues / Netzwerk", ContractGroupTests.TreeAsync);
runner.Add("Magnolienbaum Nextcloud / WebDAV / Authentisierung", NextcloudMailboxTests.RunAsync);
runner.Add("DAV credential identity / checked account changes cannot reuse a retained secret", NextcloudMailboxTests.CredentialIdentityGuardAsync);
runner.Add("Embedded timezone boundary anchors / historical UTC range", RecurrenceIntegrationTests.BoundaryAnchorsAsync);
runner.Add("ICS unfolding / actual codec / semantic compatibility", CalendarUnfoldingTests.SemanticsAsync);
runner.Add("ICS unfolding / bounded allocations / valid folded descriptions", CalendarUnfoldingTests.AllocationsAsync);
runner.Add("DAV wildcard ETag / exact version preconditions / no transport", NextcloudDavTests.WildcardVersionBindingAsync);
runner.Add("Nextcloud CalDAV / CardDAV / Discovery / ETag / Sicherheit", NextcloudDavTests.RunAsync);
runner.Add("Calendar birthday cleanup", CalendarBirthdayCleanupTests.RunAsync);
runner.Add("Shared preference controller", SharedSyncControllerTests.RunAsync);
runner.Add("Own profile / LibreOffice field comparison", OfficeProfileTests.RunAsync);
runner.Add("Thunderbird bridge / framing / provider identity", ThunderbirdBridgeTests.RunAsync);
runner.Add("Managed internet accounts / isolated profiles", ManagedInternetAccountsTests.RunAsync);
runner.Add("Managed EAS source folder contracts", ManagedEasSourceFolderTests.RunAsync);
runner.Add("Calendar diagnostics / read-only transport / no provider mutations", CalendarSyncReadOnlyProbe.SafetyAsync);
runner.Add("Calendar resource identity / stale mapping / exact UID / no duplicate create", CalendarResourceIdentityTests.RunAsync);
runner.Add("Sync commit projection / own transient marker / exact durable proof", SyncCommitProjectionTests.RunAsync);
runner.Add("Calendar location projection / legacy baseline / genuine edits", CalendarLocationSyncTests.RunAsync);
runner.Add("Recovery comparison / unchanged photo allocations", RecoveryComparisonAllocationTests.RunAsync);
runner.Add("Magnolienbaum discovery / allowed UDP port / active listener", MagnolienbaumDiscoveryTests.RunAsync);
runner.Add("Magnolienbaum Kontakte / Fotos / manuelle Löschvorschläge", ContractGroupTests.TreeContactsAsync);
runner.Add("Telefonverbindung / Crypto / Pairingcode / Rahmen / Verträge", TelefonProtocolTests.RunAsync);
runner.Add("Telefon renewal / existing binding / pending proofs", TelefonRepairTests.RunAsync);
runner.Add("Notes contacts / read-only / bounded pages / source binding", PhoneContactReadTests.RunAsync);
runner.Add("Notes contact groups / separate opt-in / live tickets / saved readback", PhoneContactGroupTests.RunAsync);
runner.Add("Notes contact values / scoped codec / correlated actual fields", PhoneContactValueWriteTests.RunAsync);
runner.Add("Developer diagnostics / own Wi-Fi / bounded reports / revocation", DeveloperDiagnosticsTests.RunAsync);
runner.Add("Contact groups sync / v4 sets / legacy fences", ContactGroupSyncContractTests.RunAsync);
runner.Add("Telefon WLAN invitations / bounded discovery", TelefonInvitationTests.RunAsync);
runner.Add("Telefon Bluetooth first pairing / target binding", TelefonBluetoothSetupTests.RunAsync);
runner.Add("Telefon setup startup lifecycle / Finish / Skip / rollback", PhoneStartupLifecycleTests.RunAsync);
runner.Add("Bluetooth-Funkschalter / Gesprächsdauer / Zustandsrückgabe", BluetoothRadioTests.RunAsync);
runner.Add("KDE Connect / Codec / P-256-Ablage / Pinning / Integration", KdeConnectTests.RunAsync);
runner.Add("KDE share / strict payload envelope / safe incoming filenames", KdeShareTests.RunAsync);
runner.Add("KDE incoming batch / immutable manifest / source revocation / private staging", KdeIncomingFileBatchTests.RunAsync);
runner.Add("KDE incoming payload / pinned TLS / byte witness / cancellation", KdeReceiveTransportTests.RunAsync);
runner.Add("KDE incoming offer / guarded destination / partial retry / no overwrite", KdeIncomingFileOfferTests.RunAsync);
runner.Add("KDE receive backend / real control-payload TLS / one offer / cleanup", KdeReceiveIntegrationTests.RunAsync);
runner.Add("KDE receive bridge / actual commands / owner lease / one native chooser", KdeReceiveBridgeTests.RunAsync);
runner.Add("KDE receive clipboard / actual TLS / confirm default / automatic opt-in / revocation", KdeClipboardReceiveTests.RunAsync);
runner.Add("Device file manifest / immutable members / shared hash / portable paths", DeviceFileManifestTests.RunAsync);
runner.Add("Device file offer / complete envelope / native peer binding / exact byte budget", DeviceFileOfferEnvelopeTests.RunAsync);
runner.Add("Photo sync schedule / manual default / explicit automatic / no overlapping native work", PhotoSyncScheduleTests.RunAsync);
runner.Add("Photo sync plan / shared three-way cases / preserve edits and missing-photo uncertainty", PhotoSyncPlanTests.RunAsync);
runner.Add("Media backup maintenance / policy age Never savings and content keys", DeviceFileBackupMaintenanceTests.PolicyAsync);
runner.Add("Media backup maintenance / native resource sampling and sticky busy state", DeviceFileBackupMaintenanceTests.ProbeAsync);
runner.Add("Media backup maintenance / saved book stop and memory ownership", DeviceFileBackupMaintenanceTests.NativeOwnerAsync);
runner.Add("Device file controls / dedicated own-peer / fresh echo / persistent grants", DeviceFileControlTests.RunAsync);
runner.Add("Media offer envelope / strict context and shared canonical vector", MediaOfferEnvelopeTests.RunAsync);
runner.Add("Published readback / shared vector and metadata-only authority", DevicePublishedReadbackTests.RunAsync);
runner.Add("Media source MIME / bounded actual bytes and unknown formats", DeviceFileMediaMimeTests.ByteDerivedMimeAsync);
runner.Add("Media source collection kinds / known exclusion preserves strict sender MIME", DeviceFileMediaMimeTests.CollectionKindsAsync);
runner.Add("Device file metadata commands / fresh echo / no data authority", DeviceFileMetadataCommandTests.BootstrapAsync);
runner.Add("Device file native transport / actual secure echo / read-only identity", DeviceFileConnectionTransportTests.HandshakeAsync);
runner.Add("Device file native transport / uncertain write / scope withdrawal", DeviceFileConnectionTransportTests.FailureAsync);
runner.Add("Device file native transport / OFF handlers / reserved data isolation", DeviceFileConnectionTransportTests.ReservedAsync);
runner.Add("Device file native transport / strict envelope / no expired grace", DeviceFileConnectionTransportTests.EnvelopeAsync);
runner.Add("Device file native transport / lost protected identity / no owner revival", DeviceFileConnectionTransportTests.LostIdentityAsync);
runner.Add("Device file native source status / actual secure output / no READ", DeviceFileConnectionSourcesTests.StatusAsync);
runner.Add("Device file native source status / correlation / schema / withdrawal", DeviceFileConnectionSourcesTests.RejectAsync);
runner.Add("Device file native source status / cancellation / no old reply", DeviceFileConnectionSourcesTests.CancelAsync);
runner.Add("Device file native source status / close / exact cleanup", DeviceFileConnectionSourcesTests.CloseAsync);
runner.Add("Device file native source status / actual bounded timeout", DeviceFileConnectionSourcesTests.TimeoutAsync);
runner.Add("Device file native source status / failed secure output / metadata change", DeviceFileConnectionSourcesTests.OutputFailureAsync);
runner.Add("Device file native source status / prompt metadata and session withdrawal", DeviceFileConnectionSourcesTests.PromptWithdrawalAsync);
runner.Add("Device file metadata commands / withdrawal / monotonic TTL / exact cleanup", DeviceFileMetadataCommandTests.WithdrawalAsync);
runner.Add("Device file channel metadata / successful secure ACK only", DeviceFileConnectionMetadataTests.SecureAckAsync);
runner.Add("Device file channel metadata / withdrawal / superseded replay / replacement", DeviceFileConnectionMetadataTests.WithdrawalAsync);
runner.Add("Device file channel metadata / pairing changes during secure ACK", DeviceFileConnectionMetadataTests.ChangedDuringAckAsync);
runner.Add("Device file channel metadata / protected changes cannot revive receipts", DeviceFileConnectionMetadataTests.DurableChangesAsync);
runner.Add("Device file channel metadata / withdrawal ACK failure / no historical reconsent", DeviceFileConnectionMetadataTests.FailedWithdrawalAckAsync);
runner.Add("Device file source settings / strict metadata codecs", DeviceFileSourcesTests.RunAsync);
runner.Add("Device file video metadata / configure golden / no image-kind coupling", DeviceFileVideoSourceMetadataTests.CodecAsync);
runner.Add("Device file protected preferences / read-only defaults / no bootstrap", DeviceFileStorePreferencesTests.DefaultsAsync);
runner.Add("Device file protected preferences / persistence / exact native choice", DeviceFileStorePreferencesTests.PersistenceAsync);
runner.Add("Device file protected preferences / identity and pairing HOLD", DeviceFileStorePreferencesTests.BindingAsync);
runner.Add("Device file protected preferences / authenticated corruption HOLD", DeviceFileStorePreferencesTests.CorruptionAsync);
runner.Add("Device file protected preferences / strict schema / exhausted revision", DeviceFileStorePreferencesTests.SchemaAsync);
runner.Add("Device file protected preferences / actual restore fence / retained intent", DeviceFileStorePreferencesTests.RestoreAsync);
runner.Add("Device file protected preferences / independent concurrent owners", DeviceFileStorePreferencesTests.ConcurrentAsync);
runner.Add("Device file protected preferences / selectable deletion directions / no runtime grant", DeviceFileStorePreferencesTests.DeletionChoicesAsync);
runner.Add("Device file protected preferences / Notes-style skip deletions checkbox", DeviceFileStorePreferencesTests.NotesStyleDeletionModeAsync);
runner.Add("Device file native directory / conservative local path grammar", DeviceFileNativeDirectoryTests.GrammarAsync);
runner.Add("Device file native receive / conservative leaf grammar", DeviceFileNativeReceiveTests.LeafGrammarAsync);
runner.Add("Device file native run lifecycle / strict batch and END codec", DeviceFileConnectionRunsTests.CodecAsync);
runner.Add("Device file native run lifecycle / retained cleanup lease boundaries", DeviceFileMetadataCommandTests.SourceCleanupLeaseAsync);
runner.Add("Device file native destination / absent read does not bootstrap", DeviceFileStoreDestinationsTests.DefaultsAsync);
runner.Add("Device file native media UI / strict requests reject browser paths and grants", DeviceFileUiTests.StrictRequestsAsync);
if (OperatingSystem.IsWindows())
{
    runner.Add("Phone webcam parent module / original process and fixed sibling layout", PhoneCameraAudioParentModuleTests.FixedLayoutAsync);
    runner.Add("Phone webcam parent module / trusted owner and no unprivileged mutation rights", PhoneCameraAudioParentModuleTests.ProtectedAclAsync);
    runner.Add("Phone webcam parent module / ambiguous callback and oversized ACL denied", PhoneCameraAudioParentModuleTests.AmbiguousAclAsync);
    runner.Add("Phone webcam parent module / actual writable file and ancestor refusal without load", PhoneCameraAudioParentModuleTests.ActualWritableFileAsync);
    runner.Add("Phone webcam parent module / actual junction refusal without load", PhoneCameraAudioParentModuleTests.ActualJunctionAsync);
    runner.Add("Phone webcam parent module / original live authority before resource access", PhoneCameraSessionTests.LoaderRequiresOriginalCurrentAsync);
    runner.Add("Phone webcam parent runtime / exact original callbacks scope and private PCM record", PhoneCameraSessionTests.RuntimeOriginalCallbacksAndRecordsAsync);
    runner.Add("Phone webcam parent runtime / forged authority and original native failure", PhoneCameraSessionTests.RuntimeForgeryAndOriginalFailureAsync);
    runner.Add("Phone webcam parent runtime / cancelled Prepare drains native caller", PhoneCameraSessionTests.RuntimeCancelledPrepareDrainsAsync);
    runner.Add("Phone webcam parent runtime / concurrent Write Stop Close drains before unload", PhoneCameraSessionTests.RuntimeConcurrentWriteCloseAsync);
    runner.Add("Phone webcam parent runtime / unconfirmed Close retains terminal root without retry", PhoneCameraSessionTests.RuntimeUnconfirmedCloseRetainsRootAsync);
    runner.Add("Phone webcam parent runtime / missing immutable resources and explicit mute forbid fallback", PhoneCameraSessionTests.RuntimeProductionNoFallbackOrMutedWorkerAsync);
    runner.Add("Calendar legacy Android alias / Windows actual source wire and RID fixture", CalendarLegacyAndroidImportTests.RunAsync);
    runner.Add("Collection inventory / Windows read-only native identities exclusions and cancellation", DeviceFileCollectionInventoryTests.WindowsInventoryAsync);
    runner.Add("Collection inventory / Windows actual reparse hardlink and paged enumeration", DeviceFileCollectionInventoryTests.WindowsHazardsAsync);
    runner.Add("Collection roots / Windows independent read-only selection protected persistence and replacement HOLD", DeviceFileCollectionRootsTests.WindowsPersistenceAsync);
    runner.Add("Collection folder choice / Windows original native picker metadata only and append-only roots", DeviceFileCollectionSourceTests.WindowsNativeFolderChoiceAsync);
    runner.Add("Destination folder choice / Windows initial same cancel and legacy remain metadata only", DeviceFileDestinationChoiceTests.WindowsChoicesAsync);
    runner.Add("Destination folder choice / Windows original book connection full settings consent control and stale guards", DeviceFileDestinationChoiceTests.WindowsContextAsync);
    runner.Add("Destination folder choice / Windows original deadline and sticky worker retirement", DeviceFileDestinationChoiceTests.WindowsLifetimeAsync);
    runner.Add("Destination folder choice / Windows late original context denies and rolls back initial SQL record", DeviceFileDestinationChoiceTests.WindowsStoreRollbackAsync);
    runner.Add("Destination selection design / Windows retained backup snapshot is not an antirollback current head", DeviceFileDestinationSelectionTests.WindowsBackupAnchorIsNotCurrentSelectionAsync);
    runner.Add("Destination independent witness / Windows explicit metadata cycle preserves original tokens without activation", DeviceFileDestinationSelectionTests.WindowsWitnessChoiceCycleAsync);
    runner.Add("Destination independent witness / Windows old and missing SQL head cannot adopt native inventory", DeviceFileDestinationSelectionTests.WindowsWitnessHeadRollbackAsync);
    runner.Add("Destination independent witness / Windows partial native intent stays uncertain without cleanup or replay", DeviceFileDestinationSelectionTests.WindowsWitnessPartialCommitAsync);
    runner.Add("Destination independent witness / Windows native bytes identities unknown files and missing key HOLD", DeviceFileDestinationSelectionTests.WindowsWitnessNativeGuardsAsync);
    runner.Add("Destination independent witness / Windows bounded append-only capacity without eviction", DeviceFileDestinationSelectionTests.WindowsWitnessCapacityAsync);
    runner.Add("Destination independent witness / Windows strict metadata and lost original never repair from independent intent", DeviceFileDestinationSelectionTests.WindowsWitnessMetadataGuardsAsync);
    runner.Add("Destination independent witness / Windows opposite legacy witness stage and received roots never overlap", DeviceFileDestinationSelectionTests.WindowsWitnessOtherKindAsync);
    runner.Add("Destination independent witness / Windows actual post-SQL withdrawal rolls back head and retains independent intent", DeviceFileDestinationSelectionTests.WindowsWitnessSqlRollbackAsync);
    runner.Add("Destination metadata context / Windows unobserved ABA and observed failure never revive original owner", DeviceFileDestinationSelectionTests.WindowsWitnessOriginalContextAsync);
    runner.Add("Destination native admission / Windows original native picker admits immutable generation without activation", DeviceFileDestinationAdmissionTests.WindowsNativeAdmissionAsync);
    runner.Add("Destination native admission / Windows original proof stays independent of current head and legacy record", DeviceFileDestinationAdmissionTests.WindowsHistoricalAdmissionIndependentAsync);
    runner.Add("Destination native admission / Windows original callback cancellation book consent channel control and slot guards", DeviceFileDestinationAdmissionTests.WindowsAdmissionPickerGuardsAsync);
    runner.Add("Destination native admission / Windows lost original admission never rebuilds from historical flags", DeviceFileDestinationAdmissionTests.WindowsLostAdmissionNeverRebuiltAsync);
    runner.Add("Destination native admission / Windows authenticated generic intent is never actual native admission", DeviceFileDestinationAdmissionTests.WindowsIntentIsNotAdmissionAsync);
    runner.Add("Destination native admission / Windows admission-only loss evidence denies bootstrap and opposite root overlap", DeviceFileDestinationAdmissionTests.WindowsAdmissionLossAndOtherKindAsync);
    runner.Add("Destination native admission / Windows immutable original descriptor native bytes file identity and key guards", DeviceFileDestinationAdmissionTests.WindowsAdmissionOriginalGuardsAsync);
    runner.Add("Destination native admission / Windows actual original deadline never restarts after native picker", DeviceFileDestinationAdmissionTests.WindowsAdmissionOriginalDeadlineAsync);
    runner.Add("Destination native admission / Windows actual generation SQL failure rolls back head without adopting intent", DeviceFileDestinationAdmissionTests.WindowsAdmissionSqlAtomicityAsync);
    runner.Add("Destination admitted original job / Windows actual backup trash preview restore independent of lost current and legacy records", DeviceFileDestinationAdmissionTests.WindowsOriginalJobUsesIndependentAdmissionAsync);
    runner.Add("Destination generation backups / Windows immutable legacy and admitted generation parent choices stay separate", DeviceFileDestinationAdmissionTests.WindowsGenerationBackupParentsAsync);
    runner.Add("Destination admitted source / Windows original mapping independent of current selection PC receive and phone read", DeviceFileDestinationAdmissionTests.WindowsAdmittedMappedSourceIndependentAsync);
    runner.Add("Collection producer / Windows two original offers actual END and fresh unchanged pass", DeviceFileCollectionSourceTests.WindowsCollectionProducerAsync);
    runner.Add("Collection producer / Windows automatic gate original catalog and content guards", DeviceFileCollectionSourceTests.WindowsCollectionProducerGuardsAsync);
    runner.Add("Collection producer / Windows actual changed successor exact previous publication and END", DeviceFileCollectionSourceTests.WindowsCollectionProducerSuccessorAsync);
    runner.Add("Collection producer / Windows late edits and additions after genuine individual END hold whole pass", DeviceFileCollectionSourceTests.WindowsCollectionProducerLateInventoryAsync);
    runner.Add("Collection overlap / Windows actual fully read mapped members inside explicit root are not offered twice", DeviceFileCollectionSourceTests.WindowsCollectionMappedOverlapAsync);
    runner.Add("Collection overlap / Windows actual changed mapped member reaches END before overlap skip", DeviceFileCollectionSourceTests.WindowsCollectionChangedMappedOverlapAsync);
    runner.Add("Collection overlap guards / Windows late edits filtered unprepared and foreign witnesses HOLD", DeviceFileCollectionSourceTests.WindowsCollectionOverlapGuardsAsync);
    runner.Add("Collection media kinds / Windows known opposite container excluded without video SEND", DeviceFileCollectionSourceTests.WindowsCollectionKnownOppositeTypeAsync);
    runner.Add("Collection media kinds / Windows unknown broken and photos-only mixed roots preserve gates", DeviceFileCollectionSourceTests.WindowsCollectionKindGuardsAsync);
    runner.Add("Collection previous destination / Windows migration HOLD preserves original mapping source and history", DeviceFileCollectionSourceTests.WindowsCollectionPreviousDestinationAsync);
    runner.Add("Collection folder choice / Windows original book connection intent control catalog guards", DeviceFileCollectionSourceTests.WindowsNativeFolderChoiceGuardsAsync);
    runner.Add("Collection roots / Windows pairing ciphertext and missing-key HOLD preserve source records", DeviceFileCollectionRootsTests.WindowsTamperAsync);
    runner.Add("Collection generation / Windows actual file and ancestor creation witness no owner revival", DeviceFileCollectionInventoryTests.WindowsGenerationAsync);
    runner.Add("Collection generation / Windows versioned root witness legacy and malformed HOLD", DeviceFileCollectionRootsTests.WindowsGenerationAsync);
    runner.Add("Collection source / Windows independent PC-only origin cache versions and actual wire END", DeviceFileCollectionSourceTests.WindowsActualSourceAsync);
    runner.Add("Collection source / Windows original consent book and entire-scope guards", DeviceFileCollectionSourceTests.WindowsOwnerGuardsAsync);
    runner.Add("Collection source / Windows mixed mapped history and strict authenticated origin schema", DeviceFileCollectionSourceTests.WindowsMixedHistoryAndSchemaAsync);
    runner.Add("Collection source paths / Windows full native relative paths and legacy origin HOLD", DeviceFileCollectionSourceTests.WindowsPathHistoryAsync);
    runner.Add("Collection source backup / Windows explicit output dedup and independent offline raw restore", DeviceFileCollectionSourceTests.WindowsPreparedBackupAsync);
    runner.Add("Collection source backup / Windows interrupted exact candidate unaligned resume", DeviceFileCollectionSourceTests.WindowsPreparedBackupInterruptedAsync);
    runner.Add("Collection source backup / Windows corrupt prefix HOLD without truncation", DeviceFileCollectionSourceTests.WindowsPreparedBackupCorruptAsync);
    runner.Add("Collection source backup / Windows original source withdrawal cannot be renewed by output consent", DeviceFileCollectionSourceTests.WindowsPreparedBackupWithdrawalAsync);
    runner.Add("Collection source backup / Windows complete interrupted bytes independently recover offline", DeviceFileCollectionSourceTests.WindowsPreparedBackupPendingOfflineAsync);
    runner.Add("Collection source backup / Windows actual local copy drains before source disposal END", DeviceFileCollectionSourceTests.WindowsPreparedBackupDrainAsync);
    runner.Add("Independent PC recovery / Windows offline native choice saved book lane and exact retry", DeviceFileCollectionSourceTests.WindowsIndependentRecoveryChoiceAsync);
    runner.Add("Independent PC recovery / Windows collision exact FID resume and restored source HOLD", DeviceFileCollectionSourceTests.WindowsIndependentRecoveryResumeAsync);
    runner.Add("Media independent choices / Windows import display does not expand authority", DeviceFileSharedPreferencesTests.IndependentDirectionViewAsync);
    runner.Add("Media shared storage / Windows readonly persistence independent fields and merge", DeviceFileSharedPreferencesTests.PersistenceAsync);
    runner.Add("Media shared storage / Windows seven-field projection preserves original ciphertext and clocks", DeviceFileSharedPreferencesTests.SevenFieldProjectionAsync);
    runner.Add("Media shared storage / Windows preserve legacy choices and ambiguous deletions", DeviceFileSharedPreferencesTests.LegacyAsync);
    runner.Add("Media shared storage / Windows corruption pairing identity and restore HOLD", DeviceFileSharedPreferencesTests.BindingAsync);
    runner.Add("Media shared transport / Windows actual bilateral ACK exact snapshot and no grants", DeviceFileSharedTransportTests.MatchedAsync);
    runner.Add("Media shared transport / Windows old capability and failed secure ACK HOLD", DeviceFileSharedTransportTests.GuardsAsync);
    runner.Add("Media local receiving consent / Windows remote intent cannot grant and protected persistence", DeviceFileReceiveConsentTests.DefaultsAndPersistenceAsync);
    runner.Add("Media local sending consent / Windows independent defaults persistence and pairing", DeviceFileSendConsentTests.DefaultsAndPersistenceAsync);
    runner.Add("Media local sending consent / Windows corrupted ciphertext stays held", DeviceFileSendConsentTests.CorruptionStaysHeldAsync);
    runner.Add("Media local sending consent / Windows actual mapped source and cache withdrawal", DeviceFileMappedSourceTests.WindowsSendingConsentWithdrawalAsync);
    runner.Add("Media native sending dialog / Windows exact native answer and stale context", DeviceFileSendConsentTests.NativeDialogContextAsync);
    runner.Add("Media local receiving consent / Windows actual receiver withdrawal is sticky", DeviceFileReceiveConsentTests.ActualWithdrawalAsync);
    runner.Add("Media shared projection / Windows local rights master and unchanged idempotence", DeviceFileSharedProjectionTests.RightsAndMasterAsync);
    runner.Add("Media shared projection / Windows stale snapshot and native write rollback", DeviceFileSharedProjectionTests.AtomicFenceAsync);
    runner.Add("Media shared projection / Windows VIDEO-only base bootstrap and actual data ACK", DeviceFileConnectionCommandsTests.WindowsSharedVideoOnlyBootstrapAsync);
    runner.Add("Media shared projection / Windows explicit manual inventory actual receive Saved END", DeviceFileAutomaticTests.WindowsSharedManualReceiveSavedAsync);
    runner.Add("Media shared incoming / Windows video inventory adopts fresh enabled status without configure", DeviceFileAutomaticTests.WindowsSharedManualVideoInventoryAsync);
    runner.Add("Media shared incoming automatic / Windows actual fresh status chunks Saved END without configure", DeviceFileAutomaticTests.WindowsSharedAutomaticReceiveSavedAsync);
    runner.Add("Media automatic original intent / Windows later matched snapshot cannot replace admitted root", DeviceFileAutomaticTests.WindowsSharedAutomaticOriginalIntentAsync);
    runner.Add("Media shared incoming / Windows phone source OFF repair and association stay review", DeviceFileAutomaticTests.WindowsSharedSourceOffReviewAsync);
    runner.Add("Media shared transport / Windows manual duplicate deadline stale intent and failed ACK guards", DeviceFileSharedTransportTests.ManualGuardsAsync);
    runner.Add("Media backup exclusions / Windows former backup destination rejection without catalog", DeviceFileBackupExclusionTests.WindowsDestinationAsync);
    runner.Add("Media backup locations / Windows retained parents default and idempotence", DeviceFileBackupLocationTests.WindowsChoicesAsync);
    runner.Add("Media backup locations / Windows actual catalogs and historical restore source", DeviceFileBackupLocationTests.WindowsCatalogsAndRestoreAsync);
    runner.Add("Media backup locations / Windows rollback foreign folder and corruption HOLD", DeviceFileBackupLocationTests.WindowsFencesAsync);
    runner.Add("Media backup maintenance / Windows actual input CPU and memory sample", DeviceFileBackupMaintenanceTests.WindowsNativeSampleAsync);
    runner.Add("Media backup bytes / Windows held FID independent copy and new restore", DeviceFileBackupBytesTests.WindowsCopyRestoreAsync);
    runner.Add("Media backup bytes / Windows digest existing target and stale identity HOLD", DeviceFileBackupBytesTests.WindowsRejectAsync);
    runner.Add("Media backup bytes / Windows bounded abort and held source exclusion", DeviceFileBackupBytesTests.WindowsAbortAsync);
    runner.Add("Media backup bytes / Windows verified empty independent object", DeviceFileBackupBytesTests.WindowsEmptyAsync);
    runner.Add("Media backup catalog / Windows actual Saved dedup across names and new restore", DeviceFileBackupCatalogTests.WindowsDedupAsync);
    runner.Add("Media backup catalog / Windows different bytes versions and PC edits HOLD", DeviceFileBackupCatalogTests.WindowsDifferentVersionsAsync);
    runner.Add("Media backup catalog / Windows partial registered candidate same FID resume", DeviceFileBackupCatalogTests.WindowsInterruptedAsync);
    runner.Add("Media backup pending / Windows complete interrupted copy offline recoverable", DeviceFileBackupCatalogTests.WindowsCompleteInterruptedOfflineAsync);
    runner.Add("Media backup pending / Windows partial and complete exact-FID retry", DeviceFileBackupCatalogTests.WindowsPendingRetryAsync);
    runner.Add("Media backup pending / Windows corrupt bytes and replaced FID HOLD", DeviceFileBackupCatalogTests.WindowsPendingCorruptionAsync);
    runner.Add("Media backup catalog / Windows corrupt candidate prefix preserved HOLD", DeviceFileBackupCatalogTests.WindowsCorruptCandidateAsync);
    runner.Add("Media backup catalog / Windows foreign Backup folder never adopted", DeviceFileBackupCatalogTests.WindowsForeignFolderAsync);
    runner.Add("Media backup catalog / Windows local restore after source and connection gone", DeviceFileBackupCatalogTests.WindowsLocalRestoreAsync);
    runner.Add("Media backup catalog / Windows corrupt object snapshot anchor HOLD", DeviceFileBackupCatalogTests.WindowsCorruptionAsync);
    runner.Add("Media backup catalog / Windows actual saved book receive END and unchanged lane", DeviceFileBackupCatalogTests.WindowsJoinedLifecycleAsync);
    runner.Add("Media backup recovery / Windows native new-file publication after disconnect", DeviceFileBackupCatalogTests.WindowsPublishedRestoreAsync);
    runner.Add("Media backup recovery / Windows interrupted copy and published FID recovery", DeviceFileBackupCatalogTests.WindowsInterruptedPublishedRestoreAsync);
    runner.Add("Media backup recovery / Windows local UI saved book and shared worker", DeviceFileBackupCatalogTests.WindowsLocalBackupUiAsync);
    runner.Add("Device file native directory / Windows actual handle and identity", DeviceFileNativeDirectoryTests.WindowsHandleAsync);
    runner.Add("Device file native directory / Windows actual reparse rejection", DeviceFileNativeDirectoryTests.WindowsReparseAsync);
    runner.Add("Device file native receive / Windows actual no-replace publication", DeviceFileNativeReceiveTests.WindowsPublicationAsync);
    runner.Add("Device file native source / Windows original mapped file bounded read", DeviceFileNativeReceiveTests.WindowsManagedSourceAsync);
    runner.Add("Device file native source / Windows cancellation drains original read", DeviceFileNativeReceiveTests.WindowsManagedSourceDrainAsync);
    runner.Add("Device file native source / Windows metadata selection on held original", DeviceFileNativeReceiveTests.WindowsManagedSourceMetadataAsync);
    runner.Add("Device file mapped source / Windows actual completed mapping and matched send intent", DeviceFileMappedSourceTests.WindowsCompletedMappingAsync);
    runner.Add("Device file mapped source / Windows original saved book and file identity", DeviceFileMappedSourceTests.WindowsOriginalBookAndFileAsync);
    runner.Add("Device file mapped source / Windows import scope and actual metadata filter", DeviceFileMappedSourceTests.WindowsScopeAndMetadataAsync);
    runner.Add("Device file source cache / Windows actual sealed preparation and original history", DeviceFileSourceCacheTests.WindowsActualFreezeAsync);
    runner.Add("Device file source cache / Windows corruption and missing original record", DeviceFileSourceCacheTests.WindowsCorruptionAndMissingHeadAsync);
    runner.Add("Device file source cache / Windows original book change during committed copy", DeviceFileSourceCacheTests.WindowsSaveDuringCopyAsync);
    runner.Add("Device file source cache / Windows cancellation drains actual cache read", DeviceFileSourceCacheTests.WindowsCancellationDrainsReadAsync);
    runner.Add("Device file source send / Windows actual secure requested chunks and peer Saved", DeviceFileSourceSendTests.WindowsActualSecureSendAsync);
    foreach (var scenario in new[] { "none", "publication", "mime", "early", "cancel" })
        runner.Add("Published readback / Windows actual sender " + scenario, () => DeviceFileSourceSendTests.WindowsCorrelatedReadbackAsync(scenario));
    foreach (var scenario in new[] { "end-none", "end-publication", "end-early", "end-cancel" })
        runner.Add("Source END / Windows actual sender " + scenario, () => DeviceFileSourceSendTests.WindowsCorrelatedReadbackAsync(scenario));
    foreach (var scenario in new[] { "successor-new", "successor-unchanged", "successor-incomplete", "successor-corrupt" })
        runner.Add("Source successor / Windows actual sender " + scenario, () => DeviceFileSourceSendTests.WindowsCorrelatedReadbackAsync(scenario));
    runner.Add("Source successor / Windows actual sender successor-chain", () => DeviceFileSourceSendTests.WindowsCorrelatedReadbackAsync("successor-chain"));
    runner.Add("Source successor / Windows unattempted preparation stays held", DeviceFileSourceSendTests.WindowsSuccessorBeforeOfferAsync);
    runner.Add("Source successor / Windows actual sender successor-during-copy", () => DeviceFileSourceSendTests.WindowsCorrelatedReadbackAsync("successor-during-copy"));
    runner.Add("Mapped export / Windows actual manual pass versions and unchanged dedup", DeviceFileSourceSendTests.WindowsMappedOutgoingPassAsync);
    runner.Add("Mapped export / Windows actual WiFi automatic pass and unchanged dedup", DeviceFileSourceSendTests.WindowsMappedAutomaticOutgoingPassAsync);
    runner.Add("Mapped native UI export / Windows own SEND dialog control ACK and source END without RECEIVE", DeviceFileSourceSendTests.WindowsNativeUiOutgoingPassAsync);
    runner.Add("Shared UI request export / Windows strict request native status and source END without RECEIVE", DeviceFileSourceSendTests.WindowsSharedUiRequestPassAsync);
    runner.Add("Shared UI request export / Windows cancel before control ACK preserves source", DeviceFileSourceSendTests.WindowsSharedUiRequestCancelAsync);
    runner.Add("Shared UI reply failure / Windows cancels and drains before releasing UI dispatch", DeviceFileSourceSendTests.WindowsSharedUiReplyFailureAsync);
    runner.Add("Video preview native / Windows actual memory-only H264 frame orientation and withdrawal", DeviceFileVideoPreviewTests.WindowsFrameAsync);
    if (Directory.Exists(Path.Combine(AppContext.BaseDirectory, "preview-product")))
        runner.Add("Video preview rotation / Windows actual product JPEG honors native display matrix", DeviceFileVideoPreviewTests.WindowsProductRotationAsync);
    if (Directory.Exists(Path.Combine(AppContext.BaseDirectory, "preview-product")))
        runner.Add("Video preview retained product / Windows actual wire Saved END original trash and native JPEG", DeviceFileConnectionReceiveTests.WindowsVideoWireRetainedProductPreviewAsync);
    runner.Add("Mapped native UI export / Windows SEND-only withdrawal while awaiting actual peer ACK", DeviceFileSourceSendTests.WindowsNativeUiSendWithdrawalAsync);
    runner.Add("Mapped native UI export / Windows close while awaiting actual peer ACK", DeviceFileSourceSendTests.WindowsNativeUiSendCloseAsync);
    runner.Add("Mapped export / Windows import-only and unknown content before output", DeviceFileSourceSendTests.WindowsMappedOutgoingRejectsScopeAndUnknownBytesAsync);
    runner.Add("Mapped export / Windows actual photos-only filter before preparation", DeviceFileSourceSendTests.WindowsMappedPhotoFilterBeforePreparationAsync);
    runner.Add("Device file source send / Windows early Saved and missing exchange hold", DeviceFileSourceSendTests.WindowsRejectsEarlySavedAndLostAttemptAsync);
    runner.Add("Device file source send / Windows actual offer output cancellation drains", DeviceFileSourceSendTests.WindowsOfferDrainAndCancellationAsync);
    runner.Add("Device file source send / Windows early acceptance waits for actual output", DeviceFileSourceSendTests.WindowsEarlyAcceptanceWaitsForOutputAsync);
    runner.Add("Device file source send / Windows unknown MIME holds before output", DeviceFileSourceSendTests.WindowsUnknownMimeBeforeOutputAsync);
    runner.Add("Device file native receive / Windows actual content verification", DeviceFileNativeReceiveTests.WindowsVerificationAsync);
    runner.Add("Device file native receive / Windows uncertain publication and reparse", DeviceFileNativeReceiveTests.WindowsUncertainAndReparseAsync);
    runner.Add("Device file native destination / Windows independent protected roots", DeviceFileStoreDestinationsTests.WindowsPersistenceAsync);
    runner.Add("Destination choice staging / Windows inert append-only native choice preserves active original", DeviceFileStoreDestinationsTests.WindowsInertChoiceStagingAsync);
    runner.Add("Destination choice staging / Windows original catalog generation context and ciphertext guards", DeviceFileStoreDestinationsTests.WindowsInertChoiceStagingGuardsAsync);
    runner.Add("Destination choice staging / Windows bounded capacity missing key and original never bootstrap", DeviceFileStoreDestinationsTests.WindowsInertChoiceCapacityAndKeyAsync);
    runner.Add("Completed destination owner / Windows staged choice cannot displace original raw backup trash preview and restore", DeviceFileStoreDestinationsTests.WindowsOriginalJobRecoveryAfterStagingAsync);
    runner.Add("Completed destination owner / Windows exact authenticated job original root key and irreversible metadata retirement", DeviceFileStoreDestinationsTests.WindowsOriginalJobOwnerGuardsAsync);
    runner.Add("Completed destination source / Windows staged metadata cannot replace original mapped source through actual END", DeviceFileCollectionSourceTests.WindowsCollectionChangedMappedAfterStagingAsync);
    runner.Add("Lost destination original / Windows received and staged evidence forbid first-choice fallback", DeviceFileStoreDestinationsTests.WindowsLostDestinationCannotInitializeAsync);
    runner.Add("Lost destination original / Windows historical other-kind overlap holds but distinct first choice stays metadata", DeviceFileStoreDestinationsTests.WindowsLostDestinationOtherKindAsync);
    runner.Add("Device file native destination / Windows overlap and original-root reopen", DeviceFileStoreDestinationsTests.WindowsOverlapAndReopenAsync);
    runner.Add("Device file native destination / Windows binding and ciphertext HOLD", DeviceFileStoreDestinationsTests.WindowsBindingAndTamperAsync);
    runner.Add("Device file native destination / Windows missing database never bootstraps", DeviceFileStoreDestinationsTests.WindowsMissingDatabaseAsync);
    runner.Add("Device file native receive job / Windows secure agreement to protected publication", DeviceFileReceiveJobTests.WindowsActualReceiveAsync);
    runner.Add("Device file native receive job / Windows metadata filter preserves rejected staged originals", DeviceFileReceiveJobTests.WindowsPhotoMetadataSelectionAsync);
    runner.Add("Device file native receive job / Windows interrupted original and withdrawal", DeviceFileReceiveJobTests.WindowsInterruptedAndWithdrawnAsync);
    runner.Add("Device file native receive job / Windows partial publication preserves history", DeviceFileReceiveJobTests.WindowsPartialPublicationAsync);
    runner.Add("Device file native receive job / Windows missing history and occupied target", DeviceFileReceiveJobTests.WindowsMissingHistoryAndOccupiedAsync);
    runner.Add("Device file native receive job / Windows key withdrawal and corrupt history", DeviceFileReceiveJobTests.WindowsKeyWithdrawalAndCorruptionAsync);
    runner.Add("Device file native receive job / Windows reserved job and byte bounds", DeviceFileReceiveJobTests.WindowsReservationBoundsAsync);
    runner.Add("Device file native media commands / Windows configure catalog permission", DeviceFileConnectionCommandsTests.WindowsConfigureDiscoverPermissionAsync);
    runner.Add("Device file native media commands / Windows choice and output withdrawal", DeviceFileConnectionCommandsTests.WindowsChoiceAndOutputWithdrawalAsync);
    runner.Add("Device file native media commands / Windows fresh positive video only", DeviceFileConnectionCommandsTests.WindowsVideoNeedsCurrentPositiveAsync);
    runner.Add("Device file native media commands / Windows wrong scope and close cleanup", DeviceFileConnectionCommandsTests.WindowsPendingCloseAndWrongScopeAsync);
    runner.Add("Device file native media commands / Windows cancellation and no old reply", DeviceFileConnectionCommandsTests.WindowsCancellationAsync);
    runner.Add("Device file native media commands / Windows superseded positive video", DeviceFileConnectionCommandsTests.WindowsSupersededVideoAsync);
    runner.Add("Device file native media commands / Windows actual bounded timeout", DeviceFileConnectionCommandsTests.WindowsActualTimeoutAsync);
    runner.Add("Device file native media commands / Windows video after current data ACK", DeviceFileConnectionCommandsTests.WindowsVideoAfterActualDataAckAsync);
    runner.Add("Device file native run lifecycle / Windows original batch END and advance", DeviceFileConnectionRunsTests.WindowsBatchEndAndAdvanceAsync);
    runner.Add("Device file native run lifecycle / Windows metadata cleanup after withdrawal", DeviceFileConnectionRunsTests.WindowsCleanupAfterWithdrawalAsync);
    runner.Add("Device file native run lifecycle / Windows reused next owner HOLD", DeviceFileConnectionRunsTests.WindowsRejectReusedNextAsync);
    runner.Add("Device file native run lifecycle / Windows media cursor and album provenance", DeviceFileConnectionRunsTests.WindowsMediaPagesAndAlbumScopeAsync);
    runner.Add("Device file native run lifecycle / Windows unconfirmed END and rollback HOLD", DeviceFileConnectionRunsTests.WindowsUnconfirmedEndAndRollbackAsync);
    runner.Add("Device file native run lifecycle / Windows correlated original source resume history", DeviceFileConnectionRunsTests.WindowsOriginalSourceResumeHistoryAsync);
    runner.Add("Device file native run lifecycle / Windows resume correlation and expiry HOLD", DeviceFileConnectionRunsTests.WindowsResumeCorrelationAndExpiryAsync);
    runner.Add("Device file native run lifecycle / Windows stale local resume owner HOLD", DeviceFileConnectionRunsTests.WindowsResumeStaleLocalOwnerAsync);
    runner.Add("Device file native run lifecycle / Windows actual original checkpoint recovery", DeviceFileConnectionRunsTests.WindowsActualCheckpointRecoveryAsync);
    runner.Add("Device file native run lifecycle / Windows checkpoint mutation preserves bytes", DeviceFileConnectionRunsTests.WindowsCheckpointMutationHoldAsync);
    runner.Add("Device file native run lifecycle / Windows recovered source resume and metadata cleanup", DeviceFileConnectionRunsTests.WindowsRecoveredSourceResumeAndCleanupAsync);
    runner.Add("Device file native offer routing / Windows offer before correlated command result", DeviceFileConnectionRunsTests.WindowsOfferBeforeCommandResultAsync);
    runner.Add("Device file native offer routing / Windows early offer scope and expiry HOLD", DeviceFileConnectionRunsTests.WindowsEarlyOfferCorrelationHoldAsync);
    runner.Add("Device file native wire receive / Windows actual admission chunks Saved END", DeviceFileConnectionReceiveTests.WindowsActualReceiveSavedEndAsync);
    runner.Add("Device file native wire receive / Windows invalid chunks preserve original stage", DeviceFileConnectionReceiveTests.WindowsBadChunkAndPartialHistoryAsync);
    runner.Add("Device file native wire receive / Windows Saved END after receive withdrawal", DeviceFileConnectionReceiveTests.WindowsEndAfterReceiveWithdrawalAsync);
    runner.Add("Device file native wire receive / Windows stop drain original wire resume", DeviceFileConnectionReceiveTests.WindowsWireStopDrainAndOriginalResumeAsync);
    runner.Add("Device file native wire receive / Windows uncertain Saved or END retains budget", DeviceFileConnectionReceiveTests.WindowsUncertainSavedOrEndKeepsBudgetAsync);
    runner.Add("Device file native wire receive / Windows independently activated video destination", DeviceFileConnectionReceiveTests.WindowsSeparateVideoWireReceiveAsync);
    runner.Add("Device file native reconcile / Windows repeat preserves local edit and skips unchanged", DeviceFileReconcileTests.WindowsRepeatKeepsLocalEditsAsync);
    runner.Add("Device file native reconcile / Windows changed source held without destructive replacement", DeviceFileReconcileTests.WindowsChangedSourceIsHeldAsync);
    runner.Add("Device file native reconcile / Windows mixed preview selects only new content", DeviceFileReconcileTests.WindowsMixedPreviewSelectsOnlyNewAsync);
    runner.Add("Device file native reconcile / Windows corrupt subset and reused owner HOLD", DeviceFileReconcileTests.WindowsSelectionRejectsChangedSubsetAsync);
    runner.Add("Device file native media trash / Windows original bytes restore and stale replay HOLD", DeviceFileMediaTrashTests.WindowsOriginalTrashRestoreAsync);
    runner.Add("Device file native media trash / Windows readonly preview exact retained file and withdrawal HOLD", DeviceFileMediaTrashTests.WindowsReadonlyTrashPreviewAsync);
    // Optional actual-product fixture, staged only by the bounded native probe.
    if (Directory.Exists(Path.Combine(AppContext.BaseDirectory, "preview-product")))
    {
        runner.Add("Device file native media trash / Windows actual product drawing preview", DeviceFileMediaTrashTests.WindowsActualProductDrawingPreviewAsync);
        runner.Add("Tray appearance / Windows actual product drawing", TrayAppearanceTests.DrawingAsync);
    }
    runner.Add("Device file native media trash / Windows occupied restore and original retry", DeviceFileMediaTrashTests.WindowsRestoreOccupiedTargetAsync);
    runner.Add("Device file native media trash / Windows changed identity content and permit HOLD", DeviceFileMediaTrashTests.WindowsTrashChangedSourceAndPermitHoldAsync);
    runner.Add("Device file native media trash / Windows interrupted move and original recovery", DeviceFileMediaTrashTests.WindowsInterruptedMoveRecoveryAsync);
    runner.Add("Device file native media trash / Windows album restore keeps incremental baseline", DeviceFileMediaTrashTests.WindowsAlbumTrashRestoreAsync);
    runner.Add("Device file native media trash / Windows corrupt protected journal HOLD", DeviceFileMediaTrashTests.WindowsCorruptTrashHistoryHoldAsync);
    runner.Add("Device file native media purge / Windows canonical retention never and exact native confirmation", DeviceFileMediaPurgeTests.WindowsRetentionAndManualNeverAsync);
    runner.Add("Device file native media purge / Windows actual expired original removal", DeviceFileMediaPurgeTests.WindowsActualExpiryAsync);
    runner.Add("Device file native media purge / Windows foreign file destination and saved policy HOLD", DeviceFileMediaPurgeTests.WindowsForeignFileAndPolicyHoldAsync);
    runner.Add("Device file native media purge / Windows prepared removed and foreign-name recovery", DeviceFileMediaPurgeTests.WindowsInterruptedRemovalRecoveryAsync);
    runner.Add("Device file native media purge / Windows native UI lane Never sweep and actual failed save HOLD", DeviceFileMediaPurgeTests.WindowsNativeUiAndFailedSaveAsync);
    runner.Add("Device file native media purge / Windows original replacement archive held through Saved and source END", DeviceFileMediaPurgeTests.WindowsReplacementArchiveUntilSavedEndAsync);
    runner.Add("Device file native replacement / Windows original trash latest baseline and repeated replacement", DeviceFileReplacementTests.WindowsReplacementChainAsync);
    runner.Add("Device file native replacement / Windows withdrawn consent and local edit HOLD", DeviceFileReplacementTests.WindowsReplacementWithdrawalAndEditAsync);
    runner.Add("Device file native replacement / Windows occupied publication preserves old and new user bytes", DeviceFileReplacementTests.WindowsReplacementOccupiedPublicationAsync);
    runner.Add("Device file native replacement / Windows media binding overlapping reservation and stale consent HOLD", DeviceFileReplacementTests.WindowsReplacementAdmissionGuardsAsync);
    runner.Add("Device file native saved book / Windows actual failed save revokes media authority", DeviceFileBookPermitTests.WindowsFailedNativeSaveRevokesAsync);
    runner.Add("Device file native saved book / Windows canonical policy and prewrite rejection", DeviceFileBookPermitTests.WindowsSavedPolicyAndRejectedSaveAsync);
    runner.Add("Device file native saved book / Windows actual incoming data after book change HOLD", DeviceFileBookPermitTests.WindowsBookChangedDuringActualReceiveAsync);
    runner.Add("Device file automatic media / Windows actual saved book ACK fresh catalog and empty END", DeviceFileAutomaticTests.WindowsEmptyAlbumAsync);
    runner.Add("Device file automatic media / Windows owned stop cleanup and paused next tick", DeviceFileAutomaticTests.WindowsStopPreparingAsync);
    runner.Add("Device file automatic media / Windows video requires fresh ACK configure then catalog", DeviceFileAutomaticTests.WindowsVideoEmptyAlbumAsync);
    runner.Add("Device file automatic media / Windows actual chunks publication Saved and source END", DeviceFileAutomaticTests.WindowsReceiveSavedAsync);
    runner.Add("Device file automatic media / Windows actual service starts and drains tracked loop", DeviceFileAutomaticTests.WindowsServiceLifetimeAsync);
    runner.Add("Device file native media UI / Windows explicit owner actual ACK and no locked-book revival", DeviceFileUiTests.WindowsExplicitNativeUiHandshakeAsync);
    runner.Add("Device file native media UI / Windows legacy explicit activation preserves pairing and requires reconnect", DeviceFileUiTests.WindowsLegacyActivationAsync);
    runner.Add("Device file native media UI / Windows standard phone photo and video destinations preserve existing files", DeviceFileUiTests.WindowsDefaultDestinationsAsync);
    runner.Add("Device file native media UI / Windows fresh closed source permits metadata but never implicit data", DeviceFileUiTests.WindowsClosedSourceBootstrapAsync);
    runner.Add("Device file native media UI / Windows access rights before album scan require actual foreground consent", DeviceFileUiTests.WindowsReadBeforeAlbumScanAsync);
    runner.Add("Device file native media UI / Windows actual status configure catalog and unknown album HOLD", DeviceFileUiTests.WindowsUiActualDiscoveryAsync);
    runner.Add("Device file native media UI / Windows source count mismatch stays review without deletion proof", DeviceFileAlbumTests.WindowsPartialAlbumCoverageAsync);
    runner.Add("Device file native album / Windows stable namespace folders and same-name separation", DeviceFileAlbumTests.WindowsStableAlbumNamespaceAsync);
    runner.Add("Device file native album / Windows replaced album directory HOLD", DeviceFileAlbumTests.WindowsAlbumReplacementHoldAsync);
    runner.Add("Device file native album / Windows existing unowned album directory HOLD", DeviceFileAlbumTests.WindowsUnownedAlbumFolderHoldAsync);
    runner.Add("Device file native album / Windows original album wire stop and resume", DeviceFileConnectionReceiveTests.WindowsAlbumWireStopDrainAndOriginalResumeAsync);
    runner.Add("Device file native album / Windows whole album batch loop and empty terminal", DeviceFileAlbumTests.WindowsWholeAlbumBatchLoopAsync);
    runner.Add("Device file native album / Windows whole album preparing cancellation and drain", DeviceFileAlbumTests.WindowsWholeAlbumPreparingCancelAsync);
    runner.Add("Device file native album / Windows real saved book change stops worker but permits source cleanup", DeviceFileAlbumTests.WindowsWholeAlbumSavedBookChangedAsync);
}
else
    runner.Add("Device file native directory / non-Windows rejects ownership", DeviceFileNativeDirectoryTests.UnsupportedPlatformAsync);
runner.Add("Device file video metadata / negotiated extension / strict counters", DeviceFileVideoSourceMetadataTests.StatusCodecAsync);
runner.Add("Device file video metadata / actual current channel / no READ", DeviceFileVideoSourceMetadataTests.CurrentChannelAsync);
runner.Add("Device file video metadata / withdrawal / base photo independence", DeviceFileVideoSourceMetadataTests.WithdrawalAsync);
runner.Add("Device file video metadata / scoped commands / shared golden vectors", DeviceFileVideoSourceMetadataTests.ScopedCommandsAsync);
runner.Add("Device file video metadata / typed results / no image fallback", DeviceFileVideoSourceMetadataTests.ScopedResultsAsync);
runner.Add("Device file acceptance / exact offer metadata", DeviceFileAcceptanceEnvelopeTests.RunAsync);
runner.Add("Device file chunks / exact accepted source bytes", DeviceFileChunkEnvelopeTests.RunAsync);
runner.Add("Device file saved confirmation / historical remote metadata", DeviceFileSavedEnvelopeTests.RunAsync);
runner.Add("Photo destination / native pictures path projection", PhotoDestinationPathsTests.RunAsync);
runner.Add("Device file resume / native binding / actual readback / checkpoint rejection", DeviceFileResumeLedgerTests.RunAsync);
runner.Add("KDE contact import / projection / source binding", KdeContactImportTests.RunAsync);
runner.Add("KDE digitizer / delta state / pressure / reset", KdeDigitizerTests.RunAsync);
runner.Add("KDE media / player lifetime / bounded metadata / commands", KdeMediaTests.RunAsync);
runner.Add("KDE systemvolume / output mute / native receipts / pinned TLS", KdeSystemVolumeTests.RunAsync);
runner.Add("KDE filesystem / pinned TLS source / native arguments / revocation", KdeFilesystemTests.RunAsync);
runner.Add("KDE input / bounded packets / target lifetime / presenter", KdeInputTests.RunAsync);
runner.Add("Drawing SVG / inline PNG / external reference rejection", DrawingSvgTests.RunAsync);
runner.Add("WebView2 / Handbuch-Start / Navigationssicherheit", WebViewStartupSourceTests.RunAsync);
runner.Add("WebView2 / geschützte Assets / URI / Header", ProtectedAssetPolicyTests.RunAsync);
runner.Add("Shell-Öffnen / URI-Positivliste / lokale Pfade", ShellLauncherTests.RunAsync);
runner.Add("Windows-Update / Manifest / Download / Installation", WindowsUpdateTests.RunAsync);
runner.Add("Release-Audit / Windows-Manifest / Installer / Prüfsummen", WindowsReleaseAuditTests.RunAsync);
runner.Add("F11-Vollbild / WebView2 / Persistenz / Tray", FullscreenSourceTests.RunAsync);
runner.Add("Native Lokalisierung / 20 Sprachen / Fallback", NativeLocalizationTests.RunAsync);
runner.Add("Lokalisierte Fehlergrenzen / Sync / Sicherung / Gesamtarchiv", LocalizationBoundaryTests.RunAsync);
runner.Add("Regionale Einstellungen / Grenzen / frühe Persistenz", RegionalSettingsTests.RunAsync);
runner.Add("Time zone management / optional sources / manual fallback", TimeZoneManagementTests.RunAsync);
runner.Add("Telefonnummern / Herkunft / gemeinsame Vektoren", PhoneRegionInfoTests.RunAsync);
runner.Add("Ersteinrichtung / Zustand / Atomik / Startreihenfolge", FirstRunSetupTests.RunAsync);
runner.Add("Vertiefte portable Cross-Platform-Regression", PortableRegressionTests.RunAsync);
runner.Add("Größen, Grenzen und Last", StressTests.RunAsync);
return await runner.RunAsync(args.Length == 0 ? null : string.Join(' ', args));
