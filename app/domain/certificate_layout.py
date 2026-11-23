"""Self-service certificate layout rules: design settings, name normalisation and the fitting algorithm.

Font measurement and pixel rendering are adapters; the rules below take a ``measure`` callable
(text size -> bounding box) so the shrink-then-drop-words policy stays pure and testable.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable
from typing import Sequence

from app.domain.errors import Unavailable, fail

PIXEL_LIMIT = 18_000_000
DESIGN_FIELDS = frozenset({'name_rect', 'stamp_rect', 'font_id', 'preferred_size', 'minimum_size', 'direction',
                           'align', 'vertical_align', 'color'})
MAX_FONT_SIZE = 1024
DIRECTIONS = ('rtl', 'ltr')
HORIZONTAL_ALIGNMENTS = ('left', 'center', 'right')
VERTICAL_ALIGNMENTS = ('top', 'middle', 'bottom')
COLOR = re.compile(r'#[a-fA-F0-9]{6}')
MAX_NAME_LENGTH = 250
MAX_NAME_WORDS = 5
MIN_WORDS_KEPT = 2
NAME_PADDING = 2
ALGORITHM = 'shrink-then-penultimate-v1'
Box = Sequence[float]


def require_design_shape(config) -> None:
    if not isinstance(config, dict) or set(config) != DESIGN_FIELDS:
        fail('DESIGN_CONFIG_INVALID')


def require_pixel_budget(width: int, height: int) -> None:
    if width * height > PIXEL_LIMIT:
        fail('IMAGE_PIXEL_LIMIT')


def require_typography(config: dict, width: int, height: int) -> None:
    """Font sizes are bounded integers, never below 0.8% of the shorter side; alignment and color are closed sets."""
    for key in ('preferred_size', 'minimum_size'):
        if type(config[key]) is not int or not 1 <= config[key] <= MAX_FONT_SIZE:
            fail('FONT_SIZE_INVALID')
    if config['minimum_size'] < max(1, math.ceil(min(width, height) * .008)) or config['preferred_size'] < config['minimum_size']:
        fail('FONT_SIZE_INVALID')
    if (config['direction'] not in DIRECTIONS or config['align'] not in HORIZONTAL_ALIGNMENTS
            or config['vertical_align'] not in VERTICAL_ALIGNMENTS):
        fail('TEXT_ALIGNMENT_INVALID')
    if not isinstance(config['color'], str) or not COLOR.fullmatch(config['color']):
        fail('TEXT_COLOR_INVALID')


def require_stamp_matches(has_stamp: bool, stamp_rect) -> None:
    """A stamp rectangle exists exactly when a stamp asset is attached."""
    if not has_stamp and stamp_rect is not None:
        fail('STAMP_CONFIG_INVALID')


def require_font_matches(primary_font_id: str, font_id: str) -> None:
    if primary_font_id != font_id:
        fail('FONT_MANIFEST_INVALID')


def require_font_manifest_unchanged(validated: dict, stored: dict) -> None:
    if validated != stored:
        fail('FONT_MANIFEST_INVALID')


def require_supported_renderer(version: str, supported: Sequence[str]) -> None:
    if version not in supported:
        fail('RENDERER_VERSION_UNAVAILABLE', Unavailable)


def require_renderable_revision(schema_version: int, version: str, supported: Sequence[str], current_schema: int = 2) -> None:
    if schema_version != current_schema or version not in supported:
        fail('RENDERER_VERSION_UNAVAILABLE', Unavailable)


def require_layout_snapshot(layout: dict, expected: dict) -> None:
    """A stored layout must be exactly what the algorithm produces now (tamper/renderer drift detection)."""
    if layout != expected:
        fail('LAYOUT_SNAPSHOT_INVALID')


def normalize_name(value, supports: Callable[[str], bool]) -> str:
    """NFC, single-spaced, at most five words, no control/format/surrogate characters, all glyphs supported."""
    if not isinstance(value, str) or not value or len(value) > MAX_NAME_LENGTH:
        fail('INVALID_NAME')
    if any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs') for char in value):
        fail('NAME_CONTROL_CHARACTERS')
    normalized = ' '.join(unicodedata.normalize('NFC', value).split())
    if not normalized or len(normalized.split()) > MAX_NAME_WORDS:
        fail('NAME_WORD_LIMIT')
    if not supports(normalized):
        fail('NAME_GLYPH_UNSUPPORTED')
    return normalized


def fit_name(normalized: str, rect: dict, config: dict, measure: Callable[[str, int], Box]) -> dict:
    """Largest size that fits; otherwise drop penultimate words (keeping first and last) at the minimum size.

    ``measure(text, size)`` returns the ink bounding box. The descending search is exact: it assumes
    nothing about hinted bounding boxes being monotonic in size.
    """
    pad = NAME_PADDING
    if rect['width'] <= 2 * pad or rect['height'] <= 2 * pad:
        fail('NAME_CANNOT_FIT')

    def fits(box):
        return box[2] - box[0] <= rect['width'] - 2 * pad and box[3] - box[1] <= rect['height'] - 2 * pad

    printed, removed, chosen = normalized, [], None
    for size in range(config['preferred_size'], config['minimum_size'] - 1, -1):
        box = measure(printed, size)
        if fits(box):
            chosen = (size, box)
            break
    words = normalized.split()
    while chosen is None and len(words) > MIN_WORDS_KEPT:
        removed.append(words.pop(-2))
        printed = ' '.join(words)
        box = measure(printed, config['minimum_size'])
        if fits(box):
            chosen = (config['minimum_size'], box)
    if chosen is None:
        fail('NAME_CANNOT_FIT')
    size, box = chosen
    remaining_x = rect['width'] - 2 * pad - (box[2] - box[0])
    remaining_y = rect['height'] - 2 * pad - (box[3] - box[1])
    dx = {'left': 0, 'center': remaining_x / 2, 'right': remaining_x}[config['align']]
    dy = {'top': 0, 'middle': remaining_y / 2, 'bottom': remaining_y}[config['vertical_align']]
    origin = [rect['x'] + pad + dx - box[0], rect['y'] + pad + dy - box[1]]
    return dict(name_printed=printed, removed_words=removed, font_size=size, text_bbox=box,
                text_origin=origin)


def stamp_placement(rect: dict, seal_width: int, seal_height: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Scale the seal to fit its rectangle, centred; ((width, height), (x, y)). Overflow is refused."""
    scale = min(rect['width'] / seal_width, rect['height'] / seal_height)
    size = (max(1, math.floor(seal_width * scale)), max(1, math.floor(seal_height * scale)))
    if size[0] > rect['width'] or size[1] > rect['height']:
        fail('STAMP_CANNOT_FIT')
    x = round(rect['x'] + (rect['width'] - size[0]) / 2)
    y = round(rect['y'] + (rect['height'] - size[1]) / 2)
    if x < rect['x'] or y < rect['y'] or x + size[0] > rect['x'] + rect['width'] or y + size[1] > rect['y'] + rect['height']:
        fail('STAMP_CANNOT_FIT')
    return size, (x, y)
