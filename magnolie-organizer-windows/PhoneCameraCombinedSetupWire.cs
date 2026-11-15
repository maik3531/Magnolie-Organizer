using System.Buffers.Binary;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Public identity metadata ONLY, not authentication, mutation permission,
// installation confirmation or capture authority. The original caller must
// additionally enforce PID/SID/birth/pipe binding and explicit user approval.
// Used only by the separate original combined setup, never the audio v1 wire.
internal sealed partial class PhoneCameraCombinedSetupWire
{
    internal enum Mode { Plan = 1, Install = 2 }
    internal const int HeaderBytes = 144;
    private readonly byte[] header;
    private readonly bool parent;
    private int writeStarted, writeCompleted, echoStarted, echoCompleted, resultStarted;
    internal Mode RequestedMode => (Mode)BinaryPrimitives.ReadInt32LittleEndian(header.AsSpan(12));
    internal Guid Transaction => new(header.AsSpan(16, 16));
    private PhoneCameraCombinedSetupWire(byte[] ownedHeader, bool parent)
    { header = ownedHeader; this.parent = parent; }
    private static void RequireMode(Mode mode)
    {
        if (mode is not (Mode.Plan or Mode.Install)) throw new ArgumentOutOfRangeException(nameof(mode));
    }
    private static byte[] Header(Mode mode, Guid transaction, ReadOnlySpan<byte> source, ReadOnlySpan<byte> helper)
    {
        RequireMode(mode);
        if (transaction == Guid.Empty || source.Length != 32 || helper.Length != 32)
            throw new InvalidDataException("webcam_combined_setup_identity_required");
        var bytes = new byte[HeaderBytes];
        "MGWSET02"u8.CopyTo(bytes);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(8), 2);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(12), (int)mode);
        transaction.TryWriteBytes(bytes.AsSpan(16, 16));
        Guid.Parse(PhoneCameraSourcePayload.ClassId).TryWriteBytes(bytes.AsSpan(32, 16));
        source.CopyTo(bytes.AsSpan(48, 32)); helper.CopyTo(bytes.AsSpan(80, 32));
        Convert.FromHexString(PhoneCameraAudioPackage.Sha256).CopyTo(bytes, 112);
        return bytes;
    }
    private static (byte[] Source, byte[] Helper) OwnIdentities()
    {
        var source = PhoneCameraSourcePayload.LoadEmbedded() ?? throw new InvalidOperationException("webcam_combined_setup_source_unavailable");
        var helper = PhoneCameraAudioHelperPayload.LoadEmbedded() ?? throw new InvalidOperationException("webcam_combined_setup_helper_unavailable");
        return (Convert.FromHexString(source.Sha256), Convert.FromHexString(helper.Sha256));
    }
    internal static PhoneCameraCombinedSetupWire CreateCurrent(Mode mode)
    {
        RequireMode(mode);
        var own = OwnIdentities();
        return new(Header(mode, Guid.NewGuid(), own.Source, own.Helper), parent: true);
    }
    internal static Task<PhoneCameraCombinedSetupWire> ReadCurrentAsync(Stream stream, Mode expectedMode, CancellationToken cancellation)
    {
        RequireMode(expectedMode);
        var own = OwnIdentities();
        return ReadExpectedAsync(stream, expectedMode, own.Source, own.Helper, cancellation);
    }
    private static async Task<PhoneCameraCombinedSetupWire> ReadExpectedAsync(Stream stream, Mode expectedMode,
        byte[] ownSource, byte[] ownHelper, CancellationToken cancellation)
    {
        RequireMode(expectedMode);
        var received = new byte[HeaderBytes];
        await stream.ReadExactlyAsync(received, cancellation);
        cancellation.ThrowIfCancellationRequested();
        var owned = received.ToArray(); // Stream implementations must not retain our stored identity buffer.
        var transaction = new Guid(owned.AsSpan(16, 16));
        var expected = Header(expectedMode, transaction, ownSource, ownHelper);
        // Hashes/transaction are not secrets or a MAC. Equality just refuses
        // wrong composition/mode; original peer authentication is still required.
        if (!CryptographicOperations.FixedTimeEquals(owned, expected))
            throw new InvalidDataException("webcam_combined_setup_header_changed");
        return new(owned, parent: false);
    }
    internal async Task WriteHeaderAsync(Stream stream, CancellationToken cancellation)
    {
        if (Interlocked.CompareExchange(ref writeStarted, 1, 0) != 0)
            throw new InvalidOperationException("webcam_combined_setup_header_already_attempted");
        await stream.WriteAsync(header.ToArray(), cancellation);
        await stream.FlushAsync(cancellation);
        cancellation.ThrowIfCancellationRequested();
        Volatile.Write(ref writeCompleted, 1);
    }
    internal async Task RequireEchoAsync(Stream stream, CancellationToken cancellation)
    {
        if (!parent || Volatile.Read(ref writeCompleted) != 1 || Interlocked.CompareExchange(ref echoStarted, 1, 0) != 0)
            throw new InvalidOperationException("webcam_combined_setup_original_echo_required");
        var echoed = new byte[HeaderBytes];
        await stream.ReadExactlyAsync(echoed, cancellation);
        cancellation.ThrowIfCancellationRequested();
        if (!CryptographicOperations.FixedTimeEquals(header, echoed))
            throw new InvalidDataException("webcam_combined_setup_original_transaction_changed");
        Volatile.Write(ref echoCompleted, 1);
        // No Ready/admission flag is produced. This is NOT user confirmation.
    }
    // Structural metadata gate ONLY. Original peer/mutation approval must still
    // be verified by the caller, not inferred from this method succeeding.
    internal void RequireCompletedInstallHeader()
    {
        if (parent || RequestedMode != Mode.Install || Volatile.Read(ref writeCompleted) != 1)
            throw new InvalidOperationException("webcam_combined_setup_completed_install_header_required");
    }
}
