using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeDigitizerTests
{
    internal static Task RunAsync()
    {
        var state = new KdeDigitizerState();
        JsonObject Send(string type, string body) => state.Accept(type, JsonNode.Parse(body)!.AsObject());
        void Start() => Send(KdeDigitizerState.SessionPacket,
            """{"action":"start","width":1000,"height":500,"resolutionX":10,"resolutionY":10}""");
        Start();
        TestAssert.That(!Send(KdeDigitizerState.EventPacket, """{"active":true,"touching":true}""")["touching"]!.GetValue<bool>(),
            "Missing coordinates drew at the origin.");
        var down = Send(KdeDigitizerState.EventPacket, """{"x":250,"y":100,"pressure":0.3,"tool":"Pen"}""");
        TestAssert.That(down["touching"]!.GetValue<bool>() && down["x"]!.GetValue<double>() == 0.25 && down["y"]!.GetValue<double>() == 0.2,
            "Tablet coordinates were not normalized.");
        var move = Send(KdeDigitizerState.EventPacket, """{"x":500}""");
        TestAssert.That(move["y"]!.GetValue<double>() == 0.2 && move["pressure"]!.GetValue<double>() == 0.3,
            "Partial updates lost previous axes/pressure.");
        TestAssert.That(Send(KdeDigitizerState.EventPacket, """{"tool":"Rubber"}""")["tool"]!.GetValue<string>() == "Rubber", "Eraser was lost.");
        TestAssert.That(!Send(KdeDigitizerState.EventPacket, """{"active":false}""")["touching"]!.GetValue<bool>(), "Hover exit left pen down.");
        TestAssert.That(!Send(KdeDigitizerState.EventPacket, """{"active":true}""")["touching"]!.GetValue<bool>(), "Hover reentry drew a phantom stroke.");
        foreach (var invalid in new[] { "{\"x\":true}", "{\"y\":1.5}", "{\"pressure\":-1}", "{\"tool\":\"Mouse\"}", "{\"touching\":\"true\"}", "{\"unknown\":1}" })
        {
            Start();
            try { Send(KdeDigitizerState.EventPacket, invalid); throw new Exception("Invalid digitizer input accepted."); }
            catch (InvalidDataException) { }
            try { Send(KdeDigitizerState.EventPacket, "{\"x\":1}"); throw new Exception("Invalid input did not reset the session."); }
            catch (InvalidDataException) { }
        }
        Start();
        TestAssert.That(Send(KdeDigitizerState.EventPacket, "{\"pressure\":1.2}")["pressure"]!.GetValue<double>() == 1, "Pressure above one was not clamped.");
        Start();
        TestAssert.That(Send(KdeDigitizerState.EventPacket,
            """{"active":true,"touching":false,"tool":"Pen","x":20,"y":30,"pressure":0}""")["touching"]!.GetValue<bool>(),
            "Finger down must draw without the phone's extra draw button.");
        TestAssert.That(Send(KdeDigitizerState.EventPacket, """{"x":40,"pressure":1}""")["touching"]!.GetValue<bool>(),
            "Android draw-button pressure must start finger drawing without a touching delta.");
        TestAssert.That(Send(KdeDigitizerState.EventPacket, """{"x":50}""")["touching"]!.GetValue<bool>(),
            "Coordinate-only deltas must keep a drawing stroke active.");
        TestAssert.That(Send(KdeDigitizerState.EventPacket, """{"pressure":0}""")["touching"]!.GetValue<bool>(),
            "A finger still on the screen must continue drawing without pressure.");
        TestAssert.That(!Send(KdeDigitizerState.EventPacket, """{"active":false,"touching":false}""")["touching"]!.GetValue<bool>(),
            "Lifting the finger must end its stroke.");
        TestAssert.That(!Send(KdeDigitizerState.EventPacket, """{"active":true,"x":70,"y":30}""")["touching"]!.GetValue<bool>(),
            "Stylus hover after lifting must not draw.");
        Send(KdeDigitizerState.EventPacket, """{"touching":true,"pressure":1}""");
        var released = Send(KdeDigitizerState.EventPacket, """{"touching":false,"pressure":1}""");
        TestAssert.That(!released["touching"]!.GetValue<bool>() && released["pressure"]!.GetValue<double>() == 0,
            "Explicit pen release must override retained pressure.");
        return Task.CompletedTask;
    }
}
