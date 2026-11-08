import java.security.MessageDigest
import java.util.zip.ZipFile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val projection = tasks.register<Exec>("projectDesktop") {
    workingDir(rootDir)
    commandLine(System.getenv("MAGNOLIE_JS_RUNTIME") ?: "bun", "tools/project-web.cjs")
    // Always reread the live canonical source, including concurrent UI corrections.
    outputs.upToDateWhen { false }
}
// Verify the resolved dependency, not merely the version string in this script.
// This intentionally targets the new TZDB backport only; it does not weaken any
// repository-wide dependency verification or accept replacement providers.
val verifyThreeTenRuntime = tasks.register("verifyThreeTenRuntime") {
    doLast {
        val candidates = configurations.getByName("debugRuntimeClasspath").resolvedConfiguration.resolvedArtifacts
            .filter { it.moduleVersion.id.group == "org.threeten" && it.moduleVersion.id.name == "threetenbp" }
        check(candidates.size == 1) { "Exactly one verified ThreeTenBP runtime artifact is required" }
        val artifact = candidates.single()
        check(artifact.moduleVersion.id.version == "1.7.5" && artifact.file.extension == "jar") {
            "Unexpected ThreeTenBP version or runtime artifact type"
        }
        fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        check(sha256(artifact.file.readBytes()) == "58c5593452f871ebf736dfda3bf8f3bc0de4e92cec61bc19c8ad81f9dfb70d72") {
            "Resolved ThreeTenBP runtime JAR does not match the verified published artifact"
        }
        ZipFile(artifact.file).use { archive ->
            val entry = archive.getEntry("org/threeten/bp/TZDB.dat") ?: error("ThreeTenBP runtime has no complete TZDB resource")
            check(sha256(archive.getInputStream(entry).use { it.readBytes() }) == "e28750a597bca9fe12fc927d6e8dd71cc71e9195a90e2bc7490265ffa10f1b12") {
                "ThreeTenBP TZDB resource does not match the verified full database"
            }
        }
    }
}

val betaDebugKey = rootProject.file(".debug-signing/beta-debug.keystore")
val createBetaDebugKey = tasks.register<Exec>("createBetaDebugKey") {
    onlyIf { !betaDebugKey.exists() }
    doFirst { betaDebugKey.parentFile.mkdirs() }
    commandLine(File(System.getProperty("java.home"), "bin/keytool"), "-genkeypair",
        "-keystore", betaDebugKey, "-storepass", "android", "-keypass", "android",
        "-alias", "androiddebugkey", "-dname", "CN=Android Debug,O=Magnolie Tablet Beta,C=DE",
        "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650")
}

android {
    namespace = "io.gitlab.maik3531.magnolietabletbeta"
    compileSdk = 35
    defaultConfig {
        applicationId = "io.gitlab.maik3531.magnolieorganizer.tablet.beta"
        minSdk = 26
        targetSdk = 35
        versionCode = 20030
        versionName = "2.0.30Beta"
        testInstrumentationRunner = "io.gitlab.maik3531.magnolietabletbeta.NativeTabletInstrumentation"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    signingConfigs.getByName("debug").storeFile = betaDebugKey
    sourceSets["androidTest"].assets.srcDir(rootProject.file("../port-adapters/tests"))
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/projection/assets"))
    sourceSets["main"].res.srcDir(layout.buildDirectory.dir("generated/projection/res"))
    testOptions { unitTests.isReturnDefaultValues = false }
}
kotlin {
    jvmToolchain(17)
    sourceSets.getByName("androidTest").kotlin.srcDir(rootProject.file("tests/input"))
    sourceSets.getByName("test").kotlin.srcDir(rootProject.file("tests/input"))
    // Kotlin has its own source filter; Android's Java filter does not constrain it.
    sourceSets.getByName("main").kotlin.apply {
        srcDir(rootProject.file("../magnolie-notes/app/src/main/java"))
        include("io/gitlab/maik3531/magnolietabletbeta/**",
            "io/gitlab/maik3531/magnolienotes/daten/DatenDateiKrypto.kt",
            "io/gitlab/maik3531/magnolienotes/daten/DateiDauerhaft.kt")
    }
}
tasks.named("preBuild") { dependsOn(projection, verifyThreeTenRuntime) }
tasks.matching { it.name == "validateSigningDebug" }.configureEach { dependsOn(createBetaDebugKey) }
tasks.configureEach {
    if (name.startsWith("compile") || name.startsWith("test")) dependsOn(verifyThreeTenRuntime)
    if (name.contains("Release")) doFirst { error("Development gate supports debug only; production workflow required.") }
}
tasks.withType<Test>().configureEach {
    systemProperty("tablet.root", rootDir.absolutePath)
    inputs.file(rootProject.file("artifacts/a3-editor-vectors.json"))
    maxHeapSize = "512m"
    maxParallelForks = 1
    jvmArgs("-XX:ActiveProcessorCount=2")
    testLogging { events("passed", "failed", "skipped") }
}
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.core:core:1.13.1")
    implementation("org.threeten:threetenbp:1.7.5")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
