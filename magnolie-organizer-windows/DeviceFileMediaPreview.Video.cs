using System.Buffers.Binary;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Runtime.Versioning;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Refs #429: decode verified bytes, never a source path, shell thumbnail or URL.
internal static class NativeMediaVideoContainer
{
    internal static void RequireLocalMp4(byte[] bytes)
    {
        if (bytes.Length is < 24 or > NativeMediaPreviewBytes.MaximumBytes || !bytes.AsSpan(4, 4).SequenceEqual("ftyp"u8))
            throw DeviceFileControl.Error("media_preview_video_container");
        var boxes = 0; var references = 0;
        void Scan(int start, int end, int depth)
        {
            if (depth > 12) throw DeviceFileControl.Error("media_preview_video_container");
            for (var offset = start; offset < end;)
            {
                if (++boxes > 4096 || end - offset < 8) throw DeviceFileControl.Error("media_preview_video_container");
                var size = (ulong)BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(offset, 4)); var header = 8;
                if (size == 1)
                {
                    if (end - offset < 16) throw DeviceFileControl.Error("media_preview_video_container");
                    size = BinaryPrimitives.ReadUInt64BigEndian(bytes.AsSpan(offset + 8, 8)); header = 16;
                }
                if (size == 0) size = (ulong)(end - offset);
                if (size < (ulong)header || size > (ulong)(end - offset)) throw DeviceFileControl.Error("media_preview_video_container");
                var next = offset + (int)size; var body = offset + header;
                var kind = System.Text.Encoding.ASCII.GetString(bytes, offset + 4, 4);
                if (kind is "rmra" or "rmda" or "rdrf" or "alis" or "url " or "urn ")
                    throw DeviceFileControl.Error("media_preview_video_external_reference");
                if (kind is "moov" or "trak" or "mdia" or "minf" or "dinf" or "stbl" or "mvex" or "moof" or "traf")
                    Scan(body, next, depth + 1);
                else if (kind == "dref")
                {
                    if (next - body < 8 || BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(body, 4)) != 0)
                        throw DeviceFileControl.Error("media_preview_video_external_reference");
                    var count = BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(body + 4, 4)); var entry = body + 8;
                    if (count is 0 or > 128) throw DeviceFileControl.Error("media_preview_video_external_reference");
                    for (var index = 0U; index < count; index++, entry += 12)
                    {
                        // Only an empty, self-contained ISO BMFF URL entry. No
                        // external URL/URN, QuickTime alias or filename fallback.
                        if (next - entry < 12 || BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(entry, 4)) != 12 ||
                            !bytes.AsSpan(entry + 4, 4).SequenceEqual("url "u8) ||
                            BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(entry + 8, 4)) != 1)
                            throw DeviceFileControl.Error("media_preview_video_external_reference");
                        references++;
                    }
                    if (entry != next) throw DeviceFileControl.Error("media_preview_video_external_reference");
                }
                offset = next;
            }
        }
        Scan(0, bytes.Length, 0);
        if (references == 0) throw DeviceFileControl.Error("media_preview_video_external_reference");
    }
}

internal sealed record NativeMediaVideoFrame(int Width, int Height, byte[] Pixels, int Rotation = 0) : IDisposable
{
    public void Dispose() => CryptographicOperations.ZeroMemory(Pixels);
}

[SupportedOSPlatform("windows")]
internal static class NativeMediaPreviewVideo
{
    private static readonly Guid MajorType = new("48eba18e-f8c9-4687-bf11-0a74c9f96a8f"),
        Subtype = new("f7e34c9a-42e8-4714-b74b-cb29d72c35e5"),
        VideoType = new("73646976-0000-0010-8000-00aa00389b71"),
        Rgb32 = new("00000016-0000-0010-8000-00aa00389b71"),
        FrameSize = new("1652c33d-d6b2-4012-b834-72030849a37d"),
        DefaultStride = new("644b4e48-1e02-4516-b0eb-c01ca9d49ac6"),
        DisplayRotation = new("c380465d-2271-428c-9b83-ecea3b4a85c1"),
        VideoProcessing = new("fb394f3d-ccf1-42ee-bbb3-f9b845d5681d");
    private const uint FirstVideo = 0xfffffffc, AllStreams = 0xfffffffe;

    internal static NativeMediaVideoFrame Decode(byte[] bytes, Action current)
    {
        current(); NativeMediaVideoContainer.RequireLocalMp4(bytes); current();
        IMFAttributes? attributes = null; IMFByteStream? stream = null; IMFSourceReader? reader = null;
        IMFMediaType? native = null, output = null, actual = null; var started = false;
        var input = new ReadOnlyStream(bytes);
        static void Check(int hr) { if (hr < 0) Marshal.ThrowExceptionForHR(hr); }
        static void Release(object? value) { if (value is not null) Marshal.ReleaseComObject(value); }
        static (int Width, int Height) Size(IMFMediaType type)
        {
            Check(((IMFAttributes)type).GetUINT64(FrameSize, out var packed));
            var width = (int)(packed >> 32); var height = (int)(packed & uint.MaxValue);
            if (width is < 1 or > 32768 || height is < 1 or > 32768 || (long)width * height > 24000000)
                throw DeviceFileControl.Error("media_preview_dimensions");
            return (width, height);
        }
        try
        {
            // LITE has no Winsock initialization; input is a read-only memory
            // stream and the container parser forbids external data references.
            Check(MFStartup(0x20070, 1)); started = true;
            Check(MFCreateAttributes(out attributes, 1)); Check(attributes.SetUINT32(VideoProcessing, 1));
            Check(MFCreateMFByteStreamOnStream(input, out stream));
            Check(MFCreateSourceReaderFromByteStream(stream, attributes, out reader)); current();
            Check(reader.SetStreamSelection(AllStreams, false)); Check(reader.SetStreamSelection(FirstVideo, true));
            Check(reader.GetNativeMediaType(FirstVideo, 0, out native)); _ = Size(native); current();
            var rotation = ((IMFAttributes)native).GetUINT32(DisplayRotation, out var nativeRotation) < 0 ? 0 : (int)nativeRotation;
            if (rotation is not (0 or 90 or 180 or 270)) throw DeviceFileControl.Error("media_preview_video_rotation");
            Check(MFCreateMediaType(out output)); var format = (IMFAttributes)output;
            Check(format.SetGUID(MajorType, VideoType)); Check(format.SetGUID(Subtype, Rgb32));
            Check(reader.SetCurrentMediaType(FirstVideo, IntPtr.Zero, output));
            Check(reader.GetCurrentMediaType(FirstVideo, out actual)); var (width, height) = Size(actual);
            var strideResult = ((IMFAttributes)actual).GetUINT32(DefaultStride, out var packedStride);
            var stride = unchecked((int)packedStride);
            if (strideResult < 0) Check(MFGetStrideForBitmapInfoHeader(22, width, out stride));
            if (Math.Abs((long)stride) < (long)width * 4 || Math.Abs((long)stride) * height > 128L * 1024 * 1024)
                throw DeviceFileControl.Error("media_preview_dimensions");
            for (var attempt = 0; attempt < 128; attempt++)
            {
                current(); Check(reader.ReadSample(FirstVideo, 0, out _, out var flags, out _, out var sample));
                if ((flags & 0x30) != 0)
                {
                    if (sample != IntPtr.Zero) Marshal.Release(sample);
                    throw DeviceFileControl.Error("media_preview_video_format_changed");
                }
                if (sample == IntPtr.Zero)
                {
                    if ((flags & 2) != 0) break;
                    continue;
                }
                IMFMediaBuffer? buffer = null; var locked = false;
                try
                {
                    // IMFSample extends the 30 IMFAttributes methods. Its ninth
                    // method is ConvertToContiguousBuffer (IUnknown vtable 41).
                    var convert = Marshal.GetDelegateForFunctionPointer<ConvertSample>(Marshal.ReadIntPtr(Marshal.ReadIntPtr(sample), 41 * IntPtr.Size));
                    Check(convert(sample, out buffer)); Check(buffer.Lock(out var data, out _, out var length)); locked = true;
                    if (data == IntPtr.Zero || (long)length < Math.Abs((long)stride) * height) throw DeviceFileControl.Error("media_preview_video_frame");
                    var pixels = new byte[checked(width * height * 4)];
                    try
                    {
                        current();
                        var top = stride < 0 ? IntPtr.Add(data, checked((-stride) * (height - 1))) : data;
                        for (var row = 0; row < height; row++)
                            Marshal.Copy(IntPtr.Add(top, checked(row * stride)), pixels, row * width * 4, width * 4);
                        current(); return new(width, height, pixels, rotation);
                    }
                    catch { CryptographicOperations.ZeroMemory(pixels); throw; }
                }
                finally
                {
                    if (locked) _ = buffer!.Unlock();
                    Release(buffer); Marshal.Release(sample);
                }
            }
            throw DeviceFileControl.Error("media_preview_video_frame");
        }
        finally
        {
            Release(actual); Release(output); Release(native); Release(reader); Release(stream); Release(attributes);
            if (started) _ = MFShutdown();
            GC.KeepAlive(input);
        }
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    private sealed class ReadOnlyStream(byte[] bytes) : IStream
    {
        private readonly object gate = new(); private long position;
        public void Read(byte[] pv, int cb, IntPtr read)
        {
            lock (gate)
            {
                if (cb < 0 || cb > pv.Length) throw new COMException("Invalid read.", unchecked((int)0x80030057));
                var count = (int)Math.Min(cb, Math.Max(0, bytes.LongLength - position));
                if (count > 0) Buffer.BlockCopy(bytes, (int)position, pv, 0, count);
                position += count; if (read != IntPtr.Zero) Marshal.WriteInt32(read, count);
            }
        }
        public void Seek(long offset, int origin, IntPtr result)
        {
            lock (gate)
            {
                var next = checked((origin switch { 0 => 0, 1 => position, 2 => bytes.LongLength, _ => throw new COMException("Invalid seek.") }) + offset);
                if (next < 0 || next > bytes.LongLength) throw new COMException("Invalid seek.");
                position = next; if (result != IntPtr.Zero) Marshal.WriteInt64(result, next);
            }
        }
        public void Stat(out STATSTG stat, int flags) => stat = new STATSTG { type = 2, cbSize = bytes.LongLength, grfMode = 0 };
        public void Clone(out IStream clone) { lock (gate) clone = new ReadOnlyStream(bytes) { position = position }; }
        public void Write(byte[] pv, int cb, IntPtr written) => throw new COMException("Read only.", unchecked((int)0x80030005));
        public void SetSize(long size) => throw new COMException("Read only.", unchecked((int)0x80030005));
        public void CopyTo(IStream target, long count, IntPtr read, IntPtr written) => throw new COMException("Not implemented.", unchecked((int)0x80004001));
        public void Commit(int flags) { }
        public void Revert() => throw new COMException("Read only.");
        public void LockRegion(long offset, long count, int type) => throw new COMException("Not supported.");
        public void UnlockRegion(long offset, long count, int type) => throw new COMException("Not supported.");
    }

    [DllImport("mfplat.dll", ExactSpelling = true)] private static extern int MFStartup(int version, int flags);
    [DllImport("mfplat.dll", ExactSpelling = true)] private static extern int MFShutdown();
    [DllImport("mfplat.dll", ExactSpelling = true)] private static extern int MFCreateAttributes(out IMFAttributes attributes, int count);
    [DllImport("mfplat.dll", ExactSpelling = true)] private static extern int MFCreateMediaType(out IMFMediaType type);
    [DllImport("mfplat.dll", ExactSpelling = true)] private static extern int MFCreateMFByteStreamOnStream(IStream stream, out IMFByteStream bytes);
    [DllImport("mfreadwrite.dll", ExactSpelling = true)] private static extern int MFCreateSourceReaderFromByteStream(IMFByteStream stream, IMFAttributes attributes, out IMFSourceReader reader);
    [DllImport("mfplat.dll", ExactSpelling = true)] private static extern int MFGetStrideForBitmapInfoHeader(int format, int width, out int stride);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int ConvertSample(IntPtr sample, out IMFMediaBuffer buffer);

    [ComImport, Guid("ad4c1b00-4bf7-422f-9175-756693d9130d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] private interface IMFByteStream { }
    [ComImport, Guid("44ae0fa8-ea31-4109-8d2e-4cae4997c555"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] private interface IMFMediaType { }
    [ComImport, Guid("045fa593-8799-42b8-bc8d-8968c6453507"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] private interface IMFMediaBuffer
    {
        [PreserveSig] int Lock(out IntPtr data, out int maximum, out int length);
        [PreserveSig] int Unlock();
        [PreserveSig] int GetCurrentLength(out int length);
        [PreserveSig] int SetCurrentLength(int length);
        [PreserveSig] int GetMaxLength(out int length);
    }
    [ComImport, Guid("70ae66f2-c809-4e4f-8915-bdcb406b7993"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] private interface IMFSourceReader
    {
        [PreserveSig] int GetStreamSelection(uint stream, [MarshalAs(UnmanagedType.Bool)] out bool selected);
        [PreserveSig] int SetStreamSelection(uint stream, [MarshalAs(UnmanagedType.Bool)] bool selected);
        [PreserveSig] int GetNativeMediaType(uint stream, int index, out IMFMediaType type);
        [PreserveSig] int GetCurrentMediaType(uint stream, out IMFMediaType type);
        [PreserveSig] int SetCurrentMediaType(uint stream, IntPtr reserved, IMFMediaType type);
        [PreserveSig] int SetCurrentPosition(in Guid format, IntPtr position);
        [PreserveSig] int ReadSample(uint stream, int control, out uint actualStream, out int flags, out long timestamp, out IntPtr sample);
        [PreserveSig] int Flush(uint stream);
        [PreserveSig] int GetServiceForStream(uint stream, in Guid service, in Guid iid, out IntPtr result);
        [PreserveSig] int GetPresentationAttribute(uint stream, in Guid key, IntPtr value);
    }
    [ComImport, Guid("2cd2d921-c447-44a7-a13c-4adabfc247e3"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] private interface IMFAttributes
    {
        [PreserveSig] int GetItem(in Guid key, IntPtr value);
        [PreserveSig] int GetItemType(in Guid key, out int type);
        [PreserveSig] int CompareItem(in Guid key, IntPtr value, out int result);
        [PreserveSig] int Compare(IMFAttributes other, int kind, out int result);
        [PreserveSig] int GetUINT32(in Guid key, out uint value);
        [PreserveSig] int GetUINT64(in Guid key, out ulong value);
        [PreserveSig] int GetDouble(in Guid key, out double value);
        [PreserveSig] int GetGUID(in Guid key, out Guid value);
        [PreserveSig] int GetStringLength(in Guid key, out int length);
        [PreserveSig] int GetString(in Guid key, IntPtr value, int length, out int written);
        [PreserveSig] int GetAllocatedString(in Guid key, out IntPtr value, out int length);
        [PreserveSig] int GetBlobSize(in Guid key, out int size);
        [PreserveSig] int GetBlob(in Guid key, IntPtr value, int length, out int written);
        [PreserveSig] int GetAllocatedBlob(in Guid key, out IntPtr value, out int length);
        [PreserveSig] int GetUnknown(in Guid key, in Guid iid, out IntPtr value);
        [PreserveSig] int SetItem(in Guid key, IntPtr value);
        [PreserveSig] int DeleteItem(in Guid key);
        [PreserveSig] int DeleteAllItems();
        [PreserveSig] int SetUINT32(in Guid key, uint value);
        [PreserveSig] int SetUINT64(in Guid key, ulong value);
        [PreserveSig] int SetDouble(in Guid key, double value);
        [PreserveSig] int SetGUID(in Guid key, in Guid value);
        [PreserveSig] int SetString(in Guid key, [MarshalAs(UnmanagedType.LPWStr)] string value);
        [PreserveSig] int SetBlob(in Guid key, IntPtr value, int size);
        [PreserveSig] int SetUnknown(in Guid key, [MarshalAs(UnmanagedType.IUnknown)] object value);
        [PreserveSig] int LockStore();
        [PreserveSig] int UnlockStore();
        [PreserveSig] int GetCount(out int count);
        [PreserveSig] int GetItemByIndex(int index, out Guid key, IntPtr value);
        [PreserveSig] int CopyAllItems(IMFAttributes target);
    }
}
