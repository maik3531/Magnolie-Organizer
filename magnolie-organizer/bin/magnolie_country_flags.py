"""Local decorative country flags; never normalize or overwrite address values."""
import os

from magnolie_phone_region import ISO_ALPHA2

CELL_WIDTH, CELL_HEIGHT = 64, 48
_atlases = {}
_flags = {}


def country_code(value, choices=(), translate=lambda text: text):
    text = str(value or "").strip()
    code = text.upper()
    if code in ISO_ALPHA2:
        return code
    folded = text.casefold()
    for candidate, name in choices:
        if candidate in ISO_ALPHA2 and folded in (name.casefold(), translate(name).casefold()):
            return candidate
    return ""


def country_cell(value):
    code = country_code(value)
    return ((ord(code[1]) - 65) * CELL_WIDTH, (ord(code[0]) - 65) * CELL_HEIGHT) if code else None


def atlas_path(script_directory):
    configured = os.environ.get("MAGNOLIE_ORGANIZER_WEB")
    candidates = [os.path.join(configured, "country-flags.png")] if configured else []
    candidates.extend(os.path.join(script_directory, *parts, "country-flags.png") for parts in (
        ("..", "share", "magnolie-organizer", "web"), ("..", "web"), ("web",)))
    candidates.append("/usr/share/magnolie-organizer/web/country-flags.png")
    return next((os.path.abspath(path) for path in candidates if os.path.isfile(path)), "")


def flag_pixbuf(value, script_directory):
    code = country_code(value)
    path = atlas_path(script_directory)
    if not code or not path:
        return None
    key = (path, code)
    if key in _flags:
        return _flags[key]
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        atlas = _atlases.get(path)
        if atlas is None:
            atlas = GdkPixbuf.Pixbuf.new_from_file(path)
            if atlas.get_width() != 26 * CELL_WIDTH or atlas.get_height() != 26 * CELL_HEIGHT:
                return None
            _atlases[path] = atlas
        x, y = country_cell(code)
        crop = atlas.new_subpixbuf(x, y, CELL_WIDTH, CELL_HEIGHT)
        result = crop.scale_simple(28, 21, GdkPixbuf.InterpType.BILINEAR)
        _flags[key] = result
        return result
    except Exception:
        # Missing/invalid decoration must not block address entry or setup.
        return None
