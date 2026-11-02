using System.Text.Json.Nodes;
using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileAcceptanceEnvelopeTests
{
    internal static Task RunAsync()
    {
        const long now=1800000000000;
        var message=new JsonObject { ["type"]="message",["v"]=1,["message_id"]="22222222-2222-4222-8222-222222222222",
            ["kind"]=DeviceFileAcceptanceEnvelope.Kind,["created_ms"]=now,["expires_ms"]=now+60000,
            ["body"]=new JsonObject { ["format"]=1,["offer_id"]="11111111-1111-4111-8111-111111111111",
                ["transfer_id"]=new string('a',32),["manifest_sha256"]=new string('b',64),["acceptance_sha256"]=new string('c',64),
                ["permission_epoch"]=new string('d',64),["destination_token"]=new string('e',64) } };
        var parsed=DeviceFileAcceptanceEnvelope.Parse(message,now);
        TestAssert.That(parsed.TransferId==new string('a',32) && parsed.DestinationToken==new string('e',64),"Exact acceptance rejected.");
        foreach (var (key,value) in new (string,JsonNode?)[] { ("format",JsonValue.Create(true)),("offer_id",JsonValue.Create("wrong")),
            ("transfer_id",JsonValue.Create(new string('A',32))),("permission_epoch",JsonValue.Create("old")),
            ("path",JsonValue.Create("/private")),("saved",JsonValue.Create(true)),("read_granted",JsonValue.Create(true)) })
        {
            var invalid=(JsonObject)message.DeepClone();invalid["body"]!.AsObject()[key]=value;
            TestAssert.Throws<InvalidDataException>(()=>DeviceFileAcceptanceEnvelope.Parse(invalid,now),"Invalid acceptance granted authority.");
        }
        TestAssert.Throws<InvalidDataException>(()=>DeviceFileAcceptanceEnvelope.Parse(message,now+60000),"Expired acceptance accepted.");
        const string relative="contracts/file-transfer-acceptance-v1-vectors.json";
        var vector=JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative),relative)))!.AsObject();
        var golden=vector["acceptance"]!.AsObject();var bytes=TelefonCrypto.Canonical(golden);
        TestAssert.That(DeviceFileAcceptanceEnvelope.Parse(golden,now)==parsed && bytes.SequenceEqual(TelefonCrypto.Canonical(message)) &&
            bytes.Length==vector["canonical_bytes"]!.GetValue<int>() && Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant()==vector["canonical_sha256"]!.GetValue<string>(),
            "Shared acceptance golden mismatch.");
        return Task.CompletedTask;
    }
}
