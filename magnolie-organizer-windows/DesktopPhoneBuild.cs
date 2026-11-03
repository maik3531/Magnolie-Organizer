namespace MagnolieOrganizer.Windows;

// Compile-time composition only. Neither these constants nor a contributor
// branding key establish runtime readiness, capture permission or media consent.
internal static class DesktopPhoneBuild
{
#if MAGNOLIE_PHOTO_SYNC
    internal const bool PhotoSync = true;
#else
    internal const bool PhotoSync = false;
#endif
#if MAGNOLIE_PHONE_CAMERA
    internal const bool PhoneCamera = true;
#else
    internal const bool PhoneCamera = false;
#endif
}
