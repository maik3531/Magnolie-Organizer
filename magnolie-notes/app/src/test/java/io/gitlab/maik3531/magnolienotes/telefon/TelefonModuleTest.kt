package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.BuildConfig
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

class TelefonModuleTest {
    @Test fun `ausgewaehlte Meldungen brauchen nur Appwahl und Systemzugriff`() {
        assertFalse(TelefonModulStatus.notifications(emptySet(), false))
        assertFalse(TelefonModulStatus.notifications(setOf("example.app"), false))
        assertTrue(TelefonModulStatus.notifications(setOf("example.app"), true))
    }

    @Test fun `Telefoncode nutzt nur die Naeherungssperre fuer aktive Anrufe`() {
        val root = File("app/src/main")
        val source = root.walkTopDown().filter { it.isFile }.joinToString("\n") { it.readText() }
        assertFalse(source.contains("KEEP_SCREEN_ON"))
        assertFalse(source.contains("setTurnScreenOn"))
        assertFalse(source.contains("FULL_WAKE_LOCK"))
        assertFalse(source.contains("SCREEN_BRIGHT_WAKE_LOCK"))
        assertFalse(source.contains("SCREEN_DIM_WAKE_LOCK"))
        assertFalse(source.contains("ACQUIRE_CAUSES_WAKEUP"))
        assertFalse(source.contains("ON_AFTER_RELEASE"))
        assertTrue(source.contains("PROXIMITY_SCREEN_OFF_WAKE_LOCK"))
        assertTrue(source.contains("RELEASE_FLAG_WAIT_FOR_NO_PROXIMITY"))
    }

    @Test fun `direktes Waehlen verfolgt ausgehende Anrufe unabhaengig vom Eingangsschalter`() {
        val calls = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/EingehendeAnrufe.kt").readText()
        val work = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt").readText()
        val activity = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        assertTrue(calls.contains("fun beginOutgoing") && calls.contains("start()"))
        assertTrue(calls.contains("handler.postDelayed(outgoingTimeout, OUTGOING_START_TIMEOUT_MS)"))
        assertFalse(calls.contains("persistentListening"))
        assertTrue(work.contains("incoming.serviceStarted(storage.incomingCallsEnabled())"))
        assertTrue(work.contains("incoming.setIncomingListening(value)"))
        assertTrue(work.contains("incoming.runtimePermissionsChanged()"))
        assertTrue(work.contains("incoming.shutdown()"))
        assertTrue(calls.contains("private fun finish(call: TrackedCall"))
        val finish = calls.substring(calls.indexOf("private fun finish(call: TrackedCall"),
            calls.indexOf("private fun emit(call: TrackedCall"))
        assertTrue(finish.contains("val origin = origins.origin(call.callRef, now)"))
        assertTrue(finish.indexOf("val origin") < finish.indexOf("origins.clear(call.callRef)"))
        assertTrue(finish.contains("runCatching { emit(call, now, now, origin) }"))
        assertTrue(calls.substring(calls.indexOf("@Synchronized fun shutdown()"),
            calls.indexOf("private fun reconcileListening()"))
            .contains("finish(call, System.currentTimeMillis())"))
        assertTrue(work.contains("@Synchronized fun placeOutgoing"))
        assertTrue(work.contains("if (!serviceRunning || !storage.enabled())"))
        assertTrue(calls.contains("generation != listenerGeneration"))
        assertTrue(calls.contains("if (manager?.callState != TelephonyManager.CALL_STATE_IDLE)"))
        assertFalse(calls.contains("callback == null && manager?.callState"))
        assertTrue(work.contains("if (!serviceRunning || !storage.enabled()"))
        assertTrue(work.contains("while (serviceRunning && storage.enabled())"))
        assertTrue(work.contains("body.string(\"direction\") == \"outgoing\""))
        assertTrue(activity.contains("TelefonModulStatus.missingCallPermissions(zusammenhang)"))
        assertTrue(TelefonModulStatus.callPermissions.toList().containsAll(listOf(android.Manifest.permission.CALL_PHONE,
            android.Manifest.permission.READ_PHONE_STATE, android.Manifest.permission.READ_CALL_LOG, android.Manifest.permission.ANSWER_PHONE_CALLS)))
        assertTrue(activity.contains("runCatching { TelefonWerk.get(this).runtimePermissionsChanged() }"))
        val service = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonDienst.kt").readText()
        assertTrue(service.substring(service.indexOf("fun stop(context: Context)"))
            .contains("TelefonWerk.get(context).serviceStopped()"))
    }

    @Test fun `Dienststart ersetzt veraltete Berechtigungsstaende`() {
        val work = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt").readText()
        val serviceStart = work.substring(work.indexOf("fun serviceStarted()"),
            work.indexOf("fun refreshModules()"))
        assertTrue(serviceStart.contains("queue.removeKind(peer.device_id, \"capabilities.update\")"))
        assertTrue(serviceStart.contains("queue.removeKind(peer.device_id, \"grants.update\")"))
        assertTrue(work.substring(work.indexOf("private fun ensureControlMessages"))
            .contains("context.checkSelfPermission"))
    }
    private val main = File("app/src/main")
    private val res = File(main, "res")

    @Test fun `SMS Nachrichten sind nicht mehr protokollwirksam`() {
        listOf("sms_send.command", "sms_send.result", "sms_received.event").forEach { kind ->
            assertThrows(kind, TelefonProtokollFehler::class.java) {
                TelefonNachrichten.validate(TelefonNachrichten.message(kind, buildJsonObject {}, 60_000))
            }
        }
        val capabilities = TelefonNachrichten.capabilities()["items"] as JsonObject
        val grants = TelefonNachrichten.grants()["grants"] as JsonObject
        assertFalse(capabilities.keys.any { it.contains("sms", ignoreCase = true) })
        assertFalse(grants.keys.any { it.contains("sms", ignoreCase = true) })
        assertFalse(capabilities.containsKey("call_control"))
        assertFalse(grants.containsKey("call_control"))
        assertTrue(capabilities.containsKey("dial_request"))
        assertTrue(capabilities.containsKey("selected_notifications_readonly"))
        assertTrue(grants.containsKey("dial_request"))
        assertTrue(grants.containsKey("selected_notifications_readonly"))
        val legacyGrants = buildJsonObject {
            put("revision", JsonPrimitive(2)); put("grants", buildJsonObject {
                put("device_status", JsonPrimitive(true)); put("sms_send", JsonPrimitive(true))
                put("sms_received", JsonPrimitive(true)); put("selected_notifications_readonly", JsonPrimitive(true))
                put("call_control", JsonPrimitive(false)); put("dial_request", JsonPrimitive(true))
            })
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validate(TelefonNachrichten.message("grants.update", legacyGrants, 86_400_000))
        }
    }

    @Test fun `Produktcode hat keine native SMS Implementierung`() {
        val forbidden = listOf("android.permission.SEND_SMS", "android.permission.RECEIVE_SMS",
            "SmsManager", "SmsEingang", "SmsStatus", "android.permission.RECORD_AUDIO",
            "android.permission.MODIFY_PHONE_STATE", "READ_PRIVILEGED_PHONE_STATE", "ROLE_DIALER", "ROLE_SMS",
            "android.provider.Telephony.SMS_RECEIVED")
        val activeFiles = main.walkTopDown().filter(File::isFile).filterNot {
            it.name == "TelefonAblage.kt" || it.name == "TelefonDatenbank.kt"
        }.toList()
        forbidden.forEach { term ->
            assertFalse("$term ist noch im Produktcode", activeFiles.any { it.readText().contains(term) })
        }
        // v4 permits the number permission only for the separate owned-device opt-in.
        assertEquals(setOf("AndroidManifest.xml", "MainActivity.kt", "DeviceIdentifiers.kt"),
            activeFiles.filter { it.readText().contains("READ_PHONE_NUMBERS") }.map { it.name }.toSet())
        val activity = File(main, "java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        val identifiers = activity.substringAfter("beiIdentifierSharing = { enabled ->")
            .substringBefore("beiPersonalEigen =")
        assertTrue(identifiers.contains("telefonWerk.beginIdentifierPermission()?.let"))
        val launch = "identifierPermission.launch(Manifest.permission.READ_PHONE_NUMBERS)"
        assertTrue(identifiers.contains(launch))
        assertEquals(1, activity.split(launch).size - 1)
        val module = File(main, "java/io/gitlab/maik3531/magnolienotes/telefon/TelefonModule.kt").readText()
        assertFalse(module.contains("Intent.ACTION_DIAL"))
        assertTrue(activeFiles.any { it.readText().contains("placeCall") })
        assertFalse(module.contains("Intent.ACTION_CALL"))
        assertTrue(module.contains("NotificationCompat.MessagingStyle"))
        assertTrue(module.contains("Notification.CATEGORY_MESSAGE"))
        assertFalse(module.contains("RemoteInput"))
        assertFalse(module.contains("notification.actions"))
    }

    @Test fun `finale Manifeste enthalten nur Dial und Benachrichtigungsdienst`() {
        val variant = if (BuildConfig.DEBUG) "debug" else "release"
        val task = if (BuildConfig.DEBUG) "Debug" else "Release"
        val manifests = listOf(
            File(main, "AndroidManifest.xml"),
            File("app/build/intermediates/merged_manifests/$variant/process${task}Manifest/AndroidManifest.xml"),
            File("app/build/intermediates/packaged_manifests/$variant/process${task}ManifestForPackage/AndroidManifest.xml")
        )
        assertTrue("Generierte Manifeste fehlen", manifests.all(File::isFile))
        manifests.forEach { file ->
            val manifest = file.readText()
            listOf("SEND_SMS", "RECEIVE_SMS", "READ_PRIVILEGED_PHONE_STATE", "RECORD_AUDIO",
                "MODIFY_PHONE_STATE", "ROLE_DIALER", "ROLE_SMS", "SmsEingang", "SmsStatus", "SMS_RECEIVED")
                .forEach { assertFalse("$it in ${file.path}", manifest.contains(it)) }
            assertFalse("ACTION_DIAL in ${file.path}", manifest.contains("android.intent.action.DIAL"))
            listOf("CALL_PHONE", "READ_PHONE_STATE", "READ_PHONE_NUMBERS", "ANSWER_PHONE_CALLS", "READ_CALL_LOG", "WAKE_LOCK")
                .forEach { assertTrue("$it fehlt in ${file.path}", manifest.contains(it)) }
            assertTrue("NotificationListener fehlt in ${file.path}", manifest.contains("NotificationListenerService"))
        }
    }

    @Test fun `alte Peer SMS Felder werden eng migriert`() {
        val current = JsonObject((TelefonKanonisch.json.encodeToJsonElement(TelefonBestand.serializer(), TelefonBestand(peer = TelefonPeer(
            device_id = "22222222-2222-4222-8222-222222222222", display_name = "Desktop", static_public = "key"))) as JsonObject) +
            ("storage_version" to JsonPrimitive(1)))
        val peer = current["peer"] as JsonObject
        val old = JsonObject(current + ("peer" to JsonObject(peer +
            ("remote_sms_send_granted" to JsonPrimitive(true)) + ("remote_sms_send_available" to JsonPrimitive(true)))))
        val (clean, migrated) = sanitizeLegacyPeer(old)
        assertTrue(migrated)
        val cleanPeer = clean["peer"] as JsonObject
        assertFalse(cleanPeer.keys.any { it.startsWith("remote_sms") })
        assertEquals(false, TelefonKanonisch.json.decodeFromJsonElement(TelefonBestand.serializer(), clean)
            .peer?.remote_dial_request_granted)
        assertThrows(TelefonProtokollFehler::class.java) {
            sanitizeLegacyPeer(JsonObject(current + ("unexpected" to JsonPrimitive(true))))
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            sanitizeLegacyPeer(JsonObject(current + ("peer" to JsonObject(peer + ("unexpected" to JsonPrimitive(true))))))
        }
    }

    @Test fun `DB Migration entfernt nur alte SMS Daten`() {
        val source = File(main, "java/io/gitlab/maik3531/magnolienotes/telefon/TelefonDatenbank.kt").readText()
        assertTrue(source.contains("null, 7"))
        assertTrue(source.contains("transport_policy"))
        assertTrue(source.contains("personal_batch"))
        assertTrue(source.contains("personal_run"))
        assertTrue(source.contains("queuePersonalCompletion"))
        assertTrue(source.contains("transportPolicy in setOf(\"any\", \"wifi_only\")"))
        assertTrue(source.contains("records > 100_000"))
        assertTrue(source.contains("50 * 1024 * 1024"))
        assertTrue(source.contains("DROP TABLE IF EXISTS sms_effect"))
        assertTrue(source.contains("sms_send.command"))
        assertTrue(source.contains("sms_received.event"))
        val migration = source.substringAfter("override fun onUpgrade").substringBefore("private fun createAttachmentTables")
        assertFalse(Regex("delete\\([^\\n]+dial_request").containsMatchIn(migration))
        assertFalse(Regex("delete\\([^\\n]+selected_notifications").containsMatchIn(migration))
        assertFalse(source.contains("CREATE TABLE sms_effect"))
    }

    @Test fun `alle Telefontexte sind SMS frei und beschreiben Dial und Notifications`() {
        val semanticMarkers = mapOf(
            "values" to ("dial" to "read-only"),
            "values-ar" to ("طلبات الاتصال" to "للقراءة فقط"),
            "values-be" to ("набор" to "толькі для чытання"),
            "values-cs" to ("vytáčení" to "pouze pro čtení"),
            "values-da" to ("opkald" to "skrivebeskyttet"),
            "values-de" to ("wähl" to "nur lesend"),
            "values-es" to ("marcación" to "solo lectura"),
            "values-fr" to ("numérotation" to "lecture seule"),
            "values-hi" to ("डायल" to "केवल पढ़ने"),
            "values-hsb" to ("wołanja" to "jenož čitajomne"),
            "values-it" to ("composizione" to "sola lettura"),
            "values-ja" to ("発信" to "読み取り専用"),
            "values-nb" to ("oppring" to "skrivebeskyttet"),
            "values-nl" to ("kies" to "alleen-lezen"),
            "values-pl" to ("wybier" to "tylko do odczytu"),
            "values-pt" to ("marcação" to "só de leitura"),
            "values-ru" to ("набор" to "только для чтения"),
            "values-tr" to ("arama" to "salt okunur"),
            "values-uk" to ("набор" to "лише для читання"),
            "values-zh-rCN" to ("拨号" to "只读"),
        )
        val files = res.listFiles()!!.filter { it.name == "values" || it.name.startsWith("values-") }
            .map { File(it, "strings.xml") }.filter(File::exists)
        assertEquals(20, files.size)
        files.forEach { file ->
            val locale = requireNotNull(file.parentFile).name
            val markers = semanticMarkers.getValue(locale)
            val strings = strings(file)
            assertFalse("SMS-Ressource in $locale", strings.keys.any {
                it.startsWith("telefon_sms") || it.startsWith("telefon_sim") || it == "telefon_call_control_hinweis"
            })
            val hint = strings.getValue("telefon_hinweis").lowercase()
            assertFalse("SMS-Text in $locale", hint.contains("sms"))
            assertTrue("Dial fehlt in $locale", hint.contains(markers.first))
            val notifications = strings.getValue("telefon_benachrichtigungen_hinweis").lowercase()
            assertTrue("Read-only fehlt in $locale", notifications.contains(markers.second))
        }
    }

    private fun strings(file: File): Map<String, String> {
        val document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file)
        return (0 until document.getElementsByTagName("string").length).associate { index ->
            val node = document.getElementsByTagName("string").item(index)
            node.attributes.getNamedItem("name").nodeValue to node.textContent
        }
    }
}
