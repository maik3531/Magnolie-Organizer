package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Draft-only body validation. No product message kind, consent or durable state. */
internal object DesktopScreenDraftControl {
    const val DRAFT = "desktop-screen-control/1"
    private val common = setOf("draft", "op", "request", "mode", "setup_until_ms")
    private val hex = Regex("[0-9a-f]+")
    private val positive = Regex("[1-9][0-9]*")

    enum class Role { PHONE, DESKTOP }

    fun validate(body: JsonObject, sender: Role): JsonObject {
        fun text(name: String): String {
            val field = body[name] as? JsonPrimitive ?: error("desktop_screen_control_invalid")
            require(field.isString)
            return field.content
        }
        fun number(name: String, range: LongRange): Long {
            val field = body[name] as? JsonPrimitive ?: error("desktop_screen_control_invalid")
            require(!field.isString && field.content.length <= 16 && positive.matches(field.content))
            val value = requireNotNull(field.content.toLongOrNull())
            require(value in range)
            return value
        }
        fun identity(name: String, length: Int) {
            val field = text(name)
            require(field.length == length && hex.matches(field))
        }

        val op = text("op")
        val extra = when (op) {
            "request" -> { require(sender == Role.PHONE); emptySet() }
            "offer" -> { require(sender == Role.DESKTOP); setOf("session", "secret", "port", "width", "height") }
            "prepared" -> { require(sender == Role.PHONE); setOf("session", "transcript") }
            "send" -> { require(sender == Role.DESKTOP); setOf("session", "transcript") }
            "stop" -> setOf("session")
            else -> throw IllegalArgumentException("desktop_screen_control_invalid")
        }
        require(body.keys == common + extra && text("draft") == DRAFT)
        identity("request", 32)
        number("mode", 1L..2L)
        number("setup_until_ms", 1L..9_007_199_254_740_991L)
        if ("session" in extra) identity("session", 32)
        if ("transcript" in extra) identity("transcript", 64)
        if (op == "offer") {
            identity("secret", 64)
            number("port", 1024L..65535L)
            val width = number("width", 16L..1920L)
            val height = number("height", 16L..1920L)
            require(width * height <= 1920 * 1080)
        }
        return body
    }
}
