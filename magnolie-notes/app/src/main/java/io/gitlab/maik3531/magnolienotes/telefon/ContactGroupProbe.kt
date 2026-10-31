package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Own-device debug-only preparation probe. No contact fields, accounts or write ticket leave it. */
object ContactGroupProbe {
    const val VERSION = 18
    val stages = setOf("request", "permission", "snapshot", "snapshot_shape", "uid", "raw_versions", "account_scope", "groups", "catalog", "report", "complete")
    fun validateRequest(value: JsonObject) {
        require(value.keys == setOf("version", "request_id", "action", "uid"))
        require(value["version"] == JsonPrimitive(VERSION) && value.string("action") == "diagnostics")
        ContactGroupWrite.validateRequest(JsonObject(value + mapOf("version" to JsonPrimitive(ContactGroupWrite.VERSION), "action" to JsonPrimitive("prepare"))))
    }
    fun validateReport(value: JsonObject) {
        require(value.keys == setOf("version", "request_id", "action", "uid", "state", "stage", "error_type", "reason", "raw_count", "version_count", "account_count", "mime_supported", "reader_complete"))
        validateRequest(JsonObject(value.filterKeys { it in setOf("version", "request_id", "action", "uid") }))
        require(value.string("state") in setOf("available", "failed") && value.string("stage") in stages)
        require(Regex("[A-Za-z][A-Za-z0-9]{0,63}").matches(value.string("error_type")))
        require(value.string("reason") in setOf("none", "contact_groups_ambiguous_account", "contact_groups_unknown", "contact_groups_unavailable", "contact_groups_incomplete", "provider_failure"))
        for (key in listOf("raw_count", "version_count", "account_count")) require(value[key]?.jsonPrimitive?.let {
            !it.isString && it.intOrNull?.let { number -> number in 0..10000 } == true } == true)
        require(value["mime_supported"]?.jsonPrimitive?.let { !it.isString && it.booleanOrNull != null } == true)
        require(value["reader_complete"]?.jsonPrimitive?.let { !it.isString && it.booleanOrNull != null } == true)
        if (value.string("state") == "available") require(value.string("stage") == "complete" && value.string("error_type") == "None" && value.string("reason") == "none" && value["reader_complete"] == JsonPrimitive(true))
    }
}
