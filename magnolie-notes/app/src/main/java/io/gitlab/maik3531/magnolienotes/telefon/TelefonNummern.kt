package io.gitlab.maik3531.magnolienotes.telefon

import android.telephony.TelephonyManager
import com.google.i18n.phonenumbers.PhoneNumberUtil

internal object TelefonNummern {
    private val util by lazy(PhoneNumberUtil::getInstance)

    fun land(manager: TelephonyManager?): String? {
        val sim = runCatching { manager?.simCountryIso }.getOrNull().gueltigesLand()
        if (sim != null) return sim
        val roaming = runCatching { manager?.isNetworkRoaming ?: true }.getOrDefault(true)
        return if (roaming) null else runCatching { manager?.networkCountryIso }.getOrNull().gueltigesLand()
    }

    fun land(simLand: String?, netzLand: String?, roaming: Boolean): String? =
        simLand.gueltigesLand() ?: if (roaming) null else netzLand.gueltigesLand()

    fun land(gebundeneSim: String?, aktiveSims: List<String>, netzLand: String?, roaming: Boolean): String? {
        gebundeneSim.gueltigesLand()?.let { return it }
        val laender = aktiveSims.mapNotNull { it.gueltigesLand() }.distinct()
        return when (laender.size) {
            1 -> laender.single()
            0 -> if (roaming) null else netzLand.gueltigesLand()
            else -> null
        }
    }

    fun e164(number: String, country: String?): String {
        val raw = number.trim()
        if (raw.isEmpty() || raw.length > 128) return ""
        val region = country.gueltigesLand() ?: "ZZ"
        return runCatching {
            val parsed = util.parse(raw, region)
            if (util.isValidNumber(parsed)) util.format(parsed, PhoneNumberUtil.PhoneNumberFormat.E164) else ""
        }.getOrDefault("")
    }

    fun status(shared: Boolean, enabled: Boolean, permitted: Boolean, raw: String,
               normalized: String, legacyIncoming: Boolean): String = when {
        !shared -> "not_shared"
        !enabled || !permitted -> "permission_missing"
        normalized.isNotEmpty() -> "available"
        raw.isNotBlank() -> "unavailable"
        legacyIncoming -> "withheld"
        else -> "unavailable"
    }

    private fun String?.gueltigesLand(): String? = this?.trim()?.uppercase()
        ?.takeIf { it.length == 2 && it.all(Char::isLetter) && it in util.supportedRegions }
}
