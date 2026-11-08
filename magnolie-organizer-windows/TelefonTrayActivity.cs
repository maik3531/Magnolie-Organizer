namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    internal NativeSyncActivity TraySyncActivity { get; } = new();
}

internal sealed partial class TelefonConnection
{
    internal NativeSyncActivity? TraySyncActivity { get; set; }
}
