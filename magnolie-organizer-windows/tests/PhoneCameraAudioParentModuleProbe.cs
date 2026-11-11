namespace MagnolieOrganizer.Windows;

// Test assembly only: exercise the real held-handle admission, NOT a DLL-load
// bypass. No such member is compiled into the optional product.
internal sealed partial class PhoneCameraAudioParentModule
{
    internal static void ProbeHeldPath(string path, bool directory, bool ancestors)
    {
        using var module = new PhoneCameraAudioParentModule();
        if (ancestors) module.HoldAncestors(path);
        module.Hold(path, directory, requireProtection: true);
        if (module.module != IntPtr.Zero) throw new Exception("Held-file probe loaded a DLL");
    }
}
