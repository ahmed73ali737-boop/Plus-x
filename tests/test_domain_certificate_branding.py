"""Domain unit tests: system branding card geometry and the reserved area (no imaging, no files)."""
import pytest

from app.domain import InvalidInput, Unavailable
from app.domain import certificate_branding as branding


def manifest(width=1400, height=1000, profile=branding.PROFILE_ID):
    return branding.card_manifest(width, height, profile, branding.profile_resources(profile))


def test_background_must_be_an_integer_canvas_of_at_least_100_pixels():
    branding.require_background_dimensions(100, 5000)
    for width, height in ((99, 500), (500, 99), (500.0, 500), ('500', 500), (True, 500), (None, 500)):
        with pytest.raises(InvalidInput) as error:
            branding.require_background_dimensions(width, height)
        assert error.value.code == 'BACKGROUND_DIMENSIONS_INVALID'


def test_profiles_are_frozen_by_id_and_unknown_ids_are_unavailable():
    assert branding.profile_resources('rts-bottom-left-14-v1')['version'] == 1
    assert branding.profile_resources(branding.PROFILE_ID)['version'] == 2
    for unknown in ('rts-bottom-left-99-v9', None, 5, ''):
        with pytest.raises(Unavailable) as error:
            branding.profile_resources(unknown)
        assert error.value.code == 'BRANDING_PROFILE_UNAVAILABLE'


def test_card_sits_bottom_left_with_the_logo_inside_it():
    m = manifest()
    card, logo = m['card_rect'], m['logo_rect']
    assert m['margin'] == 15 and card['x'] == 15
    assert card['y'] + card['height'] == 1000 - m['margin']                   # bottom-left, inside the margin
    assert card['width'] == round(1400 * .14)
    assert card['x'] <= logo['x'] and logo['x'] + logo['width'] <= card['x'] + card['width']
    assert card['y'] <= logo['y'] and logo['y'] + logo['height'] <= card['y'] + card['height']
    assert (m['logo_width'], m['logo_height']) == (763, 538)                  # native logo size, never the scaled one
    assert m['canvas_width'] == 1400 and m['canvas_height'] == 1000
    assert manifest() == manifest()                                           # deterministic: manifests are compared by equality


def test_a_wider_profile_makes_a_wider_card_and_a_canvas_too_small_for_it_is_refused():
    assert manifest(profile='rts-bottom-left-20-v1')['card_rect']['width'] == round(1400 * .20)
    with pytest.raises(InvalidInput) as error:
        manifest(width=1400, height=150)
    assert error.value.code == 'BRANDING_CANNOT_FIT'
    with pytest.raises(InvalidInput):
        manifest(width=80, height=1000)                                       # logo narrower than 10 px


def test_a_client_manifest_is_never_trusted():
    good = manifest()
    expected = lambda profile_id: manifest(profile=profile_id)  # noqa: E731
    assert branding.require_manifest_matches(good, expected) is good
    for forged in (None, [], {**good, 'label': 'Sponsored by'}, {**good, 'card_rect': {**good['card_rect'], 'x': 0}}):
        with pytest.raises(InvalidInput) as error:
            branding.require_manifest_matches(forged, expected)
        assert error.value.code == 'BRANDING_MANIFEST_INVALID'


RECT = {'x': 300, 'y': 100, 'width': 400, 'height': 200}


def test_reserved_rectangles_stay_inside_and_keep_clear_of_the_card():
    m = manifest()
    assert branding.require_reserved_rect(RECT, m, 1400, 1000) is RECT
    for bad in (None, [1], {'x': 1}, {**RECT, 'z': 1}):
        with pytest.raises(InvalidInput) as error:
            branding.require_reserved_rect(bad, m, 1400, 1000)
        assert error.value.code == 'RECT_INVALID'
    for bad in ({**RECT, 'x': 'a'}, {**RECT, 'width': float('inf')}, {**RECT, 'y': float('nan')}, {**RECT, 'x': True}):
        with pytest.raises(InvalidInput) as error:
            branding.require_reserved_rect(bad, m, 1400, 1000)
        assert error.value.code == 'RECT_INVALID' or bad['x'] is True
    for bad in ({**RECT, 'width': 0}, {**RECT, 'height': -1}, {**RECT, 'x': -1}, {**RECT, 'y': -1},
                {**RECT, 'width': 1200}, {**RECT, 'height': 901}):
        with pytest.raises(InvalidInput) as error:
            branding.require_reserved_rect(bad, m, 1400, 1000)
        assert error.value.code == 'RECT_OUTSIDE_BACKGROUND'


def test_a_rectangle_touching_the_card_or_its_clearance_is_refused():
    m = manifest()
    card = m['card_rect']
    over = {'x': card['x'], 'y': card['y'], 'width': 50, 'height': 50}
    near = {'x': card['x'] + card['width'] + m['clearance'], 'y': card['y'], 'width': 50, 'height': 50}   # touches the clearance
    clear = {'x': card['x'] + card['width'] + m['clearance'] + 1, 'y': card['y'], 'width': 50, 'height': 50}
    above = {'x': card['x'], 'y': card['y'] - m['clearance'] - 51, 'width': 50, 'height': 50}
    for bad in (over, near):
        with pytest.raises(InvalidInput) as error:
            branding.require_reserved_rect(bad, m, 1400, 1000)
        assert error.value.code == 'BRANDING_OVERLAP'
    assert branding.require_reserved_rect(clear, m, 1400, 1000) is clear
    assert branding.require_reserved_rect(above, m, 1400, 1000) is above


def test_the_label_must_fit_the_padded_card():
    branding.require_label_fits(80, 100, 10)
    with pytest.raises(InvalidInput) as error:
        branding.require_label_fits(81, 100, 10)
    assert error.value.code == 'BRANDING_LABEL_CANNOT_FIT'
