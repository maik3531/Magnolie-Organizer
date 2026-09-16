using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class BridgeDispatcherContract
{
    internal const int MaximumCharacters = 384 * 1024 * 1024;
    internal const int MaximumUtf8Bytes = 384 * 1024 * 1024;
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly IReadOnlyDictionary<string, Schema> Schemas = new Dictionary<string, Schema>(StringComparer.Ordinal)
    {
        ["bereit"] = S(), ["entsperren"] = S(T("kennwort")),
        ["kennwort_setzen"] = S(T("alt"), T("neu"), O("sicherungen", JsonValueKind.True, JsonValueKind.False), O("sicherungsordner", JsonValueKind.String)),
        ["kennwort_entfernen"] = S(T("alt"), O("sicherungsordner", JsonValueKind.String)),
        ["speichern"] = S(N("id"), T("text")), ["contributor_pruefen"] = S(T("key")), ["beenden"] = S(), ["beenden_bereit"] = S(), ["beenden_abgebrochen"] = S(),
        ["ablage_kopieren"] = S(T("text")), ["ablage_holen"] = S(), ["sicherung"] = S(T("pfad"), T("kennwort")), ["sicherung_waehlen"] = S(),
        ["sicherung_wiederherstellen"] = S(T("pfad"), T("kennwort"), O("sicherungsordner", JsonValueKind.String)), ["journal_liste"] = S(), ["journal_erzeugen"] = S(), ["journal_manuell"] = S(),
        ["cloud_sicherung_status"] = S(), ["cloud_sicherung_kennwort"] = S(T("kennwort")), ["cloud_sicherung_test"] = S(),
        ["journal_vorschau"] = S(O("snapshotId", JsonValueKind.String), O("id", JsonValueKind.String)), ["journal_intervall"] = S(T("intervall")), ["journal_anzahl"] = S(N("maximum")),
        ["journal_aufbewahrung"] = S(T("modus"), N("maximum"), N("tage")),
        ["journal_loeschen"] = S(O("snapshotId", JsonValueKind.String), O("id", JsonValueKind.String)), ["journal_wiederherstellen"] = S(O("snapshotId", JsonValueKind.String), O("id", JsonValueKind.String), O("bereiche", JsonValueKind.Array), O("modus", JsonValueKind.String)),
        ["mutations_snapshot"] = S(T("token"), T("reason")), ["gesamtarchiv_waehlen"] = S(), ["gesamtarchiv_pruefen"] = S(T("pfad"), T("kennwort")),
        ["gesamtarchiv_importieren"] = S(T("pfad"), T("kennwort"), T("modus"), O("sicherungsordner", JsonValueKind.String)), ["gesamtarchiv_exportieren"] = S(T("kennwort")),
        ["ordner_waehlen"] = S(O("pfad", JsonValueKind.String)), ["drucken"] = S(O("html", JsonValueKind.String)),
        ["notiz_anhang_datei"] = S(N("id"), T("daten"), T("name"), O("aktion", JsonValueKind.String)),
        ["update_oeffnen"] = S(T("url")), ["handbuch_herunterladen"] = S(T("url"), T("sha256"), O("version", JsonValueKind.String), O("platform", JsonValueKind.String)),
        ["handbuch_oeffnen"] = S(), ["protokoll_zeigen"] = S(), ["medikament_suchen"] = S(T("name")),
        ["mail"] = S(T("email"), T("name")), ["karte"] = S(J("kontakt"), T("land"), O("dienst", JsonValueKind.String), O("route", JsonValueKind.True, JsonValueKind.False), O("absender", JsonValueKind.String)),
        ["sozial"] = S(T("dienst"), T("wert"), O("aktionArt", JsonValueKind.String), O("aktionZiel", JsonValueKind.String), O("land", JsonValueKind.String)),
        ["update_pruefen"] = S(), ["update_herunterladen"] = S(), ["update_installieren"] = S(),
        ["wetter"] = S(T("ort"), B("ohneOrtAbrufen"), N("kennung")),
        ["feiertage"] = S(T("land"), T("region"), A("regionen"), B("regionErforderlich"), A("jahre"), B("ferien")), ["regional_einstellungen"] = S(J("regional")), ["import"] = S(O("art", JsonValueKind.String), O("daten", JsonValueKind.String)),
        ["import_lokal"] = S(O("bereich", JsonValueKind.String)), ["export"] = S(T("art"), A("daten")), ["brief"] = S(J("kontakt"), O("absender", JsonValueKind.String), O("layout", JsonValueKind.String)),
        ["adressen_ods"] = S(T("titel"), A("spalten"), A("zeilen")),
        ["planer_ods"] = S(T("layout"), N("jahr"), O("monat", JsonValueKind.Number), T("titel"), A("spalten"), A("zeilen"), A("stile"), A("inhalte")),
        ["gesundheit_ods"] = S(A("tabellen")),
        ["eds_status"] = S(), ["sync"] = S(T("transactionId"), J("wahl"), J("daten")), ["sync_commit"] = S(T("transactionId")), ["graph_client_id_speichern"] = S(T("clientId")), ["graph_anmelden"] = S(), ["graph_abmelden"] = S(),
        ["lo_benutzer"] = S(), ["tray_einstellungen"] = S(J("einstellungen")), ["tray_zaehler"] = S(N("anzahl")),
        ["rechtschreibung"] = S(B("an"), O("sprache", JsonValueKind.String)), ["vorschlaege"] = S(T("wort"), T("kennung"), O("sprache", JsonValueKind.String)), ["wort_merken"] = S(T("wort"), O("sprache", JsonValueKind.String)),
        ["baum_stand"] = S(), ["baum_ein"] = S(B("an"), T("name")), ["baum_suchen"] = S(), ["baum_paaren"] = S(T("adresse"), O("port", JsonValueKind.Number, JsonValueKind.String), O("fingerabdruck", JsonValueKind.String)),
        ["baum_bestaetigen"] = S(T("kennung"), B("ja")), ["baum_entfernen"] = S(T("kennung")),
        ["baum_partner_einstellungen"] = S(T("kennung"), B("vertraut"), B("kontakte"), B("kontaktLoeschen"), T("fernAdresse"), O("fernPort", JsonValueKind.Number, JsonValueKind.String)),
        ["baum_delegieren"] = S(T("kennung"), J("aufgabe")), ["baum_teilen"] = S(T("kennung"), T("art"), J("inhalt")), ["baum_rueckmeldung"] = S(T("kennung"), J("stand")),
        ["baum_eingang_geleert"] = S(A("ids")), ["baum_paarungsdatei_erzeugen"] = S(T("adresse"), O("port", JsonValueKind.Number, JsonValueKind.String)),
        ["baum_paarungsdatei_importieren"] = S(), ["baum_internet_adresse"] = S(),
        ["baum_briefkasten_status"] = S(), ["baum_briefkasten_pruefen"] = S(),
        ["baum_briefkasten_speichern"] = S(B("davAktiv"), B("briefkastenAktiv"), T("url"), T("benutzer"), T("anwendungskennwort"), B("kennwortLoeschen"), O("kontoArt", JsonValueKind.String)),
        ["erinnerung_zeigen"] = S(T("kopf"), T("rumpf"), T("art"), T("stil")), ["erinnerung_einrichten"] = S(B("an"), B("wecken"), O("vorlauf", JsonValueKind.String, JsonValueKind.Number), O("termine", JsonValueKind.Array)),
        ["telefon_stand"] = S(), ["telefon_verbindung_stand"] = S(),
        ["telefon_ein"] = S(B("an")), ["telefon_verbindung_ein"] = S(B("an")),
        ["telefon_pairing_oeffnen"] = S(), ["telefon_verbinden"] = S(), ["telefon_pairing_abbrechen"] = S(),
        ["telefon_pairing_bestaetigen"] = S(B("ja"), O("attemptId", JsonValueKind.String), O("kennung", JsonValueKind.String)),
        ["telefon_paarung_bestaetigen"] = S(T("kennung"), B("ja")),
        ["telefon_entfernen"] = S(T("kennung")), ["telefon_status_anfordern"] = S(T("kennung"), T("requestId")), ["telefon_oeffnen"] = S(T("kennung")),
        ["telefon_freigabe"] = S(T("kennung"), T("name"), B("an")),
        ["telefon_freigaben"] = S(B("smsEmpfangen"), B("benachrichtigungen")),
        ["telefon_waehlen"] = S(T("nummer"), T("clientRef"), O("land", JsonValueKind.String), O("kennung", JsonValueKind.String)),
        ["telefon_annehmen"] = S(T("kennung"), T("callRef"), T("commandRef")),
        ["telefon_auflegen"] = S(T("kennung"), T("callRef"), T("commandRef"), N("revision")),
        ["telefon_bluetooth_schalten"] = S(O("kennung", JsonValueKind.String), O("an", JsonValueKind.True, JsonValueKind.False), O("adresse", JsonValueKind.String)),
        ["telefon_sms_benachrichtigen"] = S(T("name"), T("text"), T("nummer"), T("kennung"), T("foto"), T("stil"), N("dauer")),
        ["telefon_meldung_anzeigen"] = S(T("app"), T("titel"), T("text")),
        ["telefon_anruf_anzeigen"] = S(T("kennung"), T("callRef"), N("revision"), T("state"), T("name"), T("nummer"),
            T("foto"), T("stil"), N("dauer"), B("annehmen"), B("leiser")),
        ["telefon_anruf_lautstaerke_wiederherstellen"] = S(T("callRef")),
        ["personal_sync_einstellungen"] = S(T("kennung"), B("eigen"), B("autoWlan")),
        ["personal_sync_senden"] = S(T("kennung"), T("art"), J("inhalt")),
        ["personal_sync_lauf_senden"] = S(T("kennung"), J("request"), A("batches"), A("sources"), O("report", JsonValueKind.Object), O("commit", JsonValueKind.Object)),
        ["personal_sync_attachment_index"] = S(T("kennung"), T("runId"), B("reply"), T("recordsHash"), A("sources")),
        ["telefon_personal_sync_commit"] = S(T("kennung"), T("messageId"), T("token"), B("erfolgreich"), O("outcome", JsonValueKind.String)),
        ["kde_sms_senden"] = S(T("nummer"), T("text"), T("land"), T("clientRef"), T("device_id"), T("device_fingerprint")),
        ["kde_pairing_start"] = S(O("kennung", JsonValueKind.String), O("erneuern", JsonValueKind.True, JsonValueKind.False)),
        ["kde_pairing_complete"] = S(O("kennung", JsonValueKind.String), O("erneuern", JsonValueKind.True, JsonValueKind.False)),
        ["kde_paaren"] = S(O("kennung", JsonValueKind.String), O("erneuern", JsonValueKind.True, JsonValueKind.False)),
        ["kde_pairing_confirm"] = S(B("ja")), ["kde_paarung_bestaetigen"] = S(T("kennung"), B("ja")),
        ["kde_reconnect"] = S(), ["kde_entfernen"] = S(T("kennung"))
    };

    internal static JsonDocument Parse(string raw)
    {
        ValidateSize(raw.Length, 0);
        int bytes;
        try { bytes = StrictUtf8.GetByteCount(raw); }
        catch (EncoderFallbackException error) { throw new InvalidDataException("Bridge-Nachricht enthält ungültigen Text.", error); }
        ValidateSize(raw.Length, bytes);
        JsonDocument document;
        try { document = JsonDocument.Parse(raw, new JsonDocumentOptions { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow, MaxDepth = 64 }); }
        catch (JsonException error) { throw new InvalidDataException("Bridge-Nachricht ist kein gültiges JSON.", error); }
        try
        {
            RejectDuplicates(document.RootElement);
            if (document.RootElement.ValueKind != JsonValueKind.Object || !document.RootElement.TryGetProperty("cmd", out var commandNode) || commandNode.ValueKind != JsonValueKind.String) throw new InvalidDataException("Bridge-Envelope ungültig.");
            var command = commandNode.GetString() ?? "";
            if (!Schemas.TryGetValue(command, out var schema)) throw new InvalidDataException("Unbekannter Bridge-Befehl.");
            ValidateSchema(document.RootElement, schema);
            return document;
        }
        catch { document.Dispose(); throw; }
    }

    internal static void ValidateSize(int characters, int utf8Bytes)
    {
        if (characters < 0 || utf8Bytes < 0 || characters > MaximumCharacters || utf8Bytes > MaximumUtf8Bytes) throw new InvalidDataException("Bridge-Nachricht ist zu groß.");
    }

    private static void ValidateSchema(JsonElement value, Schema schema)
    {
        var allowed = schema.Fields.ToDictionary(item => item.Name, StringComparer.Ordinal); allowed["cmd"] = new Field("cmd", true, [JsonValueKind.String]);
        foreach (var property in value.EnumerateObject())
        {
            if (!allowed.TryGetValue(property.Name, out var field) || !field.Kinds.Contains(property.Value.ValueKind)) throw new InvalidDataException("Bridge-Feld ungültig.");
        }
        foreach (var field in allowed.Values) if (field.Required && !value.TryGetProperty(field.Name, out _)) throw new InvalidDataException("Bridge-Feld fehlt.");
    }

    private static void RejectDuplicates(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject()) { if (!names.Add(property.Name)) throw new InvalidDataException("Doppeltes Bridge-Feld."); RejectDuplicates(property.Value); }
        }
        else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) RejectDuplicates(item);
    }

    private static Schema S(params Field[] fields) => new(fields);
    private static Field T(string name) => new(name, true, [JsonValueKind.String]);
    private static Field B(string name) => new(name, true, [JsonValueKind.True, JsonValueKind.False]);
    private static Field N(string name) => new(name, true, [JsonValueKind.Number]);
    private static Field J(string name) => new(name, true, [JsonValueKind.Object]);
    private static Field A(string name) => new(name, true, [JsonValueKind.Array]);
    private static Field O(string name, params JsonValueKind[] kinds) => new(name, false, kinds);
    private sealed record Schema(Field[] Fields);
    private sealed record Field(string Name, bool Required, JsonValueKind[] Kinds);
}
