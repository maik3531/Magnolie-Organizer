using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native-only, never a request/JSON/IPC capability. The bridge retains its
// document writer lock; the coordinator retains the live source gate while
// invoking the one permitted synchronous file write. No book bytes retained.
internal sealed class NativeHistoricalWriterInvocation(TelefonCoordinator source, PersonalActorHandle handle, string claimToken)
{
    internal Task<JsonObject> WriteAsync(string payload, Action<string> nativeWriter, CancellationToken cancellation = default) =>
        source.WritePersonalActorHistoricalRestoreSaveAsync(handle, claimToken, payload, nativeWriter, cancellation);
}
