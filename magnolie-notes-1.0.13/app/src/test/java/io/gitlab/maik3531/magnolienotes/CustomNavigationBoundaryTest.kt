package io.gitlab.maik3531.magnolienotes

import android.app.Application
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import io.gitlab.maik3531.magnolienotes.telefon.TelefonPeer
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28])
class CustomNavigationBoundaryTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private val state get() = PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch)
    private val peer = TelefonPeer("fixture", "Fixture", "public-key", own_device = true,
        remote_own_device = true, remote_personal_tasks_sync_available = true,
        remote_personal_tasks_sync_versions = listOf(4))
    private val id get() = state.items.keys.single()
    private fun intent() = CustomNavigation.absicht(context, state, id)
    private fun target(s: PersonalCustomState = state, p: TelefonPeer? = peer, i: Intent = intent()) =
        CustomNavigation.ziel(context, i, s, p)

    @Test fun exactExistingMirrorIsTheOnlyReadOnlyTarget() {
        val before = Bestand(personalCustom = state, notizen = listOf(Notiz(id)), aufgaben = listOf(Aufgabe(id)))
        assertEquals(id, target(before.personalCustom))
        assertEquals(before, before.copy(personalCustom = state))
        assertNull(target(state.copy(items = emptyMap())))
    }

    @Test fun malformedAndForeignUrisAreRejectedWithoutMutation() {
        val valid = intent().dataString!!
        val invalid = listOf(valid + "/", valid + "?id=other", valid + "#fragment", valid + "/other",
            valid.replace("custom/", "custom:80/"), valid.replace("//custom", "//user@custom"),
            valid.replace("custom:", "custom%3A"), valid.replace("magnolie:", "MAGNOLIE:"),
            "magnolie://custom/ordinary-note", "magnolie://custom/+12025550123", "tel:+12025550123",
            "magnolie-pair:e30", "magnolie-phone://custom/$id", "https://custom/$id", "magnolie://aufgabe/$id")
        for (text in invalid) {
            val request = intent().setData(Uri.parse(text))
            assertNull(text, CustomNavigation.anfrage(context, request))
            assertEquals(text, request.dataString)
        }
    }

    @Test fun exportedMainImplicitWrongActionAndCallerExtrasCannotBecomeInternalRequests() {
        val cases = listOf(intent().setComponent(ComponentName(context, MainActivity::class.java)),
            intent().setComponent(null), intent().setAction(Intent.ACTION_VIEW),
            intent().setPackage("foreign.package"), intent().addCategory(Intent.CATEGORY_BROWSABLE),
            intent().setDataAndType(intent().data, "text/plain"),
            intent().apply { selector = Intent(Intent.ACTION_CALL) })
        cases.forEach { assertNull(CustomNavigation.anfrage(context, it)) }
        val withExtras = intent().putExtra(MainActivity.ZEIGE_AUFGABE, "ordinary")
            .putExtra("call_ref", "+12025550123").putExtra("custom_id", "other")
        val clean = CustomNavigation.anfrage(context, withExtras)!!
        assertFalse(clean.hasExtra(MainActivity.ZEIGE_AUFGABE))
        assertFalse(clean.hasExtra("call_ref"))
        assertFalse(clean.hasExtra("custom_id"))
        assertEquals(id, target(i = clean))
    }

    @Test fun peerIdentityAndBilateralOwnDeviceCapabilityAreMandatory() {
        val peers = listOf(null, peer.copy(device_id = "other"), peer.copy(static_public = "other-key"),
            peer.copy(state = "paired_unverified"), peer.copy(own_device = false), peer.copy(remote_own_device = false),
            peer.copy(remote_personal_tasks_sync_available = false), peer.copy(remote_personal_tasks_sync_versions = listOf(1)))
        peers.forEach { assertNull(target(p = it)) }
        assertNull(target(state.copy(owner = "other")))
        assertNull(target(state.copy(active = false)))
    }

    @Test fun staleGenerationGrantAndRestoredArchiveCannotResurrectNavigation() {
        assertNull(target(state.copy(generation = "new-generation")))
        assertNull(target(PersonalCustom.restore(state, state)))
        for (field in listOf("local", "remote")) {
            val disabled = CustomFixtures.consent.getValue("revoked").jsonObject
            val reenabled = CustomFixtures.consent.getValue("reenabled").jsonObject
            assertNull(target(if (field == "local") state.copy(local = disabled) else state.copy(remote = disabled)))
            assertNull(target(if (field == "local") state.copy(local = reenabled) else state.copy(remote = reenabled)))
        }
    }

    @Test fun missingDeletedPendingKeptAndMutedItemsCannotBeOpenedByAnOldNotice() {
        val item = state.items.getValue(id)
        for (status in listOf("deleted", "pending", "kept"))
            assertNull(target(state.copy(items = mapOf(id to item.copy(status = status)))))
        for ((field, value) in listOf("module_reminders" to false, "item_reminder" to false, "completed" to true)) {
            val record = CustomFixtures.changed { it[field] = JsonPrimitive(value) }.getValue("upserts").jsonArray.single().jsonObject
            assertNull(target(state.copy(items = mapOf(id to item.copy(record = record)))))
        }
        assertNull(target(state.copy(items = emptyMap())))
    }

    @Test fun sourceBindingExactSchemaAndContentHashAreRevalidated() {
        val item = state.items.getValue(id)
        val changes = listOf(item.copy(source = "123e4567-e89b-42d3-a456-426614174002"),
            item.copy(record = JsonObject(item.record + ("item_id" to JsonPrimitive("other")))),
            item.copy(record = JsonObject(item.record + ("id" to JsonPrimitive("custom:" + "0".repeat(64))))),
            item.copy(record = JsonObject(item.record + ("hash" to JsonPrimitive("0".repeat(64))))),
            item.copy(record = JsonObject(item.record + ("call_ref" to JsonPrimitive("injected")))),
            item.copy(record = JsonObject(emptyMap())), item.copy(owner = "other"), item.copy(generation = "old"))
        changes.forEach { assertNull(target(state.copy(items = mapOf(id to it)))) }
    }

    @Test fun absentAndWronglyTypedProvenanceExtrasFailClosed() {
        for (key in listOf("custom_owner", "custom_generation", "custom_local_epoch", "custom_remote_epoch")) {
            assertNull(target(i = intent().apply { removeExtra(key) }))
            assertNull(target(i = intent().putExtra(key, 42)))
            assertNull(target(i = intent().putExtra(key, "x".repeat(257))))
            assertNull(target(i = intent().putExtra(key, "forged")))
        }
    }

    @Test fun notificationAliasIsNonExportedAndResolvesToExistingSingleTaskActivity() {
        val info = context.packageManager.getActivityInfo(intent().component!!, 0)
        assertFalse(info.exported)
        assertEquals(MainActivity::class.java.name, info.targetActivity)
        assertEquals(android.content.pm.ActivityInfo.LAUNCH_SINGLE_TASK, info.launchMode)
    }
}
