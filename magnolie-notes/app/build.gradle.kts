import java.util.Properties
import java.security.KeyStore
import java.security.cert.X509Certificate
import javax.naming.ldap.LdapName
import org.gradle.api.tasks.testing.TestDescriptor
import org.gradle.api.tasks.testing.TestListener
import org.gradle.api.tasks.testing.TestResult

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

/*
 * Freigabeschluessel. Angelegt wird er einmalig mit keytool; die Zugangsdaten
 * gehoeren in app/schluessel.properties und niemals in die Versionsverwaltung.
 * Der offizielle signierte Bau verwendet diesen Schluessel. F-Droid baut mit
 * -PmagnolieFdroid=true eine unsignierte Release-APK und signiert sie separat.
 */
val fdroidBau = providers.gradleProperty("magnolieFdroid")
    .map { it.toBooleanStrict() }.getOrElse(false)
val privatePcVideoReceive = providers.gradleProperty("magnoliePrivatePcVideoReceive")
    .map { it.toBooleanStrict() }.getOrElse(false)
// #691: an explicit, unsigned, offline migration candidate; not release approval.
// Reuse the locked release configuration instead of adding new dependency variants.
val target37Validierung = providers.gradleProperty("magnolieTarget37Validation")
    .map { it.toBooleanStrict() }.getOrElse(false)
check(!target37Validierung || (fdroidBau && gradle.startParameter.isOffline)) {
    "#691: Target-37-Validierung erfordert --offline und -PmagnolieFdroid=true; keine Signier-/Installations-/Storefreigabe."
}
val target37Manifest = file("src/target37/AndroidManifest.xml")
val schluesselDatei = providers.environmentVariable("MAGNOLIE_SCHLUESSEL_PROPERTIES")
    .map { file(it) }
    .getOrElse(rootProject.file("app/schluessel.properties"))
val schluessel = Properties().apply {
    if (!fdroidBau && schluesselDatei.isFile) schluesselDatei.inputStream().use { strom -> load(strom) }
}
val erforderlicheSchluesselwerte = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
val schluesselVollstaendig = erforderlicheSchluesselwerte.all {
    !schluessel.getProperty(it).isNullOrBlank()
}
val produktionsSchluesselDatei = providers.environmentVariable("MAGNOLIE_KEYSTORE_FILE")
    .map { file(it) }
    .orNull ?: schluessel.getProperty("storeFile")
        ?.takeIf { it.isNotBlank() }
        ?.let(rootProject::file)
val eigenerSchluessel = !fdroidBau && schluesselDatei.isFile && schluesselVollstaendig &&
    produktionsSchluesselDatei?.isFile == true

// A complete JDK 21 is required; a runtime-only installation has no compiler.
// Keep the Android Java/Kotlin bytecode target at 17 for compatibility.
kotlin {
    jvmToolchain(21)
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

android {
    namespace = "io.gitlab.maik3531.magnolienotes"
    // #672 toolchain; #691 keeps the product target at 35 pending native acceptance.
    compileSdk {
        version = release(37) { minorApiLevel = 2 }
    }
    testBuildType = "release"

    defaultConfig {
        applicationId = "io.gitlab.maik3531.magnolienotes"
        minSdk = 26
        targetSdk = if (target37Validierung) 37 else 35
        versionCode = 21
        versionName = "1.0.21"
        buildConfigField("boolean", "FDROID_DISTRIBUTION", fdroidBau.toString())
        buildConfigField("boolean", "PRIVATE_PC_VIDEO_RECEIVE", privatePcVideoReceive.toString())
        testInstrumentationRunner = "io.gitlab.maik3531.magnolienotes.MagnolieTestRunner"
        resourceConfigurations += listOf(
            "ar", "be", "cs", "da", "de", "en", "es", "fr", "hi", "hsb",
            "it", "ja", "nb", "nl", "pl", "pt", "ru", "tr", "uk", "zh-rCN"
        )
    }

    signingConfigs {
        if (eigenerSchluessel) create("freigabe") {
            storeFile = produktionsSchluesselDatei
            storePassword = schluessel.getProperty("storePassword")
            keyAlias = schluessel.getProperty("keyAlias")
            keyPassword = schluessel.getProperty("keyPassword")
        }
    }

    buildTypes {
        debug {
            buildConfigField("boolean", "LEGACY_PLAINTEXT_FIXTURE", "false")
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.findByName("freigabe")
            if (target37Validierung) versionNameSuffix = "-api37-validation"
            buildConfigField("boolean", "LEGACY_PLAINTEXT_FIXTURE", "false")
        }
        create("fixture") {
            initWith(getByName("debug"))
            versionNameSuffix = "-plaintext-fixture"
            buildConfigField("boolean", "LEGACY_PLAINTEXT_FIXTURE", "true")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
        unitTests.isIncludeAndroidResources = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "/META-INF/versions/9/OSGI-INF/MANIFEST.MF"
        }
    }
}

androidComponents {
    finalizeDsl { extension ->
        check(extension.defaultConfig.minSdk == 26) {
            "#691: Die Target-Migration darf minSdk 26 nicht anheben."
        }
        check(extension.defaultConfig.targetSdk == if (target37Validierung) 37 else 35) {
            "#691: Produktziel bleibt 35; Ziel 37 ist nur als gekoppelter Validierungsstand zugelassen."
        }
        val release = extension.buildTypes.getByName("release")
        // The public AGP AndroidSourceFile API has a setter, not a srcFile getter.
        // Select the paired overlay here, immediately before DSL locking. Normal
        // release uses its usual source-set path and never the target-37 overlay.
        val releaseManifest = if (target37Validierung) target37Manifest
            else file("src/release/AndroidManifest.xml")
        extension.sourceSets.getByName("release").manifest.srcFile(releaseManifest)
        if (target37Validierung) {
            check(fdroidBau && release.signingConfig == null && !release.isDebuggable) {
                "#691: Der Target-37-Kandidat muss eine unsignierte Release-Variante bleiben."
            }
            check(target37Manifest.isFile) {
                "#691: Target 37 erfordert das zugehoerige LAN-/testOnly-Manifest."
            }
            check(release.versionNameSuffix == "-api37-validation") {
                "#691: Dem privaten Target-37-Pruefstand fehlt die Versionskennzeichnung."
            }
        }
    }
    beforeVariants(selector().all()) { variant ->
        // Do not accidentally create a debug-signed or plaintext target-37 APK.
        if (target37Validierung) {
            if (variant.buildType != "release") variant.enable = false
            // Device-test APKs have their own signing path. Native validation
            // needs a separate authorized stage; keep the host unit gate usable.
            variant.deviceTests.values.forEach { it.enable = false }
        }
    }
}

val pruefeReleaseSigningKonfiguration = tasks.register("pruefeReleaseSigningKonfiguration") {
    doLast {
        val signingConfig = android.buildTypes.getByName("release").signingConfig
        if (fdroidBau) {
            check(signingConfig == null) { "Der F-Droid-Bau muss ohne eingebundenen Signierschluessel erfolgen." }
            return@doLast
        }
        check(schluesselDatei.isFile && schluesselVollstaendig &&
            produktionsSchluesselDatei?.isFile == true) {
            "Release-Signing erfordert vollstaendige Properties und einen vorhandenen Produktionskeystore."
        }
        check(signingConfig != null && signingConfig.name == "freigabe" &&
            signingConfig !== android.signingConfigs.getByName("debug")) {
            "Release erfordert die Produktions-Signing-Konfiguration; null oder Debug-Signing ist verboten."
        }

        val istProduktionsschluessel = runCatching {
            val storePassword = requireNotNull(signingConfig.storePassword).toCharArray()
            val keyPassword = requireNotNull(signingConfig.keyPassword).toCharArray()
            val alias = requireNotNull(signingConfig.keyAlias)
            val keyStore = KeyStore.getInstance(KeyStore.getDefaultType())
            requireNotNull(signingConfig.storeFile).inputStream().use {
                keyStore.load(it, storePassword)
            }
            val zertifikat = keyStore.getCertificate(alias) as? X509Certificate
            keyStore.isKeyEntry(alias) && keyStore.getKey(alias, keyPassword) != null &&
                zertifikat != null && LdapName(zertifikat.subjectX500Principal.name).rdns.none {
                    it.type.equals("CN", ignoreCase = true) && it.value.toString() == "Android Debug"
                }
        }.getOrDefault(false)
        check(istProduktionsschluessel) {
            "Release-Keystore oder Schluessel ist ungueltig oder verwendet ein Android-Debugzertifikat."
        }
    }
}

tasks.configureEach {
    if (name.startsWith("generate") && name.endsWith("UnitTestConfig")) {
        // AGP 8 emits paths relative to app/, while the documented tests run from rootDir.
        doLast {
            outputs.files.asFileTree.matching { include("**/test_config.properties") }.forEach { config ->
                val values = Properties().apply { config.inputStream().use(::load) }
                listOf("android_merged_assets", "android_resource_apk", "android_merged_manifest").forEach { key ->
                    values.getProperty(key)?.let { values.setProperty(key, project.file(it).absolutePath) }
                }
                config.outputStream().use { values.store(it, "Absolute Android test resource paths") }
            }
        }
    }
    if (name in setOf("preReleaseBuild", "assembleRelease", "bundleRelease", "packageRelease")) {
        dependsOn(pruefeReleaseSigningKonfiguration)
    }
}

// Die Livesonde startet den echten Organizer-Dienst aus `werkzeuge/`;
// dafür laufen die Einheitstests im Projektstammverzeichnis.
tasks.withType<Test>().configureEach {
    workingDir = rootDir
    // Assert the selected variant's exact version, not a suffix-tolerant product version.
    systemProperty("magnolieTarget37Validation", target37Validierung.toString())
    // The shared native-hash oracle is outside the Kotlin source/resource tree.
    // Changing its vectors must invalidate the test result, not reuse an older
    // successful run as evidence for newly added interoperability cases.
    inputs.file(rootDir.resolve("../contracts/contact-original-return-hash-v1-vectors.json"))
        .withPathSensitivity(org.gradle.api.tasks.PathSensitivity.RELATIVE)
    // Robolectric/Compose retain SDK sandboxes across classes. Bound the
    // serial worker lifetime instead of accumulating them for the whole gate.
    maxParallelForks = 1
    maxHeapSize = "768m"
    forkEvery = 32
    val cross = providers.gradleProperty("magnolieCrossTests").orNull == "true"
    // These explicit tests launch external Python sources and a separately built
    // Windows test host; unchanged Kotlin classes are not evidence they still pass.
    if (cross) outputs.upToDateWhen { false }
    val crossClasses = listOf("*.TelefonWlanInvitationTest", "*.TelefonBluetoothSetupTest",
        "*.BaumReceiptInteropTest", "*.LiveprobeTest", "*.PersonalCustomTransportTest", "*.PersonalNoteModeTransportTest", "*.PersonalSyncActorTransportTest", "*.TimeSyncTransportTest", "*.ContactReadTransportTest", "*.DeveloperDiagnosticsTransportTest", "*.NativeMediaSupportSessionTest")
    filter {
        crossClasses.forEach { if (cross) includeTestsMatching(it) else excludeTestsMatching(it) }
    }
    doFirst {
        logger.lifecycle(if (cross) "Explicit cross-platform test gate: prerequisites are mandatory."
            else "Public unit gate; cross-platform classes run separately with -PmagnolieCrossTests=true: $crossClasses")
    }
    addTestListener(object : TestListener {
        override fun beforeSuite(suite: TestDescriptor) {}
        override fun beforeTest(testDescriptor: TestDescriptor) {}
        override fun afterTest(testDescriptor: TestDescriptor, result: TestResult) {}
        override fun afterSuite(suite: TestDescriptor, result: TestResult) {
            if (suite.parent == null && (result.skippedTestCount > 0 || result.testCount == 0L)) {
                throw GradleException("Declared test gate must run without skips and cannot be empty.")
            }
        }
    })
    testLogging {
        events("passed", "skipped", "failed")
        showStandardStreams = false
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.documentfile)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.bouncycastle)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.libphonenumber)
    debugImplementation(libs.androidx.ui.tooling)
    testImplementation(libs.junit)
    testImplementation(kotlin("test"))
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core)
    androidTestImplementation(libs.junit)
}
