namespace MagnolieOrganizer.Windows;

/// <summary>Explicit local prerequisite utility, not webcam admission or capture.
/// The native question remains mandatory. Closing cancels the original action;
/// the window stays owned until any already-started setup child has exited.</summary>
internal sealed class PhoneCameraAudioSetupForm : Form
{
    internal const string Argument = "--prepare-phone-webcam-audio";
    private readonly CancellationTokenSource lifetime = new();
    private bool running, finished, lifetimeDisposed;
    private IntPtr originalHandle;
    internal PhoneCameraAudioSetupResult Result { get; private set; } = new(PhoneCameraAudioSetupState.Cancelled);

    internal PhoneCameraAudioSetupForm()
    {
        Text = NativeLocalization.Gettext("Phone webcam microphone");
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        ClientSize = new Size(480, 100);
        Controls.Add(new Label { Text = Text, Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter, AutoEllipsis = true });
        Shown += RunSetup;
        FormClosing += (_, args) =>
        {
            if (finished) return;
            lifetime.Cancel();
            // Cancellation is never permission to kill SetupAPI or let the
            // original form/guard disappear while a child is still owned.
            args.Cancel = running;
        };
    }

    private void RequireOriginalWindow()
    {
        lifetime.Token.ThrowIfCancellationRequested();
        if (finished || IsDisposed || Disposing || !IsHandleCreated || Handle != originalHandle)
            throw new OperationCanceledException("webcam_audio_original_window_retired", lifetime.Token);
    }

    private async void RunSetup(object? sender, EventArgs args)
    {
        if (running || finished) return;
        running = true; originalHandle = Handle;
        try
        {
            Result = await PhoneCameraAudioSetupUi.AskAndPrepareAsync(this, RequireOriginalWindow, lifetime.Token);
        }
        catch (OperationCanceledException) { Result = new(PhoneCameraAudioSetupState.Cancelled); }
        catch (Exception)
        {
            // Native async-event boundary: never turn an exception into success
            // or retry, and never print package tokens/credentials/raw arguments.
            Result = new(PhoneCameraAudioSetupState.Failed, "native_setup_ui_failed");
        }
        finally
        {
            running = false; finished = true;
            Close();
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing && !lifetimeDisposed)
        {
            lifetimeDisposed = true; lifetime.Cancel(); lifetime.Dispose();
        }
        base.Dispose(disposing);
    }
}
