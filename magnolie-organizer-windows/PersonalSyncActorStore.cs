using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record PersonalActorHandle(string ActorId, string OwnerToken)
{
    public override string ToString() => $"PersonalActorHandle({ActorId})";
}

/// <summary>Sealed raw inbox, not transport authorization, GUI adoption or a successful wire receipt.
/// The native source callback must bind the current profile/book, exact channel/key,
/// fresh controls, ownership, grants and content scope. Never use a display-only revision.</summary>
internal sealed class PersonalSyncActorStore
{
    internal const long LifetimeMs = 30 * 60 * 1000;
    private const int MaximumContexts = 32, MaximumActive = 4, MaximumPackets = 4096;
    private const long MaximumActorBytes = 50L * 1024 * 1024, MaximumTotalBytes = 100L * 1024 * 1024;
    private static readonly Regex Hex = new("^[0-9a-f]{64}$", RegexOptions.CultureInvariant);
    private static readonly Regex Fingerprint = new("^[0-9A-F]{4}(?:-[0-9A-F]{4}){3}$", RegexOptions.CultureInvariant);
    private readonly TelefonStore store;
    private readonly Func<string, string, string?> currentSource;
    private readonly Func<long> clock, monotonicClock;
    private readonly byte[] revisionKey = RandomNumberGenerator.GetBytes(32);
    internal string Epoch { get; }

    internal PersonalSyncActorStore(TelefonStore store, Func<string, string, string?> currentSource,
        string? epoch = null, Func<long>? clock = null, Func<long>? monotonicClock = null)
    {
        this.store = store; this.currentSource = currentSource ?? throw new ArgumentNullException(nameof(currentSource));
        Epoch = epoch ?? Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        if (!Hex.IsMatch(Epoch)) throw new InvalidDataException("Invalid native actor epoch.");
        this.clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        this.monotonicClock = monotonicClock ?? (() => Environment.TickCount64);
        using var db = Open(); using var create = db.CreateCommand();
        create.CommandText = "CREATE TABLE IF NOT EXISTS personal_actor_context(actor_id TEXT PRIMARY KEY,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL);" +
            "CREATE TABLE IF NOT EXISTS personal_actor_wire(actor_id TEXT NOT NULL,message_id TEXT NOT NULL,wire_hash TEXT NOT NULL,byte_count INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(actor_id,message_id));";
        create.ExecuteNonQuery();
    }

    internal void RequireCurrent(PersonalActorHandle handle)
    {
        using var db = Open(); Require(db, handle); Require(db, handle);
    }

    private SqliteConnection Open()
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        var db = store.OpenDatabase(); db.Open(); return db;
    }
    private static string Text(JsonObject value, string key) => TelefonMessagingContract.String(value, key);
    private static long Number(JsonObject value, string key) => TelefonProtocolContract.Integer(value[key]);
    private static string Hash(byte[] value) => Convert.ToHexString(SHA256.HashData(value)).ToLowerInvariant();

    private JsonObject Decode(string id, long expires, byte[] payload)
    {
        var value = JsonNode.Parse(store.Open("personal_actor_context", id, payload))!.AsObject();
        TelefonProtocolContract.ExactObject(value, "format", "actor_id", "peer_id", "fingerprint", "source_revision", "owner_epoch", "owner_hash", "storage_peer", "created_ms", "expires_ms", "created_monotonic_ms", "expires_monotonic_ms", "phase");
        if (Number(value, "format") != PersonalSyncActorContract.Version || Text(value, "actor_id") != id || Number(value, "expires_ms") != expires ||
            Text(value, "storage_peer") != PersonalSyncActorContract.StoragePeer(id) || Text(value, "phase") is not ("registered" or "receiving" or "cancelled" or "cancelled_clean") ||
            !TelefonProtocolContract.IsUuidV4(Text(value, "peer_id")) || !Fingerprint.IsMatch(Text(value, "fingerprint")) ||
            new[] { "source_revision", "owner_epoch", "owner_hash" }.Any(key => !Hex.IsMatch(Text(value, key))) ||
            Number(value, "created_ms") < 0 || expires > 253402300799999 || expires - Number(value, "created_ms") is <= 0 or > LifetimeMs ||
            Number(value, "created_monotonic_ms") < 0 || Number(value, "expires_monotonic_ms") - Number(value, "created_monotonic_ms") != LifetimeMs)
            throw new InvalidDataException("Invalid protected actor binding.");
        return value;
    }

    private void Write(SqliteConnection db, SqliteTransaction transaction, JsonObject value)
    {
        var id = Text(value, "actor_id"); using var write = db.CreateCommand(); write.Transaction = transaction;
        write.CommandText = "INSERT OR REPLACE INTO personal_actor_context VALUES($id,$expires,$payload)";
        write.Parameters.AddWithValue("$id", id); write.Parameters.AddWithValue("$expires", Number(value, "expires_ms"));
        write.Parameters.AddWithValue("$payload", store.Seal("personal_actor_context", id, TelefonCrypto.Canonical(value))); write.ExecuteNonQuery();
    }

    private JsonObject Require(SqliteConnection db, PersonalActorHandle handle, SqliteTransaction? transaction = null, bool active = true, bool source = true)
    {
        if (!Hex.IsMatch(handle.OwnerToken)) throw new InvalidOperationException("actor_not_found");
        JsonObject value;
        using (var read = db.CreateCommand())
        {
            read.Transaction = transaction; read.CommandText = "SELECT expires_ms,payload FROM personal_actor_context WHERE actor_id=$id";
            read.Parameters.AddWithValue("$id", handle.ActorId); using var row = read.ExecuteReader();
            if (!row.Read()) throw new InvalidOperationException("actor_not_found");
            value = Decode(handle.ActorId, row.GetInt64(0), (byte[])row[1]);
        }
        if (Text(value, "owner_epoch") != Epoch || !CryptographicOperations.FixedTimeEquals(Convert.FromHexString(Text(value, "owner_hash")), SHA256.HashData(Encoding.ASCII.GetBytes(handle.OwnerToken))))
            throw new InvalidOperationException("actor_not_found");
        if (active && (Text(value, "phase") is not ("registered" or "receiving") || Number(value, "expires_ms") <= clock() || Number(value, "expires_monotonic_ms") <= monotonicClock()))
            throw new InvalidOperationException("actor_inactive");
        if (source && currentSource(Text(value, "peer_id"), Text(value, "fingerprint")) != Text(value, "source_revision"))
            throw new InvalidOperationException("actor_source_changed");
        return value;
    }

    internal PersonalActorHandle Create(string peerId, string fingerprint, string sourceRevision, string? runId = null)
    {
        runId ??= Guid.NewGuid().ToString("D"); fingerprint = fingerprint.ToUpperInvariant();
        if (!TelefonProtocolContract.IsUuidV4(peerId) || !TelefonProtocolContract.IsUuidV4(runId) || !Fingerprint.IsMatch(fingerprint) || !Hex.IsMatch(sourceRevision))
            throw new InvalidDataException("Invalid actor source snapshot.");
        Reap();
        if (currentSource(peerId, fingerprint) != sourceRevision) throw new InvalidOperationException("actor_source_changed");
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(); var created = clock(); var monotonic = monotonicClock();
        if (created < 0 || created > 253402300799999 - LifetimeMs || monotonic < 0 || monotonic > long.MaxValue - LifetimeMs)
            throw new InvalidDataException("Invalid native actor clock.");
        var value = new JsonObject { ["format"] = PersonalSyncActorContract.Version, ["actor_id"] = runId, ["peer_id"] = peerId, ["fingerprint"] = fingerprint,
            ["source_revision"] = sourceRevision, ["owner_epoch"] = Epoch, ["owner_hash"] = Hash(Encoding.ASCII.GetBytes(token)),
            ["storage_peer"] = PersonalSyncActorContract.StoragePeer(runId), ["created_ms"] = created, ["expires_ms"] = created + LifetimeMs,
            ["created_monotonic_ms"] = monotonic, ["expires_monotonic_ms"] = monotonic + LifetimeMs, ["phase"] = "registered" };
        using var db = Open(); using var transaction = db.BeginTransaction(); var count = 0; var active = 0; var duplicate = false;
        using (var read = db.CreateCommand())
        {
            read.Transaction = transaction; read.CommandText = "SELECT actor_id,expires_ms,payload FROM personal_actor_context"; using var row = read.ExecuteReader();
            while (row.Read())
            {
                var item = Decode(row.GetString(0), row.GetInt64(1), (byte[])row[2]); count++; duplicate |= Text(item, "actor_id") == runId;
                if (Text(item, "owner_epoch") == Epoch && Text(item, "phase") is ("registered" or "receiving") && Number(item, "expires_ms") > created && Number(item, "expires_monotonic_ms") > monotonic) active++;
            }
        }
        if (count >= MaximumContexts || active >= MaximumActive) throw new InvalidOperationException("actor_capacity");
        if (duplicate) throw new InvalidDataException("actor_identity_reused");
        if (currentSource(peerId, fingerprint) != sourceRevision) throw new InvalidOperationException("actor_source_changed");
        Write(db, transaction, value); transaction.Commit(); return new PersonalActorHandle(runId, token);
    }

    internal int Reap()
    {
        var wall = clock(); var monotonic = monotonicClock();
        var retired = new List<(JsonObject Binding, bool Discard)>();
        using (var db = Open())
        {
            using var transaction = db.BeginTransaction(); var bindings = new List<JsonObject>();
            using (var read = db.CreateCommand())
            {
                read.Transaction = transaction; read.CommandText = "SELECT actor_id,expires_ms,payload FROM personal_actor_context";
                using var row = read.ExecuteReader();
                while (row.Read()) bindings.Add(Decode(row.GetString(0), row.GetInt64(1), (byte[])row[2]));
            }
            foreach (var value in bindings)
            {
                var discard = Text(value, "owner_epoch") != Epoch || Number(value, "expires_ms") <= wall ||
                    Number(value, "expires_monotonic_ms") <= monotonic || Number(value, "created_monotonic_ms") > monotonic;
                if (!discard && Text(value, "phase") == "cancelled_clean") continue;
                if (!discard && Text(value, "phase") != "cancelled" && currentSource(Text(value, "peer_id"), Text(value, "fingerprint")) == Text(value, "source_revision")) continue;
                if (Text(value, "phase") is not ("cancelled" or "cancelled_clean")) { value["phase"] = "cancelled"; Write(db, transaction, value); }
                retired.Add((value, discard));
            }
            transaction.Commit();
        }
        foreach (var (value, discard) in retired)
        {
            // Retirement precedes existing domain cleanup. Failure retains an inactive
            // context for retry, never a resumed owner with partially purged staging.
            if (Text(value, "phase") != "cancelled_clean") new PersonalSyncStore(store).PurgeProtocol(Text(value, "storage_peer"));
            using var db = Open(); using var transaction = db.BeginTransaction();
            var peer = Text(value, "peer_id"); var actor = Text(value, "actor_id");
            var queued = new List<(string Id, byte[] Payload)>();
            using (var read = db.CreateCommand())
            {
                read.Transaction = transaction; read.CommandText = "SELECT message_id,payload FROM outbox WHERE peer_id=$peer";
                read.Parameters.AddWithValue("$peer", peer); using var row = read.ExecuteReader();
                while (row.Read()) queued.Add((row.GetString(0), (byte[])row[1]));
            }
            foreach (var item in queued)
            {
                var message = JsonNode.Parse(store.Open("outbox", item.Id, item.Payload))!.AsObject();
                if (message["kind"]?.GetValue<string>() != PersonalSyncActorContract.DataKind || message["body"]?["run_id"]?.GetValue<string>() != actor) continue;
                PersonalSyncActorContract.Unwrap(message["body"]!.AsObject());
                using var remove = db.CreateCommand(); remove.Transaction = transaction;
                remove.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND message_id=$id";
                remove.Parameters.AddWithValue("$peer", peer); remove.Parameters.AddWithValue("$id", item.Id); remove.ExecuteNonQuery();
            }
            if (discard)
                foreach (var table in new[] { "personal_actor_wire", "personal_actor_context" })
                {
                    using var remove = db.CreateCommand(); remove.Transaction = transaction;
                    remove.CommandText = $"DELETE FROM {table} WHERE actor_id=$actor";
                    remove.Parameters.AddWithValue("$actor", actor); remove.ExecuteNonQuery();
                }
            if (!discard) { value["phase"] = "cancelled_clean"; Write(db, transaction, value); }
            transaction.Commit();
        }
        return retired.Count;
    }

    internal JsonObject Status(PersonalActorHandle handle)
    {
        using var db = Open(); var value = Require(db, handle, active: false, source: false); var packets = new JsonArray(); long size = 0;
        using (var read = db.CreateCommand())
        {
            read.CommandText = "SELECT message_id,wire_hash,byte_count FROM personal_actor_wire WHERE actor_id=$id ORDER BY message_id";
            read.Parameters.AddWithValue("$id", handle.ActorId); using var row = read.ExecuteReader();
            while (row.Read()) { size += row.GetInt64(2); packets.Add(new JsonArray(row.GetString(0), row.GetString(1), row.GetInt64(2))); }
        }
        var revision = Convert.ToHexString(HMACSHA256.HashData(revisionKey, TelefonCrypto.Canonical(new JsonObject { ["binding"] = value.DeepClone(), ["packets"] = packets }))).ToLowerInvariant();
        return new JsonObject { ["actor_id"] = handle.ActorId, ["peer_id"] = value["peer_id"]!.DeepClone(), ["fingerprint"] = value["fingerprint"]!.DeepClone(),
            ["phase"] = Text(value, "phase") == "cancelled_clean" ? JsonValue.Create("cancelled") : value["phase"]!.DeepClone(), ["expires_ms"] = value["expires_ms"]!.DeepClone(), ["packets"] = packets.Count, ["bytes"] = size, ["revision"] = revision };
    }

    internal bool Put(PersonalActorHandle handle, JsonObject wire)
    {
        TelefonProtocolContract.ExactObject(wire, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var kind = Text(wire, "kind"); var id = Text(wire, "message_id"); var body = wire["body"] as JsonObject ?? throw new InvalidDataException("Invalid raw actor body.");
        if (Text(wire, "type") != "message" || Number(wire, "v") != 1 || !TelefonProtocolContract.IsUuidV4(id) || kind is not (PersonalSyncActorContract.DataKind or PersonalSyncActorContract.AckKind))
            throw new InvalidDataException("Invalid raw actor wire frame.");
        long lifetime = 60000;
        if (kind == PersonalSyncActorContract.DataKind)
        {
            var semantic = PersonalSyncActorContract.Unwrap(body); var semanticKind = semantic.Kind == PhoneContentScope.DataKind ? Text(semantic.Body, "kind") : semantic.Kind;
            lifetime = semanticKind == "personal_sync.request" ? 3600000 : 86400000;
        }
        else PersonalSyncActorContract.ValidateAck(body);
        var clear = TelefonCrypto.Canonical(wire); var created = Number(wire, "created_ms"); var expires = Number(wire, "expires_ms");
        if (Text(body, "run_id") != handle.ActorId || clear.Length > PersonalSyncContract.MaxChunkBody || created < 0 || expires > 253402300799999 ||
            expires - created <= 0 || expires - created > lifetime || created > clock() + 300000 || expires <= clock()) throw new InvalidDataException("Invalid actor wire identity/lifetime/budget.");
        var digest = Hash(clear); var primary = handle.ActorId + ":" + id; var sealedValue = store.Seal("personal_actor_wire", primary, clear);
        using var db = Open(); using var transaction = db.BeginTransaction(); var context = Require(db, handle, transaction);
        using (var old = db.CreateCommand())
        {
            old.Transaction = transaction; old.CommandText = "SELECT wire_hash,payload FROM personal_actor_wire WHERE actor_id=$actor AND message_id=$id";
            old.Parameters.AddWithValue("$actor", handle.ActorId); old.Parameters.AddWithValue("$id", id); using var row = old.ExecuteReader();
            if (row.Read())
            {
                if (row.GetString(0) != digest || !store.Open("personal_actor_wire", primary, (byte[])row[1]).AsSpan().SequenceEqual(clear)) throw new InvalidDataException("actor_frame_conflict");
                row.Close(); Require(db, handle, transaction); transaction.Commit(); return false;
            }
        }
        using (var quota = db.CreateCommand())
        {
            quota.Transaction = transaction; quota.CommandText = "SELECT COUNT(*),COALESCE(SUM(length(payload)),0),(SELECT COALESCE(SUM(length(payload)),0) FROM personal_actor_wire) FROM personal_actor_wire WHERE actor_id=$actor";
            quota.Parameters.AddWithValue("$actor", handle.ActorId); using var row = quota.ExecuteReader(); row.Read();
            if (row.GetInt64(0) >= MaximumPackets || row.GetInt64(1) + sealedValue.Length > MaximumActorBytes || row.GetInt64(2) + sealedValue.Length > MaximumTotalBytes)
                throw new InvalidOperationException("actor_capacity");
        }
        using (var insert = db.CreateCommand())
        {
            insert.Transaction = transaction; insert.CommandText = "INSERT INTO personal_actor_wire VALUES($actor,$id,$hash,$bytes,$payload)";
            insert.Parameters.AddWithValue("$actor", handle.ActorId); insert.Parameters.AddWithValue("$id", id); insert.Parameters.AddWithValue("$hash", digest);
            insert.Parameters.AddWithValue("$bytes", clear.Length); insert.Parameters.AddWithValue("$payload", sealedValue); insert.ExecuteNonQuery();
        }
        context["phase"] = "receiving"; Write(db, transaction, context); Require(db, handle, transaction); transaction.Commit(); return true;
    }

    internal JsonObject Read(PersonalActorHandle handle, string messageId)
    {
        using var db = Open(); Require(db, handle); byte[] clear;
        using (var read = db.CreateCommand())
        {
            read.CommandText = "SELECT wire_hash,byte_count,payload FROM personal_actor_wire WHERE actor_id=$actor AND message_id=$id";
            read.Parameters.AddWithValue("$actor", handle.ActorId); read.Parameters.AddWithValue("$id", messageId); using var row = read.ExecuteReader();
            if (!row.Read()) throw new KeyNotFoundException("actor_packet_not_found");
            clear = store.Open("personal_actor_wire", handle.ActorId + ":" + messageId, (byte[])row[2]);
            if (clear.Length != row.GetInt64(1) || Hash(clear) != row.GetString(0)) throw new InvalidDataException("Invalid protected actor packet.");
        }
        Require(db, handle); return JsonNode.Parse(clear)!.AsObject();
    }

    internal JsonObject Cancel(PersonalActorHandle handle)
    {
        using (var db = Open())
        {
            using var transaction = db.BeginTransaction(); var value = Require(db, handle, transaction, active: false, source: false);
            if (Text(value, "phase") != "cancelled_clean") { value["phase"] = "cancelled"; Write(db, transaction, value); }
            transaction.Commit();
        }
        return Status(handle);
    }
}
