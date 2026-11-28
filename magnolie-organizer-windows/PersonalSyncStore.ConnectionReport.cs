using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PersonalSyncStore
{
    internal (TelefonAck Receipt, string Authority) StageScopedConnectionReport(string peerId, JsonObject envelope, string transport, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var plan = RequireScopedConnectionReport(db, transaction, peerId, envelope, transport, now, currentAuthority, currentBook);
        var id = envelope["message_id"]!.GetValue<string>();
        var authority = plan["authority"]!.GetValue<string>();
        var key = ScopedReportReceiptKey(peerId, envelope);
        var existing = ReadMeta(key, "personal_connection_report", (db, transaction));
        if (existing is not null)
        {
            if (existing["message_id"]?.GetValue<string>() != id ||
                !JsonNode.DeepEquals(ReadConnectionReceipt(db, transaction, peerId, id, now), envelope))
                throw new InvalidDataException("The original reader already has a different connection report.");
            return (new TelefonAck(id, "duplicate", "none"), authority);
        }
        WriteConnectionReceipt(db, transaction, peerId, envelope, now);
        WriteMeta(key, "personal_connection_report", new JsonObject { ["message_id"] = id, ["ack_written"] = false },
            false, (db, transaction));
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        transaction.Commit();
        return (new TelefonAck(id, "accepted", "none"), authority);
    }

    internal bool ConfirmScopedConnectionReport(string peerId, JsonObject envelope, string transport, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var plan = RequireScopedConnectionReport(db, transaction, peerId, envelope, transport, now, currentAuthority, currentBook);
        var key = ScopedReportReceiptKey(peerId, envelope);
        var report = ReadMeta(key, "personal_connection_report", (db, transaction));
        var id = envelope["message_id"]!.GetValue<string>();
        if (report?["message_id"]?.GetValue<string>() != id ||
            !JsonNode.DeepEquals(ReadConnectionReceipt(db, transaction, peerId, id, now), envelope))
            throw new InvalidOperationException("The written report acknowledgement has no exact receipt.");
        if (report["ack_written"]?.GetValue<bool>() == true) return false;
        report["ack_written"] = true;
        WriteMeta(key, "personal_connection_report", report, true, (db, transaction));
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        transaction.Commit();
        return true;
    }

    private JsonObject RequireScopedConnectionReport(SqliteConnection db, SqliteTransaction transaction, string peerId, JsonObject envelope,
        string transport, long now, Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook)
    {
        var wrapper = envelope["body"]!.AsObject();
        var body = wrapper["body"]!.AsObject();
        var runId = body["run_id"]!.GetValue<string>();
        var run = LoadRun(peerId, runId, now, (db, transaction));
        var plan = ReadMeta(ConnectionOriginalResultsKey(peerId, runId), "personal_connection_reply", (db, transaction));
        if (run is not { Expired: false, Policy: "connection_only" } || plan?["incoming_reply"]?.GetValue<bool>() != true ||
            wrapper["scope"] is not JsonObject reference || !JsonNode.DeepEquals(plan["scope"], reference) ||
            !JsonNode.DeepEquals(plan["request"], run.Request) || !JsonNode.DeepEquals(body["format"], run.Request["format"]) ||
            body["trigger"]?.GetValue<string>() != PersonalSyncContract.AutoConnectionTrigger ||
            body["state"]?.GetValue<string>() != "complete" || body["error"]?.GetValue<string>() != "none" ||
            body["transport"]?.GetValue<string>() != transport || TelefonProtocolContract.Integer(envelope["expires_ms"]) <= now ||
            TelefonProtocolContract.Integer(envelope["expires_ms"]) > run.ExpiresMs || TelefonProtocolContract.Integer(plan["expires_ms"]) <= now)
            throw new InvalidOperationException("The exact scoped report has no confirmed reply on this reader.");
        var authority = plan["authority"]!.GetValue<string>();
        if (TelefonProtocolContract.Integer(plan["acknowledged"]) != plan["message_ids"]!.AsArray().Count ||
            !ScopedInitialAcknowledged(db, transaction, peerId, runId, now, authority, reference))
            throw new IOException("The connection report is waiting for the saved reply and actual original acknowledgements.");
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        return plan;
    }

    private static string ScopedReportReceiptKey(string peerId, JsonObject envelope) =>
        $"personal_report:{peerId}:{envelope["body"]!["body"]!["run_id"]!.GetValue<string>()}:connection_received_report";
}
