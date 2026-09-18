using MagnolieOrganizer.Windows;

// Actual Windows journal and phone code, with no backend/service dependencies.
var root = Path.Combine(Path.GetTempPath(), "aur-sms-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    void Check(bool condition, string label) { if (!condition) throw new Exception(label); }
    foreach (var clientRef in new[] { "plan:synthetic", "immediate-stable-ref" })
    {
        var path = Path.Combine(root, Guid.NewGuid().ToString("N") + ".json");
        var journal = new SmsSubmissionJournal(path);
        Check(journal.Reserve(clientRef, "+447700900123", "Synthetic secret body", "GB") is null, "first reservation");
        Check(new SmsSubmissionJournal(path).Reserve(clientRef, "+447700900123", "Synthetic secret body", "GB") == "uncertain", "restart reservation");
        journal.Submitted(clientRef);
        Check(new SmsSubmissionJournal(path).Reserve(clientRef, "+447700900123", "Synthetic secret body", "GB") == "submitted", "sent content replay");
        var rejected = false;
        try { journal.Reserve(clientRef, "+447700900123", "changed", "GB"); }
        catch (InvalidDataException) { rejected = true; }
        Check(rejected, "payload mismatch");
        foreach (var file in new[] { path, AtomicStore.BackupPath(path) })
        {
            var json = File.ReadAllText(file);
            Check(!json.Contains(clientRef) && !json.Contains("447700900123") && !json.Contains("Synthetic secret body"), "digest-only storage");
        }
    }
    Console.WriteLine("PASS Windows SmsSubmissionJournal: plan/immediate, restart, uncertain, submitted, mismatch, digest-only");
    foreach (var (country, number, expected) in new[] {
        ("GB", "07700 900123", "+447700900123"), ("DE", "0170 1234567", "+491701234567"),
        ("AT", "0664 1234567", "+436641234567"), ("CH", "079 1234567", "+41791234567"),
        ("IT", "02 12345678", "+390212345678"), ("FR", "06 12 34 56 78", "+33612345678"),
        ("US", "202 555 0123", "+12025550123"), ("AU", "0412 345 678", "+61412345678") })
    {
        Check(PhoneUri.Normalize(number, country) == expected, country + " national");
        Check(PhoneUri.Normalize(expected, "ZZ") == expected, country + " explicit");
    }
    Check(PhoneUri.Normalize("07700900123", "ZZ") == "", "unknown country");
    Check(PhoneUri.Normalize("+490123456789", "GB") == "+490123456789", "explicit E.164 unchanged");
    Check(PhoneUri.Normalize("+44 (0)7700 900123", "DE") == "+447700900123", "optional trunk prefix");
    Console.WriteLine("PASS Windows PhoneUri: GB/DE/AT/CH/IT/FR/US/AU, unknown and explicit E.164");
}
finally { Directory.Delete(root, true); }

namespace MagnolieOrganizer.Windows
{
    internal static class NativeLocalization
    {
        internal static string Gettext(string text) => text;
    }
}
