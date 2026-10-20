using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NativeBookOwnerScopeTests
{
    internal static Task RunAsync()
    {
        var owner = new NativeBookOwnerScope();
        TestAssert.That(owner.Current("profile-a", true) is null, "A book became authoritative before native initialization.");
        owner.SetReady(true);
        TestAssert.That(owner.Current("profile-a", false) is null, "Ready transport replaced actual available book state.");
        var first = owner.Current("profile-a", true);
        TestAssert.That(first is { Length: 64 }, "Actual native book did not acquire a private source.");
        owner.SetReady(true);
        TestAssert.That(owner.Current("profile-a", true) == first, "Ordinary ready/save replay rotated book ownership.");
        var initial = owner.SaveState("profile-a", true)!;
        TestAssert.That(initial.Sequence == 0 && initial.Sha256 == "", "Native readiness fabricated a saved-book receipt.");
        var saved = owner.RecordSaved("profile-a", true, new string('a', 64))!;
        var repeated = owner.RecordSaved("profile-a", true, new string('a', 64))!;
        TestAssert.That(saved.BookSource == first && saved.Sequence == 1 && repeated.Sequence == 2 &&
            repeated.Sha256 == new string('a', 64) && owner.Current("profile-a", true) == first,
            "Actual save observations lost their native book binding or write sequence.");
        owner.SetReady(false); owner.SetReady(true);
        var unlocked = owner.Current("profile-a", true);
        TestAssert.That(unlocked is not null && unlocked != first, "Lock/unlock inherited a prior book owner.");
        TestAssert.That(owner.SaveState("profile-a", true)!.Sequence == 0 && owner.SaveState("profile-a", true)!.Sha256 == "",
            "Lock/unlock inherited an earlier save proof.");
        owner.RecordSaved("profile-a", true, new string('b', 64));
        var other = owner.Current("profile-b", true);
        TestAssert.That(other is not null && other != unlocked, "Another native profile inherited book ownership.");
        TestAssert.That(owner.SaveState("profile-b", true)!.Sequence == 0, "Another profile inherited save sequence authority.");
        owner.RecordSaved("profile-b", true, new string('c', 64));
        owner.Invalidate();
        var restored = owner.Current("profile-b", true);
        TestAssert.That(restored is not null && restored != other, "Restore fence inherited its previous book owner.");
        TestAssert.That(owner.SaveState("profile-b", true)!.Sequence == 0, "Restore inherited an earlier actual-store observation.");
        TestAssert.That(owner.Current("profile-b", false) is null && owner.Current("profile-b", true) != restored,
            "Lost native book availability recovered old source authority.");
        return Task.CompletedTask;
    }
}
