using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalController
{
    private Work DiscoverOne()
    {
        // Serial deferred worker/book lane only. Scan at most one private source
        // per turn, with a rotating cursor. Never enumerate journal directories.
        Source source; NotesOriginalNegotiation protocol;
        lock (gate)
        {
            RequireActive();
            if (sources.Length == 0) return new("waiting");
            source = sources[discoveryCursor++ % sources.Length];
            if (discoveryCursor == int.MaxValue) discoveryCursor = 0;
            if (!peers.TryGetValue(source.Pins, out protocol!) || !protocol.HasOffer ||
                physical.ContainsKey((source.Binding, source.Id)) || retired.ContainsKey((source.Binding, source.Id)) || owners.Count(pair => pair.Key.Pins == source.Pins) >= perPeer)
                return new("waiting");
        }
        try
        {
            protocol.RequireCurrent();
            var record = requests.LoadPhysical(source.Binding, source.Id);
            if (record is null) return new("waiting");
            var request = record["request"]!.DeepClone().AsObject();
            var key = NotesOriginalSchema.Hash(request);
            var owner = new Owner(source, protocol, request);
            // Presence of unreadable/conflicting genuine ACK history is a hold,
            // never permission to downgrade into unconfirmed local recovery.
            var saved = outcomes.LoadHeld(key);
            if (saved is not null)
            {
                owner.History = outcomes.ReadOnlyQuery(key, consent, protocol);
                owner.AckKey = key;
            }
            else
            {
                if (NotesOriginalSchema.Text(record, "state") != "request_pending")
                    throw new InvalidOperationException("notes_controller_settled_ack_history_required");
                owner.Unconfirmed = requests.ReadOnlyQuery(source.Binding, source.Id, consent, protocol);
            }
            Add(owner);
            return new("query", (object?)owner.History ?? owner.Unconfirmed, owner.Id);
        }
        catch (Exception error) when (Expected(error))
        { Hold("discovery"); return new("held"); } // That physical disk slot remains held; other sources can proceed.
    }
}
