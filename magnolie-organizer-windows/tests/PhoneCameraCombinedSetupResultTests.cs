using System.Buffers.Binary;
using MagnolieOrganizer.Windows;
using Wire = MagnolieOrganizer.Windows.PhoneCameraCombinedSetupWire;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraCombinedSetupResultTests
{
    private static readonly byte[] Source = Enumerable.Repeat((byte)0xa1, 32).ToArray();
    private static readonly byte[] Helper = Enumerable.Repeat((byte)0xb2, 32).ToArray();
    private static async Task<(Wire Parent, Wire Child)> Pair(Wire.Mode mode = Wire.Mode.Install, bool echo = true)
    {
        var parent = Wire.CombinedWireFixtureCreate(mode, Guid.NewGuid(), Source, Helper);
        using var header = new MemoryStream(); await parent.WriteHeaderAsync(header, default); header.Position = 0;
        var child = await Wire.CombinedWireFixtureReadAsync(header, mode, Source, Helper);
        using var reply = new MemoryStream(); await child.WriteHeaderAsync(reply, default); reply.Position = 0;
        if (echo) await parent.RequireEchoAsync(reply, default);
        return (parent, child);
    }
    private static async Task<byte[]> Encode(Wire child, Wire.Result result)
    { using var stream = new MemoryStream(); await child.WriteResultAsync(stream, result, default); return stream.ToArray(); }
    internal static async Task RoundTripAsync()
    {
        CallerSourceGuards(); // Source structure only, NOT native install acceptance.
        foreach (var mode in new[] { Wire.Mode.Plan, Wire.Mode.Install })
        {
            var results = new List<Wire.Result> { new(Wire.State.Failed), new(Wire.State.Unsupported), new(Wire.State.ExistingDevice), new(Wire.State.Cancelled) };
            if (mode == Wire.Mode.Plan) results.Add(new(Wire.State.PreparedOnly));
            else results.AddRange([new(Wire.State.UnknownPending), new(Wire.State.UnknownPending, true),
                new(Wire.State.UnknownPending, true, true), new(Wire.State.UnknownPending, true, true, true),
                new(Wire.State.RebootRequired, true, true, true)]);
            foreach (var expected in results)
            {
                var pair = await Pair(mode); var bytes = await Encode(pair.Child, expected);
                TestAssert.That(bytes.Length == 160 && bytes.AsSpan(0, 8).SequenceEqual("MGWRES02"u8), "Combined result framing changed");
                using var input = new MemoryStream(bytes);
                TestAssert.That(await pair.Parent.ReadResultAsync(input,
                    mutationApproved: expected.State is Wire.State.UnknownPending or Wire.State.RebootRequired, default) == expected,
                    "Combined result lost separate component outcomes");
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => pair.Parent.ReadResultAsync(new MemoryStream(bytes), true, default), "Result read replayed");
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => pair.Child.WriteResultAsync(new MemoryStream(), expected, default), "Result write replayed");
            }
        }
    }
    private static void CallerSourceGuards()
    {
        var source = File.ReadAllText("PhoneCameraCombinedSetup.cs");
        var child = source[source.IndexOf("internal static async Task<int> RunCombinedElevatedAsync", StringComparison.Ordinal)..];
        var position = -1;
        foreach (var step in new[] { "if (!ValidCombinedArguments(args))", "identity.User?.Value != args[4]",
            "using var originalProcessHandle = OpenProcess", "parent.StartTime.ToUniversalTime().Ticks !=",
            "RequireOriginalPeer(pipe", "PhoneCameraAudioSetupPipe.RequireOriginalDescriptor",
            "await pipe.WriteAsync(Convert.FromHexString(args[2])", "PhoneCameraCombinedSetupWire.ReadCurrentAsync",
            "PhoneCameraAudioPackage.Verify(archive)", "await OriginalPermissionAsync(CombinedContinue)",
            "PhoneCameraAudioStaging.Prepare", "CombinedNativeAsync(prepared, \"--plan\", planOnly)",
            "else if (planOnly)", "await OriginalPermissionAsync(CombinedWillInstall)", "mutationApproved = true",
            "header.RequireCompletedInstallHeader()", "PhoneCameraSetupJournal.CreateCurrent(header)",
            "PhoneCameraSourceRegistration.InstallCurrent(journal)", "sourceConfirmed = true", "journal.BeginMicrophone()",
            "CombinedNativeAsync(prepared, \"--install\", planOnly)", "journal.RecordMicrophoneResult(installed.Exit, installed.Json)" })
        {
            var next = child.IndexOf(step, position + 1, StringComparison.Ordinal);
            TestAssert.That(next > position, "Combined original setup gate missing/out of order: " + step); position = next;
        }
        TestAssert.That(source.Split("Verb = \"runas\"").Length == 2 && source.Split("PhoneCameraSourceRegistration.InstallCurrent(journal)").Length == 2 &&
            !source.Contains(".Kill(", StringComparison.Ordinal) && !source.Contains("ElevatedArgument, pipeName", StringComparison.Ordinal),
            "Combined setup gained second elevation, repeated source mutation, kill or audio-wire fallback");
        var native = child[child.IndexOf("private static async Task<(int Exit, string Json)> CombinedNativeAsync", StringComparison.Ordinal)..];
        TestAssert.That(native.IndexOf("AllowsNativeMode(mode, planOnly)", StringComparison.Ordinal) < native.IndexOf("prepared.MarkInstallationStarted()", StringComparison.Ordinal) &&
            native.Contains("await child.WaitForExitAsync()", StringComparison.Ordinal) && native.Contains("await Task.WhenAll(output, errors)", StringComparison.Ordinal) &&
            native.Contains("Math.Min(count, remaining)", StringComparison.Ordinal), "Native mode/lifetime/bounded drain fence missing");
        var program = File.ReadAllText("Program.cs"); var entry = File.ReadAllText("PhoneCameraAudioSetupEntry.cs");
        foreach (var flag in new[] { "--phone-camera-combined-elevated", "--phone-camera-combined-elevated-plan" })
        {
            var flagIndex = program.IndexOf(flag, StringComparison.Ordinal);
            TestAssert.That(flagIndex >= 0 && flagIndex < program.IndexOf("Missing optional module", StringComparison.Ordinal),
                "Missing optional combined module can fall into ordinary GUI");
        }
        TestAssert.That(entry.Contains("RunCombinedElevatedAsync(args)", StringComparison.Ordinal) &&
            !File.ReadAllText("PhoneCameraAudioSetupForm.cs").Contains("RunCombined", StringComparison.Ordinal),
            "Original internal combined dispatcher missing or unaccepted UI hook added");
    }
    internal static async Task RejectAsync()
    {
        foreach (var mode in new[] { Wire.Mode.Plan, Wire.Mode.Install })
        foreach (var invalid in new[] { new Wire.Result((Wire.State)99), new(Wire.State.RebootRequired),
            new(Wire.State.UnknownPending, false, true), new(Wire.State.UnknownPending, true, false, true),
            new(Wire.State.Failed, true), new(Wire.State.PreparedOnly, true),
            mode == Wire.Mode.Plan ? new(Wire.State.UnknownPending) : new(Wire.State.PreparedOnly) })
        {
            var pair = await Pair(mode);
            await TestAssert.ThrowsAsync<InvalidDataException>(() => pair.Child.WriteResultAsync(new MemoryStream(), invalid, default), "Invalid composite outcome written");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => pair.Child.WriteResultAsync(new MemoryStream(), new(Wire.State.Failed), default), "Rejected result revived");
        }
        foreach (var offset in new[] { 0, 8, 16, 20, 24, 40, 56, 88, 120, 152, 156 })
        {
            var pair = await Pair(); var bytes = await Encode(pair.Child, new(Wire.State.RebootRequired, true, true, true));
            bytes[offset] ^= 0x40;
            await TestAssert.ThrowsAsync<InvalidDataException>(() => pair.Parent.ReadResultAsync(new MemoryStream(bytes), true, default), "Changed result identity/state/flags accepted");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => pair.Parent.ReadResultAsync(new MemoryStream(bytes), true, default), "Bad result allowed retry");
        }
        foreach (var flags in new[] { 2, 4, 5, 6, 8, -1 })
        {
            var pair = await Pair(); var bytes = await Encode(pair.Child, new(Wire.State.UnknownPending));
            BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(156), flags);
            await TestAssert.ThrowsAsync<InvalidDataException>(() => pair.Parent.ReadResultAsync(new MemoryStream(bytes), true, default), "Impossible component flags accepted");
        }
        var unapproved = await Pair(); var reboot = await Encode(unapproved.Child, new(Wire.State.RebootRequired, true, true, true));
        await TestAssert.ThrowsAsync<InvalidDataException>(() => unapproved.Parent.ReadResultAsync(new MemoryStream(reboot), false, default), "Header echo substituted for mutation approval");
        var other = await Pair();
        await TestAssert.ThrowsAsync<InvalidDataException>(() => other.Parent.ReadResultAsync(new MemoryStream(reboot), true, default), "Foreign transaction result adopted");
        var downgrade = await Pair(); var failed = await Encode(downgrade.Child, new(Wire.State.Failed));
        await TestAssert.ThrowsAsync<InvalidDataException>(() => downgrade.Parent.ReadResultAsync(new MemoryStream(failed), true, default), "Approved mutation downgraded to non-mutating failure");
        var noEcho = await Pair(echo: false);
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => noEcho.Parent.ReadResultAsync(new MemoryStream(), true, default), "Result accepted before completed echo");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => noEcho.Parent.WriteResultAsync(new MemoryStream(), new(Wire.State.Failed), default), "Sender wrote receiver result");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => noEcho.Child.ReadResultAsync(new MemoryStream(), true, default), "Receiver acquired parent result role");
    }
    private sealed class FlushFailure : MemoryStream
    { public override Task FlushAsync(CancellationToken cancellationToken) => Task.FromException(new IOException("combined result fixture")); }
    internal static async Task InterruptedAsync()
    {
        var pair = await Pair(); var bytes = await Encode(pair.Child, new(Wire.State.UnknownPending, true));
        await TestAssert.ThrowsAsync<EndOfStreamException>(() => pair.Parent.ReadResultAsync(new MemoryStream(bytes[..^1]), true, default), "Truncated result guessed");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => pair.Parent.ReadResultAsync(new MemoryStream(bytes), true, default), "Truncated result retried");
        var failed = await Pair(); using var output = new FlushFailure();
        await TestAssert.ThrowsAsync<IOException>(() => failed.Child.WriteResultAsync(output, new(Wire.State.Failed), default), "Unknown result flush succeeded");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => failed.Child.WriteResultAsync(new MemoryStream(), new(Wire.State.Failed), default), "Unknown flush retried");
        var cancelled = await Pair(); using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        await TestAssert.ThrowsAsync<OperationCanceledException>(() => cancelled.Parent.ReadResultAsync(new MemoryStream(bytes), true, cancellation.Token), "Cancelled result accepted");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => cancelled.Parent.ReadResultAsync(new MemoryStream(bytes), true, default), "Cancelled result revived");
    }
}
