namespace MagnolieOrganizer.Windows;

// Test-only prepared composition of controlled tables. This constructor path
// is absent from product and never supplies fake readiness to a native device.
internal sealed partial class PhoneCameraNativeOutputs
{
    internal static PhoneCameraNativeOutputs CreateDiagnostic(PhoneCameraSession.OutputAuthority original,
        PhoneCameraAudioParentRuntime? audio, PhoneCameraVideoParentRuntime video)
    {
        original.RequireCurrent();
        if (original.Muted != (audio is null)) throw new InvalidOperationException("Diagnostic original output mode mismatch");
        return new PhoneCameraNativeOutputs { original = original, audio = audio, video = video, preparation = Task.CompletedTask };
    }
}
