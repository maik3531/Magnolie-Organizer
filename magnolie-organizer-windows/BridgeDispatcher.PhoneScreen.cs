using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private async Task PhoneScreenActionAsync(JsonElement request)
    {
        string command = Text(request, "cmd"), requestId = Text(request, "requestId");
        // Browser input is only a request for the native dialog, never a grant.
        bool included = TelefonCoordinator.NativeScreenChecked && currentPlainTextAvailable && !restoreInProgress && !disposed;
        bool ok = command == "telefon_screen_stand";
        if (included && command == "telefon_screen_stop") { form.StopPhoneScreen(); ok = true; }
        if (included && command == "telefon_screen_start" && Text(request, "peer") is { } id && TelefonProtocolContract.IsUuidV4(id) &&
            telefon.ScreenProbeFor(id) is { } probe && telefon.Peers.FirstOrDefault(value => value.Id == id && value.State == "paired") is { } peer &&
            NativeActorBookSource() is { } originalProfile)
        {
            void Current()
            {
                telefon.RequireScreenParent(id, probe.Parent);
                if (NativeActorBookSource() != originalProfile) throw new InvalidOperationException("screen_original_profile_lost");
            }
            try { ok = form.ConfirmPhoneScreen(probe, peer.Name, Current, () => ReferenceEquals(telefon.ScreenProbeFor(id), probe)); }
            catch (Exception error) when (error is InvalidOperationException or IOException or UnauthorizedAccessException) { }
        }
        var peers = included ? telefon.Peers.Where(peer => peer.State == "paired" && telefon.ScreenProbeFor(peer.Id) is not null)
            .Select(peer => new { id = peer.Id, name = peer.Name }).ToArray() : [];
        await form.SendAsync("App.kdeMedien", new { ok, requestId, screen = new { included, active = form.PhoneScreenActive, busy = form.PhoneScreenBusy(), peers } });
    }
}
