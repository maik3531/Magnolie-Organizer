using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhotoSyncPlanTests
{
    internal static Task RunAsync()
    {
        const string relative = "contracts/photo-sync-plan-v1-vectors.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!;
        var contents = vectors["contents"]!.AsObject().ToDictionary(pair => pair.Key, pair =>
            new PhotoContentWitness(pair.Value!["sha256"]!.GetValue<string>(), pair.Value["size"]!.GetValue<long>()), StringComparer.Ordinal);
        var association = new NativePhotoAssociation(new DeviceTransferBinding("sender_fixture_01", "receiver_fixture_01",
            new string('d', 64), new string('e', 64), new string('f', 64), new string('0', 64)), new string('a', 64), new string('b', 64), new string('c', 64));
        foreach (var item in vectors["cases"]!.AsArray())
        {
            var test = item!.AsObject(); var name = test["name"]!.GetValue<string>();
            var baselineName = test["baseline"]?.GetValue<string>();
            var baseline = baselineName is null ? null : new NativePhotoBaseline(association, contents[baselineName], new string('9', 64));
            NativePhotoObservation Observation(string side)
            {
                var label = test[side]!.GetValue<string>();
                return contents.TryGetValue(label, out var content)
                    ? new("present", content, side == "desktop" && (test["managed"]?.GetValue<bool>() ?? true),
                        side == "phone" && (test["insertion"]?.GetValue<bool>() ?? true)) : new(label);
            }
            var names = (test["support"] ?? vectors["default_support"])!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            var support = new NativePhotoPlanSupport(names.Contains("create_desktop"), names.Contains("replace_desktop"), names.Contains("trash_desktop"), names.Contains("replace_phone"), names.Contains("delete_phone"));
            var policy = new PhotoSyncPlanPolicy(test["direction"]?.GetValue<string>() ?? "phone_to_desktop",
                test["phone_delete"]?.GetValue<bool>() ?? false, test["pc_delete"]?.GetValue<bool>() ?? false);
            var phone = Observation("phone"); var desktop = Observation("desktop");
            var proposal = PhotoSyncPlan.Compare(association, baseline, phone, desktop, policy, support);
            TestAssert.That(proposal.Kind == test["expected"]!.GetValue<string>(), $"Three-way photo vector differs: {name} ({proposal.Kind}).");
            TestAssert.That(!proposal.GrantsWriteAuthority && !proposal.IsSavedReceipt && proposal.BaselineReceipt == baseline?.ReceiptSha256 &&
                proposal.ExpectedPhone == phone.Content && proposal.ExpectedDesktop == desktop.Content, "Comparison manufactured write/receipt authority or lost original expected bytes.");
        }
        var original = new NativePhotoBaseline(association, contents["old"], new string('9', 64));
        var changes = new[]
        {
            new NativePhotoAssociation(association.Binding, new string('1', 64), association.PhotoId, association.TargetMappingToken),
            new NativePhotoAssociation(association.Binding, association.SourceEpoch, new string('1', 64), association.TargetMappingToken),
            new NativePhotoAssociation(association.Binding, association.SourceEpoch, association.PhotoId, new string('1', 64)),
            new NativePhotoAssociation(association.Binding with { SenderIdentitySha256 = new string('1', 64) }, association.SourceEpoch, association.PhotoId, association.TargetMappingToken),
            new NativePhotoAssociation(association.Binding with { ReceiverIdentitySha256 = new string('1', 64) }, association.SourceEpoch, association.PhotoId, association.TargetMappingToken),
            new NativePhotoAssociation(association.Binding with { PermissionEpoch = new string('1', 64) }, association.SourceEpoch, association.PhotoId, association.TargetMappingToken),
            new NativePhotoAssociation(association.Binding with { DestinationToken = new string('1', 64) }, association.SourceEpoch, association.PhotoId, association.TargetMappingToken)
        };
        foreach (var changed in changes)
            TestAssert.That(PhotoSyncPlan.Compare(changed, original, new("deleted"), new("present", contents["old"], managed: true),
                new("bidirectional", true, true), new(true, true, true, true, true)).Kind == "pause_scope_changed", "Changed source/target/peer reinterpreted an old baseline as deletion.");
        var defaults = new PhotoSyncPlanPolicy();
        TestAssert.That(defaults.Direction == "phone_to_desktop" && !defaults.PhoneDeletionsToDesktop && !defaults.DesktopDeletionsToPhone,
            "Reverse writes/deletions are not off by default.");
        TestAssert.That(PhotoSyncPlan.Compare(association, null, new("present", contents["old"]), new("missing")).Kind == "unsupported_desktop_create", "Native no-loss backend support was assumed.");
        TestAssert.Throws<InvalidDataException>(() => new PhotoContentWitness(new string('1', 64), -1), "Invalid byte witness accepted.");
        TestAssert.Throws<InvalidDataException>(() => new PhotoContentWitness(new string('1', 64), DeviceFileManifest.MaxFileBytes + 1), "Oversized photo witness accepted.");
        TestAssert.Throws<InvalidDataException>(() => new NativePhotoObservation("present"), "Unknown bytes became a present observation.");
        TestAssert.Throws<InvalidDataException>(() => new NativePhotoObservation("missing", contents["old"]), "Missing observation adopted cached bytes.");
        TestAssert.Throws<InvalidDataException>(() => new PhotoSyncPlanPolicy("automatic"), "Scheduling mode was misinterpreted as data-direction consent.");
        return Task.CompletedTask;
    }
}
