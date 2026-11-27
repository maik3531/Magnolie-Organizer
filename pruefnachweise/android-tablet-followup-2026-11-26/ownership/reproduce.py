#!/usr/bin/env python3
"""Reproduce the #463 host-policy and Android API compile-only checks.

This records the three commands actually used for the original proof. It starts
neither Gradle nor an emulator and is not the complete coordinated APK gate.
Use the existing verified dependency directory; this script downloads nothing.
The original directory was /workspace/scratch/acde70e8594b/tablet-build-dependencies.
Its maven-dependency-manifest.json and android-platform-manifest.json record the
upstream artifacts and hashes. They can be supplied from another location below.

Example (choose a fresh output directory to preserve the original evidence):
  python3 -B reproduce.py --repo /path/to/Magnolie-Organizer \
    --dependencies /path/to/tablet-build-dependencies --output /path/to/rerun-463
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--dependencies", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dependency-manifest", type=Path)
    parser.add_argument("--platform-manifest", type=Path)
    args = parser.parse_args()
    repo, deps, out = args.repo.resolve(), args.dependencies.resolve(), args.output.resolve()
    manifests = [args.dependency_manifest or deps / "maven-dependency-manifest.json",
                 args.platform_manifest or deps / "android-platform-manifest.json"]
    for item in json.loads(manifests[0].read_text()):
        if sha256(deps / item["file"]) != item["sha256"]:
            raise SystemExit("Dependency hash mismatch: " + item["file"])
    platform = json.loads(manifests[1].read_text())
    if sha256(deps / "android-37.2.jar") != platform["android_jar_sha256"]:
        raise SystemExit("Android API JAR hash mismatch")
    out.mkdir(parents=True, exist_ok=True)
    logs = ("jvm-compile.log", "junit.log", "android-adapter-compile.log", "receipt.json", "commands.json")
    if any((out / name).exists() for name in logs):
        raise SystemExit("Choose a fresh output directory; existing proof is not overwritten.")

    tablet = repo / "Magnolie-Organizer-Android-Tablet-Beta"
    policy = tablet / "tests/input/NativeWindowOwnershipPolicy.kt"
    test = tablet / "app/src/test/java/io/gitlab/maik3531/magnolietabletbeta/NativeWindowOwnershipPolicyTest.kt"
    adapter = tablet / "app/src/androidTest/java/io/gitlab/maik3531/magnolietabletbeta/NativeDomainAcceptance.kt"
    saved = tablet / "tests/input/SavedBookEpochExpectation.kt"
    sources = {str(path.relative_to(repo)): sha256(path) for path in (policy, test, adapter, saved)}
    compiler = ["java", "-Xmx512m", "-XX:ActiveProcessorCount=2", "-cp", str(deps / "*"),
                "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect", "-jvm-target", "17"]
    classpath = os.pathsep.join(str(deps / name) for name in (
        "kotlin-stdlib-2.4.21.jar", "annotations-13.0.jar", "junit-4.13.2.jar",
        "hamcrest-core-1.3.jar", "json-20240303.jar"))
    commands = [
        (logs[0], compiler + ["-classpath", classpath, "-d", str(out / "classes"), str(policy), str(test)]),
        (logs[1], ["java", "-Xmx128m", "-XX:ActiveProcessorCount=2", "-cp",
                   str(out / "classes") + os.pathsep + classpath, "org.junit.runner.JUnitCore",
                   "io.gitlab.maik3531.magnolietabletbeta.NativeWindowOwnershipPolicyTest"]),
        (logs[2], compiler + ["-classpath", classpath + os.pathsep + str(deps / "android-37.2.jar"),
                              "-d", str(out / "android-classes"), str(policy), str(adapter), str(saved)]),
    ]
    (out / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    junit_count = None
    for name, command in commands:
        print("$ " + shlex.join(command), flush=True)
        result = subprocess.run(command, cwd=repo, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=60)
        (out / name).write_text(result.stdout)
        print(result.stdout, end="", flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
        if name == "junit.log":
            match = re.search(r"OK \((\d+) tests\)", result.stdout)
            if not match:
                raise SystemExit("Missing successful JUnit result")
            junit_count = int(match[1])
    if sources != {name: sha256(repo / name) for name in sources}:
        raise SystemExit("Source changed during checks")
    receipt = dict(issue=463, kind="JVM policy execution and real Android API compile-only",
                   jvm_tests=junit_count, recorded_reference_truth_table_cases=432,
                   android_api="37.2", compiler="Kotlin 2.4.21", jvm_target=17,
                   nativeRuntimeTest=False, apkBuild=False, sources=sources,
                   dependencyManifests={str(path.resolve()): sha256(path) for path in manifests})
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
