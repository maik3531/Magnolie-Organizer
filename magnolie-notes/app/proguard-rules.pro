# Magnolie Notes

# Native file/Gallery components belong to every Notes APK, including F-Droid.
# Desktop build composition and branding keys must never strip this runtime.
# Keep its native entrypoints even while production acceptance is still closed;
# this does not advertise readiness or grant Android/media permissions.
-keep class io.gitlab.maik3531.magnolienotes.telefon.NativeGallery** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.NativeFile** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.DeviceFile** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.DeviceTransferProtection** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.AndroidGallery** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.GalleryPhoto** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.PhotoSource** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.PhotoFolder** { *; }
-keep class io.gitlab.maik3531.magnolienotes.telefon.ProtectedPhoto** { *; }

# kotlinx.serialization braucht die generierten Serializer.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class io.gitlab.maik3531.magnolienotes.** {
    *** Companion;
}
-keepclasseswithmembers class io.gitlab.maik3531.magnolienotes.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class io.gitlab.maik3531.magnolienotes.**$$serializer { *; }

# BouncyCastle: nur die genutzten Low-Level-Klassen bleiben erhalten,
# die JCE-Provider-Registrierung wird nicht verwendet.
-keep class org.bouncycastle.crypto.agreement.X25519Agreement { *; }
-keep class org.bouncycastle.crypto.params.X25519* { *; }
-keep class org.bouncycastle.crypto.generators.HKDFBytesGenerator { *; }
-keep class org.bouncycastle.crypto.params.HKDFParameters { *; }
-dontwarn org.bouncycastle.**
-dontwarn javax.naming.**

# Release-Instrumentation laeuft in demselben Prozess wie die Ziel-APK. Die
# getrennt minimierte Test-APK muss deshalb dieselbe Kotlin-Laufzeit-ABI sehen.
-keep class kotlin.** { *; }
-keep class kotlinx.coroutines.** { *; }

# Die separat minimierte Release-Test-APK greift auf diese produktiven APIs zu.
# Namen/Signaturen bleiben gemeinsam, der Methodenrumpf wird weiterhin von R8 optimiert.
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.MagnolieApp { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.StartZustand** { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.Ablage { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.Ablage$Companion { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.WiederherstellungsPaarCommit { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.StartFehler** { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.Notiz { *; }
-keep,allowoptimization class io.gitlab.maik3531.magnolienotes.daten.Baumzustand { *; }
