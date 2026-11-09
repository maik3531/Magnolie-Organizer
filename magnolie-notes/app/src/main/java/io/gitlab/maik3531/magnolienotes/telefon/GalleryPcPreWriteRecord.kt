package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Durable write phases retaining the original prewrite witness. Not an open
 * descriptor, OS grant, history completion, Saved or restart capability. */
internal class GalleryPcPreWriteRecord private constructor(internal val body: JsonObject) {
    val id: String get() = stage.id
    val stage: GalleryPcStageRecord get() = GalleryPcStageRecord.parse(body.getValue("stage").jsonObject)
    val grantsWriteAuthority: Boolean get() = false
    val state: String get() = body.string("state")
    internal fun startWrite(): GalleryPcPreWriteRecord {
        if (state != "before_write") DeviceFileControl.fail("gallery_pc_write_start_original_operation_required")
        return parse(JsonObject(body + ("state" to JsonPrimitive("write_started"))))
    }
    internal fun verifyProvider(row: JsonObject, descriptor: JsonObject): GalleryPcPreWriteRecord {
        if (state != "write_started") DeviceFileControl.fail("gallery_pc_postwrite_original_operation_required")
        val file = GalleryPcStageRecord.media(stage.plan).manifest.files.single()
        return parse(JsonObject(body + mapOf("state" to JsonPrimitive("provider_verified"), "postwrite" to buildJsonObject {
            put("row", row); put("descriptor", descriptor); put("size", file.size); put("sha256", file.sha256)
        })))
    }
    companion object {
        const val PREFIX = "gallery-pc-before-write-v1/"
        const val MAX_RECORDS = 128
        internal fun create(stage: GalleryPcStageRecord, descriptor: JsonObject): GalleryPcPreWriteRecord = parse(buildJsonObject {
            put("format", 1); put("state", "before_write"); put("stage", stage.body); put("descriptor", descriptor)
        })
        internal fun parse(value: JsonObject): GalleryPcPreWriteRecord = try {
            val verified = value["state"] == JsonPrimitive("provider_verified")
            if (value.keys != setOf("format", "state", "stage", "descriptor") + (if (verified) setOf("postwrite") else emptySet()) ||
                value["format"] != JsonPrimitive(1) || value["state"] !in setOf(JsonPrimitive("before_write"), JsonPrimitive("write_started"), JsonPrimitive("provider_verified"))) fail()
            val stage = GalleryPcStageRecord.parse(value.getValue("stage").jsonObject)
            if (!stage.sealed) fail()
            val fd = value.getValue("descriptor").jsonObject
            validateDescriptor(fd, stage.plan.predecessor.body.long("size"))
            if (verified) {
                val post = value.getValue("postwrite").jsonObject; val file = GalleryPcStageRecord.media(stage.plan).manifest.files.single()
                if (post.keys != setOf("row", "descriptor", "size", "sha256") || post["size"] != JsonPrimitive(file.size) || post["sha256"] != JsonPrimitive(file.sha256)) fail()
                val oldRow = stage.plan.predecessor.row!!; val row = post.getValue("row").jsonObject
                if (row.filterKeys { it != "revision" } != oldRow.filterKeys { it != "revision" } ||
                    !Regex("[1-9][0-9]*").matches(row.string("revision")) || row.string("revision").toLong() <= oldRow.string("revision").toLong()) fail()
                val newFd = post.getValue("descriptor").jsonObject; validateDescriptor(newFd, file.size)
                if (listOf("device", "inode", "mode", "links", "uid", "gid").any { fd[it] != newFd[it] }) fail()
            }
            GalleryPcPreWriteRecord(value)
        } catch (_: Exception) { fail() }
        private fun validateDescriptor(fd: JsonObject, bytes: Long) {
            if (fd.keys != setOf("device", "inode", "mode", "links", "uid", "gid", "size", "mtime_s", "mtime_ns", "ctime_s", "ctime_ns") ||
                fd.long("device") < 0 || fd.long("inode") <= 0 || fd.long("mode") !in 0..Int.MAX_VALUE.toLong() ||
                !android.system.OsConstants.S_ISREG(fd.long("mode").toInt()) || fd.long("links") != 1L ||
                fd.long("uid") < 0 || fd.long("gid") < 0 || fd["size"] != JsonPrimitive(bytes) ||
                fd.long("mtime_ns") !in 0..999_999_999 || fd.long("ctime_ns") !in 0..999_999_999) fail()
            fd.long("mtime_s"); fd.long("ctime_s")
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_before_write_record_invalid")
    }
}
