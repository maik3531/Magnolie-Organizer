import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_drawing_svg import validated_bytes

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAARUlEQVR4nO3OsQEAEADAMPz/M7slI0NzQeYef1mvA7dCUkgKSSEpJIWkkBSSQlJICkkhKSSFpJAUkkJSSApJISkkhaSQHEnhAV+0eRpfAAAAAElFTkSuQmCC"

def svg(href):
    return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300"><image href="' + href + '" x="0" y="0" width="400" height="300"/><path d="M1 2L3 4" fill="none" stroke="#000000" stroke-width="2"/></svg>'

def test_opened_image_with_signature_is_self_contained():
    assert validated_bytes(svg(PNG)).startswith(b"<svg")

@pytest.mark.parametrize("href", ["https://example.invalid/private.png", "file:///private.png", "data:image/svg+xml;base64,PHN2Zy8+", "data:image/png;base64,YmFk"])
def test_external_or_non_png_image_references_are_not_loaded(href):
    with pytest.raises(ValueError): validated_bytes(svg(href))
