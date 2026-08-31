using System.Net;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Diagnostics;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher : IDisposable
{
    private readonly MainForm form;
    private readonly WindowsPaths paths;
    private readonly AtomicStore store = new();
    private EncryptionService encryption = new();
    private readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(15) };
    private string currentPlainText = "{}";
    private string currentEnvelope = "";
    private bool currentPlainTextAvailable;
    private int failedUnlocks;
    private long unlockBlockedUntil;
    private readonly ReminderScheduler reminders;
    private readonly SemaphoreSlim bridgeCommands = new(1, 1);
    private readonly MagnolienbaumCoordinator baum;
    private readonly TelefonCoordinator telefon;
    private readonly KdeConnectSms kdeConnectSms;
    private string pendingTelefonPairingId = "";
    private string pendingKdePairingId = "";
    private readonly RecoveryJournal recovery;
    private readonly System.Threading.Timer recoveryTimer;
    private readonly byte[]? contributorHash = ReadContributorHash();
    private readonly WindowsUpdateService updates;
    private readonly CloudBackupService cloudBackups;
    private string firewallHint = "";
    private bool disposed;

    internal BridgeDispatcher(MainForm form, WindowsPaths paths)
    {
        this.form = form;
        this.paths = paths;
        kdeConnectSms = new KdeConnectSms(paths);
        reminders = new ReminderScheduler(paths.ReminderState, notice =>
            form.ShowReminder(notice.Title, notice.Body, notice.Kind, notice.Style));
        LoadPersistentReminders();
        baum = new MagnolienbaumCoordinator(paths, form.SendAsync);
        telefon = new TelefonCoordinator(paths, HandleTelefonEventAsync, KdeStatusForWebAsync,
            new WindowsBluetoothRadio());
        kdeConnectSms.StatusChanged += HandleKdeStatusChanged;
        kdeConnectSms.SmsReceived += HandleKdeSmsReceived;
        kdeConnectSms.PairingChanged += HandleKdePairingChanged;
        form.SetTelefonCoordinator(telefon);
        recovery = new RecoveryJournal(paths.RecoveryJournal, paths.RecoverySettings, store);
        recoveryTimer = new System.Threading.Timer(_ => _ = RunPeriodicSnapshotAsync(), null,
            TimeSpan.FromMinutes(1), TimeSpan.FromMinutes(15));
        http.DefaultRequestHeaders.UserAgent.ParseAdd($"Magnolie-Organizer-Windows/{AppVersion}");
        updates = new WindowsUpdateService(paths.Root);
        cloudBackups = new CloudBackupService(paths.CloudBackupPassword);
    }

    internal async Task HandleAsync(string rawMessage)
    {
        await bridgeCommands.WaitAsync();
        try { await HandleCoreAsync(rawMessage); }
        finally { bridgeCommands.Release(); }
    }

    private async Task HandleCoreAsync(string rawMessage)
    {
        JsonDocument document;
        try { document = BridgeDispatcherContract.Parse(rawMessage); }
        catch (InvalidDataException) { return; }
        using (document)
        {
            var message = document.RootElement;
            if (message.ValueKind != JsonValueKind.Object || !message.TryGetProperty("cmd", out var commandNode))
                return;
            var command = commandNode.GetString() ?? "";
            try
            {
                switch (command)
                {
                    case "bereit": await InitializeAsync(); break;
                    case "entsperren": await UnlockAsync(Text(message, "kennwort")); break;
                    case "kennwort_setzen": await SetPasswordAsync(message); break;
                    case "kennwort_entfernen": await RemovePasswordAsync(message); break;
                    case "speichern": await SaveAsync(message); break;
                    case "contributor_pruefen": await CheckContributorAsync(Text(message, "key")); break;
                    case "beenden": form.RequestClose(); break;
                    case "beenden_bereit": form.CloseAfterSave(); break;
                    case "beenden_abgebrochen": form.CancelClose(); break;
                    case "ablage_kopieren": SetClipboard(Text(message, "text")); break;
                    case "ablage_holen": await GetClipboardAsync(); break;
                    case "sicherung": await BackupAsync(message); break;
                    case "cloud_sicherung_status": await SendCloudBackupStatusAsync(); break;
                    case "cloud_sicherung_kennwort": await StoreCloudBackupPasswordAsync(Text(message, "kennwort")); break;
                    case "cloud_sicherung_test": await RunCloudBackupTestAsync(); break;
                    case "sicherung_waehlen": await SelectBackupAsync(); break;
                    case "sicherung_wiederherstellen": await RestoreBackupAsync(message); break;
                    case "journal_liste": await SendRecoveryStatusAsync(); break;
                    case "journal_erzeugen":
                    case "journal_manuell": await CreateManualSnapshotAsync(); break;
                    case "journal_vorschau": await PreviewSnapshotAsync(SnapshotId(message)); break;
                    case "journal_intervall": recovery.SetInterval(Text(message, "intervall")); await SendRecoveryStatusAsync(); break;
                    case "journal_anzahl": recovery.SetMaximum(Integer(message, "maximum")); await SendRecoveryStatusAsync(); break;
                    case "journal_loeschen": recovery.Delete(SnapshotId(message)); await form.SendAsync("App.journalErgebnis", new { ok = true, deleted = true, fehler = "" }); await SendRecoveryStatusAsync(); break;
                    case "journal_wiederherstellen": await RestoreSnapshotAsync(SnapshotId(message)); break;
                    case "mutations_snapshot": await CreateMutationSnapshotAsync(message); break;
                    case "gesamtarchiv_waehlen": await SelectGesamtarchivAsync(); break;
                    case "gesamtarchiv_pruefen": await PreviewGesamtarchivAsync(Text(message, "pfad"), Text(message, "kennwort")); break;
                    case "gesamtarchiv_importieren": await ImportGesamtarchivAsync(message); break;
                    case "gesamtarchiv_exportieren": await ExportGesamtarchivAsync(Text(message, "kennwort")); break;
                    case "ordner_waehlen": await SelectFolderAsync(); break;
                    case "drucken": form.ShowPrintDialog(Text(message, "html")); break;
                    case "notiz_anhang_datei": await HandleAttachmentFileAsync(message); break;
                    case "update_oeffnen": await OpenValidatedResultAsync("App.updateGeoeffnet", Text(message, "url"), IsAllowedWindowsUpdateUrl); break;
                    case "handbuch_herunterladen": await DownloadManualAsync(message); break;
                    case "handbuch_oeffnen": await OpenManualAsync(); break;
                    case "protokoll_zeigen": await OpenLogsAsync(); break;
                    case "medikament_suchen": OpenMedicine(Text(message, "name")); break;
                    case "mail": await OpenAddressResultAsync(MailUri(message)); break;
                    case "karte": await OpenAddressResultAsync(MapUri(message)); break;
                    case "sozial": await OpenAddressResultAsync(SocialUri(message)); break;
                    case "update_pruefen": await CheckUpdateAsync(); break;
                    case "update_herunterladen": await DownloadUpdateAsync(); break;
                    case "update_installieren": await PrepareUpdateInstallationAsync(); break;
                    case "wetter": await FetchWeatherAsync(message); break;
                    case "feiertage": await FetchHolidaysAsync(message); break;
                    case "regional_einstellungen": await SaveRegionalSettingsAsync(message); break;
                    case "import": await ImportAsync(message); break;
                    case "import_lokal": await ImportLocalAsync(message.TryGetProperty("bereich", out var bereich) &&
                        bereich.ValueKind == JsonValueKind.String && bereich.GetString() == "kontakte"); break;
                    case "export": await ExportAsync(message); break;
                    case "brief": await CreateLetterAsync(message); break;
                    case "adressen_ods": await CreateSpreadsheetAsync(message, "Adressen", "Magnolie-Adressen.ods"); break;
                    case "planer_ods": await CreateSpreadsheetAsync(message, "Planer", "Magnolie-Planer.ods"); break;
                    case "gesundheit_ods": await CreateHealthSpreadsheetAsync(message); break;
                    case "eds_status": await ContactSourcesAsync(); break;
                    case "sync": await SynchronizeContactsAsync(message); break;
                    case "sync_commit": CommitSynchronization(Text(message, "transactionId")); break;
                    case "graph_client_id_speichern": await SaveGraphConfigurationAsync(message); break;
                    case "graph_anmelden": await SignInGraphAsync(); break;
                    case "graph_abmelden": await SignOutGraphAsync(); break;
                    case "lo_benutzer":
                        await form.SendAsync("App.loBenutzer", await Task.Run(() => LibreOfficeUserData.Read()));
                        break;
                    case "tray_einstellungen":
                        if (message.TryGetProperty("einstellungen", out var tray)) await form.ApplyTraySettingsAsync(tray);
                        break;
                    case "tray_zaehler": form.UpdateTrayCounter(Integer(message, "anzahl")); break;
                    case "rechtschreibung": break;
                    case "vorschlaege": await SpellSuggestionsAsync(message); break;
                    case "wort_merken": await RememberWordAsync(message); break;
                    case "baum_stand": await baum.ReportStatusAsync(); break;
                    case "baum_ein":
                        if (Boolean(message, "an")) await EnsureFirewallAsync();
                        await baum.SwitchAsync(Boolean(message, "an"), Text(message, "name"));
                        break;
                    case "baum_suchen": await baum.SearchAsync(); break;
                    case "baum_paaren": await baum.PairV1Async(Text(message, "adresse"), Integer(message, "port"), Text(message, "fingerabdruck")); break;
                    case "baum_bestaetigen": await baum.ConfirmAsync(Text(message, "kennung"), Boolean(message, "ja")); break;
                    case "baum_entfernen": await baum.RemoveAsync(Text(message, "kennung")); break;
                    case "baum_partner_einstellungen": await baum.SetPartnerAsync(Text(message, "kennung"), Boolean(message, "vertraut"), Boolean(message, "kontakte"), Boolean(message, "kontaktLoeschen"), Text(message, "fernAdresse"), Port(message, "fernPort")); break;
                    case "baum_delegieren": await BaumSendAsync(message, "aufgabe", "aufgabe"); break;
                    case "baum_teilen": await BaumSendAsync(message, Text(message, "art"), "inhalt"); break;
                    case "baum_rueckmeldung": await BaumSendAsync(message, "stand", "stand"); break;
                    case "baum_eingang_geleert": BaumClearInbox(message); break;
                    case "baum_paarungsdatei_erzeugen": await CreateBaumPairingFileAsync(message); break;
                    case "baum_paarungsdatei_importieren": await ImportBaumPairingFileAsync(); break;
                    case "baum_internet_adresse": await BaumInternetAddressAsync(); break;
                    case "baum_briefkasten_status": await baum.ReportMailboxStatusAsync(); break;
                    case "baum_briefkasten_speichern": await baum.SaveMailboxAsync(Boolean(message, "davAktiv"), Boolean(message, "briefkastenAktiv"),
                        Text(message, "url"), Text(message, "benutzer"), Text(message, "anwendungskennwort"),
                        Boolean(message, "kennwortLoeschen")); break;
                    case "baum_briefkasten_pruefen": await baum.TestMailboxAsync(); break;
                    case "telefon_stand":
                    case "telefon_verbindung_stand": await telefon.ReportStatusAsync(); break;
                    case "telefon_ein":
                    case "telefon_verbindung_ein":
                        if (Boolean(message, "an")) await EnsureFirewallAsync();
                        await telefon.SwitchAsync(Boolean(message, "an"));
                        break;
                    case "telefon_pairing_oeffnen":
                    case "telefon_verbinden":
                        await EnsureFirewallAsync();
                        await telefon.StartPairingAsync();
                        break;
                    case "telefon_pairing_abbrechen": CancelTelefonPairing(); break;
                    case "telefon_pairing_bestaetigen":
                    case "telefon_paarung_bestaetigen": ConfirmTelefonPairing(message); break;
                    case "telefon_entfernen": await RemoveTelefonAsync(Text(message, "kennung")); break;
                    case "telefon_status_anfordern": await telefon.RequestDeviceStatusAsync(Text(message, "kennung")); break;
                    case "telefon_oeffnen": await OpenDeviceAsync(Text(message, "kennung")); break;
                    case "telefon_freigabe": await telefon.SetGrantAsync(Text(message, "kennung"), Text(message, "name"), Boolean(message, "an")); break;
                    case "telefon_freigaben": await telefon.SetLocalGrantsAsync(Boolean(message, "smsEmpfangen"), Boolean(message, "benachrichtigungen")); break;
                    case "telefon_waehlen": await DialTelefonAsync(message); break;
                    case "telefon_annehmen": await AnswerTelefonAsync(message); break;
                    case "telefon_auflegen": await EndTelefonCallAsync(message); break;
                    case "telefon_bluetooth_schalten": await SetTelefonBluetoothAsync(message); break;
                    case "telefon_sms_benachrichtigen": form.ShowTelefonMessage(Text(message, "name"), Text(message, "text"),
                        new JsonObject { ["nummer"] = Text(message, "nummer"), ["device_id"] = Text(message, "kennung") }); break;
                    case "telefon_meldung_anzeigen": form.ShowTelefonNotification(Text(message, "app"),
                        string.Join(": ", new[] { Text(message, "titel"), Text(message, "text") }.Where(value => value.Length > 0))); break;
                    case "telefon_anruf_anzeigen": form.ShowIncomingCall(message); break;
                    case "telefon_anruf_lautstaerke_wiederherstellen": break;
                    case "personal_sync_einstellungen": await telefon.SetPersonalSyncAsync(Text(message, "kennung"), Boolean(message, "eigen"), Boolean(message, "autoWlan")); break;
                    case "personal_sync_senden": await SendPersonalSyncAsync(message); break;
                    case "personal_sync_lauf_senden": await SendPersonalSyncRunAsync(message); break;
                    case "personal_sync_attachment_index": await IndexPersonalSyncAttachmentsAsync(message); break;
                    case "telefon_personal_sync_commit": await CommitPersonalSyncAsync(message); break;
                    case "kde_sms_senden": await SendKdeSmsAsync(message); break;
                    case "kde_pairing_start":
                    case "kde_pairing_complete":
                    case "kde_paaren": await EnsureFirewallAsync(); await StartKdePairingAsync(message); break;
                    case "kde_pairing_confirm": await ConfirmKdePairingAsync(pendingKdePairingId, Boolean(message, "ja")); break;
                    case "kde_paarung_bestaetigen": await ConfirmKdePairingAsync(Text(message, "kennung"), Boolean(message, "ja")); break;
                    case "kde_reconnect": await telefon.ReportStatusAsync(); break;
                    case "kde_entfernen": kdeConnectSms.Remove(Text(message, "kennung")); break;
                    case "erinnerung_zeigen":
                        form.ShowReminder(Text(message, "kopf"), Text(message, "rumpf"), Text(message, "art"), Text(message, "stil"));
                        break;
                    case "erinnerung_einrichten": await ConfigureRemindersAsync(message); break;
                    default: await ReportUnsupportedAsync(command); break;
                }
            }
            catch (Exception error)
            {
                await ReportCommandErrorAsync(command, message, error.Message);
            }
        }
    }

    internal TelefonPeer[] ConfirmedDevicePartners() => telefon.Enabled ? telefon.Peers : [];

    private async Task RemoveTelefonAsync(string id)
    {
        if (pendingTelefonPairingId == id) pendingTelefonPairingId = "";
        ClearPersonalSyncRuntime(id);
        await telefon.RemoveAsync(id);
    }

    private async Task SendKdeSmsAsync(JsonElement message)
    {
        var clientRef = Text(message, "clientRef");
        try
        {
            var result = await kdeConnectSms.SendWithResultAsync(Text(message, "nummer"), Text(message, "text"), Text(message, "land"));
            await form.SendAsync("App.kdeSmsStatus", new { ok = result.Ok, state = result.State,
                device_id = result.DeviceId, client_ref = clientRef, error = result.Error ?? "" });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.kdeSmsStatus", new { ok = false, state = "failed", client_ref = clientRef, error = error.Message });
        }
    }

    private async Task StartKdePairingAsync(JsonElement message)
    {
        if (Boolean(message, "erneuern"))
        {
            var id = Text(message, "kennung");
            if (id.Length == 0) throw new InvalidOperationException(T("The KDE Connect device to renew is missing."));
            kdeConnectSms.Remove(id);
        }
        var pairing = await kdeConnectSms.StartPairingAsync();
        pendingKdePairingId = pairing.DeviceId;
    }

    private async Task ConfirmKdePairingAsync(string deviceId, bool accept)
    {
        if (string.IsNullOrWhiteSpace(deviceId)) throw new InvalidOperationException(T("No KDE Connect pairing is awaiting confirmation."));
        await kdeConnectSms.ConfirmPairingAsync(deviceId, accept);
    }

    internal async Task OpenDeviceAsync(string id)
    {
        var partner = telefon.Peers.FirstOrDefault(item => item.Id == id);
        if (partner is null) return;
        var notifications = telefon.RecentNotifications(id);
        foreach (var notification in notifications.OfType<JsonObject>()) ResolveTelefonContact(notification, false);
        await form.SendAsync("App.geraetOeffnen", new
        {
            kennung = partner.Id,
            name = partner.Name,
            status = telefon.CachedDeviceStatus(id),
            grants = telefon.LocalGrants(),
            notifications
        });
        await telefon.RequestDeviceStatusAsync(id);
    }

    private async Task HandleTelefonEventAsync(string function, object payload)
    {
        var message = payload as JsonObject ?? JsonSerializer.SerializeToNode(payload, JsonOptions.Default) as JsonObject;
        if (function == "App.telefonVerbindungStand" && message is not null)
        {
            await form.SendAsync("App.telefonStand", await BuildTelefonStatusAsync(message));
            return;
        }
        if (function == "App.telefonPaarung" && message is not null)
        {
            await HandleTelefonPairingEventAsync(message);
            return;
        }
        if (function == "App.telefonStatus" && message is not null)
        {
            await form.SendAsync("App.geraetStatus", new { kennung = message["kennung"]?.GetValue<string>() ?? "", status = message });
            return;
        }
        if (function == "App.telefonPersonalSync" && message is not null)
        {
            await HandlePersonalSyncEventAsync(message);
            return;
        }
        if (function == "App.telefonPersonalSyncEinstellungen")
        {
            await telefon.ReportStatusAsync();
            return;
        }
        if (function == "App.telefonBenachrichtigung" && message is not null)
        {
            function = "App.telefonMeldung";
        }
        if (function == "App.telefonWaehlstatus") function = "App.telefonWaehlStatus";
        if (function == "App.telefonAnnehmstatus") function = "App.telefonAnnehmStatus";
        if (function == "App.telefonAuflegestatus") function = "App.telefonAuflegeStatus";
        if (function == "App.telefonEingehenderAnruf" && message is not null)
        {
            form.TrackIncomingCall(message);
        }
        await form.SendAsync(function, message ?? payload);
    }

    private void ResolveTelefonContact(JsonObject message, bool sms)
    {
        if (!currentPlainTextAvailable) return;
        try
        {
            var root = JsonNode.Parse(currentPlainText) as JsonObject; var contacts = root?["kontakte"] as JsonArray;
            var source = message["source"]?.GetValue<string>() ?? "";
            var sought = sms ? NormalizePhone(message["from"]?.GetValue<string>() ?? "") : (message["sender"]?.GetValue<string>() ?? "").Trim().ToLowerInvariant();
            var matches = contacts?.OfType<JsonObject>().Where(contact => sms
                ? ContactPhones(contact).Any(phone => NormalizePhone(phone) == sought)
                : (contact["sozialeMedien"] as JsonArray)?.OfType<JsonObject>().Any(item =>
                    (item["dienst"]?.GetValue<string>() ?? "").Equals(source, StringComparison.OrdinalIgnoreCase) &&
                    (item["wert"]?.GetValue<string>() ?? "").Trim().Equals(sought, StringComparison.OrdinalIgnoreCase)) == true).Take(2).ToArray() ?? [];
            if (matches.Length != 1) return;
            var contact = matches[0]; var name = string.Join(" ", new[] { contact["vorname"]?.GetValue<string>(), contact["nachname"]?.GetValue<string>() }.Where(value => !string.IsNullOrWhiteSpace(value)));
            if (name.Length == 0) name = contact["firma"]?.GetValue<string>() ?? "";
            message["kontaktName"] = name; message["kontaktId"] = contact["id"]?.GetValue<string>() ?? "";
            if ((contact["foto"]?.GetValue<string>() ?? "").StartsWith("data:image/", StringComparison.OrdinalIgnoreCase)) message["kontaktFoto"] = contact["foto"]!.DeepClone();
        }
        catch (Exception) { }
    }

    private static IEnumerable<string> ContactPhones(JsonObject contact)
    {
        if (contact["telefone"] is JsonArray phones) foreach (var phone in phones.OfType<JsonObject>()) yield return phone["wert"]?.GetValue<string>() ?? "";
        yield return contact["telefon"]?.GetValue<string>() ?? ""; yield return contact["mobil"]?.GetValue<string>() ?? "";
    }
    private static string NormalizePhone(string value) => new(value.Where(character => char.IsAsciiDigit(character) || character == '+').ToArray());

    private async Task InitializeAsync()
    {
        var text = store.ReadRecoverableJson(paths.Data);
        recovery.ReleaseAbandonedRestoreLeases();
        if (EncryptionService.IsEncrypted(text))
        {
            currentEnvelope = text!;
            await form.SendAsync("App.init", new
            {
                gesperrt = true, wartet = 0, datenPfad = paths.Data,
                trayVerfuegbar = true, handbuchInstalliert = ManualInstalled(),
                handbuchVersion = ManualVersion(),
                teamsVerfuegbar = NativeMethods.HasUriScheme("msteams"),
                trayEinstellungen = form.CurrentTraySettings,
                contributorAktiv = contributorHash is not null,
                regional = RegionalSettings.Read(paths.RegionalSettings)
            });
            return;
        }
        currentPlainText = text ?? "{}";
        currentPlainTextAvailable = true;
        UpdateReminderRuntime(currentPlainText);
        await baum.ResumeAsync();
        await telefon.ResumeAsync();
        await InitializeWithPlainTextAsync(currentPlainText, text is null);
        await telefon.ReplayPersonalSyncAsync();
    }

    private async Task InitializeWithPlainTextAsync(string text, bool isNew = false)
    {
        JsonNode data;
        try { data = JsonNode.Parse(text) ?? new JsonObject(); }
        catch (JsonException) { data = new JsonObject(); }
        await form.SendAsync("App.init", new
        {
            gesperrt = false,
            kennwort = encryption.Session is not null,
            daten = data,
            neu = isNew,
            echterErststart = isNew,
            migriert = false,
            datenPfad = paths.Data,
            wayland = false,
            trayVerfuegbar = true,
            teamsVerfuegbar = NativeMethods.HasUriScheme("msteams"),
            trayEinstellungen = form.CurrentTraySettings,
            handbuchInstalliert = ManualInstalled(),
            handbuchVersion = ManualVersion(),
            contributorAktiv = contributorHash is not null,
            regional = RegionalSettings.Read(paths.RegionalSettings)
        });
        _ = RunPeriodicSnapshotAsync();
    }

    private static string ManualPath => Path.Combine(AppContext.BaseDirectory, "handbuch", "index.html");

    private async Task SaveRegionalSettingsAsync(JsonElement message)
    {
        try
        {
            if (!message.TryGetProperty("regional", out var regional)) throw new ArgumentException(T("The regional settings are invalid."));
            var clean = RegionalSettings.Write(paths.RegionalSettings, regional);
            await form.SendAsync("App.regionalErgebnis", new { ok = true, regional = clean });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.regionalErgebnis", new { ok = false, fehler = error.Message });
        }
    }

    private static bool ManualInstalled() => File.Exists(ManualPath);

    internal static string ManualVersion(string? baseDirectory = null)
    {
        var path = Path.Combine(baseDirectory ?? AppContext.BaseDirectory, "handbuch", "version.json");
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var version = PropertyText(document.RootElement, "version").Trim();
            return VersionPattern().IsMatch(version) ? version : "";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException) { return ""; }
    }

    private async Task OpenManualAsync()
    {
        var installed = ManualInstalled();
        var opened = installed && await form.OpenHandbookAsync(ManualPath);
        await form.SendAsync("App.handbuchGeoeffnet", new
        {
            ok = opened,
            fehler = opened ? "" : installed
                ? T("The manual could not be opened.")
                : T("The Magnolie manual is not installed.")
        });
    }

    private async Task HandleAttachmentFileAsync(JsonElement message)
    {
        var action = Text(message, "aktion");
        if (action is not ("oeffnen" or "speichern"))
        {
            await form.SendAsync("App.notizAnhangDateiErgebnis", new { aktion = action, ok = false, abgebrochen = false });
            return;
        }
        try
        {
            var attachment = AttachmentFile.Parse(Text(message, "daten"), Text(message, "name"));
            if (action == "speichern")
            {
                using var dialog = new SaveFileDialog
                {
                    Title = T("Save") + " - " + T("Attachments"),
                    FileName = attachment.FileName,
                    Filter = AttachmentFilter(attachment.MimeType, attachment.Extension),
                    DefaultExt = attachment.Extension[1..],
                    AddExtension = true,
                    OverwritePrompt = true
                };
                if (dialog.ShowDialog(form) != DialogResult.OK)
                {
                    await form.SendAsync("App.notizAnhangDateiErgebnis", new { aktion = action, ok = false, abgebrochen = true });
                    return;
                }
                await File.WriteAllBytesAsync(dialog.FileName, attachment.Bytes);
            }
            else
            {
                var directory = Path.Combine(Path.GetTempPath(), "Magnolie Organizer", "Anhaenge");
                Directory.CreateDirectory(directory);
                CleanOldAttachments(directory);
                var path = Path.Combine(directory, Guid.NewGuid().ToString("N") + attachment.Extension);
                await File.WriteAllBytesAsync(path, attachment.Bytes);
                if (!ShellLauncher.OpenLocalFile(path, directory))
                {
                    try { File.Delete(path); } catch (Exception) { }
                    throw new IOException(T("No application is registered for the attachment."));
                }
            }
            await form.SendAsync("App.notizAnhangDateiErgebnis", new { aktion = action, ok = true, abgebrochen = false });
        }
        catch (Exception error) when (error is InvalidDataException or IOException or UnauthorizedAccessException or ArgumentException)
        {
            await form.SendAsync("App.notizAnhangDateiErgebnis", new { aktion = action, ok = false, abgebrochen = false });
        }
    }

    private static string AttachmentFilter(string mime, string extension) => mime switch
    {
        "image/jpeg" => "JPEG (*.jpg)|*.jpg",
        "image/png" => "PNG (*.png)|*.png",
        "image/webp" => "WebP (*.webp)|*.webp",
        "image/gif" => "GIF (*.gif)|*.gif",
        _ => $"PDF (*{extension})|*{extension}"
    };

    private static void CleanOldAttachments(string directory)
    {
        var cutoff = DateTime.UtcNow.AddDays(-7);
        try
        {
            foreach (var file in Directory.EnumerateFiles(directory))
            {
                try { if (File.GetLastWriteTimeUtc(file) < cutoff) File.Delete(file); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
    }

    internal static byte[]? ReadContributorHash()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "build-config.json");
        try
        {
            if (!File.Exists(path) || new FileInfo(path).Length > 4096) return null;
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            if (!document.RootElement.TryGetProperty("contributorHash", out var node)) return null;
            var value = node.GetString() ?? "";
            return Regex.IsMatch(value, "^[0-9a-fA-F]{64}$")
                ? Convert.FromHexString(value)
                : null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or FormatException)
        {
            return null;
        }
    }

    private async Task CheckContributorAsync(string key)
    {
        var actual = SHA256.HashData(Encoding.UTF8.GetBytes(key));
        var valid = contributorHash is not null &&
            CryptographicOperations.FixedTimeEquals(actual, contributorHash);
        await form.SendAsync("App.contributorGeprueft", new { ok = valid });
    }

    private async Task SaveAsync(JsonElement message)
    {
        var locked = false;
        var id = Integer(message, "id");
        var text = Text(message, "text");
        if (id < 1 || string.IsNullOrWhiteSpace(text))
        {
            await form.SendAsync("App.gespeichert", new { id, ok = false, fehler = T("The save request is invalid.") });
            return;
        }
        if (!string.IsNullOrEmpty(currentEnvelope) && encryption.Session is null)
        {
            await form.SendAsync("App.gespeichert", new
            {
                id, ok = false, fehler = T("Save rejected: The data is encrypted and has not been unlocked yet.")
            });
            return;
        }
        try
        {
            await MutationGate.Global.WaitAsync(); locked = true;
            using var document = JsonDocument.Parse(text);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
                throw new JsonException(T("The data is not a JSON object."));

            if (encryption.Session is not null)
            {
                var envelope = encryption.EncryptData(text);
                store.WriteRecoverableJson(paths.Data, envelope);
                currentEnvelope = envelope;
            }
            else store.WriteRecoverableJson(paths.Data, text);
            currentPlainText = text;
            currentPlainTextAvailable = true;
            RefreshReminderData(currentPlainText, encryption.Session is not null);
            UpdateReminderRuntime(currentPlainText);
            await form.SendAsync("App.gespeichert", new { id, ok = true, fehler = "" });
            await RunCloudBackupAfterSaveAsync(document.RootElement.GetRawText(), force: false);
        }
        catch (Exception error)
        {
            await form.SendAsync("App.gespeichert", new { id, ok = false, fehler = error.Message });
        }
        finally { if (locked) MutationGate.Global.Release(); }
    }

    private async Task UnlockAsync(string password)
    {
        var now = Stopwatch.GetTimestamp();
        if (now < unlockBlockedUntil)
        {
            var remaining = (int)Math.Ceiling((unlockBlockedUntil - now) / (double)Stopwatch.Frequency);
            await form.SendAsync("App.entsperrtFehler", new { fehler = T("Too many failed attempts. Wait a moment."), wartet = remaining });
            return;
        }
        try
        {
            currentPlainText = encryption.Unlock(currentEnvelope, password);
            failedUnlocks = 0; unlockBlockedUntil = 0;
            currentPlainTextAvailable = true;
            UpdateReminderRuntime(currentPlainText);
            // Alte Hüllen werden beim nächsten Speichern in die DEK-Hülle migriert.
            if (encryption.Session is null)
            {
                currentEnvelope = encryption.Enable(currentPlainText, password);
                store.WriteRecoverableJson(paths.Data, currentEnvelope);
            }
            await baum.ResumeAsync();
            await telefon.ResumeAsync();
            await InitializeWithPlainTextAsync(currentPlainText);
            await telefon.ReplayPersonalSyncAsync();
        }
        catch (CryptographicException error)
        {
            failedUnlocks++;
            var wait = 0;
            if (failedUnlocks >= 3)
            {
                failedUnlocks = 0; wait = 5 * 60;
                unlockBlockedUntil = Stopwatch.GetTimestamp() + wait * Stopwatch.Frequency;
            }
            await form.SendAsync("App.entsperrtFehler", new { fehler = error.Message, wartet = wait });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.entsperrtFehler", new { fehler = error.Message, wartet = 0 });
        }
    }

    private async Task SetPasswordAsync(JsonElement message)
    {
        var oldPassword = Text(message, "alt");
        var newPassword = Text(message, "neu");
        var candidate = string.IsNullOrEmpty(currentEnvelope) ? new EncryptionService() : encryption.CloneUnlocked();
        try
        {
            if (newPassword.Length < 4)
                throw new InvalidOperationException(T("The password must contain at least four characters."));
            var nextEnvelope = string.IsNullOrEmpty(currentEnvelope)
                ? candidate.Enable(currentPlainText, newPassword)
                : string.IsNullOrEmpty(oldPassword) ? candidate.ChangePasswordWithSession(currentEnvelope, newPassword)
                    : candidate.ChangePassword(currentEnvelope, oldPassword, newPassword);
            store.WriteRecoverableJson(paths.Data, nextEnvelope);
            var copies = RewriteProtectedCopies(message, candidate, removeProtection: false);
            encryption.Clear(); encryption = candidate; currentEnvelope = nextEnvelope;
            try { RefreshReminderData(currentPlainText, encrypted: true); }
            catch { copies.Failed++; }
            await form.SendAsync("App.kennwortStand", new
            {
                ok = true, an = true, sicherungen = copies.Changed, sicherungenFehler = copies.Failed,
                fehler = copies.Failed == 0 ? "" : T("Some existing backups could not be encrypted.")
            });
        }
        catch (Exception error)
        {
            if (!ReferenceEquals(encryption, candidate)) candidate.Clear();
            await form.SendAsync("App.kennwortStand", new { ok = false, an = true, fehler = error.Message });
        }
    }

    private async Task RemovePasswordAsync(JsonElement message)
    {
        var candidate = string.IsNullOrEmpty(currentEnvelope) ? new EncryptionService() : encryption.CloneUnlocked();
        try
        {
            var oldPassword = Text(message, "alt");
            var plainText = string.IsNullOrEmpty(currentEnvelope) ? currentPlainText : string.IsNullOrEmpty(oldPassword)
                ? candidate.DecryptDataWithSession(currentEnvelope) : candidate.Unlock(currentEnvelope, oldPassword);
            store.WriteRecoverableJson(paths.Data, plainText);
            var copies = RewriteProtectedCopies(message, candidate, removeProtection: true);
            candidate.Clear();
            encryption.Clear(); encryption = candidate; currentPlainText = plainText; currentEnvelope = "";
            try { RefreshReminderData(currentPlainText, encrypted: false); }
            catch { copies.Failed++; }
            await form.SendAsync("App.kennwortStand", new
            {
                ok = true, an = false, sicherungen = copies.Changed, sicherungenFehler = copies.Failed,
                fehler = copies.Failed == 0 ? "" : T("Some existing backups could not be decrypted.")
            });
        }
        catch (Exception error)
        {
            if (!ReferenceEquals(encryption, candidate)) candidate.Clear();
            await form.SendAsync("App.kennwortStand", new { ok = false, an = true, fehler = error.Message });
        }
    }

    private async Task BackupAsync(JsonElement message)
    {
        var locked = false;
        var requested = Text(message, "pfad");
        var directory = string.IsNullOrWhiteSpace(requested) ? paths.Backups : requested;
        try
        {
            await MutationGate.Global.WaitAsync(); locked = true;
            string target;
            if (!string.IsNullOrWhiteSpace(requested))
            {
                var password = Text(message, "kennwort");
                if (password.Length < 4) throw new InvalidOperationException(T("Backups outside the data location require a password with at least four characters."));
                var data = JsonNode.Parse(currentPlainText) as JsonObject ?? throw new InvalidDataException(T("The data is invalid."));
                var archive = GesamtarchivService.Create(data, "windows", AppVersion, password);
                Directory.CreateDirectory(directory);
                target = Path.Combine(directory,
                    $"magnolie-sicherung-{DateTime.Now:yyyyMMdd-HHmmss-fff}-{Guid.NewGuid():N}.magnolie");
                store.Write(target, archive, AtomicStore.MaxArchiveBytes);
                _ = GesamtarchivService.Read(store.Read(target, AtomicStore.MaxArchiveBytes)
                    ?? throw new IOException(T("The backup is empty.")), password);
            }
            else target = store.Backup(paths.Data, directory);
            await form.SendAsync("App.sicherungFertig", new { ok = true, pfad = target, fehler = "" });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.sicherungFertig", new { ok = false, pfad = "", fehler = error.Message });
        }
        finally { if (locked) MutationGate.Global.Release(); }
    }

    private async Task SendCloudBackupStatusAsync(string status = "") =>
        await form.SendAsync("App.cloudSicherungStand", new
        {
            kennwortVorhanden = cloudBackups.PasswordAvailable, status
        });

    private async Task StoreCloudBackupPasswordAsync(string password)
    {
        try { cloudBackups.StorePassword(password); await SendCloudBackupStatusAsync("ready"); }
        catch { await SendCloudBackupStatusAsync("secret_unavailable"); }
    }

    private async Task RunCloudBackupTestAsync()
    {
        var locked = false;
        try
        {
            await MutationGate.Global.WaitAsync(); locked = true;
            if (!currentPlainTextAvailable) { await SendCloudBackupStatusAsync("locked"); return; }
            await RunCloudBackupAfterSaveAsync(currentPlainText, force: true);
        }
        finally { if (locked) MutationGate.Global.Release(); }
    }

    private async Task RunCloudBackupAfterSaveAsync(string plainText, bool force)
    {
        try
        {
            var data = JsonNode.Parse(plainText) as JsonObject ?? throw new InvalidDataException();
            var settings = CloudBackupService.Settings(data);
            if (!force && !CloudBackupService.IsDue(settings.Enabled, settings.Interval,
                    settings.LastSuccess, DateTimeOffset.UtcNow)) return;
            if (string.IsNullOrWhiteSpace(settings.Folder)) { await SendCloudBackupStatusAsync("folder_missing"); return; }
            if (!cloudBackups.PasswordAvailable) { await SendCloudBackupStatusAsync("secret_unavailable"); return; }
            cloudBackups.CreateVerified(data, settings, AppVersion);
            await form.SendAsync("App.cloudSicherungStand", new
            {
                kennwortVorhanden = true, status = "success",
                letzterErfolg = DateTimeOffset.UtcNow.ToString("O")
            });
        }
        catch { await SendCloudBackupStatusAsync("failed"); }
    }

    private (int Changed, int Failed) RewriteProtectedCopies(JsonElement message, EncryptionService session,
        bool removeProtection)
    {
        var changed = 0; var failed = 0;
        var requested = message.TryGetProperty("sicherungsordner", out var folder) && folder.ValueKind == JsonValueKind.String
            ? folder.GetString() ?? "" : "";
        var directory = string.IsNullOrWhiteSpace(requested) ? paths.Backups : requested;
        try
        {
            if (Directory.Exists(directory))
            {
                var files = Directory.EnumerateFiles(directory, "magnolie-sicherung-*.json", SearchOption.TopDirectoryOnly)
                    .Take(1001).ToArray();
                if (files.Length > 1000) { failed += files.Length - 1000; files = files[..1000]; }
                foreach (var file in files)
                {
                    try
                    {
                        var text = store.Read(file, AtomicStore.MaxDataBytes) ?? throw new IOException(T("The backup is empty."));
                        var encrypted = EncryptionService.IsEncrypted(text);
                        var rewritten = removeProtection
                            ? encrypted ? session.DecryptDataWithSession(text) : text
                            : encrypted ? session.RewrapWithSession(text) : session.EncryptData(text);
                        if (rewritten != text) { store.Write(file, rewritten, AtomicStore.MaxDataBytes); changed++; }
                    }
                    catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or
                                                   JsonException or CryptographicException)
                    { failed++; }
                }
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { failed++; }
        try
        {
            var snapshots = recovery.RewritePayloads((text, encrypted) => removeProtection
                ? encrypted ? session.DecryptDataWithSession(text) : text
                : encrypted ? session.RewrapWithSession(text) : session.EncryptData(text));
            changed += snapshots.Changed; failed += snapshots.Failed;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException)
        { failed++; }
        return (changed, failed);
    }

    private async Task SelectBackupAsync()
    {
        using var dialog = new OpenFileDialog
        {
            Title = T("Restore backup"),
            Filter = T("Magnolie backup (*.json)") + "|*.json|" +
                T("Magnolie complete archive (.magnolie) …") + "|*.magnolie|" +
                T("All files") + " (*.*)|*.*",
            CheckFileExists = true,
            Multiselect = false
        };
        if (dialog.ShowDialog(form) != DialogResult.OK)
        {
            await form.SendAsync("App.sicherungAusgewaehlt", new { ok = false, abgebrochen = true });
            return;
        }
        try
        {
            if (GesamtarchivService.IsArchivePath(dialog.FileName))
            {
                await PreviewGesamtarchivAsync(dialog.FileName, "");
                return;
            }
            var text = store.Read(dialog.FileName) ?? throw new IOException(T("The backup is empty."));
            var encrypted = EncryptionService.IsEncrypted(text);
            if (!encrypted) RequireJsonObject(text);
            await form.SendAsync("App.sicherungAusgewaehlt", new
            {
                ok = true, pfad = dialog.FileName, verschluesselt = encrypted,
                brauchtKennwort = encrypted, fehler = ""
            });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.sicherungAusgewaehlt", new
            {
                ok = false, abgebrochen = false, fehler = error.Message
            });
        }
    }

    private async Task RestoreBackupAsync(JsonElement message)
    {
        var locked = false;
        SnapshotInfo? restorePoint = null;
        try
        {
            var source = Text(message, "pfad");
            if (GesamtarchivService.IsArchivePath(source))
            {
                await PreviewGesamtarchivAsync(source, Text(message, "kennwort"));
                return;
            }
            await MutationGate.Global.WaitAsync(); locked = true;
            restorePoint = CreateRestorePoint();
            var storedText = store.Read(source) ?? throw new IOException(T("The backup is empty."));
            var encrypted = EncryptionService.IsEncrypted(storedText);
            var plainText = storedText;
            var restoredEncryption = new EncryptionService();
            if (encrypted)
            {
                var password = Text(message, "kennwort");
                plainText = restoredEncryption.Unlock(storedText, password);
                if (restoredEncryption.Session is null)
                    storedText = restoredEncryption.Enable(plainText, password);
            }
            RequireJsonObject(plainText);
            var restoredData = JsonNode.Parse(plainText)!.AsObject();
            PrepareRestoredData(restoredData);
            plainText = restoredData.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            storedText = encrypted ? restoredEncryption.EncryptData(plainText) : plainText;
            if (File.Exists(paths.Data)) store.Backup(paths.Data, paths.Backups);
            store.WriteRecoverableJson(paths.Data, storedText);
            encryption.Clear();
            encryption = restoredEncryption;
            currentPlainText = plainText;
            currentPlainTextAvailable = true;
            currentEnvelope = encrypted ? storedText : "";
            var warning = await CompleteRestoreRuntimeAsync(currentPlainText, encrypted, resumeTree: true);
            await form.SendAsync("App.sicherungWiederhergestellt", new
            {
                ok = true, daten = JsonNode.Parse(plainText), kennwort = encrypted, fehler = warning
            });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.sicherungWiederhergestellt", new
            {
                ok = false, daten = (object?)null, kennwort = false, fehler = error.Message
            });
        }
        finally
        {
            try { if (restorePoint is not null) recovery.ReleaseRestoreLease(restorePoint.Id); }
            finally { if (locked) MutationGate.Global.Release(); }
        }
    }

    private static void RequireJsonObject(string text)
    {
        using var document = JsonDocument.Parse(text);
        if (document.RootElement.ValueKind != JsonValueKind.Object)
            throw new JsonException(T("The data is not a JSON object."));
    }

    private async Task SelectGesamtarchivAsync()
    {
        using var dialog = new OpenFileDialog
        {
            Title = T("Import Magnolie complete archive"),
            Filter = T("Magnolie complete archive (.magnolie) …") + "|*.magnolie",
            CheckFileExists = true, Multiselect = false
        };
        if (dialog.ShowDialog(form) != DialogResult.OK)
        {
            await form.SendAsync("App.gesamtarchivAusgewaehlt", new { ok = false, abgebrochen = true });
            return;
        }
        var text = "";
        try
        {
            text = store.Read(dialog.FileName, AtomicStore.MaxArchiveBytes)
                ?? throw new IOException(T("The complete archive is empty."));
            if (EncryptionService.IsEncrypted(text))
            {
                await form.SendAsync("App.gesamtarchivAusgewaehlt", new
                {
                    ok = true, pfad = dialog.FileName, verschluesselt = true,
                    brauchtKennwort = true, geprueft = false
                });
                return;
            }
            await SendGesamtarchivPreviewAsync(dialog.FileName, GesamtarchivService.Read(text));
        }
        catch (Exception error)
        {
            await form.SendAsync("App.gesamtarchivAusgewaehlt", new
                { ok = false, abgebrochen = false, pfad = dialog.FileName, fehler = error.Message });
        }
    }

    private async Task PreviewGesamtarchivAsync(string path, string password)
    {
        try
        {
            var text = store.Read(path, AtomicStore.MaxArchiveBytes)
                ?? throw new IOException(T("The complete archive is empty."));
            await SendGesamtarchivPreviewAsync(path, GesamtarchivService.Read(text, password));
        }
        catch (Exception error)
        {
            await form.SendAsync("App.gesamtarchivAusgewaehlt", new
                { ok = false, abgebrochen = false, pfad = path, verschluesselt = true,
                  brauchtKennwort = true, fehler = error.Message });
        }
    }

    private Task SendGesamtarchivPreviewAsync(string path, GesamtarchivInfo info) =>
        form.SendAsync("App.gesamtarchivAusgewaehlt", new
        {
            ok = true, pfad = path, verschluesselt = info.Verschluesselt,
            brauchtKennwort = false, geprueft = true, erstellt = info.Erstellt,
            plattform = info.Plattform, appversion = info.Appversion,
            anzahlen = info.Anzahlen, fotos = info.Fotos, anhaenge = info.Anhaenge
        });

    private async Task ExportGesamtarchivAsync(string password)
    {
        using var dialog = new SaveFileDialog
        {
            Title = T("Export Magnolie complete archive"), FileName = "magnolie-gesamtarchiv.magnolie",
            Filter = T("Magnolie complete archive (.magnolie) …") + "|*.magnolie", AddExtension = true, OverwritePrompt = true
        };
        if (dialog.ShowDialog(form) != DialogResult.OK)
        {
            await form.SendAsync("App.gesamtarchivExportiert", new { ok = false, abgebrochen = true });
            return;
        }
        try
        {
            var data = JsonNode.Parse(currentPlainText) as JsonObject
                ?? throw new InvalidDataException(T("The current organizer data is incomplete."));
            var version = AppVersion;
            var archive = GesamtarchivService.Create(data, "windows", version, password);
            store.Write(dialog.FileName, archive, AtomicStore.MaxArchiveBytes);
            await form.SendAsync("App.gesamtarchivExportiert", new
                { ok = true, abgebrochen = false, pfad = dialog.FileName, verschluesselt = password.Length > 0 });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.gesamtarchivExportiert", new
                { ok = false, abgebrochen = false, fehler = error.Message });
        }
    }

    private async Task ImportGesamtarchivAsync(JsonElement message)
    {
        var locked = false;
        SnapshotInfo? restorePoint = null;
        try
        {
            await MutationGate.Global.WaitAsync(); locked = true;
            restorePoint = CreateRestorePoint();
            if (Text(message, "modus") != "vollstaendig-ersetzen")
                throw new InvalidOperationException(T("Only 'Replace completely' is supported."));
            var source = Text(message, "pfad");
            var text = store.Read(source, AtomicStore.MaxArchiveBytes)
                ?? throw new IOException(T("The complete archive is empty."));
            var info = GesamtarchivService.Read(text, Text(message, "kennwort"));
            var local = JsonNode.Parse(currentPlainText) as JsonObject ?? new JsonObject();
            var imported = GesamtarchivService.PreserveDeviceSettings(info.Daten, local, info.Plattform != "windows");
            PrepareRestoredData(imported);
            var plain = imported.ToJsonString(new JsonSerializerOptions { WriteIndented = true });

            if (File.Exists(paths.Data)) store.Backup(paths.Data, paths.Backups);
            var stored = encryption.Session is not null ? encryption.EncryptData(plain) : plain;
            store.WriteRecoverableJson(paths.Data, stored);
            currentPlainText = plain;
            currentPlainTextAvailable = true;
            currentEnvelope = encryption.Session is not null ? stored : "";
            var warning = await CompleteRestoreRuntimeAsync(currentPlainText, encryption.Session is not null, resumeTree: false);
            await form.SendAsync("App.gesamtarchivImportiert", new
                { ok = true, daten = imported, kennwort = encryption.Session is not null, fehler = warning });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.gesamtarchivImportiert", new
                { ok = false, daten = (object?)null, fehler = error.Message });
        }
        finally
        {
            try { if (restorePoint is not null) recovery.ReleaseRestoreLease(restorePoint.Id); }
            finally { if (locked) MutationGate.Global.Release(); }
        }
    }

    private string AppVersion => typeof(BridgeDispatcher).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";

    private SnapshotInfo CreateSnapshot(SnapshotReason reason)
    {
        if (!currentPlainTextAvailable) throw new InvalidOperationException(T("The locked data cannot be backed up."));
        var data = JsonNode.Parse(currentPlainText) as JsonObject ?? throw new InvalidDataException(T("The data is invalid."));
        return recovery.Create(data, reason, AppVersion,
            encryption.Session is null ? null : archive => encryption.EncryptData(archive));
    }

    private SnapshotInfo CreateRestorePoint()
    {
        if (!currentPlainTextAvailable) throw new InvalidOperationException(T("The locked data cannot be backed up."));
        var data = JsonNode.Parse(currentPlainText) as JsonObject ?? throw new InvalidDataException(T("The data is invalid."));
        return recovery.CreateRestorePoint(data, AppVersion,
            encryption.Session is null ? null : archive => encryption.EncryptData(archive));
    }

    private async Task RunPeriodicSnapshotAsync()
    {
        if (disposed || !currentPlainTextAvailable || !recovery.IsDue() || !await MutationGate.Global.WaitAsync(0)) return;
        try { CreateSnapshot(SnapshotReason.Periodic); recovery.RecordPeriodicResult(true); }
        catch (Exception error) { recovery.RecordPeriodicResult(false, error.Message); }
        finally { MutationGate.Global.Release(); }
        await SendRecoveryStatusAsync();
    }

    private async Task CreateManualSnapshotAsync()
    {
        await MutationGate.Global.WaitAsync();
        try { CreateSnapshot(SnapshotReason.Manual); await form.SendAsync("App.journalErgebnis", new { ok = true, deleted = false, fehler = "" }); await SendRecoveryStatusAsync(); }
        catch (Exception error) { await form.SendAsync("App.journalErgebnis", new { ok = false, deleted = false, fehler = error.Message }); }
        finally { MutationGate.Global.Release(); }
    }

    private async Task CreateMutationSnapshotAsync(JsonElement message)
    {
        var token = Text(message, "token");
        await MutationGate.Global.WaitAsync();
        try
        {
            var reason = Text(message, "reason") switch
            {
                "pre-contact-delete" => SnapshotReason.PreContactDelete,
                "pre-contact-merge" => SnapshotReason.PreContactMerge,
                "pre-contact-import" => SnapshotReason.PreContactImport,
                "pre-sync" => SnapshotReason.PreSync,
                "pre-restore" => SnapshotReason.PreRestore,
                _ => throw new InvalidDataException(T("The recovery snapshot reason is invalid."))
            };
            CreateSnapshot(reason);
            await form.SendAsync("App.mutationsSnapshot", new { token, ok = true, fehler = "" });
        }
        catch (Exception error) { await form.SendAsync("App.mutationsSnapshot", new { token, ok = false, fehler = error.Message }); }
        finally { MutationGate.Global.Release(); }
    }

    private async Task PreviewSnapshotAsync(string id)
    {
        try
        {
            var item = recovery.Verify(id);
            await form.SendAsync("App.journalVorschau", new { ok = true, snapshot = NativeSnapshot(item), summary = item.Summary, fehler = "" });
        }
        catch (Exception error) { await form.SendAsync("App.journalVorschau", new { ok = false, fehler = error.Message }); }
    }

    private Task SendRecoveryStatusAsync()
    {
        var schedule = recovery.Schedule();
        return form.SendAsync("App.journalStand", new
        {
            intervall = schedule.Interval, letzte = schedule.Last?.ToString("O"),
            naechste = schedule.Next?.ToString("O"), status = schedule.Status, fehler = schedule.Error,
            maximum = schedule.Maximum,
            snapshots = recovery.List().Select(NativeSnapshot)
        });
    }

    private static object NativeSnapshot(SnapshotInfo item) => new
    {
        snapshotId = item.Id, createdAt = item.CreatedUtc.ToString("O"), reason = item.Reason,
        integrity = item.Integrity, summary = item.Summary, payload = new { size = item.Size },
        encrypted = item.Encrypted, pinned = item.Pinned
    };

    private static string SnapshotId(JsonElement message)
    {
        var id = Text(message, "snapshotId");
        return id.Length == 0 ? Text(message, "id") : id;
    }

    private async Task RestoreSnapshotAsync(string id)
    {
        await MutationGate.Global.WaitAsync();
        SnapshotInfo? restorePoint = null;
        try
        {
            restorePoint = CreateRestorePoint();
            var payload = recovery.ReadPayload(id);
            if (EncryptionService.IsEncrypted(payload)) payload = encryption.DecryptDataWithSession(payload);
            var restored = GesamtarchivService.Read(payload).Daten.DeepClone().AsObject();
            PrepareRestoredData(restored);
            var plain = restored.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            var stored = encryption.Session is null ? plain : encryption.EncryptData(plain);
            store.WriteRecoverableJson(paths.Data, stored);
            currentPlainText = plain; currentPlainTextAvailable = true; currentEnvelope = encryption.Session is null ? "" : stored;
            var warning = await CompleteRestoreRuntimeAsync(currentPlainText, encryption.Session is not null, resumeTree: false);
            await form.SendAsync("App.journalWiederhergestellt", new { ok = true, daten = restored, fehler = warning });
            await SendRecoveryStatusAsync();
        }
        catch (Exception error) { await form.SendAsync("App.journalWiederhergestellt", new { ok = false, daten = (object?)null, fehler = error.Message }); }
        finally
        {
            try { if (restorePoint is not null) recovery.ReleaseRestoreLease(restorePoint.Id); }
            finally { MutationGate.Global.Release(); }
        }
    }

    private static void PrepareRestoredData(JsonObject data)
    {
        RestoreSyncState.Prepare(data);
    }

    private void QuarantineTreeOutbox()
    {
        if (!File.Exists(paths.BaumOutbox)) return;
        File.Move(paths.BaumOutbox, Path.Combine(paths.Root,
            $"baum-post-quarantaene-{DateTime.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid():N}.json"), false);
    }

    private async Task<string> CompleteRestoreRuntimeAsync(string plainText, bool encrypted, bool resumeTree)
    {
        var warnings = new List<string>();
        try { RefreshReminderData(plainText, encrypted); }
        catch (Exception error) { warnings.Add(T("Reminder data:") + " " + error.Message); }
        try { UpdateReminderRuntime(plainText); }
        catch (Exception error) { warnings.Add(T("Reminder runtime:") + " " + error.Message); }
        try { QuarantineTreeOutbox(); }
        catch (Exception error) { warnings.Add(T("Magnolienbaum quarantine:") + " " + error.Message); }
        if (resumeTree)
        {
            try { await baum.ResumeAsync(); }
            catch (Exception error) { warnings.Add(T("Magnolienbaum restart:") + " " + error.Message); }
        }
        return string.Join(" ", warnings);
    }

    private async Task SelectFolderAsync()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = T("Select backup folder"),
            UseDescriptionForTitle = true,
            ShowNewFolderButton = true
        };
        if (dialog.ShowDialog(form) == DialogResult.OK)
            await form.SendAsync("App.sicherungsordnerGewaehlt", new { pfad = dialog.SelectedPath });
    }

    private async Task ConfigureRemindersAsync(JsonElement message)
    {
        var active = message.TryGetProperty("an", out var enabled) && enabled.ValueKind == JsonValueKind.True;
        reminders.UpdateData(currentPlainText);
        reminders.Configure(active);
        form.SetReminderAutostart(active);
        var wake = message.TryGetProperty("wecken", out var wakeNode) && wakeNode.ValueKind == JsonValueKind.True;
        await form.SendAsync("App.erinnerungStand", new
        {
            ok = true,
            fehler = "",
            weckruf = wake ? new { ok = false, fehler = T("This system did not allow waking from suspend. The reminder will appear as soon as the computer is running again.") } : null
        });
    }

    private void LoadPersistentReminders()
    {
        try
        {
            var stored = store.ReadRecoverableJson(paths.Data);
            if (stored is null) { form.SetReminderAutostart(false); return; }
            var reminderData = stored;
            if (EncryptionService.IsEncrypted(stored))
                reminderData = store.ReadRecoverableJson(paths.ReminderData) ?? "";
            if (reminderData.Length == 0) { form.SetReminderAutostart(false); return; }
            UpdateReminderRuntime(reminderData);
        }
        catch (Exception) { form.SetReminderAutostart(false); }
    }

    private void UpdateReminderRuntime(string text)
    {
        reminders.UpdateData(text);
        var active = false;
        try
        {
            using var document = JsonDocument.Parse(text);
            active = document.RootElement.TryGetProperty("einstellungen", out var settings) &&
                     settings.TryGetProperty("erinnerung", out var reminder) &&
                     reminder.TryGetProperty("an", out var enabled) && enabled.ValueKind == JsonValueKind.True;
        }
        catch (JsonException) { }
        reminders.Configure(active);
        form.SetReminderAutostart(active);
    }

    private void RefreshReminderData(string plainText, bool encrypted)
    {
        if (!encrypted)
        {
            DeleteReminderData();
            return;
        }
        var selected = ReminderScheduler.SelectBackgroundData(plainText);
        if (selected is null) DeleteReminderData();
        else store.WriteRecoverableJson(paths.ReminderData, selected, 64 * 1024 * 1024);
    }

    private void DeleteReminderData()
    {
        foreach (var path in new[] { paths.ReminderData, AtomicStore.BackupPath(paths.ReminderData) })
            try { if (File.Exists(path)) File.Delete(path); } catch (IOException) { }
    }

    internal async Task ShutdownAsync()
    {
        if (disposed) return;
        kdeConnectSms.StatusChanged -= HandleKdeStatusChanged;
        kdeConnectSms.SmsReceived -= HandleKdeSmsReceived;
        kdeConnectSms.PairingChanged -= HandleKdePairingChanged;
        ClearPersonalSyncRuntime();
        await baum.ShutdownAsync().ConfigureAwait(false);
        telefon.Dispose();
        recoveryTimer.Dispose(); reminders.Dispose(); http.Dispose(); updates.Dispose(); kdeConnectSms.Dispose(); disposed = true;
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true; kdeConnectSms.StatusChanged -= HandleKdeStatusChanged; kdeConnectSms.SmsReceived -= HandleKdeSmsReceived;
        kdeConnectSms.PairingChanged -= HandleKdePairingChanged; ClearPersonalSyncRuntime(); recoveryTimer.Dispose(); baum.Dispose(); telefon.Dispose(); reminders.Dispose(); http.Dispose(); updates.Dispose(); kdeConnectSms.Dispose();
    }

    private async Task BaumSendAsync(JsonElement message, string kind, string property)
    {
        if (!message.TryGetProperty(property, out var content) || content.ValueKind != JsonValueKind.Object)
        {
            await form.SendAsync("App.baumGesendet", new { ok = false, fehler = T("The content is missing.") });
            return;
        }
        var node = JsonNode.Parse(content.GetRawText()) ?? new JsonObject();
        await baum.SendAsync(Text(message, "kennung"), kind, node);
    }

    private void BaumClearInbox(JsonElement message)
    {
        var ids = message.TryGetProperty("ids", out var values) && values.ValueKind == JsonValueKind.Array
            ? values.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.String).Select(value => value.GetString() ?? "")
            : Enumerable.Empty<string>();
        baum.ClearInbox(ids);
    }

    private async Task CreateBaumPairingFileAsync(JsonElement message)
    {
        using var dialog = new SaveFileDialog { Title = T("Save Magnolienbaum pairing file"), FileName = "magnolie-paarung.magnolie-paarung",
            Filter = T("Magnolienbaum pairing file (*.magnolie-paarung)") + "|*.magnolie-paarung", AddExtension = true, OverwritePrompt = true };
        if (dialog.ShowDialog(form) != DialogResult.OK) return;
        try
        {
            var document = baum.CreatePairingFile(Text(message, "adresse"), Port(message, "port"));
            store.Write(dialog.FileName, document.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            await form.SendAsync("App.baumPaarungsdatei", new { ok = true, art = "erzeugt", pfad = dialog.FileName,
                gueltigBis = document["gueltigBis"]?.GetValue<long>() ?? 0, fehler = "" });
            await baum.ReportStatusAsync();
        }
        catch (Exception error) { await form.SendAsync("App.baumPaarungsdatei", new { ok = false, art = "erzeugt", fehler = error.Message }); }
    }

    private async Task ImportBaumPairingFileAsync()
    {
        using var dialog = new OpenFileDialog { Title = T("Open Magnolienbaum pairing file"),
            Filter = T("Magnolienbaum pairing file (*.magnolie-paarung)") + "|*.magnolie-paarung", CheckFileExists = true };
        if (dialog.ShowDialog(form) != DialogResult.OK) return;
        try
        {
            var info = new FileInfo(dialog.FileName); if (info.Length > 8192) throw new IOException(T("The pairing file is too large."));
            var text = store.Read(dialog.FileName, 8192) ?? throw new IOException(T("The pairing file is empty."));
            var document = JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException(T("The pairing file is damaged."));
            await baum.ImportPairingFileAsync(document);
        }
        catch (Exception error) { await form.SendAsync("App.baumPaarungsdatei", new { ok = false, art = "importiert", fehler = error.Message }); }
    }

    private async Task BaumInternetAddressAsync()
    {
        try
        {
            var value = (await http.GetStringAsync("https://api64.ipify.org")).Trim();
            if (!IPAddress.TryParse(value, out var address) || IPAddress.IsLoopback(address)) throw new InvalidDataException(T("No public IP address was found."));
            await form.SendAsync("App.baumInternet", new { ok = true, adresse = value, fehler = "" });
        }
        catch (Exception error) { await form.SendAsync("App.baumInternet", new { ok = false, adresse = "", fehler = error.Message }); }
    }

    private static void SetClipboard(string text)
    {
        if (!string.IsNullOrEmpty(text)) Clipboard.SetText(text);
    }

    private async Task GetClipboardAsync()
    {
        var text = Clipboard.ContainsText() ? Clipboard.GetText() : "";
        await form.SendAsync("App.ablage", new { text });
    }

    private async Task OpenResultAsync(string callback, string target)
    {
        var ok = IsAllowedWebTarget(target) && ShellLauncher.OpenWebUri(target);
        await form.SendAsync(callback, new { ok, fehler = ok ? "" : T("The address could not be opened.") });
    }

    private async Task OpenValidatedResultAsync(string callback, string target, Func<string, bool> allowed)
    {
        var ok = allowed(target) && ShellLauncher.OpenWebUri(target);
        await form.SendAsync(callback, new { ok, fehler = ok ? "" : T("The download address is not permitted for this platform.") });
    }

    private async Task OpenLogsAsync()
    {
        try
        {
            var unlocked = LogPresentation.HasPersistentContributorUnlock(
                currentPlainText, contributorHash is not null, currentPlainTextAvailable);
            var viewPath = LogPresentation.CreateView(paths.Logs, unlocked);
            var ok = ShellLauncher.OpenLocalDirectory(viewPath, paths.Logs);
            await form.SendAsync("App.protokollStand", new { ok, pfad = viewPath, womit = ok ? "explorer" : "", fehler = ok ? "" : T("The log folder could not be opened.") });
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            await form.SendAsync("App.protokollStand", new { ok = false, pfad = paths.Logs, womit = "", fehler = error.Message });
        }
    }

    private async Task SpellSuggestionsAsync(JsonElement message)
    {
        var word = Text(message, "wort").Trim(); var identifier = Text(message, "kennung");
        if (word.Length == 0) { await form.SendAsync("App.vorschlaege", new { kennung = identifier, wort = "", richtig = true, vorschlaege = Array.Empty<string>(), fehler = "" }); return; }
        try
        {
            var result = await Task.Run(() => WindowsSpellChecker.Check(word, Text(message, "sprache")));
            await form.SendAsync("App.vorschlaege", new { kennung = identifier, wort = word, richtig = result.Correct, vorschlaege = result.Suggestions, fehler = "" });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.vorschlaege", new { kennung = identifier, wort = word, richtig = true, vorschlaege = Array.Empty<string>(), fehler = error.Message });
        }
    }

    private async Task RememberWordAsync(JsonElement message)
    {
        var word = Text(message, "wort").Trim();
        if (word.Length == 0) { await form.SendAsync("App.wortGemerkt", new { wort = "", ok = false, fehler = T("No word was provided.") }); return; }
        try { await Task.Run(() => WindowsSpellChecker.Add(word, Text(message, "sprache"))); await form.SendAsync("App.wortGemerkt", new { wort = word, ok = true, fehler = "" }); }
        catch (Exception error) { await form.SendAsync("App.wortGemerkt", new { wort = word, ok = false, fehler = error.Message }); }
    }

    private async Task OpenAddressResultAsync(string target)
    {
        var ok = ShellLauncher.OpenContactUri(target);
        await form.SendAsync("App.adressWeg", new { ok, fehler = ok ? "" : T("The destination could not be opened.") });
    }

    private static void OpenMedicine(string name)
    {
        if (string.IsNullOrWhiteSpace(name)) return;
        ShellLauncher.OpenWebUri("https://www.gelbe-liste.de/suche?query=" + Uri.EscapeDataString(name.Trim()));
    }

    private async Task CheckUpdateAsync()
    {
        var result = await updates.CheckAsync(AppVersion);
        if (!result.Ok)
        {
            await form.SendAsync("App.updateErgebnis", new { ok = false, fehler = result.Error });
            return;
        }
        var release = result.Release!;
        var manualPayload = result.Manual is null ? new { } : (object)new
        {
            version = result.Manual.Version, url = result.Manual.Url,
            sha256 = result.Manual.Sha256, platform = result.Manual.Platform
        };
        await form.SendAsync("App.updateErgebnis", new
        {
            ok = true, aktuell = result.Current, version = release.Version,
            url = result.Current ? "" : release.Url, sha256 = release.Sha256,
            handbuch = manualPayload, handbuchFehler = "", windows = true, fehler = ""
        });
    }

    private async Task DownloadUpdateAsync()
    {
        var result = await updates.DownloadAsync();
        await form.SendAsync("App.updateHeruntergeladen", new { ok = result.Ok, fehler = result.Error,
            version = result.Version, artifact = result.Artifact, bereit = result.Ready });
    }

    private async Task PrepareUpdateInstallationAsync()
    {
        var result = updates.PrepareInstallation();
        await form.SendAsync("App.updateInstallationVorbereitet", new { ok = result.Ok, fehler = result.Error,
            version = result.Version, artifact = result.Artifact, bereitZumBeenden = result.ReadyToExit });
    }

    private async Task DownloadManualAsync(JsonElement message)
    {
        var requested = new ValidatedManualRelease(Text(message, "version"), Text(message, "url"),
            Text(message, "sha256").ToLowerInvariant(), Text(message, "platform"));
        if (updates.LastManualRelease is null || requested != updates.LastManualRelease)
        {
            await form.SendAsync("App.handbuchDownloadGeoeffnet", new { ok = false, fehler = T("The manual download request is no longer valid.") });
            return;
        }
        try
        {
            var ok = await updates.DownloadAndOpenManualAsync(requested);
            await form.SendAsync("App.handbuchDownloadGeoeffnet", new { ok, fehler = ok ? "" : T("The manual download request is no longer valid.") });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.handbuchDownloadGeoeffnet", new { ok = false, fehler = error.Message });
        }
    }

    private async Task FetchWeatherAsync(JsonElement message)
    {
        var identifier = Integer(message, "kennung");
        var allowApproximate = !message.TryGetProperty("ohneOrtAbrufen", out var approximate) ||
                               approximate.ValueKind != JsonValueKind.False;
        var weatherLocation = WeatherLocationSelector.Select(Text(message, "ort"), allowApproximate);
        if (!weatherLocation.ShouldFetch)
        {
            await form.SendAsync("App.wetterErgebnis", new
            {
                ok = true, ohneOrt = true, ort = "", quelle = "none",
                tage = Array.Empty<object>(), fehler = "", kennung = identifier
            });
            return;
        }
        try
        {
            var location = weatherLocation.SearchLocation;
            var language = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "de" ? "de" : "en";
            var path = location.Length == 0 ? "" : Uri.EscapeDataString(location);
            using var response = await http.GetAsync($"https://wttr.in/{path}?format=j1&lang={language}",
                HttpCompletionOption.ResponseHeadersRead);
            response.EnsureSuccessStatusCode();
            await using var stream = await response.Content.ReadAsStreamAsync();
            using var document = await JsonDocument.ParseAsync(stream);
            var root = document.RootElement;
            var days = new List<object>();
            if (root.TryGetProperty("weather", out var weather) && weather.ValueKind == JsonValueKind.Array)
            {
                foreach (var day in weather.EnumerateArray().Take(3))
                {
                    var date = PropertyText(day, "date");
                    if (!DateOnly.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                            DateTimeStyles.None, out _)) continue;
                    var noon = day.TryGetProperty("hourly", out var hourly) && hourly.ValueKind == JsonValueKind.Array
                        ? hourly.EnumerateArray().OrderBy(hour => Math.Abs(PropertyInt(hour, "time") - 1200)).FirstOrDefault()
                        : default;
                    if (!double.TryParse(PropertyText(day, "mintempC"), NumberStyles.Float,
                            CultureInfo.InvariantCulture, out var minimum) ||
                        !double.TryParse(PropertyText(day, "maxtempC"), NumberStyles.Float,
                            CultureInfo.InvariantCulture, out var maximum)) continue;
                    var description = FirstValue(noon, $"lang_{language}");
                    if (description.Length == 0) description = FirstValue(noon, "weatherDesc");
                    days.Add(new
                    {
                        datum = date,
                        min = (int)Math.Round(minimum),
                        max = (int)Math.Round(maximum),
                        code = PropertyInt(noon, "weatherCode"),
                        beschreibung = description
                    });
                }
            }
            if (days.Count == 0) throw new IOException(T("The weather service returned no forecast."));
            var place = "";
            if (root.TryGetProperty("nearest_area", out var areas) && areas.ValueKind == JsonValueKind.Array)
                place = FirstValue(areas.EnumerateArray().FirstOrDefault(), "areaName");
            await form.SendAsync("App.wetterErgebnis", new
            {
                ok = true, ort = place.Length > 0 ? place : location,
                quelle = weatherLocation.Source,
                tage = days, fehler = "", kennung = identifier
            });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.wetterErgebnis", new
            {
                ok = false, fehler = error.Message, kennung = identifier
            });
        }
    }

    private async Task FetchHolidaysAsync(JsonElement message)
    {
        try
        {
            var country = Text(message, "land").Trim().ToUpperInvariant();
            var region = Text(message, "region").Trim().ToUpperInvariant();
            if (country.Length == 0) throw new ArgumentException(T("Select a country first."));
            var years = message.TryGetProperty("jahre", out var yearsNode) && yearsNode.ValueKind == JsonValueKind.Array
                ? yearsNode.EnumerateArray().Select(node => node.TryGetInt32(out var year) ? year : 0)
                    .Where(year => year is >= 1900 and <= 2200).Distinct().Order().Take(3).ToArray()
                : Array.Empty<int>();
            if (years.Length == 0) throw new ArgumentException(T("Select at least one year."));
            var includeSchool = !message.TryGetProperty("ferien", out var school) || school.ValueKind != JsonValueKind.False;
            var regions = new List<HolidayRegion>();
            if (message.TryGetProperty("regionen", out var regionsNode) && regionsNode.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in regionsNode.EnumerateArray())
                {
                    if (item.ValueKind != JsonValueKind.Array) continue;
                    var parts = item.EnumerateArray().ToArray();
                    if (parts.Length < 2) continue;
                    var code = parts[0].ToString().Trim().ToUpperInvariant();
                    var name = parts[1].ToString().Trim();
                    if (code.Length > 0 && name.Length > 0 && !regions.Any(value => value.Code == code && value.Name == name))
                        regions.Add(new HolidayRegion(code, name));
                }
            }
            if (regions.Count > 26) throw new ArgumentException(T("Too many regions were selected."));
            if (region.Length > 0) regions.Clear();
            if (Boolean(message, "regionErforderlich") && region.Length == 0 && regions.Count == 0)
                throw new ArgumentException(country == "CH"
                    ? T("Select your canton first or enable “All cantons”.")
                    : T("Select your state first or enable “All states”."));
            var targets = region.Length > 0
                ? new[] { new HolidayRegion(region, "") }
                : regions.Count > 0 ? regions.ToArray() : new[] { new HolidayRegion("", "") };
            var entries = new List<HolidayEntry>();
            var downloadedBytes = 0;
            foreach (var year in years)
            {
                foreach (var target in targets)
                {
                    downloadedBytes += await AddHolidayEntriesAsync(entries, "PublicHolidays", "public-holiday",
                        country, target, year, HolidayDownloadMaxBytes - downloadedBytes);
                    if (includeSchool)
                    {
                        try
                        {
                            downloadedBytes += await AddHolidayEntriesAsync(entries, "SchoolHolidays", "school-holiday",
                                country, target, year, HolidayDownloadMaxBytes - downloadedBytes);
                        }
                        catch (HttpRequestException) { }
                    }
                }
            }
            var allRegionNames = regions.Select(item => item.Name).ToHashSet(StringComparer.CurrentCultureIgnoreCase);
            var clean = entries.GroupBy(item => new { item.von, item.bis, item.name, item.art })
                .Select(group =>
                {
                    var first = group.First();
                    var names = group.Select(item => item.regionName).Where(name => name.Length > 0)
                        .Distinct(StringComparer.CurrentCultureIgnoreCase).Order(StringComparer.CurrentCultureIgnoreCase).ToArray();
                    var codes = group.Select(item => item.region).Where(code => code.Length > 0)
                        .Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
                    if (regions.Count == 0 || names.Length == 0) return first;
                    string suffix;
                    if (names.Length == allRegionNames.Count) suffix = country == "CH" ? T("all cantons") : T("all states");
                    else if (names.Length > allRegionNames.Count / 2)
                    {
                        var missing = allRegionNames.Except(names, StringComparer.CurrentCultureIgnoreCase)
                            .Order(StringComparer.CurrentCultureIgnoreCase);
                        suffix = T("all except %(regions)s").Replace("%(regions)s", string.Join(", ", missing));
                    }
                    else suffix = string.Join(", ", names);
                    return new HolidayEntry(first.von, first.bis, $"{first.name} ({suffix})", first.art,
                        string.Join(",", codes), suffix);
                }).OrderBy(item => item.von).ThenBy(item => item.name).ToArray();
            var publicCount = clean.Count(item => item.art == "public-holiday");
            var schoolCount = clean.Length - publicCount;
            var report = $"Abgerufen: {publicCount} Feiertage, {schoolCount} Ferienabschnitte für {string.Join(", ", years)}.";
            await form.SendAsync("App.feiertageErgebnis", new { feiertage = clean, bericht = report, jahre = years });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.feiertageErgebnis", new { fehler = error.Message });
        }
    }

    private const int HolidayDownloadMaxBytes = 8 * 1024 * 1024;

    private async Task<int> AddHolidayEntriesAsync(List<HolidayEntry> target, string path, string kind,
        string country, HolidayRegion region, int year, int remainingBytes)
    {
        if (remainingBytes <= 0) throw new IOException(T("The holiday service returned too much data."));
        var language = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "de" ? "DE" : "EN";
        var query = $"countryIsoCode={Uri.EscapeDataString(country)}&languageIsoCode={language}" +
                    $"&validFrom={year}-01-01&validTo={year}-12-31" +
                    (region.Code.Length > 0 ? $"&subdivisionCode={Uri.EscapeDataString(region.Code)}" : "");
        using var response = await http.GetAsync($"https://openholidaysapi.org/{path}?{query}", HttpCompletionOption.ResponseHeadersRead);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength > remainingBytes)
            throw new IOException(T("The holiday service returned too much data."));
        await using var stream = await response.Content.ReadAsStreamAsync();
        using var buffer = new MemoryStream();
        var chunk = new byte[81920];
        while (true)
        {
            var read = await stream.ReadAsync(chunk.AsMemory(0, Math.Min(chunk.Length, remainingBytes - (int)buffer.Length + 1)));
            if (read == 0) break;
            if (buffer.Length + read > remainingBytes)
                throw new IOException(T("The holiday service returned too much data."));
            buffer.Write(chunk, 0, read);
        }
        buffer.Position = 0;
        using var document = await JsonDocument.ParseAsync(buffer);
        var data = document.RootElement;
        if (data.ValueKind == JsonValueKind.Object && data.TryGetProperty("data", out var nested)) data = nested;
        if (data.ValueKind != JsonValueKind.Array) return checked((int)buffer.Length);
        foreach (var item in data.EnumerateArray())
        {
            var from = PropertyText(item, "startDate")[..Math.Min(10, PropertyText(item, "startDate").Length)];
            var toText = PropertyText(item, "endDate");
            var to = toText.Length >= 10 ? toText[..10] : from;
            var name = LocalizedName(item, language);
            if (DateOnly.TryParseExact(from, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out _) && name.Length > 0)
                target.Add(new HolidayEntry(from, to, name, kind, region.Code, region.Name));
        }
        return checked((int)buffer.Length);
    }

    private async Task ImportAsync(JsonElement message)
    {
        var art = Text(message, "art");
        var filter = art switch
        {
            "ics" => T("Calendar (*.ics)") + "|*.ics;*.vcs;*.lcs;*.zip|" + T("All files") + " (*.*)|*.*",
            "vcf" => T("Contact cards (*.vcf)") + "|*.vcf;*.csv;*.zip|" + T("All files") + " (*.*)|*.*",
            "lotus" => T("CSV files (*.csv)") + "|*.csv;*.zip|" + T("All files") + " (*.*)|*.*",
            "claws" => T("Claws Mail address book (*.xml)") + "|*.xml;*.ldif;*.ldi;*.zip|" + T("All files") + " (*.*)|*.*",
            _ => ""
        };
        if (filter.Length == 0)
        {
            await form.SendAsync("App.importErgebnis", new { art, abgebrochen = false, fehler = T("This import format is not yet available on Windows.") });
            return;
        }
        using var dialog = new OpenFileDialog { Title = T("Import"), Filter = filter, CheckFileExists = true, Multiselect = false };
        if (dialog.ShowDialog(form) != DialogResult.OK)
        {
            await form.SendAsync("App.importErgebnis", new { art, abgebrochen = true });
            return;
        }
        try
        {
            var info = new FileInfo(dialog.FileName);
            if (info.Length > ExchangeCodec.MaxImportBytes) throw new IOException(T("The import file is larger than 32 megabytes."));
            var bytes = await File.ReadAllBytesAsync(dialog.FileName);
            var result = ExchangeCodec.ParseImport(bytes, art, dialog.FileName);
            await form.SendAsync("App.importErgebnis", result.ToPayload(art, Path.GetFileName(dialog.FileName)));
        }
        catch (Exception error)
        {
            await form.SendAsync("App.importErgebnis", new { art, abgebrochen = false, fehler = error.Message });
        }
    }

    private async Task ImportLocalAsync(bool contactsOnly = false)
    {
        try
        {
            var folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Contacts");
            var contacts = await new WindowsContactStore(folder).ReadAsync(CancellationToken.None);
            var payload = contacts.Select(contact =>
            {
                var item = contact.Data.DeepClone().AsObject(); item["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
                item["geaendert"] = contact.Modified; return item;
            }).ToArray();
            var termine = new JsonArray(); var jahrestage = new JsonArray(); var aufgaben = new JsonArray();
            var skipped = 0; var recurring = 0; var thunderbirdFiles = 0;
            var profiles = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Thunderbird", "Profiles");
            if (!contactsOnly && Directory.Exists(profiles))
            {
                var calendars = Directory.EnumerateDirectories(profiles).Take(32)
                    .Select(profile => Path.Combine(profile, "calendar-data", "local.sqlite"));
                var parsed = ThunderbirdCalendarImporter.ParseProfiles(calendars, out thunderbirdFiles);
                foreach (var node in parsed.Termine) termine.Add(node?.DeepClone());
                foreach (var node in parsed.Jahrestage) jahrestage.Add(node?.DeepClone());
                foreach (var node in parsed.Aufgaben) aufgaben.Add(node?.DeepClone());
                skipped += parsed.Uebersprungen; recurring += parsed.Wiederholend;
            }
            var report = contactsOnly ? $"{T("Windows Contacts folder")}: {payload.Length}" :
                $"{payload.Length} Kontaktdateien und {thunderbirdFiles} Thunderbird-Kalenderablagen gelesen.";
            await form.SendAsync("App.importErgebnis", new { art = "lokal", abgebrochen = false, kontakte = payload,
                geburtstage = Array.Empty<object>(), termine, jahrestage, aufgaben, uebersprungen = skipped, wiederholend = recurring,
                bericht = report });
        }
        catch (Exception error) { await form.SendAsync("App.importErgebnis", new { art = "lokal", abgebrochen = false, fehler = error.Message }); }
    }

    private async Task ExportAsync(JsonElement message)
    {
        var art = Text(message, "art");
        var settings = art switch
        {
            "ics-termine" => ("magnolie-termine.ics", T("Calendar (*.ics)") + "|*.ics"),
            "ics-jahrestage" => ("magnolie-jahrestage.ics", T("Calendar (*.ics)") + "|*.ics"),
            "ics-aufgaben" => ("magnolie-aufgaben.ics", T("Calendar (*.ics)") + "|*.ics"),
            "vcf-adressen" => ("magnolie-adressen.vcf", T("Contact cards (*.vcf)") + "|*.vcf"),
            "ldif-adressen" => ("magnolie-adressen-claws.ldif", T("LDIF address book (*.ldif)") + "|*.ldif"),
            "csv-termine" => ("magnolie-termine-lotus.csv", T("CSV files (*.csv)") + "|*.csv"),
            _ => ("", "")
        };
        if (settings.Item1.Length == 0)
        {
            await form.SendAsync("App.exportErgebnis", new { art, abgebrochen = false, ok = false, fehler = T("This export format is not yet available on Windows.") });
            return;
        }
        using var dialog = new SaveFileDialog { Title = T("Export"), FileName = settings.Item1, Filter = settings.Item2, AddExtension = true, OverwritePrompt = true };
        if (dialog.ShowDialog(form) != DialogResult.OK)
        {
            await form.SendAsync("App.exportErgebnis", new { art, abgebrochen = true });
            return;
        }
        try
        {
            if (!message.TryGetProperty("daten", out var data)) throw new ArgumentException(T("The export data is missing."));
            var result = art switch { "vcf-adressen" => ExchangeCodec.WriteVCard(data), "ldif-adressen" => ExchangeCodec.WriteLdif(data), "csv-termine" => ExchangeCodec.WriteLotusCsv(data), _ => ExchangeCodec.WriteIcs(art, data) };
            if (art == "ldif-adressen") new AtomicStore().Write(dialog.FileName, result.Text);
            else await File.WriteAllTextAsync(dialog.FileName, result.Text, new UTF8Encoding(art == "csv-termine"));
            await form.SendAsync("App.exportErgebnis", new { art, abgebrochen = false, ok = true, pfad = dialog.FileName, anzahl = result.Count, uebersprungen = art == "ldif-adressen" ? 0 : result.Skipped, bericht = result.Bericht, rawVerworfen = result.RawOmitted, ldifUnbrauchbar = art == "ldif-adressen" ? result.Skipped : 0, ldifFotoVerloren = result.PhotoOmitted });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.exportErgebnis", new { art, abgebrochen = false, ok = false, fehler = error.Message });
        }
    }

    private async Task CreateLetterAsync(JsonElement message)
    {
        try
        {
            if (!message.TryGetProperty("kontakt", out var contact) || contact.ValueKind != JsonValueKind.Object) throw new ArgumentException(T("The contact is missing."));
            var bytes = DocumentExportService.CreateLetter(contact, Text(message, "absender"), Text(message, "layout"));
            using var dialog = new SaveFileDialog
            {
                Title = T("Save") + " - " + T("Letter"),
                FileName = $"Brief-{DateTime.Now:yyyyMMdd-HHmmss}.odt",
                Filter = T("Letter") + " (*.odt)|*.odt",
                DefaultExt = "odt",
                AddExtension = true,
                OverwritePrompt = true
            };
            if (dialog.ShowDialog(form) != DialogResult.OK)
            {
                await form.SendAsync("App.adressWeg", new { ok = false, abgebrochen = true, pfad = "", womit = "", fehler = "" });
                return;
            }
            var file = DocumentExportService.LetterFileName(dialog.FileName);
            await File.WriteAllBytesAsync(file, bytes);
            var opened = ShellLauncher.OpenLocalFile(file, Path.GetDirectoryName(Path.GetFullPath(file))!);
            await form.SendAsync("App.adressWeg", new { ok = opened, pfad = file, womit = opened ? "system" : "", fehler = opened ? "" : T("The letter was created but could not be opened.") });
        }
        catch (Exception error) { await form.SendAsync("App.adressWeg", new { ok = false, pfad = "", womit = "", fehler = error.Message }); }
    }

    private async Task CreateSpreadsheetAsync(JsonElement message, string defaultName, string fileName)
    {
        try
        {
            var sheet = DocumentExportService.ReadSheet(message, defaultName);
            await WriteAndOpenSpreadsheetAsync(DocumentExportService.CreateSpreadsheet(new[] { sheet }), fileName);
        }
        catch (Exception error) { await form.SendAsync("App.adressWeg", new { ok = false, pfad = "", womit = "", fehler = error.Message }); }
    }

    private async Task CreateHealthSpreadsheetAsync(JsonElement message)
    {
        try
        {
            var sheets = DocumentExportService.ReadHealthSheets(message);
            await WriteAndOpenSpreadsheetAsync(DocumentExportService.CreateSpreadsheet(sheets), "Magnolie-Gesundheit.ods");
        }
        catch (Exception error) { await form.SendAsync("App.adressWeg", new { ok = false, pfad = "", womit = "", fehler = error.Message }); }
    }

    private async Task WriteAndOpenSpreadsheetAsync(byte[] bytes, string fileName)
    {
        var directory = Path.Combine(Path.GetTempPath(), "Magnolie Organizer", "Tabellen");
        Directory.CreateDirectory(directory);
        var file = Path.Combine(directory, fileName);
        await File.WriteAllBytesAsync(file, bytes);
        var opened = ShellLauncher.OpenLocalFile(file, directory);
        await form.SendAsync("App.adressWeg", new { ok = opened, pfad = file, womit = opened ? "system" : "", fehler = opened ? "" : T("The spreadsheet was created but could not be opened.") });
    }

    private static string LocalizedName(JsonElement item, string language)
    {
        if (!item.TryGetProperty("name", out var names)) return "";
        if (names.ValueKind == JsonValueKind.String) return names.GetString() ?? "";
        if (names.ValueKind != JsonValueKind.Array) return "";
        var fallback = "";
        foreach (var name in names.EnumerateArray())
        {
            var text = PropertyText(name, "text");
            if (fallback.Length == 0) fallback = text;
            if (PropertyText(name, "language").Equals(language, StringComparison.OrdinalIgnoreCase)) return text;
        }
        return fallback;
    }

    private static string FirstValue(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object || !element.TryGetProperty(name, out var values) ||
            values.ValueKind != JsonValueKind.Array) return "";
        var first = values.EnumerateArray().FirstOrDefault();
        return PropertyText(first, "value");
    }

    private static string PropertyText(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value)
            ? value.ToString().Trim() : "";

    private static int PropertyInt(JsonElement element, string name) =>
        int.TryParse(PropertyText(element, name), NumberStyles.Integer, CultureInfo.InvariantCulture,
            out var value) ? value : 0;

    private Task ReportUnsupportedAsync(string command)
    {
        RotatingLog.Append(Path.Combine(paths.Logs, "bridge.log"), $"{DateTimeOffset.Now:O} unsupported={command}");
        return Task.CompletedTask;
    }

    private static string T(string message) => NativeLocalization.Gettext(message);

    /// <summary>
    /// Ohne Firewallregel nimmt Windows keine eingehende Netzwerkverbindung an.
    /// Die Regel wird genau dann angelegt, wenn der Benutzer einen Netzwerkdienst
    /// ausdrücklich einschaltet oder eine Paarung startet – nur dann ist die
    /// UAC-Abfrage für ihn nachvollziehbar. Der lange laufende Aufruf gehört
    /// nicht auf den Oberflächenfaden.
    /// </summary>
    private async Task EnsureFirewallAsync()
    {
        try { firewallHint = await Task.Run(WindowsFirewall.Ensure); }
        catch (Exception error) { firewallHint = WindowsFirewall.FirewallHint; await ReportErrorAsync("firewall", error.Message); }
    }

    private Task ReportErrorAsync(string command, string error)
    {
        RotatingLog.Append(Path.Combine(paths.Logs, "bridge.log"),
            $"{DateTimeOffset.Now:O} command={command} error={error}");
        return Task.CompletedTask;
    }

    private async Task ReportCommandErrorAsync(string command, JsonElement message, string error)
    {
        if (command == "telefon_waehlen")
            await form.SendAsync("App.telefonWaehlStatus", new { device_id = Text(message, "kennung"),
                client_ref = Text(message, "clientRef"), state = "failed", error, occurred_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() });
        else if (command == "telefon_auflegen")
            await form.SendAsync("App.telefonAuflegeStatus", new { device_id = Text(message, "kennung"),
                call_ref = Text(message, "callRef"), command_ref = Text(message, "commandRef"), state = "failed", error,
                occurred_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() });
        else if (command == "telefon_annehmen")
            await form.SendAsync("App.telefonAnnehmStatus", new { device_id = Text(message, "kennung"),
                call_ref = Text(message, "callRef"), command_ref = Text(message, "commandRef"), state = "failed", error,
                occurred_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() });
        else if (command.StartsWith("personal_sync_", StringComparison.Ordinal) || command == "telefon_personal_sync_commit")
            await form.SendAsync("App.personalSyncFehler", new { fehler = error });
        else if (command.StartsWith("telefon_pairing_", StringComparison.Ordinal))
            await form.SendAsync("App.telefonPairingFehler", new { fehler = error });
        else if (command.StartsWith("kde_pairing_", StringComparison.Ordinal))
            await form.SendAsync("App.kdePairingStatus", new { state = "failed", error });
        await ReportErrorAsync(command, error);
    }

    private static string MailUri(JsonElement message)
    {
        var address = Text(message, "email").Trim();
        if (address.StartsWith("mailto:", StringComparison.OrdinalIgnoreCase)) address = address[7..];
        var angle = Regex.Match(address, @"<([^<>]+)>$"); if (angle.Success) address = angle.Groups[1].Value;
        if (!EmailPattern().IsMatch(address) || address.Length > 254 || address.EndsWith(".invalid", StringComparison.OrdinalIgnoreCase)) return "";
        var name = Regex.Replace(Text(message, "name").ReplaceLineEndings(" ").Replace("<", "").Replace(">", ""), @"\s+", " ").Trim();
        var target = name.Length > 0 ? $"{name} <{address}>" : address;
        return "mailto:" + Uri.EscapeDataString(target).Replace("%40", "@", StringComparison.OrdinalIgnoreCase);
    }

    private static string MapUri(JsonElement message)
    {
        if (!message.TryGetProperty("kontakt", out var contact) || contact.ValueKind != JsonValueKind.Object) return "";
        var street = PropertyText(contact, "strasse"); var city = $"{PropertyText(contact, "plz")} {PropertyText(contact, "ort")}".Trim();
        var country = Text(message, "land").Trim();
        var destination = string.Join(", ", new[] { street, city, country }.Where(value => value.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase));
        if (destination.Length == 0) return "";
        var google = Text(message, "dienst") != "openstreetmap";
        var route = message.TryGetProperty("route", out var routeNode) && routeNode.ValueKind == JsonValueKind.True;
        if (!route) return google
            ? "https://www.google.com/maps/search/?api=1&query=" + Uri.EscapeDataString(destination)
            : "https://www.openstreetmap.org/search?query=" + Uri.EscapeDataString(destination);
        var origin = SenderAddress(Text(message, "absender"), country);
        if (origin.Length == 0) return "";
        return google
            ? $"https://www.google.com/maps/dir/?api=1&destination={Uri.EscapeDataString(destination)}&origin={Uri.EscapeDataString(origin)}"
            : $"https://www.openstreetmap.org/directions?from={Uri.EscapeDataString(origin)}&to={Uri.EscapeDataString(destination)}";
    }

    private static string SocialUri(JsonElement message)
    {
        var value = Text(message, "wert").Trim();
        var service = Text(message, "dienst").Trim().ToLowerInvariant() switch { "telefon" => "phone", "twitter" => "x", "likedin" => "linkedin", var other => other };
        var action = Text(message, "aktionArt"); var actionTarget = Text(message, "aktionZiel");
        if (action == "program") return "";
        if (action == "website")
        {
            var replaced = actionTarget.Replace("{wert}", Uri.EscapeDataString(value)).Replace("{ziel}", Uri.EscapeDataString(value));
            return IsAllowedHttpsTarget(replaced) ? replaced : "";
        }
        if (service is "whatsapp" or "signal" or "sms" or "phone" or "teams-call")
        {
            var phoneUri = PhoneUri.Build(service, value, Text(message, "land"),
                NativeMethods.HasUriScheme("msteams"));
            if (phoneUri.Length == 0) return "";
            var phone = phoneUri.StartsWith("tel:", StringComparison.Ordinal) ? phoneUri[4..] : "";
            if (service == "teams-call") return phoneUri;
            return service switch { "whatsapp" => "https://wa.me/" + phone.TrimStart('+'), "signal" => "https://signal.me/#p/" + phone,
                "sms" => "sms:" + phone, _ => phoneUri };
        }
        var clean = value.Trim().TrimStart('@');
        return service switch
        {
            "threema" => "https://web.threema.ch/", "facebook" => Profile("https://www.facebook.com/", clean),
            "instagram" => Profile("https://www.instagram.com/", clean), "teams" => "https://teams.microsoft.com/l/chat/0/0?users=" + Uri.EscapeDataString(value),
            "snapchat" => Profile("https://www.snapchat.com/add/", clean), "tiktok" => Profile("https://www.tiktok.com/@", clean),
            "youtube" => Profile("https://www.youtube.com/@", clean), "telegram" => Profile("https://t.me/", clean),
            "x" => Profile("https://x.com/", clean), "linkedin" => Profile("https://www.linkedin.com/in/", clean),
            "reddit" => Profile("https://www.reddit.com/user/", clean), "custom" when IsAllowedHttpsTarget(value) => value,
            _ => ""
        };
    }

    private static bool IsAllowedWebTarget(string target) =>
        Uri.TryCreate(target, UriKind.Absolute, out var uri) &&
            (uri.Scheme == Uri.UriSchemeHttps || uri.Scheme == Uri.UriSchemeHttp);

    private static bool IsAllowedHttpsTarget(string target) => Uri.TryCreate(target, UriKind.Absolute, out var uri) &&
        uri.Scheme == Uri.UriSchemeHttps && uri.Host.Length > 0 && string.IsNullOrEmpty(uri.UserInfo);
    private static bool IsAllowedWindowsUpdateUrl(string target) => IsAllowedPackageUrl(target, "Magnolie-Organizer-Windows-", "-Setup-x64.exe");
    internal static bool IsAllowedManualUrl(string target, string version) =>
        VersionPattern().IsMatch(version) && IsAllowedPackageUrl(target,
            $"Magnolie-Organizer-Windows-{version}-Setup-x64", ".exe") &&
        Uri.TryCreate(target, UriKind.Absolute, out var uri) &&
        Path.GetFileName(uri.AbsolutePath) == $"Magnolie-Organizer-Windows-{version}-Setup-x64.exe";
    private static bool IsAllowedPackageUrl(string target, string prefix, string suffix) => Uri.TryCreate(target, UriKind.Absolute, out var uri) &&
        uri.Scheme == Uri.UriSchemeHttps && uri.Host.Equals("gitlab.com", StringComparison.OrdinalIgnoreCase) && string.IsNullOrEmpty(uri.Query) &&
        string.IsNullOrEmpty(uri.Fragment) && string.IsNullOrEmpty(uri.UserInfo) &&
        uri.AbsolutePath.StartsWith("/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/" + prefix, StringComparison.Ordinal) && uri.AbsolutePath.EndsWith(suffix, StringComparison.Ordinal);
    private static string Profile(string prefix, string value) => value.Length > 0 ? prefix + Uri.EscapeDataString(value) : "";
    private static string SenderAddress(string sender, string country)
    {
        var lines = sender.ReplaceLineEndings("\n").Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var useful = lines.Where(line => line.Any(char.IsDigit)).Take(2).ToList(); if (country.Length > 0) useful.Add(country);
        return string.Join(", ", useful);
    }
    private static int CompareVersions(string left, string right)
    {
        var a = Regex.Matches(left.TrimStart('v', 'V'), @"\d+").Select(match => int.Parse(match.Value, CultureInfo.InvariantCulture)).ToArray();
        var b = Regex.Matches(right.TrimStart('v', 'V'), @"\d+").Select(match => int.Parse(match.Value, CultureInfo.InvariantCulture)).ToArray();
        for (var index = 0; index < Math.Max(a.Length, b.Length); index++) { var result = (index < a.Length ? a[index] : 0).CompareTo(index < b.Length ? b[index] : 0); if (result != 0) return result; }
        return 0;
    }

    [GeneratedRegex(@"^[^\s<>,;:@]+@[^\s<>,;:@]+\.[^\s<>,;:@]+$", RegexOptions.CultureInvariant)] private static partial Regex EmailPattern();
    [GeneratedRegex(@"^[vV]?\d+(?:\.\d+)*(?:-\d+)?$", RegexOptions.CultureInvariant)] private static partial Regex VersionPattern();
    [GeneratedRegex(@"^[0-9a-f]{64}$", RegexOptions.CultureInvariant)] private static partial Regex ShaPattern();

    private static string Text(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? "" : "";

    private static int Integer(JsonElement element, string name) =>
            element.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : 0;

    private static bool Boolean(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    private static int Port(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value)) return 8737;
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) && number is >= 1 and <= 65535) return number;
        if (value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), out number) && number is >= 1 and <= 65535) return number;
        throw new ArgumentException(T("The port must be between 1 and 65535."));
    }

    private sealed record HolidayEntry(string von, string bis, string name, string art,
        string region, string regionName);
    private sealed record HolidayRegion(string Code, string Name);
}
