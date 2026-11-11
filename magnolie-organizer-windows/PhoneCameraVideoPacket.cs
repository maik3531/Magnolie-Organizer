using System.Buffers.Binary;

namespace MagnolieOrganizer.Windows;

/// <summary>Exact record consumed by native VideoRelay. Pure serialization:
/// neither this record nor a successful copy grants a pipe, capture or SEND.
/// The output owner must guard the original context and bound its actual IO.</summary>
internal static class PhoneCameraVideoPacket
{
    internal const int Bytes = PhoneCameraMediaChannel.PacketBytes + PhoneCameraMediaChannel.VideoBytes;
    internal static void Write(PhoneCameraMediaFrame frame, Span<byte> destination)
    {
        ArgumentNullException.ThrowIfNull(frame);
        // Validate everything before changing the caller's destination. Do not
        // accept audio, variable dimensions, signed overflow or ambiguous PTS.
        if (!frame.Video || frame.Data is null || frame.Data.Length != PhoneCameraMediaChannel.VideoBytes ||
            frame.Sequence < 0 || frame.PresentationTimeUs is < 0 or > 9_007_199_254_740_991 || destination.Length != Bytes)
            throw new ArgumentException("webcam_native_video_record_invalid");
        destination[0] = 1;
        destination[1] = 1;
        BinaryPrimitives.WriteInt64BigEndian(destination[2..10], frame.Sequence);
        BinaryPrimitives.WriteInt64BigEndian(destination[10..18], frame.PresentationTimeUs);
        frame.Data.AsSpan().CopyTo(destination[18..]);
    }
}
