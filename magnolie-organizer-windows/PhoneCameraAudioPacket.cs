using System.Buffers.Binary;

namespace MagnolieOrganizer.Windows;

/// <summary>Canonical native audio record, not an output, pipe or SEND grant.
/// Header integers are big endian; PCM16LE mono payload bytes stay unchanged.
/// The original output owner must separately bound IO and enforce live authority.</summary>
internal static class PhoneCameraAudioPacket
{
    internal const int Bytes = PhoneCameraMediaChannel.PacketBytes + PhoneCameraMediaChannel.AudioBytes;
    internal static void Write(PhoneCameraMediaFrame frame, Span<byte> destination)
    {
        ArgumentNullException.ThrowIfNull(frame);
        // Reject before changing any destination byte. No resampling, volume,
        // channel duplication, device discovery or capture fallback here.
        if (frame.Video || frame.Data is null || frame.Data.Length != PhoneCameraMediaChannel.AudioBytes ||
            frame.Sequence < 0 || frame.PresentationTimeUs is < 0 or > 9_007_199_254_740_991 || destination.Length != Bytes)
            throw new ArgumentException("webcam_native_audio_record_invalid");
        destination[0] = 1;
        destination[1] = 2;
        BinaryPrimitives.WriteInt64BigEndian(destination[2..10], frame.Sequence);
        BinaryPrimitives.WriteInt64BigEndian(destination[10..18], frame.PresentationTimeUs);
        frame.Data.AsSpan().CopyTo(destination[18..]);
    }
}
