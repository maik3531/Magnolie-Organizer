using System.ComponentModel;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

/// <summary>One original local user across normal UAC elevation. CurrentUserOnly
/// is intentionally NOT used: Windows compares elevation-dependent token Owner,
/// whereas this channel binds User SID plus actual peer PID and one-use token.</summary>
[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioSetupPipe
{
    internal static NamedPipeServerStream CreateServer(string name)
    {
        if (!name.StartsWith("magnolie-phone-audio-", StringComparison.Ordinal) || name.Length != 53 ||
            name.AsSpan(21).ContainsAnyExcept("0123456789abcdef")) throw new ArgumentException("webcam_audio_local_pipe_name_invalid");
        using var identity = WindowsIdentity.GetCurrent();
        var sid = identity.User ?? throw new UnauthorizedAccessException("webcam_audio_original_user_required");
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor("O:" + sid.Value + "D:P(A;;GA;;;" + sid.Value + ")", 1, out var descriptor, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        SafePipeHandle? handle = null;
        try
        {
            var security = new SecurityAttributes { Length = Marshal.SizeOf<SecurityAttributes>(), Descriptor = descriptor };
            // DUPLEX | OVERLAPPED | FIRST_PIPE_INSTANCE; byte/wait mode plus
            // PIPE_REJECT_REMOTE_CLIENTS. No network/other-user/admin fallback.
            handle = CreateNamedPipe(@"\\.\pipe\" + name, 0x40080003, 0x8, 1, 4096, 4096, 0, ref security);
            if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            var pipe = new NamedPipeServerStream(PipeDirection.InOut, isAsync: true, isConnected: false, handle);
            handle = null; // The stream now owns this exact kernel handle.
            try { RequireOriginalDescriptor(pipe, sid); return pipe; }
            catch { pipe.Dispose(); throw; }
        }
        finally { handle?.Dispose(); LocalFree(descriptor); }
    }
    internal static bool IsOriginalDescriptor(RawSecurityDescriptor descriptor, SecurityIdentifier user)
    {
        if (descriptor.Owner is null || !descriptor.Owner.Equals(user) || descriptor.DiscretionaryAcl is not { Count: 1 } acl ||
            (descriptor.ControlFlags & (ControlFlags.DiscretionaryAclPresent | ControlFlags.DiscretionaryAclProtected)) !=
                (ControlFlags.DiscretionaryAclPresent | ControlFlags.DiscretionaryAclProtected) ||
            acl[0] is not CommonAce rule || rule.IsCallback || rule.AceFlags != AceFlags.None || rule.AceQualifier != AceQualifier.AccessAllowed ||
            !rule.SecurityIdentifier.Equals(user)) return false;
        // Accept the canonical generic-all source or its kernel-mapped full
        // pipe rights; never another principal or an inherited/broad ACL.
        return rule.AccessMask == 0x10000000 || (rule.AccessMask & 0x1f019f) == 0x1f019f;
    }
    internal static void RequireOriginalDescriptor(PipeStream pipe, SecurityIdentifier user)
    {
        var error = GetSecurityInfo(pipe.SafePipeHandle, 1, 1 | 4, out _, out _, out _, out _, out var descriptor);
        if (error != 0) throw new Win32Exception((int)error);
        try
        {
            var size = GetSecurityDescriptorLength(descriptor);
            if (size is < 20 or > 4096) throw new UnauthorizedAccessException("webcam_audio_original_pipe_descriptor_required");
            var bytes = new byte[size]; Marshal.Copy(descriptor, bytes, 0, bytes.Length);
            if (!IsOriginalDescriptor(new RawSecurityDescriptor(bytes, 0), user)) throw new UnauthorizedAccessException("webcam_audio_original_user_pipe_required");
        }
        finally { LocalFree(descriptor); }
    }
    [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { internal int Length; internal IntPtr Descriptor; internal int Inherit; }
    [DllImport("kernel32.dll", EntryPoint = "CreateNamedPipeW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafePipeHandle CreateNamedPipe(string name, uint openMode, uint mode, uint maximum, uint output, uint input, uint timeout, ref SecurityAttributes security);
    [DllImport("advapi32.dll", EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint revision, out IntPtr descriptor, out uint size);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityInfo(SafePipeHandle handle, int type, uint flags, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
}
