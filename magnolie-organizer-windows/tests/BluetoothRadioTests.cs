using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class BluetoothRadioTests
{
    /// <summary>Ein steuerbares Funkgerät, das jede Schaltung mitschreibt.</summary>
    private sealed class TestRadio(bool on, bool erlaubt = true) : IBluetoothRadio
    {
        internal bool On = on;
        internal readonly List<bool> Schaltungen = [];
        internal bool? Zugriff = null;

        public Task<bool?> IsOnAsync() => Task.FromResult(Zugriff is false ? (bool?)null : On);
        public Task<bool> SetAsync(bool value)
        {
            Schaltungen.Add(value);
            if (!erlaubt) return Task.FromResult(false);
            On = value; return Task.FromResult(true);
        }
    }

    internal static async Task RunAsync()
    {
        /* Funk war aus: einschalten, nach dem Gespräch wieder ausschalten. */
        var aus = new TestRadio(on: false);
        var schalter = new BluetoothRadioSwitch(aus);
        await schalter.RequestAsync("anruf/telefon1");
        TestAssert.That(aus.On && schalter.HoldsRadio && schalter.ActiveHolds == 1,
            "Der Funk wurde für ein Gespräch nicht eingeschaltet.");
        await schalter.ReleaseAsync("anruf/telefon1");
        TestAssert.That(!aus.On && !schalter.HoldsRadio && schalter.ActiveHolds == 0,
            "Der vorher ausgeschaltete Funk blieb nach dem Gespräch an.");

        /* Funk war an – etwa wegen einer Bluetooth-Maus. Dann darf das
           Gesprächsende ihn keinesfalls ausschalten. */
        var an = new TestRadio(on: true);
        var schalter2 = new BluetoothRadioSwitch(an);
        await schalter2.RequestAsync("anruf/telefon1");
        await schalter2.ReleaseAsync("anruf/telefon1");
        TestAssert.That(an.On && an.Schaltungen.Count == 0,
            "Ein vorher eingeschalteter Funk wurde nach dem Gespräch abgeschaltet.");

        /* Der Benutzer schaltet während des Gesprächs selbst aus: dabei bleibt es. */
        var eigenhand = new TestRadio(on: false);
        var schalter3 = new BluetoothRadioSwitch(eigenhand);
        await schalter3.RequestAsync("anruf/telefon1");
        eigenhand.On = false; eigenhand.Schaltungen.Clear();
        await schalter3.ReleaseAsync("anruf/telefon1");
        TestAssert.That(eigenhand.Schaltungen.Count == 0,
            "Ein vom Benutzer ausgeschalteter Funk wurde erneut geschaltet.");

        /* Zwei Vorgänge gleichzeitig: erst der letzte stellt zurück. */
        var doppelt = new TestRadio(on: false);
        var schalter4 = new BluetoothRadioSwitch(doppelt);
        await schalter4.RequestAsync("waehlen/telefon1", temporary: true);
        await schalter4.RequestAsync("anruf/telefon1");
        await schalter4.ReleaseAsync("waehlen/telefon1");
        TestAssert.That(doppelt.On, "Der Funk ging aus, obwohl das Gespräch noch lief.");
        await schalter4.ReleaseAllAsync("telefon1");
        TestAssert.That(!doppelt.On && schalter4.ActiveHolds == 0,
            "Das Gesprächsende stellte den Funk nicht zurück.");

        /* Ein Wählauftrag ohne Anruf läuft ab und hält den Funk nicht ewig. */
        var uhr = 1_000_000L;
        var befristet = new TestRadio(on: false);
        var schalter5 = new BluetoothRadioSwitch(befristet, () => uhr);
        await schalter5.RequestAsync("waehlen/telefon1", temporary: true);
        TestAssert.That(schalter5.ActiveHolds == 1, "Der Wählauftrag wurde nicht vorgemerkt.");
        uhr += (long)BluetoothRadioSwitch.DialHold.TotalMilliseconds + 1;
        TestAssert.That(schalter5.ActiveHolds == 0, "Ein Wählauftrag ohne Anruf lief nicht ab.");
        var automatischeUhr = 2_000_000L;
        var automatisch = new TestRadio(on: false);
        var schalterAutomatisch = new BluetoothRadioSwitch(automatisch, () => automatischeUhr, delay: dauer =>
        {
            automatischeUhr += (long)dauer.TotalMilliseconds + 1;
            return Task.CompletedTask;
        });
        await schalterAutomatisch.RequestAsync("waehlen/telefon2", temporary: true);
        TestAssert.That(!automatisch.On && automatisch.Schaltungen.SequenceEqual(new[] { true, false }) &&
            schalterAutomatisch.ActiveHolds == 0,
            "Ein abgelaufener Wählauftrag stellte den zuvor ausgeschalteten Funk nicht automatisch zurück.");

        /* Ohne Zugriff auf das Funkgerät wird nichts geschaltet und nichts geworfen. */
        var ohne = new TestRadio(on: false) { Zugriff = false };
        var schalter6 = new BluetoothRadioSwitch(ohne);
        await schalter6.RequestAsync("anruf/telefon1");
        await schalter6.ReleaseAsync("anruf/telefon1");
        TestAssert.That(ohne.Schaltungen.Count == 0 && !schalter6.HoldsRadio,
            "Ohne Funkzugriff wurde dennoch geschaltet.");

        Console.WriteLine("BLUETOOTH-FUNKSCHALTER-OK");
    }
}
