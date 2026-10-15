using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeMediaTests
{
    internal static Task RunAsync()
    {
        RegisteredChoices();
        var state = new KdeMediaState();
        var requests = state.Accept(JsonNode.Parse("""{"playerList":["Music"]}""")!.AsObject());
        TestAssert.That(requests.Count == 1 && requests[0]["requestNowPlaying"]!.GetValue<bool>(), "Player bootstrap missing.");
        var token = state.Snapshot("device")["token"]!.GetValue<string>();
        state.Accept(JsonNode.Parse("""{"player":"Music","title":"Track","canSeek":true,"volume":50}""")!.AsObject());
        TestAssert.That(state.Command(token, "Music", "seek", -1000000)["Seek"]!.GetValue<long>() == -1000000, "Seek units lost.");
        foreach (var input in new[] { """{"playerList":["same","same"]}""", """{"player":"Music","volume":true}""",
            """{"player":"Music","canSeek":1}""", """{"player":"Music","volume":101}""" })
        {
            var before = state.Snapshot("device").ToJsonString();
            TestAssert.Throws<InvalidDataException>(() => state.Accept(JsonNode.Parse(input)!.AsObject()), "Malformed metadata accepted.");
            TestAssert.That(state.Snapshot("device").ToJsonString() == before, "Malformed packet damaged valid state.");
        }
        state.Accept(new JsonObject { ["player"] = "Music", ["title"] = string.Concat(Enumerable.Repeat("😀", 1000)), ["isPlaying"] = true });
        TestAssert.That(state.Snapshot("device")["players"]![0]!["title"]!.GetValue<string>() == string.Concat(Enumerable.Repeat("😀", 32)), "Unicode metadata not bounded.");
        state.Accept(JsonNode.Parse("""{"playerList":[]}""")!.AsObject());
        state.Accept(JsonNode.Parse("""{"player":"Music","title":"Late"}""")!.AsObject());
        TestAssert.That(state.Snapshot("device")["players"]!.AsArray().Count == 0, "Late update resurrected a player.");
        TestAssert.Throws<InvalidDataException>(() => state.Command(token, "Music", "Play", null), "Removed player remained actionable.");
        state.Accept(JsonNode.Parse("""{"playerList":["Music"],"player":"Music","canSeek":false}""")!.AsObject());
        TestAssert.Throws<InvalidDataException>(() => state.Command(token, "Music", "Play", null), "Old list token remained valid.");
        var current = state.Snapshot("device")["token"]!.GetValue<string>();
        TestAssert.Throws<InvalidDataException>(() => state.Command(current, "Music", "position", 0), "canSeek false ignored.");
        TestAssert.Throws<InvalidDataException>(() => KdeMediaState.CommandBody("Music", "shell", null), "Unknown action accepted.");
        TestAssert.Throws<InvalidDataException>(() => KdeMediaState.CommandBody("Music", "volume", 101), "Invalid volume accepted.");
        return Task.CompletedTask;
    }

    private static void RegisteredChoices()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-registered-media-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var apps = new[] { new KdeRegisteredPlayer("owned:music", "Same", "owned-music.exe", ["owned-music"]),
                new KdeRegisteredPlayer("owned:video", "Same", "owned-video.exe", ["owned-video"]) };
            var launched = new List<string>();
            var choices = new KdeRegisteredPlayers(root, () => apps, app => launched.Add(app.Id));
            choices.Configure("music", apps[0].Id); choices.Configure("video", apps[1].Id);
            var aliases = choices.Choices().Keys.ToArray();
            TestAssert.That(aliases.Length == 2 && aliases.Distinct().Count() == 2, "Two slots with the same application name collided.");
            foreach (var alias in aliases)
            {
                TestAssert.That(choices.Closed(alias, new JsonObject(), () => true)["canPlay"]!.GetValue<bool>(), "Closed player was not offered.");
                TestAssert.Throws<InvalidOperationException>(() => choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => false), "Revoked source launched an app.");
                TestAssert.Throws<InvalidOperationException>(() => choices.Closed(alias, new JsonObject { ["action"] = "Pause" }, () => true), "Closed player accepted Pause.");
            }
            TestAssert.That(launched.Count == 0, "Metadata or denied requests launched an app.");
            foreach (var alias in aliases)
            {
                choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => true);
                choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => true);
            }
            TestAssert.That(launched.SequenceEqual(apps.Select(app => app.Id)), "Slot launch throttles were lost or shared.");
            var reopened = new KdeRegisteredPlayers(root, () => apps, app => launched.Add(app.Id));
            TestAssert.That(reopened.Settings()["video"]!.GetValue<string>() == apps[1].Id, "Player choices were not durable.");
            reopened.Configure("music", "");
            TestAssert.That(new KdeRegisteredPlayers(root, () => apps).Settings()["music"]!.GetValue<string>() == "", "Explicit None was automatically enabled again.");
            TestAssert.Throws<InvalidOperationException>(() => reopened.Configure("video", @"C:\arbitrary.exe"), "A packet supplied an executable path.");
            TestAssert.Throws<InvalidDataException>(() => reopened.Configure("shell", apps[0].Id), "Unknown slot accepted.");
        }
        finally { Directory.Delete(root, true); }
    }
}
