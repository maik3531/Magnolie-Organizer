using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed class NativeMediaBookPermit
{
    private readonly NativeBookSaveState expected;
    private readonly Func<NativeBookSaveState?> current;
    private readonly object gate = new(); private bool revoked;
    internal bool TrashEnabled { get; }
    internal int RetentionDays { get; }
    internal NativeMediaReplacementConsent? ReplacementConsent { get; }

    private NativeMediaBookPermit(NativeActorBookSnapshot snapshot, Func<NativeBookSaveState?> currentSaved)
    {
        expected = snapshot.SavedBook; current = currentSaved; Require();
        using var document = JsonDocument.Parse(snapshot.Text);
        if (!document.RootElement.TryGetProperty("einstellungen", out var settings) || settings.ValueKind != JsonValueKind.Object ||
            !settings.TryGetProperty("papierkorb", out var trash) || trash.ValueKind != JsonValueKind.Object ||
            !trash.TryGetProperty("an", out var enabled) || enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
            !trash.TryGetProperty("tage", out var days) || !days.TryGetInt32(out var retention) || retention is not (0 or 7 or 30 or 90 or 365))
            throw DeviceFileControl.Error("file_media_saved_trash_setting_required");
        TrashEnabled = enabled.GetBoolean(); RetentionDays = retention;
        // OFF is NOT permission for permanent replacement/deletion. That needs
        // the separate exact native confirmation; this adapter only preserves.
        ReplacementConsent = TrashEnabled ? new(() => { Require(); return true; }) : null;
        Require();
    }

    internal static NativeMediaBookPermit Capture(NativeActorBookSnapshot snapshot, Func<NativeBookSaveState?> currentSaved)
        => new(snapshot, currentSaved);

    internal void Require()
    {
        lock (gate)
        {
            try { if (revoked || current() != expected) throw DeviceFileControl.Error("file_media_current_saved_book_required"); }
            catch { revoked = true; throw; }
        }
    }
}

internal sealed partial class TelefonStore
{
    internal sealed partial class NativeMediaReceiveJob
    {
        private Action? nativeWorkerGuard;
        internal void GuardNativeMediaWorker(Action require)
        {
            lock (jobGate) { Current(); require(); nativeWorkerGuard = require; }
        }
    }
}
