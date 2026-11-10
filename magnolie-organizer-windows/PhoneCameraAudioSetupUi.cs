namespace MagnolieOrganizer.Windows;

// Native entry for the future original webcam admission UI, not a renderer/
// phone action. No startup/discovery path calls it or advertises readiness.
internal static class PhoneCameraAudioSetupUi
{
    private static int busy;
    private static string T(string text) => NativeLocalization.Gettext(text);
    internal static async Task<PhoneCameraAudioSetupResult> AskAndPrepareAsync(IWin32Window owner,
        Action originalCurrent, CancellationToken cancellation)
    {
        if (Interlocked.CompareExchange(ref busy, 1, 0) != 0) throw new InvalidOperationException("webcam_audio_setup_busy");
        try
        {
            originalCurrent(); cancellation.ThrowIfCancellationRequested();
            using (var bootstrap = PhoneCameraAudioBootstrapLease.TryAcquire())
            {
                if (bootstrap is null || PhoneCameraAudioHelperPayload.LoadEmbedded() is null)
                {
                    var unavailable = new PhoneCameraAudioSetupResult(PhoneCameraAudioSetupState.Unsupported);
                    ShowOutcome(unavailable); return unavailable;
                }
            }
            var question = T("To use your phone as a system microphone, Magnolie needs the VB-CABLE driver by VB-Audio.") + "\n\n" +
                T("Magnolie downloads and verifies the original package. Windows asks once for administrator approval. A restart is required, but Magnolie will not restart your PC.") + "\n\n" +
                T("VB-CABLE is selected separately in OBS or another application. This setup prevents it from becoming the Windows default audio device, including manual default selection.") + "\n\n" +
                T("VB-CABLE is donationware by VB-Audio: www.vb-cable.com. Donations are welcome; professional deployments may require purchased licences.") + "\n" +
                PhoneCameraAudioPackage.LicenseUrl + "\n\n" + T("Install VB-CABLE now?");
            if (MessageBox.Show(owner, question, T("Phone webcam microphone"), MessageBoxButtons.YesNo,
                MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes)
                return new(PhoneCameraAudioSetupState.Cancelled);
            originalCurrent(); cancellation.ThrowIfCancellationRequested();
            var package = await PhoneCameraAudioPackage.DownloadAsync(cancellation);
            originalCurrent();
            var result = await PhoneCameraAudioSetup.RunConfirmedAsync(package, originalCurrent, cancellation);
            if (result.State != PhoneCameraAudioSetupState.Cancelled) ShowOutcome(result);
            return result;
        }
        catch (OperationCanceledException) { return new(PhoneCameraAudioSetupState.Cancelled); }
        catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or System.Net.Http.HttpRequestException or
            System.Security.Cryptography.CryptographicException or InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            var result = new PhoneCameraAudioSetupResult(PhoneCameraAudioSetupState.Failed); ShowOutcome(result); return result;
        }
        finally { Volatile.Write(ref busy, 0); }

        void ShowOutcome(PhoneCameraAudioSetupResult result)
        {
            var message = result.State switch
            {
                PhoneCameraAudioSetupState.RebootRequired => T("VB-CABLE setup reports that a restart is required. Restart Windows yourself when convenient. Magnolie must check the actual audio endpoints afterwards; the phone microphone is not ready yet."),
                PhoneCameraAudioSetupState.UnknownPending => T("The VB-CABLE setup outcome is not confirmed. Do not retry automatically. Check the installation and any pending restart before continuing."),
                PhoneCameraAudioSetupState.ExistingDevice => T("An existing VB-CABLE device was found and was not changed. Its actual audio endpoints still need to be checked."),
                _ => T("Magnolie could not safely install VB-CABLE. You can install the driver manually using VB-Audio's official instructions.")
            };
            MessageBox.Show(owner, message + "\n\n" + PhoneCameraAudioPackage.DriverName + "\n" + PhoneCameraAudioPackage.ManualUrl,
                T("Phone webcam microphone"), MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }
}
