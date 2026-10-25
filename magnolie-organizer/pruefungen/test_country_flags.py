"""#223: shared local artwork, ISO coordinates and non-mutating setup lookup."""
from pathlib import Path
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "magnolie-organizer/bin"))
import magnolie_country_flags as flags
from magnolie_phone_region import ISO_ALPHA2


def test_country_atlas_is_identical_local_artwork_for_both_platforms():
    linux = ROOT / "magnolie-organizer/web/country-flags.png"
    windows = ROOT / "magnolie-organizer-windows/app/web/country-flags.png"
    assert linux.read_bytes() == windows.read_bytes()
    with Image.open(linux) as image:
        assert image.size == (1664, 1248)
        for code in ISO_ALPHA2:
            x, y = flags.country_cell(code)
            assert image.crop((x, y, x+64, y+48)).getbbox(), code
        x, y = flags.country_cell("DE")
        black, red, gold = (image.getpixel((x+32, y+offset)) for offset in (7, 24, 41))
        assert max(black[:3]) < 30
        assert red[0] > 150 and red[1] < 80 and red[2] < 80
        assert gold[0] > 200 and gold[1] > 120 and gold[2] < 80
        assert image.crop((25*64, 25*48, 26*64, 26*48)).getbbox() is None


def test_setup_flag_lookup_keeps_address_values_and_rejects_unknown_codes():
    choices = (("DE", "Germany"), ("AT", "Austria"))
    source = "  Österreich  "
    translate = lambda text: {"Germany": "Deutschland", "Austria": "Österreich"}.get(text, text)
    assert flags.country_code(source, choices, translate) == "AT" and source == "  Österreich  "
    assert flags.country_code("Germany", choices, translate) == "DE"
    assert flags.country_cell("de") == (4*64, 3*48)
    for invalid in ("", None, "ZZ", "other", "DE-other", "Deutschland extra", "../../DE"):
        assert flags.country_code(invalid, choices, translate) == ""
        assert flags.country_cell(invalid) is None


def test_native_setup_pixbuf_uses_the_same_atlas_without_network(monkeypatch):
    pytest.importorskip("gi")
    monkeypatch.setenv("MAGNOLIE_ORGANIZER_WEB", str(ROOT / "magnolie-organizer/web"))
    image = flags.flag_pixbuf("AT", str(ROOT / "magnolie-organizer/bin"))
    assert image is not None and (image.get_width(), image.get_height()) == (28, 21)
    assert flags.flag_pixbuf("AT", str(ROOT / "magnolie-organizer/bin")) is image
    assert flags.flag_pixbuf("ZZ", str(ROOT / "magnolie-organizer/bin")) is None
