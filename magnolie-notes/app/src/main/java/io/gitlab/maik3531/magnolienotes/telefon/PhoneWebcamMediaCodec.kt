package io.gitlab.maik3531.magnolienotes.telefon

import java.nio.ByteBuffer
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Binary AV sender codec, NOT camera permission, a socket or a capture service.
 * The future native host must supply a fresh secret/session received through the
 * original authenticated control channel after genuine current OS consent.
 * Never recreate this codec with the same secret/session on reconnect.
 */
internal class PhoneWebcamMediaCodec(session: String, secret: ByteArray, private val current: () -> Unit) : AutoCloseable {
    private val identity: ByteArray
    private val key: SecretKeySpec
    private val prefix: ByteArray
    private var sequence = 0L
    private var retired = false

    init {
        require(Regex("[0-9a-f]{32}").matches(session) && secret.size == 32) { "webcam_channel_context_invalid" }
        current()
        identity = ByteArray(16) { session.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
        val material = derive(identity, secret)
        key = SecretKeySpec(material.copyOfRange(0, 32), "AES")
        prefix = material.copyOfRange(32, 36)
        material.fill(0)
    }

    @Synchronized
    fun encode(video: Boolean, packetSequence: Long, ptsUs: Long, data: ByteArray): ByteArray {
        try {
            check(!retired) { "webcam_channel_retired" }
            current()
            require(sequence < Long.MAX_VALUE && packetSequence >= 0 && ptsUs in 0..9_007_199_254_740_991L &&
                data.size == if (video) VIDEO_BYTES else AUDIO_BYTES) { "webcam_packet_invalid" }
            val plain = ByteBuffer.allocate(PACKET_BYTES + data.size)
                .put(1).put(if (video) 1.toByte() else 2.toByte()).putLong(packetSequence).putLong(ptsUs).put(data).array()
            try {
                val header = ByteBuffer.allocate(12).putInt(plain.size + 16).putLong(sequence).array()
                val nonce = ByteBuffer.allocate(12).put(prefix).putLong(sequence).array()
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(128, nonce))
                cipher.updateAAD(PROTOCOL + identity + header)
                val encrypted = cipher.doFinal(plain)
                current()
                sequence++
                return header + encrypted
            } finally { plain.fill(0) }
        } catch (error: Throwable) {
            retired = true
            throw error
        }
    }

    @Synchronized
    override fun close() { retired = true }

    companion object {
        const val WIDTH = 640
        const val HEIGHT = 480
        const val FPS = 15
        const val VIDEO_BYTES = WIDTH * HEIGHT * 3 / 2
        const val AUDIO_BYTES = 960 * 2
        private const val PACKET_BYTES = 18
        private val PROTOCOL = "magnolie-phone-webcam/1\u0000phone_to_desktop\u0000".toByteArray(Charsets.US_ASCII)

        private fun derive(salt: ByteArray, secret: ByteArray): ByteArray {
            // RFC 5869 HKDF-SHA256, same domain separation as the desktop.
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(salt, "HmacSHA256"))
            val prk = mac.doFinal(secret)
            var previous = byteArrayOf()
            val result = ByteArray(36)
            try {
                for (block in 1..2) {
                    mac.init(SecretKeySpec(prk, "HmacSHA256"))
                    mac.update(previous); mac.update(PROTOCOL); mac.update(block.toByte())
                    val next = mac.doFinal()
                    previous.fill(0); previous = next
                    val offset = (block - 1) * 32
                    next.copyInto(result, offset, 0, minOf(32, result.size - offset))
                }
                return result
            } finally { prk.fill(0); previous.fill(0) }
        }
    }
}
