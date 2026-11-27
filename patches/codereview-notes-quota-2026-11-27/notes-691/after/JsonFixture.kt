
package kotlinx.serialization.json
open class JsonElement
data class JsonPrimitive(val value: Any): JsonElement()
class JsonObject(val values: Map<String, JsonElement> = emptyMap()): JsonElement() {
    operator fun get(key: String) = values[key]
}
val JsonElement.jsonObject: JsonObject get() = this as JsonObject
