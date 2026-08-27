import java.util.Properties
import java.security.KeyStore
import java.security.cert.X509Certificate
import javax.naming.ldap.LdapName

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

/*
 * Freigabeschluessel. Angelegt wird er einmalig mit keytool; die Zugangsdaten
 * gehoeren in app/schluessel.properties und niemals in die Versionsverwaltung.
 * Ohne diesen Schluessel wird jeder Release-Build absichtlich abgewiesen.
 */
val schluesselDatei = providers.environmentVariable("MAGNOLIE_SCHLUESSEL_PROPERTIES")
    .map { file(it) }
    .getOrElse(rootProject.file("app/schluessel.properties"))
val schluessel = Properties().apply {
    if (schluesselDatei.isFile) schluesselDatei.inputStream().use { strom -> load(strom) }
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
val eigenerSchluessel = schluesselDatei.isFile && schluesselVollstaendig &&
    produktionsSchluesselDatei?.isFile == true

/*
 * Uebersetzt wird ausdruecklich gegen JDK 17.
 *
 * Ohne diese Festlegung nimmt Gradle die Java-Fassung, unter der es selbst
 * laeuft. Auf dem Baurechner ist das Java 21, und dort war nur die Laufzeit
 * ohne Compiler installiert - der Bau brach mit "does not provide the required
 * capabilities: [JAVA_COMPILER]" ab. Mit der Toolchain sucht Gradle sich das
 * passende JDK selbst; ein gesetztes JAVA_HOME ist dann nicht mehr noetig.
 */
kotlin {
    jvmToolchain(17)
}

android {
    namespace = "io.gitlab.maik3531.magnolienotes"
    compileSdk = 35
    testBuildType = "release"

    defaultConfig {
        applicationId = "io.gitlab.maik3531.magnolienotes"
        minSdk = 26
        targetSdk = 35
        versionCode = 7
        versionName = "1.0.7"
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

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "/META-INF/versions/9/OSGI-INF/MANIFEST.MF"
        }
    }
}

val pruefeReleaseSigningKonfiguration = tasks.register("pruefeReleaseSigningKonfiguration") {
    doLast {
        val signingConfig = android.buildTypes.getByName("release").signingConfig
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
    if (name in setOf("preReleaseBuild", "assembleRelease", "bundleRelease", "packageRelease")) {
        dependsOn(pruefeReleaseSigningKonfiguration)
    }
}

// Die Livesonde startet den echten Organizer-Dienst aus `werkzeuge/`;
// dafür laufen die Einheitstests im Projektstammverzeichnis.
tasks.withType<Test>().configureEach {
    workingDir = rootDir
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
    debugImplementation(libs.androidx.ui.tooling)
    testImplementation(libs.junit)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core)
    androidTestImplementation(libs.junit)
}
