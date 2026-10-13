using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeInputTests
{
    internal static Task RunAsync()
    {
        foreach (var value in new[] { """{"dx":10.5,"dy":-2}""", """{"x":-300,"y":400}""",
            """{"singleclick":true}""", """{"singlehold":true}""", """{"singlerelease":true}""",
            """{"scroll":true,"dy":120}""", """{"key":"ä 😀","shift":false,"sendAck":true}""",
            """{"specialKey":9}""", """{"specialKey":25}""", """{"specialKey":14}""" })
        {
            var input = JsonNode.Parse(value)!.AsObject();
            TestAssert.That(KdeInputProtocol.Input(input).ToJsonString() == input.ToJsonString(), "Valid input lost protocol values.");
        }
        foreach (var value in new[] { "{}", """{"singleclick":1}""", """{"dx":true}""", """{"dx":4097}""",
            """{"x":100}""", """{"x":100,"y":100,"dx":1}""", """{"key":"\u0000"}""",
            """{"specialKey":true}""", """{"specialKey":33}""", """{"specialKey":12,"key":"x"}""",
            """{"singleclick":true,"rightclick":true}""", """{"singleclick":true,"key":"x"}""",
            """{"ctrl":true,"dx":1}""", """{"shell":"anything"}""", """{"scroll":true,"x":1,"y":1}""" })
            TestAssert.Throws<InvalidDataException>(() => KdeInputProtocol.Input(JsonNode.Parse(value)!.AsObject()), "Malformed input accepted.");
        TestAssert.Throws<InvalidDataException>(() => KdeInputProtocol.Input(new JsonObject { ["key"] = new string('x', 1025) }), "Oversized text accepted.");
        var sink = new Sink(); var target = new KdeInputTarget(sink);
        var old = new object(); var current = new object(); var allowed = true;
        var oldToken = Guid.NewGuid().ToString(); var token = Guid.NewGuid().ToString();
        target.Arm(old, oldToken, () => allowed); target.Accept(old, new JsonObject { ["singlehold"] = true });
        target.Arm(current, token, () => allowed);
        TestAssert.That(sink.Releases == 1 && !target.Accept(old, new JsonObject { ["key"] = "late" }), "Old worker survived replacement.");
        TestAssert.That(!target.Disarm(targetToken: oldToken), "Old UI token disarmed new target.");
        TestAssert.That(target.Accept(current, new JsonObject { ["specialKey"] = 9 }), "Current target rejected valid PageDown.");
        allowed = false;
        TestAssert.That(target.Expire() && sink.Releases == 2, "Expired target left a held button without another packet.");
        TestAssert.That(!target.Accept(current, new JsonObject { ["key"] = "blocked" }) && sink.Applied == 2, "Revoked target remained actionable.");
        allowed = true; target.Arm(current, token, () => allowed);
        TestAssert.Throws<InvalidDataException>(() => target.Accept(current, new JsonObject { ["specialKey"] = 33 }), "Invalid key reached sink.");
        TestAssert.That(sink.Releases == 3, "Invalid request did not release target.");
        var point = KdeInputProtocol.Pointer(JsonNode.Parse("""{"dx":0.01,"dy":-0.01}""")!.AsObject());
        TestAssert.That(point.ContainsKey("dx") && KdeInputProtocol.Pointer(new JsonObject { ["stop"] = true }).Count == 1, "Presenter values lost.");
        TestAssert.Throws<InvalidDataException>(() => KdeInputProtocol.Pointer(new JsonObject { ["stop"] = true, ["dx"] = 0 }), "Ambiguous presenter stop accepted.");
        return Task.CompletedTask;
    }

    private sealed class Sink : IKdeInputSink
    {
        internal int Applied, Releases;
        public bool Keyboard => true;
        public void Apply(JsonObject body) => Applied++;
        public void Release() => Releases++;
        public void Dispose() { }
    }
}
