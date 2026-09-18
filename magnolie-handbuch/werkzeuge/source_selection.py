"""Standalone source selector; the handbook ships a byte-identical copy."""

import os
from pathlib import Path
import re

PRIVATE_DIRS = {".git", ".private-testing", ".claude", ".idea", ".vscode",
                ".private", ".ssh", ".aws", ".azure", ".config", ".local", ".cache",
                ".pytest_cache", "__pycache__", "node_modules", ".gradle", ".kotlin",
                ".flatpak-builder", ".rpm-check", ".debhelper", "bau", "obj", "Ausgabe"}
SECRET = re.compile(r"\.(?:pem|key|pfx|p12|jks|keystore|secret|token)$|^\.env(?:\.|$)"
                    r"|^(?:settings\.local\.json|local\.properties|schluessel\.properties)$", re.I)
NOTE = re.compile(r"(?:REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|ANALYSE|PLAN|AUDIT).*\.md$", re.I)
ARCHIVE = re.compile(r"\.(?:tar(?:\.[a-z0-9]+)?|zip|rpm|deb|dsc|buildinfo|changes|AppImage|flatpak|apk|aab|exe|dll|msi|iso|qcow2|img|raw|pyc|pdb|mo)$", re.I)
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\r?\n")


def private_path(relative):
    return any(part in PRIVATE_DIRS or part.startswith((".private-", ".release-staging-",
               ".magnolie-desktop-", ".installer-", "obj-")) or
               ".rollback" in part for part in relative.parts) or \
        relative.name == "an-claude.md" or bool(NOTE.search(relative.name))


def source_files(root):
    root = Path(root).resolve()
    windows = (root / "Directory.Build.props").is_file()
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(name for name in dirs if not private_path((base / name).relative_to(root))
                         and not (name == "build" and not (windows and base == root))
                         and not (windows and (name.casefold() == "bin" or
                                  base == root and name in {"handbuch", "handbook-windows-i18n"}))
                         and not (not windows and base == root and name in {"locale", "klang"})
                         and not (base.name == "debian" and name.startswith("magnolie-")))
        for name in dirs:
            if (base / name).is_symlink():
                raise ValueError("Source directory symlink is not permitted")
        for name in sorted(files):
            path = base / name
            relative = path.relative_to(root)
            if private_path(relative) or ARCHIVE.search(name) or name.endswith("~") or \
                    "PRUEFSUMMEN" in name or name.startswith(".magnolie-") or \
                    (base.name == "debian" and (name in {"files", "debhelper-build-stamp"} or name.endswith(".substvars"))):
                continue
            if windows and (name.endswith((".exe", ".exe.build.json", "-provenance.json")) or
                            (relative.parts[0] == "vm" and path.suffix.lower() in {".png", ".ppm", ".iso", ".img", ".qcow2"})):
                continue
            if SECRET.search(name) or name == "build-config.json":
                raise ValueError("Secret or build configuration in source selection")
            if path.is_symlink() or not path.is_file():
                raise ValueError("Non-regular source input")
            data = path.read_bytes()
            contributor = os.environ.get("MAGNOLIE_CONTRIBUTOR_HASH", "")
            if PRIVATE_KEY.search(data) or (re.fullmatch(r"[0-9a-fA-F]{64}", contributor) and
                    contributor != "0" * 64 and contributor.lower().encode() in data.lower()):
                raise ValueError("Private material in source input")
            yield relative, path


if __name__ == "__main__":
    import sys
    # A NUL-delimited allowlist for tar --null --verbatim-files-from --no-recursion.
    files = list(source_files(sys.argv[1]))
    for relative, _ in files:
        sys.stdout.buffer.write(os.fsencode(relative) + b"\0")
