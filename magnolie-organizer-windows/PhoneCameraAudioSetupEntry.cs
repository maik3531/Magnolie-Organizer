namespace MagnolieOrganizer.Windows;

internal static partial class Program
{
    static partial void HandleWebcamAudioSetup(string[] args, ref bool handled)
    {
        if (args.Length == 0 || args[0] is not (PhoneCameraAudioSetup.ElevatedArgument or PhoneCameraAudioSetup.ElevatedPlanArgument or PhoneCameraAudioSetup.PreparationProbeArgument or PhoneCameraAudioSetupForm.Argument or
            PhoneCameraAudioSetup.CombinedElevatedArgument or PhoneCameraAudioSetup.CombinedElevatedPlanArgument)) return;
        handled = true;
        try
        {
            if (args[0] is PhoneCameraAudioSetup.CombinedElevatedArgument or PhoneCameraAudioSetup.CombinedElevatedPlanArgument)
                Environment.ExitCode = PhoneCameraAudioSetup.RunCombinedElevatedAsync(args).GetAwaiter().GetResult();
            else if (args[0] == PhoneCameraAudioSetupForm.Argument)
            {
                if (args.Length != 1) { Environment.ExitCode = 87; return; }
                ApplicationConfiguration.Initialize();
                using var form = new PhoneCameraAudioSetupForm();
                Application.Run(form);
                Environment.ExitCode = form.Result.State switch
                {
                    PhoneCameraAudioSetupState.Cancelled => 1223,
                    PhoneCameraAudioSetupState.Unsupported => 50,
                    PhoneCameraAudioSetupState.RebootRequired => 3010,
                    PhoneCameraAudioSetupState.ExistingDevice => 1638,
                    PhoneCameraAudioSetupState.UnknownPending => 1618,
                    _ => 1603
                };
            }
            else if (args[0] == PhoneCameraAudioSetup.PreparationProbeArgument)
            {
                if (args.Length != 2) { Environment.ExitCode = 87; return; }
                using var file = new FileStream(args[1], FileMode.Open, FileAccess.Read, FileShare.Read);
                if (file.Length is < 1 or > PhoneCameraAudioSetupWire.MaximumArchive) { Environment.ExitCode = 87; return; }
                var bytes = new byte[checked((int)file.Length)]; file.ReadExactly(bytes);
                var package = PhoneCameraAudioPackage.Verify(bytes);
                var result = PhoneCameraAudioSetup.RunPreparationProbeAsync(package, () => { }, CancellationToken.None).GetAwaiter().GetResult();
                Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new { schema = 1, mode = "preparation-probe", state = result.State.ToString(),
                    failureReason = result.FailureReason, nativeError = result.NativeError, elevatedExit = result.ElevatedExit, installationAttempted = false }));
                Environment.ExitCode = result.State == PhoneCameraAudioSetupState.PreparedOnly ? 0 : 1;
            }
            else Environment.ExitCode = PhoneCameraAudioSetup.RunElevatedAsync(args).GetAwaiter().GetResult();
        }
        catch (UnauthorizedAccessException) { Environment.ExitCode = 5; }
        catch (Exception error) when (error is IOException or InvalidDataException or System.ComponentModel.Win32Exception or
            System.Security.Cryptography.CryptographicException or OperationCanceledException or ArgumentException or InvalidOperationException or System.Text.Json.JsonException)
        { Environment.ExitCode = 1603; }
    }
}
