package io.gitlab.maik3531.magnolienotes.telefon

/** A single latest JPEG between the original encoder and its SEND worker.
 * Ownership moves only on a successful offer or take. Consumer must clear the
 * taken bytes on every outcome and check current transport authority again
 * before *each* write. No IO, waiting, or callbacks while the slot is locked. */
internal class PhoneScreenFrameSlot(private val width: Int, private val height: Int) : AutoCloseable {
    private val gate = Any()
    private var pending: PhoneScreenJpegOutput.Frame? = null
    private var lastTimestamp = -1L
    private var terminal = false

    init { require(width in 2..1920 && height in 2..1920 && width * height <= 1920 * 1080) }

    fun matchesSize(width: Int, height: Int) = this.width == width && this.height == height

    /** The producer supplies a fresh owned byte array and never reuses it. */
    fun offer(frame: PhoneScreenJpegOutput.Frame): Boolean {
        if (frame.width != width || frame.height != height || frame.timestampNanos < 0 ||
            frame.jpeg.size !in 1..PhoneScreenJpegOutput.MAX_FRAME_BYTES) return false
        val old = synchronized(gate) {
            if (terminal || frame.timestampNanos <= lastTimestamp || pending?.jpeg === frame.jpeg) return false
            lastTimestamp = frame.timestampNanos
            pending.also { pending = frame }
        }
        old?.jpeg?.fill(0)
        return true
    }

    fun take(): PhoneScreenJpegOutput.Frame? = synchronized(gate) {
        if (terminal) null else pending.also { pending = null }
    }

    fun requireOpen() = synchronized(gate) { check(!terminal) { "screen_frame_slot_closed" } }

    override fun close() {
        val discarded = synchronized(gate) {
            terminal = true
            pending.also { pending = null }
        }
        discarded?.jpeg?.fill(0)
    }
}
