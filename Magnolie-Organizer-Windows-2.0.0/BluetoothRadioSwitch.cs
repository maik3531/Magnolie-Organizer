namespace MagnolieOrganizer.Windows;

/// <summary>
/// Zugriff auf das Bluetooth-Funkgerät. Bewusst als Schnittstelle: Die
/// Buchführung unten muss ohne WinRT prüfbar sein, weil das Testprojekt auf
/// <c>net8.0</c> ohne Windows-Laufzeit zielt.
/// </summary>
internal interface IBluetoothRadio
{
    /// <summary>Ein, aus, oder <c>null</c>, wenn kein Zugriff besteht.</summary>
    Task<bool?> IsOnAsync();
    /// <summary>Schaltet und meldet, ob es gelungen ist.</summary>
    Task<bool> SetAsync(bool on);
}

/// <summary>
/// Kein Funkgerät. Rückfall, solange keines gereicht wurde – etwa im
/// Testprojekt, das ohne WinRT übersetzt.
/// </summary>
internal sealed class NoBluetoothRadio : IBluetoothRadio
{
    public Task<bool?> IsOnAsync() => Task.FromResult<bool?>(null);
    public Task<bool> SetAsync(bool on) => Task.FromResult(false);
}

/// <summary>
/// Schaltet das Bluetooth-Funkgerät für die Dauer eines Gesprächs ein und
/// stellt danach den vorherigen Zustand wieder her.
///
/// Den Ton eines Anrufs überträgt nicht der Organizer, sondern das Telefon
/// selbst über das Bluetooth-Freisprechprofil des Betriebssystems; der
/// Organizer führt ausschließlich die Steuerung. Damit der Ton am Rechner
/// ankommt, muss der Funk an sein – und damit man ihn nicht dauerhaft laufen
/// lassen muss, geschieht das nur rund um das Gespräch.
///
/// Ausgeschaltet wird ausschließlich, was diese Klasse selbst eingeschaltet
/// hat und was seither niemand sonst wieder abgeschaltet hat. Wer eine
/// Bluetooth-Maus oder Kopfhörer benutzt, hatte den Funk vorher an; dann
/// bleibt er an. Das ist der Grund für die Buchführung: Ein pauschales „nach
/// dem Gespräch aus“ risse solche Geräte mit.
///
/// Der Anruf wird über WLAN gemeldet, der Ton läuft über Bluetooth – zwei
/// getrennte Wege. Deshalb gibt es auch bei einem eingehenden Anruf einen
/// Auslöser, obwohl der Funk in dem Moment noch aus ist.
/// </summary>
internal sealed class BluetoothRadioSwitch
{
    /// <summary>Nach dieser Zeit gilt ein Wählauftrag ohne Anrufzustand als erledigt.</summary>
    internal static readonly TimeSpan DialHold = TimeSpan.FromSeconds(60);

    private readonly object gate = new();
    private readonly Dictionary<string, long> holds = new(StringComparer.Ordinal);
    private readonly IBluetoothRadio radio;
    private readonly Func<long> clock;
    private readonly Func<TimeSpan, Task> delay;
    private bool switchedOn;

    internal BluetoothRadioSwitch(IBluetoothRadio? radio = null, Func<long>? clock = null,
        Func<TimeSpan, Task>? delay = null)
    {
        this.radio = radio ?? new NoBluetoothRadio();
        this.clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        this.delay = delay ?? Task.Delay;
    }

    /// <summary>Hält der Organizer den Funk gerade selbst?</summary>
    internal bool HoldsRadio { get { lock (gate) return switchedOn; } }

    /// <summary>Anzahl der Vorgänge, die den Funk derzeit beanspruchen.</summary>
    internal int ActiveHolds { get { lock (gate) { Expire(); return holds.Count; } } }

    /// <summary>
    /// Meldet einen Vorgang an, der den Funk braucht. Beim ersten Vorgang wird
    /// eingeschaltet, falls der Funk aus ist.
    /// </summary>
    internal async Task RequestAsync(string key, bool temporary = false)
    {
        bool first; long expires;
        lock (gate)
        {
            Expire();
            expires = temporary ? clock() + (long)DialHold.TotalMilliseconds : long.MaxValue;
            holds[key] = expires;
            first = holds.Count == 1;
        }
        if (first && await radio.IsOnAsync().ConfigureAwait(false) == false)
        {
            var ok = await radio.SetAsync(true).ConfigureAwait(false);
            lock (gate) switchedOn = ok;
        }
        if (temporary) _ = ExpireAfterAsync(key, expires);
    }

    /// <summary>
    /// Meldet einen Vorgang ab. Ist keiner mehr offen und war der Funk vorher
    /// aus, wird er wieder ausgeschaltet.
    /// </summary>
    internal async Task ReleaseAsync(string key)
    {
        bool restore;
        lock (gate)
        {
            holds.Remove(key); Expire();
            restore = holds.Count == 0 && switchedOn;
            if (restore) switchedOn = false;
        }
        if (!restore) return;
        /* Hat der Benutzer den Funk zwischenzeitlich selbst ausgeschaltet,
           bleibt es dabei. */
        if (await radio.IsOnAsync().ConfigureAwait(false) != true) return;
        await radio.SetAsync(false).ConfigureAwait(false);
    }

    /// <summary>Gibt alle Vorgänge eines Telefons frei, etwa am Gesprächsende.</summary>
    internal async Task ReleaseAllAsync(string peerId)
    {
        string[] betroffen;
        lock (gate) betroffen = holds.Keys.Where(item =>
            item.EndsWith("/" + peerId, StringComparison.Ordinal)).ToArray();
        foreach (var key in betroffen) await ReleaseAsync(key).ConfigureAwait(false);
    }

    /// <summary>Entfernt abgelaufene Wählaufträge, zu denen nie ein Anruf kam.</summary>
    private void Expire()
    {
        var now = clock();
        foreach (var abgelaufen in holds.Where(item => item.Value <= now).Select(item => item.Key).ToArray())
            holds.Remove(abgelaufen);
    }

    private async Task ExpireAfterAsync(string key, long expectedExpiry)
    {
        await delay(DialHold).ConfigureAwait(false);
        bool restore;
        lock (gate)
        {
            if (!holds.TryGetValue(key, out var expiry) || expiry != expectedExpiry || expiry > clock()) return;
            holds.Remove(key);
            restore = holds.Count == 0 && switchedOn;
            if (restore) switchedOn = false;
        }
        if (restore && await radio.IsOnAsync().ConfigureAwait(false) == true)
            await radio.SetAsync(false).ConfigureAwait(false);
    }
}
