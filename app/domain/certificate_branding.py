"""System branding of self-service certificates: immutable profiles, card geometry and the reserved area.

The card (a white box with a "Powered by" label and a logo) is placed bottom-left and its rectangle is
reserved: design rectangles may never touch it. Profiles are retained by id forever; a future identity
appends a new definition. Reading logo/font bytes and drawing are adapters.
"""
from __future__ import annotations

import math

from app.domain.errors import Unavailable, fail

LOGO_SHA256 = 'f234da2551cf3ba73641ead5e6274463e60a3c8930ff77dab9909ff6c9b8f198'
FONT_SHA256 = '34b56369900e012c9aa991938397f465702194b7a5e3aa89a83220d2aa45a81f'
PROFILE_ID = 'rts-bottom-left-14-v2'
# 14% selected by the project owner on 2026-10-22; the other profiles are retained for calibration history.
PROFILE_WIDTH_SHARE = {'rts-bottom-left-14-v1': .14, 'rts-bottom-left-20-v1': .20, PROFILE_ID: .14}
PROFILE_RESOURCES = {
    ident: dict(logo_sha256=LOGO_SHA256, font_hash=FONT_SHA256, version=version)
    for ident, version in (('rts-bottom-left-14-v1', 1), ('rts-bottom-left-20-v1', 1), ('rts-bottom-left-14-v2', 2))
}
MIN_BACKGROUND_SIDE = 100
LOGO_NATIVE = (763, 538)
CARD_CLEARANCE = 2
RECT_KEYS = frozenset({'x', 'y', 'width', 'height'})


def require_background_dimensions(width, height) -> None:
    if type(width) is not int or type(height) is not int or min(width, height) < MIN_BACKGROUND_SIDE:
        fail('BACKGROUND_DIMENSIONS_INVALID')


def profile_resources(profile_id) -> dict:
    """The frozen resource definition of a profile id; unknown ids are unavailable, never guessed."""
    if not isinstance(profile_id, str) or profile_id not in PROFILE_RESOURCES:
        fail('BRANDING_PROFILE_UNAVAILABLE', Unavailable)
    return PROFILE_RESOURCES[profile_id]


def card_manifest(width: int, height: int, profile_id: str, resource: dict) -> dict:
    """The deterministic manifest of the branding card for a background of ``width`` x ``height``."""
    margin = max(2, round(min(width, height) * .015))
    if profile_id not in PROFILE_WIDTH_SHARE:
        fail('BRANDING_PROFILE_UNAVAILABLE', Unavailable)
    card_width = round(width * PROFILE_WIDTH_SHARE[profile_id])
    padding = max(2, round(card_width * .045))
    label_size = max(6, round(card_width * .065))
    logo_width = min(LOGO_NATIVE[0], card_width - 2 * padding)
    logo_height = round(logo_width * LOGO_NATIVE[1] / LOGO_NATIVE[0])
    card_height = 3 * padding + label_size + logo_height
    if logo_width < 10 or card_height + 2 * margin > height:
        fail('BRANDING_CANNOT_FIT')
    x, y = margin, height - margin - card_height
    return dict(profile_id=profile_id, version=resource['version'], logo_sha256=resource['logo_sha256'],
                logo_width=LOGO_NATIVE[0], logo_height=LOGO_NATIVE[1], label='Powered by',
                font_id='certificate-sans-label-v1', font_hash=resource['font_hash'],
                card_rect=dict(x=x, y=y, width=card_width, height=card_height),
                logo_rect=dict(x=x + (card_width - logo_width) // 2, y=y + 2 * padding + label_size,
                               width=logo_width, height=logo_height),
                label_size=label_size, padding=padding, margin=margin, clearance=CARD_CLEARANCE,
                background='#FFFFFF', layout_version=1, canvas_width=width, canvas_height=height)


def require_manifest_matches(manifest, expected_for) -> dict:
    """A client-provided manifest is never trusted: it must equal the one computed for its profile.

    ``expected_for(profile_id)`` computes it (the use case supplies the call that also verifies resources).
    """
    if not isinstance(manifest, dict) or manifest != expected_for(manifest.get('profile_id')):
        fail('BRANDING_MANIFEST_INVALID')
    return manifest


def require_reserved_rect(rect, manifest: dict, width: int, height: int) -> dict:
    """Rectangles use original pixels, stay inside the background and never touch the expanded card."""
    if not isinstance(rect, dict) or set(rect) != RECT_KEYS:
        fail('RECT_INVALID')
    values = [rect[key] for key in ('x', 'y', 'width', 'height')]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        fail('RECT_INVALID')
    x, y, w, h = values
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        fail('RECT_OUTSIDE_BACKGROUND')
    card, gap = manifest['card_rect'], manifest['clearance']
    if (x + w >= card['x'] - gap and x <= card['x'] + card['width'] + gap
            and y + h >= card['y'] - gap and y <= card['y'] + card['height'] + gap):
        fail('BRANDING_OVERLAP')
    return rect


def require_label_fits(label_width: float, card_width: int, padding: int) -> None:
    if label_width > card_width - 2 * padding:
        fail('BRANDING_LABEL_CANNOT_FIT')
