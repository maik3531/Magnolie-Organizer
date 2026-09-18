package io.gitlab.maik3531.magnolienotes

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import org.w3c.dom.Element

class LocalizationCompletenessTest {
    private val root = File(System.getProperty("user.dir").orEmpty())
    private val resources = File(root, "app/src/main/res")
    private val requiredLocales = setOf(
        "ar", "be", "cs", "da", "de", "en", "es", "fr", "hi", "hsb",
        "it", "ja", "nb", "nl", "pl", "pt", "ru", "tr", "uk", "zh-CN",
    )
    private val protectedTokens = listOf(
        "Magnolienbaum", "KDE Connect", "Magnolie Notes", "Bluetooth",
        "Android", "RemoteInput", "PendingIntent", "JSON", "PDF", "JPEG", "PNG",
        "WebP", "GIF", "HFP", "SMS",
    )
    private val englishEqualAllowlist = protectedTokens.toSet()
    private val staleEnglishSentences = setOf(
        "Encrypted local snapshots, never cloud backups.",
        "No snapshots.",
        "Restore “%1\$s”? A safety snapshot is created first.",
        "Delete this snapshot?",
        "Contact changed",
        "“%1\$s” changed since the snapshot. Overwrite only the selected bound contact?",
        "Overwrite selected contact",
        "Independent encrypted connection for device status, dial requests, and read-only notifications from exactly selected apps. It never uses Magnolienbaum pairings or permissions.",
        "Optional and off by default. Wi-Fi remains preferred. Pair the desktop in Android settings, then select the paired device here. This phone connection never uses the Magnolienbaum Bluetooth service.",
        "Bluetooth permission was not granted.",
        "First securely pair the phone connection over Wi-Fi.",
        "Read-only. Only message notifications from exactly selected apps are forwarded. Actions, replies, RemoteInput and PendingIntent are never transferred.",
        "Off by default. Opens only the system dialer for confirmation.",
        "No system dialer is available.",
        "Options are off by default and request only required permissions. Call audio is never sent over Magnolie.",
        "Permission not granted. The option remains off.",
        "Create or restore a separate password-encrypted archive of notes, notebooks, tasks, trash and attachments.",
        "Enter the archive password. Nothing is changed while the backup is checked.",
        "This replaces all current personal content. A local safety snapshot is created first; this device’s Magnolienbaum identity is preserved.",
        "The backup could not be opened. Check the file and password.",
    )
    private val placeholder = Regex("%(?:[1-9]\\d*\\$)?[-#+ 0,(]*\\d*(?:\\.\\d+)?[a-zA-Z%]")
    private val identifier = Regex(
        "https?://[^\\s\\\"'<>]+|\\.(?:magnolie|json|ics|vcf|ldif|csv|ods|pdf|jpe?g|png|webp|gif|deb|rpm|xml|contact|db)\\b",
    )

    private val pluralQuantities = mapOf(
        "ar" to setOf("zero", "one", "two", "few", "many", "other"),
        "be" to setOf("one", "few", "many", "other"),
        "cs" to setOf("one", "few", "many", "other"),
        "da" to setOf("one", "other"), "de" to setOf("one", "other"),
        "en" to setOf("one", "other"), "es" to setOf("one", "many", "other"),
        "fr" to setOf("one", "many", "other"), "hi" to setOf("one", "other"),
        "hsb" to setOf("one", "two", "few", "other"),
        "it" to setOf("one", "many", "other"), "ja" to setOf("other"),
        "nb" to setOf("one", "other"), "nl" to setOf("one", "other"),
        "pl" to setOf("one", "few", "many", "other"),
        "pt" to setOf("one", "many", "other"),
        "ru" to setOf("one", "few", "many", "other"),
        "tr" to setOf("one", "other"),
        "uk" to setOf("one", "few", "many", "other"), "zh-CN" to setOf("other"),
    )

    private data class Resource(val type: String, val name: String, val values: Map<String, String>)

    private fun readResources(file: File): Map<String, Resource> {
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = true
            setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
            setFeature("http://xml.org/sax/features/external-general-entities", false)
            setFeature("http://xml.org/sax/features/external-parameter-entities", false)
        }
        val document = factory.newDocumentBuilder().parse(file)
        val result = linkedMapOf<String, Resource>()
        val children = document.documentElement.childNodes
        for (index in 0 until children.length) {
            val element = children.item(index) as? Element ?: continue
            val name = element.getAttribute("name")
            if (name.isEmpty() || element.getAttribute("translatable") == "false") continue
            val values = if (element.tagName == "plurals") {
                val items = element.getElementsByTagName("item")
                val quantities = (0 until items.length).map { itemIndex ->
                    val item = items.item(itemIndex) as Element
                    item.getAttribute("quantity") to item.textContent.trim()
                }
                check(quantities.map { it.first }.toSet().size == quantities.size) {
                    "Duplicate plural quantity for $name in ${file.path}"
                }
                quantities.toMap()
            } else if (element.tagName == "string-array") {
                val items = element.getElementsByTagName("item")
                (0 until items.length).associate { it.toString() to items.item(it).textContent.trim() }
            } else {
                mapOf("value" to element.textContent.trim())
            }
            val key = "${element.tagName}:$name"
            check(result.put(key, Resource(element.tagName, name, values)) == null) {
                "Duplicate resource $key in ${file.path}"
            }
        }
        return result
    }

    private fun multiset(regex: Regex, text: String) =
        regex.findAll(text).map { it.value }.groupingBy { it }.eachCount()

    @Test
    fun everyDeclaredLocaleIsCompleteAndStructurallySafe() {
        val failures = mutableListOf<String>()
        val defaults = readResources(File(resources, "values/strings.xml"))
        defaults.values.filter { it.type == "plurals" }.forEach { resource ->
            if (resource.values.keys != pluralQuantities.getValue("en")) {
                failures += "en has wrong plural quantities for ${resource.name}: expected ${pluralQuantities.getValue("en")}, found ${resource.values.keys}"
            }
        }
        val localeDirectories = resources.listFiles().orEmpty()
            .filter { it.isDirectory && it.name.startsWith("values-") && File(it, "strings.xml").isFile }
            .associateBy {
                it.name.removePrefix("values-").replace("-r", "-")
            }
        if (requiredLocales - "en" != localeDirectories.keys) {
            failures += "locale directories differ: expected ${requiredLocales - "en"}, found ${localeDirectories.keys}"
        }

        for ((locale, directory) in localeDirectories) {
            val translations = readResources(File(directory, "strings.xml"))
            if (defaults.keys != translations.keys) {
                failures += "$locale key set differs: missing ${defaults.keys - translations.keys}, extra ${translations.keys - defaults.keys}"
            }
            for ((key, source) in defaults) {
                val translated = translations[key] ?: continue
                if (source.type != translated.type) failures += "$locale changes XML resource type for $key"
                if (source.type == "plurals" && translated.values.keys != pluralQuantities.getValue(locale)) {
                    failures += "$locale has wrong plural quantities for $key: expected ${pluralQuantities.getValue(locale)}, found ${translated.values.keys}"
                } else if (source.type != "plurals" && source.values.keys != translated.values.keys) {
                    failures += "$locale changes value positions for $key"
                }
                for ((position, value) in translated.values) {
                    val sourceValue = source.values[position] ?: source.values["other"] ?: continue
                    if (value.isBlank()) failures += "$locale has an empty translation for $key"
                    if (multiset(placeholder, sourceValue) != multiset(placeholder, value)) {
                        failures += "$locale changes placeholder positions/types for $key"
                    }
                    if (multiset(identifier, sourceValue) != multiset(identifier, value)) {
                        failures += "$locale changes technical identifiers for $key"
                    }
                    for (token in protectedTokens.filter(sourceValue::contains)) {
                        if (!value.contains(token)) failures += "$locale must preserve $token in $key"
                    }
                    val plainSource = placeholder.replace(sourceValue, "")
                    val sentenceLength = Regex("[A-Za-z]+(?:'[A-Za-z]+)?")
                        .findAll(plainSource).count() >= 4
                    if (value == sourceValue && sentenceLength && sourceValue !in englishEqualAllowlist) {
                        failures += "$locale contains the current English default for $key"
                    }
                    if (value in staleEnglishSentences) {
                        failures += "$locale contains a historical English fallback for $key: $value"
                    }
                }
            }
        }
        if (failures.isNotEmpty()) fail(failures.joinToString("\n"))
    }

    @Test
    fun localeDeclarationsMatchRequiredList() {
        val localeConfig = File(resources, "xml/locales_config.xml").readText()
        val configured = Regex("android:name=\"([^\"]+)\"").findAll(localeConfig)
            .map { it.groupValues[1] }.toSet()
        assertEquals(requiredLocales, configured)

        val gradle = File(root, "app/build.gradle.kts").readText()
        val block = Regex("resourceConfigurations \\+= listOf\\((.*?)\\)", RegexOption.DOT_MATCHES_ALL)
            .find(gradle)?.groupValues?.get(1).orEmpty()
        val packaged = Regex("\"([^\"]+)\"").findAll(block)
            .map { it.groupValues[1].replace("-r", "-") }.toSet()
        assertEquals(requiredLocales, packaged)
    }
}
