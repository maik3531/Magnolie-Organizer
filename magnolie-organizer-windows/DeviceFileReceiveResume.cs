using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed record NativeMediaResumeSelection(TelefonStore Owner, string PeerId, string JobId, string Version,
        string MediaType, string DestinationVersion, DeviceFileManifest Manifest)
    {
        internal bool GrantsResumeAuthority => false;
    }

    // Read exact existing history only: no directory open, key bootstrap, new
    // job, reservation, chunk grant or claim that staged bytes were recovered.
    internal NativeMediaResumeSelection SelectNativeMediaResume(string peerId, string jobId, string expectedVersion)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var head = ReceiveHeads(db, null, scope).SingleOrDefault(head => head.JobId == jobId);
            if (head is null || head.Version != expectedVersion) throw DeviceFileControl.Error("file_receive_original_history_required");
            using var document = JsonDocument.Parse(head.Body["manifest"]!.ToJsonString());
            var manifest = DeviceFileManifest.Parse(document.RootElement);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_history_binding_changed");
            return new(this, peerId, jobId, head.Version, TelefonMessagingContract.String(head.Body, "media_type"),
                TelefonMessagingContract.String(head.Body, "destination_version"), manifest);
        }
    }

    internal void RequireNativeMediaResumeSelection(NativeMediaResumeSelection selected)
    {
        if (!ReferenceEquals(selected.Owner, this)) throw DeviceFileControl.Error("file_receive_foreign_resume_selection");
        var current = SelectNativeMediaResume(selected.PeerId, selected.JobId, selected.Version);
        if (current.MediaType != selected.MediaType || current.DestinationVersion != selected.DestinationVersion ||
            current.Manifest.Fingerprint != selected.Manifest.Fingerprint)
            throw DeviceFileControl.Error("file_receive_original_history_changed");
    }

    internal NativeMediaResumeSelection RecordNativeSourceResumeHistory(NativeMediaResumeSelection selected,
        DeviceFileResumeHistory remote, Action current)
    {
        lock (gate)
        {
            RequireNativeMediaResumeSelection(selected); current();
            if (remote.MediaType != selected.MediaType || remote.SourceId != selected.Manifest.SourceId ||
                remote.TransferId != selected.Manifest.TransferId || remote.ManifestSha256 != selected.Manifest.Fingerprint)
                throw DeviceFileControl.Error("file_receive_original_source_history_changed");
            var scope = MediaPreferenceScope(selected.PeerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var head = ReceiveHeads(db, null, scope).Single(value => value.JobId == selected.JobId);
            var body = head.Body.DeepClone().AsObject();
            body["source_job"] = new JsonObject { ["job_id"] = remote.JobId, ["job_version"] = remote.JobVersion };
            var saved = SaveReceiveHead(selected.PeerId, selected.JobId, selected.Version, body, current);
            return selected with { Version = saved.Version };
        }
    }
}
