using System.Buffers.Binary;
using System.Runtime.InteropServices;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraCombinedSetupWireTests
{
    private static byte[] Source() => Enumerable.Repeat((byte)0xa1, 32).ToArray();
    private static byte[] Helper() => Enumerable.Repeat((byte)0xb2, 32).ToArray();
    private static PhoneCameraCombinedSetupWire Parent(PhoneCameraCombinedSetupWire.Mode mode = PhoneCameraCombinedSetupWire.Mode.Install) =>
        PhoneCameraCombinedSetupWire.CombinedWireFixtureCreate(mode, Guid.NewGuid(), Source(), Helper());
    private static async Task<byte[]> Encode(PhoneCameraCombinedSetupWire parent)
    { using var stream = new MemoryStream(); await parent.WriteHeaderAsync(stream, CancellationToken.None); return stream.ToArray(); }
    private sealed class MutatingWrite : MemoryStream
    {
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (MemoryMarshal.TryGetArray(buffer, out var segment)) segment.Array![segment.Offset + 12] ^= 0x40;
            return base.WriteAsync(buffer, cancellationToken);
        }
    }
    private sealed class RetainedRead(byte[] bytes) : MemoryStream(bytes)
    {
        private ArraySegment<byte> saved;
        internal void MutateSavedMode() { var segment = saved; segment.Array![segment.Offset + 12] ^= 0x40; }
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            MemoryMarshal.TryGetArray((ReadOnlyMemory<byte>)buffer, out saved);
            return base.ReadAsync(buffer, cancellationToken);
        }
    }
    internal static async Task IdentityAndEchoAsync()
    {
        await PhoneCameraCombinedSetupResultTests.RoundTripAsync();
        foreach (var mode in new[] { PhoneCameraCombinedSetupWire.Mode.Plan, PhoneCameraCombinedSetupWire.Mode.Install })
        {
            var source = Source(); var helper = Helper(); var transaction = Guid.NewGuid();
            var parent = PhoneCameraCombinedSetupWire.CombinedWireFixtureCreate(mode, transaction, source, helper);
            source[0] = 0; helper[0] = 0; // Caller mutation must not change owned wire bytes.
            var bytes = await Encode(parent);
            TestAssert.That(bytes.Length == 144 && bytes.AsSpan(0, 8).SequenceEqual("MGWSET02"u8) &&
                BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(8)) == 2 && BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(12)) == (int)mode &&
                new Guid(bytes.AsSpan(16, 16)) == transaction && new Guid(bytes.AsSpan(32, 16)).ToString() == PhoneCameraSourcePayload.ClassId,
                "Combined fixed framing changed");
            using var incoming = new MemoryStream(bytes);
            var child = await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(incoming, mode, Source(), Helper());
            TestAssert.That(child.Transaction == transaction && child.RequestedMode == mode, "Child lost original transaction/mode");
            var echoed = await Encode(child); using var reply = new MemoryStream(echoed);
            await parent.RequireEchoAsync(reply, CancellationToken.None);
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => parent.RequireEchoAsync(new MemoryStream(bytes), CancellationToken.None), "Original echo consumed twice");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => child.RequireEchoAsync(new MemoryStream(bytes), CancellationToken.None), "Child acquired parent confirmation role");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => parent.WriteHeaderAsync(new MemoryStream(), CancellationToken.None), "Header write retried");
        }
        TestAssert.Throws<InvalidOperationException>(() => PhoneCameraCombinedSetupWire.CreateCurrent(PhoneCameraCombinedSetupWire.Mode.Install), "Missing embedded resources acquired external fallback");
        TestAssert.Throws<ArgumentOutOfRangeException>(() => PhoneCameraCombinedSetupWire.CreateCurrent((PhoneCameraCombinedSetupWire.Mode)0), "Unknown mode accepted");
        var isolated = Parent(PhoneCameraCombinedSetupWire.Mode.Plan);
        using var mutating = new MutatingWrite(); await isolated.WriteHeaderAsync(mutating, CancellationToken.None);
        TestAssert.That(isolated.RequestedMode == PhoneCameraCombinedSetupWire.Mode.Plan, "Output stream changed owned mode");
        var intact = await Encode(Parent()); using var retaining = new RetainedRead(intact);
        var read = await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(retaining, PhoneCameraCombinedSetupWire.Mode.Install, Source(), Helper());
        retaining.MutateSavedMode();
        TestAssert.That(read.RequestedMode == PhoneCameraCombinedSetupWire.Mode.Install, "Input stream changed stored identity after validation");
    }
    internal static async Task RejectWrongIdentityAsync()
    {
        await PhoneCameraCombinedSetupResultTests.RejectAsync();
        var original = Parent(); var bytes = await Encode(original);
        foreach (var offset in new[] { 0, 8, 12, 32, 48, 80, 112 })
        {
            var changed = bytes.ToArray(); changed[offset] ^= 0x40;
            using var incoming = new MemoryStream(changed);
            await TestAssert.ThrowsAsync<InvalidDataException>(async () => {
                await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(incoming, PhoneCameraCombinedSetupWire.Mode.Install, Source(), Helper());
            }, "Foreign version/mode/class/source/helper/package accepted");
        }
        var emptyTransaction = bytes.ToArray(); Array.Clear(emptyTransaction, 16, 16);
        await TestAssert.ThrowsAsync<InvalidDataException>(async () => {
            using var incoming = new MemoryStream(emptyTransaction);
            await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(incoming, PhoneCameraCombinedSetupWire.Mode.Install, Source(), Helper());
        }, "Empty transaction accepted");
        await TestAssert.ThrowsAsync<InvalidDataException>(async () => {
            using var incoming = new MemoryStream(bytes);
            await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(incoming, PhoneCameraCombinedSetupWire.Mode.Plan, Source(), Helper());
        }, "Install header reinterpreted as plan");
        var otherTransaction = bytes.ToArray(); Guid.NewGuid().TryWriteBytes(otherTransaction.AsSpan(16, 16));
        using var wrongEcho = new MemoryStream(otherTransaction);
        await TestAssert.ThrowsAsync<InvalidDataException>(() => original.RequireEchoAsync(wrongEcho, CancellationToken.None), "Another transaction echoed as original");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => original.RequireEchoAsync(new MemoryStream(bytes), CancellationToken.None), "Wrong echo allowed retry/revival");
    }
    private sealed class FlushFailure : MemoryStream
    { public override Task FlushAsync(CancellationToken cancellationToken) => Task.FromException(new IOException("owned flush fixture")); }
    internal static async Task InterruptedExchangeAsync()
    {
        await PhoneCameraCombinedSetupResultTests.InterruptedAsync();
        var parent = Parent(); var bytes = await Encode(parent);
        using var truncated = new MemoryStream(bytes[..^1]);
        await TestAssert.ThrowsAsync<EndOfStreamException>(async () => {
            await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(truncated, PhoneCameraCombinedSetupWire.Mode.Install, Source(), Helper());
        }, "Truncated header guessed");
        using var truncatedEcho = new MemoryStream(bytes[..^1]);
        await TestAssert.ThrowsAsync<EndOfStreamException>(() => parent.RequireEchoAsync(truncatedEcho, CancellationToken.None), "Truncated echo guessed");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => parent.RequireEchoAsync(new MemoryStream(bytes), CancellationToken.None), "Truncated echo retried");
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        using var cancelledInput = new MemoryStream(bytes);
        await TestAssert.ThrowsAsync<OperationCanceledException>(async () => {
            await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(cancelledInput, PhoneCameraCombinedSetupWire.Mode.Install, Source(), Helper(), cancellation.Token);
        }, "Cancelled exchange admitted");
        var pending = Parent();
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => pending.RequireEchoAsync(new MemoryStream(bytes), CancellationToken.None), "Echo accepted before original write");
        using var failing = new FlushFailure();
        await TestAssert.ThrowsAsync<IOException>(() => pending.WriteHeaderAsync(failing, CancellationToken.None), "Unconfirmed flush succeeded");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => pending.WriteHeaderAsync(new MemoryStream(), CancellationToken.None), "Unknown header write retried");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => pending.RequireEchoAsync(new MemoryStream(bytes), CancellationToken.None), "Partial write became valid header");
    }
    internal static async Task JournalTransactionAndPlanGuardAsync()
    {
        foreach (var mode in new[] { PhoneCameraCombinedSetupWire.Mode.Plan, PhoneCameraCombinedSetupWire.Mode.Install })
        {
            var source = Enumerable.Repeat((byte)0xaa, 32).ToArray(); var helper = Enumerable.Repeat((byte)0xbb, 32).ToArray();
            var transaction = Guid.NewGuid();
            var parent = PhoneCameraCombinedSetupWire.CombinedWireFixtureCreate(mode, transaction, source, helper);
            var bytes = await Encode(parent);
            TestAssert.Throws<InvalidOperationException>(parent.RequireCompletedInstallHeader, "Sender header acquired receiver setup gate");
            using var incoming = new MemoryStream(bytes);
            var child = await PhoneCameraCombinedSetupWire.CombinedWireFixtureReadAsync(incoming, mode, source, helper);
            TestAssert.Throws<InvalidOperationException>(child.RequireCompletedInstallHeader, "Unsent echo acquired setup gate");
            _ = await Encode(child);
            var path = Path.Combine(Path.GetTempPath(), "magnolie-combined-journal-" + Guid.NewGuid().ToString("N") + ".journal");
            var created = false;
            try
            {
                if (mode == PhoneCameraCombinedSetupWire.Mode.Plan)
                {
                    TestAssert.Throws<InvalidOperationException>(() => PhoneCameraSetupJournal.JournalFixtureCreateFromHeader(path, child), "Plan created a journal");
                    TestAssert.That(!File.Exists(path), "Plan guard ran after file creation");
                }
                else
                {
                    child.RequireCompletedInstallHeader();
                    using (var journal = PhoneCameraSetupJournal.JournalFixtureCreateFromHeader(path, child)) created = true;
                    var audit = PhoneCameraSetupJournal.Inspect(File.ReadAllBytes(path));
                    TestAssert.That(audit.Transaction == transaction && audit.SourceSha256 == new string('a', 64) &&
                        audit.HelperSha256 == new string('b', 64) && audit.Outcome == PhoneCameraSetupJournal.Phase.UnknownPending,
                        "Journal generated a foreign transaction or claimed installation");
                    TestAssert.Throws<IOException>(() => PhoneCameraSetupJournal.JournalFixtureCreateFromHeader(path, child), "Same header replaced an existing journal");
                }
            }
            finally { if (created) File.Delete(path); }
        }
    }
}
