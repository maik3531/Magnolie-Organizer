using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class OfficeProfileTests
{
    internal static Task RunAsync()
    {
        var directory = Path.Combine(Path.GetTempPath(), "office-profile-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(directory, "user"));
        try
        {
            var path = Path.Combine(directory, "user", "registrymodifications.xcu");
            File.WriteAllText(path, "<oor:items xmlns:oor=\"http://openoffice.org/2001/registry\"><!--keep--><item oor:path=\"/org.openoffice.UserProfile/Data\"><prop oor:name=\"givenname\"><value>Before</value></prop><prop oor:name=\"mail\"><value>keep@example.invalid</value></prop></item><item oor:path=\"/org.openoffice.Other\"><prop oor:name=\"setting\"><value>unchanged</value></prop></item></oor:items>");
            var initial = JsonSerializer.SerializeToElement(LibreOfficeUserData.ExchangeProfile("test", "read", new Dictionary<string, string>(), "", path));
            var stamp = initial.GetProperty("stamp").GetString()!;
            var updated = JsonSerializer.SerializeToElement(LibreOfficeUserData.ExchangeProfile("test", "write",
                new Dictionary<string, string> { ["givenname"] = "After & more", ["street"] = "Test road 1" }, stamp, path));
            TestAssert.That(updated.GetProperty("felder").GetProperty("mail").GetString() == "keep@example.invalid", "Unselected profile field changed.");
            var saved = File.ReadAllText(path);
            TestAssert.That(saved.Contains("<!--keep-->") && saved.Contains("<value>unchanged</value>") && saved.Contains("After &amp; more"), "Unrelated Office content or XML escaping changed.");
            TestAssert.Throws<IOException>(() => LibreOfficeUserData.ExchangeProfile("test", "write", new Dictionary<string, string> { ["givenname"] = "stale" }, stamp, path), "Stale comparison overwrote Office data.");
            File.WriteAllText(Path.Combine(directory, ".lock"), "running");
            TestAssert.Throws<IOException>(() => LibreOfficeUserData.ExchangeProfile("test", "write", new Dictionary<string, string> { ["givenname"] = "running" }, updated.GetProperty("stamp").GetString()!, path), "Running Office profile was overwritten.");
            TestAssert.That(File.ReadAllText(path) == saved, "Rejected write changed Office settings.");
        }
        finally { Directory.Delete(directory, true); }
        return Task.CompletedTask;
    }
}
