#!/usr/bin/env python3
"""Package the static Magnolie website without publishing application sources.

Requires Python 3.9 or newer with only its standard library. The editable HTML,
CSS, JavaScript and media live at the repository root and also work on any
static web server.
"""

import argparse
import copy
from html.parser import HTMLParser
from pathlib import Path
import shutil
from urllib.parse import unquote, urlsplit
import zipfile

SOURCE_URL = "https://maik3531.github.io/Magnolie-Organizer"
FILES = ("index.html", ".nojekyll", "robots.txt", "sitemap.xml", "SOURCE-NOTICES.txt")
DIRECTORIES = ("assets", "de", "en", "intl", "media", "presse", "impressum", "datenschutz")
DOCUMENTS = ("docs/PRESSE.md",)


def correct_promotional_archive(path):
    """Fix #712 in the Pages artifact, keeping the existing Git ZIP unchanged."""
    prefix = "Magnolie-Werbepaket/"
    replacements = {
        prefix + "Texte-und-Bilder/quellen.txt": 1,
        prefix + "Texte-und-Bilder/verzeichniseintraege.txt": 2,
    }
    old = b"https://github.com/maik3531/Magnolie-Organizer/blob/main/LICENSE.md"
    new = b"https://github.com/maik3531/Magnolie-Organizer/blob/main/LICENSE"
    metadata = (
        "date_time", "compress_type", "comment", "extra", "create_system", "create_version",
        "extract_version", "reserved", "flag_bits", "volume", "internal_attr", "external_attr",
    )
    temporary = path.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(path) as original:
            names = original.namelist()
            if len(names) != len(set(names)) or not set(replacements).issubset(names):
                raise ValueError("Unexpected promotional archive entries; review the #712 input before publishing")
            entries = [(info, original.read(info)) for info in original.infolist()]
            comment = original.comment
        changed = 0
        for info, data in entries:
            if info.filename in replacements:
                # Count the exact targets, including an already corrected input.
                count = replacements[info.filename]
                corrected = data.replace(old, new)
                if corrected.splitlines().count(new) != count or corrected.count(new) != count:
                    raise ValueError(f"Unexpected license links in promotional archive: {info.filename}")
                changed += data.count(old)
            elif old in data:
                raise ValueError(f"Unexpected obsolete license link in promotional archive: {info.filename}")
        if not changed:
            return 0
        with zipfile.ZipFile(temporary, "w") as output:
            output.comment = comment
            for info, data in entries:
                output.writestr(copy.copy(info), data.replace(old, new) if info.filename in replacements else data)
        with zipfile.ZipFile(temporary) as output:
            if output.comment != comment or output.namelist() != names:
                raise ValueError("Promotional archive order or comment changed")
            for (before, data), after in zip(entries, output.infolist()):
                wanted = data.replace(old, new) if before.filename in replacements else data
                if output.read(after) != wanted or any(getattr(before, key) != getattr(after, key) for key in metadata):
                    raise ValueError(f"Promotional archive content or metadata changed: {before.filename}")
        temporary.replace(path)
        return changed
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise ValueError(f"Cannot prepare promotional archive: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def validate_sources(source):
    """Reject missing inputs and links before copying any website files."""
    for name in FILES + DOCUMENTS + DIRECTORIES:
        path = source / name
        if path.is_symlink() or path.resolve() != path:
            raise ValueError(f"Symbolic link in website sources: {name}")
        expected_directory = name in DIRECTORIES
        if not (path.is_dir() if expected_directory else path.is_file()):
            raise ValueError(f"Missing website {'directory' if expected_directory else 'file'}: {name}")
        entries = [path]
        if expected_directory:
            entries.extend(path.rglob("*"))
        for entry in entries:
            if entry.is_symlink() or entry.resolve() != entry:
                raise ValueError(f"Symbolic link in website sources: {entry.relative_to(source)}")
            if not entry.is_file() and not entry.is_dir():
                raise ValueError(f"Unsupported website source: {entry.relative_to(source)}")


class LocalLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for key in ("href", "src", "poster"):
            if attrs.get(key):
                self.links.append(attrs[key])


def validate(root):
    root = root.resolve()
    documents = {}
    for page in root.rglob("*.html"):
        parser = LocalLinks()
        text = page.read_text(encoding="utf-8")
        parser.feed(text)
        if "chatgpt.site" in text:
            raise ValueError(f"Old hosting dependency in {page.relative_to(root)}")
        documents[page.resolve()] = parser
    errors = []
    for page, parser in documents.items():
        for link in parser.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            if url.path.startswith("/"):
                errors.append(f"{page.relative_to(root)}: host-absolute path {link}")
                continue
            target = (page.parent / unquote(url.path)).resolve() if url.path else page
            if not target.is_relative_to(root):
                errors.append(f"{page.relative_to(root)}: link leaves website: {link}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{page.relative_to(root)}: missing {link}")
            elif url.fragment and target in documents and unquote(url.fragment) not in documents[target].ids:
                errors.append(f"{page.relative_to(root)}: missing anchor {link}")
    if errors:
        raise ValueError("\n".join(errors))
    return len(documents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("_site"))
    parser.add_argument("--base-url", default=SOURCE_URL + "/")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    destination = args.output.resolve()
    base_url = args.base_url.rstrip("/")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in ("https", "http") or not parsed_url.netloc or parsed_url.query or parsed_url.fragment:
        parser.error("--base-url must be an absolute HTTP(S) website URL")
    if args.output.is_symlink() or source.is_relative_to(destination):
        parser.error("--output must not be a symlink, the source root, or its parent")
    if any(destination.is_relative_to(source / name) for name in DIRECTORIES):
        parser.error("--output must be outside the copied website source directories")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        parser.error("--output must be an empty directory")
    try:
        validate_sources(source)
    except ValueError as error:
        parser.error(str(error))
    destination.mkdir(parents=True, exist_ok=True)
    for name in FILES + DOCUMENTS:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    for name in DIRECTORIES:
        shutil.copytree(source / name, destination / name)
    try:
        corrected_links = correct_promotional_archive(destination / "media/Magnolie-Werbepaket.zip")
    except ValueError as error:
        parser.error(str(error))
    for file in destination.rglob("*"):
        if file.is_file() and file.suffix in (".html", ".xml", ".txt", ".md"):
            text = file.read_text(encoding="utf-8")
            file.write_text(text.replace(SOURCE_URL, base_url), encoding="utf-8")
    pages = validate(destination)
    total = sum(file.stat().st_size for file in destination.rglob("*") if file.is_file())
    print(f"Validated {pages} HTML pages; corrected {corrected_links} promotional license links; "
          f"packaged {total:,} bytes for {base_url}/")


if __name__ == "__main__":
    main()
