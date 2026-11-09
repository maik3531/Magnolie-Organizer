package io.gitlab.maik3531.magnolietabletbeta

/** Stable identity bytes match Python json.dumps(ensure_ascii=False,
 * sort_keys=True,separators=(',',':')). Platform JSON quoting is not an identity
 * contract: Android escapes '/', JSON-java also escapes some Unicode ranges. */
internal object CalendarIdentity {
    fun quote(value: String): String = buildString {
        append('"');var i=0
        while(i<value.length) {
            val c=value[i++];val n=c.code
            when(c) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\b' -> append("\\b")
                '\u000c' -> append("\\f")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> when {
                    n<32 -> {append("\\u00");append("0123456789abcdef"[n ushr 4]);append("0123456789abcdef"[n and 15])}
                    n in 0xd800..0xdbff -> {
                        require(i<value.length && value[i].code in 0xdc00..0xdfff) {"Invalid calendar identity Unicode"}
                        append(c);append(value[i++])
                    }
                    n in 0xdc00..0xdfff -> throw IllegalArgumentException("Invalid calendar identity Unicode")
                    else -> append(c)
                }
            }
        }
        append('"')
    }
    // Evidence only: Android JSONObject.quote historically escapes every slash.
    // The current canonical quote/recurrenceKey algorithms remain unchanged.
    fun legacyAndroidQuote(value: String): String = quote(value).replace("/", "\\/")
    fun legacyAndroidRecurrenceKey(parameters: Map<String,String>,value: String): String {
        require(parameters.keys.all {it.matches(Regex("[A-Za-z0-9-]+"))})
        val fields=parameters.keys.sorted().joinToString(",","{","}") {legacyAndroidQuote(it)+":"+legacyAndroidQuote(parameters.getValue(it))}
        return "["+fields+","+legacyAndroidQuote(value)+"]"
    }
    fun recurrenceKey(parameters: Map<String,String>,value: String): String {
        // RFC property parameter names are ASCII tokens, normalized by the parser.
        require(parameters.keys.all {it.matches(Regex("[A-Za-z0-9-]+"))})
        val fields=parameters.keys.sorted().joinToString(",","{","}") {quote(it)+":"+quote(parameters.getValue(it))}
        return "["+fields+","+quote(value)+"]"
    }
}
