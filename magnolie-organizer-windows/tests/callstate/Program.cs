using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

long now = 1000;
var actions = new TelefonCallActions(() => now);
var call = new JsonObject { ["call_ref"] = "22222222-2222-4222-8222-222222222222",
    ["revision"] = 1L, ["state"] = "ringing", ["direction"] = "incoming", ["number"] = "+12025550123" };
var connection = new object();
var assertions = 0;
void Check(bool result) { assertions++; if (!result) throw new Exception("Call-state assertion " + assertions); }
string Issue(string action) => actions.Issue("synthetic-peer", "synthetic-public-identity", connection, call, action);
var token = Issue("answer");
Check(token.Length == 64 && !token.Contains("12025550123"));
var ticket = actions.Take(token)!;
Check(ticket.PeerId == "synthetic-peer" && ticket.Identity == "synthetic-public-identity" && ReferenceEquals(ticket.Connection, connection));
Check(ticket.CallRef == call["call_ref"]!.GetValue<string>() && ticket.Revision == 1 && ticket.Action == "answer");
Check(!ticket.ToString().Contains("12025550123"));
Check(actions.Take(token) is null);
var answer = Issue("answer"); var reject = Issue("reject");
actions.Invalidate("synthetic-peer", ticket.CallRef);
Check(actions.Take(answer) is null && actions.Take(reject) is null);
token = Issue("reject"); now += 60_000;
Check(actions.Take(token) is null);
token = Issue("answer");
Check(new TelefonCallActions().Take(token) is null);
foreach (var direction in new[] { "incoming", "outgoing", "unknown" })
foreach (var state in new[] { "ringing", "offhook", "idle" })
{
    call["direction"] = direction; call["state"] = state;
    Check(TelefonCallActions.IsRinging(call) == (direction == "incoming" && state == "ringing"));
    if (!TelefonCallActions.IsRinging(call))
    {
        try { Issue("answer"); throw new Exception("unsafe direction accepted"); }
        catch (InvalidOperationException) { assertions++; }
    }
}
Console.WriteLine($"Call-state C# probe: {assertions} assertions passed; no native phone or profile access.");
