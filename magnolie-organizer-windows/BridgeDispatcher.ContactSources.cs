using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private ContactSourceNativeSession? originalContactSession;
    private ContactSourceNativeSession OriginalContactSession => LazyInitializer.EnsureInitialized(ref originalContactSession, () => new(
        NativeActorBook, NativeActorSavedBook, NextcloudSettings, OriginalContactCommit,
        OriginalContactWlanAvailable, _ => CreateSnapshot(SnapshotReason.PreContact)));

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
            var changed = await OriginalContactSession.ConfigureAsync((sources, selected, token) =>
                ContactSourceApprovalDialog.ChooseAsync(form, sources, selected, T, token), operation.Token);
            await form.SendAsync("App.originalKontaktFreigabe", new { requestId = Text(message, "requestId"), ok = true,
                changed, freigaben = OriginalContactSession.GrantCount });
        }
        catch (Exception)
        {
            await form.SendAsync("App.originalKontaktFreigabe", new { requestId = Text(message, "requestId"), ok = false,
                changed = false, freigaben = originalContactSession?.GrantCount ?? 0 });
        }
    }

    private async Task RevokeOriginalContactSourcesAsync()
    {
        originalContactSession?.Revoke();
        await form.SendAsync("App.originalKontaktFreigabe", new { ok = true, changed = true, freigaben = 0 });
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
