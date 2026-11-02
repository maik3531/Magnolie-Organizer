using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorLocalRestoreSourceTests
{
    internal static async Task RunAsync()
    {
        var fixtures = await LoadGuiFixturesAsync();
        VerifySources(fixtures);
    }

    internal static async Task HistoricalReviewAsync()
    {
        var fixtures = await LoadGuiFixturesAsync();
        foreach (var raw in fixtures) foreach (var fault in new[] { "none", "missing", "changed", "duplicate" })
            await PersonalActorTargetObserverRuntimeTests.RunHistoricalSourceAsync(raw!.AsObject(), fault);
    }

    private static async Task<JsonArray> LoadGuiFixturesAsync()
    {
        var root = TestSource.Root("magnolie-organizer-windows/tests/mcp-notes-historical-source-fixture.js");
        var script = Path.Combine(root, "magnolie-organizer-windows", "tests", "mcp-notes-historical-source-fixture.js");
        var start = new ProcessStartInfo(Environment.GetEnvironmentVariable("NODE") ?? "node") {
            RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        start.ArgumentList.Add(script);
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Existing Node runtime required for source parity.");
        var output = process.StandardOutput.ReadToEndAsync(); var errors = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(40));
        try { await process.WaitForExitAsync(timeout.Token); }
        catch { if (!process.HasExited) process.Kill(entireProcessTree: true); throw; }
        var text = await output; var error = await errors;
        TestAssert.That(process.ExitCode == 0, "Synthetic GUI source fixture failed: " + error);
        var fixtures = JsonNode.Parse(text)!.AsArray(); TestAssert.That(fixtures.Count == 8, "Incomplete shared GUI source matrix.");
        return fixtures;
    }

    private static void VerifySources(JsonArray fixtures)
    {
        foreach (var raw in fixtures) foreach (var fault in new[] { "none", "missing", "duplicate", "foreign", "changed", "hash", "clock", "live", "child", "scope", "save", "source", "owner" })
        {
            var fixture = raw!.DeepClone().AsObject(); var book = fixture["book"]!.AsObject(); var target = fixture["target"]!.AsObject();
            var kind = target["kind"]!.GetValue<string>(); var id = target["id"]!.GetValue<string>();
            if (fault == "child" && kind != "note") continue;
            var trash = book["papierkorb"]!.AsArray(); var piece = trash[0]!.AsObject();
            if (fault == "missing") trash.Clear();
            if (fault == "duplicate") trash.Add(piece.DeepClone());
            if (fault == "foreign") piece["eintrag"]![kind == "note" ? "baumQuelle" : "delegiertAn"] = "foreign";
            if (fault == "changed") piece["eintrag"]!["titel"] = "Changed source";
            if (fault == "hash") target["prior_hash"] = new string('f', 64);
            if (fault == "clock") target["clock"]![0]!["counter"] = target["clock"]![0]!["counter"]!.GetValue<long>() + 1;
            if (fault == "live") book[kind == "note" ? "notizen" : "aufgaben"]!.AsArray().Add(piece["eintrag"]!.DeepClone());
            if (fault == "child") book["personalSync"]!["entities"]!["attachment\0" + id + "\0pending-child"] = new JsonObject { ["state"] = "deleted" };
            var owner = new NativeBookOwnerScope(); owner.SetReady(true); owner.Current("restore-source", true);
            var bookText = book.ToJsonString(); var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(bookText))).ToLowerInvariant();
            owner.RecordSaved("restore-source", true, hash);
            var snapshot = NativeActorBookSnapshot.Capture(() => owner.SaveState("restore-source", true), () => bookText)!;
            var beforeScope = PhoneContentScope.Create(fixture["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()),
                fixture["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()));
            var currentScope = beforeScope.DeepClone().AsObject(); var source = new string('a', 64); var currentOwner = true;
            var observation = new PersonalActorHistoricalRestoreSourceObservation(fixture["peer"]!.GetValue<string>(), fixture["run"]!.GetValue<string>(),
                fixture["format"]!.GetValue<int>(), () => currentOwner, () => source, () => snapshot, () => currentScope);
            if (fault == "scope") currentScope = PhoneContentScope.Create(["foreign"], []);
            if (fault == "save") { owner.RecordSaved("restore-source", true, hash); snapshot = NativeActorBookSnapshot.Capture(() => owner.SaveState("restore-source", true), () => bookText)!; }
            if (fault == "source") source = new string('b', 64);
            if (fault == "owner") currentOwner = false;
            var retained = book.ToJsonString();
            if (fault == "none")
            {
                var result = observation.Observe(fixture["run"]!.GetValue<string>(), target);
                TestAssert.That(result["local_state"]!.GetValue<string>() == "deleted" && result["metadata_matches"]!.GetValue<bool>() &&
                    !result["action_authorized"]!.GetValue<bool>() && result["requires_conflict_choice"]!.GetValue<bool>(), "Local source proof acquired action rights.");
                TestAssert.That(result["local_restore_source"]!["trash_id"]!.GetValue<string>() == piece["id"]!.GetValue<string>() &&
                    result["local_restore_source"]!["sha256"]!.GetValue<string>() == PersonalSyncContract.ProjectionHash(piece), "Local source proof changed its original trash binding.");
                TestAssert.That(!result.ToJsonString().Contains("Synthetic", StringComparison.Ordinal) && !result.ToJsonString().Contains("data:", StringComparison.Ordinal), "Source observation leaked source content.");
            }
            else
            {
                var denied = false;
                try { observation.Observe(fixture["run"]!.GetValue<string>(), target); }
                catch (Exception failure) when (failure is InvalidOperationException or InvalidDataException or ArgumentException) { denied = true; }
                TestAssert.That(denied, "Invalid source observation survived: " + kind + "/" + fault);
            }
            TestAssert.That(book.ToJsonString() == retained, "Source observation mutated original book.");
        }
    }
}
