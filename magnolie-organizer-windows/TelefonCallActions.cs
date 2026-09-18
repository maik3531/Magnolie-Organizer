using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Runtime-only tickets. No caller data, profile writes, or usable tickets after restart.
internal sealed class TelefonCallActions
{
    internal sealed record Ticket(string PeerId, string Identity, object Connection, string CallRef,
        long Revision, string Action, long Expires);
    private readonly Dictionary<string, Ticket> tickets = new(StringComparer.Ordinal);
    private readonly Func<long> clock;
    internal TelefonCallActions(Func<long>? clock = null) => this.clock = clock ?? (() => Environment.TickCount64);
    internal static bool IsRinging(JsonObject call) => call["state"]?.GetValue<string>() == "ringing" &&
        call["direction"]?.GetValue<string>() == "incoming";
    internal string Issue(string peer, string identity, object connection, JsonObject call, string action)
    {
        if (!IsRinging(call) || action is not ("answer" or "reject")) throw new InvalidOperationException();
        foreach (var key in tickets.Where(item => item.Value.Expires <= clock()).Select(item => item.Key).ToArray()) tickets.Remove(key);
        while (tickets.Count >= 64) tickets.Remove(tickets.Keys.First());
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        tickets[token] = new(peer, identity, connection, call["call_ref"]!.GetValue<string>(),
            call["revision"]!.GetValue<long>(), action, clock() + 60_000);
        return token;
    }
    internal Ticket? Take(string token) => tickets.Remove(token, out var ticket) && ticket.Expires > clock() ? ticket : null;
    internal void Clear() => tickets.Clear();
    internal void Invalidate(string peer, string callRef)
    {
        foreach (var key in tickets.Where(item => item.Value.PeerId == peer && item.Value.CallRef == callRef).Select(item => item.Key).ToArray()) tickets.Remove(key);
    }
}
