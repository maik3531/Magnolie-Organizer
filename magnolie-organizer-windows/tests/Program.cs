using MagnolieOrganizer.Windows.Tests;

if (args.FirstOrDefault() == "--dav-live") return await NextcloudDavLiveTests.RunAsync();
if (args.FirstOrDefault() == "--thunderbird-live") return await NextcloudDavLiveTests.RunAsync(thunderbird: true);
if (args.FirstOrDefault() == "--thunderbird-readonly") return await NextcloudDavLiveTests.ReadOnlyAsync();
if (args.FirstOrDefault() == "--managed-accounts-readonly") return await NextcloudDavLiveTests.ReadOnlyAsync(managed: true);
if (args.FirstOrDefault() == "--contact-identity-audit" && args.Length == 2) return await WindowsContactGraphTests.AuditIdentityAsync(args[1]);
if (args.FirstOrDefault() == "--contact-cleanup-fixture")
{
    using var fixture = System.Text.Json.JsonDocument.Parse(await Console.In.ReadToEndAsync());
    Console.WriteLine(MagnolieOrganizer.Windows.ContactCleanupPlan.Create(fixture.RootElement).ToJsonString());
    return 0;
}
if (args.FirstOrDefault() == "--managed-account-host" && args.Length == 4)
    return await ManagedInternetAccountsTests.ProbeAsync(args[1], args[2], args[3]);
if (args.FirstOrDefault() == "--managed-account-lifecycle" && args.Length == 4)
    return await ManagedInternetAccountsTests.ProbeAsync(args[1], args[2], args[3], lifecycle: true);

if (args.FirstOrDefault() == "--scoped-call-host") return await OutgoingDialTests.RunAsync(args.ElementAtOrDefault(1), args.ElementAtOrDefault(2));

if (args.FirstOrDefault() == "--personal-custom-host") return await PersonalCustomTransportTests.HostAsync();
if (args.FirstOrDefault() == "--personal-note-mode-host") return await PersonalNoteModeTransportHost.RunAsync();
if (args.FirstOrDefault() == "--time-sync-host") return await TimeSyncTransportHost.RunAsync();
if (args.FirstOrDefault() == "--phone-contact-read-host") return await PhoneContactReadTests.HostAsync();
if (args.FirstOrDefault() == "--waste-import-fixture")
{
    var fixture = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(
        TestSource.Root("contracts/waste-calendar-v1.json"), "contracts", "waste-calendar-v1.json")))!;
    Console.WriteLine(MagnolieOrganizer.Windows.ExchangeCodec.ParseWasteImport(
        System.Text.Encoding.UTF8.GetBytes(fixture["ics"]!.GetValue<string>()), "waste.ics").ToJsonString());
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
runner.Add("Shared synchronization settings / one choice / peer scope / convergence", SharedSyncSettingsTests.RunAsync);
runner.Add("Baum synchronization snapshot continuity", BaumSyncSnapshotTests.RunAsync);
runner.Add("Background lifecycle regressions", BackgroundLifecycleTests.RunAsync);
runner.Add("Native sync safety / baselines / mailbox / recovery", NativeSyncSafetyTests.RunAsync);
runner.Add("AtomicStore / Dateisicherheit", AtomicStoreTests.RunAsync);
runner.Add("Wiederherstellungsjournal / Manifest / Tamper / Retention / Scheduler", RecoveryJournalTests.RunAsync);
runner.Add("Cloud-Ordner-Sicherung / Policy / Retention / DPAPI", CloudBackupTests.RunAsync);
runner.Add("Loganzeige / Contributor-Marker", LogPresentationTests.RunAsync);
runner.Add("Lokale Absturzberichte / Format / Rotation / Parallelität", CrashReportTests.RunAsync);
runner.Add("Encryption / Python-Goldens / Manipulation", ContractGroupTests.EncryptionAsync);
runner.Add(".magnolie Gesamtarchiv / Cross-Platform / Anhänge / Fehler", ContractGroupTests.ArchiveAsync);
runner.Add("Notizanhänge / Data-URL / Dateinamen", AttachmentFileTests.RunAsync);
runner.Add("ICS / VCF / LDIF / Claws / Lotus / Thunderbird", ContractGroupTests.ExchangeAsync);
runner.Add("Thunderbird local.sqlite Schema 23", ThunderbirdSchema23Tests.RunAsync);
runner.Add("ODS Paket / XML / Styles / Geometrie / Chart", ContractGroupTests.OdsAsync);
runner.Add("Time sync / v7 consent and strict records", TimeSyncContractTests.RunAsync);
runner.Add("Time sync / encrypted staging and durable receipts", TimeSyncStoreTests.RunAsync);
        runner.Add("Time sheet / formulas and regional layout", TimeSheetExportTests.RunAsync);
        runner.Add("Holiday scope / country and subdivision metadata", OpenHolidayDataTests.RunAsync);
runner.Add("ODT Brief / MIME / Paket / Dateiendung", ContractGroupTests.OdtAsync);
runner.Add("Windows Contacts / Graph / OAuth / Token", WindowsContactGraphTests.RunAsync);
runner.Add("Reminder / Serien", ContractGroupTests.RemindersAsync);
runner.Add("Cycle calendar / explicit markers and optional forecasts", CycleCalendarTests.RunAsync);
runner.Add("Reminder / Neustart / Kennwort / DST", ReminderPersistenceTests.RunAsync);
runner.Add("Anniversary reminder / text / independent dismissal", AnniversaryReminderTests.RunAsync);
runner.Add("Tray-Persistenz / Autostart", ContractGroupTests.TrayAsync);
runner.Add("Wetterstandort / LibreOffice / Datenschutz", WeatherLocationTests.RunAsync);
runner.Add("Magnolienbaum Crypto / Pairing / FS1 / Replay / Queues / Netzwerk", ContractGroupTests.TreeAsync);
runner.Add("Magnolienbaum Nextcloud / WebDAV / Authentisierung", NextcloudMailboxTests.RunAsync);
runner.Add("Nextcloud CalDAV / CardDAV / Discovery / ETag / Sicherheit", NextcloudDavTests.RunAsync);
runner.Add("Thunderbird bridge / framing / provider identity", ThunderbirdBridgeTests.RunAsync);
runner.Add("Managed internet accounts / isolated profiles", ManagedInternetAccountsTests.RunAsync);
runner.Add("Recovery comparison / unchanged photo allocations", RecoveryComparisonAllocationTests.RunAsync);
runner.Add("Magnolienbaum discovery / allowed UDP port / active listener", MagnolienbaumDiscoveryTests.RunAsync);
runner.Add("Magnolienbaum Kontakte / Fotos / manuelle Löschvorschläge", ContractGroupTests.TreeContactsAsync);
runner.Add("Telefonverbindung / Crypto / Pairingcode / Rahmen / Verträge", TelefonProtocolTests.RunAsync);
runner.Add("Notes contacts / read-only / bounded pages / source binding", PhoneContactReadTests.RunAsync);
runner.Add("Telefon WLAN invitations / bounded discovery", TelefonInvitationTests.RunAsync);
runner.Add("Telefon Bluetooth first pairing / target binding", TelefonBluetoothSetupTests.RunAsync);
runner.Add("Telefon setup startup lifecycle / Finish / Skip / rollback", PhoneStartupLifecycleTests.RunAsync);
runner.Add("Bluetooth-Funkschalter / Gesprächsdauer / Zustandsrückgabe", BluetoothRadioTests.RunAsync);
runner.Add("KDE Connect / Codec / P-256-Ablage / Pinning / Integration", KdeConnectTests.RunAsync);
runner.Add("KDE contact import / projection / source binding", KdeContactImportTests.RunAsync);
runner.Add("KDE digitizer / delta state / pressure / reset", KdeDigitizerTests.RunAsync);
runner.Add("WebView2 / Handbuch-Start / Navigationssicherheit", WebViewStartupSourceTests.RunAsync);
runner.Add("WebView2 / geschützte Assets / URI / Header", ProtectedAssetPolicyTests.RunAsync);
runner.Add("Shell-Öffnen / URI-Positivliste / lokale Pfade", ShellLauncherTests.RunAsync);
runner.Add("Windows-Update / Manifest / Download / Installation", WindowsUpdateTests.RunAsync);
runner.Add("Release-Audit / Windows-Manifest / Installer / Prüfsummen", WindowsReleaseAuditTests.RunAsync);
runner.Add("F11-Vollbild / WebView2 / Persistenz / Tray", FullscreenSourceTests.RunAsync);
runner.Add("Native Lokalisierung / 20 Sprachen / Fallback", NativeLocalizationTests.RunAsync);
runner.Add("Lokalisierte Fehlergrenzen / Sync / Sicherung / Gesamtarchiv", LocalizationBoundaryTests.RunAsync);
runner.Add("Regionale Einstellungen / Grenzen / frühe Persistenz", RegionalSettingsTests.RunAsync);
runner.Add("Telefonnummern / Herkunft / gemeinsame Vektoren", PhoneRegionInfoTests.RunAsync);
runner.Add("Ersteinrichtung / Zustand / Atomik / Startreihenfolge", FirstRunSetupTests.RunAsync);
runner.Add("Vertiefte portable Cross-Platform-Regression", PortableRegressionTests.RunAsync);
runner.Add("Größen, Grenzen und Last", StressTests.RunAsync);
return await runner.RunAsync(args.Length == 0 ? null : string.Join(' ', args));
