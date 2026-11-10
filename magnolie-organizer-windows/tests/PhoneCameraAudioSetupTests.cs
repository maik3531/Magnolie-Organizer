using System.Runtime.Versioning;
using System.Text.Json.Nodes;
using System.IO.Pipes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraAudioSetupTests
{
    private static JsonObject Plan() => new() { ["schema"] = 1, ["driver"] = "VB-CABLE", ["mode"] = "plan", ["supportedHost"] = true,
        ["elevated"] = true, ["protectedPackage"] = true, ["existingTransaction"] = false, ["existingDeviceCount"] = 0,
        ["canInspectAudioDefaults"] = true, ["endpointPolicy"] = "explicit_app_selection_never_system_default", ["installationAttempted"] = false };
    internal static Task StrictPlanAsync()
    {
        TestAssert.That(PhoneCameraAudioSetupWire.IsOriginalPlan(Plan().ToJsonString(), out var existing) && !existing, "Original protected read-only plan refused");
        foreach (var field in new[] { "supportedHost", "elevated", "protectedPackage", "canInspectAudioDefaults" })
        {
            var plan = Plan(); plan[field] = false;
            TestAssert.That(!PhoneCameraAudioSetupWire.IsOriginalPlan(plan.ToJsonString(), out _), "Unready plan admitted: " + field);
        }
        foreach (var field in new[] { "existingTransaction", "installationAttempted" })
        {
            var plan = Plan(); plan[field] = true;
            TestAssert.That(!PhoneCameraAudioSetupWire.IsOriginalPlan(plan.ToJsonString(), out _), "Old mutation authority admitted: " + field);
        }
        var old = Plan(); old["existingDeviceCount"] = 1;
        TestAssert.That(!PhoneCameraAudioSetupWire.IsOriginalPlan(old.ToJsonString(), out existing) && existing, "Existing foreign device replacement admitted");
        var extra = Plan(); extra["unknown"] = "anything";
        TestAssert.That(!PhoneCameraAudioSetupWire.IsOriginalPlan(extra.ToJsonString(), out _), "Unknown plan field admitted");
        var duplicate = Plan().ToJsonString().Replace("\"schema\":1", "\"schema\":1,\"schema\":1", StringComparison.Ordinal);
        TestAssert.That(!PhoneCameraAudioSetupWire.IsOriginalPlan(duplicate, out _), "Duplicate plan property admitted");
        return Task.CompletedTask;
    }
    internal static Task RebootIsNotReadinessAsync()
    {
        var result = new JsonObject { ["schema"] = 1, ["driver"] = "VB-CABLE", ["mode"] = "install", ["state"] = "reboot_required", ["error"] = 0,
            ["ownDeviceRegistered"] = true, ["ownDeviceRemoved"] = false, ["rebootRequired"] = true, ["defaultsPreserved"] = true, ["ownInstance"] = "ROOT\\MEDIA\\fixture" };
        TestAssert.That(PhoneCameraAudioSetupWire.IsRebootResult(result.ToJsonString()), "Confirmed reboot-required result refused");
        foreach (var field in new[] { "ownDeviceRegistered", "rebootRequired", "defaultsPreserved" })
        {
            var invalid = result.DeepClone().AsObject(); invalid[field] = false;
            TestAssert.That(!PhoneCameraAudioSetupWire.IsRebootResult(invalid.ToJsonString()), "Unconfirmed reboot outcome admitted: " + field);
        }
        result["state"] = "unknown_pending";
        TestAssert.That(!PhoneCameraAudioSetupWire.IsRebootResult(result.ToJsonString()), "Unknown transaction presented as success");
        TestAssert.That(!Enum.GetNames<PhoneCameraAudioSetupState>().Any(n => n.Contains("Ready", StringComparison.Ordinal) || n == "Installed"),
            "Setup without endpoint reprobe advertised microphone readiness");
        return Task.CompletedTask;
    }
    internal static async Task OriginalBoundedWireAsync()
    {
        TestAssert.That(PhoneCameraAudioSetupWire.AllowsNativeMode("--plan", preparationOnly: true) &&
            !PhoneCameraAudioSetupWire.AllowsNativeMode("--install", preparationOnly: true) &&
            !PhoneCameraAudioSetupWire.AllowsNativeMode("--uninstall", preparationOnly: false) &&
            !PhoneCameraAudioSetupWire.AllowsNativeMode("--retry", preparationOnly: false), "Preparation probe acquired native mutation/retry authority");
        using var stream = new MemoryStream(); await PhoneCameraAudioSetupWire.WriteIntAsync(stream, 0x01020304, CancellationToken.None);
        TestAssert.That(stream.ToArray().SequenceEqual(new byte[] { 4, 3, 2, 1 }), "Setup wire integer changed");
        stream.Position = 0; TestAssert.That(await PhoneCameraAudioSetupWire.ReadIntAsync(stream, CancellationToken.None) == 0x01020304, "Original setup wire changed");
        using var truncated = new MemoryStream([1, 2, 3]);
        await TestAssert.ThrowsAsync<EndOfStreamException>(async () => { await PhoneCameraAudioSetupWire.ReadIntAsync(truncated, CancellationToken.None); }, "Truncated setup control guessed");
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        await TestAssert.ThrowsAsync<OperationCanceledException>(async () => { await PhoneCameraAudioSetupWire.ReadIntAsync(stream, cancelled.Token); }, "Cancelled setup read admitted");
    }
    [SupportedOSPlatform("windows")]
    internal static Task ArgumentBoundaryAsync()
    {
        var args = new[] { "--phone-camera-audio-elevated", "magnolie-phone-audio-" + new string('a', 32), new string('b', 64), "123", "S-1-5-21-1-2-3-1001" };
        TestAssert.That(PhoneCameraAudioSetup.ValidArguments(args), "Original bounded invocation shape refused");
        var probe = args.ToArray(); probe[0] = "--phone-camera-audio-elevated-plan";
        TestAssert.That(PhoneCameraAudioSetup.ValidArguments(probe), "Explicit separate plan-only invocation shape refused");
        foreach (var (field, value) in new[] { (0,"--install"), (1,"\\\\foreign\\pipe"), (2,new string('B',64)), (3,"0"), (3,"123 & setup.exe"), (4,"not-a-sid") })
        {
            var invalid = args.ToArray(); invalid[field] = value;
            TestAssert.That(!PhoneCameraAudioSetup.ValidArguments(invalid), "Malformed setup argument admitted: " + field);
        }
        TestAssert.That(!PhoneCameraAudioSetup.ValidArguments(args.Concat(new[] { "retry" }).ToArray()), "Unknown setup switch admitted");
        return Task.CompletedTask; // No pipe, UAC, staging or installer invocation.
    }
    [SupportedOSPlatform("windows")]
    internal static async Task ActualLocalPipeIdentityAsync()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var name = "magnolie-audio530-test-" + Guid.NewGuid().ToString("N");
        using var server = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly | PipeOptions.FirstPipeInstance);
        TestAssert.Throws<IOException>(() => { using var collision = new NamedPipeServerStream(name, PipeDirection.InOut, 1,
            PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly | PipeOptions.FirstPipeInstance); }, "Original first pipe instance replaced");
        var accepting = server.WaitForConnectionAsync(deadline.Token);
        using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        await client.ConnectAsync(deadline.Token); await accepting;
        PhoneCameraAudioSetup.RequireOriginalPeer(server, (uint)Environment.ProcessId, server: true);
        PhoneCameraAudioSetup.RequireOriginalPeer(client, (uint)Environment.ProcessId, server: false);
        TestAssert.Throws<UnauthorizedAccessException>(() => PhoneCameraAudioSetup.RequireOriginalPeer(server, 0, server: true), "Wrong original client PID accepted");
        TestAssert.Throws<UnauthorizedAccessException>(() => PhoneCameraAudioSetup.RequireOriginalPeer(client, 0, server: false), "Wrong original server PID accepted");
        var received = PhoneCameraAudioSetupWire.ReadIntAsync(server, deadline.Token);
        await PhoneCameraAudioSetupWire.WriteIntAsync(client, 7, deadline.Token);
        TestAssert.That(await received == 7, "Actual original local pipe wire changed");
        // Controlled same-process pair only: no UAC, files, staging or setup.
    }
}
