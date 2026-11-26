buildscript {
    dependencies {
        // Use AGP's built-in Kotlin, aligned with the repository's Notes toolchain.
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.21")
    }
}

plugins {
    id("com.android.application") version "9.5.1" apply false
}
