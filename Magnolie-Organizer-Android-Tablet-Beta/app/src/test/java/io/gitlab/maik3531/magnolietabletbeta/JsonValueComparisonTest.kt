package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.math.BigDecimal
import java.math.BigInteger
import java.util.concurrent.atomic.AtomicInteger

class JsonValueComparisonTest {
    private fun same(left: Any?, right: Any?) {
        assertTrue(jsonValuesEqual(left, right))
        assertTrue(jsonValuesEqual(right, left))
    }
    private fun different(left: Any?, right: Any?) {
        assertFalse(jsonValuesEqual(left, right))
        assertFalse(jsonValuesEqual(right, left))
    }

    @Test fun objectKeyOrderDoesNotChangeNestedValues() {
        // These colliding keys retain different traversal orders in the JVM JSON map.
        val left = JSONObject().put("Aa", JSONArray().put(1).put(JSONObject.NULL))
            .put("BB", JSONObject().put("text", "value").put("flag", true))
        val right = JSONObject().put("BB", JSONObject().put("flag", true).put("text", "value"))
            .put("Aa", JSONArray().put(1L).put(JSONObject.NULL))
        assertNotEquals(left.keys().asSequence().toList(), right.keys().asSequence().toList())
        same(left, right)
        same(JSONObject(), JSONObject())
    }

    @Test fun missingExtraAndRenamedKeysNeverMatch() {
        different(JSONObject().put("one", 1), JSONObject())
        different(JSONObject().put("one", 1), JSONObject().put("one", 1).put("two", 2))
        different(JSONObject().put("one", 1), JSONObject().put("two", 1))
        different(JSONObject().put("one", JSONObject().put("nested", true)),
            JSONObject().put("one", JSONObject()))
    }

    @Test fun explicitNullDoesNotMatchAnAbsentMember() {
        val withNull = JSONObject().put("value", JSONObject.NULL)
        same(withNull, JSONObject().put("value", JSONObject.NULL))
        different(withNull, JSONObject())
        different(withNull, JSONObject().put("value", "null"))
        same(JSONObject.NULL, JSONObject.NULL)
        different(JSONObject.NULL, null)
        same(null, null)
    }

    @Test fun arrayLengthOrderAndNestedValuesAreSignificant() {
        same(JSONArray(), JSONArray())
        same(JSONArray().put(1).put("two").put(JSONObject.NULL), JSONArray().put(1L).put("two").put(JSONObject.NULL))
        different(JSONArray().put(1).put(2), JSONArray().put(2).put(1))
        different(JSONArray().put(1), JSONArray().put(1).put(JSONObject.NULL))
        different(JSONArray().put(JSONObject().put("v", true)), JSONArray().put(JSONObject().put("v", false)))
        different(JSONArray().put(JSONArray().put(1)), JSONArray().put(JSONArray().put(2)))
    }

    @Test fun distinctJsonKindsAndPrimitiveValuesNeverCoerce() {
        different("1", 1)
        different(true, 1)
        different("true", true)
        different("text", "Text")
        different(true, false)
        different(JSONObject(), JSONArray())
        different(JSONObject().put("0", "value"), JSONArray().put("value"))
        different(JSONObject.NULL, "null")
        same("value", "value")
        same(false, false)
    }

    @Test fun integralWrappersAndDecimalScaleKeepTheSameExactValue() {
        for (number in listOf<Number>(1.toByte(), 1.toShort(), 1, 1L, BigInteger.ONE,
            BigDecimal("1.0000"), 1.0f, 1.0)) same(1, number)
        same(BigDecimal("1E+40"), BigInteger("10000000000000000000000000000000000000000"))
        same(Long.MIN_VALUE, BigInteger("-9223372036854775808"))
        same(-0.0, 0)
    }

    @Test fun opaqueTwoTo63NeverMatchesSaturatedLongMaximum() {
        val beyondLong = BigInteger("9223372036854775808")
        different(beyondLong, Long.MAX_VALUE)
        different(9223372036854775808.0, Long.MAX_VALUE)
        same(beyondLong, 9223372036854775808.0)
        val expected = JSONObject("""{"futureNumber":9223372036854775808}""")
        val clamped = JSONObject("""{"futureNumber":9223372036854775807}""")
        different(expected, clamped)
        different(JSONArray().put(expected), JSONArray().put(clamped))
    }

    @Test fun adjacentIntegersBeyondDoublePrecisionRemainDistinct() {
        different(9007199254740992L, 9007199254740993L)
        different(9007199254740992.0, 9007199254740993L)
        same(9007199254740992.0, BigInteger("9007199254740992"))
        different(BigInteger("10000000000000000000000000000000000000001"), BigDecimal("1E+40"))
    }

    @Test fun arbitraryPrecisionDecimalsNeverRoundThroughDouble() {
        different(BigDecimal("0.10000000000000000000001"), BigDecimal("0.1"))
        different(BigDecimal("1E-4000"), BigDecimal.ZERO)
        same(BigDecimal("0.1000000000000000000000100"), BigDecimal("0.10000000000000000000001"))
    }

    @Test fun binaryFloatingValuesAreComparedExactlyWithoutDecimalStringRounding() {
        different(0.1, BigDecimal("0.1"))
        different(0.1f, 0.1)
        same(0.1, BigDecimal("0.1000000000000000055511151231257827021181583404541015625"))
        same(0.1f, BigDecimal("0.100000001490116119384765625"))
        same(0.5, BigDecimal("0.5"))
        different(Double.MIN_VALUE, BigDecimal.ZERO)
        different(Float.MIN_VALUE, BigDecimal.ZERO)
        different(Double.MAX_VALUE, BigDecimal("1E+309"))
    }

    @Test fun nonFiniteNumbersAreNotValidMatchingJsonValues() {
        for (number in listOf<Number>(Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY,
            Float.NaN, Float.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY)) {
            different(number, number)
            different(number, 0)
        }
    }

    @Test fun unsupportedValuesDoNotBecomeEqualByIdentityOrStringification() {
        val unsupported = AtomicInteger(1)
        different(unsupported, unsupported)
        different(unsupported, 1)
        val text = StringBuilder("value")
        different(text, text)
        different(text, "value")
    }
}
