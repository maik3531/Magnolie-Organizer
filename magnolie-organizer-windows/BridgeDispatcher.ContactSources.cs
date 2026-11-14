using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private ContactSourceNativeSession? originalContactSession;
    private ContactSourceApprovalStore? originalContactApprovalStore;
    private ContactSourceAutomation? originalContactAutomation;
    private System.Threading.Timer? originalContactMonitor;
    private int originalContactProbe;
    private ContactSourceApprovalStore OriginalContactApprovals => LazyInitializer.EnsureInitialized(ref originalContactApprovalStore,
        () => new(new ContactSourcePrivateFiles(Path.Combine(Path.GetFullPath(paths.Root), "kontakt-quellen-freigabe")),
            NextcloudSettings, NativeActorBook, () => Path.GetFullPath(paths.Data), capturePrimary: () =>
                ContactSourcePrimaryBook.Capture(Path.GetFullPath(paths.Data), store, encryption,
                    () => currentPlainTextAvailable && !restoreInProgress && !disposed &&
                        (string.IsNullOrEmpty(currentEnvelope) || encryption.Session is not null))));
    private ContactSourceNativeSession OriginalContactSession => LazyInitializer.EnsureInitialized(ref originalContactSession, () => new(
        NativeActorBook, NativeActorSavedBook, NextcloudSettings, OriginalContactCommit,
        OriginalContactWlanAvailable, _ => CreateSnapshot(SnapshotReason.PreContact), durableStore: OriginalContactApprovals));
    private ContactSourceAutomation OriginalContactAutomation => LazyInitializer.EnsureInitialized(ref originalContactAutomation,
        () => new(OriginalContactApprovals, OriginalContactSession, NativeActorBook,
            () => currentPlainTextAvailable && !restoreInProgress && !disposed, notice =>
                form.SendAsync("App.originalKontaktDauerfreigabe", new { id = notice.Id, standSha256 = notice.Sha256,
                    ok = notice.Ok, freigaben = notice.Grants })));

    private void StopOriginalContactMonitor() => Interlocked.Exchange(ref originalContactMonitor, null)?.Dispose();

    private void StartOriginalContactMonitor()
    {
        if (disposed || originalContactMonitor is not null || originalContactAutomation?.HasCurrentIntent != true) return;
        var timer = new System.Threading.Timer(_ =>
        {
            if (Interlocked.CompareExchange(ref originalContactProbe, 1, 0) != 0) return;
            _ = QueueBackground(async () =>
            {
                try
                {
                    var automation = originalContactAutomation;
                    if (disposed || automation?.HasCurrentIntent != true) { StopOriginalContactMonitor(); return; }
                    var usable = await automation.ProbeAsync();
                    if (usable && !disposed && automation.HasCurrentIntent && OriginalContactWlanAvailable())
                        await form.SendAsync("App.originalKontaktNetz", new { wlan = true });
                }
                catch (Exception) { /* Quietly hold; no prompt, provider retry or permission expansion. */ }
                finally { Volatile.Write(ref originalContactProbe, 0); }
            });
        }, null, TimeSpan.FromSeconds(15), TimeSpan.FromSeconds(15));
        if (Interlocked.CompareExchange(ref originalContactMonitor, timer, null) is not null) timer.Dispose();
        if (disposed) StopOriginalContactMonitor();
    }

    private async Task OriginalContactSaveAcknowledgedAsync(int id, string hash, bool recognized)
    {
        try
        {
            if (await OriginalContactAutomation.SavedAsync(id, hash, recognized)) StartOriginalContactMonitor();
            else StopOriginalContactMonitor();
        }
        catch (Exception) { /* The user data SaveACK already succeeded. Consent remains held. */ }
    }

    private static bool OriginalContactWlanAvailable()
    {
        try
        {
            // An UP wireless adapter alone does not prove that Windows routes
            // this connection over WLAN (mobile/VPN may own the default route).
            // Unknown/non-WLAN default profiles conservatively hold the run.
            var profile = global::Windows.Networking.Connectivity.NetworkInformation.GetInternetConnectionProfile();
            return profile?.IsWlanConnectionProfile == true && profile.GetNetworkConnectivityLevel() !=
                global::Windows.Networking.Connectivity.NetworkConnectivityLevel.None;
        }
        catch (Exception) { return false; } // Unknown network is not permission to fall back to mobile data.
    }

    private async Task ConfigureOriginalContactSourcesAsync(JsonElement message)
    {
        using var operation = NetworkDeadline(TimeSpan.FromMinutes(10));
        try
        {
            var result = await OriginalContactAutomation.ConfigureAsync((sources, selected, token) =>
                ContactSourceApprovalDialog.ChooseAsync(form, sources, selected, T, token), operation.Token);
            await form.SendAsync("App.originalKontaktFreigabe", new { requestId = Text(message, "requestId"), ok = true,
                changed = result.Changed, freigaben = result.Grants, dauerhaft = result.Desired, wartet = result.Waiting,
                id = result.Id, standSha256 = result.Sha256 });
            if (result.Desired) StartOriginalContactMonitor(); else StopOriginalContactMonitor();
        }
        catch (Exception)
        {
            await form.SendAsync("App.originalKontaktFreigabe", new { requestId = Text(message, "requestId"), ok = false,
                changed = false, freigaben = originalContactSession?.GrantCount ?? 0 });
        }
    }

    private async Task RevokeOriginalContactSourcesAsync(JsonElement message)
    {
        StopOriginalContactMonitor();
        var ok = true;
        try { await OriginalContactAutomation.RevokeAsync(Boolean(message, "dauerhaft")); }
        catch (Exception) { ok = false; }
        await form.SendAsync("App.originalKontaktFreigabe", new { ok, changed = true, freigaben = 0 });
    }

    private async Task UpdateOriginalContactSourcesAsync(JsonElement message)
    {
        using var operation = NetworkDeadline(TimeSpan.FromMinutes(10));
        var ownsSync = false;
        try
        {
            lock (serviceGate)
            {
                if (activeSync is not null) throw new InvalidOperationException("native_busy");
                activeSync = operation; graphSync = false; ownsSync = true;
            }
            form.QueueTrayAppearanceRefresh();
            if (OriginalContactAutomation.HasCurrentIntent && !await OriginalContactAutomation.ProbeAsync(wait: true))
                throw new InvalidOperationException("contact_source_account_access_wait");
            var result = await OriginalContactSession.RunAsync(Text(message, "standSha256"), operation.Token,
                RegionalSettings.Read(paths.RegionalSettings)["homeCountry"]?.GetValue<string>() ?? "");
            await form.SendAsync("App.originalKontaktErgebnis", new { requestId = Text(message, "requestId"), ok = true,
                token = result.Offer?.Token ?? "", originalSha256 = result.Offer?.OriginalSha256 ?? Text(message, "standSha256"),
                kontakte = result.Offer?.Contacts, fehlerQuellen = result.SourceErrors, freigaben = result.Grants });
        }
        catch (Exception error)
        {
            await form.SendAsync("App.originalKontaktErgebnis", new { requestId = Text(message, "requestId"), ok = false,
                code = error is InvalidOperationException { Message: "contact_source_wlan_required" } ? "wlan_required" :
                    error is InvalidOperationException { Message: "contact_source_account_access_wait" } ? "account_access_wait" :
                    error is OperationCanceledException ? "cancelled" : "held",
                freigaben = originalContactSession?.GrantCount ?? 0 });
        }
        finally
        {
            if (ownsSync) lock (serviceGate) { if (ReferenceEquals(activeSync, operation)) activeSync = null; }
            form.QueueTrayAppearanceRefresh();
        }
    }
}
