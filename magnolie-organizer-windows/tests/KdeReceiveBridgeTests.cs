using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

// Compile the ACTUAL receive bridge partial. Only WinForms' modal boundary,
// the existing command scheduler and service facade are supplied by this host.
// Actual TLS/staging/publication have separate real-backend integration tests.
namespace MagnolieOrganizer.Windows
{
    internal enum DialogResult { OK, Cancel }
    internal sealed class FolderBrowserDialog : IDisposable
    {
        public string Description { get; set; } = "";
        public bool UseDescriptionForTitle { get; set; }
        public bool ShowNewFolderButton { get; set; }
        public string SelectedPath { get; set; } = "C:\\Owned-Fixture";
        internal static int Shown;
        internal static Action? OnShow;
        internal static DialogResult Result = DialogResult.OK;
        public DialogResult ShowDialog(KdeReceiveBridgeForm form) { Shown++; OnShow?.Invoke(); return Result; }
        public void Dispose() { }
    }
    internal sealed class KdeReceiveBridgeForm
    {
        internal readonly List<(string Function, object Payload)> Sent = [];
        internal Task SendAsync(string function, object payload) { Sent.Add((function, payload)); return Task.CompletedTask; }
        internal void ShowTelefonNotification(string title, string text) { }
    }
    internal sealed class KdeReceiveBridgeService
    {
        internal KdeFileReceiveProposal? Proposal;
        internal readonly List<(bool Enabled, string Device, Func<bool>? Permission)> Configurations = [];
        internal readonly List<(string Id, string Directory)> Accepted = [];
        internal readonly List<string> Rejected = [];
        internal void ConfigureFileReceive(bool enabled, string device, string directory, Func<bool>? permission = null) =>
            Configurations.Add((enabled, device, permission));
        internal KdeFileReceiveProposal? CurrentFileReceiveProposal(string id) => Proposal?.Id == id ? Proposal : null;
        internal Task RejectFileReceiveAsync(string id) { Rejected.Add(id); return Task.CompletedTask; }
        internal Task<JsonObject> AcceptFileReceiveAsync(string id, string directory, CancellationToken cancellation)
        { cancellation.ThrowIfCancellationRequested(); Accepted.Add((id, directory)); return Task.FromResult(new JsonObject { ["ok"] = true, ["id"] = id }); }
    }
    internal sealed partial class BridgeDispatcher
    {
        private readonly KdeReceiveBridgeForm form = new();
        private readonly KdeReceiveBridgeService kdeInstance = new();
        private KdeReceiveBridgeService kdeConnectSms => kdeInstance;
        private readonly WindowsPaths paths = new("/tmp/opencode/unused-receive-bridge-no-io");
        private readonly NativeBookOwnerScope actorBookOwner = new();
        private bool disposed = false, currentPlainTextAvailable = true, restoreInProgress = false;
        private string currentPlainText = "{}";
        private readonly Queue<Func<Task>> commands = new();
        internal BridgeDispatcher() { actorBookOwner.SetReady(true); }
        private string? NativeActorBookSource() => actorBookOwner.Current("owned-fixture", currentPlainTextAvailable && !restoreInProgress && !disposed);
        private static string Text(JsonElement value, string key) => value.TryGetProperty(key, out var child) && child.ValueKind == JsonValueKind.String ? child.GetString()! : "";
        private static bool Boolean(JsonElement value, string key) => value.TryGetProperty(key, out var child) && child.ValueKind == JsonValueKind.True;
        private static string T(string text) => text;
        private static Task SafeBackgroundAsync(Func<Task> work) => work();
        private static CancellationTokenSource NetworkDeadline(TimeSpan duration) => new(duration);
        private void QueueNetworkCommand(Func<Task> work, string owner, Func<string, Task>? onAborted = null) => commands.Enqueue(work);

        internal async Task CheckReceiveBridgeAsync()
        {
            using var document = JsonDocument.Parse("{\"einstellungen\":{\"sync\":{\"kdeEmpfang\":{\"dateien\":true,\"geraetId\":\"fixture\",\"ordner\":\"/Linux/Downloads\"}}}}");
            currentPlainText = document.RootElement.GetRawText(); ApplySavedReceiveConfiguration();
            ApplySavedReceiveConfiguration();
            Tests.TestAssert.That(kdeInstance.Configurations.Count == 1, "Unchanged book save revoked receiving by reconfiguration.");
            var permission = kdeInstance.Configurations.Single().Permission!;
            actorBookOwner.RecordSaved("owned-fixture", true, new string('a', 64));
            Tests.TestAssert.That(permission(), "An ordinary saved-book revision canceled stable-owner receive authority.");
            actorBookOwner.Invalidate();
            Tests.TestAssert.That(!permission(), "An old owner token survived lock/restore invalidation.");
            ApplySavedReceiveConfiguration();
            Tests.TestAssert.That(kdeInstance.Configurations.Count == 2 && kdeInstance.Configurations.Last().Permission!(),
                "A new native owner did not receive a separate live permission lease.");
            restoreInProgress = true; Tests.TestAssert.That(!kdeInstance.Configurations.Last().Permission!(), "Restore retained receive permission.");
            restoreInProgress = false;
            async Task Send(string command, string id, bool accept = true)
            {
                using var input = JsonDocument.Parse(JsonSerializer.Serialize(new { cmd = command, id, accept, directory = "C:\\Injected" }));
                await KdeReceiveAsync(input.RootElement);
            }
            var id = new string('a', 32);
            kdeInstance.Proposal = new(id, "fixture", [new("first.txt", 1), new("second.txt", 2)], 3, DateTimeOffset.UtcNow.AddMinutes(5), false);
            FolderBrowserDialog.Shown = 0; FolderBrowserDialog.Result = DialogResult.OK; FolderBrowserDialog.OnShow = null;
            await Send("kde_receive_ziel_waehlen", "not-an-id");
            await Send("kde_receive_ziel_waehlen", new string('b', 32));
            Tests.TestAssert.That(FolderBrowserDialog.Shown == 0, "Invalid/expired IDs opened a destination picker.");
            await Send("kde_receive_decide", id);
            await Send("kde_receive_ziel_waehlen", id);
            Tests.TestAssert.That(FolderBrowserDialog.Shown == 1 && kdeInstance.Accepted.Count == 0 && commands.Count == 1,
                "Duplicate acceptance opened two pickers or copied in the bridge command lane.");
            await commands.Dequeue()();
            Tests.TestAssert.That(kdeInstance.Accepted.Single().Directory == "C:\\Owned-Fixture", "Caller-supplied path bypassed the native folder chooser.");
            kdeInstance.Proposal = kdeInstance.Proposal with { DestinationFixed = true };
            await Send("kde_receive_ziel_waehlen", id); await commands.Dequeue()();
            Tests.TestAssert.That(FolderBrowserDialog.Shown == 1 && kdeInstance.Accepted.Last().Directory == "",
                "Partial retry asked for another folder instead of retaining the native bound destination.");
            kdeInstance.Proposal = kdeInstance.Proposal with { DestinationFixed = false };
            FolderBrowserDialog.Result = DialogResult.Cancel;
            await Send("kde_receive_ziel_waehlen", id); await commands.Dequeue()();
            Tests.TestAssert.That(kdeInstance.Rejected.SequenceEqual([id]) && kdeInstance.Accepted.Count == 2,
                "Canceling native destination selection saved files or failed to reject the offer.");
            FolderBrowserDialog.Result = DialogResult.OK;
            FolderBrowserDialog.OnShow = () => actorBookOwner.Invalidate();
            await Send("kde_receive_ziel_waehlen", id);
            Tests.TestAssert.That(commands.Count == 0, "Owner change during the native chooser retained publication authority.");
            FolderBrowserDialog.OnShow = null;
            await Send("kde_receive_ziel_waehlen", id);
            actorBookOwner.Invalidate(); await commands.Dequeue()();
            Tests.TestAssert.That(kdeInstance.Accepted.Count == 2, "Queued acceptance survived owner revocation before IO started.");
            currentPlainTextAvailable = false;
            Tests.TestAssert.That(!kdeInstance.Configurations.Last().Permission!(), "Lock retained native receiving authority.");
        }
    }
}

namespace MagnolieOrganizer.Windows.Tests
{
    internal static class KdeReceiveBridgeTests
    {
        internal static Task RunAsync() => new BridgeDispatcher().CheckReceiveBridgeAsync();
    }
}
