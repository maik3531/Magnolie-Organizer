using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Dedicated file controls only. Discovery 21 stays unadvertised until actual
// native handlers exist. No global notes/contact grants, stores, I/O or worker.
internal static class DeviceFileControl
{
    internal const string Kind = "file_transfer.control";
    internal const int DiscoveryVersion = 21;
    internal const long MaximumRevision = 9007199254740991;
    internal const int MaximumWireBytes = 8192;
    internal const long MaximumTtlMs = 60000;
    internal static bool Hash(string? value) => NativeFilePairingIdentity.Hash(value);
    internal static bool Identity(string? value) => value is { Length: >= 16 and <= 160 } &&
        value.All(character => char.IsAsciiLetterOrDigit(character) || character is '_' or '-');
    internal static string Digest(string domain, JsonNode value) => Convert.ToHexString(SHA256.HashData(
        Encoding.UTF8.GetBytes(domain).Concat(TelefonCrypto.Canonical(value)).ToArray())).ToLowerInvariant();
    internal static InvalidDataException Error(string code) => new(code);
    internal static string PairingEpoch(byte[] transcript) => NativeFilePairingIdentity.Epoch(transcript);
    internal static string? CurrentPairingEpoch(TelefonPeer? peer, bool ownDevice, bool remoteOwnDevice) =>
        peer is { State: "paired" } && ownDevice && remoteOwnDevice && Hash(peer.FilePairingEpoch) ? peer.FilePairingEpoch : null;
}

internal sealed class DeviceFileGrantState
{
    internal long Revision { get; }
    internal string Epoch { get; }
    internal bool SendFiles { get; }
    internal bool ReceiveFiles { get; }
    internal IReadOnlyList<int> ManifestVersions { get; }
    internal DeviceFileGrantState(long revision, string epoch, bool sendFiles = false, bool receiveFiles = false, IEnumerable<int>? versions = null)
    {
        var values = (versions ?? [1]).ToArray();
        if (revision is < 1 or > DeviceFileControl.MaximumRevision || !DeviceFileControl.Hash(epoch) || values.Length is < 1 or > 8 ||
            values.Any(value => value is < 1 or > 65535) || !values.Order().Distinct().SequenceEqual(values))
            throw DeviceFileControl.Error("file_control_invalid_grant_state");
        Revision = revision; Epoch = epoch; SendFiles = sendFiles; ReceiveFiles = receiveFiles;
        ManifestVersions = Array.AsReadOnly(values);
    }
    internal JsonObject PermissionWire() => new() { ["grant_revision"] = Revision, ["grant_epoch"] = Epoch,
        ["send_files"] = SendFiles, ["receive_files"] = ReceiveFiles };
    internal JsonObject Wire()
    {
        var value = PermissionWire(); value["manifest_versions"] = new JsonArray(ManifestVersions.Select(version => (JsonNode?)JsonValue.Create(version)).ToArray());
        return value;
    }
    internal bool SamePermission(DeviceFileGrantState other) => Revision == other.Revision && Epoch == other.Epoch && SendFiles == other.SendFiles && ReceiveFiles == other.ReceiveFiles;
    internal bool Same(DeviceFileGrantState? other) => other is not null && SamePermission(other) && ManifestVersions.SequenceEqual(other.ManifestVersions);
}

internal sealed class DeviceFileControlPacket
{
    internal DeviceFileGrantState Grants { get; }
    internal string SessionEpoch { get; }
    internal long Sequence { get; }
    internal string? Echo { get; }
    internal DeviceFileControlPacket(DeviceFileGrantState grants, string sessionEpoch, long sequence, string? echo)
    {
        if (!DeviceFileControl.Hash(sessionEpoch) || sequence is < 1 or > DeviceFileControl.MaximumRevision || echo is not null && !DeviceFileControl.Hash(echo))
            throw DeviceFileControl.Error("file_control_invalid_packet");
        Grants = grants; SessionEpoch = sessionEpoch; Sequence = sequence; Echo = echo;
    }
    internal JsonObject Wire()
    {
        var value = Grants.Wire(); value["format"] = 1; value["session_epoch"] = SessionEpoch; value["sequence"] = Sequence; value["echo"] = Echo;
        return value;
    }
    internal string Challenge
    {
        get
        {
            var value = Grants.Wire(); value["format"] = 1; value["session_epoch"] = SessionEpoch;
            return DeviceFileControl.Digest("magnolie-file-control-challenge-v1\0", value);
        }
    }
    internal bool Same(DeviceFileControlPacket other) => Grants.Same(other.Grants) && SessionEpoch == other.SessionEpoch && Sequence == other.Sequence && Echo == other.Echo;
    internal static DeviceFileControlPacket Parse(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "format", "grant_revision", "grant_epoch", "send_files", "receive_files", "manifest_versions", "session_epoch", "sequence", "echo");
        if (TelefonProtocolContract.Integer(value["format"]) != 1 || value["manifest_versions"] is not JsonArray versions || versions.Count is < 1 or > 8)
            throw DeviceFileControl.Error("file_control_invalid_packet");
        string Text(string key) => value[key] is JsonValue item && item.TryGetValue<string>(out var text) && text is not null
            ? text : throw DeviceFileControl.Error("file_control_invalid_packet");
        bool Flag(string key) => value[key] is JsonValue item && item.TryGetValue<bool>(out var flag)
            ? flag : throw DeviceFileControl.Error("file_control_invalid_packet");
        var numbers = versions.Select(element =>
        {
            var number = TelefonProtocolContract.Integer(element);
            return number is >= 1 and <= 65535 ? (int)number : throw DeviceFileControl.Error("file_control_invalid_packet");
        }).ToArray();
        return new(new DeviceFileGrantState(TelefonProtocolContract.Integer(value["grant_revision"]), Text("grant_epoch"), Flag("send_files"), Flag("receive_files"), numbers),
            Text("session_epoch"), TelefonProtocolContract.Integer(value["sequence"]), value["echo"] is null ? null : Text("echo"));
    }
}

internal sealed record NativeFileControlIdentity
{
    internal string DeviceId { get; }
    internal string IdentitySha256 { get; }
    internal NativeFileControlIdentity(string deviceId, string identitySha256)
    {
        if (!DeviceFileControl.Identity(deviceId) || !DeviceFileControl.Hash(identitySha256)) throw DeviceFileControl.Error("file_control_invalid_identity");
        DeviceId = deviceId; IdentitySha256 = identitySha256;
    }
}

internal sealed class NativeLocalFileGrant
{
    internal DeviceFileGrantState Grants { get; }
    internal object Owner { get; }
    internal bool HandlersReady { get; }
    internal bool PolicyReady { get; }
    internal NativeLocalFileGrant(DeviceFileGrantState grants, object owner, bool handlersReady, bool policyReady = true)
    {
        if (owner is null || !handlersReady && (grants.SendFiles || grants.ReceiveFiles)) throw DeviceFileControl.Error("file_control_native_local_state_required");
        Grants = grants; Owner = owner; HandlersReady = handlersReady;
        PolicyReady = policyReady;
    }
}

internal sealed record NativeFileControlPeer(string PeerId, string IdentitySha256, object Owner,
    bool Ready, bool Paired, bool OwnDevice, bool RemoteOwnDevice, bool ControlSupported, string? PairingEpoch = null)
{
    internal bool Allowed => Owner is not null && DeviceFileControl.Identity(PeerId) && DeviceFileControl.Hash(IdentitySha256) &&
        Ready && Paired && OwnDevice && RemoteOwnDevice && ControlSupported && (PairingEpoch is null || DeviceFileControl.Hash(PairingEpoch));
}

// Only this native object identity can finish/retry its metadata command. It has
// no JSON representation and grants neither a source READ nor Saved completion.
internal sealed class NativeReceiverCommandTicket { }

internal sealed class NativeFileControlSession : IDisposable
{
    internal sealed class SourceRunLease
    {
        internal readonly string RunId, Version, MediaType, RemoteSession;
        internal bool Invalidated;
        internal SourceRunLease(string runId, string version, string mediaType, string remoteSession)
        { RunId = runId; Version = version; MediaType = mediaType; RemoteSession = remoteSession; }
        internal bool GrantsReadAuthority => false;
    }
    private sealed class ReceiverCommandScope(DeviceFileGrantState local, DeviceFileControlPacket remote, long now, SourceRunLease? cleanup = null)
    {
        internal readonly DeviceFileGrantState LocalPermission = local;
        internal readonly string RemoteSession = remote.SessionEpoch;
        internal readonly long RemoteSequence = remote.Sequence, Issued = now, Expires = now + DeviceFileControl.MaximumTtlMs;
        internal long LastChecked = now;
        internal bool Invalidated;
        internal readonly SourceRunLease? Cleanup = cleanup;
    }
    private readonly NativeFileControlIdentity identity;
    private readonly Func<NativeFileControlPeer?> currentPeer;
    private readonly Func<NativeLocalFileGrant?> currentLocal;
    private readonly NativeFileControlPeer peer;
    private NativeLocalFileGrant local;
    private readonly string sessionEpoch = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
    private readonly object gate = new();
    private readonly Func<long> monotonicMs;
    private readonly Dictionary<NativeReceiverCommandTicket, ReceiverCommandScope> receiverCommands = new();
    private readonly HashSet<SourceRunLease> sourceRuns = new();
    private long sequence;
    private DeviceFileControlPacket? remote;
    private DeviceFileControlPacket? pending;
    private DeviceFileGrantState? sentGrants;
    private string? sentEcho;
    private bool faulted;
    internal NativeFileControlSession(NativeFileControlIdentity identity, Func<NativeFileControlPeer?> currentPeer, Func<NativeLocalFileGrant?> currentLocal,
        Func<long>? monotonicMs = null)
    {
        this.identity = identity; this.currentPeer = currentPeer; this.currentLocal = currentLocal;
        this.monotonicMs = monotonicMs ?? (() => Environment.TickCount64);
        peer = currentPeer() ?? throw DeviceFileControl.Error("file_control_native_scope_required");
        local = currentLocal() ?? throw DeviceFileControl.Error("file_control_native_scope_required");
        if (!peer.Allowed || peer.PeerId == identity.DeviceId) throw DeviceFileControl.Error("file_control_native_scope_required");
    }
    private (NativeFileControlPeer Peer, NativeLocalFileGrant Local)? Scope()
    {
        if (faulted) return null;
        var nextPeer = currentPeer(); var nextLocal = currentLocal();
        if (nextPeer is not null && (!ReferenceEquals(nextPeer.Owner, peer.Owner) || nextPeer.PeerId != peer.PeerId || nextPeer.IdentitySha256 != peer.IdentitySha256 || nextPeer.PairingEpoch != peer.PairingEpoch) ||
            nextLocal is not null && !ReferenceEquals(nextLocal.Owner, local.Owner)) faulted = true;
        if (faulted || nextPeer?.Allowed != true || nextLocal is null) return null;
        if (nextLocal.Grants.Revision < local.Grants.Revision || nextLocal.Grants.Revision == local.Grants.Revision && !nextLocal.Grants.SamePermission(local.Grants))
        { faulted = true; return null; }
        local = nextLocal;
        return (nextPeer, nextLocal);
    }
    internal DeviceFileControlPacket Packet()
    {
        lock (gate)
        {
            var scope = Scope() ?? throw DeviceFileControl.Error("file_control_native_scope_changed");
            if (sequence >= DeviceFileControl.MaximumRevision) throw DeviceFileControl.Error("file_control_native_scope_changed");
            if (!scope.Local.PolicyReady) throw DeviceFileControl.Error("file_control_policy_pending");
            pending = new(scope.Local.Grants, sessionEpoch, ++sequence, remote?.Challenge);
            return pending;
        }
    }
    internal void MarkSent(DeviceFileControlPacket packet)
    {
        lock (gate)
        {
            var scope = Scope();
            if (scope is null || !scope.Value.Local.PolicyReady || !ReferenceEquals(packet, pending) || packet is null || !packet.Grants.Same(scope.Value.Local.Grants) || packet.Echo != remote?.Challenge)
                throw DeviceFileControl.Error("file_control_invalid_native_send_completion");
            sentGrants = packet.Grants; sentEcho = packet.Echo; pending = null;
        }
    }
    internal bool NeedsPacket
    {
        get { lock (gate) { var scope = Scope(); return scope is not null && scope.Value.Local.PolicyReady && (!scope.Value.Local.Grants.Same(sentGrants) || remote is not null && sentEcho != remote.Challenge); } }
    }
    internal bool ObserveRemote(DeviceFileControlPacket packet, NativeFileControlPeer boundPeer)
    {
        lock (gate)
        {
            if (Scope() is null || !boundPeer.Allowed || !ReferenceEquals(boundPeer.Owner, peer.Owner) || boundPeer.PeerId != peer.PeerId || boundPeer.IdentitySha256 != peer.IdentitySha256 || boundPeer.PairingEpoch != peer.PairingEpoch)
                throw DeviceFileControl.Error("file_control_native_scope_changed");
            if (remote is not null)
            {
                var same = packet.SessionEpoch == remote.SessionEpoch;
                if (same && packet.Sequence < remote.Sequence || packet.Grants.Revision < remote.Grants.Revision) throw DeviceFileControl.Error("file_control_stale_packet");
                if (same && packet.Sequence == remote.Sequence && !packet.Same(remote) || packet.Grants.Revision == remote.Grants.Revision && !packet.Grants.SamePermission(remote.Grants))
                { faulted = true; throw DeviceFileControl.Error("file_control_equivocation"); }
                if (same && packet.Same(remote)) return false;
                if (!same)
                {
                    foreach (var held in receiverCommands.Values) held.Invalidated = true;
                    foreach (var run in sourceRuns) run.Invalidated = true;
                }
            }
            remote = packet;
            return true;
        }
    }
    private (NativeFileControlPeer Peer, NativeLocalFileGrant Local, DeviceFileControlPacket Remote)? Agreed()
    {
        var scope = Scope(); var observed = remote;
        if (scope is null || observed is null) return null;
        var (current, state) = scope.Value;
        var challenge = new DeviceFileControlPacket(state.Grants, sessionEpoch, 1, null).Challenge;
        if (!state.HandlersReady || !state.PolicyReady || observed.Echo != challenge || !state.Grants.Same(sentGrants) || sentEcho != observed.Challenge ||
            !state.Grants.ManifestVersions.Contains(1) || !observed.Grants.ManifestVersions.Contains(1)) return null;
        return (current, state, observed);
    }

    internal NativeReceiverCommandTicket ReceiverCommandTicket()
    {
        lock (gate)
        {
            var agreed = Agreed();
            if (agreed is null || !agreed.Value.Local.Grants.ReceiveFiles || receiverCommands.Count != 0)
                throw DeviceFileControl.Error("file_control_receiver_command_not_ready");
            var at = monotonicMs();
            if (at < 0 || at > long.MaxValue - DeviceFileControl.MaximumTtlMs)
                throw DeviceFileControl.Error("file_control_receiver_command_clock");
            var ticket = new NativeReceiverCommandTicket();
            receiverCommands.Add(ticket, new(agreed.Value.Local.Grants, agreed.Value.Remote, at));
            return ticket;
        }
    }

    internal SourceRunLease RetainSourceRun(NativeReceiverCommandTicket ticket, string runId, string version, string mediaType)
    {
        lock (gate)
        {
            if (!ReceiverCommandCurrent(ticket) || receiverCommands[ticket].Cleanup is not null ||
                !TelefonProtocolContract.IsUuidV4(runId) || !DeviceFileControl.Hash(version) || mediaType is not ("images" or "video") ||
                sourceRuns.Count >= 4 || sourceRuns.Any(run => run.RunId == runId))
                throw DeviceFileControl.Error("file_control_original_source_run_required");
            var lease = new SourceRunLease(runId, version, mediaType, receiverCommands[ticket].RemoteSession);
            sourceRuns.Add(lease); return lease;
        }
    }

    private bool SourceRunCurrent(SourceRunLease lease)
    {
        var scope = Scope();
        return sourceRuns.Contains(lease) && !lease.Invalidated && scope is not null && remote is not null && remote.SessionEpoch == lease.RemoteSession;
    }

    internal NativeReceiverCommandTicket CleanupCommandTicket(SourceRunLease lease)
    {
        lock (gate)
        {
            if (!SourceRunCurrent(lease) || receiverCommands.Count != 0) throw DeviceFileControl.Error("file_control_original_source_run_required");
            var at = monotonicMs();
            if (at < 0 || at > long.MaxValue - DeviceFileControl.MaximumTtlMs) throw DeviceFileControl.Error("file_control_receiver_command_clock");
            var ticket = new NativeReceiverCommandTicket();
            receiverCommands.Add(ticket, new(local.Grants, remote!, at, lease)); return ticket;
        }
    }

    internal void ReleaseSourceRun(SourceRunLease lease)
    {
        lock (gate)
        {
            if (!sourceRuns.Remove(lease)) throw DeviceFileControl.Error("file_control_foreign_source_run");
        }
    }

    // A captured control position is not current authority or an ACK receipt.
    internal (string SessionEpoch, long Sequence) ReceiverCommandWitness(NativeReceiverCommandTicket ticket)
    {
        lock (gate)
        {
            if (ticket is null || !receiverCommands.TryGetValue(ticket, out var held))
                throw DeviceFileControl.Error("file_control_foreign_receiver_command_ticket");
            return (held.RemoteSession, held.RemoteSequence);
        }
    }

    internal (string SessionEpoch, long Sequence)? RemoteControlWitness()
    {
        lock (gate) return Scope() is not null && remote is not null ? (remote.SessionEpoch, remote.Sequence) : null;
    }

    // Deny-only comparison for a native metadata dialog's original position.
    // No Scope callback or transport monitor inside a protected-store CAS.
    // The caller must separately retain/recheck its native peer, book, full
    // settings and local choices. This is NOT agreement or a data grant.
    internal bool NativeMetadataPositionUnchanged((string SessionEpoch, long Sequence)? original)
    {
        var observed = Volatile.Read(ref remote);
        return !Volatile.Read(ref faulted) && (observed is null ? original is null :
            original is { } position && observed.SessionEpoch == position.SessionEpoch && observed.Sequence == position.Sequence);
    }

    internal bool ReceiverCommandCurrent(NativeReceiverCommandTicket? ticket)
    {
        lock (gate)
        {
            if (ticket is null || !receiverCommands.TryGetValue(ticket, out var held) || held.Invalidated) return false;
            try
            {
                var scope = Scope(); var observed = remote; var at = monotonicMs();
                if (held.Cleanup is not null)
                {
                    if (at < held.LastChecked || at >= held.Expires || !SourceRunCurrent(held.Cleanup))
                    { held.Invalidated = true; return false; }
                    held.LastChecked = at; return true;
                }
                if (scope is null || observed is null || at < held.LastChecked || at >= held.Expires ||
                    !scope.Value.Local.HandlersReady || !scope.Value.Local.PolicyReady || !scope.Value.Local.Grants.ReceiveFiles ||
                    !scope.Value.Local.Grants.SamePermission(held.LocalPermission) || observed.SessionEpoch != held.RemoteSession ||
                    !scope.Value.Local.Grants.ManifestVersions.Contains(1) || !observed.Grants.ManifestVersions.Contains(1))
                { held.Invalidated = true; return false; }
                held.LastChecked = at;
                // The source may change its send policy DURING this exact
                // configure command. The metadata reply can finish before its
                // new data echo; it cannot make Binding() return data authority.
                return true;
            }
            catch { held.Invalidated = true; throw; }
        }
    }

    internal void FinishReceiverCommand(NativeReceiverCommandTicket ticket)
    {
        lock (gate)
            if (ticket is null || !receiverCommands.Remove(ticket))
                throw DeviceFileControl.Error("file_control_foreign_receiver_command_ticket");
    }

    internal DeviceTransferBinding? Binding(string destinationToken, bool senderIsLocal = false)
    {
        lock (gate)
        {
            var agreed = Agreed(); if (agreed is null) return null;
            var (current, state, observed) = agreed.Value;
            if (!(senderIsLocal ? state.Grants.SendFiles && observed.Grants.ReceiveFiles : observed.Grants.SendFiles && state.Grants.ReceiveFiles)) return null;
            var entries = new[] { (Id: identity.DeviceId, Value: new JsonArray(identity.DeviceId, identity.IdentitySha256, state.Grants.PermissionWire())),
                (Id: current.PeerId, Value: new JsonArray(current.PeerId, current.IdentitySha256, observed.Grants.PermissionWire())) };
            var epoch = DeviceFileControl.Digest("magnolie-file-permission-v1\0", new JsonArray(entries.OrderBy(entry => entry.Id, StringComparer.Ordinal).Select(entry => (JsonNode)entry.Value).ToArray()));
            var result = senderIsLocal ? new DeviceTransferBinding(identity.DeviceId, current.PeerId, identity.IdentitySha256, current.IdentitySha256, epoch, destinationToken)
                : new DeviceTransferBinding(current.PeerId, identity.DeviceId, current.IdentitySha256, identity.IdentitySha256, epoch, destinationToken);
            result.Validate();
            return result;
        }
    }
    public void Dispose()
    {
        lock (gate)
        {
            faulted = true; remote = null; pending = null;
            foreach (var held in receiverCommands.Values) held.Invalidated = true;
        }
    }
}
