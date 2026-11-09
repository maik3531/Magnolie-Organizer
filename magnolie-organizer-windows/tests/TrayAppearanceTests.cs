using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TrayAppearanceTests
{
    internal static Task VisualLeaseAsync()
    {
        const string saved = "{\"einstellungen\":{\"allgemein\":{\"entwicklermodus\":true}}}";
        TestAssert.That(TrayVisualTest.SavedDeveloperMode(saved, true) && !TrayVisualTest.SavedDeveloperMode(saved, false), "Saved developer flag ignored native lock.");
        foreach (var invalid in new[] { "{}", "[]", "null", "invalid", saved.Replace("true", "1"), saved.Replace("true", "false"), saved.Replace("true", "\"true\"") })
            TestAssert.That(!TrayVisualTest.SavedDeveloperMode(invalid, true), "Malformed/truthy saved flag enabled native test.");
        var lease = new TrayVisualTest(); var owner = new object();
        System.Text.Json.JsonDocument Request(string connection = "both", string mode = "camera", string sync = "true", string extra = "")
            => System.Text.Json.JsonDocument.Parse("{\"cmd\":\"tray_darstellung_test\",\"connection\":\"" + connection +
                "\",\"mode\":\"" + mode + "\",\"sync\":" + sync + extra + "}");
        using var valid = Request();
        using var bridge = BridgeDispatcherContract.Parse(valid.RootElement.GetRawText());
        using var clear = BridgeDispatcherContract.Parse("{\"cmd\":\"tray_darstellung_test_ende\"}");
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"tray_darstellung_test\",\"connection\":\"both\",\"mode\":\"camera\",\"sync\":1}"), "Bridge accepted a non-boolean visual state.");
        TestAssert.Throws<InvalidOperationException>(() => lease.Start(valid.RootElement, false, owner, 100), "Browser preview bypassed saved developer gate.");
        foreach (var connection in new[] { "none", "notes", "kde", "both" }) foreach (var mode in new[] { "flower", "camera", "phone" })
        foreach (var sync in new[] { "true", "false" })
        {
            using var request = Request(connection, mode, sync); lease.Start(request.RootElement, true, owner, 100);
            TestAssert.That(lease.Current(true, owner, 60099).HasValue && !lease.Current(true, owner, 60100).HasValue, "Native preview deadline was not exactly 60 seconds.");
        }
        lease.Start(valid.RootElement, true, owner, 100);
        TestAssert.That(!lease.Current(true, new object(), 101).HasValue, "New book retained old preview.");
        lease.Start(valid.RootElement, true, owner, 100);
        TestAssert.That(!lease.Current(false, owner, 101).HasValue, "Lock/developer disable retained preview.");
        foreach (var request in new[] { Request("paired"), Request(mode: "live_camera"), Request(sync: "1"), Request(extra: ",\"ready\":true"), Request(extra: ",\"sync\":false") })
        {
            using (request)
            {
                var rejected = false;
                try { lease.Start(request.RootElement, true, owner, 100); }
                catch (Exception error) when (error is InvalidOperationException or InvalidDataException) { rejected = true; }
                TestAssert.That(rejected && !lease.HasLease, "Malformed/native-readiness claim was accepted as visual state.");
            }
        }
        return Task.CompletedTask;
    }
    internal static Task DrawingAsync()
    {
        var folder = Path.Combine(AppContext.BaseDirectory, "preview-product");
        var context = System.Runtime.Loader.AssemblyLoadContext.Default;
        System.Reflection.Assembly? Resolve(System.Runtime.Loader.AssemblyLoadContext _, System.Reflection.AssemblyName name)
        {
            var path = Path.Combine(folder, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        }
        context.Resolving += Resolve;
        try
        {
            var product = context.LoadFromAssemblyPath(Path.Combine(folder, "Magnolie Organizer.dll"));
            var renderer = product.GetType("MagnolieOrganizer.Windows.TrayAppearanceRenderer", true)!;
            var stateType = product.GetType("MagnolieOrganizer.Windows.TrayAppearanceState", true)!;
            var connectionType = product.GetType("MagnolieOrganizer.Windows.TrayFlowerConnection", true)!;
            var modeType = product.GetType("MagnolieOrganizer.Windows.TrayAppearanceMode", true)!;
            var create = renderer.GetMethod("Create", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
            var drawing = context.LoadFromAssemblyPath(Path.Combine(folder, "System.Drawing.Common.dll"));
            var iconType = drawing.GetType("System.Drawing.Icon", true)!;
            using var original = (IDisposable)Activator.CreateInstance(iconType, Path.Combine(folder, "magnolie-organizer.ico"), new System.Drawing.Size(256, 256))!;
            var toBitmap = iconType.GetMethod("ToBitmap", Type.EmptyTypes)!;
            var idle = Activator.CreateInstance(stateType, Enum.ToObject(connectionType, 0), false, Enum.ToObject(modeType, 0))!;
            using var baselineIcon = (IDisposable)create.Invoke(null, new object[] { original, idle })!;
            using var before = (IDisposable)toBitmap.Invoke(baselineIcon, null)!;
            // Compare at the renderer's common 256px scale; GDI may select a
            // smaller image from a multi-resolution original ICO.
            var getPixel = before.GetType().GetMethod("GetPixel")!;
            for (var connection = 0; connection < 4; connection++)
            for (var mode = 0; mode < 3; mode++)
            foreach (var sync in new[] { false, true })
            {
                var state = Activator.CreateInstance(stateType, Enum.ToObject(connectionType, connection), sync, Enum.ToObject(modeType, mode))!;
                using var icon = (IDisposable)create.Invoke(null, new object[] { original, state })!;
                using var bitmap = (IDisposable)toBitmap.Invoke(icon, null)!;
                TestAssert.That((int)bitmap.GetType().GetProperty("Width")!.GetValue(bitmap)! == 256, "Native generated icon size changed.");
                if (mode == 0 && !sync)
                {
                    foreach (var point in new[] { (42,60), (198,80), (121,188), (21,62), (228,100) })
                        TestAssert.That(Equals(getPixel.Invoke(before, new object[] { point.Item1, point.Item2 }),
                            getPixel.Invoke(bitmap, new object[] { point.Item1, point.Item2 })), "Flower recoloring changed a frame/binding/book pixel.");
                    if (connection > 0)
                    {
                        var expected = connection switch { 1 => (255,255,255), 2 => (247,215,119), _ => (238,152,70) };
                        var matches = 0;
                        for (var x = 82; x < 161; x += 2) for (var y = 80; y < 173; y += 2)
                        {
                            var pixel = (System.Drawing.Color)getPixel.Invoke(bitmap, new object[] { x, y })!;
                            if (Math.Abs(pixel.R - expected.Item1) < 6 && Math.Abs(pixel.G - expected.Item2) < 6 && Math.Abs(pixel.B - expected.Item3) < 6) matches++;
                        }
                        TestAssert.That(matches > 20, "Actual native raster did not contain its required flower color.");
                    }
                }
            }
            // Repeated HICON creation/disposal must not accumulate native GDI resources.
            var baseline = GetGuiResources(System.Diagnostics.Process.GetCurrentProcess().Handle, 0);
            var userBaseline = GetGuiResources(System.Diagnostics.Process.GetCurrentProcess().Handle, 1);
            for (var i = 0; i < 80; i++)
            {
                var state = Activator.CreateInstance(stateType, Enum.ToObject(connectionType, i % 4), true, Enum.ToObject(modeType, i % 3))!;
                using var icon = (IDisposable)create.Invoke(null, new object[] { original, state })!;
            }
            var after = GetGuiResources(System.Diagnostics.Process.GetCurrentProcess().Handle, 0);
            var userAfter = GetGuiResources(System.Diagnostics.Process.GetCurrentProcess().Handle, 1);
            TestAssert.That(after <= baseline + 2, $"Native renderer leaked GDI resources: {baseline} → {after}.");
            TestAssert.That(userAfter <= userBaseline + 2, $"Native renderer leaked USER/HICON resources: {userBaseline} → {userAfter}.");
        }
        finally { context.Resolving -= Resolve; }
        return Task.CompletedTask;
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern int GetGuiResources(IntPtr process, int flags);

    internal static Task OwnersAsync()
    {
        TestAssert.That(TrayAppearanceState.FromOwners(false, false, false).IsOriginal, "Idle icon changed.");
        TestAssert.That(TrayAppearanceState.FromOwners(true, false, false).Connection == TrayFlowerConnection.Notes &&
            TrayAppearanceState.FromOwners(false, true, false).Connection == TrayFlowerConnection.Kde &&
            TrayAppearanceState.FromOwners(true, true, true) == new TrayAppearanceState(TrayFlowerConnection.Both, true), "Native color/activity matrix changed.");
        var activity = new NativeSyncActivity(); var states = new List<bool>();
        activity.Changed += () => states.Add(activity.Active);
        activity.Changed += () => throw new InvalidOperationException("visual observer fixture");
        var first = activity.Enter(); var second = activity.Enter();
        first.Dispose(); first.Dispose();
        TestAssert.That(activity.Active, "First/duplicate end hid another actual owner.");
        second.Dispose(); TestAssert.That(!activity.Active && states.SequenceEqual(new[] { true, true, true, false }), "Lease activity did not finish exactly once.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-tray-lazy-" + Guid.NewGuid().ToString("N"));
        using var facade = new KdeConnectSms(new WindowsPaths(root));
        TestAssert.That(!facade.HasLiveConnection && !Directory.Exists(root), "Passive facade created transport/identity files.");
        return Task.CompletedTask;
    }
}
