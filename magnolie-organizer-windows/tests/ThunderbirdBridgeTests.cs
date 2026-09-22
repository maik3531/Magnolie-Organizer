using System.Buffers.Binary;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ThunderbirdBridgeTests
{
    internal static async Task RunAsync()
    {
        using var frame = new MemoryStream();
        await ThunderbirdBridge.WriteFrameAsync(frame, Encoding.UTF8.GetBytes("{\"ok\":true}"), 1024, default);
        frame.Position = 0;
        TestAssert.That(Encoding.UTF8.GetString(await ThunderbirdBridge.ReadFrameAsync(frame, 1024, default)) == "{\"ok\":true}", "Native message framing changed.");
        var header = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(header, uint.MaxValue);
        using var oversized = new MemoryStream(header);
        await TestAssert.ThrowsAsync<InvalidDataException>(() => ThunderbirdBridge.ReadFrameAsync(oversized, 1024, default), "An oversized native frame was accepted.");
        using var truncated = new MemoryStream(new byte[] { 5, 0, 0, 0, 1 });
        await TestAssert.ThrowsAsync<EndOfStreamException>(() => ThunderbirdBridge.ReadFrameAsync(truncated, 1024, default), "A partial native frame was accepted.");
        TestAssert.That(NextcloudDavSelection.IsSupported("thunderbird-addressbook:profile:book", ["thunderbird-calendar:profile:calendar"]), "Thunderbird sources cannot be selected.");
        var directory = Path.Combine(Path.GetTempPath(), "magnolie-tb-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var journal = new NextcloudSyncJournal(Path.Combine(directory, "journal"), new Protector());
            var context = new NextcloudMailboxContext(new NextcloudMailboxSettings(true, false, "https://dav.example", "Thunderbird") { AccountType = "generic-dav" }, null);
            using var http = new HttpClient(new RelocatingHandler());
            using var client = new NextcloudDavClient(context, http, journal, new string('b', 64));
            var source = new NextcloudDavSource("thunderbird-addressbook:profile:book", "Google", "addressbook", new Uri("https://dav.example/book/"));
            var remote = new NextcloudCardDavRemote(client, source);
            var local = new JsonObject { ["uid"] = "local-uid", ["vorname"] = "Changed" };
            var created = await remote.CreateAsync("local-uid", local, default);
            TestAssert.That(created.Id == "https://dav.example/book/provider-id.vcf" && created.ETag == "\"provider-etag\"", "A provider-assigned contact path/ETag was lost.");
            var stored = created with { Data = new JsonObject { ["uid"] = "provider-uid", ["vorname"] = "Original" } };
            await remote.UpdateAsync(stored, "local-uid", local, default);
            TestAssert.That(local["uid"]?.GetValue<string>() == "local-uid", "The local contact identity was replaced by a provider UID.");
        }
        finally { Directory.Delete(directory, true); }
    }
    private sealed class RelocatingHandler : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            TestAssert.That(request.Headers.Authorization is null, "Credentials crossed the Thunderbird transport.");
            if (request.Headers.Contains("If-Match"))
                TestAssert.That((await request.Content!.ReadAsStringAsync(token)).Contains("UID:provider-uid\r\n"), "Updating a Google contact changed its remote UID.");
            var response = new HttpResponseMessage(HttpStatusCode.Created)
            { Content = new StringContent("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:provider-uid\r\nFN:Changed\r\nEND:VCARD\r\n") };
            response.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"provider-etag\"");
            response.Content.Headers.ContentLocation = new Uri("https://dav.example/book/provider-id.vcf");
            return response;
        }
    }
    private sealed class Protector : ISecretProtector
    {
        public byte[] Protect(byte[] value) => value.Select(item => (byte)(item ^ 0x5a)).ToArray();
        public byte[] Unprotect(byte[] value) => Protect(value);
    }
}
