using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalDesktopFeaturesTests
{
    internal static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "desktop-features-" + Guid.NewGuid().ToString("N"));
        var key = Enumerable.Repeat((byte)6, 32).ToArray();
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, key);
            TestAssert.That(store.DesktopFeatures().Count == 0, "Unknown desktop features were invented.");
            TestAssert.That(store.SetDesktopFeatures(true, false), "Initial features were not saved.");
            var first = store.DesktopFeatures();
            TestAssert.That(!store.SetDesktopFeatures(true, false), "Unchanged features advanced their revision.");
            var reopened = new TelefonStore(paths, key);
            TestAssert.That(JsonNode.DeepEquals(first, reopened.DesktopFeatures()), "Desktop feature snapshot did not survive restart.");
            var token = Guid.NewGuid().ToString("D");
            reopened.BeginRestore(token); reopened.CompleteRestore(Guid.NewGuid().ToString("D"), token);
            reopened.SetDesktopFeatures(false, true);
            var next = reopened.DesktopFeatures();
            TestAssert.That(TelefonProtocolContract.Integer(next["revision"]) > TelefonProtocolContract.Integer(first["revision"]),
                "Profile restoration reset the feature high-water mark.");
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.AcceptDesktopFeatures(next, first), "A stale feature revision was accepted.");
            var altered = next.DeepClone().AsObject(); altered["custom_tab"] = true;
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.AcceptDesktopFeatures(next, altered), "Feature equivocation was accepted.");
            altered = next.DeepClone().AsObject(); altered["tree"] = "true";
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateDesktopFeatures(altered), "A string was accepted as a feature boolean.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
