using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Test-host-only implementation; tests/** is excluded from the actual product.
internal sealed partial class TelefonConnection
{
    internal Action<JsonObject, Task>? WebcamWriterWaitProbe;
    partial void ObserveNativeWebcamWriterWait(JsonObject snapshot, Task waiting) => WebcamWriterWaitProbe?.Invoke(snapshot, waiting);
}
