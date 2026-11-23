"""Domain unit tests: self-service certificate layout rules (no imaging library, no database)."""
import pytest

from app.domain import InvalidInput, Unavailable
from app.domain import certificate_layout as layout

CONFIG = dict(name_rect={'x': 10, 'y': 20, 'width': 204, 'height': 54}, stamp_rect=None, font_id='f',
              preferred_size=40, minimum_size=10, direction='rtl', align='center', vertical_align='middle',
              color='#152e4d')


def box_of(text, size):
    """Deterministic fake font metrics: 0.5em per character, 1em tall, ink starts at (0, -size)."""
    return [0, -size, len(text) * size / 2, 0]


def test_design_shape_and_pixel_budget():
    layout.require_design_shape(CONFIG)
    for bad in (None, {}, {**CONFIG, 'extra': 1}, {k: v for k, v in CONFIG.items() if k != 'color'}):
        with pytest.raises(InvalidInput) as error:
            layout.require_design_shape(bad)
        assert error.value.code == 'DESIGN_CONFIG_INVALID'
    layout.require_pixel_budget(6000, 3000)
    with pytest.raises(InvalidInput) as error:
        layout.require_pixel_budget(6001, 3000)
    assert error.value.code == 'IMAGE_PIXEL_LIMIT'


@pytest.mark.parametrize('change,code', [
    ({'preferred_size': 0}, 'FONT_SIZE_INVALID'),
    ({'preferred_size': 1025}, 'FONT_SIZE_INVALID'),
    ({'minimum_size': 10.0}, 'FONT_SIZE_INVALID'),
    ({'minimum_size': True}, 'FONT_SIZE_INVALID'),
    ({'minimum_size': 5}, 'FONT_SIZE_INVALID'),           # below 0.8% of the shorter side (1000 -> 8)
    ({'preferred_size': 9}, 'FONT_SIZE_INVALID'),         # smaller than the minimum
    ({'direction': 'up'}, 'TEXT_ALIGNMENT_INVALID'),
    ({'align': 'justify'}, 'TEXT_ALIGNMENT_INVALID'),
    ({'vertical_align': 'baseline'}, 'TEXT_ALIGNMENT_INVALID'),
    ({'color': 'red'}, 'TEXT_COLOR_INVALID'),
    ({'color': '#12345'}, 'TEXT_COLOR_INVALID'),
    ({'color': 5}, 'TEXT_COLOR_INVALID'),
])
def test_typography_rules(change, code):
    layout.require_typography(CONFIG, 1400, 1000)
    with pytest.raises(InvalidInput) as error:
        layout.require_typography({**CONFIG, **change}, 1400, 1000)
    assert error.value.code == code


def test_stamp_font_renderer_and_snapshot_consistency():
    layout.require_stamp_matches(True, {'x': 1})
    layout.require_stamp_matches(False, None)
    with pytest.raises(InvalidInput) as error:
        layout.require_stamp_matches(False, {'x': 1})
    assert error.value.code == 'STAMP_CONFIG_INVALID'
    layout.require_font_matches('f', 'f')
    with pytest.raises(InvalidInput):
        layout.require_font_matches('g', 'f')
    layout.require_font_manifest_unchanged({'a': 1}, {'a': 1})
    with pytest.raises(InvalidInput):
        layout.require_font_manifest_unchanged({'a': 1}, {'a': 2})
    layout.require_supported_renderer('v2', ('v1', 'v2'))
    with pytest.raises(Unavailable):
        layout.require_supported_renderer('v0', ('v1', 'v2'))
    layout.require_renderable_revision(2, 'v1', ('v1',))
    for schema, version in ((1, 'v1'), (2, 'v9')):
        with pytest.raises(Unavailable):
            layout.require_renderable_revision(schema, version, ('v1',))
    layout.require_layout_snapshot({'a': 1}, {'a': 1})
    with pytest.raises(InvalidInput) as error:
        layout.require_layout_snapshot({'a': 1}, {'a': 2})
    assert error.value.code == 'LAYOUT_SNAPSHOT_INVALID'


def test_names_are_normalised_and_bounded():
    supports = lambda text: True  # noqa: E731
    assert layout.normalize_name('  Ali   bin  Omar ', supports) == 'Ali bin Omar'
    cases = [(None, 'INVALID_NAME'), ('', 'INVALID_NAME'), ('x' * 251, 'INVALID_NAME'), (5, 'INVALID_NAME'),
             ('Ali‮Omar', 'NAME_CONTROL_CHARACTERS'), ('Ali\x00', 'NAME_CONTROL_CHARACTERS'),
             ('   ', 'NAME_WORD_LIMIT'), ('a b c d e f', 'NAME_WORD_LIMIT')]
    for value, code in cases:
        with pytest.raises(InvalidInput) as error:
            layout.normalize_name(value, supports)
        assert error.value.code == code
    with pytest.raises(InvalidInput) as glyph:
        layout.normalize_name('Ali', lambda text: False)
    assert glyph.value.code == 'NAME_GLYPH_UNSUPPORTED'


def test_fit_uses_the_largest_size_that_fits_and_centres_the_ink():
    fitted = layout.fit_name('Ali Omar', CONFIG['name_rect'], CONFIG, box_of)
    assert fitted['font_size'] == 40 and fitted['name_printed'] == 'Ali Omar' and fitted['removed_words'] == []
    # width 8 chars * 20 = 160 <= 200; height 40 <= 50 ; centred in the padded rectangle
    assert fitted['text_origin'] == [10 + 2 + (200 - 160) / 2 - 0, 20 + 2 + (50 - 40) / 2 + 40]


def test_fit_shrinks_before_it_drops_words():
    config = {**CONFIG, 'preferred_size': 60}
    fitted = layout.fit_name('Ali Omar', CONFIG['name_rect'], config, box_of)
    assert fitted['font_size'] == 50 and fitted['removed_words'] == []       # 8 chars * 25 = 200 wide, 50 tall


def test_fit_drops_penultimate_words_only_at_the_minimum_size_and_keeps_first_and_last():
    rect = {'x': 0, 'y': 0, 'width': 64, 'height': 40}                       # 60 x 36 usable
    config = {**CONFIG, 'name_rect': rect, 'preferred_size': 12, 'minimum_size': 10}
    fitted = layout.fit_name('A BB CCC DDDD EEEEE', rect, config, box_of)
    assert fitted['font_size'] == 10
    assert fitted['removed_words'] == ['DDDD', 'CCC']
    assert fitted['name_printed'] == 'A BB EEEEE'


def test_fit_refuses_when_two_words_still_do_not_fit_or_the_rectangle_is_degenerate():
    rect = {'x': 0, 'y': 0, 'width': 14, 'height': 40}
    with pytest.raises(InvalidInput) as error:
        layout.fit_name('Aliiiii Omarrrr', rect, {**CONFIG, 'name_rect': rect}, box_of)
    assert error.value.code == 'NAME_CANNOT_FIT'
    tiny = {'x': 0, 'y': 0, 'width': 4, 'height': 40}
    with pytest.raises(InvalidInput):
        layout.fit_name('Ali', tiny, {**CONFIG, 'name_rect': tiny}, box_of)


@pytest.mark.parametrize('align,vertical,x,y', [('left', 'top', 2, 2 + 8), ('right', 'bottom', 2 + 100 - 8, 2 + 40 - 8 + 8)])
def test_alignment_places_the_ink_box_inside_the_padded_rectangle(align, vertical, x, y):
    rect = {'x': 0, 'y': 0, 'width': 104, 'height': 44}
    config = {**CONFIG, 'name_rect': rect, 'preferred_size': 8, 'minimum_size': 8, 'align': align, 'vertical_align': vertical}
    fitted = layout.fit_name('ab', rect, config, box_of)                  # ink 8 wide x 8 tall at size 8
    assert fitted['text_origin'] == [x, y]


def test_stamp_is_scaled_centred_and_never_overflows():
    rect = {'x': 100, 'y': 200, 'width': 100, 'height': 50}
    assert layout.stamp_placement(rect, 400, 100) == ((100, 25), (100, 212))
    assert layout.stamp_placement(rect, 50, 100) == ((25, 50), (138, 200))
    assert layout.stamp_placement(rect, 1, 1)[0] == (50, 50)
    with pytest.raises(InvalidInput) as error:
        layout.stamp_placement({'x': 0, 'y': 0, 'width': 0, 'height': 10}, 10, 10)
    assert error.value.code == 'STAMP_CANNOT_FIT'
