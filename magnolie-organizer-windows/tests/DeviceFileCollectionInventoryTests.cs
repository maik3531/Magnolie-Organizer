using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileCollectionInventoryTests
{
    internal static Task WindowsHazardsAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-collection-hazards-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var selected = Path.Combine(root, "selected"); Directory.CreateDirectory(selected);
            var outside = Path.Combine(root, "outside"); Directory.CreateDirectory(outside);
            File.WriteAllText(Path.Combine(outside, "not-selected.jpg"), "must not read");
            var alias = Path.Combine(selected, "alias"); Directory.CreateSymbolicLink(alias, outside);
            try
            {
                using var owner = DeviceFileNativeDirectory.OpenExisting(selected);
                var scan = owner.InventoryCollection(() => { }, CancellationToken.None);
                TestAssert.That(scan.NeedsReview && scan.Members.Count == 0, "Collection scan traversed an actual external reparse subtree or claimed complete inventory.");
            }
            finally { Directory.Delete(alias); }
            var file = Path.Combine(selected, "one.jpg"); File.WriteAllText(file, "single original");
            var link = Path.Combine(selected, "two.jpg");
            if (!CreateHardLink(link, file, IntPtr.Zero)) throw new System.ComponentModel.Win32Exception(System.Runtime.InteropServices.Marshal.GetLastWin32Error());
            using (var owner = DeviceFileNativeDirectory.OpenExisting(selected))
                TestAssert.Throws<InvalidDataException>(() => owner.InventoryCollection(() => { }, CancellationToken.None), "Actual multiply-linked source was accepted as independent collection member.");
            File.Delete(link); File.Delete(file);
            // More than one native64-KiB directory buffer, without huge files.
            for (var index = 0; index < 180; index++) File.WriteAllBytes(Path.Combine(selected, index.ToString("D3") + new string('x', 150) + ".jpg"), [1, 2]);
            using (var owner = DeviceFileNativeDirectory.OpenExisting(selected))
            {
                var first = owner.InventoryCollection(() => { }, CancellationToken.None);
                var next = owner.InventoryCollection(() => { }, CancellationToken.None);
                TestAssert.That(first.Members.Count == 180 && !first.NeedsReview && next.Members.Count == 180 &&
                    first.Members.Select(item => item.Identity).ToHashSet().SetEquals(next.Members.Select(item => item.Identity)),
                    "Actual paged/restarted directory inventory dropped, repeated or reassociated members.");
            }
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    [System.Runtime.InteropServices.DllImport("kernel32.dll", EntryPoint = "CreateHardLinkW", CharSet = System.Runtime.InteropServices.CharSet.Unicode, SetLastError = true)]
    [return: System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.Bool)]
    private static extern bool CreateHardLink(string name, string existing, IntPtr security);

    internal static Task WindowsInventoryAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-collection-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var nested = Path.Combine(root, "Album"); Directory.CreateDirectory(nested);
            File.WriteAllBytes(Path.Combine(root, "one.jpg"), [1, 2, 3]);
            File.WriteAllBytes(Path.Combine(nested, "two.mp4"), [4, 5, 6, 7]);
            Directory.CreateDirectory(Path.Combine(root, "Backup"));
            File.WriteAllText(Path.Combine(root, "Backup", "not-source.jpg"), "private backup");
            File.WriteAllText(Path.Combine(root, ".magnolie-trash-synthetic"), "retained bytes");
            var before = Directory.GetFiles(root, "*", SearchOption.AllDirectories).ToDictionary(path => path, File.ReadAllBytes);
            using var owner = DeviceFileNativeDirectory.OpenExisting(root); var checks = 0;
            var inventory = owner.InventoryCollection(() => checks++, CancellationToken.None);
            TestAssert.That(!inventory.NeedsReview && inventory.Members.Count == 2 && checks > 4,
                "Actual read-only collection inventory lost selected files or private-storage exclusion.");
            var first = inventory.Members.Single(item => item.Name == "one.jpg");
            var second = inventory.Members.Single(item => item.Name == "two.mp4");
            TestAssert.That(first.Parents.Count == 0 && first.Size == 3 && second.Size == 4 && second.Parents.Count == 1 &&
                second.Parents[0].Name == "Album" && inventory.Members.All(item => item.Identity.VolumeSerial == owner.OriginalIdentity.VolumeSerial) &&
                first.Identity != second.Identity, "Actual collection member/ancestor identity or size was inferred from a filename.");
            using (var actual = DeviceFileNativeDirectory.OpenExisting(nested))
                TestAssert.That(second.Parents[0].Identity == actual.CurrentIdentity(), "Nested source path lost its actual native directory ID.");
            using (var held = owner.OpenManagedSource(first.Name, first.Identity, () => { }))
                TestAssert.That(held.ReadExact(0, 3).SequenceEqual(new byte[] { 1, 2, 3 }), "Inventoried identity did not reopen the exact source bytes.");
            var allowed = true;
            using (var held = owner.OpenCollectionMember(second, () => {
                if (!allowed) throw DeviceFileControl.Error("synthetic_collection_permission_revoked");
            }))
            {
                TestAssert.That(held.ReadExact(0, 4).SequenceEqual(new byte[] { 4, 5, 6, 7 }), "Nested inventory member did not open by exact ancestor/file identity.");
                TestAssert.Throws<IOException>(() => Directory.Move(nested, Path.Combine(root, "moved-album")), "Held source ancestor could be replaced.");
                allowed = false;
                TestAssert.Throws<InvalidDataException>(() => held.ReadExact(0, 1), "Collection source retained read rights after withdrawal.");
            }
            TestAssert.Throws<InvalidDataException>(() => owner.CreateStagedFile("must-not-create"), "Read-only collection root conferred receive/write authority.");
            TestAssert.Throws<InvalidDataException>(() => owner.InventoryCollection(() => { }, CancellationToken.None, maximumEntries: 1),
                "Inventory silently truncated a full collection.");
            TestAssert.Throws<InvalidDataException>(() => owner.InventoryCollection(() => { }, CancellationToken.None, maximumDepth: 0),
                "Inventory silently skipped a required source subtree.");
            checks = 0;
            TestAssert.Throws<InvalidDataException>(() => owner.InventoryCollection(() => {
                if (++checks == 4) throw DeviceFileControl.Error("synthetic_collection_permission_revoked");
            }, CancellationToken.None), "Inventory returned members after native permission withdrawal.");
            using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
            TestAssert.Throws<OperationCanceledException>(() => owner.InventoryCollection(() => { }, cancelled.Token), "Cancelled collection scan continued.");
            var after = Directory.GetFiles(root, "*", SearchOption.AllDirectories);
            TestAssert.That(after.Length == before.Count && after.All(path => before.TryGetValue(path, out var bytes) && File.ReadAllBytes(path).SequenceEqual(bytes)),
                "Collection inventory wrote, removed or changed source/private files.");
            var nestedMoved = Path.Combine(root, "old-album"); Directory.Move(nested, nestedMoved); Directory.CreateDirectory(nested);
            File.WriteAllBytes(Path.Combine(nested, "two.mp4"), [4, 5, 6, 7]);
            TestAssert.Throws<InvalidDataException>(() => owner.OpenCollectionMember(second, () => { }), "Equal-name/content replacement subtree was adopted as old inventory.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
