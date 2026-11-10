using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TraySyncActivityTests
{
    internal static async Task WriterAsync()
    {
        foreach (var kind in new[] { "personal_sync.batch", "personal_sync.time_batch", "personal_sync.actor_data", "personal_sync.settings", "personal_sync.time_settings" })
        foreach (var fail in new[] { false, true })
        {
            var root = Path.Combine(Path.GetTempPath(), "tray-sync-io-" + Guid.NewGuid().ToString("N"));
            try
            {
                var store = new TelefonStore(new WindowsPaths(root), new byte[32]);
                using var ownPool = new OwnedTelefonPool(store);
                var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Tray IO fixture", new byte[32]);
                store.SavePeers([peer]);
                var activity = new NativeSyncActivity();
                using var stream = new BlockingWrite(fail);
                using var connection = new TelefonConnection(peer, stream, new byte[32], new byte[72], store,
                    (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi") { TraySyncActivity = activity };
                var message = new JsonObject { ["type"] = "message", ["kind"] = kind, ["body"] = new JsonObject() };
                var sending = connection.SendPlainAsync(message);
                try
                {
                    await stream.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
                    TestAssert.That(activity.Active == TraySyncFrames.IsData(message), "Actual writer activity confused a setting with data.");
                    using var other = activity.Enter();
                    stream.Release.TrySetResult();
                    if (fail) await TestAssert.ThrowsAsync<IOException>(() => sending, "Fixture write failure disappeared.");
                    else { await sending; TestAssert.That(stream.Output.Length > 4, "Actual secure envelope was not written."); }
                    TestAssert.That(activity.Active, "This IO's end hid another actual owner.");
                    other.Dispose(); TestAssert.That(!activity.Active, "Completed/failed writer retained activity.");
                }
                finally { stream.Release.TrySetResult(); }
            }
            finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
        }
        foreach (var kind in new[] { "personal_sync.custom_settings", "capabilities.update", "personal_sync.not_real", "file_transfer.chunk" })
            TestAssert.That(!TraySyncFrames.IsData(new() { ["type"] = "message", ["kind"] = kind }), "Non-data frame counted as sync.");
    }

    private sealed class BlockingWrite(bool fail) : Stream
    {
        internal TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal MemoryStream Output { get; } = new();
        public override async ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
        {
            Entered.TrySetResult(); await Release.Task.WaitAsync(cancellationToken);
            if (fail) throw new IOException("actual native writer failure fixture");
            await Output.WriteAsync(buffer, cancellationToken);
        }
        public override bool CanRead => false;
        public override bool CanSeek => false;
        public override bool CanWrite => true;
        public override long Length => Output.Length;
        public override long Position { get => Output.Position; set => throw new NotSupportedException(); }
        public override void Flush() { }
        public override Task FlushAsync(CancellationToken cancellationToken) => Task.CompletedTask;
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        protected override void Dispose(bool disposing) { if (disposing) Release.TrySetResult(); base.Dispose(disposing); }
    }
}
