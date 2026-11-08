using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private readonly object receiveConfigurationGate = new();
    private string receiveConfigurationSignature = "";
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, byte> receiveChoosers = new(StringComparer.Ordinal);

    private bool ReceiveOwnerCurrent(string? owner) => owner is not null && !disposed &&
        currentPlainTextAvailable && !restoreInProgress && NativeActorBookSource() == owner;

    private void ConfigureReceive(bool enabled, string device, string directory = "", bool chooseEach = true,
        bool clipboard = false, bool automaticClipboard = false)
    {
        var owner = NativeActorBookSource();
        if (!ReceiveOwnerCurrent(owner)) enabled = clipboard = false;
        var destination = !enabled || chooseEach ? "" : directory.Length != 0 ? directory : NativeMethods.UserDownloadsPath();
        var signature = JsonSerializer.Serialize(new { enabled, clipboard, automaticClipboard = clipboard && automaticClipboard,
            device = enabled || clipboard ? device : "", destination, owner });
        lock (receiveConfigurationGate)
        {
            if (signature == receiveConfigurationSignature) return;
            if (enabled) kdeConnectSms.ConfigureFileReceive(true, device, destination, () => ReceiveOwnerCurrent(owner));
            else kdeInstance?.ConfigureFileReceive(false, "", "");
            if (clipboard) kdeConnectSms.ConfigureClipboardReceive(true, device, automaticClipboard, () => ReceiveOwnerCurrent(owner));
            else kdeInstance?.ConfigureClipboardReceive(false, "", false);
            receiveConfigurationSignature = signature;
        }
    }

    private void ApplySavedReceiveConfiguration()
    {
        try
        {
            using var document = JsonDocument.Parse(currentPlainText);
            var root = document.RootElement;
            if (root.TryGetProperty("einstellungen", out var settings) && settings.TryGetProperty("sync", out var sync) &&
                sync.TryGetProperty("kdeEmpfang", out var receive) && receive.ValueKind == JsonValueKind.Object)
                ConfigureReceive(Boolean(receive, "dateien"), Text(receive, "geraetId"), Text(receive, "ordner"),
                    !receive.TryGetProperty("ordnerBeiAnnahme", out var choose) || choose.ValueKind != JsonValueKind.False,
                    Boolean(receive, "zwischenablage"), Boolean(receive, "zwischenablageAutomatisch"));
            else ConfigureReceive(false, "");
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or IOException or UnauthorizedAccessException)
        {
            kdeInstance?.ConfigureFileReceive(false, "", "");
            kdeInstance?.ConfigureClipboardReceive(false, "", false);
            lock (receiveConfigurationGate) receiveConfigurationSignature = "";
            RotatingLog.Append(Path.Combine(paths.Logs, "background.log"), "KDE receive configuration: " + error.GetType().Name);
        }
    }

    private static bool ReceiveId(string id) => id.Length == 32 && id.All(char.IsAsciiHexDigitLower);

    private async Task KdeReceiveAsync(JsonElement message)
    {
        var command = Text(message, "cmd");
        if (command == "kde_receive_settings")
        {
            if (!ReceiveOwnerCurrent(NativeActorBookSource())) return;
            ConfigureReceive(Boolean(message, "files"), Text(message, "deviceId"), Text(message, "directory"),
                !message.TryGetProperty("chooseEach", out var choose) || choose.ValueKind != JsonValueKind.False,
                Boolean(message, "clipboard"), Boolean(message, "automaticClipboard"));
            return;
        }
        if (command == "kde_receive_directory")
        {
            var requestId = Text(message, "requestId");
            if (!Guid.TryParse(requestId, out _)) return;
            var owner = NativeActorBookSource();
            if (!ReceiveOwnerCurrent(owner)) return;
            using var dialog = new FolderBrowserDialog { Description = T("Choose folder …"), UseDescriptionForTitle = true,
                ShowNewFolderButton = true, SelectedPath = Text(message, "directory") };
            var selected = dialog.ShowDialog(form) == DialogResult.OK && ReceiveOwnerCurrent(owner) &&
                KdeIncomingFileBatch.RealDirectoryChain(dialog.SelectedPath) ? dialog.SelectedPath : "";
            await form.SendAsync("App.kdeEmpfangsordner", new { requestId, pfad = selected });
            return;
        }
        var id = Text(message, "id");
        if (!ReceiveId(id)) return;
        if (command == "kde_receive_angebot")
        {
            var clipboard = kdeInstance?.CurrentClipboardReceiveProposal(id);
            if (clipboard is not null && ReceiveOwnerCurrent(NativeActorBookSource()))
            {
                await form.SendAsync("App.kdeEmpfangGeprueft", new { id, live = true, kind = "clipboard",
                    text = clipboard.Text, automatic = clipboard.Automatic });
                return;
            }
            var live = kdeInstance?.CurrentFileReceiveProposal(id);
            await form.SendAsync("App.kdeEmpfangGeprueft", live is null ? new { id, live = false } :
                (object)new { id, live = true, destination_fixed = live.DestinationFixed,
                    files = live.Files.Select(file => new { name = file.Name, size = file.Size }) });
            return;
        }
        if (command == "kde_receive_decide" && kdeInstance?.CurrentClipboardReceiveProposal(id) is not null)
        {
            var accept = Boolean(message, "accept") && ReceiveOwnerCurrent(NativeActorBookSource());
            var text = kdeInstance.TakeClipboardReceive(id, accept);
            if (text is not null && ReceiveOwnerCurrent(NativeActorBookSource()))
            {
                if (text.Length == 0) Clipboard.Clear(); else Clipboard.SetText(text);
            }
            await form.SendAsync("App.kdeEmpfangBeendet", new { id });
            return;
        }
        if (command == "kde_receive_decide" && !Boolean(message, "accept"))
        {
            QueueNetworkCommand(() => kdeConnectSms.RejectFileReceiveAsync(id), "kde");
            return;
        }
        // Even a caller using the old direct-accept command must select a native
        // destination. Frontend-supplied paths never authorize publication.
        var proposal = kdeInstance?.CurrentFileReceiveProposal(id);
        if (proposal is null || !ReceiveOwnerCurrent(NativeActorBookSource()))
        { await form.SendAsync("App.kdeEmpfangBeendet", new { id }); return; }
        if (!receiveChoosers.TryAdd(id, 0)) return;
        var queued = false;
        try
        {
            var owner = NativeActorBookSource();
            var selected = "";
            if (!proposal.DestinationFixed)
            {
                using var dialog = new FolderBrowserDialog { Description = T("Choose folder …"),
                    UseDescriptionForTitle = true, ShowNewFolderButton = true };
                if (kdeInstance?.CurrentFileReceiveProposal(id) is null || !ReceiveOwnerCurrent(owner)) return;
                if (dialog.ShowDialog(form) != DialogResult.OK)
                {
                    QueueNetworkCommand(() => kdeConnectSms.RejectFileReceiveAsync(id), "kde");
                    await form.SendAsync("App.kdeEmpfangBeendet", new { id }); return;
                }
                selected = dialog.SelectedPath;
            }
            if (!ReceiveOwnerCurrent(owner) || kdeInstance?.CurrentFileReceiveProposal(id) is null)
            { await form.SendAsync("App.kdeEmpfangBeendet", new { id }); return; }
            QueueNetworkCommand(async () =>
            {
                try
                {
                    if (!ReceiveOwnerCurrent(owner) || kdeInstance?.CurrentFileReceiveProposal(id) is null) return;
                    using var deadline = NetworkDeadline(TimeSpan.FromMinutes(10));
                    var result = await kdeConnectSms.AcceptFileReceiveAsync(id, selected, deadline.Token).ConfigureAwait(false);
                    await form.SendAsync("App.kdeEmpfangErgebnis", result).ConfigureAwait(false);
                }
                finally
                {
                    receiveChoosers.TryRemove(id, out _);
                    var retry = kdeInstance?.CurrentFileReceiveProposal(id);
                    if (retry is not null && ReceiveOwnerCurrent(owner)) HandleKdeFileProposed(retry);
                }
            }, "kde", reason =>
            {
                receiveChoosers.TryRemove(id, out _);
                return form.SendAsync("App.kdeEmpfangBeendet", new { id });
            });
            queued = true;
        }
        finally { if (!queued) receiveChoosers.TryRemove(id, out _); }
    }

    private void HandleKdeFileProposed(KdeFileReceiveProposal proposal) => _ = SafeBackgroundAsync(async () =>
    {
        var live = kdeInstance?.CurrentFileReceiveProposal(proposal.Id);
        if (live is null || receiveChoosers.ContainsKey(proposal.Id) || !ReceiveOwnerCurrent(NativeActorBookSource())) return;
        form.ShowTelefonNotification(T("Receive files"), T("Open") + " · " + live.Files.Count.ToString(System.Globalization.CultureInfo.InvariantCulture));
        await form.SendAsync("App.kdeEmpfangAngebot", new { id = live.Id, device_id = live.DeviceId,
            size = live.Size, destination_fixed = live.DestinationFixed,
            files = live.Files.Select(file => new { name = file.Name, size = file.Size }) });
    });

    private void HandleKdeClipboardProposed(KdeClipboardReceiveProposal proposal) => _ = SafeBackgroundAsync(async () =>
    {
        if (kdeInstance?.CurrentClipboardReceiveProposal(proposal.Id) is null || !ReceiveOwnerCurrent(NativeActorBookSource())) return;
        if (!proposal.Automatic) form.ShowTelefonNotification(T("Transfer received text to the clipboard"), T("Open"));
        await form.SendAsync("App.kdeEmpfangAngebot", new { id = proposal.Id });
    });

    private void HandleKdeFileReceiveProgress(KdeFileReceiveProgress progress) => _ = SafeBackgroundAsync(async () =>
    {
        if (progress.State is "expired" or "rejected" or "saved")
            await form.SendAsync("App.kdeEmpfangBeendet", new { id = progress.Id });
        else if (progress.State == "failed")
            await form.SendAsync("App.kdeEmpfangFehler", new { id = progress.Id, fehler = T("KDE Connect reception failed.") });
    });

    private void HandleKdeFileSaved(KdeSavedIncomingFile file) => _ = SafeBackgroundAsync(() =>
        form.SendAsync("App.kdeDateiEmpfangen", new { name = file.Name, size = file.Size }));
}
