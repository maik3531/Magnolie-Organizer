using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhotoSyncScheduleTests
{
    private sealed class Fixture
    {
        internal long Time = 100;
        internal NativePhotoSyncScope? Scope = new(new DeviceTransferBinding("sender_fixture_01", "receiver_fixture_01",
            new string('d', 64), new string('e', 64), new string('f', 64), new string('0', 64)), new string('a', 64), new object());
        internal int Reads;
        internal PhotoSyncSchedule Schedule { get; }
        internal Fixture() { Schedule = new(() => { Reads++; return Scope; }, () => Time); }
    }
    internal static Task RunAsync()
    {
        var f = new Fixture();
        TestAssert.That(f.Schedule.Mode == "manual" && f.Schedule.Active is null && f.Reads == 0, "Construction enabled automation or inspected sources.");
        TestAssert.That(f.Schedule.CancellationRequested(null!), "Absent native run became active authority.");
        f.Schedule.HintChanged();
        TestAssert.That(f.Schedule.TakeDue() is null && f.Reads == 0, "Manual mode scheduled background work.");
        var manual = f.Schedule.RequestNow();
        TestAssert.That(manual.Trigger == "manual" && ReferenceEquals(f.Schedule.RequestNow(), manual), "Sync now overlapped an active run.");
        TestAssert.That(f.Schedule.Finished(manual) && f.Schedule.TakeDue() is null, "Manual completion started repeats.");

        f = new Fixture(); f.Schedule.SetMode("automatic");
        var automatic = f.Schedule.TakeDue()!;
        for (var index = 0; index < 20; index++)
        {
            f.Schedule.HintChanged();
            TestAssert.That(f.Schedule.TakeDue() is null && ReferenceEquals(f.Schedule.RequestNow(), automatic), "Hints/manual action overlapped automatic work.");
        }
        TestAssert.That(f.Schedule.Finished(automatic), "Native completion was lost.");
        f.Time += 999; TestAssert.That(f.Schedule.TakeDue() is null, "Changes were not debounced.");
        f.Time++; var next = f.Schedule.TakeDue()!;
        TestAssert.That(next is not null && !ReferenceEquals(next, automatic), "Coalesced change was not scheduled.");
        f.Schedule.Finished(next!); f.Time += PhotoSyncSchedule.IntervalMs - 1;
        TestAssert.That(f.Schedule.TakeDue() is null, "Periodic run was early.");
        f.Time++; TestAssert.That(f.Schedule.TakeDue() is not null, "Periodic run was lost.");

        f = new Fixture(); f.Schedule.SetMode("automatic");
        var accepted = f.Schedule.TakeDue()!; var binding = accepted.Scope.Binding;
        f.Schedule.HintChanged(); f.Schedule.SetMode("manual");
        TestAssert.That(ReferenceEquals(f.Schedule.Active, accepted) && !f.Schedule.CancellationRequested(accepted) && accepted.Scope.Binding == binding,
            "Mode change reset accepted binding/work instead of stopping scheduled repeats.");
        f.Schedule.Finished(accepted); f.Time += 600000; f.Schedule.HintChanged();
        TestAssert.That(f.Schedule.TakeDue() is null && f.Schedule.RequestNow().Trigger == "manual", "Automatic-to-manual left a scheduled repeat.");

        foreach (var change in new[] { "offline", "owner", "key", "permission", "source", "destination" })
        {
            f = new Fixture(); f.Schedule.SetMode("automatic"); var active = f.Schedule.TakeDue()!; var original = f.Scope!;
            f.Scope = change switch
            {
                "offline" => null,
                "owner" => new(original.Binding, original.SourceEpoch, new object()),
                "key" => new(original.Binding with { SenderIdentitySha256 = new string('b', 64) }, original.SourceEpoch, original.Owner),
                "permission" => new(original.Binding with { PermissionEpoch = new string('b', 64) }, original.SourceEpoch, original.Owner),
                "source" => new(original.Binding, new string('b', 64), original.Owner),
                _ => new(original.Binding with { DestinationToken = new string('b', 64) }, original.SourceEpoch, original.Owner)
            };
            TestAssert.That(f.Schedule.CancellationRequested(active) && ReferenceEquals(f.Schedule.Active, active) && f.Schedule.TakeDue() is null &&
                ReferenceEquals(f.Schedule.RequestNow(), active), "Scope change released ownership before actual worker end.");
            f.Schedule.Finished(active);
            if (change == "offline")
            {
                f.Time += PhotoSyncSchedule.IntervalMs;
                TestAssert.That(f.Schedule.TakeDue() is null, "Offline scope became automatic consent.");
                TestAssert.Throws<InvalidOperationException>(() => f.Schedule.RequestNow(), "Manual start ignored offline/revoked scope.");
                f.Scope = original; TestAssert.That(f.Schedule.TakeDue() is not null, "Valid reconnection did not resume due scheduling.");
            }
        }
        f = new Fixture(); var first = f.Schedule.RequestNow();
        var forged = new NativePhotoRun(first.Scope, first.Trigger);
        TestAssert.That(!f.Schedule.Finished(forged) && f.Schedule.CancellationRequested(forged) && ReferenceEquals(f.Schedule.Active, first), "Foreign completion released native work.");
        f.Schedule.Finished(first); var second = f.Schedule.RequestNow();
        TestAssert.That(!f.Schedule.Finished(first) && ReferenceEquals(f.Schedule.Active, second), "Late end callback released a different run.");
        f.Schedule.Dispose();
        TestAssert.That(ReferenceEquals(f.Schedule.Active, second) && f.Schedule.CancellationRequested(second), "Close fabricated worker completion.");
        TestAssert.Throws<InvalidOperationException>(() => f.Schedule.RequestNow(), "Closed scheduler started work.");
        TestAssert.That(f.Schedule.Finished(second) && f.Schedule.Active is null, "Real worker end could not release closed ownership.");

        f = new Fixture();
        TestAssert.Throws<InvalidDataException>(() => f.Schedule.SetMode("auto"), "Unknown mode enabled automation.");
        var held = f.Schedule.RequestNow(); f.Time--;
        TestAssert.Throws<InvalidOperationException>(() => f.Schedule.Finished(held), "Non-monotonic clock was silently rebased.");
        TestAssert.That(ReferenceEquals(f.Schedule.Active, held), "Clock fault fabricated native completion.");
        return Task.CompletedTask;
    }
}
