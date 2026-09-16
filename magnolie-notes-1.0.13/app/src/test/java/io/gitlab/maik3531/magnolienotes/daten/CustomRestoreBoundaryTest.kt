package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.UUID
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class, sdk = [28])
class CustomRestoreBoundaryTest {
    @Test fun archiveCannotUndoOffUnpairOrNewDevice() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val key = { SecretKeySpec(ByteArray(32) { 27 }, "AES") }
        var store = Ablage.fuerTest(context, key)
        val on = PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch)
        store.personalCustomChange { on }
        val archive = store.journalNutzlast()
        val states = listOf(
            on.copy(local = CustomFixtures.consent.getValue("revoked").jsonObject),
            PersonalCustomState(items = on.items),
            PersonalCustom.bind(PersonalCustomState(), "different:peer"),
            PersonalCustomState())
        for (live in states) for (portable in listOf(false, true)) {
            store.personalCustomChange { live }
            if (portable) store.portableWiederherstellen(archive.first, UUID.randomUUID().toString())
            else store.journalWiederherstellen(archive.first, archive.second, UUID.randomUUID().toString())
            val beforeReopen = store.bestand.value.personalCustom
            assertTrue(Ablage.enthaeltKryptoBestand(context.filesDir))
            store = Ablage.fuerTest(context, key)
            val restored = store.bestand.value.personalCustom
            assertEquals(beforeReopen, restored)
            assertEquals(live.local, restored.local)
            assertEquals(live.remote, restored.remote)
            assertEquals(live.owner, restored.owner)
            assertEquals(on.items.keys, restored.items.keys)
            assertNull(PersonalCustom.nextAlarm(restored, restored.items.values.single(), 0))
        }
    }
}
