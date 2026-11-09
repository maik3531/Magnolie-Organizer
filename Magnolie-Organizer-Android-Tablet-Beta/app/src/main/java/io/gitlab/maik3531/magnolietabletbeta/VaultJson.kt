package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.util.IdentityHashMap

/** Bounded storage encoding of the parsed JSON model, without AOSP numberToString narrowing. */
internal object VaultJson {
    fun encode(value: JSONObject, maximumBytes: Int): String {
        require(maximumBytes in 1..MAX_BYTES)
        val output=StringBuilder()
        var bytes=0; var nodes=0
        val ancestors=IdentityHashMap<Any,Boolean>()
        fun append(text: String, size: Int=text.length) {
            require(size<=maximumBytes-bytes) {"JSON output exceeds storage limit"}
            bytes+=size; output.append(text)
        }
        fun quoted(text: String) {
            append("\"");var i=0
            while(i<text.length) {
                val c=text[i++]
                when(c) {
                    '"' -> append("\\\"")
                    '\\' -> append("\\\\")
                    '/' -> append("\\/")
                    '\b' -> append("\\b")
                    '\u000c' -> append("\\f")
                    '\n' -> append("\\n")
                    '\r' -> append("\\r")
                    '\t' -> append("\\t")
                    else -> when {
                        c.code<32 -> append("\\u"+c.code.toString(16).padStart(4,'0'))
                        c.code in 0xd800..0xdbff -> {
                            require(i<text.length && text[i].code in 0xdc00..0xdfff) {"Invalid Unicode scalar"}
                            append(""+c+text[i++],4)
                        }
                        c.code in 0xdc00..0xdfff -> error("Invalid Unicode scalar")
                        else -> append(c.toString(),if(c.code<128) 1 else if(c.code<2048) 2 else 3)
                    }
                }
            }
            append("\"")
        }
        fun number(value: Number): String = when(value) {
            is Byte,is Short,is Int,is Long -> value.toString()
            is Double,is Float -> {
                val n=value.toDouble();require(n.isFinite()) {"Nonfinite JSON number"}
                // An integral Double above Long.MAX_VALUE must never use a saturated Long cast.
                // Retain floating representation as well as its exact integral value.
                if(n!=0.0 && n%1.0==0.0) java.math.BigDecimal(n).toPlainString()+".0" else n.toString()
            }
            is java.math.BigInteger,is java.math.BigDecimal -> value.toString()
            else -> error("Unsupported JSON number type")
        }
        fun write(item: Any?,depth: Int) {
            require(depth<64 && ++nodes<=2_000_000) {"JSON structure exceeds storage limit"}
            when(item) {
                null,JSONObject.NULL -> append("null")
                is String -> quoted(item)
                is Boolean -> append(if(item) "true" else "false")
                is Number -> append(number(item))
                is JSONObject,is JSONArray -> {
                    require(ancestors.put(item,true)==null) {"Cyclic JSON value"}
                    try {
                        if(item is JSONObject) {
                            append("{");var first=true
                            for(key in item.keys().asSequence()) {
                                require(++nodes<=2_000_000)
                                if(!first) append(",");first=false;quoted(key);append(":");write(item.get(key),depth+1)
                            }
                            append("}")
                        } else {
                            item as JSONArray;append("[")
                            for(i in 0 until item.length()) {if(i>0) append(",");write(item.opt(i),depth+1)}
                            append("]")
                        }
                    } finally {ancestors.remove(item)}
                }
                else -> error("Unsupported JSON value")
            }
        }
        write(value,0)
        return output.toString()
    }
}
