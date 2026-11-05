using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Local receiving rights and the saved-book owner are prerequisites. A
    // matched remote preference is never itself a filesystem permission.
    internal NativeMediaPreferences ProjectNativeMediaSharedPreferences(string peerId, byte[] expectedPublic,
        JsonObject expectedBody, Action requireMatchedNativeBook)
    {
        lock (gate)
        {
            void Intent()
            {
                requireMatchedNativeBook();
                if (!JsonNode.DeepEquals(ReadNativeMediaSharedSettings(peerId, expectedPublic), expectedBody))
                    throw DeviceFileControl.Error("media_shared_projection_changed");
            }
            Intent();
            var receiving = ReadNativeMediaReceiveConsent(peerId);
            // Freeze only the existing locally confirmed legacy choice (or a
            // new FALSE default), before native policy projection changes its
            // old carrier. A remote enable can never turn this migration TRUE.
            if (!receiving.Explicit)
                receiving = ChangeNativeMediaReceiveConsent(peerId, receiving.Version, receiving.Granted);
            void Current()
            {
                Intent();
                if (ReadNativeMediaReceiveConsent(peerId) != receiving)
                    throw DeviceFileControl.Error("media_shared_local_receiving_changed");
            }
            Current();
            var values = MediaSyncSettings.Effective(expectedBody);
            var enabled = receiving.Granted && values["enabled"]!.GetValue<bool>();
            var photos = enabled && values["photos_enabled"]!.GetValue<bool>();
            var videos = enabled && values["videos_enabled"]!.GetValue<bool>();
            var automatic = enabled && (photos || videos) && values["auto_mode"]!.GetValue<string>() == "wifi";
            var deletions = enabled && !values["skip_deletions"]!.GetValue<bool>();
            var previous = ReadNativeMediaPreferences(peerId);
            var next = SetNativeMediaPreferences(peerId, previous.Version, photos, videos, automatic,
                deleteFromPhone: deletions, deleteFromDesktop: deletions, nativeGuard: Current);
            Current();
            if (ReadNativeMediaPreferences(peerId) != next) throw DeviceFileControl.Error("media_shared_projection_not_proven");
            return next;
        }
    }
}
