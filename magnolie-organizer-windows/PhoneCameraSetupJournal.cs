using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

// Setup accounting ONLY. A receipt is neither proof of installed COM ownership
// nor a capture/SourceBindingProof. No installer/registry/process is invoked here.
internal sealed partial class PhoneCameraSetupJournal : IDisposable
{
    internal enum Phase { Prepared, SourceIntent, SourceInstalled, MicrophoneIntent, RebootRequired, Failed, UnknownPending }
    internal sealed record Audit(Guid Transaction, string SourceSha256, string HelperSha256, Phase LastPhase,
        string? OwnMicrophoneInstance, bool SourceStarted, bool SourceConfirmed, bool MicrophoneStarted)
    {
        // Every pre-completion interruption needs review, even if the last
        // record merely says Prepared. Existing journals NEVER authorize retry.
        internal Phase Outcome => LastPhase is Phase.RebootRequired or Phase.Failed ? LastPhase : Phase.UnknownPending;
        internal string SourceRelativePath => ModuleRelativePath(SourceSha256);
    }
    private sealed record Entry(int Schema, string Transaction, string SourceClassId, string SourceSha256,
        string SourceRelativePath, string HelperSha256, string MicrophonePackageSha256, int Sequence, string PreviousSha256, string Phase,
        string? OwnMicrophoneInstance);
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private const string ZeroHash = "0000000000000000000000000000000000000000000000000000000000000000";
    private const int MaximumBytes = 32768, MaximumRow = 2048;
    private readonly FileStream file;
    private readonly IDisposable[] leases;
    private readonly object gate = new();
    private Entry current;
    private string previous = ZeroHash;
    private bool poisoned, disposed;
    private PhoneCameraSetupJournal(FileStream file, IDisposable[] leases, Guid transaction, string sourceHash, string helperHash)
    {
        this.file = file; this.leases = leases;
        current = new Entry(1, transaction.ToString("D"), PhoneCameraSourcePayload.ClassId, sourceHash,
            ModuleRelativePath(sourceHash), helperHash, PhoneCameraAudioPackage.Sha256, 0, ZeroHash, Phase.Prepared.ToString(), null);
        Append(current); // CreateNew collision refusal happens before this constructor.
    }

    // Future combined elevated installer only, AFTER its original explicit
    // approval. Not wired to the current audio-only setup or a preparation probe.
    [SupportedOSPlatform("windows")]
    internal static PhoneCameraSetupJournal CreateCurrent()
    {
        using var identity = WindowsIdentity.GetCurrent();
        if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
            throw new UnauthorizedAccessException("webcam_setup_journal_administrator_required");
        var source = PhoneCameraSourcePayload.LoadEmbedded() ?? throw new InvalidOperationException("webcam_setup_source_required");
        var helper = PhoneCameraAudioHelperPayload.LoadEmbedded() ?? throw new InvalidOperationException("webcam_setup_helper_required");
        var programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
        var drive = Path.GetPathRoot(programData);
        if (!Path.IsPathFullyQualified(programData) || drive is null || drive.Length != 3 || drive[1] != ':' ||
            !string.Equals(Directory.GetParent(programData)?.FullName.TrimEnd(Path.DirectorySeparatorChar),
                drive.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("webcam_setup_programdata_invalid");
        var held = new List<IDisposable>();
        FileStream? output = null;
        try
        {
            held.Add(PhoneCameraAudioStaging.HoldProtected(programData, programData: true));
            var root = Path.Combine(programData, "Magnolie-Webcam-Setup");
            PhoneCameraAudioStaging.CreateProtected(root, allowExisting: true);
            held.Add(PhoneCameraAudioStaging.HoldProtected(root, programData: false));
            // Fixed journal, never truncate/reuse/replace an old transaction,
            // including an empty/partial file left by failed creation.
            output = PhoneCameraAudioStaging.CreateProtectedFile(Path.Combine(root, "combined-setup-v1.journal"));
            return new PhoneCameraSetupJournal(output, held.ToArray(), Guid.NewGuid(), source.Sha256, helper.Sha256);
        }
        catch
        {
            output?.Dispose();
            for (var i = held.Count - 1; i >= 0; --i) held[i].Dispose();
            throw; // Preserve partial/unknown journal, never clean it to enable retry.
        }
    }
    private static bool IsHash(string? text) => text is { Length: 64 } && !text.AsSpan().ContainsAnyExcept("0123456789abcdef");
    internal string SourceSha256 { get { lock (gate) return current.SourceSha256; } }
    private static string ModuleRelativePath(string hash) => "Magnolie-Webcam-Source\\" + hash + "\\" + PhoneCameraSourcePayload.Filename;
    private static bool IsInstance(string? text) => text is { Length: > 0 and < 200 } && text.All(c => c is >= ' ' and <= '~');
    private static bool Allows(Phase from, Phase to) => from is not (Phase.RebootRequired or Phase.Failed or Phase.UnknownPending) &&
        (to is Phase.Failed or Phase.UnknownPending || (from, to) is (Phase.Prepared, Phase.SourceIntent) or
         (Phase.SourceIntent, Phase.SourceInstalled) or (Phase.SourceInstalled, Phase.MicrophoneIntent) or
         (Phase.MicrophoneIntent, Phase.RebootRequired));
    internal void BeginSource() => Advance(Phase.SourceIntent);
    internal void ConfirmSource() => Advance(Phase.SourceInstalled);
    internal void BeginMicrophone() => Advance(Phase.MicrophoneIntent);
    internal void ConfirmMicrophoneRebootRequired(string ownInstance) => Advance(Phase.RebootRequired, ownInstance);
    internal void RecordFailure(bool unknown, string? knownMicrophoneInstance = null) =>
        Advance(unknown ? Phase.UnknownPending : Phase.Failed, knownMicrophoneInstance);
    private void Advance(Phase next, string? ownInstance = null)
    {
        lock (gate)
        {
            if (disposed || poisoned) throw new InvalidOperationException("webcam_setup_journal_closed_or_uncertain");
            var phase = Enum.Parse<Phase>(current.Phase);
            if (!Allows(phase, next) || (next == Phase.RebootRequired ? !IsInstance(ownInstance) :
                ownInstance is not null && (phase != Phase.MicrophoneIntent || !IsInstance(ownInstance))))
                throw new InvalidOperationException("webcam_setup_journal_invalid_transition");
            Append(current with { Sequence = current.Sequence + 1, PreviousSha256 = previous,
                Phase = next.ToString(), OwnMicrophoneInstance = ownInstance });
        }
    }
    private void Append(Entry entry)
    {
        // Mark uncertain BEFORE any write. A write/flush exception must poison
        // this live writer even if it managed to put a whole row on disk.
        poisoned = true;
        var payload = JsonSerializer.SerializeToUtf8Bytes(entry, Json);
        var hash = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
        var row = Encoding.UTF8.GetBytes(hash + ":" + Encoding.UTF8.GetString(payload) + "\n");
        if (row.Length > MaximumRow || file.Position + row.Length > MaximumBytes)
            throw new InvalidDataException("webcam_setup_journal_bounds_invalid");
        file.Write(row); file.Flush(flushToDisk: true);
        current = entry; previous = hash; poisoned = false;
    }
    // Read-only review of bounded bytes, not reopening or resuming a writer.
    // The hashes detect corruption; ONLY protected ownership prevents forgery.
    internal static Audit Inspect(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length is < 1 or > MaximumBytes || bytes[^1] != '\n')
            throw new InvalidDataException("webcam_setup_journal_incomplete_preserve");
        var rows = new UTF8Encoding(false, true).GetString(bytes).Split('\n');
        Entry? first = null, last = null; var previous = ZeroHash;
        bool sourceStarted = false, sourceConfirmed = false, microphoneStarted = false;
        for (var i = 0; i < rows.Length - 1; ++i)
        {
            var row = rows[i];
            if (row.Length < 66 || row.Length + 1 > MaximumRow || row[64] != ':')
                throw new InvalidDataException("webcam_setup_journal_row_invalid");
            var payload = Encoding.UTF8.GetBytes(row[65..]);
            var hash = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
            if (!row.AsSpan(0, 64).SequenceEqual(hash)) throw new InvalidDataException("webcam_setup_journal_checksum_changed");
            Entry entry;
            try { entry = JsonSerializer.Deserialize<Entry>(payload, Json) ?? throw new JsonException(); }
            catch (JsonException error) { throw new InvalidDataException("webcam_setup_journal_entry_invalid", error); }
            if (!JsonSerializer.SerializeToUtf8Bytes(entry, Json).AsSpan().SequenceEqual(payload) || entry.Schema != 1 ||
                !Guid.TryParseExact(entry.Transaction, "D", out var transaction) || transaction == Guid.Empty ||
                transaction.ToString("D") != entry.Transaction || entry.SourceClassId != PhoneCameraSourcePayload.ClassId ||
                !IsHash(entry.SourceSha256) || entry.SourceRelativePath != ModuleRelativePath(entry.SourceSha256) ||
                !IsHash(entry.HelperSha256) || entry.MicrophonePackageSha256 != PhoneCameraAudioPackage.Sha256 ||
                entry.Sequence != i || entry.PreviousSha256 != previous || !Enum.TryParse<Phase>(entry.Phase, out var phase) ||
                !Enum.IsDefined(phase) || entry.Phase != phase.ToString() ||
                (phase == Phase.RebootRequired ? !IsInstance(entry.OwnMicrophoneInstance) : entry.OwnMicrophoneInstance is not null &&
                 (!microphoneStarted || phase is not (Phase.Failed or Phase.UnknownPending) || !IsInstance(entry.OwnMicrophoneInstance))))
                throw new InvalidDataException("webcam_setup_journal_identity_invalid");
            if (first is null)
            {
                if (phase != Phase.Prepared) throw new InvalidDataException("webcam_setup_journal_start_invalid");
                first = entry;
            }
            else if (entry.Transaction != first.Transaction || entry.SourceSha256 != first.SourceSha256 ||
                entry.HelperSha256 != first.HelperSha256 || !Allows(Enum.Parse<Phase>(last!.Phase), phase))
                throw new InvalidDataException("webcam_setup_journal_history_invalid");
            sourceStarted |= phase == Phase.SourceIntent;
            sourceConfirmed |= phase == Phase.SourceInstalled;
            microphoneStarted |= phase == Phase.MicrophoneIntent;
            last = entry; previous = hash;
        }
        if (last is null) throw new InvalidDataException("webcam_setup_journal_empty_preserve");
        return new Audit(Guid.Parse(last.Transaction), last.SourceSha256, last.HelperSha256,
            Enum.Parse<Phase>(last.Phase), last.OwnMicrophoneInstance, sourceStarted, sourceConfirmed, microphoneStarted);
    }
    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return; disposed = true;
            try { file.Dispose(); }
            finally { for (var i = leases.Length - 1; i >= 0; --i) leases[i].Dispose(); }
        }
    }
}
