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
        ), foregroundPermissions.toSet())
        assertEquals(3, foregroundPermissions.size)
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
        assertEquals("specialUse", services[".zeit.ZeitDienst"])
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
        assertTrue("FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE" in baum)
        assertTrue("FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE" in telefon)
        assertFalse("FOREGROUND_SERVICE_TYPE_DATA_SYNC" in baum)
        assertFalse("FOREGROUND_SERVICE_TYPE_DATA_SYNC" in telefon)
    }
}
