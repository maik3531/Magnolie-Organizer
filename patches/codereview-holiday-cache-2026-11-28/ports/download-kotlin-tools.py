#!/usr/bin/env python3
"""Fetch the declared JVM toolchain into a disposable cache; no system changes."""
import concurrent.futures, hashlib, json, pathlib, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
CACHE = ROOT / "compiler-cache"
CACHE.mkdir(exist_ok=True)
ARTIFACTS = [
    ("org.jetbrains.kotlin", "kotlin-compiler-embeddable", "2.4.21"),
    ("org.jetbrains.kotlin", "kotlin-build-tools-api", "2.4.21"),
    ("org.jetbrains.kotlin", "kotlin-stdlib", "2.4.21"),
    ("org.jetbrains.kotlin", "kotlin-script-runtime", "2.4.21"),
    ("org.jetbrains.kotlin", "kotlin-reflect", "1.6.10"),
    ("org.jetbrains.kotlin", "kotlin-daemon-embeddable", "2.4.21"),
    ("org.jetbrains.kotlinx", "kotlinx-coroutines-core-jvm", "1.8.0"),
    ("org.jetbrains", "annotations", "13.0"),
    ("com.squareup.okhttp3", "okhttp", "4.12.0"),
    ("com.squareup.okio", "okio-jvm", "3.6.0"),
    ("org.threeten", "threetenbp", "1.7.5"),
    ("org.json", "json", "20240303"),
    ("junit", "junit", "4.13.2"),
    ("org.hamcrest", "hamcrest-core", "1.3"),
]

def fetch(artifact):
    group, name, version = artifact
    filename = f"{name}-{version}.jar"
    url = f"https://repo.maven.apache.org/maven2/{group.replace('.', '/')}/{name}/{version}/{filename}"
    path = CACHE / filename
    if not path.exists():
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read()
        path.write_bytes(data)
    data = path.read_bytes()
    if name == "threetenbp":
        assert hashlib.sha256(data).hexdigest() == "58c5593452f871ebf736dfda3bf8f3bc0de4e92cec61bc19c8ad81f9dfb70d72"
    return {"file": filename, "url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    records = list(executor.map(fetch, ARTIFACTS))
(ROOT / "toolchain-manifest.json").write_text(json.dumps(records, indent=2) + "\n")
print(f"Downloaded and hashed {len(records)} declared/compiler dependency artifacts ({sum(x['bytes'] for x in records)} bytes).")
