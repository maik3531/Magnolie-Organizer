package io.gitlab.maik3531.magnolienotes.telefon

import android.annotation.SuppressLint
import android.app.Service
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.ImageReader
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import android.util.Size
import androidx.annotation.RequiresApi
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Actual platform capture, entered ONLY after a genuine Activity permission
 * result and native camera/microphone foreground service. No discovery, saved
 * autostart, notification bypass, preview UI, file recording or silent audio-only
 * fallback. The consumer must synchronously enqueue into its bounded AV lane,
 * not block these native capture callbacks on network IO.
 *
 * This engine is not yet wired into a service/control handler or advertised as
 * a usable provider. Native physical device acceptance remains separate.
 */
@RequiresApi(30)
internal class PhoneWebcamAndroidCapture(private val service: Service, private val permit: PhoneWebcamCapturePermit,
    private val sample: (video: Boolean, bootTimeNanos: Long, bytes: ByteArray) -> Unit,
    private val ended: (Throwable?) -> Unit) : PhoneWebcamCaptureDevice {
    private val started = AtomicBoolean(false)
    private val active = AtomicBoolean(false)
    private val stop = CountDownLatch(1)
    private val cleanupEnded = CountDownLatch(1)
    private val cameraOpenEnded = CountDownLatch(1)
    private val resources = Any()
    @Volatile private var failure: Throwable? = null
    @Volatile private var imageThread: HandlerThread? = null
    @Volatile private var audioThread: Thread? = null
    private var reader: ImageReader? = null
    private var recorder: AudioRecord? = null
    private var camera: CameraDevice? = null
    private var capture: CameraCaptureSession? = null
    @Volatile private var openRequested = false
    @Volatile private var cleanupStarted = false
    @Volatile private var lastVideo = 0L
    @Volatile private var lastAudio = 0L
    private var admittedAt = 0L
    private var previousVideo = -1L
    val terminalFailure: Throwable? get() = failure

    @SuppressLint("MissingPermission") // Real fresh permission/FGS check below and at every callback/read.
    override fun start() {
        check(Looper.myLooper() == Looper.getMainLooper()) { "webcam_foreground_start_thread_required" }
        check(started.compareAndSet(false, true)) { "webcam_capture_start_already_used" }
        try {
            permit.enterForeground(service)
            active.set(true)
            admittedAt = SystemClock.elapsedRealtimeNanos()
            Thread(::finish, "Magnolie webcam cleanup").start()
            cleanupStarted = true
            current()
            val manager = service.getSystemService(CameraManager::class.java)
            val facing = if (permit.frontCamera) CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
            val ids = manager.cameraIdList
            check(ids.size <= 16) { "webcam_camera_inventory_unsupported" }
            val id = ids.firstOrNull { manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == facing }
                ?: error("webcam_requested_camera_unavailable")
            val characteristics = manager.getCameraCharacteristics(id)
            check(characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME) {
                "webcam_common_av_clock_unsupported"
            }
            check(characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)?.getOutputSizes(ImageFormat.YUV_420_888)
                ?.contains(Size(PhoneWebcamMediaCodec.WIDTH, PhoneWebcamMediaCodec.HEIGHT)) == true) { "webcam_camera_format_unsupported" }
            val rate = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
                ?.filter { it.lower <= PhoneWebcamMediaCodec.FPS && it.upper >= PhoneWebcamMediaCodec.FPS }
                ?.minByOrNull { it.upper - it.lower } ?: error("webcam_camera_rate_unsupported")
            val images = ImageReader.newInstance(PhoneWebcamMediaCodec.WIDTH, PhoneWebcamMediaCodec.HEIGHT, ImageFormat.YUV_420_888, 2)
            synchronized(resources) {
                if (!active.get()) { images.close(); error("webcam_capture_retired") }
                reader = images
                imageThread = HandlerThread("Magnolie webcam images").also { it.start() }
            }
            images.setOnImageAvailableListener({ available -> image(available) }, Handler(checkNotNull(imageThread).looper))
            if (!permit.muted) startAudio()
            current()
            openRequested = true
            // App main executor remains valid after this engine stops. A late
            // open callback can always close its ORIGINAL device, not disappear
            // into a dead per-session HandlerThread and leak the camera.
            try { manager.openCamera(id, service.mainExecutor, object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    if (!active.get()) { device.close(); cameraOpenEnded.countDown(); return }
                    try {
                        current()
                        synchronized(resources) {
                            if (!active.get()) { device.close(); cameraOpenEnded.countDown(); return }
                            camera = device
                        }
                        cameraOpenEnded.countDown()
                        val handler = Handler(Looper.getMainLooper())
                        @Suppress("DEPRECATION")
                        device.createCaptureSession(listOf(images.surface), object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(session: CameraCaptureSession) {
                                if (!active.get()) { session.close(); return }
                                try {
                                    current()
                                    synchronized(resources) {
                                        if (!active.get()) { session.close(); return }
                                        capture = session
                                    }
                                    val request = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                                        addTarget(images.surface)
                                        set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                                        set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, rate)
                                    }.build()
                                    current()
                                    session.setRepeatingRequest(request, null, handler)
                                } catch (error: Throwable) { if (active.get()) fail(error) }
                            }
                            override fun onConfigureFailed(session: CameraCaptureSession) { session.close(); if (active.get()) fail(IllegalStateException("webcam_camera_configuration_failed")) }
                        }, handler)
                    } catch (error: Throwable) { device.close(); cameraOpenEnded.countDown(); if (active.get()) fail(error) }
                }
                override fun onDisconnected(device: CameraDevice) { device.close(); cameraOpenEnded.countDown(); if (active.get()) fail(IllegalStateException("webcam_camera_disconnected")) }
                override fun onError(device: CameraDevice, error: Int) { device.close(); cameraOpenEnded.countDown(); if (active.get()) fail(IllegalStateException("webcam_camera_error_$error")) }
            }) } catch (error: Throwable) { cameraOpenEnded.countDown(); throw error }
        } catch (error: Throwable) {
            if (!openRequested) cameraOpenEnded.countDown()
            fail(error)
            if (!cleanupStarted) {
                // Foreground admission may fail before the cleanup worker starts.
                permit.close()
                cleanupEnded.countDown()
                notifyEnded()
            }
            throw error
        }
    }

    private fun current() { check(active.get()) { "webcam_capture_retired" }; permit.requireActive(service); check(active.get()) { "webcam_capture_retired" } }

    private fun image(source: ImageReader) {
        if (!active.get()) return
        try {
            source.acquireLatestImage()?.use { value ->
                current()
                val time = value.timestamp
                check(time > 0) { "webcam_camera_timestamp_invalid" }
                check(previousVideo < 0 || time > previousVideo) { "webcam_camera_timestamp_stale" }
                if (previousVideo >= 0 && time - previousVideo < 1_000_000_000L / PhoneWebcamMediaCodec.FPS) return
                check(value.cropRect.left == 0 && value.cropRect.top == 0 && value.cropRect.width() == PhoneWebcamMediaCodec.WIDTH &&
                    value.cropRect.height() == PhoneWebcamMediaCodec.HEIGHT) { "webcam_camera_crop_unsupported" }
                val bytes = PhoneWebcamYuv.i420(value.width, value.height, value.planes.map { PhoneWebcamYuv.Plane(it.buffer, it.rowStride, it.pixelStride) })
                current(); sample(true, time, bytes); previousVideo = time; lastVideo = SystemClock.elapsedRealtimeNanos()
            }
        } catch (error: Throwable) { if (active.get()) fail(error) }
    }

    @SuppressLint("MissingPermission")
    private fun startAudio() {
        current()
        val minimum = AudioRecord.getMinBufferSize(48_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        check(minimum > 0) { "webcam_microphone_format_unsupported" }
        val record = AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.MIC)
            .setAudioFormat(AudioFormat.Builder().setSampleRate(48_000).setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build()).setBufferSizeInBytes(maxOf(minimum, PhoneWebcamMediaCodec.AUDIO_BYTES * 4)).build()
        synchronized(resources) {
            if (!active.get()) { record.release(); error("webcam_capture_retired") }
            recorder = record
            check(record.state == AudioRecord.STATE_INITIALIZED) { "webcam_microphone_unavailable" }
            current(); record.startRecording()
            check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING) { "webcam_microphone_unavailable" }
            audioThread = Thread({ audio(record) }, "Magnolie webcam microphone").also { it.start() }
        }
    }

    private fun audio(record: AudioRecord) {
        var frames = 0L
        var previous = -1L
        val initialDeadline = SystemClock.elapsedRealtime() + 2_000
        try {
            while (active.get()) {
                val data = ByteArray(PhoneWebcamMediaCodec.AUDIO_BYTES)
                var at = 0
                while (at < data.size) {
                    current()
                    val count = record.read(data, at, data.size - at, AudioRecord.READ_BLOCKING)
                    check(count > 0 && count <= data.size - at) { "webcam_microphone_read_failed" }
                    at += count
                }
                val startFrame = frames
                frames += data.size / 2
                current()
                val stamp = AudioTimestamp()
                if (record.getTimestamp(stamp, AudioTimestamp.TIMEBASE_BOOTTIME) != AudioRecord.SUCCESS) {
                    check(previous < 0 && SystemClock.elapsedRealtime() < initialDeadline) { "webcam_microphone_clock_unavailable" }
                    continue // Initial clock warmup only, not a published audio gap.
                }
                check(stamp.nanoTime > 0 && stamp.framePosition >= 0) { "webcam_microphone_timestamp_invalid" }
                val delta = startFrame - stamp.framePosition
                check(delta in -96_000L..96_000L) { "webcam_microphone_buffer_clock_diverged" }
                val time = stamp.nanoTime + delta * 1_000_000_000L / 48_000
                check(time > 0 && (previous < 0 || time > previous)) { "webcam_microphone_timestamp_stale" }
                current(); sample(false, time, data); previous = time; lastAudio = SystemClock.elapsedRealtimeNanos()
            }
        } catch (error: Throwable) { if (active.get()) fail(error) }
    }

    private fun fail(error: Throwable) { if (failure == null && cleanupEnded.count != 0L) failure = error; close() }
    override fun close() {
        active.set(false); permit.close(); stop.countDown()
        // Construction alone owns no native resource/worker. A cancelled
        // unstarted factory must not remain an imaginary pending capture.
        if (!started.get()) { cameraOpenEnded.countDown(); cleanupEnded.countDown() }
    }
    // A bounded cleanup ATTEMPT may finish while a native worker is still
    // draining. Preserve its original reference and deny slot reuse until the
    // actual thread exits, even after the shutdown-pending callback was sent.
    override fun isCompletelyStopped() = cleanupEnded.count == 0L &&
        imageThread?.isAlive != true && audioThread?.isAlive != true &&
        (!openRequested || cameraOpenEnded.count == 0L)
    private fun notifyEnded() {
        try { ended(failure) }
        catch (error: Exception) {
            // Optional transport/UI observers must not crash the Android app's
            // main/native cleanup thread after resources have been retired.
            val original = failure
            if (original == null) failure = error else if (original !== error) original.addSuppressed(error)
        }
    }

    private fun finish() {
        while (!stop.await(100, TimeUnit.MILLISECONDS)) {
            try {
                if (!active.get()) break
                permit.requireActive(service)
                val now = SystemClock.elapsedRealtimeNanos()
                check((lastVideo != 0L && (permit.muted || lastAudio != 0L)) || now - admittedAt < 5_000_000_000L) { "webcam_capture_start_timeout" }
                check((lastVideo == 0L || now - lastVideo < 500_000_000L) &&
                    (permit.muted || lastAudio == 0L || now - lastAudio < 500_000_000L)) { "webcam_capture_track_stalled" }
            } catch (error: Throwable) { if (active.get()) fail(error); break }
        }
        val snapshot = synchronized(resources) {
            val value = arrayOf(capture, camera, reader, recorder, imageThread, audioThread)
            capture = null; camera = null; reader = null; recorder = null
            value
        }
        runCatching { (snapshot[0] as? CameraCaptureSession)?.close() }.onFailure { if (failure == null) failure = it }
        runCatching { (snapshot[1] as? CameraDevice)?.close() }.onFailure { if (failure == null) failure = it }
        runCatching { (snapshot[2] as? ImageReader)?.close() }.onFailure { if (failure == null) failure = it }
        (snapshot[3] as? AudioRecord)?.let { record -> runCatching { record.stop() }; runCatching { record.release() }.onFailure { if (failure == null) failure = it } }
        val images = snapshot[4] as? HandlerThread
        images?.quitSafely()
        val microphone = snapshot[5] as? Thread
        images?.join(2_000); microphone?.join(2_000)
        if (images?.isAlive == true || microphone?.isAlive == true || openRequested && !cameraOpenEnded.await(2, TimeUnit.SECONDS)) {
            failure = IllegalStateException("webcam_capture_shutdown_pending", failure)
        }
        cleanupEnded.countDown()
        notifyEnded()
    }
}
