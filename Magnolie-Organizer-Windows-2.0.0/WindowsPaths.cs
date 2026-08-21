namespace MagnolieOrganizer.Windows;

internal sealed class WindowsPaths
{
    internal WindowsPaths(string? root = null)
    {
        Root = root ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Magnolie Organizer");
        Data = Path.Combine(Root, "daten.json");
        Settings = Path.Combine(Root, "fenster.json");
        TraySettings = Path.Combine(Root, "tray.json");
        ReminderState = Path.Combine(Root, "erinnerungen.json");
        ReminderData = Path.Combine(Root, "erinnerungsdaten.json");
        Baum = Path.Combine(Root, "baum.json");
        BaumOutbox = Path.Combine(Root, "baum-post.json");
        BaumInbox = Path.Combine(Root, "baum-eingang.json");
        BaumMailboxSettings = Path.Combine(Root, "baum-briefkasten.json");
        BaumMailboxPassword = Path.Combine(Root, "baum-briefkasten-kennwort.dpapi");
        NextcloudSyncJournal = Path.Combine(Root, "nextcloud-sync-journal.dpapi");
        Telefon = Path.Combine(Root, "Telefon");
        TelefonIdentity = Path.Combine(Telefon, "identity.json");
        TelefonIdentityKey = Path.Combine(Telefon, "identity.key");
        TelefonStorageKey = Path.Combine(Telefon, "storage.key");
        TelefonPeers = Path.Combine(Telefon, "peers.json");
        TelefonDatabase = Path.Combine(Telefon, "phone.db");
        TelefonStatusCache = Path.Combine(Telefon, "status-cache.json");
        TelefonSettings = Path.Combine(Telefon, "settings.json");
        KdeConnect = Path.Combine(Root, "KDE Connect");
        KdeConnectIdentity = Path.Combine(KdeConnect, "identity.json");
        KdeConnectIdentityKey = Path.Combine(KdeConnect, "identity.pfx.dpapi");
        KdeConnectPeers = Path.Combine(KdeConnect, "peers.json");
        Logs = Path.Combine(Root, "Logs");
        WebView = Path.Combine(Root, "WebView2");
        RecoveryJournal = Path.Combine(Root, "wiederherstellungsstaende");
        RecoverySettings = Path.Combine(Root, "wiederherstellungsjournal.json");
        Backups = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Magnolie Organizer", "Sicherungen");
    }

    internal string Root { get; }
    internal string Data { get; }
    internal string Settings { get; }
    internal string TraySettings { get; }
    internal string ReminderState { get; }
    internal string ReminderData { get; }
    internal string Baum { get; }
    internal string BaumOutbox { get; }
    internal string BaumInbox { get; }
    internal string BaumMailboxSettings { get; }
    internal string BaumMailboxPassword { get; }
    internal string NextcloudSyncJournal { get; }
    internal string Telefon { get; }
    internal string TelefonIdentity { get; }
    internal string TelefonIdentityKey { get; }
    internal string TelefonStorageKey { get; }
    internal string TelefonPeers { get; }
    internal string TelefonDatabase { get; }
    internal string TelefonStatusCache { get; }
    internal string TelefonSettings { get; }
    internal string KdeConnect { get; }
    internal string KdeConnectIdentity { get; }
    internal string KdeConnectIdentityKey { get; }
    internal string KdeConnectPeers { get; }
    internal string Logs { get; }
    internal string WebView { get; }
    internal string RecoveryJournal { get; }
    internal string RecoverySettings { get; }
    internal string Backups { get; }

    internal void EnsureDirectories()
    {
        Directory.CreateDirectory(Root);
        Directory.CreateDirectory(Logs);
        Directory.CreateDirectory(WebView);
        Directory.CreateDirectory(Telefon);
        Directory.CreateDirectory(KdeConnect);
    }
}
