using System.Buffers.Binary;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PhoneCameraCombinedSetupWire
{
    // Setup accounting only. None of these outcomes means capture Ready.
    internal enum State { PreparedOnly, ExistingDevice, Unsupported, Failed, UnknownPending, RebootRequired, Cancelled }
    internal sealed record Result(State State, bool SourceStarted = false, bool SourceConfirmed = false, bool MicrophoneStarted = false);
    private const int ResultBytes = 8 + HeaderBytes + 8;
    private void RequireResultShape(Result result)
    {
        if (!Enum.IsDefined(result.State) || result.SourceConfirmed && !result.SourceStarted ||
            result.MicrophoneStarted && !result.SourceConfirmed ||
            RequestedMode == Mode.Plan && (result.SourceStarted || result.State is State.UnknownPending or State.RebootRequired) ||
            RequestedMode == Mode.Install && result.State == State.PreparedOnly ||
            result.State == State.RebootRequired && !result.MicrophoneStarted ||
            result.SourceStarted && result.State is not (State.UnknownPending or State.RebootRequired))
            throw new InvalidDataException("webcam_combined_setup_result_shape_invalid");
    }
    internal async Task WriteResultAsync(Stream stream, Result result, CancellationToken cancellation)
    {
        if (parent || Volatile.Read(ref writeCompleted) != 1 || Interlocked.CompareExchange(ref resultStarted, 1, 0) != 0)
            throw new InvalidOperationException("webcam_combined_setup_receiver_result_required");
        RequireResultShape(result);
        var bytes = new byte[ResultBytes];
        "MGWRES02"u8.CopyTo(bytes); header.CopyTo(bytes, 8);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(8 + HeaderBytes), (int)result.State);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(12 + HeaderBytes),
            (result.SourceStarted ? 1 : 0) | (result.SourceConfirmed ? 2 : 0) | (result.MicrophoneStarted ? 4 : 0));
        await stream.WriteAsync(bytes, cancellation); await stream.FlushAsync(cancellation);
        cancellation.ThrowIfCancellationRequested();
    }
    internal async Task<Result> ReadResultAsync(Stream stream, bool mutationApproved, CancellationToken cancellation)
    {
        if (!parent || Volatile.Read(ref echoCompleted) != 1 || Interlocked.CompareExchange(ref resultStarted, 1, 0) != 0)
            throw new InvalidOperationException("webcam_combined_setup_original_result_required");
        var bytes = new byte[ResultBytes]; await stream.ReadExactlyAsync(bytes, cancellation);
        cancellation.ThrowIfCancellationRequested();
        if (!bytes.AsSpan(0, 8).SequenceEqual("MGWRES02"u8) ||
            !CryptographicOperations.FixedTimeEquals(header, bytes.AsSpan(8, HeaderBytes)))
            throw new InvalidDataException("webcam_combined_setup_result_binding_changed");
        var flags = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(12 + HeaderBytes));
        if ((flags & ~7) != 0) throw new InvalidDataException("webcam_combined_setup_result_flags_invalid");
        var result = new Result((State)BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(8 + HeaderBytes)),
            (flags & 1) != 0, (flags & 2) != 0, (flags & 4) != 0);
        RequireResultShape(result);
        if (!mutationApproved && (result.SourceStarted || result.State is State.UnknownPending or State.RebootRequired) ||
            mutationApproved && result.State is not (State.UnknownPending or State.RebootRequired))
            throw new InvalidDataException("webcam_combined_setup_result_without_original_approval");
        return result;
    }
}
