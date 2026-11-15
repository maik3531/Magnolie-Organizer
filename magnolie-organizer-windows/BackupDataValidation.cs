using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Minimum legacy profile shape, not a new version/full-schema requirement.
// Unknown fields and valid old partial/empty collections remain untouched.
internal static class BackupDataValidation
{
    internal static void Validate(JsonObject data)
    {
        var recognized = false;
        foreach (var name in new[] { "notizen", "aufgaben", "termine", "kontakte", "jahrestage", "notizgruppen", "notizbuecher", "personen" })
        {
            if (data[name] is null) continue;
            if (data[name] is not JsonArray) throw Invalid();
            recognized = true;
        }
        foreach (var name in new[] { "einstellungen", "gesundheit", "customOrganizer", "zeiterfassung" })
        {
            if (data[name] is null) continue;
            if (data[name] is not JsonObject) throw Invalid();
            recognized = true;
        }
        if (!recognized) throw Invalid();
    }

    private static InvalidDataException Invalid() => new(NativeLocalization.Gettext("The backup does not contain a complete data set."));
}
