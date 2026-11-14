using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Reserved native FS1 only. No raw JSON/outbox/Baum1/mailbox admission and no
// startup registration. Native policy/body callbacks run outside the tree gate.
internal sealed partial class MagnolienbaumCoordinator
{
    internal Task<bool> SendNotesProbeAsync(NotesOriginalNegotiation protocol, Func<bool> networkAllowed, CancellationToken cancellation = default) =>
        SendNotesNativeAsync(protocol, protocol.Probe, networkAllowed, cancellation);
    internal Task<bool> SendNotesRequestAsync(NotesOriginalPendingResult pending, NotesOriginalRequestIntents.FreshRequest intention,
        NotesOriginalNegotiation protocol, Func<bool> networkAllowed, CancellationToken cancellation = default) =>
        SendNotesNativeAsync(protocol, () => intention.RequireFor(pending, protocol), networkAllowed, cancellation);
    internal Task<bool> SendNotesQueryAsync(NotesOriginalRequestIntents.UnconfirmedQuery query, NotesOriginalNegotiation protocol,
        Func<bool> networkAllowed, CancellationToken cancellation = default) =>
        SendNotesNativeAsync(protocol, () => query.Request(protocol), networkAllowed, cancellation);
    internal Task<bool> SendNotesQueryAsync(NotesOriginalSavedAckIntents.HistoryQuery query, NotesOriginalNegotiation protocol,
        Func<bool> networkAllowed, CancellationToken cancellation = default) =>
        SendNotesNativeAsync(protocol, () => query.Request(protocol), networkAllowed, cancellation);
    internal Task<bool> SendNotesSavedAckAsync(NotesOriginalSavedAckIntents.SavedAck ack, NotesOriginalNegotiation protocol,
        Func<bool> networkAllowed, CancellationToken cancellation = default) =>
        SendNotesNativeAsync(protocol, () => ack.RequireFor(protocol), networkAllowed, cancellation);
    internal Task<bool> SendNotesSavedAckAsync(NotesOriginalSavedAckIntents.RestoredAck ack, NotesOriginalNegotiation protocol,
        Func<bool> networkAllowed, CancellationToken cancellation = default) =>
        SendNotesNativeAsync(protocol, () => ack.RequireFor(protocol), networkAllowed, cancellation);

    private sealed record NotesRoute(JsonObject Own, JsonObject Peer, long Generation, CancellationToken Stop);
    private NotesRoute? CaptureNotesRoute((NotesPins Peer, NotesPins Own) pins, long? expectedGeneration = null)
    {
        lock (gate)
        {
            var peer = Partner(pins.Peer.Id);
            if (disposed || outboxPaused || !Boolean(state, "an") || String(state, "geheim").Length == 0 || peer is null || !Boolean(peer, "bestaetigt") ||
                !Boolean(peer, "vertraut") || !Boolean(peer, "kontaktSync") ||
                new NotesPins(String(peer, "kennung"), String(peer, "oeffentlich")) != pins.Peer ||
                new NotesPins(String(state, "kennung"), String(state, "oeffentlich")) != pins.Own ||
                expectedGeneration is not null && expectedGeneration != notesReceiveGeneration)
                return null;
            return new(new JsonObject { ["kennung"] = state["kennung"]!.DeepClone(), ["oeffentlich"] = state["oeffentlich"]!.DeepClone(),
                ["geheim"] = state["geheim"]!.DeepClone() }, peer.DeepClone().AsObject(), notesReceiveGeneration, outboxCancellation.Token);
        }
    }

    private async Task<bool> SendNotesNativeAsync(NotesOriginalNegotiation protocol, Func<JsonObject> captureBody,
        Func<bool> networkAllowed, CancellationToken cancellation)
    {
        ArgumentNullException.ThrowIfNull(networkAllowed);
        cancellation.ThrowIfCancellationRequested();
        try
        {
            if (!networkAllowed()) return false; // Quiet native WLAN/connection wait.
            var pins = protocol.NativeProbePins(); var route = CaptureNotesRoute(pins);
            if (route is null) return false;
            var body = captureBody();
            if (MagnolienbaumCrypto.Canonical(body).Length > 256 * 1024) return false;
            var hash = NotesOriginalSchema.Hash(body);
            using var bounded = CancellationTokenSource.CreateLinkedTokenSource(cancellation, route.Stop);
            bounded.CancelAfter(TimeSpan.FromSeconds(8));
            void Current()
            {
                bounded.Token.ThrowIfCancellationRequested();
                var current = CaptureNotesRoute(pins, route.Generation);
                if (!networkAllowed() || protocol.NativeProbePins() != pins || current is null || String(current.Own, "geheim") != String(route.Own, "geheim") ||
                    NotesOriginalSchema.Hash(captureBody()) != hash)
                    throw new InvalidOperationException("notes_original_native_send_context_changed");
            }
            foreach (var endpoint in Endpoints(route.Peer))
            {
                try
                {
                    Current();
                    using var start = MagnolienbaumFs1.BuildStart(route.Own, route.Peer);
                    var basis = BuildUri(endpoint.Host, endpoint.Port, "/");
                    var response = await PostAsync(new Uri(basis, "/magnolie/v2/sitzung"), start.Message, bounded.Token).ConfigureAwait(false);
                    Current();
                    using var session = MagnolienbaumFs1.OpenResponse(route.Own, route.Peer, start.Message, response, start.EphemeralPrivate);
                    var envelope = MagnolienbaumFs1.BuildEnvelope(session, pins.Own.Id, pins.Peer.Id, body,
                        Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)));
                    Current();
                    var receipt = await PostAsync(new Uri(basis, "/magnolie/v2/nachricht"), envelope, bounded.Token).ConfigureAwait(false);
                    Current();
                    if (MagnolienbaumFs1.VerifyAcknowledgement(session, envelope, receipt)) return true;
                }
                catch (HttpRequestException) { } // Same paired endpoint alternatives only; no legacy/mailbox fallback.
                catch (JsonException) { }
                catch (InvalidDataException) { }
            }
            return false;
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { return false; }
        catch (InvalidOperationException) { return false; }
        catch (CryptographicException) { return false; }
        catch (IOException) { return false; }
        catch (ArgumentException) { return false; }
    } // A true return means authenticated transport delivery, never SaveACK settlement.
}
