using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeControlContractTests
{
    internal static Task RunAsync()
    {
        const string source = "contracts/time-control-v13.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(source), source)))!.AsObject();
        foreach (var request in vectors["requests"]!.AsArray().OfType<JsonObject>()) TimeControlContract.ValidateRequest(request);
        foreach (var report in vectors["reports"]!.AsArray().OfType<JsonObject>()) TimeControlContract.ValidateReport(report);
        var invalid = vectors["requests"]![1]!.DeepClone().AsObject(); invalid["action"] = "shell";
        TestAssert.Throws<InvalidDataException>(() => TimeControlContract.ValidateRequest(invalid), "Timer accepted an arbitrary command.");
        invalid = vectors["requests"]![1]!.DeepClone().AsObject(); invalid["format"] = true;
        TestAssert.Throws<InvalidDataException>(() => TimeControlContract.ValidateRequest(invalid), "Timer accepted a Boolean as version.");
        invalid = vectors["reports"]![0]!.DeepClone().AsObject(); invalid["persisted"] = true;
        TestAssert.Throws<InvalidDataException>(() => TimeControlContract.ValidateReport(invalid), "Read report claimed a timer save.");
        invalid = vectors["reports"]![2]!.DeepClone().AsObject(); invalid["revision"] = new string('a', 64);
        TestAssert.Throws<InvalidDataException>(() => TimeControlContract.ValidateReport(invalid), "Denied timer report leaked source data.");
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var wire = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = TimeControlContract.RequestKind, ["created_ms"] = now, ["expires_ms"] = now + 60000,
            ["body"] = vectors["requests"]![0]!.DeepClone() };
        TelefonMessageContract.ValidateMessage(wire, now, false);
        wire["expires_ms"] = now + 60001;
        TestAssert.Throws<TelefonMessageException>(() => TelefonMessageContract.ValidateMessage(wire, now, false), "Timer request exceeded bounded lifetime.");
        return Task.CompletedTask;
    }
}
