using System.Runtime.InteropServices;
using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

// Local backup scheduling only. None of these observations/keys grant source,
// write, expiry or remote deletion authority.
internal static class NativeMediaBackupPolicy
{
    internal const long DayMs = 86400000;
    internal const long MinimumAgeMs = 30 * DayMs;
    internal const long MinimumIdleMs = 10 * 60 * 1000;
    internal const long MinimumAvailableBytes = 2L * 1024 * 1024 * 1024;
    internal const int MaximumExternalCpuPercent = 15;
    internal const long MaximumTimestampMs = 253402300799999;

    internal static bool ColdAgeEligible(long savedMs, long nowMs, int retentionDays)
        => retentionDays is 0 or 90 or 365 && savedMs > 0 && nowMs > savedMs && nowMs <= MaximumTimestampMs && nowMs - savedMs > MinimumAgeMs;

    internal static bool Worthwhile(long rawBytes, long storedBytes, long extraBytes = 0)
        => rawBytes is > 0 and <= DeviceFileManifest.MaxFileBytes && storedBytes > 0 && storedBytes <= rawBytes &&
            extraBytes is >= 0 and <= 1024 * 1024 && (storedBytes + extraBytes) * 10 <= rawBytes * 9;

    internal static string ContentKey(long size, string sha256)
    {
        if (size is < 0 or > DeviceFileManifest.MaxFileBytes || !DeviceFileControl.Hash(sha256))
            throw DeviceFileControl.Error("media_backup_original_digest_required");
        return sha256 + "-" + size.ToString(System.Globalization.CultureInfo.InvariantCulture);
    }
}

internal sealed record NativeBackupIdleObservation(long IdleMs, int ExternalCpuPercent, long AvailableBytes)
{
    internal bool Eligible => IdleMs >= NativeMediaBackupPolicy.MinimumIdleMs && ExternalCpuPercent is >= 0 and <= NativeMediaBackupPolicy.MaximumExternalCpuPercent &&
        AvailableBytes >= NativeMediaBackupPolicy.MinimumAvailableBytes;
    internal bool GrantsMutationAuthority => false;
}

internal sealed class NativeBackupIdlePermit
{
    private readonly Func<NativeBackupIdleObservation?> observe;
    private readonly Action ensureNative;
    private readonly CancellationToken stop;
    private readonly object gate = new();
    private bool revoked;
    internal NativeBackupIdlePermit(Func<NativeBackupIdleObservation?> observe, Action ensureNative, CancellationToken stop = default)
    {
        this.observe = observe; this.ensureNative = ensureNative; this.stop = stop;
        Require();
    }
    internal void Require()
    {
        lock (gate)
        {
            try
            {
                if (revoked) throw DeviceFileControl.Error("media_backup_native_idle_revoked");
                stop.ThrowIfCancellationRequested(); ensureNative();
                if (observe()?.Eligible != true) throw DeviceFileControl.Error("media_backup_not_idle");
            }
            catch { revoked = true; throw; }
        }
    }
}

/** Passive native Windows probe. Unknown/first samples do not admit work. The
 * owner supplies a monotonic CPU counter for ONLY its maintenance work (including
 * any owned compressor process); its own load must not look like user activity.
 * No timer/thread/process is constructed here. Native guards are still required.
 */
internal sealed class NativeWindowsBackupIdleProbe
{
    private readonly Func<long> clock, ownCpu;
    private readonly Func<long?> idle, memory;
    private readonly Func<(ulong Total, ulong Idle)?> cpu;
    private readonly object gate = new();
    private sealed record Sample(long Now, ulong Total, ulong Idle, long Own);
    private Sample? previous;
    private NativeBackupIdleObservation? cached;

    internal NativeWindowsBackupIdleProbe(Func<long>? clock = null, Func<long?>? idle = null,
        Func<(ulong Total, ulong Idle)?>? cpu = null, Func<long?>? memory = null, Func<long>? ownCpu100ns = null)
    {
        this.clock = clock ?? (() => Environment.TickCount64);
        this.idle = idle ?? NativeIdle; this.cpu = cpu ?? NativeCpu; this.memory = memory ?? NativeMemory;
        ownCpu = ownCpu100ns ?? (() => 0);
    }

    internal NativeBackupIdleObservation? Observe()
    {
        lock (gate)
        {
            try
            {
                var now = clock();
                if (now < 0 || previous is not null && now < previous.Now) throw new InvalidDataException();
                if (previous is not null && now - previous.Now < 500) return cached;
                var inactive = idle(); var ram = memory(); var counters = cpu(); var own = ownCpu();
                if (inactive is null or < 0 || ram is null or < 0 || counters is null || own < 0 || counters.Value.Idle > counters.Value.Total)
                    throw new InvalidDataException();
                var before = previous;
                previous = new(now, counters.Value.Total, counters.Value.Idle, own);
                if (before is null) return null;
                if (previous.Total <= before.Total || previous.Idle < before.Idle || own < before.Own) throw new InvalidDataException();
                var total = previous.Total - before.Total; var waiting = previous.Idle - before.Idle;
                if (waiting > total) throw new InvalidDataException();
                var busy = total - waiting; var maintenance = (ulong)(own - before.Own);
                var external = busy > maintenance ? busy - maintenance : 0;
                var percent = Math.Clamp((int)Math.Ceiling(external * 100d / total), 0, 100);
                cached = new(inactive.Value, percent, ram.Value); return cached;
            }
            catch (Exception) { previous = null; cached = null; return null; }
        }
    }

    private static long? NativeIdle()
    {
        if (!NativeSessionObservable()) return null;
        var info = new LastInputInfo { Size = (uint)Marshal.SizeOf<LastInputInfo>() };
        return GetLastInputInfo(ref info) ? unchecked((uint)Environment.TickCount64 - info.Time) : null;
    }
    internal static bool NativeSessionObservable()
    {
        // GetLastInputInfo is session-local. A service/SSH session must NEVER
        // mistake its lack of input for the actual desktop user being idle.
        if (!OperatingSystem.IsWindows() || !Environment.UserInteractive) return false;
        using var process = Process.GetCurrentProcess(); var session = process.SessionId;
        if (session == 0) return false;
        var data = IntPtr.Zero;
        try { return WTSQuerySessionInformation(IntPtr.Zero, session, 8, out data, out var bytes) && bytes >= 4 && Marshal.ReadInt32(data) == 0; }
        finally { if (data != IntPtr.Zero) WTSFreeMemory(data); }
    }
    private static (ulong, ulong)? NativeCpu()
    {
        if (!OperatingSystem.IsWindows() || !GetSystemTimes(out var idle, out var kernel, out var user)) return null;
        if (kernel.Ticks > ulong.MaxValue - user.Ticks) return null;
        return (kernel.Ticks + user.Ticks, idle.Ticks);
    }
    private static long? NativeMemory()
    {
        if (!OperatingSystem.IsWindows()) return null;
        var value = new MemoryStatus { Length = (uint)Marshal.SizeOf<MemoryStatus>() };
        return GlobalMemoryStatusEx(ref value) && value.AvailablePhysical <= long.MaxValue ? (long)value.AvailablePhysical : null;
    }

    [StructLayout(LayoutKind.Sequential)] private struct LastInputInfo { public uint Size, Time; }
    [StructLayout(LayoutKind.Sequential)] private struct FileTime { public uint Low, High; public readonly ulong Ticks => ((ulong)High << 32) | Low; }
    [StructLayout(LayoutKind.Sequential)] private struct MemoryStatus
    {
        public uint Length, Load;
        public ulong TotalPhysical, AvailablePhysical, TotalPageFile, AvailablePageFile, TotalVirtual, AvailableVirtual, AvailableExtendedVirtual;
    }
    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetLastInputInfo(ref LastInputInfo info);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetSystemTimes(out FileTime idle, out FileTime kernel, out FileTime user);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
    [DllImport("wtsapi32.dll", EntryPoint = "WTSQuerySessionInformationW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool WTSQuerySessionInformation(IntPtr server, int session, int infoClass, out IntPtr data, out uint bytes);
    [DllImport("wtsapi32.dll")] private static extern void WTSFreeMemory(IntPtr data);
}
