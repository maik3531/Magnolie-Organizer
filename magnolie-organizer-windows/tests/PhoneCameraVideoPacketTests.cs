using System.Buffers.Binary;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraVideoPacketTests
{
    internal static Task NativeRecordAsync()
    {
        var data = Enumerable.Range(0, PhoneCameraMediaChannel.VideoBytes).Select(i => (byte)(i * 17)).ToArray();
        var frame = new PhoneCameraMediaFrame(true, 0x0102030405060708, 0x0001020304050607, data);
        var packet = new byte[PhoneCameraVideoPacket.Bytes];
        PhoneCameraVideoPacket.Write(frame, packet);
        TestAssert.That(packet.AsSpan(0, 18).SequenceEqual(new byte[] {
            1, 1, 1, 2, 3, 4, 5, 6, 7, 8, 0, 1, 2, 3, 4, 5, 6, 7 }), "Native VideoRelay header/byte order changed");
        TestAssert.That(packet.AsSpan(18).SequenceEqual(data), "I420 planes were changed/reordered during native record serialization");
        data[0] ^= 0xff;
        TestAssert.That(packet[18] != data[0], "Native record retained caller-owned frame storage");
        PhoneCameraVideoPacket.Write(new(true, long.MaxValue, 9_007_199_254_740_991, data), packet);
        TestAssert.That(BinaryPrimitives.ReadInt64BigEndian(packet.AsSpan(2, 8)) == long.MaxValue &&
            BinaryPrimitives.ReadInt64BigEndian(packet.AsSpan(10, 8)) == 9_007_199_254_740_991,
            "Native relay numeric domain was narrowed or rounded");
        return Task.CompletedTask;
    }

    internal static Task InvalidRecordIsAtomicAsync()
    {
        var data = new byte[PhoneCameraMediaChannel.VideoBytes];
        foreach (var frame in new[] {
            new PhoneCameraMediaFrame(false, 0, 0, data), new(true, -1, 0, data), new(true, 0, -1, data),
            new(true, 0, 9_007_199_254_740_992, data), new(true, 0, 0, new byte[data.Length - 1]),
            new(true, 0, 0, new byte[data.Length + 1]), new(true, 0, 0, null!) })
        {
            var target = Enumerable.Repeat((byte)0xa5, PhoneCameraVideoPacket.Bytes).ToArray();
            TestAssert.Throws<ArgumentException>(() => PhoneCameraVideoPacket.Write(frame, target), "Invalid native record admitted");
            TestAssert.That(target.All(b => b == 0xa5), "Rejected record partially changed output bytes");
        }
        foreach (var size in new[] { 0, PhoneCameraVideoPacket.Bytes - 1, PhoneCameraVideoPacket.Bytes + 1 })
        {
            var target = Enumerable.Repeat((byte)0xa5, size).ToArray();
            TestAssert.Throws<ArgumentException>(() => PhoneCameraVideoPacket.Write(new(true, 0, 0, data), target), "Nonexact native record buffer admitted");
            TestAssert.That(target.All(b => b == 0xa5), "Invalid buffer was modified");
        }
        TestAssert.Throws<ArgumentNullException>(() => PhoneCameraVideoPacket.Write(null!, new byte[PhoneCameraVideoPacket.Bytes]), "Null frame admitted");
        return Task.CompletedTask;
    }
}
