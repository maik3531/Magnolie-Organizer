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
    internal static bool Hash(string? value) => value is { Length: 64 } && value.All(char.IsAsciiHexDigitLower);
    internal static bool Identity(string? value) => value is { Length: >= 16 and <= 160 } &&
        value.All(character => char.IsAsciiLetterOrDigit(character) || character is '_' or '-');
    internal static string Digest(string domain, JsonNode value) => Convert.ToHexString(SHA256.HashData(
        Encoding.UTF8.GetBytes(domain).Concat(TelefonCrypto.Canonical(value)).ToArray())).ToLowerInvariant();
    internal static InvalidDataException Error(string code) => new(code);
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
    internal NativeLocalFileGrant(DeviceFileGrantState grants, object owner, bool handlersReady)
    {
        if (owner is null || !handlersReady && (grants.SendFiles || grants.ReceiveFiles)) throw DeviceFileControl.Error("file_control_native_local_state_required");
        Grants = grants; Owner = owner; HandlersReady = handlersReady;
    }
}

internal sealed record NativeFileControlPeer(string PeerId, string IdentitySha256, object Owner,
    bool Ready, bool Paired, bool OwnDevice, bool RemoteOwnDevice, bool ControlSupported)
{
    internal bool Allowed => Owner is not null && DeviceFileControl.Identity(PeerId) && DeviceFileControl.Hash(IdentitySha256) &&
        Ready && Paired && OwnDevice && RemoteOwnDevice && ControlSupported;
}

internal sealed class NativeFileControlSession : IDisposable
{
    private readonly NativeFileControlIdentity identity;
    private readonly Func<NativeFileControlPeer?> currentPeer;
    private readonly Func<NativeLocalFileGrant?> currentLocal;
    private readonly NativeFileControlPeer peer;
    private NativeLocalFileGrant local;
    private readonly string sessionEpoch = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
    private readonly object gate = new();
    private long sequence;
    private DeviceFileControlPacket? remote;
    private DeviceFileControlPacket? pending;
    private DeviceFileGrantState? sentGrants;
    private string? sentEcho;
    private bool faulted;
    internal NativeFileControlSession(NativeFileControlIdentity identity, Func<NativeFileControlPeer?> currentPeer, Func<NativeLocalFileGrant?> currentLocal)
    {
        this.identity = identity; this.currentPeer = currentPeer; this.currentLocal = currentLocal;
        peer = currentPeer() ?? throw DeviceFileControl.Error("file_control_native_scope_required");
        local = currentLocal() ?? throw DeviceFileControl.Error("file_control_native_scope_required");
        if (!peer.Allowed || peer.PeerId == identity.DeviceId) throw DeviceFileControl.Error("file_control_native_scope_required");
    }
    private (NativeFileControlPeer Peer, NativeLocalFileGrant Local)? Scope()
    {
        var nextPeer = currentPeer(); var nextLocal = currentLocal();
        if (nextPeer is not null && (!ReferenceEquals(nextPeer.Owner, peer.Owner) || nextPeer.PeerId != peer.PeerId || nextPeer.IdentitySha256 != peer.IdentitySha256) ||
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
            pending = new(scope.Local.Grants, sessionEpoch, ++sequence, remote?.Challenge);
            return pending;
        }
    }
    internal void MarkSent(DeviceFileControlPacket packet)
    {
        lock (gate)
        {
            var scope = Scope();
            if (scope is null || !ReferenceEquals(packet, pending) || packet is null || !packet.Grants.Same(scope.Value.Local.Grants) || packet.Echo != remote?.Challenge)
                throw DeviceFileControl.Error("file_control_invalid_native_send_completion");
            sentGrants = packet.Grants; sentEcho = packet.Echo; pending = null;
        }
    }
    internal bool NeedsPacket
    {
        get { lock (gate) { var scope = Scope(); return scope is not null && (!scope.Value.Local.Grants.Same(sentGrants) || remote is not null && sentEcho != remote.Challenge); } }
    }
    internal bool ObserveRemote(DeviceFileControlPacket packet, NativeFileControlPeer boundPeer)
    {
        lock (gate)
        {
            if (Scope() is null || !boundPeer.Allowed || !ReferenceEquals(boundPeer.Owner, peer.Owner) || boundPeer.PeerId != peer.PeerId || boundPeer.IdentitySha256 != peer.IdentitySha256)
                throw DeviceFileControl.Error("file_control_native_scope_changed");
            if (remote is not null)
            {
                var same = packet.SessionEpoch == remote.SessionEpoch;
                if (same && packet.Sequence < remote.Sequence || packet.Grants.Revision < remote.Grants.Revision) throw DeviceFileControl.Error("file_control_stale_packet");
                if (same && packet.Sequence == remote.Sequence && !packet.Same(remote) || packet.Grants.Revision == remote.Grants.Revision && !packet.Grants.SamePermission(remote.Grants))
                { faulted = true; throw DeviceFileControl.Error("file_control_equivocation"); }
                if (same && packet.Same(remote)) return false;
            }
            remote = packet;
            return true;
        }
    }
    internal DeviceTransferBinding? Binding(string destinationToken, bool senderIsLocal = false)
    {
        lock (gate)
        {
            var scope = Scope(); if (scope is null || remote is null) return null;
            var (current, state) = scope.Value;
            var challenge = new DeviceFileControlPacket(state.Grants, sessionEpoch, 1, null).Challenge;
            if (!state.HandlersReady || remote.Echo != challenge || !state.Grants.Same(sentGrants) || sentEcho != remote.Challenge ||
                !state.Grants.ManifestVersions.Contains(1) || !remote.Grants.ManifestVersions.Contains(1) ||
                !(senderIsLocal ? state.Grants.SendFiles && remote.Grants.ReceiveFiles : remote.Grants.SendFiles && state.Grants.ReceiveFiles)) return null;
            var entries = new[] { (Id: identity.DeviceId, Value: new JsonArray(identity.DeviceId, identity.IdentitySha256, state.Grants.PermissionWire())),
                (Id: current.PeerId, Value: new JsonArray(current.PeerId, current.IdentitySha256, remote.Grants.PermissionWire())) };
            var epoch = DeviceFileControl.Digest("magnolie-file-permission-v1\0", new JsonArray(entries.OrderBy(entry => entry.Id, StringComparer.Ordinal).Select(entry => (JsonNode)entry.Value).ToArray()));
            var result = senderIsLocal ? new DeviceTransferBinding(identity.DeviceId, current.PeerId, identity.IdentitySha256, current.IdentitySha256, epoch, destinationToken)
                : new DeviceTransferBinding(current.PeerId, identity.DeviceId, current.IdentitySha256, identity.IdentitySha256, epoch, destinationToken);
            result.Validate();
            return result;
        }
    }
    public void Dispose() { lock (gate) { faulted = true; remote = null; pending = null; } }
}
