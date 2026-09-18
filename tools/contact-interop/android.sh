#!/usr/bin/env bash
set -euo pipefail
: "${CONTACT_INTEROP_HOME:?isolated scratch directory required}"
: "${CONTACT_REPO:?canonical repository required}"
cache=/home/maik3531/.gradle/caches/modules-2/files-2.1
classes="$CONTACT_REPO/magnolie-notes/app/build/tmp/kotlin-classes/debug"
jars=("$cache"/org.jetbrains.kotlin/kotlin-compiler-embeddable/2.0.21/*/*.jar
  "$cache"/org.jetbrains.kotlin/kotlin-stdlib/2.0.21/*/kotlin-stdlib-2.0.21.jar
  "$cache"/org.jetbrains.kotlin/kotlin-reflect/1.6.10/*/*.jar
  "$cache"/org.jetbrains.kotlin/kotlin-script-runtime/2.0.21/*/*.jar
  "$cache"/org.jetbrains.kotlin/kotlin-daemon-embeddable/2.0.21/*/*.jar
  "$cache"/org.jetbrains.intellij.deps/trove4j/1.0.20200330/*/*.jar
  "$cache"/org.jetbrains/annotations/13.0/*/*.jar
  "$cache"/org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.7.3/*/*.jar
  "$cache"/org.jetbrains.kotlinx/kotlinx-serialization-core-jvm/1.7.3/*/*.jar
  "$cache"/org.jetbrains.kotlinx/kotlinx-serialization-json-jvm/1.7.3/*/*.jar
  "$cache"/org.bouncycastle/bcprov-jdk18on/1.78.1/*/*.jar)
classpath=$(IFS=:; printf '%s' "${jars[*]}")
java -Djava.io.tmpdir="$CONTACT_INTEROP_HOME" -Duser.home="$HOME" -cp "$classpath" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler \
  -no-stdlib -no-reflect -classpath "$classes:$classpath" -Xfriend-paths="$classes" \
  -d "$CONTACT_INTEROP_HOME/android-classes" "$CONTACT_REPO/tools/contact-interop/AndroidInterop.kt"
exec java -Djava.io.tmpdir="$CONTACT_INTEROP_HOME" -Duser.home="$HOME" \
  -cp "$CONTACT_INTEROP_HOME/android-classes:$classes:$classpath" AndroidInteropKt
