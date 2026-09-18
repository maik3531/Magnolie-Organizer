package io.gitlab.maik3531.magnolienotes

import android.accounts.Account
import android.accounts.AccountManager
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.ActivityInfo
import android.os.Bundle
import android.os.Process
import android.provider.ContactsContract
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.view.KeyEvent
import android.view.accessibility.AccessibilityNodeInfo
import io.gitlab.maik3531.magnolienotes.baum.*
import io.gitlab.maik3531.magnolienotes.daten.*
import io.gitlab.maik3531.magnolienotes.sicherung.*
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.File
import java.security.KeyStore
import java.util.UUID
import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class NativeValidationTest {
    private val instrumentation get() = ValidationTestRunner.instance
    private val context get() = instrumentation.targetContext
    private val storage get() = Ablage.hole(context)

    @Before fun ready() {
        check(context.packageName.endsWith(".validation"))
        assertTrue(runBlocking { withTimeout(30_000) { (context.applicationContext as MagnolieApp).awaitReady() } })
        Ersteinrichtung.abschliessen(context)
    }

    private fun key(alias: String): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            generateKey()
        }
    }

    @Test fun startupAndKeystore() {
        val alias = "native-validation-${UUID.randomUUID()}"
        try {
            val secret = key(alias)
            assertNull(secret.encoded)
            val password = "native-backup-fixture".toCharArray()
            val first = PasswortHuelle.verschluesseln(password, secret)
            val second = PasswortHuelle.verschluesseln(password, secret)
            assertFalse(first.contentEquals(second))
            assertArrayEquals(password, PasswortHuelle.entschluesseln(first, secret))
            first[first.lastIndex] = (first.last().toInt() xor 1).toByte()
            assertThrows(AEADBadTagException::class.java) { PasswortHuelle.entschluesseln(first, secret) }
            val automatic = AndroidAutoSicherung.hole(context)
            automatic.passwortSichern(password)
            assertTrue(automatic.zustand.value.passwortGesichert)
            assertEquals(AutoSicherungsStatus.BEREIT, automatic.zustand.value.status)
            val reload = AndroidAutoSicherung::class.java.getDeclaredConstructor(Context::class.java).run {
                isAccessible = true; newInstance(context)
            }
            val read = AndroidAutoSicherung::class.java.getDeclaredMethod("passwortLaden").apply { isAccessible = true }
            val restored = read.invoke(reload) as CharArray
            assertArrayEquals("native-backup-fixture".toCharArray(), restored)
            restored.fill('\u0000')
        } finally { KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) } }
    }

    @Test fun contactsInIsolatedAccount() {
        val account = Account("Magnolie native validation ${UUID.randomUUID()}", "io.gitlab.maik3531.magnolienotes.validation.account")
        val manager = AccountManager.get(context)
        assertTrue(manager.addAccountExplicitly(account, null, Bundle()))
        val ids = mutableListOf<Long>()
        try {
            val adapter = AndroidKontakte(context, account)
            assertTrue(adapter.snapshot().kontakte.isEmpty())
            val contacts = listOf(
                KontaktDaten(vorname = "Anna Maria", geburtstag = "--02-29", jubilaeum = "--06-07",
                    anzeigename = "Anna Maria", vcardName = listOf("N:;Anna Maria;;;", "FN:Anna Maria")),
                KontaktDaten(nachname = "Van Dame", geburtstag = "1604-02-29", jubilaeum = "--02-29",
                    anzeigename = "Van Dame", vcardName = listOf("N:Van Dame;;;;", "FN:Van Dame")))
            contacts.forEach { expected ->
                val created = adapter.anlegen(expected); ids += created.rawContactId
                val actual = adapter.liesRaw(created.rawContactId)!!.daten
                assertEquals(expected.vorname, actual.vorname); assertEquals(expected.nachname, actual.nachname)
                assertEquals(expected.anzeigename, actual.anzeigename); assertEquals(expected.vcardName, actual.vcardName)
                assertEquals(expected.geburtstag, actual.geburtstag); assertEquals(expected.jubilaeum, actual.jubilaeum)
                val changed = adapter.mischen(created.rawContactId, expected.copy(jubilaeum = "--12-31"))!!.daten
                assertEquals(expected.geburtstag, changed.geburtstag); assertEquals("--12-31", changed.jubilaeum)
            }
            assertEquals(2, adapter.snapshot().kontakte.size)
            val operation = "native-create-${UUID.randomUUID()}"
            val owned = KontaktDaten(vorname = "Owned", anzeigename = "Owned",
                vcardName = listOf("N:;Owned;;;", "FN:Owned"),
                emailEintraege = listOf(KontaktWert("arbeit", "fixture@example.invalid")),
                anschriften = listOf(KontaktAnschrift("arbeit", strasse = "Fixture street")))
            val created = adapter.anlegen(owned, operation)
            ids += created.rawContactId
            assertEquals(created.rawContactId, adapter.anlegen(owned, operation).rawContactId)
            assertEquals("arbeit", adapter.liesRaw(created.rawContactId)!!.daten.emailEintraege.single().art)
            assertEquals("arbeit", adapter.liesRaw(created.rawContactId)!!.daten.anschriften.single().art)
            val planned = adapter.geplanterStand(owned, "create", operation)
            assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT,
                adapter.wiederherstellen(planned, false, "undo-$operation"))
            assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT,
                adapter.wiederherstellen(planned, false, "undo-$operation"))
            assertEquals(2, adapter.snapshot().kontakte.size)
        } finally {
            val uri = ContactsContract.RawContacts.CONTENT_URI.buildUpon()
                .appendQueryParameter(ContactsContract.CALLER_IS_SYNCADAPTER, "true").build()
            ids.forEach { id -> context.contentResolver.delete(uri, "_id=? AND account_name=? AND account_type=?",
                arrayOf(id.toString(), account.name, account.type)) }
            manager.removeAccountExplicitly(account)
        }
    }

    @Test fun safAutomaticBackup() {
        AndroidAutoSicherung.hole(context).passwortSichern("native-backup-fixture".toCharArray())
        val folder = "MagnolieNativeValidation-${UUID.randomUUID()}"
        fun shell(command: String) = android.os.ParcelFileDescriptor.AutoCloseInputStream(
            instrumentation.uiAutomation.executeShellCommand(command)).use { it.readBytes().decodeToString().trim() }
        assertEquals("/sdcard/Documents", shell("ls -d /sdcard/Documents"))
        shell("mkdir /sdcard/Documents/$folder")
        assertEquals("/sdcard/Documents/$folder", shell("ls -d /sdcard/Documents/$folder"))
        val prefs = context.getSharedPreferences("native_validation", 0)
        prefs.edit().remove("saf_uri").commit()
        val image = android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)
        image.eraseColor(android.graphics.Color.rgb(72, 110, 50))
        val png = java.io.ByteArrayOutputStream().also { image.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        image.recycle()
        val photo = "data:image/png;base64," + java.util.Base64.getEncoder().encodeToString(png)
        val contact = KontaktDaten(nachname = "Van Dame", anzeigename = "Van Dame", geburtstag = "--02-29",
            jubilaeum = "--06-07", foto = photo, vcardName = listOf("N:Van Dame;;;;", "FN:Van Dame"),
            telefone = listOf(KontaktWert("mobil", "+49301234567")))
        val book = storage.legeNotizbuchAn("Native SAF fixture")
        storage.setzeNotiz(Notiz("saf-contact", "Van Dame", Kanonisch.text(KontaktSync.inhalt(
            KontaktNachricht("fixture-contact", 1, "fixture", 1700000000000, contact, 2))),
            html = "<p>Yearless fixture --02-29</p>", notizbuchId = book.id, symbol = Symbol.PERSON,
            angelegt = 1700000000000, geaendert = 1700000000100,
            anhaenge = listOf(Anhang("saf-photo", "fixture.png", "image", photo))))
        storage.setzeNotiz(Notiz("saf-given", "Anna Maria", "Given name only: Anna Maria; family name empty; --12-31",
            notizbuchId = book.id, angelegt = 1700000000001, geaendert = 1700000000200))
        storage.setzeAufgabe(Aufgabe("saf-parent", "Parent", notiz = "Parent details", uid = "saf-parent-uid",
            faellig = "2099-12-30", prio = 1, erinnern = true, vorlaufTage = 3, erinnerungsMinute = 517,
            angelegt = 1700000000000, geaendert = 1700000000300))
        storage.setzeAufgabe(Aufgabe("saf-child", "Child", notiz = "Child details", uid = "saf-child-uid",
            elternUid = "saf-parent-uid", erledigt = true, prio = 3, reihenfolge = 0,
            angelegt = 1700000000000, geaendert = 1700000000400))
        storage.setzeNotiz(Notiz("saf-trash", "Trash fixture", "Retain trash content", anhaenge = listOf(
            Anhang("saf-trash-photo", "trash.png", "image", photo))))
        storage.loescheNotiz("saf-trash")
        val expected = storage.bestand.value
        File(context.filesDir, "native-saf-expected.json").writeText(Ablage.json.encodeToString(Bestand.serializer(), expected))
        instrumentation.runOnMainSync {
            context.startActivity(Intent().setClassName(context.packageName,
                "io.gitlab.maik3531.magnolienotes.ValidationFolderActivity")
                .putExtra("folder", folder).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        if (instrumentation.hostPicker) {
            val end = System.currentTimeMillis() + 180_000
            while (!prefs.contains("saf_uri") && System.currentTimeMillis() < end) {
                dumpSafHierarchy(folder)
                Thread.sleep(500)
            }
            assertTrue("Explicit system-picker approval is required", prefs.contains("saf_uri"))
        } else {
        waitFor("SAF current-folder breadcrumb must match fixture") { nodes().any {
            it.viewIdResourceName == "com.google.android.documentsui:id/breadcrumb_text" && it.text?.toString() == folder && it.isEnabled } }
        fun confirm(label: String) {
            waitFor("SAF observed $label button") { nodes().any { it.viewIdResourceName == "android:id/button1" &&
                it.text?.toString().equals(label, true) && it.isEnabled } }
            val button = nodes().single { it.viewIdResourceName == "android:id/button1" && it.text?.toString().equals(label, true) }
            val rect = android.graphics.Rect().also(button::getBoundsInScreen)
            shell("input tap ${rect.centerX()} ${rect.top + rect.height() / 3}")
        }
        confirm("USE THIS FOLDER")
        waitFor("SAF grant dialog must name fixture") { nodes().any { it.text?.contains(folder) == true } &&
            nodes().any { it.viewIdResourceName == "android:id/button1" && it.text?.toString().equals("ALLOW", true) } }
        confirm("ALLOW")
        waitFor("SAF result must be persisted") { prefs.contains("saf_uri") }
        }
        val uri = android.net.Uri.parse(prefs.getString("saf_uri", null))
        assertEquals("primary:Documents/$folder", android.provider.DocumentsContract.getTreeDocumentId(uri))
        val automatic = AndroidAutoSicherung.hole(context)
        val tree = androidx.documentfile.provider.DocumentFile.fromTreeUri(context, uri)!!
        assertTrue(context.contentResolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission && it.isWritePermission })
            automatic.aktiviertSetzen(true)
            assertTrue(automatic.zustand.value.aktiviert)
            awaitPeriodicBackup(automatic)
            android.util.Log.i("MagnolieNativeValidation", "Backup status: ${automatic.zustand.value.status}")
            assertTrue(automatic.zustand.value.status in setOf(AutoSicherungsStatus.ERFOLG, AutoSicherungsStatus.ERFOLG_AUFBEWAHRUNG_FEHLER))
            val files = tree.listFiles()
            assertTrue(files.isNotEmpty())
            assertTrue(files.all { it.name!!.startsWith("magnolie-notes-auto-") })
            val bytes = context.contentResolver.openInputStream(files.first().uri)!!.use { it.readBytes() }
            val password = "native-backup-fixture".toCharArray()
            try {
                val checked = PortableArchiv.pruefen(bytes, password)
                val restored = Ablage.json.decodeFromString(Bestand.serializer(), checked.bestandJson)
                assertEquals(expected, restored)
                val restoredContact = KontaktSync.lies(Kanonisch.json.parseToJsonElement(
                    restored.notizen.single { it.id == "saf-contact" }.text).jsonObject)!!.kontakt
                assertEquals(contact, restoredContact)
                assertEquals("saf-parent-uid", restored.aufgaben.single { it.id == "saf-child" }.elternUid)
                assertEquals(photo, restored.notizen.single { it.id == "saf-contact" }.anhaenge.single().daten)
                assertFalse(bytes.toString(Charsets.ISO_8859_1).contains("Van Dame"))
                storage.sichereNotiz(storage.notiz("saf-given")!!.copy(text = "Changed before SAF restore"))
                assertTrue(io.gitlab.maik3531.magnolienotes.journal.AndroidJournal.hole(context)
                    .restorePortable(checked, "native-saf-restore-${UUID.randomUUID()}"))
                assertEquals(expected, storage.bestand.value)
            } finally { bytes.fill(0); password.fill('\u0000') }
        automatic.aktiviertSetzen(false)
        prefs.edit().putInt("saf_seed_pid", Process.myPid()).putInt("saf_files_before_restart", tree.listFiles().size).commit()
    }

    private fun dumpSafHierarchy(folder: String) {
        val serializer = android.util.Xml.newSerializer()
        java.io.FileOutputStream(File(context.cacheDir, "saf-hierarchy.xml")).use { output ->
            serializer.setOutput(output, "UTF-8"); serializer.startDocument("UTF-8", true)
            serializer.startTag(null, "hierarchy")
            serializer.attribute(null, "fixture", folder)
            nodes().forEach { node ->
                val bounds = android.graphics.Rect().also(node::getBoundsInScreen)
                serializer.startTag(null, "node")
                serializer.attribute(null, "package", node.packageName?.toString().orEmpty())
                serializer.attribute(null, "id", node.viewIdResourceName.orEmpty())
                serializer.attribute(null, "text", node.text?.toString().orEmpty())
                serializer.attribute(null, "description", node.contentDescription?.toString().orEmpty())
                serializer.attribute(null, "clickable", node.isClickable.toString())
                serializer.attribute(null, "enabled", node.isEnabled.toString())
                serializer.attribute(null, "bounds", bounds.flattenToString())
                serializer.endTag(null, "node")
            }
            serializer.endTag(null, "hierarchy"); serializer.endDocument()
        }
    }

    @Test fun safBackupAfterRestart() {
        val prefs = context.getSharedPreferences("native_validation", 0)
        assertNotEquals(prefs.getInt("saf_seed_pid", -1), Process.myPid())
        val uri = android.net.Uri.parse(requireNotNull(prefs.getString("saf_uri", null)))
        assertTrue(android.provider.DocumentsContract.getTreeDocumentId(uri).matches(
            Regex("primary:Documents/MagnolieNativeValidation-[0-9a-f-]{36}")))
        assertTrue(context.contentResolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission && it.isWritePermission })
        val automatic = AndroidAutoSicherung.hole(context)
        val tree = androidx.documentfile.provider.DocumentFile.fromTreeUri(context, uri)!!
        try {
            automatic.aktiviertSetzen(true)
            awaitPeriodicBackup(automatic)
            assertTrue(tree.listFiles().size > prefs.getInt("saf_files_before_restart", 0))
            val expected = Ablage.json.decodeFromString(Bestand.serializer(), File(context.filesDir, "native-saf-expected.json").readText())
            val latest = tree.listFiles().maxBy { it.lastModified() }
            val bytes = context.contentResolver.openInputStream(latest.uri)!!.use { it.readBytes() }
            val password = "native-backup-fixture".toCharArray()
            try { assertEquals(expected, Ablage.json.decodeFromString(Bestand.serializer(),
                PortableArchiv.pruefen(bytes, password).bestandJson)) } finally { bytes.fill(0); password.fill('\u0000') }
        } finally {
            automatic.aktiviertSetzen(false)
            androidx.work.WorkManager.getInstance(context).cancelUniqueWork(AndroidAutoSicherung.TEST_WORK).result.get()
            androidx.work.WorkManager.getInstance(context).cancelUniqueWork(AndroidAutoSicherung.PERIODIC_WORK).result.get()
            tree.listFiles().filter { it.name?.startsWith("magnolie-notes-auto-") == true }.forEach { assertTrue(it.delete()) }
            assertTrue(tree.delete())
        }
    }

    private fun awaitPeriodicBackup(automatic: AndroidAutoSicherung) {
        val end = System.currentTimeMillis() + 45_000
        while (System.currentTimeMillis() < end) {
            val now = System.currentTimeMillis()
            val jobs = androidx.work.WorkManager.getInstance(context)
                .getWorkInfosForUniqueWork(AndroidAutoSicherung.PERIODIC_WORK).get()
            if (automatic.zustand.value.status == AutoSicherungsStatus.ERFOLG && jobs.any {
                    it.state == androidx.work.WorkInfo.State.ENQUEUED &&
                        it.nextScheduleTimeMillis in (now + 3_600_000)..(now + 8 * 86_400_000L)
                }) {
                android.util.Log.i("MagnolieNativeValidation", "Periodic backup completed; next execution is scheduled")
                return
            }
            Thread.sleep(100)
        }
        fail("Periodic WorkManager backup must complete under real constraints")
    }

    @Test fun safProviderMetadata() {
        val uri = android.net.Uri.parse(requireNotNull(context.getSharedPreferences("native_validation", 0).getString("saf_uri", null)))
        assertTrue(android.provider.DocumentsContract.getTreeDocumentId(uri).matches(
            Regex("primary:Documents/MagnolieNativeValidation-[0-9a-f-]{36}")))
        val tree = androidx.documentfile.provider.DocumentFile.fromTreeUri(context, uri)!!
        val name = AutoSicherungsRegeln.name(System.currentTimeMillis())
        val file = tree.createFile(AutoSicherungsRegeln.MIME, name)!!
        try {
            android.util.Log.i("MagnolieNativeValidation", "SAF created name matches: ${file.name == name}; MIME: ${file.type}")
            assertEquals(name, file.name)
            assertEquals("application/octet-stream", file.type)
            assertTrue(AutoSicherungsRegeln.istEigen(SicherungsDokument(file.uri.toString(), file.name!!, file.type!!, file.lastModified())))
        } finally { assertTrue(file.delete()) }
    }

    @Test fun authenticatedUpgradeAndReplay() {
        fun identity(id: String) = Krypto.neuesSchluesselpaar().let {
            EigeneIdentitaet(id, id, Krypto.b64(it.second), Krypto.b64(it.first), 8737)
        }
        val a = identity("native-a"); val b = identity("native-b")
        val directory = File(context.filesDir, "native-auth-${UUID.randomUUID()}").apply { check(mkdirs()) }
        val scoped = object : ContextWrapper(context) {
            override fun getFilesDir() = directory
            override fun getApplicationContext(): Context = this
        }
        val alias = "native-pair-${UUID.randomUUID()}"
        try {
            val store = Ablage.fuerTest(scoped) { key(alias) }
            val peer = Partner(b.kennung, "Pinned", b.oeffentlich, "192.0.2.1", 12345,
                bestaetigt = true, vertraut = false, protokoll = "baum-1", zaehlerRaus = 21, zaehlerRein = 17,
                gesehen = listOf("seen"), kontaktSyncFassungen = listOf(1, 2))
            val (file, invite) = Paarung.erzeugeDatei(a, "127.0.0.1")
            store.setzeBaum(Baumzustand(kennung = a.kennung, name = a.name, geheim = a.geheim, oeffentlich = a.oeffentlich,
                dienstAn = true, partner = listOf(peer), einladungen = listOf(invite)))
            store.setzeAufgabe(Aufgabe("native-task", "Native", delegiertAn = b.kennung))
            val server = Server(Baumwerk.fuerTest(store, scoped))
            val start = Sitzung.baueStart(b, a.kennung, a.oeffentlich)
            val response = server.behandeln("/magnolie/v2/sitzung", start.nachricht, "127.0.0.1")
            assertEquals(200, response.first)
            val session = Sitzung.oeffneAntwort(b, a.kennung, a.oeffentlich, start, response.second)
            val request = Paarung.anfrage(file, b)
            val paired = server.behandeln("/magnolie/v2/paarung", request, "203.0.113.9")
            assertEquals(200, paired.first)
            Paarung.pruefeAntwort(file, request, paired.second)
            assertEquals(peer.copy(protokoll = "baum-fs1"), store.baum.value.partner.single())
            val before = store.baum.value
            assertEquals(200, server.behandeln("/magnolie/v2/paarung", request, "192.0.2.99").first)
            assertEquals(before, store.baum.value)
            val body = buildJsonObject {
                put("art", JsonPrimitive("stand")); put("id", JsonPrimitive("native-task"))
                put("erledigt", JsonPrimitive(true)); put("geaendert", JsonPrimitive(100))
            }
            val envelope = Sitzung.baueUmschlag(session, b.kennung, a.kennung, body, Krypto.b64(Krypto.zufallsbytes(16)))
            val delivered = server.behandeln("/magnolie/v2/nachricht", envelope, "127.0.0.1")
            assertEquals(200, delivered.first); assertTrue(Sitzung.pruefeQuittung(session, envelope, delivered.second))
            session.loeschen()
            val legacy = Baum1.baue(b, a.kennung, a.oeffentlich, body, 18)
            assertEquals(200, server.behandeln("/magnolie/v1/nachricht", legacy, "127.0.0.1").first)
            val restarted = Ablage.fuerTest(scoped) { key(alias) }
            val persisted = restarted.baum.value
            assertEquals(200, Server(Baumwerk.fuerTest(restarted, scoped)).behandeln("/magnolie/v1/nachricht", legacy, "203.0.113.9").first)
            assertEquals(persisted, restarted.baum.value)
            assertTrue(restarted.aufgabe("native-task")!!.erledigt)
        } finally {
            directory.deleteRecursively()
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
        }
    }

    private fun launch(): Activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    private fun waitFor(description: String, test: () -> Boolean) {
        android.util.Log.i("MagnolieNativeValidation", description)
        val end = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < end) {
            instrumentation.waitForIdleSync()
            if (test()) return
            Thread.sleep(100)
        }
        if (description.startsWith("SAF")) {
            android.util.Log.i("MagnolieNativeValidation", "SAF window: " + nodes().firstOrNull()?.packageName)
            nodes().filter { it.text?.startsWith("MagnolieNativeValidation") == true ||
                it.contentDescription?.startsWith("MagnolieNativeValidation") == true }.forEach {
                android.util.Log.i("MagnolieNativeValidation", "Fixture label: ${it.text} / ${it.contentDescription}")
            }
        }
        fail(description)
    }
    private fun nodes(): List<AccessibilityNodeInfo> {
        val root = instrumentation.uiAutomation.rootInActiveWindow ?: return emptyList()
        val result = mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            result += node
            repeat(node.childCount) { node.getChild(it)?.let(::visit) }
        }
        visit(root); return result
    }
    private fun typeBody(text: String) {
        waitFor("editable fields must be accessible") { nodes().count { it.isEditable } >= 2 }
        val field = nodes().filter { it.isEditable }[1]
        assertTrue(field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }))
        waitFor("text input must reach the draft") { storage.entwurf.value.notiz?.text == text || storage.entwurf.value.aufgabe?.notiz == text }
    }
    private fun actionForLabel(label: String): AccessibilityNodeInfo? {
        // The Android bridge can expose a Material label as a descendant of its actionable surface.
        for (node in nodes().filter { it.text?.toString().equals(label, true) ||
                it.contentDescription?.toString().equals(label, true) }) {
            var current: AccessibilityNodeInfo? = node
            while (current != null) {
                if (current.isClickable && current.isEnabled) return current
                current = current.parent
            }
        }
        return null
    }
    private fun tapLabel(label: String) {
        val node = nodes().first { it.text?.toString().equals(label, true) ||
            it.contentDescription?.toString().equals(label, true) }
        val bounds = android.graphics.Rect().also(node::getBoundsInScreen)
        check(!bounds.isEmpty)
        android.util.Log.i("MagnolieNativeValidation", "Tap fixture control: $label $bounds")
        val now = android.os.SystemClock.uptimeMillis()
        for (action in listOf(android.view.MotionEvent.ACTION_DOWN, android.view.MotionEvent.ACTION_UP)) {
            val event = android.view.MotionEvent.obtain(now, android.os.SystemClock.uptimeMillis(), action,
                bounds.exactCenterX(), bounds.exactCenterY(), 0)
            event.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            try { assertTrue(instrumentation.uiAutomation.injectInputEvent(event, true)) } finally { event.recycle() }
            if (action == android.view.MotionEvent.ACTION_DOWN) Thread.sleep(80)
        }
    }
    private fun enterSelection() {
        // DocumentsUI may first focus a directory for keyboard/indirect-pointer navigation.
        for (action in listOf(KeyEvent.ACTION_DOWN, KeyEvent.ACTION_UP)) {
            val event = KeyEvent(action, KeyEvent.KEYCODE_ENTER)
            event.source = android.view.InputDevice.SOURCE_KEYBOARD
            assertTrue(instrumentation.uiAutomation.injectInputEvent(event, true))
        }
    }
    @Test fun editorBackSaves() {
        storage.setzeNotizEntwurf(Notiz("native-back", titel = "Native back"))
        val activity = launch()
        typeBody("Native back content")
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        Thread.sleep(300)
        if (storage.entwurf.value.notiz != null) instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        waitFor("system Back must save and close") { storage.notiz("native-back")?.text == "Native back content" && storage.entwurf.value.notiz == null }
        instrumentation.runOnMainSync { activity.finish() }
        storage.setzeAufgabenEntwurf(Aufgabe("native-task-back", titel = "Native task"))
        val taskActivity = launch()
        typeBody("Native task content")
        File(context.cacheDir, "native-task-nodes.txt").writeText(nodes().joinToString("\n") {
            "${it.className} clickable=${it.isClickable} description=${it.contentDescription}"
        })
        java.io.FileOutputStream(File(context.cacheDir, "native-task-screen.png")).use {
            instrumentation.uiAutomation.takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)
        }
        val back = context.getString(R.string.zurueck)
        waitFor("toolbar Back must be accessible") { actionForLabel(back) != null }
        assertTrue(actionForLabel(back)!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        waitFor("toolbar Back must save and close") { storage.aufgabe("native-task-back")?.notiz == "Native task content" && storage.entwurf.value.aufgabe == null }
        instrumentation.runOnMainSync { taskActivity.finish() }
    }

    @Test fun seedDraftAndRotate() {
        storage.setzeNotizEntwurf(Notiz("native-process-draft", titel = "Native draft"))
        val activity = launch()
        typeBody("Native draft survives rotation and process death")
        instrumentation.runOnMainSync { activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE }
        waitFor("landscape recreation retains editor text") {
            context.resources.configuration.orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE &&
                nodes().any { it.isEditable && it.text?.toString() == "Native draft survives rotation and process death" }
        }
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_HOME)
        waitFor("lifecycle flush must create encrypted draft") { File(context.filesDir, "entwurf.json").exists() }
        assertTrue(context.getSharedPreferences("native_validation", 0).edit().putInt("seed_pid", Process.myPid()).commit())
    }

    @Test fun verifyDraftAfterProcessDeath() {
        assertNotEquals(context.getSharedPreferences("native_validation", 0).getInt("seed_pid", -1), Process.myPid())
        assertEquals("Native draft survives rotation and process death", storage.entwurf.value.notiz?.text)
        val activity = launch()
        waitFor("restarted editor displays recovered draft") { nodes().any { it.isEditable && it.text?.toString() == "Native draft survives rotation and process death" } }
        assertTrue(AndroidAutoSicherung.hole(context).zustand.value.passwortGesichert)
        instrumentation.runOnMainSync { activity.finish() }
    }
}
