"""Actual Pillow/native PDF probe; run with the existing Jammy rootfs or host."""
import base64
import io
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_print_pdf import prepare_pillow_for_pdf, render_pdf, compose_pdf
import PIL
from PIL import Image, ImageOps

prepare_pillow_for_pdf()
from weasyprint.images import rotate_pillow_image
from pypdf import PdfReader


def main():
    image = Image.new('RGB', (2, 3))
    image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)])
    for angle, flip, operation in [(90, False, 'ROTATE_90'), (180, False, 'ROTATE_180'),
                                    (270, False, 'ROTATE_270'), (0, True, 'FLIP_LEFT_RIGHT')]:
        actual = rotate_pillow_image(image, (angle, flip))
        expected = image.transpose(getattr(Image.Transpose, operation))
        assert actual.size == expected.size and actual.tobytes() == expected.tobytes()
    both = rotate_pillow_image(image, (90, True))
    expected = image.transpose(Image.Transpose.ROTATE_90).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    assert both.size == expected.size and both.tobytes() == expected.tobytes()
    assert rotate_pillow_image(image, 'none') is image
    image.getexif()[274] = 6
    image.info['exif'] = image.getexif().tobytes()
    assert rotate_pillow_image(image, 'from-image').tobytes() == ImageOps.exif_transpose(image).tobytes()
    png = io.BytesIO()
    image.convert('RGBA').save(png, format='PNG')
    jpeg = io.BytesIO()
    image.save(jpeg, format='JPEG')
    markup = '<html><style>@page{size:A4 landscape;margin:10mm}</style><p>Handbook Pillow compatibility fixture</p>'
    for mime, data in [('image/png', png.getvalue()), ('image/jpeg', jpeg.getvalue())]:
        markup += '<img style="width:20mm;image-orientation:90deg" src="data:' + mime + ';base64,' + base64.b64encode(data).decode() + '">'
    markup += '</html>'
    with tempfile.TemporaryDirectory(prefix='handbook-pillow-') as temporary:
        original, composed = Path(temporary) / 'original.pdf', Path(temporary) / 'composed.pdf'
        result = render_pdf(markup, Path(__file__).resolve().parents[1] / 'web', original, {})
        reader = PdfReader(original)
        assert result['sheets'] == len(reader.pages) == 1
        assert 'Handbook Pillow compatibility fixture' in reader.pages[0].extract_text()
        assert len(reader.pages[0].images) == 2
        compose_pdf(original, composed, {'number_up': 2, 'copies': 2})
        assert len(PdfReader(composed).pages) == 2
    print('PASS: actual Pillow ' + PIL.__version__ + ', rotations/EXIF, PNG/JPEG PDF render, text/images and sheet composition')


if __name__ == '__main__':
    main()
