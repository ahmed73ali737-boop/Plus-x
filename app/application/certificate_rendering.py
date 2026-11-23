"""Deterministic certificate bitmap/PDF renderer using the shipped licensed font.

PDF is a high-resolution raster document, not a cryptographically signed PDF.
No remote URLs, external SVG, system fonts or executable templates are loaded.
"""
import base64
from functools import lru_cache
from hashlib import sha256
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, features
import qrcode
from app.domain.certificates import (
    Certificate, require_font_version, require_image_reference, require_image_within_limits,
    require_normalized_image_size, require_render_size, require_text_inside_canvas, resolve_placeholders, unreadable_image,
)

FONT = Path(__file__).resolve().parents[2] / 'web/fonts/CertificateSans.ttf'


@lru_cache(maxsize=1)
def font_bytes():
    return FONT.read_bytes()


def font_hash():
    return sha256(font_bytes()).hexdigest()


def text_layout(content, layer, size):
    """Use native shaping when present, with a portable Windows fallback.

    BASIC alone does not shape Arabic. The fallback explicitly shapes Arabic
    presentation forms and applies Unicode BiDi before drawing visual glyphs.
    Neither path changes the logical text stored in the certificate snapshot.
    """
    direction = layer['direction']
    native = features.check('raqm')
    if native:
        engine, options = ImageFont.Layout.RAQM, {'direction': direction}
    else:
        from arabic_reshaper import ArabicReshaper
        from bidi import get_display
        reshaper = ArabicReshaper(configuration={'delete_harakat': False, 'shift_harakat_position': True})
        content = get_display(reshaper.reshape(content), base_dir='R' if direction == 'rtl' else 'L')
        engine, options = ImageFont.Layout.BASIC, {}
    align = layer['align']
    anchor = 'ms' if align == 'middle' else ('rs' if (align == 'start') == (direction == 'rtl') else 'ls')
    font = ImageFont.truetype(io.BytesIO(font_bytes()), max(1, round(size)), layout_engine=engine)
    return content, font, {'anchor': anchor, **options}


def validate_layout(design, data):
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    for layer in design['layers']:
        if layer.get('kind') == 'image': continue
        content = resolve_placeholders(layer['text'], data)
        content, font, options = text_layout(content, layer, layer['size'])
        left, top, right, bottom = draw.textbbox((layer['x'], layer['y']), content, font=font, **options)
        require_text_inside_canvas((left, top, right, bottom), design['width'], design['height'])


def image_data(raw):
    """Normalize uploads to bounded metadata-free PNG; never fetch URLs."""
    require_image_reference(raw)
    try:
        data = base64.b64decode(raw.split(',', 1)[1], validate=True)
        with Image.open(io.BytesIO(data)) as im:
            require_image_within_limits(im.format, im.width, im.height)
            im.load()
            result = io.BytesIO()
            im.convert('RGBA').save(result, format='PNG')
        require_normalized_image_size(len(result.getvalue()))
        return 'data:image/png;base64,' + base64.b64encode(result.getvalue()).decode()
    except (ValueError, OSError, Image.DecompressionBombError):
        unreadable_image()


def render(row, verification_url, output_format='PNG'):
    Certificate.require_valid(row)
    require_font_version(row['snapshot'].get('font_hash', font_hash()), font_hash())
    design, data = row['snapshot']['design'], row['snapshot']['data']
    # 3508px across a 297mm landscape page is approximately 300 DPI.
    scale = 3508 / design['width']
    width, height = round(design['width'] * scale), round(design['height'] * scale)
    require_render_size(width, height)
    page = Image.new('RGB', (width, height), design['background'])
    draw = ImageDraw.Draw(page)

    def paint_image(uri, x, y, w, h):
        with Image.open(io.BytesIO(base64.b64decode(uri.split(',', 1)[1]))) as im:
            resized = im.convert('RGBA').resize((round(w*scale), round(h*scale)), Image.Resampling.LANCZOS)
            page.paste(resized, (round(x*scale), round(y*scale)), resized)

    if design.get('background_image'): paint_image(design['background_image'], 0, 0, design['width'], design['height'])
    draw.rectangle((24*scale, 24*scale, width-24*scale, height-24*scale), outline='#b88a44', width=round(3*scale))
    for layer in design['layers']:
        if layer.get('kind') == 'image':
            paint_image(layer['image_data'], layer['x'], layer['y'], layer['width'], layer['height'])
            continue
        content = resolve_placeholders(layer['text'], data)
        content, font, options = text_layout(content, layer, layer['size'] * scale)
        draw.text((layer['x']*scale, layer['y']*scale), content, font=font, fill=layer['color'], **options)
    pos = design['qr']
    qr = qrcode.make(verification_url).convert('RGB').resize((round(pos['size']*scale),)*2, Image.Resampling.NEAREST)
    page.paste(qr, (round(pos['x']*scale), round(pos['y']*scale)))
    result = io.BytesIO()
    page.save(result, format=output_format, **({'resolution': 300.0} if output_format == 'PDF' else {}))
    return result.getvalue()
