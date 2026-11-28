#!/usr/bin/env python3
"""Compile and run the actual pure-JVM HolidayService test, offline after dependency preparation."""
import argparse, hashlib, json, pathlib, subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--repo", type=pathlib.Path, required=True)
p.add_argument("--compiler-cache", type=pathlib.Path, required=True)
p.add_argument("--output", type=pathlib.Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
prefix = "Magnolie-Organizer-Android-Tablet-Beta/app/src/"
package = "java/io/gitlab/maik3531/magnolietabletbeta/"
sources = [prefix + "main/" + package + name for name in ("HolidayService.kt", "DAV.kt", "StandardBase64.kt")]
sources.append(prefix + "test/" + package + "HolidayServiceTest.kt")
jars = sorted(a.compiler_cache.glob("*.jar"))
classpath = ":".join(str(x.resolve()) for x in jars)
inputs = [a.repo / path for path in sources] + jars
def hashes():
    return {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in inputs}
before = hashes()
runtime = ["java", "-Xmx512m", "-XX:ActiveProcessorCount=2"]
output_jar = a.output / "holiday-tests.jar"
commands = [runtime + ["-cp", classpath, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect",
    "-jvm-target", "17", "-classpath", classpath, "-d", str(output_jar), *[str(a.repo / x) for x in sources]],
    runtime + ["-cp", str(output_jar) + ":" + classpath, "org.junit.runner.JUnitCore",
               "io.gitlab.maik3531.magnolietabletbeta.HolidayServiceTest"]]
results = []
for name, command in zip(("compile", "junit"), commands):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, text=True)
    (a.output / f"{name}.log").write_text(result.stdout)
    results.append({"name": name, "command": command, "returncode": result.returncode})
    print(f"{name}: {result.returncode}\n{result.stdout}", flush=True)
    if result.returncode:
        break
assert hashes() == before, "Input changed while the test was running"
(a.output / "receipt.json").write_text(json.dumps({"inputs": before, "results": results}, indent=2) + "\n")
raise SystemExit(results[-1]["returncode"])
