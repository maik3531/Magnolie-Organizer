using System.Buffers.Binary;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraAudioPacketTests
{
    internal static Task NativeRecordAsync()
    {
        var data = new byte[PhoneCameraMediaChannel.AudioBytes];
        // Include both PCM16 extremes, zero, negative/positive small values.
        short[] samples = [short.MinValue, -1, 0, 1, short.MaxValue];
        for (var i = 0; i < 960; ++i)
            BinaryPrimitives.WriteInt16LittleEndian(data.AsSpan(i * 2, 2), samples[i % samples.Length]);
        var packet = new byte[PhoneCameraAudioPacket.Bytes];
        PhoneCameraAudioPacket.Write(new(false, 0x0102030405060708, 0x0001020304050607, data), packet);
        TestAssert.That(packet.AsSpan(0, 18).SequenceEqual(new byte[] {
            1, 2, 1, 2, 3, 4, 5, 6, 7, 8, 0, 1, 2, 3, 4, 5, 6, 7 }), "Native audio header/track/byte order changed");
        TestAssert.That(packet.AsSpan(18).SequenceEqual(data), "Native record altered PCM16LE mono samples");
        for (var i = 0; i < 960; ++i)
            TestAssert.That(BinaryPrimitives.ReadInt16LittleEndian(packet.AsSpan(18 + i * 2, 2)) == samples[i % samples.Length], "PCM endian/sign conversion changed samples");
        data[0] ^= 0xff;
        TestAssert.That(packet[18] != data[0], "Native audio record retained caller frame storage");
        PhoneCameraAudioPacket.Write(new(false, long.MaxValue, 9_007_199_254_740_991, data), packet);
        TestAssert.That(BinaryPrimitives.ReadInt64BigEndian(packet.AsSpan(2, 8)) == long.MaxValue &&
            BinaryPrimitives.ReadInt64BigEndian(packet.AsSpan(10, 8)) == 9_007_199_254_740_991, "Native audio integer domain rounded/narrowed");
        return Task.CompletedTask;
    }

    internal static Task InvalidRecordIsAtomicAsync()
    {
        var data = new byte[PhoneCameraMediaChannel.AudioBytes];
        foreach (var frame in new[] {
            new PhoneCameraMediaFrame(true, 0, 0, data), new(false, -1, 0, data), new(false, 0, -1, data),
            new(false, 0, 9_007_199_254_740_992, data), new(false, 0, 0, new byte[data.Length - 1]),
            new(false, 0, 0, new byte[data.Length + 1]), new(false, 0, 0, null!) })
        {
            var target = Enumerable.Repeat((byte)0xa5, PhoneCameraAudioPacket.Bytes).ToArray();
            TestAssert.Throws<ArgumentException>(() => PhoneCameraAudioPacket.Write(frame, target), "Invalid native audio record admitted");
            TestAssert.That(target.All(value => value == 0xa5), "Rejected native audio record partly changed destination");
        }
        foreach (var size in new[] { 0, PhoneCameraAudioPacket.Bytes - 1, PhoneCameraAudioPacket.Bytes + 1 })
        {
            var target = Enumerable.Repeat((byte)0xa5, size).ToArray();
            TestAssert.Throws<ArgumentException>(() => PhoneCameraAudioPacket.Write(new(false, 0, 0, data), target), "Nonexact native audio buffer admitted");
            TestAssert.That(target.All(value => value == 0xa5), "Rejected native audio buffer changed");
        }
        TestAssert.Throws<ArgumentNullException>(() => PhoneCameraAudioPacket.Write(null!, new byte[PhoneCameraAudioPacket.Bytes]), "Null native audio frame admitted");
        return Task.CompletedTask;
    }
}
