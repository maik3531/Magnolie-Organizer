using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading.Channels;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Native owner's four-control inbox on one actual authenticated parent. Only
/// native activation may bind it; packets cannot construct or replace owners.
/// Callbacks are nonblocking/nonreentrant and safe under the crypto writer.
/// </summary>
internal sealed class PhoneCameraControlBinding : IDisposable
{
    private readonly TelefonConnection parent;
    private readonly Action current;
    private readonly Action retired;
    private readonly object gate = new();
    private readonly Channel<JsonObject> incoming = Channel.CreateBounded<JsonObject>(new BoundedChannelOptions(4)
        { FullMode = BoundedChannelFullMode.Wait, AllowSynchronousContinuations = false });
    private string? requestId, nonce, session;
    private readonly HashSet<string> controls = new(StringComparer.Ordinal);
    private int stopped;
    private Exception? retirementError;
    internal bool IsRetired => Volatile.Read(ref stopped) != 0;
    internal Exception? RetirementError => Volatile.Read(ref retirementError);
    internal PhoneCameraControlBinding(TelefonConnection parent, Action current, Action retired)
    { this.parent = parent; this.current = current; this.retired = retired; }

    internal void RequireCurrent()
    {
        if (IsRetired) throw new InvalidOperationException("webcam_original_owner_retired");
        try
        {
            parent.RequireWebcamBinding(this); current();
            if (IsRetired) throw new InvalidOperationException("webcam_original_owner_retired");
        }
        catch { Dispose(); throw; }
    }
    internal bool Submit(JsonObject message)
    {
        RequireCurrent();
        var body = message["body"]!.AsObject();
        lock (gate)
        {
            if (IsRetired) return false;
            var id = message["message_id"]!.GetValue<string>();
            if (controls.Contains(id)) return false;
            if (body["op"]!.GetValue<string>() == "probe")
            {
                if (requestId is not null || !parent.ClaimWebcamProbe(body)) return false;
                requestId = body["request_id"]!.GetValue<string>(); nonce = body["nonce"]!.GetValue<string>();
            }
            else if (requestId != body["request_id"]!.GetValue<string>() || nonce != body["nonce"]!.GetValue<string>() ||
                session is null || session != body["session"]!.GetValue<string>()) return false;
            if (controls.Count < 16 && incoming.Writer.TryWrite(message.DeepClone().AsObject()))
            { controls.Add(id); return true; }
        }
        Dispose(); return false; // Overflow retires this owner, never the parent.
    }
    // Set by the native worker after handling its probe and creating its own
    // listener. Incoming packets cannot choose or replace this session.
    internal void BindSession(string originalSession)
    {
        RequireCurrent();
        if (!Regex.IsMatch(originalSession, "\\A[0-9a-f]{32}\\z")) throw new ArgumentException("webcam_session_invalid");
        lock (gate)
        {
            if (requestId is null || session is not null || IsRetired) throw new InvalidOperationException("webcam_original_exchange_required");
            session = originalSession;
        }
    }
    internal async ValueTask<JsonObject> ReadAsync(CancellationToken cancellation)
    {
        try
        {
            RequireCurrent(); var value = await incoming.Reader.ReadAsync(cancellation); RequireCurrent(); return value;
        }
        // Cancel only this pending dequeue. The original native owner performs
        // its own final STOP publication and then disposes the binding; no
        // cancelled read may transfer a queued control or restore authority.
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
        catch { Dispose(); throw; }
    }
    internal Task SendAsync(JsonObject report)
    {
        RequireCurrent(); var snapshot = report.DeepClone().AsObject();
        PhoneCameraControl.ValidateMessage(snapshot, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        if (snapshot["kind"]!.GetValue<string>() != PhoneCameraControl.Report) throw new InvalidDataException("webcam_desktop_report_required");
        var body = snapshot["body"]!.AsObject();
        lock (gate)
        {
            if (requestId != body["request_id"]!.GetValue<string>() || nonce != body["nonce"]!.GetValue<string>() ||
                body.ContainsKey("session") && (session is null || session != body["session"]!.GetValue<string>()))
                throw new InvalidOperationException("webcam_original_exchange_required");
        }
        return parent.SendBoundWebcamReportAsync(this, snapshot);
    }
    public void Dispose()
    {
        if (Interlocked.Exchange(ref stopped, 1) != 0) return;
        incoming.Writer.TryComplete(new IOException("webcam_original_owner_retired"));
        while (incoming.Reader.TryRead(out _)) { }
        parent.ReleaseWebcamBinding(this);
        // Native callback only signals; never joins its own worker. A broken
        // owner callback must not prevent the original parent from closing.
        try { retired(); }
        catch (Exception error) { Volatile.Write(ref retirementError, error); }
    }
}
