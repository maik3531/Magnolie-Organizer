package io.gitlab.maik3531.magnolienotes.baum
data class Sendung(
    val id: String,
    val transportId: String,
    val an: String,
    val art: String,
    val inhalt: String,
    val versuche: Int = 0,
    val naechsterVersuch: Long = 0L,
    val angelegt: Long = 0L,
    val aufgegeben: Boolean = false,
    val syncEpoch: String = "",
    val protokoll: String = "",
    val baum1Umschlag: String = "",
    val receiptProtocol: Int = 0,
    val receiptAttempted: Boolean = false,
    val unsicher: Boolean = false,
    val kontaktV3Probe: Boolean = false,
    val kontaktV4Probe: Boolean = false
) {
    val brauchtPruefung: Boolean get() = unsicher || receiptAttempted ||
        (baum1Umschlag.isNotEmpty() && receiptProtocol != 1)
}
