using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    // Native-only preparation hint. No renderer action projects or consumes it
    // until actual runtime activation and live-owner retirement are implemented.
    internal string NativeDestinationAdmissionVersion(string peerId, string kind)
    {
        if (kind is not ("images" or "video")) throw DeviceFileControl.Error("file_media_type_invalid");
        var connection = NativeMediaOnlineConnection(peerId);
        return connection.NativeMediaSharedUiVersion(new JsonObject {
            ["choice"] = NativeDestinationChoiceVersion(peerId, kind, connection),
            ["selected_witness"] = store.ReadNativeMediaSelectionWitness(peerId, kind)?.Stamp,
            ["opposite_witness"] = store.ReadNativeMediaSelectionWitness(peerId, kind == "images" ? "video" : "images")?.Stamp });
    }

    internal sealed class NativeDestinationAdmissionContext
    {
        private readonly TelefonCoordinator coordinator;
        private readonly TelefonConnection connection;
        private readonly NativeMediaBookPermit book;
        private readonly Action control;
        private readonly TelefonStore.NativeMediaSelectionContextOwner selected, opposite;
        private readonly string version, originalReadset;
        private readonly System.Diagnostics.Stopwatch timer = System.Diagnostics.Stopwatch.StartNew();
        private int writeState;
        private bool revoked;
        internal string PeerId { get; }
        internal string Kind { get; }
        internal string? ExpectedStamp => selected.Snapshot?.Stamp;

        internal NativeDestinationAdmissionContext(TelefonCoordinator coordinator, string peerId, string kind, string version)
        {
            this.coordinator = coordinator; PeerId = peerId; Kind = kind; this.version = version;
            connection = coordinator.NativeMediaOnlineConnection(peerId);
            control = connection.CaptureNativeDestinationContext();
            book = coordinator.NativeMediaLocalBookPermit();
            selected = new(coordinator.store, peerId, kind);
            opposite = new(coordinator.store, peerId, kind == "images" ? "video" : "images");
            originalReadset = coordinator.NativeDestinationChoiceVersion(peerId, kind, connection);
            RequireForDialog();
        }

        private void CurrentReadset(bool full = true)
        {
            try
            {
                if (revoked) throw DeviceFileControl.Error("file_destination_admission_context_retired");
                book.Require(); control(); coordinator.store.RequireNativeMediaStorageKey();
                if (timer.Elapsed >= TimeSpan.FromSeconds(60) ||
                    !ReferenceEquals(connection, coordinator.NativeMediaOnlineConnection(PeerId)))
                    throw DeviceFileControl.Error("file_destination_admission_context_retired");
                if (Volatile.Read(ref coordinator.nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
                if (full)
                {
                    if (coordinator.NativeDestinationChoiceVersion(PeerId, Kind, connection) != originalReadset)
                        throw DeviceFileControl.Error("file_destination_admission_context_retired");
                    opposite.Require();
                }
            }
            catch { revoked = true; throw; }
        }

        internal void RequireForDialog()
        {
            try
            {
                if (Volatile.Read(ref writeState) != 0) throw DeviceFileControl.Error("file_destination_admission_context_retired");
                CurrentReadset(); selected.Require();
                if (!connection.NativeMediaUiMetadataAvailable(Kind == "video")) throw DeviceFileControl.Error("file_media_native_peer_unavailable");
                coordinator.RequireNativeMediaUiDestinationConsent(PeerId);
                if (coordinator.NativeDestinationAdmissionVersion(PeerId, Kind) != version)
                    throw DeviceFileControl.Error("file_destination_admission_context_retired");
                CurrentReadset();
            }
            catch { revoked = true; throw; }
        }

        internal void BeginWrite(TelefonStore actualStore)
        {
            RequireForDialog();
            if (!ReferenceEquals(actualStore, coordinator.store) || Interlocked.CompareExchange(ref writeState, 1, 0) != 0)
            { revoked = true; throw DeviceFileControl.Error("file_destination_admission_context_retired"); }
        }
        internal void RequireForWrite()
        {
            if (Volatile.Read(ref writeState) != 1) throw DeviceFileControl.Error("file_destination_admission_context_retired");
            // The selected witness now has our own pending native file. Its
            // ORIGINAL head is separately compared by the writer's SQL CAS;
            // Book/control/deadline stay live at every IO checkpoint; the full
            // original readset is rechecked at write/commit boundaries while
            // native settings mutations are serialized by the store gate.
            CurrentReadset(full: false);
        }
        internal void RequireFullReadsetForWrite() { RequireForWrite(); CurrentReadset(); }
        internal void EndWrite() { revoked = true; Volatile.Write(ref writeState, 2); }
    }

    internal (NativeMediaSelectionWitness Selection, NativeMediaDestinationAdmission Admission)? AdmitNativeMediaDestination(
        string peerId, string kind, string version, Func<Action, DeviceFileNativeDirectory?> pickNative)
    {
        ArgumentNullException.ThrowIfNull(pickNative);
        if (kind is not ("images" or "video")) throw DeviceFileControl.Error("file_media_type_invalid");
        if (Interlocked.CompareExchange(ref nativeMediaCollectionDialog, 1, 0) != 0)
            throw DeviceFileControl.Error("media_collection_native_choice_pending");
        NativeDestinationAdmissionContext? context = null;
        try
        {
            context = new NativeDestinationAdmissionContext(this, peerId, kind, version);
            using var picked = pickNative(context.RequireForDialog);
            context.RequireForDialog();
            if (picked is null) return null;
            return store.AdmitNativeMediaDestination(context, picked);
        }
        finally { context?.EndWrite(); Volatile.Write(ref nativeMediaCollectionDialog, 0); }
    }
}
