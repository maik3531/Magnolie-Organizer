namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private int nativeMediaWorker;

    // Explicit manual native admission only. No constructor timer/automatic
    // startup, browser permission conversion or saved-video intent promotion.
    internal async Task<TelefonConnection.NativeMediaAlbumOutcome> SynchronizeNativeMediaAlbumFromSavedBookAsync(string peerId,
        string sourceVersion, string catalogId, string albumId, bool desktopChoice, string mediaType = "images", CancellationToken token = default)
    {
        if (Interlocked.CompareExchange(ref nativeMediaWorker, 1, 0) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        try
        {
            var snapshot = NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required");
            var permit = NativeMediaBookPermit.Capture(snapshot, NativeSavedBook);
            TelefonConnection connection;
            lock (gate)
            {
                if (disposed || !online.TryGetValue(peerId, out connection!)) throw DeviceFileControl.Error("file_media_native_peer_offline");
            }
            // Neither this callback nor any store IO takes the coordinator gate.
            // The connection's current native control owner detects disconnection,
            // pairing/grant/data epoch/destination changes on every actual IO.
            return await connection.SynchronizeNativeMediaAlbumAsync(sourceVersion, catalogId, albumId, desktopChoice,
                mediaType, token, permit.ReplacementConsent, permit.Require);
        }
        finally { Interlocked.Exchange(ref nativeMediaWorker, 0); }
    }
}
