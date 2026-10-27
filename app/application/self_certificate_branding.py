"""Immutable system branding profiles; never trust a client-provided manifest."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
from PIL import Image
from app.domain import fail

ROOT = Path(__file__).resolve().parents[2]
LOGO_SHA256 = 'f234da2551cf3ba73641ead5e6274463e60a3c8930ff77dab9909ff6c9b8f198'
FONT_SHA256 = '34b56369900e012c9aa991938397f465702194b7a5e3aa89a83220d2aa45a81f'
RESOURCE_ROOT=Path(os.environ.get('PX_SELF_CERTIFICATE_RESOURCE_ROOT') or ROOT/'app/resources').resolve()
LOGO_PATH = RESOURCE_ROOT/'branding/rts'/(LOGO_SHA256+'.png')
FONT_PATH = RESOURCE_ROOT/'fonts'/(FONT_SHA256+'.ttf')
PROFILE_ID = 'rts-bottom-left-14-v2'
PROFILES = {'rts-bottom-left-14-v1': .14, 'rts-bottom-left-20-v1': .20, PROFILE_ID: .14}
# Definitions are retained by ID; future identities append a new definition.
PROFILE_RESOURCES = {
    ident:dict(logo_sha256='f234da2551cf3ba73641ead5e6274463e60a3c8930ff77dab9909ff6c9b8f198',
        font_hash='34b56369900e012c9aa991938397f465702194b7a5e3aa89a83220d2aa45a81f',
        version=version)
    for ident,version in (('rts-bottom-left-14-v1',1),('rts-bottom-left-20-v1',1),('rts-bottom-left-14-v2',2))
}

def logo_path(digest):
    return LOGO_PATH if digest==LOGO_SHA256 else RESOURCE_ROOT/'branding/rts'/(digest+'.png')

def label_font_path(digest):
    return FONT_PATH if digest==FONT_SHA256 else RESOURCE_ROOT/'fonts'/(digest+'.ttf')


_ISOLATED_BYTES = {}


def prepare_isolated_resources(manifest):
    # Called only in a fresh secret-free decoder child before confinement.
    global _ISOLATED_BYTES
    _ISOLATED_BYTES = {}
    _ISOLATED_BYTES = {(str(path),digest):verified_bytes(path,digest,error) for path,digest,error in (
        (logo_path(manifest['logo_sha256']),manifest['logo_sha256'],'BRANDING_ASSET_UNAVAILABLE'),
        (label_font_path(manifest['font_hash']),manifest['font_hash'],'BRANDING_FONT_UNAVAILABLE'))}


def verified_bytes(path, digest, error):
    isolated=_ISOLATED_BYTES.get((str(path),digest))
    if isolated is not None:return isolated
    try:
        data = path.read_bytes()
    except OSError:
        fail(error, 503)
    if sha256(data).hexdigest() != digest:
        fail(error, 503)
    return data

def system_profile(width, height, *, profile_id=PROFILE_ID):
    # 14% selected by the project owner on 2026-10-22; other profile retained for calibration history.
    if type(width) is not int or type(height) is not int or min(width, height) < 100:
        fail('BACKGROUND_DIMENSIONS_INVALID')
    if not isinstance(profile_id,str) or profile_id not in PROFILE_RESOURCES:
        fail('BRANDING_PROFILE_UNAVAILABLE',503)
    resource=PROFILE_RESOURCES[profile_id]
    verified_bytes(logo_path(resource['logo_sha256']),resource['logo_sha256'],'BRANDING_ASSET_UNAVAILABLE')
    verified_bytes(label_font_path(resource['font_hash']),resource['font_hash'],'BRANDING_FONT_UNAVAILABLE')
    margin = max(2, round(min(width, height) * .015))
    if not isinstance(profile_id,str) or profile_id not in PROFILES:
        fail('BRANDING_PROFILE_UNAVAILABLE',503)
    card_width = round(width * PROFILES[profile_id])
    padding = max(2, round(card_width * .045))
    label_size = max(6, round(card_width * .065))
    logo_width = min(763, card_width - 2 * padding)
    logo_height = round(logo_width * 538 / 763)
    card_height = 3 * padding + label_size + logo_height
    if logo_width < 10 or card_height + 2 * margin > height:
        fail('BRANDING_CANNOT_FIT')
    x, y = margin, height - margin - card_height
    return dict(profile_id=profile_id, version=resource['version'], logo_sha256=resource['logo_sha256'],
        logo_width=763, logo_height=538, label='Powered by',
        font_id='certificate-sans-label-v1', font_hash=resource['font_hash'],
        card_rect=dict(x=x, y=y, width=card_width, height=card_height),
        logo_rect=dict(x=x+(card_width-logo_width)//2, y=y+2*padding+label_size, width=logo_width, height=logo_height),
        label_size=label_size, padding=padding, margin=margin, clearance=2,
        background='#FFFFFF', layout_version=1, canvas_width=width, canvas_height=height)

def validate_manifest(manifest, width, height):
    # Frozen historical profiles must be dispatched explicitly when a second profile is added.
    if not isinstance(manifest, dict) or manifest != system_profile(width, height, profile_id=manifest.get('profile_id')):
        fail('BRANDING_MANIFEST_INVALID')
    return manifest

def validate_reserved_rect(rect, manifest, width, height):
    """Rectangles use original pixels; reject touching the expanded reserved area."""
    import math
    if not isinstance(rect, dict) or set(rect) != {'x','y','width','height'}:
        fail('RECT_INVALID')
    values = [rect[k] for k in ('x','y','width','height')]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        fail('RECT_INVALID')
    x,y,w,h = values
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > width or y+h > height:
        fail('RECT_OUTSIDE_BACKGROUND')
    r=manifest['card_rect']; gap=manifest['clearance']
    if x+w >= r['x']-gap and x <= r['x']+r['width']+gap and y+h >= r['y']-gap and y <= r['y']+r['height']+gap:
        fail('BRANDING_OVERLAP')
    return rect

def composite_branding(image, manifest):
    """Last opaque layer, within the original canvas; same path for preview/final."""
    from PIL import ImageDraw, ImageFont
    width,height=image.size
    validate_manifest(manifest,width,height)
    result=image.convert('RGBA')
    r=manifest['card_rect']; logo_rect=manifest['logo_rect']
    # Rectangle's inclusive end is adjusted so no pixel escapes the reserved card.
    draw=ImageDraw.Draw(result)
    draw.rectangle((r['x'],r['y'],r['x']+r['width']-1,r['y']+r['height']-1), fill=(255,255,255,255))
    font=ImageFont.truetype(BytesIO(verified_bytes(label_font_path(manifest['font_hash']),manifest['font_hash'],'BRANDING_FONT_UNAVAILABLE')), manifest['label_size'])
    bbox=draw.textbbox((0,0),manifest['label'],font=font)
    if bbox[2]-bbox[0] > r['width']-2*manifest['padding']:
        fail('BRANDING_LABEL_CANNOT_FIT')
    draw.text((r['x']+manifest['padding']-bbox[0],r['y']+manifest['padding']-bbox[1]),manifest['label'],font=font,fill='#202020')
    with Image.open(BytesIO(verified_bytes(logo_path(manifest['logo_sha256']),manifest['logo_sha256'],'BRANDING_ASSET_UNAVAILABLE'))) as logo:
        resized=logo.convert('RGBA').resize((logo_rect['width'],logo_rect['height']),Image.Resampling.LANCZOS)
        result.alpha_composite(resized,(logo_rect['x'],logo_rect['y']))
    return result
