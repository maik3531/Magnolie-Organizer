using System.ComponentModel;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class CrashReportWriter
{
    internal const long MaximumBytes = 1024L * 1024;
    private const int MaximumExceptions = 8;
    private const int MaximumMessageCharacters = 32 * 1024;
    private const int MaximumStackCharacters = 64 * 1024;
    private static readonly object ProcessWriter = new();

    internal static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Magnolie Organizer", "Logs", "crash.log");

    internal static bool TryWrite(string path, string sourceKind, Exception exception,
        DateTimeOffset? timestamp = null, string? appVersion = null, string? os = null, string? runtime = null)
    {
        try
        {
            var remaining = MaximumExceptions;
            var report = new CrashReport(
                (timestamp ?? DateTimeOffset.UtcNow).ToUniversalTime(),
                Limited(appVersion ?? Assembly.GetEntryAssembly()?.GetName().Version?.ToString() ?? "unknown", 256),
                Limited(os ?? RuntimeInformation.OSDescription, 1024),
                Limited(runtime ?? RuntimeInformation.FrameworkDescription, 1024),
                Limited(sourceKind, 256),
                Describe(exception, ref remaining));
            var json = JsonSerializer.Serialize(report) + "\n";
            var bytes = new UTF8Encoding(false).GetBytes(json);
            if (bytes.LongLength > MaximumBytes) return false;

            lock (ProcessWriter)
            {
                using var writer = new Mutex(false, "MagnolieOrganizer.Windows.CrashReportWriter.v1");
                var acquired = false;
                try
                {
                    try { acquired = writer.WaitOne(TimeSpan.FromSeconds(5)); }
                    catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) return false;

                    var directory = Path.GetDirectoryName(path) ?? throw new IOException("Invalid crash report path.");
                    RejectReparsePoint(directory);
                    Directory.CreateDirectory(directory);
                    RejectReparsePoint(directory);
                    ApplyPrivateAcl(directory, directory: true);
                    RejectReparsePoint(path);
                    RejectReparsePoint(path + ".old");
                    if (File.Exists(path)) ApplyPrivateAcl(path, directory: false);
                    RotateIfNeeded(path, bytes.LongLength);
                    using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read,
                               bufferSize: 4096, FileOptions.WriteThrough))
                    {
                        stream.Write(bytes);
                        stream.Flush(flushToDisk: true);
                    }
                    ApplyPrivateAcl(path, directory: false);
                    return true;
                }
                finally
                {
                    if (acquired) try { writer.ReleaseMutex(); } catch (ApplicationException) { }
                }
            }
        }
        catch
        {
            // Crash reporting must never hide or replace the original failure.
            return false;
        }
    }

    private static void RotateIfNeeded(string path, long entryBytes)
    {
        if (!File.Exists(path)) return;
        var length = new FileInfo(path).Length;
        if (length + entryBytes <= MaximumBytes) return;
        var oldPath = path + ".old";
        if (File.Exists(oldPath)) File.Delete(oldPath);
        if (length <= MaximumBytes)
        {
            File.Move(path, oldPath);
            ApplyPrivateAcl(oldPath, directory: false);
        }
        else File.Delete(path);
    }

    private static void RejectReparsePoint(string path)
    {
        try
        {
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Crash report paths must not be reparse points.");
        }
        catch (FileNotFoundException) { }
        catch (DirectoryNotFoundException) { }
    }

    private static void ApplyPrivateAcl(string path, bool directory)
    {
        if (!OperatingSystem.IsWindows()) return;
        using var identity = WindowsIdentity.GetCurrent();
        var sid = identity.User?.Value ?? throw new UnauthorizedAccessException("The current user SID is unavailable.");
        var flags = directory ? "OICI" : "";
        var sddl = $"D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;{sid})";
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1, out var descriptor, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            if (!GetSecurityDescriptorDacl(descriptor, out _, out var dacl, out _))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            const uint protectedDaclSecurityInformation = 0x80000004;
            var result = SetNamedSecurityInfo(path, 1, protectedDaclSecurityInformation,
                IntPtr.Zero, IntPtr.Zero, dacl, IntPtr.Zero);
            if (result is 1 or 50) return; // Filesystems without ACL support.
            if (result != 0) throw new Win32Exception((int)result);
        }
        finally
        {
            _ = LocalFree(descriptor);
        }
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string sddl,
        uint revision, out IntPtr descriptor, out uint descriptorSize);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetSecurityDescriptorDacl(IntPtr descriptor,
        [MarshalAs(UnmanagedType.Bool)] out bool daclPresent, out IntPtr dacl,
        [MarshalAs(UnmanagedType.Bool)] out bool daclDefaulted);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
    private static extern uint SetNamedSecurityInfo(string objectName, uint objectType, uint securityInformation,
        IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    private static ExceptionReport Describe(Exception exception, ref int remaining)
    {
        remaining--;
        var inner = new List<ExceptionReport>();
        if (remaining > 0)
        {
            IEnumerable<Exception> exceptions = exception is AggregateException aggregate
                ? aggregate.InnerExceptions
                : exception.InnerException is { } value ? [value] : [];
            foreach (var child in exceptions)
            {
                if (remaining == 0) break;
                inner.Add(Describe(child, ref remaining));
            }
        }
        return new ExceptionReport(
            Limited(exception.GetType().FullName ?? exception.GetType().Name, 1024),
            Limited(exception.Message, MaximumMessageCharacters),
            Limited(exception.StackTrace ?? "", MaximumStackCharacters),
            inner);
    }

    private static string Limited(string value, int maximumCharacters) =>
        value.Length <= maximumCharacters ? value : value[..maximumCharacters] + " [truncated]";

    private sealed record CrashReport(DateTimeOffset TimestampUtc, string AppVersion, string Os,
        string Runtime, string SourceKind, ExceptionReport Exception);

    private sealed record ExceptionReport(string Type, string Message, string Stack,
        IReadOnlyList<ExceptionReport> InnerExceptions);
}

internal sealed class CrashReportDeduplicator
{
    private readonly object gate = new();
    private readonly ConditionalWeakTable<Exception, State> states = new();

    internal bool TryBegin(Exception exception)
    {
        lock (gate)
        {
            if (states.TryGetValue(exception, out _)) return false;
            states.Add(exception, new State());
            return true;
        }
    }

    internal void Complete(Exception exception, bool success)
    {
        lock (gate)
        {
            if (!success) states.Remove(exception);
        }
    }

    private sealed class State { }
}
