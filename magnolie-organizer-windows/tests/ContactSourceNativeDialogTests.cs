using System.Collections;
using System.Reflection;
using System.Runtime.Loader;

namespace MagnolieOrganizer.Windows.Tests;

// Opt-in source-only Windows modal probe. It loads only the consent dialog with
// a blank owner/synthetic catalog, never MainForm, profiles, accounts or DAV IO.
internal static class ContactSourceNativeDialogTests
{
    internal static async Task RunAsync(string productFolder)
    {
        if (!OperatingSystem.IsWindows()) throw new InvalidOperationException("native_consent_windows_required");
        var context = AssemblyLoadContext.Default;
        Assembly? Resolve(AssemblyLoadContext _, AssemblyName name)
        {
            var file = Path.Combine(productFolder, name.Name + ".dll");
            return File.Exists(file) ? context.LoadFromAssemblyPath(file) : null;
        }
        context.Resolving += Resolve;
        try
        {
            var product = context.LoadFromAssemblyPath(Path.Combine(productFolder, "Magnolie Organizer.dll"));
            var forms = Assembly.Load("System.Windows.Forms");
            if (forms.GetType("System.Windows.Forms.SystemInformation", true)!.GetProperty("UserInteractive")!.GetValue(null) is not true)
                throw new InvalidOperationException("native_consent_interactive_desktop_required");
            var formType = forms.GetType("System.Windows.Forms.Form", true)!;
            var timerType = forms.GetType("System.Windows.Forms.Timer", true)!;
            var sourceType = product.GetType("MagnolieOrganizer.Windows.NextcloudDavSource", true)!;
            var choose = product.GetType("MagnolieOrganizer.Windows.ContactSourceApprovalDialog", true)!
                .GetMethod("ChooseAsync", BindingFlags.Static | BindingFlags.NonPublic)!;
            var sources = Array.CreateInstance(sourceType, 2);
            for (var index = 0; index < 2; index++) sources.SetValue(Activator.CreateInstance(sourceType,
                "synthetic-source-" + index, "Synthetic\u202e name " + index, "addressbook",
                new Uri("https://consent.invalid/book-" + index + "/"), false, false, true), index);
            foreach (var mode in new[] { "cancel", "choose", "cancel-token" })
            {
                using var cancellation = new CancellationTokenSource();
                var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                var thread = new Thread(() =>
                {
                    using var owner = (IDisposable)Activator.CreateInstance(formType)!;
                    using var timer = (IDisposable)Activator.CreateInstance(timerType)!;
                    Exception? fault = null; var inspected = false;
                    try
                    {
                        formType.GetProperty("Text")!.SetValue(owner, "Synthetic isolated consent owner");
                        var openForms = forms.GetType("System.Windows.Forms.Application", true)!.GetProperty("OpenForms")!;
                        timerType.GetProperty("Interval")!.SetValue(timer, 40);
                        EventHandler tick = (_, _) =>
                        {
                            var dialog = ((IEnumerable)openForms.GetValue(null)!).Cast<object>().FirstOrDefault(value =>
                                (string?)formType.GetProperty("Text")!.GetValue(value) == "Original contact sources");
                            if (dialog is null) return;
                            try
                            {
                                var controls = Descendants(dialog).ToArray();
                                var choices = controls.Single(value => value.GetType().Name == "CheckedListBox");
                                var items = (IList)choices.GetType().GetProperty("Items")!.GetValue(choices)!;
                                var checkedItems = (IList)choices.GetType().GetProperty("CheckedIndices")!.GetValue(choices)!;
                                TestAssert.That(items.Count == 2 && checkedItems.Count == 0 &&
                                    !items[0]!.ToString()!.Contains('\u202e') && items[0]!.ToString()!.Contains("https://consent.invalid/book-0/", StringComparison.Ordinal),
                                    "Actual native dialog defaulted to approval or hid original collection identity");
                                inspected = true; timerType.GetMethod("Stop")!.Invoke(timer, null);
                                if (mode == "cancel-token") { cancellation.Cancel(); return; }
                                if (mode == "choose") choices.GetType().GetMethod("SetItemChecked")!.Invoke(choices, [1, true]);
                                var label = mode == "choose" ? "Apply" : "Cancel";
                                var button = controls.Single(value => value.GetType().Name == "Button" &&
                                    (string?)value.GetType().GetProperty("Text")!.GetValue(value) == label);
                                button.GetType().GetMethod("PerformClick")!.Invoke(button, null);
                            }
                            catch (Exception error) { fault = error; formType.GetMethod("Close")!.Invoke(dialog, null); }
                        };
                        timerType.GetEvent("Tick")!.AddEventHandler(timer, tick);
                        timerType.GetMethod("Start")!.Invoke(timer, null);
                        var task = (Task<IReadOnlyList<string>?>)choose.Invoke(null,
                            [owner, sources, Array.Empty<string>(), (Func<string, string>)(value => value), cancellation.Token])!;
                        IReadOnlyList<string>? answer = null;
                        try { answer = task.GetAwaiter().GetResult(); }
                        catch (OperationCanceledException) when (mode == "cancel-token") { }
                        if (fault is not null) throw fault;
                        TestAssert.That(inspected && (mode == "choose" ? answer?.SequenceEqual(new[] { "synthetic-source-1" }) == true : answer is null),
                            "Actual native modal decision/cancellation widened consent: " + mode);
                        completion.TrySetResult(true);
                    }
                    catch (Exception error) { completion.TrySetException(error); }
                    finally { timerType.GetMethod("Stop")!.Invoke(timer, null); formType.GetMethod("Close")!.Invoke(owner, null); }
                }) { IsBackground = true, Name = "Magnolie synthetic native consent" };
                thread.SetApartmentState(ApartmentState.STA); thread.Start();
                try { await completion.Task.WaitAsync(TimeSpan.FromSeconds(12)); }
                finally { cancellation.Cancel(); TestAssert.That(thread.Join(TimeSpan.FromSeconds(3)), "Owned consent UI thread did not terminate"); }
            }
            Console.WriteLine("PASS native modal source consent: default OFF, exact URI, synthetic Apply/Cancel/cancellation; no profiles/providers/installation");
        }
        finally { context.Resolving -= Resolve; }
    }

    private static IEnumerable<object> Descendants(object control)
    {
        foreach (var child in (IEnumerable)control.GetType().GetProperty("Controls")!.GetValue(control)!)
        {
            yield return child;
            foreach (var descendant in Descendants(child)) yield return descendant;
        }
    }
}
