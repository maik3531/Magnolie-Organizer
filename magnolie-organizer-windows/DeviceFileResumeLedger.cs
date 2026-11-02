using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record DeviceTransferBinding(string SenderId, string ReceiverId, string SenderIdentitySha256,
    string ReceiverIdentitySha256, string PermissionEpoch, string DestinationToken)
{
    internal void Validate()
    {
        foreach (var value in new[] { SenderIdentitySha256, ReceiverIdentitySha256, PermissionEpoch, DestinationToken })
            if (value is not { Length: 64 } || value.Any(character => !char.IsAsciiHexDigitLower(character)))
                throw new InvalidDataException("invalid_native_file_transfer_binding");
    }
    internal JsonObject Snapshot() => new() { ["sender_id"] = SenderId, ["receiver_id"] = ReceiverId,
        ["sender_identity_sha256"] = SenderIdentitySha256, ["receiver_identity_sha256"] = ReceiverIdentitySha256,
        ["permission_epoch"] = PermissionEpoch, ["destination_token"] = DestinationToken };
}

// In-memory native readback state, not an offer acceptance, network ACK or saved
// destination receipt. Native callbacks own their staging streams and must fail
// on absent files. No personal store or path is opened by this object itself.
internal sealed class DeviceFileResumeLedger
{
    private readonly object gate = new();
    internal DeviceFileManifest Manifest { get; }
    internal DeviceTransferBinding Binding { get; }
    private readonly Func<DeviceTransferBinding?> currentBinding;
    private readonly Dictionary<(string FileId, int Index), string> proofs = [];

    internal DeviceFileResumeLedger(DeviceFileManifest manifest, DeviceTransferBinding binding, Func<DeviceTransferBinding?> currentBinding)
    {
        binding.Validate();
        if (binding.SenderId != manifest.SenderId || binding.ReceiverId != manifest.ReceiverId)
            throw new InvalidDataException("file_manifest_native_peer_mismatch");
        Manifest = manifest; Binding = binding; this.currentBinding = currentBinding;
        Require();
    }
    private void Require()
    {
        if (currentBinding() != Binding) throw new InvalidOperationException("file_transfer_permission_source_or_destination_changed");
    }
    private static string Digest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static int Chunks(DeviceManifestFile file) => (int)((file.Size + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes);
    private (DeviceManifestFile File, long Offset, int Size) Chunk(string fileId, int index)
    {
        Require();
        var file = Manifest.Files.SingleOrDefault(value => value.Id == fileId);
        if (file is null || index < 0 || index >= Chunks(file)) throw new InvalidDataException("invalid_file_transfer_chunk");
        var offset = (long)index * DeviceFileManifest.ChunkBytes;
        return (file, offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, file.Size - offset));
    }

    internal long VerifiedBytes
    {
        get { lock (gate) { Require(); return proofs.Keys.Sum(key => (long)Chunk(key.FileId, key.Index).Size); } }
    }
    internal int[] Missing(string fileId)
    {
        lock (gate)
        {
            Require();
            var file = Manifest.Files.SingleOrDefault(value => value.Id == fileId) ?? throw new InvalidDataException("unknown_file_transfer_member");
            return Enumerable.Range(0, Chunks(file)).Where(index => !proofs.ContainsKey((fileId, index))).ToArray();
        }
    }

    internal void Record(string fileId, int index, byte[] data, Action<string, long, byte[]> writeExact,
        Func<string, long, int, byte[]> readChunk)
    {
        lock (gate)
        {
            var chunk = Chunk(fileId, index);
            if (data is null || data.Length != chunk.Size) throw new InvalidDataException("file_transfer_chunk_size_mismatch");
            var bytes = data.ToArray(); // caller changes cannot race the write/hash witness
            var witness = Digest(bytes); var key = (fileId, index);
            if (proofs.TryGetValue(key, out var previous))
            {
                if (previous != witness) throw new InvalidDataException("changed_duplicate_file_transfer_chunk");
            }
            else writeExact(fileId, chunk.Offset, bytes);
            Require();
            var actual = readChunk(fileId, chunk.Offset, chunk.Size);
            if (actual is null || actual.Length != chunk.Size || Digest(actual) != witness)
                throw new InvalidDataException("file_transfer_chunk_readback_mismatch");
            Require(); proofs[key] = witness;
        }
    }

    internal JsonObject Checkpoint()
    {
        lock (gate)
        {
            Require();
            return new JsonObject { ["format"] = 1, ["manifest_sha256"] = Manifest.Fingerprint, ["binding"] = Binding.Snapshot(),
                ["chunks"] = new JsonArray(proofs.OrderBy(value => value.Key.FileId, StringComparer.Ordinal).ThenBy(value => value.Key.Index)
                    .Select(value => (JsonNode)new JsonObject { ["file_id"] = value.Key.FileId, ["index"] = value.Key.Index,
                        ["sha256"] = value.Value }).ToArray()) };
        }
    }

    internal static DeviceFileResumeLedger Restore(DeviceFileManifest manifest, DeviceTransferBinding binding,
        Func<DeviceTransferBinding?> currentBinding, JsonElement checkpoint, Func<string, long, int, byte[]> readChunk)
    {
        DeviceFileManifest.Exact(checkpoint, "format", "manifest_sha256", "binding", "chunks");
        var expectedBinding = binding.Snapshot();
        var storedBinding = checkpoint.GetProperty("binding");
        DeviceFileManifest.Exact(storedBinding, expectedBinding.Select(value => value.Key).ToArray());
        if (DeviceFileManifest.Integer(checkpoint, "format") != 1 ||
            DeviceFileManifest.Text(checkpoint, "manifest_sha256") != manifest.Fingerprint ||
            expectedBinding.Any(value => DeviceFileManifest.Text(storedBinding, value.Key) != value.Value!.GetValue<string>()))
            throw new InvalidDataException("resume_manifest_or_native_binding_changed");
        var chunks = checkpoint.GetProperty("chunks");
        if (chunks.ValueKind != JsonValueKind.Array || chunks.GetArrayLength() > manifest.Files.Sum(Chunks))
            throw new InvalidDataException("resume_chunk_claim_limit_exceeded");
        var result = new DeviceFileResumeLedger(manifest, binding, currentBinding);
        foreach (var proof in chunks.EnumerateArray())
        {
            DeviceFileManifest.Exact(proof, "file_id", "index", "sha256");
            var id = DeviceFileManifest.Text(proof, "file_id");
            var rawIndex = DeviceFileManifest.Integer(proof, "index");
            var witness = DeviceFileManifest.Text(proof, "sha256");
            if (rawIndex > int.MaxValue || witness.Length != 64 || witness.Any(character => !char.IsAsciiHexDigitLower(character)))
                throw new InvalidDataException("invalid_resume_chunk_claim");
            var index = (int)rawIndex;
            var chunk = result.Chunk(id, index);
            if (result.proofs.ContainsKey((id, index))) throw new InvalidDataException("duplicate_resume_chunk_claim");
            var actual = readChunk(id, chunk.Offset, chunk.Size);
            if (actual is null || actual.Length != chunk.Size || Digest(actual) != witness)
                throw new InvalidDataException("persisted_resume_chunk_changed");
            result.Require(); result.proofs.Add((id, index), witness);
        }
        return result;
    }

    internal DeviceManifestFile VerifiedFile(string fileId, Func<string, long, int, byte[]> readChunk)
    {
        lock (gate)
        {
            if (Missing(fileId).Length != 0) throw new InvalidOperationException("incomplete_file_transfer_member");
            var file = Manifest.Files.Single(value => value.Id == fileId);
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            for (var index = 0; index < Chunks(file); index++)
            {
                var chunk = Chunk(fileId, index);
                var actual = readChunk(fileId, chunk.Offset, chunk.Size);
                if (actual is null || actual.Length != chunk.Size || Digest(actual) != proofs[(fileId, index)])
                    throw new InvalidDataException("verified_file_transfer_chunk_changed");
                hash.AppendData(actual); Require();
            }
            var eof = readChunk(fileId, file.Size, 1);
            if (eof is null || eof.Length != 0 || Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant() != file.Sha256)
                throw new InvalidDataException("file_transfer_final_integrity_mismatch");
            Require(); return file;
        }
    }
}
