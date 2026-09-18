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
        versionCode = 20018
        versionName = "2.0.18Beta"
        testInstrumentationRunner = "io.gitlab.maik3531.magnolietabletbeta.NativeTabletInstrumentation"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    signingConfigs.getByName("debug").storeFile = betaDebugKey
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
tasks.named("preBuild") { dependsOn(projection) }
tasks.matching { it.name == "validateSigningDebug" }.configureEach { dependsOn(createBetaDebugKey) }
tasks.configureEach {
    if (name.contains("Release")) doFirst { error("Tablet Beta is debug-only; production builds are not authorized.") }
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
    implementation("androidx.webkit:webkit:1.12.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
