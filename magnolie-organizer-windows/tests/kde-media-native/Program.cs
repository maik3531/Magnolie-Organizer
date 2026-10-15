using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage;

// Native feature probe: only the unique, silent player created here is controlled.
if (args.Length == 0) return NativeRegisteredPlayersProbe.Child();
if (args.Length == 1 && args[0] == "--isolated-registered-players") return NativeRegisteredPlayersProbe.Run();
if (args.Length == 1 && args[0] == "--isolated-input-window") return NativeInputProbe.Run();
if (args.Length != 1 || args[0] != "--isolated-silent-player") return 2;
var marker = "Magnolie-media-probe-" + Guid.NewGuid().ToString("N");
var file = Path.Combine(Path.GetTempPath(), marker + ".wav");
MediaPlayer? fixture = null;
using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(25));
try
{
    using (var stream = new FileStream(file, FileMode.CreateNew, FileAccess.Write, FileShare.None))
    using (var wave = new BinaryWriter(stream))
    {
        wave.Write("RIFF"u8.ToArray()); wave.Write(36 + 8000); wave.Write("WAVEfmt "u8.ToArray());
        wave.Write(16); wave.Write((short)1); wave.Write((short)1); wave.Write(8000); wave.Write(8000);
        wave.Write((short)1); wave.Write((short)8); wave.Write("data"u8.ToArray()); wave.Write(8000);
        wave.Write(Enumerable.Repeat((byte)128, 8000).ToArray());
    }
    fixture = new MediaPlayer { Volume = 0, IsLoopingEnabled = true };
    fixture.Source = MediaSource.CreateFromStorageFile(await StorageFile.GetFileFromPathAsync(file).AsTask(deadline.Token));
    fixture.Play();
    var controls = fixture.SystemMediaTransportControls;
    controls.IsEnabled = true; controls.IsPlayEnabled = true; controls.IsPauseEnabled = true;
    controls.DisplayUpdater.Type = Windows.Media.MediaPlaybackType.Music;
    controls.DisplayUpdater.MusicProperties.Title = marker;
    controls.DisplayUpdater.Update();
    var media = KdeLocalMedia.Create() ?? throw new Exception("Native Windows media access unavailable");
    string? selected = null;
    for (var attempt = 0; attempt < 40 && selected is null; attempt++)
    {
        var list = await media.ReceiveAsync(new JsonObject { ["requestPlayerList"] = true }, () => true, deadline.Token);
        foreach (var value in list[0]["playerList"]!.AsArray())
        {
            var name = value!.GetValue<string>();
            var state = await media.ReceiveAsync(new JsonObject { ["player"] = name, ["requestNowPlaying"] = true }, () => true, deadline.Token);
            if (state[0]["title"]?.GetValue<string>() == marker) { selected = name; break; }
        }
        if (selected is null) await Task.Delay(100, deadline.Token);
    }
    if (selected is null) throw new Exception("Isolated silent player was not exposed by Windows media API");
    await media.ReceiveAsync(new JsonObject { ["player"] = selected, ["action"] = "Pause" }, () => true, deadline.Token);
    for (var attempt = 0; attempt < 20 && fixture.PlaybackSession.PlaybackState != MediaPlaybackState.Paused; attempt++)
        await Task.Delay(100, deadline.Token);
    if (fixture.PlaybackSession.PlaybackState != MediaPlaybackState.Paused) throw new Exception("Native pause did not reach the fixture");
    var positioned = await media.ReceiveAsync(new JsonObject { ["player"] = selected, ["SetPosition"] = 500 }, () => true, deadline.Token);
    for (var attempt = 0; attempt < 20 && Math.Abs(fixture.PlaybackSession.Position.TotalMilliseconds - 500) > 200; attempt++)
        await Task.Delay(100, deadline.Token);
    if (Math.Abs(fixture.PlaybackSession.Position.TotalMilliseconds - 500) > 200)
        throw new Exception("Native position fixture actualMs=" + fixture.PlaybackSession.Position.TotalMilliseconds +
            " durationMs=" + fixture.PlaybackSession.NaturalDuration.TotalMilliseconds + " reportedLength=" + positioned[0]["length"]);
    try
    {
        await media.ReceiveAsync(new JsonObject { ["player"] = selected, ["action"] = "Play" }, () => false, deadline.Token);
        throw new Exception("Revoked source remained actionable");
    }
    catch (InvalidOperationException error) when (error.Message == "local_media_source_changed") { }
    if (fixture.PlaybackSession.PlaybackState != MediaPlaybackState.Paused) throw new Exception("Denied action changed fixture playback");
    await media.ReceiveAsync(new JsonObject { ["player"] = selected, ["action"] = "Play" }, () => true, deadline.Token);
    for (var attempt = 0; attempt < 20 && fixture.PlaybackSession.PlaybackState != MediaPlaybackState.Playing; attempt++)
        await Task.Delay(100, deadline.Token);
    if (fixture.PlaybackSession.PlaybackState != MediaPlaybackState.Playing) throw new Exception("Native play did not reach the fixture");
    Console.WriteLine("PASS: native Windows GSMTC isolated silent player / enumeration / pause / position-ms / revoked source / play");
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
    return 1;
}
finally
{
    fixture?.Pause(); fixture?.Dispose();
    if (File.Exists(file)) File.Delete(file);
}
