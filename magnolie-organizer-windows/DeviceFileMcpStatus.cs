using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    partial void ReadNativeMediaMcpStatus(string peerId, ref JsonObject? result)
        => result = NativeMediaUiStatus(peerId);
}
