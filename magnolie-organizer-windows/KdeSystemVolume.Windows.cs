#if WINDOWS
using System.Runtime.InteropServices;

namespace MagnolieOrganizer.Windows;

/** Core Audio output endpoints, not per-application media sessions. RCWs stay on the calling MTA. */
internal sealed class WindowsAudioOutputs : IKdeAudioOutputs
{
    private static readonly Guid VolumeInterface = new("5CDF2C82-841E-4546-9722-0CF74078229A");
    private static readonly PropertyKey FriendlyName = new(new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14);
    private static void Check(int result) => Marshal.ThrowExceptionForHR(result);
    private static void Release(object? value) { if (value is not null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value); }

    public IReadOnlyList<KdeAudioOutput> Read()
    {
        var enumerator = (IDeviceEnumerator)new DeviceEnumerator();
        IDeviceCollection? collection = null;
        IDevice? defaultDevice = null;
        try
        {
            var defaultId = "";
            if (enumerator.GetDefaultAudioEndpoint(0, 1, out defaultDevice) >= 0 && defaultDevice is not null)
            { Check(defaultDevice.GetId(out defaultId)); }
            Check(enumerator.EnumAudioEndpoints(0, 1, out collection));
            Check(collection.GetCount(out var count));
            var result = new List<KdeAudioOutput>();
            for (uint index = 0; index < Math.Min(count, 128u); index++)
            {
                IDevice? device = null; IEndpointVolume? volume = null;
                try
                {
                    Check(collection.Item(index, out device));
                    Check(device.GetId(out var id));
                    volume = Activate(device);
                    Check(volume.GetMasterVolumeLevelScalar(out var scalar));
                    Check(volume.GetMute(out var muted));
                    result.Add(new KdeAudioOutput(id, Description(device, id),
                        (int)Math.Round(Math.Clamp(scalar, 0, 1) * 100, MidpointRounding.AwayFromZero), muted, id == defaultId));
                }
                finally { Release(volume); Release(device); }
            }
            return result;
        }
        finally { Release(defaultDevice); Release(collection); Release(enumerator); }
    }

    private static IEndpointVolume Activate(IDevice device)
    {
        var iid = VolumeInterface;
        Check(device.Activate(ref iid, 23, IntPtr.Zero, out var instance));
        return (IEndpointVolume)instance;
    }

    private static string Description(IDevice device, string fallback)
    {
        IPropertyStore? properties = null;
        var value = new PropVariant();
        try
        {
            Check(device.OpenPropertyStore(0, out properties));
            var key = FriendlyName;
            Check(properties.GetValue(ref key, out value));
            var name = value.Pointer == IntPtr.Zero ? null : value.Type switch {
                31 => Marshal.PtrToStringUni(value.Pointer),
                8 => Marshal.PtrToStringBSTR(value.Pointer),
                _ => null
            };
            return string.IsNullOrWhiteSpace(name) ? fallback : name[..Math.Min(name.Length, 512)];
        }
        catch (COMException) { return fallback; }
        finally { PropVariantClear(ref value); Release(properties); }
    }

    private static void Change(string name, Func<bool> permitted, Action<IEndpointVolume> action)
    {
        var enumerator = (IDeviceEnumerator)new DeviceEnumerator();
        IDevice? device = null; IEndpointVolume? volume = null;
        try
        {
            Check(enumerator.GetDevice(name, out device));
            Check(device.GetState(out var state));
            if (state != 1) throw new InvalidOperationException("system_volume_output_unavailable");
            volume = Activate(device);
            if (!permitted()) throw new InvalidOperationException("system_volume_source_changed");
            action(volume);
        }
        finally { Release(volume); Release(device); Release(enumerator); }
    }

    public void SetVolume(string name, int volume, Func<bool> permitted) => Change(name, permitted, endpoint =>
    { var context = Guid.Empty; Check(endpoint.SetMasterVolumeLevelScalar(Math.Clamp(volume, 0, 100) / 100f, ref context)); });

    public void SetMute(string name, bool muted, Func<bool> permitted) => Change(name, permitted, endpoint =>
    { var context = Guid.Empty; Check(endpoint.SetMute(muted, ref context)); });

    public void SetDefault(string name, Func<bool> permitted) => Change(name, permitted, _ =>
    {
        var policy = (IPolicyConfig)new PolicyConfig();
        try
        {
            for (var role = 0; role < 3; role++)
            {
                if (!permitted()) throw new InvalidOperationException("system_volume_source_changed");
                Check(policy.SetDefaultEndpoint(name, role));
            }
        }
        finally { Release(policy); }
    });

    /** Native ABI probe: reapply only the value just read, preserving user volume/default selection. */
    internal int VerifyUnchangedMuteWrite()
    {
        var outputs = Read();
        foreach (var output in outputs)
            Change(output.Name, () => true, endpoint =>
            {
                Check(endpoint.GetMute(out var original));
                var context = Guid.Empty;
                Check(endpoint.SetMute(original, ref context));
                Check(endpoint.GetMute(out var actual));
                if (actual != original) throw new InvalidOperationException("The unchanged native mute readback differs.");
            });
        return outputs.Count;
    }

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class DeviceEnumerator { }
    [ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
    private class PolicyConfig { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int flow, uint mask, out IDeviceCollection collection);
        [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IDevice? device);
        [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IDevice device);
        [PreserveSig] int RegisterEndpointNotificationCallback(IntPtr client);
        [PreserveSig] int UnregisterEndpointNotificationCallback(IntPtr client);
    }
    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDeviceCollection
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int Item(uint index, out IDevice device);
    }
    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDevice
    {
        [PreserveSig] int Activate(ref Guid iid, uint context, IntPtr parameters, [MarshalAs(UnmanagedType.IUnknown)] out object instance);
        [PreserveSig] int OpenPropertyStore(uint access, out IPropertyStore properties);
        [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
        [PreserveSig] int GetState(out uint state);
    }
    [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IEndpointVolume
    {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr callback);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr callback);
        [PreserveSig] int GetChannelCount(out uint count);
        [PreserveSig] int SetMasterVolumeLevel(float level, ref Guid context);
        [PreserveSig] int SetMasterVolumeLevelScalar(float level, ref Guid context);
        [PreserveSig] int GetMasterVolumeLevel(out float level);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float level);
        [PreserveSig] int SetChannelVolumeLevel(uint channel, float level, ref Guid context);
        [PreserveSig] int SetChannelVolumeLevelScalar(uint channel, float level, ref Guid context);
        [PreserveSig] int GetChannelVolumeLevel(uint channel, out float level);
        [PreserveSig] int GetChannelVolumeLevelScalar(uint channel, out float level);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool muted, ref Guid context);
        [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool muted);
        [PreserveSig] int GetVolumeStepInfo(out uint step, out uint count);
        [PreserveSig] int VolumeStepUp(ref Guid context);
        [PreserveSig] int VolumeStepDown(ref Guid context);
        [PreserveSig] int QueryHardwareSupport(out uint mask);
        [PreserveSig] int GetVolumeRange(out float minimum, out float maximum, out float increment);
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct PropertyKey(Guid format, uint id) { internal Guid Format = format; internal uint Id = id; }
    [StructLayout(LayoutKind.Explicit, Size = 24)]
    private struct PropVariant
    {
        [FieldOffset(0)] internal ushort Type;
        [FieldOffset(8)] internal IntPtr Pointer;
    }
    [DllImport("ole32.dll")] private static extern int PropVariantClear(ref PropVariant value);
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int Commit();
    }
    [ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPolicyConfig
    {
        [PreserveSig] int GetMixFormat([MarshalAs(UnmanagedType.LPWStr)] string id, out IntPtr format);
        [PreserveSig] int GetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string id, int defaultFormat, out IntPtr format);
        [PreserveSig] int ResetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string id);
        [PreserveSig] int SetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr endpoint, IntPtr mix);
        [PreserveSig] int GetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string id, int defaultPeriod, out long period, out long minimum);
        [PreserveSig] int SetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string id, ref long period);
        [PreserveSig] int GetShareMode([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr mode);
        [PreserveSig] int SetShareMode([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr mode);
        [PreserveSig] int GetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string id, ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string id, ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string id, int role);
        [PreserveSig] int SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string id, int visible);
    }
}
#endif
