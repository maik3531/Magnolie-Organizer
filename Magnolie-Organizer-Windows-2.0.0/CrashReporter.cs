namespace MagnolieOrganizer.Windows;

internal static class CrashReporter
{
    private static readonly CrashReportDeduplicator Deduplicator = new();
    private static int registered;

    internal static void RegisterHandlers()
    {
        if (Interlocked.Exchange(ref registered, 1) != 0) return;
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
    }

    internal static void Record(string sourceKind, Exception exception)
    {
        try
        {
            if (!Deduplicator.TryBegin(exception)) return;
            var success = false;
            try
            {
                success = CrashReportWriter.TryWrite(CrashReportWriter.DefaultPath, sourceKind, exception);
            }
            finally
            {
                Deduplicator.Complete(exception, success);
            }
        }
        catch
        {
            // A reporting failure must not affect exception handling or application flow.
        }
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs eventArgs)
    {
        if (eventArgs.ExceptionObject is Exception exception)
            Record("AppDomain unhandled exception", exception);
        else
            Record("AppDomain unhandled exception", new InvalidOperationException("Unhandled non-Exception object."));
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs eventArgs)
    {
        var path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Magnolie Organizer", "Logs", "diagnostic.log");
        RotatingLog.Append(path, $"{DateTimeOffset.UtcNow:O} Unobserved task exception: {eventArgs.Exception}");
    }
}
