"""Mac-only context for projected pure codecs; no profile, account or file grants."""
import posixpath
from types import SimpleNamespace
import zoneinfo


_zone = None
_zone_name = None
_zones = frozenset()
_catalog = {}
_home_country = None
_language = None
phone_numbers = None


def configure(bundle, header, catalogs, registry):
    global _zone, _zone_name, _zones, _catalog, _home_country, _language, phone_numbers
    _zones = frozenset(registry)
    zoneinfo.reset_tzpath([str(bundle / "zones")])
    zoneinfo.ZoneInfo.clear_cache()
    _zone_name = header["timeZone"]
    _zone = zone_info(_zone_name)
    import phonenumbers
    phone_numbers = phonenumbers
    _home_country = header["homeCountry"]
    _language = header["language"]
    language = header["language"].replace("_", "-").lower()
    # Match the current desktop native catalog selection for Chinese tags;
    # regions/scripts do not create a new catalog or a system-locale lookup.
    if language == "zh" or language.startswith("zh-"):
        language = "zh-cn"
    _catalog = catalogs.get(language, catalogs.get(language.split("-", 1)[0], {}))


def zone_info(name):
    # No system-zoneinfo or optional tzdata-package fallback for unknown names.
    if not isinstance(name, str) or name not in _zones:
        raise ValueError("The calendar timezone is unavailable.")
    return zoneinfo.ZoneInfo(name)


def organizer_zone():
    if _zone is None:
        raise RuntimeError("Import context is not configured.")
    return _zone


def organizer_zone_name():
    if _zone_name is None:
        raise RuntimeError("Import context is not configured.")
    return _zone_name


def translate(message):
    return _catalog.get(message, message)


def deny_file_access(*_args, **_kwargs):
    raise PermissionError("The file import has no access to external files.")


# Only string operations are needed by the selected-file parsers. The desktop
# local-contact photo branch remains in the exact projected function, but cannot
# turn a file: value into a read capability even if accidentally called later.
read_only_os = SimpleNamespace(path=SimpleNamespace(
    basename=posixpath.basename, splitext=posixpath.splitext,
    isabs=posixpath.isabs, getsize=deny_file_access,
))


def regional_context():
    if _home_country is None:
        raise RuntimeError("Import context is not configured.")
    return _home_country, _language
