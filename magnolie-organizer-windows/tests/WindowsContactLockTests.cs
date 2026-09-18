using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WindowsContactLockTests
{
    internal static async Task RunAsync(string root)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Requires real Windows sharing semantics.");
        Directory.CreateDirectory(root);
        static void Check(bool value, string message)
        { if (!value) throw new InvalidOperationException(message); }
        static void Denied(Action action, bool sharingViolation = false)
        {
            try { action(); }
            catch (IOException error)
            {
                Check(!sharingViolation || error.HResult == unchecked((int)0x80070020), $"Expected ERROR_SHARING_VIOLATION, got 0x{error.HResult:X8}.");
                return;
            }
            throw new InvalidOperationException("Competing operation was not denied.");
        }
        var store = new WindowsContactStore(root);
        var data = new JsonObject { ["vorname"] = "Synthetic", ["notiz"] = "AAAA" };
        var original = await store.CreateAsync("synthetic", data, default);
        var path = Path.Combine(root, original.Id);
        var time = File.GetLastWriteTimeUtc(path);
        var size = new FileInfo(path).Length;
        data["notiz"] = "BBBB";
        var current = await new WindowsContactStore(root).UpdateAsync(original, "synthetic", data, default);
        Check(Directory.GetFiles(root).SequenceEqual(new[] { path }), "Normal update left an incorrectly named preimage.");
        File.SetLastWriteTimeUtc(path, time);
        Check(new FileInfo(path).Length == size && current.ETag != original.ETag, "Content revision failed.");
        var bytes = File.ReadAllBytes(path);
        Denied(() => store.UpdateAsync(original, "synthetic", data, default).GetAwaiter().GetResult());
        Denied(() => store.DeleteAsync(original, "synthetic", default).GetAwaiter().GetResult());
        Check(File.ReadAllBytes(path).SequenceEqual(bytes), "Stale mutation changed current bytes.");
        Console.WriteLine("PASS normal update; equal-size/equal-time stale update and delete; exact bytes retained");

        foreach (var delete in new[] { false, true })
        {
            current = (await store.ReadAsync(default)).Single();
            bytes = File.ReadAllBytes(path);
            var validated = false;
            var parked = false;
            var locked = new WindowsContactStore(root, stage =>
            {
                var target = stage == "validated" ? path : path + (delete ? ".magnolie-delete" : ".magnolie-update");
                // Run contenders on another thread while the canonical handle is held.
                Task.Run(() =>
                {
                    Denied(() => File.WriteAllText(target, "foreign"), sharingViolation: true);
                    Denied(() => File.Delete(target), sharingViolation: true);
                    Denied(() => File.Move(target, target + ".foreign"), sharingViolation: true);
                    if (stage == "validated")
                    {
                        Denied(() => new WindowsContactStore(root).UpdateAsync(current, "synthetic", data, default).GetAwaiter().GetResult());
                        Denied(() => new WindowsContactStore(root).DeleteAsync(current, "synthetic", default).GetAwaiter().GetResult());
                    }
                    else Denied(() => new WindowsContactStore(root).ReadAsync(default).GetAwaiter().GetResult());
                }).GetAwaiter().GetResult();
                using var reader = new FileStream(target, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                using var snapshot = new MemoryStream();
                reader.CopyTo(snapshot);
                Check(snapshot.ToArray().SequenceEqual(bytes), "Locked preimage changed.");
                if (stage == "validated") validated = true; else parked = true;
            });
            if (delete) await locked.DeleteAsync(current, "synthetic", default);
            else await locked.UpdateAsync(current, "synthetic", data, default);
            Check(validated && parked, "Win32 rename checkpoint not reached.");
            Check(Directory.GetFiles(root).SequenceEqual(delete ? Array.Empty<string>() : new[] { path }), "Completed mutation left preimage or unexpected filename.");
            Check(delete ? !File.Exists(path) : File.Exists(path), "Wrong completed mutation state.");
            Console.WriteLine($"PASS {(delete ? "delete" : "update")} locked-handle writer/delete/rename ERROR_SHARING_VIOLATION and independent-store races, validated and parked");
        }

        current = await store.CreateAsync("synthetic", data, default);
        bytes = File.ReadAllBytes(path);
        var interrupted = new WindowsContactStore(root, stage =>
        { if (stage == "parked") throw new IOException("Synthetic interruption"); });
        Denied(() => interrupted.UpdateAsync(current, "synthetic", data, default).GetAwaiter().GetResult());
        Check(!File.Exists(path) && File.ReadAllBytes(path + ".magnolie-update").SequenceEqual(bytes), "Missing exact recoverable preimage.");
        Check((await new WindowsContactStore(root).ReadAsync(default)).Single().ETag == current.ETag && File.ReadAllBytes(path).SequenceEqual(bytes), "Recovery changed preimage.");
        Console.WriteLine("PASS interrupted publication; exact parked preimage; fresh-store recovery");

        var winner = WindowsContactStore.Serialize(new JsonObject { ["notiz"] = "independent winner" }, "foreign");
        var racing = new WindowsContactStore(root, stage =>
        { if (stage == "parked") Task.Run(() => File.WriteAllText(path, winner)).GetAwaiter().GetResult(); });
        Denied(() => racing.UpdateAsync(current, "synthetic", data, default).GetAwaiter().GetResult());
        Check(File.ReadAllText(path) == winner && File.ReadAllBytes(path + ".magnolie-update").SequenceEqual(bytes), "Publication overwrote winner or lost preimage.");
        await new WindowsContactStore(root).ReadAsync(default);
        Check(File.ReadAllText(path) == winner, "Recovery overwrote independent winner.");
        Console.WriteLine("PASS publication-gap winner not overwritten; preimage retained before recovery; winner retained after recovery");

        current = (await store.ReadAsync(default)).Single();
        var deletionWinner = new WindowsContactStore(root, stage =>
        { if (stage == "parked") File.WriteAllText(path, winner); });
        await deletionWinner.DeleteAsync(current, "foreign", default);
        Check(File.ReadAllText(path) == winner, "Delete removed independent gap creator.");
        Console.WriteLine("PASS delete removes locked identity, not independent publication-gap creator");
    }
}
