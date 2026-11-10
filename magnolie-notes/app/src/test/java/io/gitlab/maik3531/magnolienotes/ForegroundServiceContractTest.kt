package io.gitlab.maik3531.magnolienotes

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.w3c.dom.Element

class ForegroundServiceContractTest {
    private val project = File(System.getProperty("user.dir")).let {
        if (it.resolve("app/src/main/AndroidManifest.xml").isFile) it.resolve("app") else it
    }

    @Test
    fun optionalWebcamHasNoExportedOrBootEntryAndDoesNotRequireCaptureHardware() {
        val document = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
            .newDocumentBuilder().parse(project.resolve("src/main/AndroidManifest.xml"))
        val android = "http://schemas.android.com/apk/res/android"
        val service = document.getElementsByTagName("service").let { nodes ->
            (0 until nodes.length).map { nodes.item(it) as Element }
                .single { it.getAttributeNS(android, "name") == ".telefon.PhoneWebcamCaptureService" }
        }
        assertEquals("false", service.getAttributeNS(android, "exported"))
        assertEquals(0, service.getElementsByTagName("intent-filter").length)
        val features = document.getElementsByTagName("uses-feature").let { nodes ->
            (0 until nodes.length).map { nodes.item(it) as Element }
                .associate { it.getAttributeNS(android, "name") to it.getAttributeNS(android, "required") }
        }
        for (name in listOf("camera", "camera.any", "camera.autofocus", "microphone")) {
            assertEquals("false", features["android.hardware.$name"])
        }
        val activity = project.resolve("src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        val early = activity.substringAfter("override fun onCreate").substringBefore("acceptGalleryPermissionIntent(intent)")
        assertTrue("PhoneWebcamForeground.register(it)" in early)
        assertEquals(4, Regex("phoneWebcamPermissionHost\\?\\.requestPending == true").findAll(early).count())
        for (slot in listOf("galleryPermissionHost", "galleryVideoPermissionHost", "galleryWriteConsentHost", "galleryPcWriteConsentHost")) {
            assertTrue("$slot?.requestPending == true" in early.substringBefore("galleryWriteConsentHost ="))
        }
        assertFalse("PhoneWebcamServiceStarts.start" in activity)
        assertFalse("PhoneWebcamForeground.request" in activity)
    }

    @Test
    fun permanentDeviceListenersDoNotUseTimedDataSyncServiceType() {
        val manifestFile = project.resolve("src/main/AndroidManifest.xml")
        val manifest = manifestFile.readText()
        val document = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
            .newDocumentBuilder().parse(manifestFile)
        val android = "http://schemas.android.com/apk/res/android"
        val permissions = document.getElementsByTagName("uses-permission").let { nodes ->
            (0 until nodes.length).map { (nodes.item(it) as Element).getAttributeNS(android, "name") }
        }
        val foregroundPermissions = permissions.filter { it.startsWith("android.permission.FOREGROUND_SERVICE") }
        assertEquals(setOf(
            "android.permission.FOREGROUND_SERVICE",
            "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
            "android.permission.FOREGROUND_SERVICE_LOCATION",
            "android.permission.FOREGROUND_SERVICE_CAMERA",
            "android.permission.FOREGROUND_SERVICE_MICROPHONE",
        ), foregroundPermissions.toSet())
        assertEquals(6, foregroundPermissions.size)
        assertEquals(1, permissions.count { it == "android.permission.CHANGE_NETWORK_STATE" })

        val services = document.getElementsByTagName("service").let { nodes ->
            (0 until nodes.length).associate {
                val service = nodes.item(it) as Element
                service.getAttributeNS(android, "name") to
                    service.getAttributeNS(android, "foregroundServiceType")
            }
        }
        assertEquals("connectedDevice", services[".baum.BaumDienst"])
        assertEquals("connectedDevice", services[".telefon.TelefonDienst"])
        assertEquals(setOf("camera", "microphone"), services[".telefon.PhoneWebcamCaptureService"]?.split('|')?.toSet())
        assertEquals(setOf("specialUse", "location"), services[".zeit.ZeitDienst"]?.split('|')?.toSet())
        val timeService = document.getElementsByTagName("service").let { nodes ->
            (0 until nodes.length).map { nodes.item(it) as Element }
                .single { it.getAttributeNS(android, "name") == ".zeit.ZeitDienst" }
        }
        assertEquals("false", timeService.getAttributeNS(android, "exported"))
        assertTrue(timeService.getElementsByTagName("property").let { nodes ->
            (0 until nodes.length).map { nodes.item(it) as Element }.any {
                it.getAttributeNS(android, "name") == "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE" &&
                    it.getAttributeNS(android, "value").isNotBlank()
            }
        })

        val baum = project.resolve(
            "src/main/java/io/gitlab/maik3531/magnolienotes/baum/BaumDienst.kt").readText()
        val telefon = project.resolve(
            "src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonDienst.kt").readText()

        assertFalse("foregroundServiceType=\"dataSync\"" in manifest)
        val gemeinsamerHinweis = project.resolve(
            "src/main/java/io/gitlab/maik3531/magnolienotes/VerbindungsHinweis.kt").readText()
        assertTrue("VerbindungsHinweis.Quelle.BAUM" in baum)
        assertTrue("VerbindungsHinweis.Quelle.TELEFON" in telefon)
        assertTrue("FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE" in gemeinsamerHinweis)
        assertFalse("FOREGROUND_SERVICE_TYPE_DATA_SYNC" in gemeinsamerHinweis)
        assertFalse("FOREGROUND_SERVICE_TYPE_DATA_SYNC" in baum)
        assertFalse("FOREGROUND_SERVICE_TYPE_DATA_SYNC" in telefon)
    }
}
