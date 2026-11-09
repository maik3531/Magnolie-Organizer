package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Durable observation before any original write. Not an open descriptor,
 * OS grant, mutation completion, Saved receipt or restart capability. */
internal class GalleryPcPreWriteRecord private constructor(internal val body: JsonObject) {
    val id: String get() = stage.id
    val stage: GalleryPcStageRecord get() = GalleryPcStageRecord.parse(body.getValue("stage").jsonObject)
    val grantsWriteAuthority: Boolean get() = false
    companion object {
        const val PREFIX = "gallery-pc-before-write-v1/"
        const val MAX_RECORDS = 128
        internal fun create(stage: GalleryPcStageRecord, descriptor: JsonObject): GalleryPcPreWriteRecord = parse(buildJsonObject {
            put("format", 1); put("state", "before_write"); put("stage", stage.body); put("descriptor", descriptor)
        })
        internal fun parse(value: JsonObject): GalleryPcPreWriteRecord = try {
            if (value.keys != setOf("format", "state", "stage", "descriptor") || value["format"] != JsonPrimitive(1) ||
                value["state"] != JsonPrimitive("before_write")) fail()
            val stage = GalleryPcStageRecord.parse(value.getValue("stage").jsonObject)
            if (!stage.sealed) fail()
            val fd = value.getValue("descriptor").jsonObject
            if (fd.keys != setOf("device", "inode", "mode", "links", "uid", "gid", "size", "mtime_s", "mtime_ns", "ctime_s", "ctime_ns") ||
                fd.long("device") < 0 || fd.long("inode") <= 0 || fd.long("mode") !in 0..Int.MAX_VALUE.toLong() ||
                !android.system.OsConstants.S_ISREG(fd.long("mode").toInt()) || fd.long("links") != 1L ||
                fd.long("uid") < 0 || fd.long("gid") < 0 || fd["size"] != stage.plan.predecessor.body["size"] ||
                fd.long("mtime_ns") !in 0..999_999_999 || fd.long("ctime_ns") !in 0..999_999_999) fail()
            fd.long("mtime_s"); fd.long("ctime_s")
            GalleryPcPreWriteRecord(value)
        } catch (_: Exception) { fail() }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_before_write_record_invalid")
    }
}
