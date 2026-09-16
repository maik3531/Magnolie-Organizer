"""Prepare a checksum-pinned Thunderbird test copy, never a system installation."""
import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(os.environ["CONTACT_INTEROP_HOME"]).resolve()
assert ROOT.is_relative_to(Path("/tmp/opencode")) and ROOT != Path("/tmp/opencode")
VERSION = "140.8.0esr"
SHA256 = "febd35bf465ad33ac5af0b2f939287cbafb82f5c9481200e49700896b36cbbfc"
URL = f"https://archive.mozilla.org/pub/thunderbird/releases/{VERSION}/linux-x86_64/en-US/thunderbird-{VERSION}.tar.xz"
ROOT.mkdir(parents=True, exist_ok=True)
archive = ROOT / f"thunderbird-{VERSION}.tar.xz"
if not archive.exists():
    with urllib.request.urlopen(URL, timeout=120) as response, archive.open("xb") as output:
        shutil.copyfileobj(response, output)
with archive.open("rb") as source:
    assert hashlib.file_digest(source, "sha256").hexdigest() == SHA256, "Thunderbird archive checksum mismatch"
if not (ROOT / "thunderbird/thunderbird").exists():
    with tarfile.open(archive) as tar:
        assert all(m.name == "thunderbird" or m.name.startswith("thunderbird/") for m in tar)
        tar.extractall(ROOT, filter="data")
for source, target in (("thunderbird-prefs.js", "defaults/pref/contact-interop.js"),
                       ("thunderbird.cfg", "thunderbird.cfg"),
                       ("thunderbird-policies.json", "distribution/policies.json")):
    (ROOT / "thunderbird" / target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name(source), ROOT / "thunderbird" / target)
print(f"Prepared isolated Thunderbird {VERSION}: {ROOT / 'thunderbird'}; SHA-256 {SHA256}")
