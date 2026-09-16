package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Partner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject

/**
 * Stellt eine einzelne Nachricht zu. `baum-fs1` ist der Regelweg; nur wenn ein
 * Partner über den kurzen Codeweg kam, geht es über `baum-1`.
 */
object Versand {

    /** Ergebnis eines Zustellversuchs; `zaehler` gilt nur für `baum-1`. */
    data class Ergebnis(val gelungen: Boolean, val zaehler: Long = 0L, val grund: String = "", val unsicher: Boolean = false)

    fun zustellen(
        eigen: EigeneIdentitaet,
        partner: Partner,
        art: String,
        inhalt: JsonObject,
        transportId: String,
        transport: Transport,
        legacyUmschlag: JsonObject? = null
    ): Ergebnis {
        if (!partner.bestaetigt) return Ergebnis(false, grund = "Der Zweig ist nicht bestätigt.")
        if (legacyUmschlag != null) return legacyZustellen(eigen, partner, legacyUmschlag, transport)
        val vollstaendig = buildJsonObject {
            inhalt.forEach { (name, wert) -> put(name, wert) }
            put("art", kotlinx.serialization.json.JsonPrimitive(art))
        }
        return if (partner.protokoll == "baum-1") {
            alterWeg(eigen, partner, vollstaendig, transport)
        } else {
            sichererWeg(eigen, partner, vollstaendig, transportId, transport)
        }
    }

    private fun sichererWeg(
        eigen: EigeneIdentitaet,
        partner: Partner,
        inhalt: JsonObject,
        transportId: String,
        transport: Transport
    ): Ergebnis {
        var sitzung: Sitzung.Offen? = null
        return try {
            val start = Sitzung.baueStart(eigen, partner.kennung, partner.oeffentlich)
            val antwort = transport.anfrage("/magnolie/v2/sitzung", start.nachricht)
            val offen = Sitzung.oeffneAntwort(
                eigen, partner.kennung, partner.oeffentlich, start, antwort
            )
            sitzung = offen
            val kennung = if (gueltigeTransportId(transportId)) transportId else {
                Krypto.b64(Krypto.zufallsbytes(16))
            }
            val umschlag = Sitzung.baueUmschlag(
                offen, eigen.kennung, partner.kennung, inhalt, kennung
            )
            val quittung = transport.anfrage("/magnolie/v2/nachricht", umschlag)
            if (!Sitzung.pruefeQuittung(offen, umschlag, quittung)) {
                Ergebnis(false, grund = "Die Gegenstelle hat den Empfang nicht bestätigt.")
            } else {
                Ergebnis(true)
            }
        } catch (fehler: Exception) {
            Ergebnis(false, grund = fehler.message ?: "Nicht erreichbar.")
        } finally {
            sitzung?.loeschen()
        }
    }

    private fun alterWeg(
        eigen: EigeneIdentitaet,
        partner: Partner,
        inhalt: JsonObject,
        transport: Transport
    ): Ergebnis = try {
        val zaehler = partner.zaehlerRaus + 1
        val umschlag = Baum1.baue(eigen, partner.kennung, partner.oeffentlich, inhalt, zaehler)
        legacyZustellen(eigen, partner, umschlag, transport)
    } catch (fehler: Exception) {
        Ergebnis(false, grund = fehler.message ?: "Nicht erreichbar.")
    }

    private fun legacyZustellen(eigen: EigeneIdentitaet, partner: Partner, umschlag: JsonObject, transport: Transport): Ergebnis {
        var key: ByteArray? = null
        return try {
            require(text(umschlag, "von") == eigen.kennung)
            key = Krypto.partnerschluessel(eigen.geheim, partner.oeffentlich, eigen.kennung, partner.kennung)
            val receipt = transport.anfrage("/magnolie/v1/nachricht", umschlag)
            if (!Baum1Quittung.pruefen(key, eigen.kennung, partner.kennung, umschlag, receipt))
                Ergebnis(false, grund = "Die Gegenstelle hat den Empfang nicht bestätigt.", unsicher = true)
            else Ergebnis(true, zahl(umschlag, "zaehler") ?: 0)
        } catch (error: KeineVerbindung) {
            Ergebnis(false, grund = error.cause?.message ?: "Nicht erreichbar.")
        } catch (error: Exception) {
            Ergebnis(false, grund = error.message ?: "Die Gegenstelle hat den Empfang nicht bestätigt.", unsicher = true)
        } finally { key?.fill(0) }
    }

    private fun gueltigeTransportId(text: String): Boolean = try {
        Krypto.b64Lesen(text, 16)
        true
    } catch (fehler: BaumFehler) {
        false
    }

    /**
     * Der Weg zu einem Partner: bevorzugt WLAN, sonst Bluetooth. Ist keiner
     * bekannt, bleibt die Sendung im Postfach.
     */
    fun wegeZu(partner: Partner, bluetoothErlaubt: Boolean): List<Transport> = buildList {
        val wlan = linkedSetOf<Pair<String, Int>>()
        if (partner.adresse.isNotBlank()) wlan += partner.adresse.trim() to partner.port
        if (partner.fernAdresse.isNotBlank()) wlan += partner.fernAdresse.trim() to partner.fernPort
        wlan.forEach { (host, port) -> add(WlanTransport(host, port)) }
        if (bluetoothErlaubt && partner.bluetooth.isNotBlank()) {
            add(BluetoothTransport(partner.bluetooth))
        }
    }

    fun wegZu(partner: Partner, bluetoothErlaubt: Boolean): Transport? =
        wegeZu(partner, bluetoothErlaubt).firstOrNull()

    /**
     * Der Paarungsweg über die Datei: Anfrage stellen, Antwort prüfen.
     * Liefert den Einlader als bestätigten Partner.
     */
    data class Paarungsweg(
        val transport: Transport,
        val bluetooth: String = ""
    )

    internal fun fragePaarung(
        wege: List<Paarungsweg>,
        anfrage: JsonObject
    ): Pair<JsonObject, Paarungsweg> {
        var letzterFehler: Exception? = null
        for (weg in wege) {
            try {
                return weg.transport.anfrage("/magnolie/v2/paarung", anfrage) to weg
            } catch (fehler: Exception) {
                letzterFehler = fehler
            } finally {
                weg.transport.schliessen()
            }
        }
        throw (letzterFehler ?: BaumFehler("Die Gegenstelle ist nicht erreichbar."))
    }

    fun paareMitDatei(
        dokument: JsonObject,
        eigen: EigeneIdentitaet,
        zusaetzlicheWege: List<Paarungsweg> = emptyList()
    ): Partner {
        Paarung.pruefe(dokument, System.currentTimeMillis() / 1000)
        val ziel = dokument["ziel"]?.jsonObject ?: throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        val einlader = dokument["einlader"]?.jsonObject
            ?: throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        val adresse = text(ziel, "adresse")
        val zielPort = zahl(ziel, "port")?.toInt() ?: Netz.PORT
        val anfrage = Paarung.anfrage(dokument, eigen)
        val wege = listOf(Paarungsweg(WlanTransport(adresse, zielPort))) + zusaetzlicheWege
        val (empfangen, erfolgreicherWeg) = fragePaarung(wege, anfrage)
        Paarung.pruefeAntwort(dokument, anfrage, empfangen)
        Paarung.pruefe(dokument, System.currentTimeMillis() / 1000)
        return Partner(
            kennung = text(einlader, "kennung"),
            name = text(einlader, "name"),
            oeffentlich = text(einlader, "oeffentlich"),
            adresse = adresse,
            port = zahl(einlader, "port")?.toInt() ?: Netz.PORT,
            bluetooth = erfolgreicherWeg.bluetooth,
            bestaetigt = true,
            vertraut = true,
            wartet = false,
            protokoll = "baum-fs1"
        )
    }

    /**
     * Der kurze Codeweg von dieser Seite aus: Identität schicken, Identität
     * empfangen, Code anzeigen. Bestätigt wird erst nach dem Vergleich.
     */
    fun frageAn(adresse: String, port: Int, eigen: EigeneIdentitaet): Pair<Partner, String> {
        val anfrage = buildJsonObject {
            put("name", kotlinx.serialization.json.JsonPrimitive(eigen.name))
            put("kennung", kotlinx.serialization.json.JsonPrimitive(eigen.kennung))
            put("oeffentlich", kotlinx.serialization.json.JsonPrimitive(eigen.oeffentlich))
            put("port", kotlinx.serialization.json.JsonPrimitive(eigen.port))
        }
        val antwort = WlanTransport(adresse, port).anfrage("/magnolie/v1/paarung", anfrage)
        val oeffentlich = text(antwort, "oeffentlich")
        if (!Paarung.schluesselGueltig(oeffentlich)) {
            throw BaumFehler("Der andere Zweig hat keinen gültigen Schlüssel geschickt.")
        }
        val code = Krypto.paarungsCode(eigen.oeffentlich, oeffentlich)
        val partner = Partner(
            kennung = text(antwort, "kennung"),
            name = text(antwort, "name"),
            oeffentlich = oeffentlich,
            adresse = adresse,
            port = zahl(antwort, "port")?.toInt() ?: port,
            bestaetigt = false,
            vertraut = false,
            wartet = true,
            code = code,
            protokoll = "baum-1"
        )
        return partner to code
    }
}
