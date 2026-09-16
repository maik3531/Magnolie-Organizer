"""Public inventory of the standalone, single-DEB KDE source recipe."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("magnolie_kde_profiles",
    Path(__file__).resolve().parents[1] / "native/akonadi-helper/profiles.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
PROFILES = _module.PROFILES
artifacts = _module.artifacts
