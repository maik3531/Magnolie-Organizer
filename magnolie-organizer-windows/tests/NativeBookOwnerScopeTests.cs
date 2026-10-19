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
        owner.SetReady(false); owner.SetReady(true);
        var unlocked = owner.Current("profile-a", true);
        TestAssert.That(unlocked is not null && unlocked != first, "Lock/unlock inherited a prior book owner.");
        var other = owner.Current("profile-b", true);
        TestAssert.That(other is not null && other != unlocked, "Another native profile inherited book ownership.");
        owner.Invalidate();
        var restored = owner.Current("profile-b", true);
        TestAssert.That(restored is not null && restored != other, "Restore fence inherited its previous book owner.");
        TestAssert.That(owner.Current("profile-b", false) is null && owner.Current("profile-b", true) != restored,
            "Lost native book availability recovered old source authority.");
        return Task.CompletedTask;
    }
}
