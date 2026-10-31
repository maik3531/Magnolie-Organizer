using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ManagedEasSourceFolderTests
{
    private const string Profile = "11111111-1111-4111-8111-111111111111";
    private const string Ticket = "22222222-2222-4222-8222-222222222222";
    private static JsonObject Row() => new()
    {
        ["protocol"] = 1, ["version"] = 1, ["account_id"] = "a1", ["folder_id"] = "f1", ["kind"] = "contacts", ["name"] = "Synthetic contacts",
        ["source_identity"] = new string('b', 64), ["revision"] = new string('c', 64), ["selected"] = false, ["target_id"] = null,
        ["provider_sync_confirmed"] = false
    };
    private static JsonObject List() => new()
    {
        ["id"] = new string('a', 32), ["ok"] = true, ["protocol"] = 1, ["version"] = 1, ["profile_id"] = Profile,
        ["complete"] = true, ["folders"] = new JsonArray(Row())
    };
    private static JsonObject Report(string state)
    {
        var row = Row(); row.Remove("name");
        row["id"] = new string('a', 32); row["ok"] = true; row["profile_id"] = Profile; row["state"] = state;
        if (state == "prepared") row["token"] = Ticket;
        if (state == "selected") { row["selected"] = true; row["target_id"] = "native-target"; row["revision"] = new string('d', 64); }
        return row;
    }

    internal static async Task RunAsync()
    {
        var source = ManagedEasSourceFolderContract.ReadList(List()).Single();
        TestAssert.That(source.Uid == $"managed-eas:{Profile}:{new string('b', 64)}" && !source.Selected && source.TargetId is null,
            "Discovered EAS folder was misrepresented as a DAV or ready data source.");
        var prepared = ManagedEasSourceFolderContract.ReadPrepared(Report("prepared"), source);
        TestAssert.That(prepared.Token == Ticket && ManagedEasSourceFolderContract.ReadCurrent(Report("current"), source).Uid == source.Uid,
            "Prepared/current EAS source identity changed.");
        var selected = ManagedEasSourceFolderContract.ReadSelected(Report("selected"), source);
        TestAssert.That(selected.Selected && selected.TargetId == "native-target" && selected.Uid == source.Uid,
            "Folder materialization redefined its remote source identity.");

        foreach (var field in new[] { "profile_id", "account_id", "folder_id", "kind", "source_identity", "revision", "provider_sync_confirmed", "state", "token", "extra" })
        {
            var value = Report("prepared");
            if (field == "profile_id") value[field] = "33333333-3333-4333-8333-333333333333";
            else if (field == "provider_sync_confirmed") value[field] = true;
            else if (field == "source_identity" || field == "revision") value[field] = new string('f', 64);
            else if (field == "token") value[field] = "not-a-ticket";
            else value[field] = "other";
            TestAssert.Throws<InvalidDataException>(() => ManagedEasSourceFolderContract.ReadPrepared(value, source), "Rejected source property was accepted: " + field);
        }
        foreach (var field in new[] { "complete", "duplicate", "provider_sync_confirmed", "target_id", "kind", "name", "extra" })
        {
            var value = List(); var row = value["folders"]![0]!.AsObject();
            if (field == "complete") value[field] = false;
            else if (field == "duplicate") value["folders"]!.AsArray().Add(row.DeepClone());
            else if (field == "provider_sync_confirmed") row[field] = true;
            else if (field == "target_id") row[field] = "orphan-target";
            else if (field == "name") row[field] = "Malformed\uD800";
            else row[field] = "unsupported";
            TestAssert.Throws<InvalidDataException>(() => ManagedEasSourceFolderContract.ReadList(value), "Invalid EAS source catalog was accepted: " + field);
        }
        var missingTarget = Report("selected"); missingTarget["target_id"] = null;
        TestAssert.Throws<InvalidDataException>(() => ManagedEasSourceFolderContract.ReadSelected(missingTarget, source), "Missing native target was accepted.");
        var replacement = Report("selected"); replacement["target_id"] = "replacement";
        TestAssert.Throws<InvalidDataException>(() => ManagedEasSourceFolderContract.ReadSelected(replacement, selected), "An existing target was silently replaced.");

        var calls = new List<JsonObject>();
        var client = new ManagedEasSourceFolderClient((request, token) =>
        {
            token.ThrowIfCancellationRequested(); calls.Add(request.DeepClone().AsObject());
            var response = request["op"]!.GetValue<string>() switch
            {
                "eas-source-list" => List(), "eas-source-inspect" => Report("current"), "eas-source-prepare" => Report("prepared"),
                "eas-source-enable" => Report("selected"), _ => throw new InvalidDataException()
            };
            return Task.FromResult(response);
        });
        var read = (await client.ReadAsync(CancellationToken.None)).Single();
        await client.InspectAsync(read, CancellationToken.None);
        var ticket = await client.PrepareAsync(read, CancellationToken.None);
        await client.EnableAsync(ticket, CancellationToken.None);
        TestAssert.That(calls.Count == 4 && calls[0].Count == 1 && calls[1]["account_id"]!.GetValue<string>() == "a1" &&
            calls[1]["folder_id"]!.GetValue<string>() == "f1" && calls[3]["token"]!.GetValue<string>() == Ticket &&
            calls[3]["revision"]!.GetValue<string>() == source.Revision && calls.All(call => !call.ContainsKey("password")),
            "Native EAS source setup requests lost scope or transmitted credentials.");
    }
}
