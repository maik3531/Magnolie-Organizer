package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigDecimal
import java.math.BigInteger

/** Test-only structural comparison using the JSON API available on Android (#805).
 *
 * Object key order and Java number wrappers are immaterial; JSON kinds, complete key
 * sets, array order and exact number values are not. No serializer is used as an oracle.
 * JSON null is distinct from an absent member (and from a raw Java null argument).
 * Inputs are JSON trees; unsupported values, including non-finite numbers, never match.
 */
internal fun jsonValuesEqual(expected: Any?, actual: Any?): Boolean {
    if (expected === JSONObject.NULL || actual === JSONObject.NULL) return expected === actual
    if (expected == null || actual == null) return expected === actual
    return when (expected) {
        is JSONObject -> {
            if (actual !is JSONObject) false
            else {
                val expectedKeys = expected.keys().asSequence().toSet()
                val actualKeys = actual.keys().asSequence().toSet()
                expectedKeys == actualKeys && expectedKeys.all { key ->
                    actual.has(key) && jsonValuesEqual(expected.get(key), actual.get(key))
                }
            }
        }
        is JSONArray -> actual is JSONArray && expected.length() == actual.length() &&
            (0 until expected.length()).all { jsonValuesEqual(expected.get(it), actual.get(it)) }
        is Number -> {
            if (actual !is Number) false
            else {
                val left = exactJsonNumber(expected)
                val right = exactJsonNumber(actual)
                left != null && right != null && left.compareTo(right) == 0
            }
        }
        is String -> actual is String && expected == actual
        is Boolean -> actual is Boolean && expected == actual
        else -> false
    }
}

private fun exactJsonNumber(value: Number): BigDecimal? = when (value) {
    is BigDecimal -> value
    is BigInteger -> BigDecimal(value)
    is Byte, is Short, is Int, is Long -> BigDecimal.valueOf(value.toLong())
    // The constructor retains the exact binary value. valueOf/toString would round
    // it to a decimal spelling and could hide the opaque-number loss fixed in #466.
    is Double -> if (value.isFinite()) BigDecimal(value) else null
    is Float -> if (value.isFinite()) BigDecimal(value.toDouble()) else null
    else -> null
}
