"""Source-only KDE package presentation and legacy upgrade contract."""

import importlib.util
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kde_profiles", ROOT / "werkzeuge/kde_profiles.py")
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


def test_kde_downloads_match_target_artifacts_not_transition_packages():
    names = profiles.artifacts("2.0.18")
    for filename in ("README.md", "README.DE.md"):
        text = (ROOT.parent / filename).read_text()
        links = re.findall(r"\[([^]]+)\]\([^)]*/(magnolie-organizer-(?:kde|akonadi)[^/)]+)\)", text)
        assert len(links) == 2
        assert all("KDE" in label and "akonadi" not in name for label, name in links)
        name = "magnolie-organizer-kde_2.0.18_amd64.deb"
        assert name in names and name in dict((name, label) for label, name in links)
        assert "24.04" in text and "Linux Mint 22" in text
        assert "Debian 13" in text and "Fedora 42" in text
        assert "Ubuntu / Kubuntu" in text and "26.04" in text


def test_kde_descriptions_preserve_technical_upgrade_contract():
    control = (ROOT / "native/akonadi-helper/debian/control").read_text()
    assert control.count("\nPackage:") == 1
    assert "Description: KDE integration for Magnolie Organizer\n" in control
    assert "Akonadi" not in control.split("Description:", 1)[1]
    for relation in ("Provides", "Breaks", "Replaces"):
        assert f"{relation}: magnolie-organizer-akonadi (" in control
    assert "Suggests: akonadi-server, kdepim-runtime" in control
    assert "Recommends:" not in control
    assert "akonadi" not in next(line for line in control.splitlines() if line.startswith("Depends:"))
    organizer = (ROOT / "debian/control").read_text()
    assert "KDE integration uses existing KDE" in organizer
    assert "Akonadi bridge" not in organizer
    install = (ROOT / "native/akonadi-helper/debian/magnolie-organizer-kde.install").read_text()
    assert "magnolie-akonadi-helper" in install
