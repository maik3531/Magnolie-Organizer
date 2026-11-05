using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileBackupMaintenanceTests
{
    internal static Task PolicyAsync()
    {
        var created = NativeMediaBackupPolicy.DayMs;
        foreach (var days in new[] { 0, 90, 365 })
        {
            TestAssert.That(!NativeMediaBackupPolicy.ColdAgeEligible(created, created + 30 * NativeMediaBackupPolicy.DayMs, days), "Exact 30-day boundary was compressed.");
            TestAssert.That(NativeMediaBackupPolicy.ColdAgeEligible(created, created + 30 * NativeMediaBackupPolicy.DayMs + 1, days), "Older retained backup was not eligible.");
        }
        foreach (var days in new[] { -1, 7, 30 })
            TestAssert.That(!NativeMediaBackupPolicy.ColdAgeEligible(created, created + 60 * NativeMediaBackupPolicy.DayMs, days), "Short or invalid retention admitted compression.");
        TestAssert.That(NativeMediaBackupPolicy.Worthwhile(1000, 890, 10) && !NativeMediaBackupPolicy.Worthwhile(1000, 891, 10), "Ten-percent threshold/overhead changed.");
        TestAssert.That(!NativeMediaBackupPolicy.Worthwhile(0, 1) && !NativeMediaBackupPolicy.Worthwhile(1000, long.MaxValue), "Empty/overflowing size admitted savings.");
        TestAssert.That(NativeMediaBackupPolicy.ContentKey(5, new string('a', 64)) == new string('a', 64) + "-5", "Name-independent content key changed.");
        return Task.CompletedTask;
    }

    internal static Task ProbeAsync()
    {
        long now = 1000, own = 0; ulong total = 1000, waiting = 800;
        long? idle = NativeMediaBackupPolicy.MinimumIdleMs, memory = NativeMediaBackupPolicy.MinimumAvailableBytes;
        var calls = 0;
        var probe = new NativeWindowsBackupIdleProbe(() => now, () => { calls++; return idle; }, () => (total, waiting), () => memory, () => own);
        TestAssert.That(calls == 0 && probe.Observe() is null, "Construction or a single cumulative CPU sample admitted work.");
        now += 1000; total += 100; waiting += 100;
        TestAssert.That(probe.Observe() is { Eligible: true, ExternalCpuPercent: 0, GrantsMutationAuthority: false }, "Native idle resource sample changed.");
        var before = calls; _ = probe.Observe(); TestAssert.That(calls == before, "Probe re-polled native APIs for every byte chunk.");
        var permit = new NativeBackupIdlePermit(probe.Observe, () => { });
        now += 1000; total += 100; waiting += 70;
        Reject(permit.Require);
        now += 1000; total += 100; waiting += 100; Reject(permit.Require); // Sticky despite becoming idle again.
        var fresh = new NativeBackupIdlePermit(probe.Observe, () => { });
        now += 1000; total += 100; own += 100; // Compressor CPU is not external work.
        TestAssert.That(probe.Observe() is { ExternalCpuPercent: 0 }, "Own compressor CPU was treated as new user load.");
        fresh.Require(); now += 1000; idle = 0; total += 100; waiting += 100; Reject(fresh.Require);
        now += 1000; idle = null; TestAssert.That(probe.Observe() is null, "Missing native idle state assumed idle.");
        now += 1000; idle = NativeMediaBackupPolicy.MinimumIdleMs;
        TestAssert.That(probe.Observe() is null, "Unknown state did not reset cumulative CPU evidence.");
        now += 1000; total += 100; waiting += 100;
        TestAssert.That(probe.Observe() is { Eligible: true }, "Fresh two-sample evidence did not recover.");
        var forward = now;
        now = 0;
        TestAssert.That(probe.Observe() is null, "Reversed native clock admitted work.");
        now = forward + 1000;
        TestAssert.That(probe.Observe() is null, "Clock reset did not require a new CPU baseline.");
        now += 1000; total = 1; waiting = 0;
        TestAssert.That(probe.Observe() is null, "Reversed native CPU counters admitted work.");
        return Task.CompletedTask;
    }

    internal static Task NativeOwnerAsync()
    {
        var active = true;
        NativeBackupIdleObservation sample = new(NativeMediaBackupPolicy.MinimumIdleMs, 0, NativeMediaBackupPolicy.MinimumAvailableBytes);
        using var stop = new CancellationTokenSource();
        var permit = new NativeBackupIdlePermit(() => sample, () => { if (!active) throw new InvalidDataException("book changed"); }, stop.Token);
        active = false; Reject(permit.Require); active = true; Reject(permit.Require);
        permit = new(() => sample, () => { }); sample = sample with { AvailableBytes = 0 }; Reject(permit.Require);
        sample = sample with { AvailableBytes = NativeMediaBackupPolicy.MinimumAvailableBytes };
        permit = new(() => sample, () => { }, stop.Token); stop.Cancel();
        var canceled = false; try { permit.Require(); } catch (OperationCanceledException) { canceled = true; }
        TestAssert.That(canceled, "Owned shutdown did not stop maintenance.");
        return Task.CompletedTask;
    }

    internal static async Task WindowsNativeSampleAsync()
    {
        var probe = new NativeWindowsBackupIdleProbe();
        TestAssert.That(probe.Observe() is null, "Native cumulative first sample admitted work.");
        await Task.Delay(600);
        var observed = probe.Observe();
        if (!NativeWindowsBackupIdleProbe.NativeSessionObservable())
        {
            TestAssert.That(observed is null, "A service/SSH/non-active session was mistaken for an idle desktop.");
            Console.WriteLine("    Native session: unobservable; maintenance refused (not desktop-idle acceptance).");
            return;
        }
        TestAssert.That(observed is { IdleMs: >= 0, ExternalCpuPercent: >= 0 and <= 100, AvailableBytes: >= 0 }, "Actual Windows input/CPU/memory APIs supplied no observation.");
        TestAssert.That(!observed!.GrantsMutationAuthority, "Native resource sample granted mutation authority.");
        Console.WriteLine("    Native active session: observable; resource sample only, no storage/compression work.");
    }

    private static void Reject(Action action)
    {
        var rejected = false; try { action(); } catch (InvalidDataException) { rejected = true; }
        TestAssert.That(rejected, "Stale/unknown/busy maintenance owner was admitted.");
    }
}
