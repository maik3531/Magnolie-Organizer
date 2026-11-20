using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private async Task DesktopWebcamActionAsync(JsonElement request)
    {
        string command = Text(request, "cmd"), requestId = Text(request, "requestId");
        bool included = false, ok = command == "telefon_webcam_stand";
        string phase = "off";
        string? run = null;
        object peers = Array.Empty<object>();
#if MAGNOLIE_PHONE_CAMERA
        var profile = MainForm.NativeWebcamChecked ? NativeActorBookSource() : null;
        if (profile is not null)
        {
            included = true;
            if (command == "telefon_webcam_stop") ok = form.StopDesktopWebcam(Text(request, "run"));
            if (command == "telefon_webcam_start" && TelefonProtocolContract.IsUuidV4(Text(request, "peer")) &&
                telefon.SelectDesktopWebcam(Text(request, "peer")) is { } selected)
            {
                void RequireProfile()
                {
                    if (NativeActorBookSource() != profile) throw new InvalidOperationException("webcam_original_profile_lost");
                }
                // Start only if the native dialog explicitly approves this
                // exact choice; never read mute/front/consent from web text.
                try { ok = form.ConfirmDesktopWebcam(selected, RequireProfile); }
                catch (Exception error) when (error is InvalidOperationException or IOException or UnauthorizedAccessException) { }
            }
            (phase, run) = form.DesktopWebcamStatus;
            if (phase == "off") peers = telefon.Peers.Where(peer => telefon.SelectDesktopWebcam(peer.Id) is not null)
                .Select(peer => new { id = peer.Id, name = peer.Name }).ToArray();
        }
#endif
        await form.SendAsync("App.kdeMedien", new { ok, requestId, webcam = new { included, phase, run, peers } });
    }
}
