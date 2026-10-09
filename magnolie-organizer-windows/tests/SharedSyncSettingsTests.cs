using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class SharedSyncSettingsTests
{
    private const string A = "11111111-1111-4111-8111-111111111111";
    private const string B = "22222222-2222-4222-8222-222222222222";
    private const string C = "33333333-3333-4333-8333-333333333333";
    private static (JsonObject One, JsonObject Two) Converge(JsonObject one, JsonObject two) =>
        (SharedSyncSettings.Merge(one, two, A, B), SharedSyncSettings.Merge(two, one, B, A));
    private static string Mode(JsonObject value) => SharedSyncSettings.Effective(value)["content_mode"]!.GetValue<string>();

    internal static Task RunAsync()
    {
        var (one, two) = Converge(SharedSyncSettings.Create(A), SharedSyncSettings.Create(B));
        TestAssert.That(Mode(one) == "phone_scope", "The default is not the Notes content scope.");
        one = SharedSyncSettings.Change(one, A, B, "content_mode", JsonValue.Create("two_way")!);
        (one, two) = Converge(one, two);
        TestAssert.That(Mode(two) == "two_way", "One local choice did not reach the other side.");
        two = SharedSyncSettings.Change(two, B, A, "content_mode", JsonValue.Create("phone_scope")!);
        (one, two) = Converge(one, two);
        TestAssert.That(Mode(one) == "phone_scope" && JsonNode.DeepEquals(SharedSyncSettings.Effective(one), SharedSyncSettings.Effective(two)),
            "Changing scope from the opposite side did not converge.");
        TestAssert.That(JsonNode.DeepEquals(one, SharedSyncSettings.Merge(one, two, A, B)), "Echo created a feedback loop.");

        one = SharedSyncSettings.Change(one, A, B, "auto_mode", JsonValue.Create("connection")!);
        two = SharedSyncSettings.Change(two, B, A, "time_mode", JsonValue.Create("two_way")!);
        (one, two) = Converge(one, two);
        var values = SharedSyncSettings.Effective(one);
        TestAssert.That(values["auto_mode"]!.GetValue<string>() == "connection" && values["time_mode"]!.GetValue<string>() == "two_way" &&
            values["content_mode"]!.GetValue<string>() == "phone_scope" && !values["custom_enabled"]!.GetValue<bool>(),
            "Independent time settings or unrelated functions were overwritten.");
        var initial = Converge(SharedSyncSettings.Create(A), SharedSyncSettings.Create(B));
        var left = SharedSyncSettings.Change(initial.One, A, B, "content_mode", JsonValue.Create("two_way")!);
        var right = SharedSyncSettings.Change(initial.Two, B, A, "content_mode", JsonValue.Create("phone_scope")!);
        (left, right) = Converge(left, right);
        TestAssert.That(Mode(left) == "phone_scope" && Mode(left) == Mode(right), "Concurrent edits did not converge.");
        right = SharedSyncSettings.Change(right, B, A, "content_mode", JsonValue.Create("two_way")!);
        (left, right) = Converge(left, right);
        TestAssert.That(Mode(left) == "two_way" && Mode(left) == Mode(right), "One new choice could not resolve the concurrent scope choice.");

        var old = two.DeepClone().AsObject();
        two = SharedSyncSettings.Change(two, B, A, "skip_deletions", JsonValue.Create(false)!);
        two = SharedSyncSettings.Change(two, B, A, "skip_deletions", JsonValue.Create(true)!);
        (one, two) = Converge(one, two);
        var reopened = JsonNode.Parse(one.ToJsonString())!.AsObject();
        TestAssert.That(JsonNode.DeepEquals(reopened, SharedSyncSettings.Merge(reopened, old, A, B)), "Old replay undid a saved choice.");
        TestAssert.Throws<InvalidDataException>(() => SharedSyncSettings.Merge(one, SharedSyncSettings.Create(C), A, B), "Other computer's settings were accepted.");
        var before = one.DeepClone(); var forged = two.DeepClone().AsObject();
        forged["settings"]!["auto_mode"]![B] = new JsonObject { ["counter"] = 2, ["value"] = "manual" };
        forged["settings"]!["content_mode"]![A] = new JsonObject { ["counter"] = 100, ["value"] = "two_way" };
        TestAssert.Throws<InvalidDataException>(() => SharedSyncSettings.Merge(one, forged, A, B), "A forged higher local echo was accepted.");
        TestAssert.That(JsonNode.DeepEquals(before, one), "Rejected multi-setting payload partially mutated state.");
        TestAssert.Throws<InvalidDataException>(() => SharedSyncSettings.Change(one, A, B, "custom_enabled", JsonValue.Create(1)!), "Untyped switch accepted.");
        TestAssert.Throws<InvalidDataException>(() => SharedSyncSettings.Change(one, A, B, "unknown", JsonValue.Create(true)!), "Unknown shared setting accepted.");
        var migrated = Converge(SharedSyncSettings.Create(A, new JsonObject { ["auto_mode"] = "wifi" }), SharedSyncSettings.Create(B));
        TestAssert.That(SharedSyncSettings.Effective(migrated.One)["auto_mode"]!.GetValue<string>() == "wifi" &&
            JsonNode.DeepEquals(SharedSyncSettings.Effective(migrated.One), SharedSyncSettings.Effective(migrated.Two)),
            "Initial Wi-Fi opt-in was lost or broadened to new transports.");
        return Task.CompletedTask;
    }
}
