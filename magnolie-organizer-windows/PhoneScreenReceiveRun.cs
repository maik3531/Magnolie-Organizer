using System;
using System.IO;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;

namespace MagnolieOrganizer.Windows;

/// <summary>Join the original accepted viewing socket, proof, protected SEND,
/// and a single authorized viewer. The protocol caller supplies the live
/// original WLAN/window guards, not a saved permission or a renderer flag.</summary>
internal sealed class PhoneScreenReceiveRun
{
    private readonly object gate = new();
    private readonly Socket socket;
    private readonly byte[] session, secret;
    private readonly int width, height;
    private readonly Action requireOriginal, requireSend;
    private readonly Func<Action, Task> publishSend;
    private readonly Func<byte[], bool> present;
    private readonly Action ended;
    private readonly TaskCompletionSource drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private bool started;
    private int stopping;
    private Exception? cleanupError;
    private Exception? failure;

    internal Task Drained => drained.Task;
    internal Exception? Failure => Volatile.Read(ref failure);

    internal PhoneScreenReceiveRun(Socket socket, ReadOnlySpan<byte> session, ReadOnlySpan<byte> secret, int width, int height,
        Action requireOriginal, Action requireSend, Func<Action, Task> publishSend, Func<byte[], bool> present, Action ended)
    {
        this.socket = socket;
        this.session = session.ToArray();
        this.secret = secret.ToArray();
        this.width = width;
        this.height = height;
        this.requireOriginal = requireOriginal;
        this.requireSend = requireSend;
        this.publishSend = publishSend;
        this.present = present;
        this.ended = ended;
    }

    internal void Start()
    {
        lock (gate)
        {
            if (started || Volatile.Read(ref stopping) != 0) throw new InvalidOperationException("screen_receive_owner_already_used");
            started = true;
            _ = Task.Run(RunAsync);
        }
    }

    internal void Stop()
    {
        bool neverStarted;
        lock (gate)
        {
            if (Interlocked.Exchange(ref stopping, 1) != 0) return;
            // Interrupt only data IO, never the authenticated phone control stream.
            try { socket.Shutdown(SocketShutdown.Both); }
            catch (SocketException) { }
            catch (ObjectDisposedException) { }
            try { socket.Dispose(); }
            catch (Exception error) { cleanupError = error; }
            neverStarted = !started;
        }
        if (neverStarted) Finish();
    }

    private void Current()
    {
        if (Volatile.Read(ref stopping) != 0) throw new OperationCanceledException("screen_receive_owner_retired");
        requireOriginal();
        if (Volatile.Read(ref stopping) != 0) throw new OperationCanceledException("screen_receive_owner_retired");
    }

    private async Task RunAsync()
    {
        try
        {
            using var lane = new PhoneScreenViewLane(socket, session, secret, width, height, Current, requireSend);
            CryptographicOperations.ZeroMemory(secret);
            lane.Prove();
            Current();
            await publishSend(Current).ConfigureAwait(false); // Native caller performs the bounded, guarded control write.
            Current();
            while (true)
            {
                byte[] bytes = lane.Receive();
                try
                {
                    if (bytes.Length == 0) continue; // Authenticated heartbeat, no rendering.
                    Current(); requireSend();
                    if (!present(bytes)) throw new IOException("screen_original_window_retired");
                }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
        }
        catch (Exception error)
        {
            if (Volatile.Read(ref stopping) == 0) Volatile.Write(ref failure, error);
        }
        finally { Stop(); Finish(); }
    }

    private void Finish()
    {
        CryptographicOperations.ZeroMemory(secret);
        try { ended(); }
        catch (Exception error) { cleanupError ??= error; }
        if (cleanupError is { } failed) drained.TrySetException(failed);
        else drained.TrySetResult();
    }
}
