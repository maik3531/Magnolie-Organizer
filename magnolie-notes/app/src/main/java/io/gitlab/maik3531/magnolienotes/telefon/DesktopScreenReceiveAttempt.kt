package io.gitlab.maik3531.magnolienotes.telefon

import androidx.activity.ComponentActivity
import java.nio.channels.SocketChannel

/** Native composition for one private draft offer. No dispatch registration,
 * address parsing or Activity launch. Hold this object until both sides drain. */
internal class DesktopScreenReceiveAttempt(
    activity: ComponentActivity,
    peerName: String,
    parent: Any,
    session: ByteArray,
    secret: ByteArray,
    mode: Int,
    width: Int,
    height: Int,
    deadline: Long,
    requireOriginalParent: () -> Unit,
    openOriginal: (() -> Unit) -> SocketChannel,
    writePrepared: (ByteArray, () -> Unit) -> Unit,
) : AutoCloseable {
    private val receiver: DesktopScreenReceiveRun
    private val viewer = DesktopScreenViewer(activity, peerName, mode, width, height, deadline, requireOriginalParent,
        { startReceiver() }, { stopReceiver() })

    init {
        receiver = DesktopScreenReceiveRun(parent, session, secret, mode, width, height, deadline,
            viewer::requireViewing, openOriginal, writePrepared, viewer::offer, viewer::close)
    }

    fun show() = viewer.show()

    /** Only the native authenticated controller can supply this receipt. */
    fun acceptSend(actualParent: Any, transcript: ByteArray): Boolean = receiver.acceptSend(actualParent, transcript)

    private fun startReceiver() = receiver.start()
    private fun stopReceiver() = receiver.close()

    override fun close() {
        receiver.close()
        viewer.close()
    }

    val drained: Boolean get() = receiver.drained && viewer.uiDrained
}
