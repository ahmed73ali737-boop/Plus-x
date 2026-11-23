"""Immutable system branding profiles; never trust a client-provided manifest."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
from PIL import Image
from app.domain import fail, Unavailable
from app.domain import certificate_branding as rules

ROOT = Path(__file__).resolve().parents[2]
LOGO_SHA256 = rules.LOGO_SHA256
FONT_SHA256 = rules.FONT_SHA256
RESOURCE_ROOT=Path(os.environ.get('PX_SELF_CERTIFICATE_RESOURCE_ROOT') or ROOT/'app/resources').resolve()
LOGO_PATH = RESOURCE_ROOT/'branding/rts'/(LOGO_SHA256+'.png')
FONT_PATH = RESOURCE_ROOT/'fonts'/(FONT_SHA256+'.ttf')
PROFILE_ID = rules.PROFILE_ID
PROFILES = rules.PROFILE_WIDTH_SHARE
PROFILE_RESOURCES = rules.PROFILE_RESOURCES

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
        fail(error, Unavailable)
    if sha256(data).hexdigest() != digest:
        fail(error, Unavailable)
    return data

def system_profile(width, height, *, profile_id=PROFILE_ID):
    rules.require_background_dimensions(width, height)
    resource=rules.profile_resources(profile_id)
    verified_bytes(logo_path(resource['logo_sha256']),resource['logo_sha256'],'BRANDING_ASSET_UNAVAILABLE')
    verified_bytes(label_font_path(resource['font_hash']),resource['font_hash'],'BRANDING_FONT_UNAVAILABLE')
    return rules.card_manifest(width, height, profile_id, resource)

def validate_manifest(manifest, width, height):
    # Frozen historical profiles must be dispatched explicitly when a second profile is added.
    return rules.require_manifest_matches(manifest, lambda profile_id: system_profile(width, height, profile_id=profile_id))

def validate_reserved_rect(rect, manifest, width, height):
    """Rectangles use original pixels; reject touching the expanded reserved area."""
    return rules.require_reserved_rect(rect, manifest, width, height)

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
    rules.require_label_fits(bbox[2]-bbox[0], r['width'], manifest['padding'])
    draw.text((r['x']+manifest['padding']-bbox[0],r['y']+manifest['padding']-bbox[1]),manifest['label'],font=font,fill='#202020')
    with Image.open(BytesIO(verified_bytes(logo_path(manifest['logo_sha256']),manifest['logo_sha256'],'BRANDING_ASSET_UNAVAILABLE'))) as logo:
        resized=logo.convert('RGBA').resize((logo_rect['width'],logo_rect['height']),Image.Resampling.LANCZOS)
        result.alpha_composite(resized,(logo_rect['x'],logo_rect['y']))
    return result
