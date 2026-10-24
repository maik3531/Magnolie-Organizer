using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace MagnolieOrganizer.Windows;

internal static class MozillaCodeTrust
{
    internal static bool IsTrusted(string path) => WindowsCodeTrust.IsTrusted(path, "Mozilla Corporation");
}

internal static class WindowsCodeTrust
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct TrustFile
    {
        internal uint Size;
        [MarshalAs(UnmanagedType.LPWStr)] internal string Path;
        internal nint File;
        internal nint Subject;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct TrustData
    {
        internal uint Size;
        internal nint Policy;
        internal nint Client;
        internal uint Ui;
        internal uint Revocation;
        internal uint Union;
        internal nint File;
        internal uint StateAction;
        internal nint State;
        internal nint Url;
        internal uint Flags;
        internal uint UiContext;
    }

    [DllImport("wintrust.dll", ExactSpelling = true, PreserveSig = true)]
    private static extern int WinVerifyTrust(nint window, ref Guid action, ref TrustData data);

    internal static bool IsTrusted(string path, string expectedPublisher)
    {
        if (!OperatingSystem.IsWindows()) return false;
        nint pointer = 0;
        var data = new TrustData();
        var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
        try
        {
            if (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) return false;
            var file = new TrustFile { Size = (uint)Marshal.SizeOf<TrustFile>(), Path = System.IO.Path.GetFullPath(path) };
            pointer = Marshal.AllocHGlobal(Marshal.SizeOf<TrustFile>());
            Marshal.StructureToPtr(file, pointer, false);
            data = new TrustData { Size = (uint)Marshal.SizeOf<TrustData>(), Ui = 2, Union = 1,
                File = pointer, StateAction = 1, Flags = 0x1000 };
            // WinTrust validates the signed file, its chain and timestamp without
            // showing UI or depending on a network fetch during every status read.
            if (WinVerifyTrust(new nint(-1), ref action, ref data) != 0) return false;
            using var certificate = new X509Certificate2(X509Certificate.CreateFromSignedFile(path));
            return certificate.GetNameInfo(X509NameType.SimpleName, false).Equals(expectedPublisher, StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or CryptographicException or ArgumentException)
        { return false; }
        finally
        {
            if (pointer != 0)
            {
                data.StateAction = 2;
                WinVerifyTrust(new nint(-1), ref action, ref data);
                Marshal.DestroyStructure<TrustFile>(pointer);
                Marshal.FreeHGlobal(pointer);
            }
        }
    }
}
