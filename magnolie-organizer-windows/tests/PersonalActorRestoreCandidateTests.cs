using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorRestoreCandidateTests
{
    internal static async Task FractionalDrawingAsync()
    {
        TestAssert.Throws<InvalidDataException>(() => TelefonCrypto.Canonical(new JsonObject { ["point"] = 0.1 }), "Local drawings relaxed telephone wire integers.");
        TestAssert.That(!NativeBookJson.Same(new JsonObject { ["enabled"] = false }, new JsonObject { ["enabled"] = 0 }), "Local drawing comparison conflated bool and number.");
        var fixtures = await PersonalActorLocalRestoreSourceTests.LoadGuiFixturesAsync(candidates: true, drawing: true);
        foreach (var raw in fixtures) foreach (var fault in new[] { "none", "coordinate", "boolean-type" })
        {
            var fixture = raw!.DeepClone().AsObject(); var book = fixture["book"]!.AsObject(); var candidate = JsonNode.Parse(fixture["candidate_text"]!.GetValue<string>())!.AsObject();
            var drawing = candidate["customOrganizer"]!["modules"]![0]!["drawing"]!;
            TestAssert.That(drawing["strokes"]![0]!["points"]![0]![0]!.GetValue<double>() == 0.1 && drawing["strokes"]![0]!["width"]!.GetValue<double>() == 1.5, "Actual GUI drawing fixture lost legitimate fractions.");
            if (fault == "coordinate") drawing["strokes"]![0]!["points"]![0]![0] = 0.1001;
            if (fault == "boolean-type") drawing["autoSize"] = 1;
            var owner = new NativeBookOwnerScope(); owner.SetReady(true); owner.Current("drawing-candidate", true);
            var text = book.ToJsonString(); owner.RecordSaved("drawing-candidate", true, BaumSyncSnapshot.Hash(text));
            var snapshot = NativeActorBookSnapshot.Capture(() => owner.SaveState("drawing-candidate", true), () => text)!;
            var scope = PhoneContentScope.Create(fixture["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()), fixture["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()));
            NativeHistoricalRestoreCandidateProof Prepare() => NativeHistoricalRestoreCandidateProof.Prepare(fixture["peer"]!.GetValue<string>(), fixture["run"]!.GetValue<string>(), fixture["format"]!.GetValue<int>(),
                [fixture["target"]!.AsObject()], [fixture["choice"]!.AsObject()], candidate.ToJsonString(), () => true, () => new string('a', 64), () => snapshot, () => scope);
            if (fault == "none") TestAssert.That(Prepare().AfterContentSha256 == NativeBookJson.Hash(candidate), "Unrelated drawing changed native after-content witness.");
            else TestAssert.Throws<InvalidOperationException>(() => Prepare(), "Changed unrelated drawing passed exact native delta.");
            TestAssert.That(text == book.ToJsonString() && owner.SaveState("drawing-candidate", true) == snapshot.SavedBook, "Drawing comparison mutated its native input.");
        }
    }

    internal static async Task RunAsync()
    {
        var fixtures = await PersonalActorLocalRestoreSourceTests.LoadGuiFixturesAsync(candidates: true);
        foreach (var raw in fixtures) foreach (var fault in new[] { "none", "content", "counter", "clock", "extra-entity", "unrelated-config", "trash-collateral",
            "alias", "boolean-type", "missing-choice", "implicit-confirm", "delete-choice", "clock-choice", "duplicate-json" })
        {
            var fixture = raw!.DeepClone().AsObject(); var book = fixture["book"]!.AsObject(); var target = fixture["target"]!.AsObject();
            var kind = target["kind"]!.GetValue<string>(); var id = target["id"]!.GetValue<string>(); var key = kind + "\0" + id;
            var originalText = fixture["candidate_text"]!.GetValue<string>(); var candidate = JsonNode.Parse(originalText)!.AsObject();
            var choices = new List<JsonObject> { fixture["choice"]!.DeepClone().AsObject() };
            if (fault == "content") candidate[kind == "note" ? "notizen" : "aufgaben"]!.AsArray().Last()!["titel"] = "Substituted content";
            if (fault == "counter") candidate["personalSync"]!["counter"] = candidate["personalSync"]!["counter"]!.GetValue<long>() + 1;
            if (fault == "clock") candidate["personalSync"]!["entities"]![key]!["clock"]![0]!["counter"] = candidate["personalSync"]!["entities"]![key]!["clock"]![0]!["counter"]!.GetValue<long>() + 1;
            if (fault == "extra-entity") candidate["personalSync"]!["entities"]!["note\0foreign"] = new JsonObject { ["state"] = "live" };
            if (fault == "unrelated-config") candidate["einstellungen"]!["historical_synthetic_change"] = true;
            if (fault == "trash-collateral") candidate["papierkorb"] = book["papierkorb"]!.DeepClone();
            if (fault == "alias") candidate["personalSync"]!["note_aliases"]!["foreign-id"] = "another-id";
            if (fault == "boolean-type") candidate["personalSync"]!["entities"]![key]!["acknowledged_by_peer"] = 0;
            if (fault == "missing-choice") choices.Clear();
            if (fault == "implicit-confirm") choices[0]["confirm_conflict"] = false;
            if (fault == "delete-choice") choices[0]["decision"] = "delete";
            if (fault == "clock-choice") choices[0]["expected_clock"]![0]!["counter"] = choices[0]["expected_clock"]![0]!["counter"]!.GetValue<long>() + 1;
            var text = fault == "none" ? originalText : candidate.ToJsonString();
            if (fault == "duplicate-json") text = text[..^1] + ",\"personalSync\":" + candidate["personalSync"]!.ToJsonString() + "}";
            var owner = new NativeBookOwnerScope(); owner.SetReady(true); owner.Current("restore-candidate", true);
            var beforeText = book.ToJsonString(); var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(beforeText))).ToLowerInvariant();
            owner.RecordSaved("restore-candidate", true, hash);
            var snapshot = NativeActorBookSnapshot.Capture(() => owner.SaveState("restore-candidate", true), () => beforeText)!;
            var scope = PhoneContentScope.Create(fixture["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()),
                fixture["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()));
            NativeHistoricalRestoreCandidateProof Prepare() => NativeHistoricalRestoreCandidateProof.Prepare(fixture["peer"]!.GetValue<string>(), fixture["run"]!.GetValue<string>(),
                fixture["format"]!.GetValue<int>(), [target], choices, text, () => true, () => new string('a', 64), () => snapshot, () => scope);
            if (fault == "none")
            {
                var proof = Prepare();
                TestAssert.That(proof.BeforeSavedBook == snapshot.SavedBook && proof.AfterSha256 == Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(originalText))).ToLowerInvariant(),
                    "Native delta proof lost its actual before/after byte witnesses.");
                TestAssert.That(proof.AfterContentSha256 == NativeBookJson.Hash(JsonNode.Parse(originalText)!.AsObject()), "Native proof lost exact after-content binding.");
                TestAssert.That(JsonNode.DeepEquals(JsonNode.Parse(proof.BeforeLiveJson), fixture["members"]) &&
                    JsonNode.Parse(proof.AfterLiveJson)![kind == "note" ? "notes" : "tasks"]!.AsArray().Any(value => value!.GetValue<string>() == id), "Native delta proof changed expected live membership.");
                TestAssert.That(!proof.ToString().Contains("Protected", StringComparison.Ordinal) && JsonNode.DeepEquals(JsonNode.Parse(proof.BeforeScopeJson), PhoneContentScope.Reference(scope)),
                    "Native delta proof leaked contents or lost original scope generation.");
            }
            else
            {
                var denied = false;
                try { Prepare(); }
                catch (Exception error) when (error is InvalidDataException or InvalidOperationException or ArgumentException or JsonException) { denied = true; }
                TestAssert.That(denied, "Claimed candidate hash bypassed exact native delta: " + kind + "/" + fault);
            }
            TestAssert.That(book.ToJsonString() == beforeText && owner.SaveState("restore-candidate", true) == snapshot.SavedBook, "Native candidate preparation mutated its source book/save.");
        }
    }
}
