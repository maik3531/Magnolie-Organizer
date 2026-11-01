using MagnolieOrganizer.Windows;
using System.Security.Cryptography;
using System.Text;

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
        FreshProducerSnapshot();
        return Task.CompletedTask;
    }

    private static void FreshProducerSnapshot()
    {
        const string text = "{\"notizen\":[{\"id\":\"synthetic\",\"text\":\"Grüße 🌸\"}]}";
        static string Hash(string value) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
        var owner = new NativeBookOwnerScope(); owner.SetReady(true);
        NativeBookSaveState? Read() => owner.SaveState("synthetic-native-profile", true);
        TestAssert.That(NativeActorBookSnapshot.Capture(Read, () => text) is null, "Readiness fabricated saved producer data.");
        var saved = owner.RecordSaved("synthetic-native-profile", true, Hash(text));
        var snapshot = NativeActorBookSnapshot.Capture(Read, () => text);
        TestAssert.That(snapshot is not null && snapshot.Text == text && snapshot.SavedBook == saved, "Exact native saved text was not captured.");
        TestAssert.That(NativeActorBookSnapshot.Capture(Read, () => text + " ") is null, "Different producer bytes inherited a writer proof.");
        TestAssert.That(NativeActorBookSnapshot.Capture(Read, () => null) is null, "Missing native plaintext became producer input.");
        foreach (var invalid in new[] { "[]", "null", "{broken" })
        {
            owner.RecordSaved("synthetic-native-profile", true, Hash(invalid));
            TestAssert.That(NativeActorBookSnapshot.Capture(Read, () => invalid) is null, "Non-book native JSON was accepted: " + invalid);
        }
        foreach (var change in new[] { "same-bytes-new-save", "lock", "restore", "profile" })
        {
            owner.SetReady(true); owner.RecordSaved("synthetic-native-profile", true, Hash(text));
            var result = NativeActorBookSnapshot.Capture(Read, () => {
                if (change == "same-bytes-new-save") owner.RecordSaved("synthetic-native-profile", true, Hash(text));
                if (change == "lock") owner.SetReady(false);
                if (change == "restore") owner.Invalidate();
                if (change == "profile") owner.Current("another-profile", true);
                return text;
            });
            TestAssert.That(result is null, "Producer capture crossed a native writer/lifecycle change: " + change);
        }
        owner.SetReady(true); owner.RecordSaved("synthetic-native-profile", true, Hash(text));
        TestAssert.That(NativeActorBookSnapshot.Capture(Read, () => text) is not null, "A fresh saved book could not acquire a new snapshot.");
        TestAssert.That(snapshot!.SavedBook != Read(), "An old snapshot silently acquired the new writer proof.");
    }
}
