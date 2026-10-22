using System.Text.Json.Nodes;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeMediaTests
{
    internal static async Task RunAsync()
    {
        RegisteredChoices();
        foreach (var command in new[] { "kde_player_datei", "kde_player_titel" })
        {
            using var envelope = BridgeDispatcherContract.Parse(new JsonObject { ["cmd"] = command, ["slot"] = "music", ["requestId"] = Guid.NewGuid().ToString("D") }.ToJsonString());
        }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse(new JsonObject { ["cmd"] = "kde_player_datei", ["slot"] = "music", ["requestId"] = Guid.NewGuid().ToString("D"), ["path"] = "unselected.mp3" }.ToJsonString()),
            "Web media command bypassed the native file chooser.");
        var state = new KdeMediaState();
        var requests = state.Accept(JsonNode.Parse("""{"playerList":["Music"]}""")!.AsObject());
        TestAssert.That(requests.Count == 1 && requests[0]["requestNowPlaying"]!.GetValue<bool>(), "Player bootstrap missing.");
        var token = state.Snapshot("device")["token"]!.GetValue<string>();
        state.Accept(JsonNode.Parse("""{"player":"Music","title":"Track","canSeek":true,"volume":50}""")!.AsObject());
        TestAssert.That(state.Command(token, "Music", "seek", -1000000)["Seek"]!.GetValue<long>() == -1000000, "Seek units lost.");
        foreach (var input in new[] { """{"playerList":["same","same"]}""", """{"player":"Music","volume":true}""",
            """{"player":"Music","canSeek":1}""", """{"player":"Music","volume":101}""" })
        {
            var before = state.Snapshot("device").ToJsonString();
            TestAssert.Throws<InvalidDataException>(() => state.Accept(JsonNode.Parse(input)!.AsObject()), "Malformed metadata accepted.");
            TestAssert.That(state.Snapshot("device").ToJsonString() == before, "Malformed packet damaged valid state.");
        }
        state.Accept(new JsonObject { ["player"] = "Music", ["title"] = string.Concat(Enumerable.Repeat("😀", 1000)), ["isPlaying"] = true });
        TestAssert.That(state.Snapshot("device")["players"]![0]!["title"]!.GetValue<string>() == string.Concat(Enumerable.Repeat("😀", 32)), "Unicode metadata not bounded.");
        state.Accept(JsonNode.Parse("""{"playerList":[]}""")!.AsObject());
        state.Accept(JsonNode.Parse("""{"player":"Music","title":"Late"}""")!.AsObject());
        TestAssert.That(state.Snapshot("device")["players"]!.AsArray().Count == 0, "Late update resurrected a player.");
        TestAssert.Throws<InvalidDataException>(() => state.Command(token, "Music", "Play", null), "Removed player remained actionable.");
        state.Accept(JsonNode.Parse("""{"playerList":["Music"],"player":"Music","canSeek":false}""")!.AsObject());
        TestAssert.Throws<InvalidDataException>(() => state.Command(token, "Music", "Play", null), "Old list token remained valid.");
        var current = state.Snapshot("device")["token"]!.GetValue<string>();
        TestAssert.Throws<InvalidDataException>(() => state.Command(current, "Music", "position", 0), "canSeek false ignored.");
        TestAssert.Throws<InvalidDataException>(() => KdeMediaState.CommandBody("Music", "shell", null), "Unknown action accepted.");
        TestAssert.Throws<InvalidDataException>(() => KdeMediaState.CommandBody("Music", "volume", 101), "Invalid volume accepted.");
        await ArtworkTransportAsync();
    }

    private static async Task ArtworkTransportAsync()
    {
        using var desktop = KdeConnectTests.Certificate("desktop_cover");
        using var phone = KdeConnectTests.Certificate("phone_cover");
        using var other = KdeConnectTests.Certificate("phone_other");
        foreach (var wrongPeer in new[] { false, true })
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            var announced = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            var artwork = new KdeMediaArtwork(new JsonObject { ["player"] = "Fixture", ["albumArtUrl"] = "kdeconnect://magnolie/owned-cover", ["transferringAlbumArt"] = true }, [1, 2, 3, 4]);
            var send = KdeConnectDirectBackend.SendMediaArtworkTransportAsync(IPAddress.Loopback, desktop, "phone_cover", KdeConnectProtocol.CertificatePin(phone),
                artwork, () => true, (bytes, _) =>
                {
                    var header = JsonNode.Parse(bytes)!.AsObject();
                    TestAssert.That(header["payloadSize"]!.GetValue<int>() == 4 && header["body"]!["transferringAlbumArt"]!.GetValue<bool>(), "Cover payload announcement lost its protocol fields.");
                    announced.TrySetResult(header["payloadTransferInfo"]!["port"]!.GetValue<int>()); return Task.CompletedTask;
                }, deadline.Token);
            var port = await announced.Task.WaitAsync(deadline.Token);
            using var client = new TcpClient(); await client.ConnectAsync(IPAddress.Loopback, port, deadline.Token);
            await using var tls = new SslStream(client.GetStream(), false, (_, certificate, _, _) =>
            {
                if (certificate is null) return false;
                using var presented = new X509Certificate2(certificate);
                return KdeConnectProtocol.CertificatePin(presented) == KdeConnectProtocol.CertificatePin(desktop);
            });
            var received = Array.Empty<byte>();
            try
            {
                await tls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions { TargetHost = "desktop_cover",
                    ClientCertificates = new X509CertificateCollection { wrongPeer ? other : phone }, EnabledSslProtocols = SslProtocols.Tls12,
                    CertificateRevocationCheckMode = X509RevocationMode.NoCheck }, deadline.Token);
                var buffer = new byte[4]; await tls.ReadExactlyAsync(buffer, deadline.Token); received = buffer;
            }
            catch (Exception error) when (wrongPeer && error is AuthenticationException or IOException) { }
            try { await send; }
            catch (Exception error) when (wrongPeer && error is AuthenticationException or IOException) { }
            TestAssert.That(wrongPeer ? received.Length == 0 : received.SequenceEqual(artwork.Data), "Cover payload was lost or sent to a different certificate.");
        }
    }

    private static void RegisteredChoices()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-registered-media-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var apps = new[] { new KdeRegisteredPlayer("owned:music", "Same", "owned-music.exe", ["owned-music"]),
                new KdeRegisteredPlayer("owned:video", "Same", "owned-video.exe", ["owned-video"]) };
            var launched = new List<string>();
            var opened = new List<(string App, string Path)>();
            var choices = new KdeRegisteredPlayers(root, () => apps, app => launched.Add(app.Id), (app, path) => opened.Add((app.Id, path)));
            choices.Configure("music", apps[0].Id); choices.Configure("video", apps[1].Id);
            var music = Path.Combine(root, "owned song.mp3"); var video = Path.Combine(root, "owned film.mp4");
            File.WriteAllBytes(music, [0]); File.WriteAllBytes(video, [0]);
            choices.OpenFile("music", apps[0].Id, music); choices.OpenFile("video", apps[1].Id, video);
            TestAssert.That(opened.SequenceEqual(new[] { (apps[0].Id, music), (apps[1].Id, video) }), "File selection did not use the matching music/video assignment.");
            TestAssert.Throws<InvalidOperationException>(() => choices.OpenFile("music", apps[0].Id, video), "Video was offered as a music file.");
            TestAssert.Throws<InvalidOperationException>(() => choices.OpenFile("video", apps[0].Id, video), "Changed application assignment remained actionable.");
            TestAssert.That(opened.Count == 2, "Rejected media file choice launched an application.");
            var aliases = choices.Choices().Keys.ToArray();
            TestAssert.That(aliases.Length == 2 && aliases.Distinct().Count() == 2, "Two slots with the same application name collided.");
            foreach (var alias in aliases)
            {
                TestAssert.That(choices.Closed(alias, new JsonObject(), () => true)["canPlay"]!.GetValue<bool>(), "Closed player was not offered.");
                TestAssert.Throws<InvalidOperationException>(() => choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => false), "Revoked source launched an app.");
                TestAssert.Throws<InvalidOperationException>(() => choices.Closed(alias, new JsonObject { ["action"] = "Pause" }, () => true), "Closed player accepted Pause.");
            }
            TestAssert.That(launched.Count == 0, "Metadata or denied requests launched an app.");
            foreach (var alias in aliases)
            {
                choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => true);
                choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => true);
            }
            TestAssert.That(launched.SequenceEqual(apps.Select(app => app.Id)), "Slot launch throttles were lost or shared.");
            var reopened = new KdeRegisteredPlayers(root, () => apps, app => launched.Add(app.Id));
            TestAssert.That(reopened.Settings()["video"]!.GetValue<string>() == apps[1].Id, "Player choices were not durable.");
            reopened.Configure("music", "");
            TestAssert.That(new KdeRegisteredPlayers(root, () => apps).Settings()["music"]!.GetValue<string>() == "", "Explicit None was automatically enabled again.");
            TestAssert.Throws<InvalidOperationException>(() => reopened.Configure("video", @"C:\arbitrary.exe"), "A packet supplied an executable path.");
            TestAssert.Throws<InvalidDataException>(() => reopened.Configure("shell", apps[0].Id), "Unknown slot accepted.");
        }
        finally { Directory.Delete(root, true); }
    }
}
