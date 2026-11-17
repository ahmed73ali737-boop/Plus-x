"""Site configuration and content records (the value objects of an EventSite).

A site's configuration is stored as a JSON document; these factories are the
only way to build one, so every stored draft/published version satisfies the
rules below. ``normalize_record`` is the Record value-object factory and
``normalize_config`` the SiteConfig factory.
"""
from __future__ import annotations

import copy
import re

from app.domain.access_control import AccessPolicy
from app.domain.errors import fail
from app.domain.values import CODE, boolean, number, ordered_range, stamp, text, url

KINDS = ('participant', 'sponsor', 'session', 'place', 'fact', 'service', 'question', 'poll',
         'offer', 'ad', 'media', 'contact', 'news')
QTYPES = ('single_choice', 'multiple_choice', 'dropdown', 'image_choice', 'yes_no', 'short_text',
          'long_text', 'number', 'currency', 'rating', 'nps', 'slider', 'ranking', 'matrix', 'emoji',
          'date', 'time', 'datetime', 'email', 'phone', 'url', 'consent', 'allocation', 'quiz')
SECTIONS = [
    ('event', 'الفعالية والمشاركون'), ('facts', 'الحقائق والأرقام'), ('about', 'عن الجهة'),
    ('services', 'الخدمات'), ('questions', 'الأسئلة والاستبيانات'), ('polls', 'التصويت'),
    ('ratings', 'التقييم والملاحظات'), ('contact', 'التواصل والمتابعة'),
    ('offers', 'الإعلانات والعروض'), ('media', 'الصور والفيديو'),
]
OPTION_TYPES = ('single_choice', 'multiple_choice', 'dropdown', 'image_choice', 'ranking', 'quiz', 'allocation')
POLL_TYPES = ('single_choice', 'multiple_choice', 'image_choice', 'rating', 'ranking', 'emoji')
SCALE_TYPES = ('rating', 'matrix', 'emoji')
FACT_DISPLAYS = ('number', 'bar', 'text', 'percentage', 'trend', 'comparison', 'timeline', 'donut')
TEMPLATES = ('fintech', 'technology', 'corporate', 'exhibition', 'minimal', 'dynamic', 'sponsor',
             'startup', 'rts_tech', 'easy_finance', 'tharawat_finance')
COLORS = (('primary', '#176B73'), ('secondary', '#0F3D46'), ('accent', '#29B8A8'),
          ('background', '#F5F8FA'), ('surface', '#FFFFFF'), ('text_color', '#17313B'))
STYLE_CHOICES = (  # (field, allowed values, default)
    ('font', ('system', 'modern', 'classic', 'geometric'), 'system'),
    ('card_style', ('soft', 'bordered', 'glass', 'flat'), 'soft'),
    ('hero_style', ('split', 'centered', 'cover', 'minimal'), 'split'),
    ('button_style', ('rounded', 'pill', 'square', 'outline'), 'rounded'),
    ('nav_style', ('clean', 'tabs', 'floating'), 'clean'),
    ('density', ('compact', 'comfortable', 'spacious'), 'comfortable'),
    ('content_width', ('narrow', 'wide', 'full'), 'wide'),
    ('heading_scale', ('compact', 'balanced', 'display'), 'balanced'),
)
SECTION_LAYOUTS = ('cards', 'featured', 'list', 'masonry', 'split')
DEFAULT_RATING_CRITERIA = [{'key': 'overall', 'label': 'التقييم العام', 'weight': 100}]
SURVEY_COMPLETION = 'شكرًا لك، تم استلام إجاباتك.'
SURVEY_SUBMIT_LABEL = 'إرسال الاستبيان'
MAX_RECORDS = 2000


def _choice(raw: dict, key: str, allowed: tuple, default: str):
    value = raw.get(key)
    return value if value in allowed else default


def default_survey(survey_id='main', title='استبيان الزوار', description='شاركنا رأيك في دقائق.') -> dict:
    return {
        'id': survey_id, 'title': title, 'description': description, 'completion': SURVEY_COMPLETION,
        'presentation': 'one_page', 'show_progress': True, 'submit_label': SURVEY_SUBMIT_LABEL,
    }


def default_config(title='صفحة جديدة', kind='agency') -> dict:
    return {
        'title': title, 'subtitle': 'مرحبًا بك في تجربتنا التفاعلية', 'description': '',
        **dict(COLORS),
        'font': 'system', 'template': 'fintech', 'card_style': 'soft', 'hero_style': 'split',
        'button_style': 'rounded', 'nav_style': 'clean', 'density': 'comfortable',
        'content_width': 'wide', 'heading_scale': 'balanced', 'radius': 22,
        'logo': '', 'logo_dark': '', 'favicon': '', 'cover': '', 'welcome': True,
        'start': '', 'end': '', 'location': '', 'phone': '', 'website': '',
        'expected_entities': 70 if kind == 'event' else 0,
        'privacy': 'بيانات التعريف اختيارية. لا تُشارك مع الجهات الأخرى تلقائيًا.',
        'rating_criteria': [dict(item) for item in DEFAULT_RATING_CRITERIA],
        'access_control': AccessPolicy.defaults().to_dict(),
        'surveys': [default_survey()],
        'sections': [
            {'key': key, 'title': title_, 'enabled': True, 'order': index, 'layout': 'cards', 'preview_count': 3}
            for index, (key, title_) in enumerate(SECTIONS)
        ],
        'records': [],
    }


def _split_list(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split('|') if item.strip()]
    return value


def _question_options(raw: dict) -> list[dict]:
    options_raw = _split_list(raw.get('options', []))
    if not isinstance(options_raw, list) or len(options_raw) > 50:
        fail('OPTIONS_LIMIT')
    options = []
    for index, option in enumerate(options_raw):
        if isinstance(option, str):
            option = {'key': f'o{index + 1}', 'label': option}
        if not isinstance(option, dict):
            fail('OPTION_INVALID')
        key = text(option.get('key') or f'o{index + 1}', 64, True)
        if not CODE.fullmatch(key):
            fail('OPTION_KEY')
        options.append({'key': key, 'label': text(option.get('label'), 500, True), 'media': url(option.get('media'))})
    if len({option['key'] for option in options}) != len(options):
        fail('DUPLICATE_OPTION')
    return options


def _question_fields(kind: str, raw: dict) -> dict:
    qtype = raw.get('qtype', 'single_choice')
    if qtype not in QTYPES:
        fail('QUESTION_TYPE_INVALID')
    if kind == 'poll' and qtype not in POLL_TYPES:
        fail('POLL_TYPE_UNSUPPORTED')
    options = _question_options(raw)
    if qtype in OPTION_TYPES and len(options) < 2:
        fail('OPTIONS_REQUIRED')
    if qtype not in OPTION_TYPES and options:
        fail('OPTIONS_NOT_APPLICABLE')
    low = number(raw.get('min'), 1 if qtype in SCALE_TYPES else 0)
    high = number(raw.get('max'), 5 if qtype in SCALE_TYPES else 10)
    if qtype == 'nps':
        low, high = 0, 10
    if qtype in ('rating', 'emoji', 'matrix') and (low < 0 or high > 10 or int(low) != low or int(high) != high):
        fail('SCALE_INVALID')
    if low >= high:
        fail('RANGE_INVALID')
    rows = _split_list(raw.get('rows', []))
    if not isinstance(rows, list) or len(rows) > 20:
        fail('MATRIX_ROWS_LIMIT')
    rows = [text(row, 300, True) for row in rows]
    if qtype == 'matrix' and (not rows or len(set(rows)) != len(rows)):
        fail('MATRIX_ROWS_REQUIRED')
    show_if = raw.get('show_if') or None
    if show_if:
        if not isinstance(show_if, dict) or set(show_if) != {'code', 'equals'}:
            fail('BRANCH_RULE_INVALID')
        show_if = {'code': text(show_if['code'], 64, True), 'equals': text(show_if['equals'], 500)}
    fields = {
        'qtype': qtype, 'options': options, 'required': boolean(raw.get('required')),
        'min': low, 'max': high, 'rows': rows,
        'form_id': text(raw.get('form_id') or 'main', 64, True), 'show_if': show_if,
        'show_results': boolean(raw.get('show_results', True)),
        'status': raw.get('status') if raw.get('status') in ('open', 'closed') else 'open',
        'poll_style': text(raw.get('poll_style') or 'quick', 30),
        'correct': text(raw.get('correct'), 100),
        'score': number(raw.get('score'), 1, 0, 10000),
    }
    fields.update(
        placeholder=text(raw.get('placeholder'), 180),
        min_label=text(raw.get('min_label'), 100),
        max_label=text(raw.get('max_label'), 100),
        selection_min=number(raw.get('selection_min'), 0, 0, 50),
        selection_max=number(raw.get('selection_max'), len(options) if options else 0, 0, 50),
        presentation=text(raw.get('presentation') or 'default', 30),
    )
    if qtype == 'multiple_choice' and fields['selection_max'] and fields['selection_min'] > fields['selection_max']:
        fail('SELECTION_RANGE_INVALID')
    if qtype == 'quiz' and fields['correct'] not in {option['key'] for option in options}:
        fail('QUIZ_CORRECT_REQUIRED')
    if kind == 'poll' and fields['poll_style'] == 'secret':
        fields['show_results'] = False
    return fields


def normalize_record(raw) -> dict:
    """Record value-object factory: validates and canonicalizes one content record."""
    if not isinstance(raw, dict):
        fail('RECORD_INVALID')
    kind = raw.get('kind')
    if kind not in KINDS:
        fail('RECORD_KIND_INVALID')
    record_code = text(raw.get('code'), 64, True)
    if not CODE.fullmatch(record_code):
        fail('CODE_INVALID')
    record = {
        'kind': kind, 'code': record_code,
        'title': text(raw.get('title'), 1000, True),
        'body': text(raw.get('body'), 6000),
        'media': url(raw.get('media')),
        'url': url(raw.get('url'), True),
        'order': number(raw.get('order'), 0, 0, 10000),
        'enabled': boolean(raw.get('enabled', True)),
        'start': stamp(raw.get('start')),
        'end': stamp(raw.get('end')),
        'tag': text(raw.get('tag'), 100),
        'subtype': text(raw.get('subtype'), 40),
    }
    ordered_range(record['start'], record['end'], 'DATE_RANGE')
    record['placement'] = text(raw.get('placement') or 'offers', 64)
    record['media_type'] = 'video' if raw.get('media_type') == 'video' else 'image'
    if kind == 'fact':
        record.update(
            value=number(raw.get('value')),
            unit=text(raw.get('unit'), 40),
            source=text(raw.get('source'), 500),
            display=raw.get('display') if raw.get('display') in FACT_DISPLAYS else 'number',
            maximum=number(raw.get('maximum'), 100, 1, 1e12),
        )
    if kind in ('question', 'poll'):
        record.update(_question_fields(kind, raw))
    return record


def _rating_criteria(raw: dict) -> list[dict]:
    criteria = raw.get('rating_criteria') or [dict(item) for item in DEFAULT_RATING_CRITERIA]
    if not isinstance(criteria, list) or not criteria or len(criteria) > 10:
        fail('RATING_CRITERIA_INVALID')
    clean, total = [], 0
    for item in criteria:
        if not isinstance(item, dict):
            fail('RATING_CRITERIA_INVALID')
        key = text(item.get('key'), 40, True)
        label = text(item.get('label'), 120, True)
        weight = number(item.get('weight'), 0, 0, 100)
        if not CODE.fullmatch(key):
            fail('RATING_CRITERIA_INVALID')
        clean.append({'key': key, 'label': label, 'weight': weight})
        total += weight
    if len({item['key'] for item in clean}) != len(clean) or total <= 0:
        fail('RATING_CRITERIA_INVALID')
    return clean


def _surveys(raw: dict) -> tuple[list[dict], set[str]]:
    surveys = raw.get('surveys') or [{
        'id': 'main', 'title': 'استبيان الزوار', 'description': 'شاركنا رأيك في دقائق.', 'completion': SURVEY_COMPLETION,
    }]
    if not isinstance(surveys, list) or not surveys or len(surveys) > 50:
        fail('SURVEYS_INVALID')
    clean, ids = [], set()
    for survey in surveys:
        if not isinstance(survey, dict):
            fail('SURVEYS_INVALID')
        survey_id = text(survey.get('id'), 64, True)
        if not CODE.fullmatch(survey_id) or survey_id in ids:
            fail('SURVEY_ID_INVALID')
        ids.add(survey_id)
        clean.append({
            'id': survey_id,
            'title': text(survey.get('title') or survey_id, 180, True),
            'description': text(survey.get('description'), 1000),
            'completion': text(survey.get('completion') or SURVEY_COMPLETION, 500, True),
            'presentation': survey.get('presentation') if survey.get('presentation') in ('one_page', 'stepper') else 'one_page',
            'show_progress': boolean(survey.get('show_progress', True)),
            'submit_label': text(survey.get('submit_label') or SURVEY_SUBMIT_LABEL, 80, True),
        })
    return clean, ids


def _sections(raw: dict, defaults: list[dict]) -> list[dict]:
    sections = raw.get('sections', defaults)
    if not isinstance(sections, list) or len(sections) > len(SECTIONS):
        fail('SECTIONS_INVALID')
    keys = [key for key, _ in SECTIONS]
    seen, clean = set(), []
    for index, section in enumerate(sections):
        if not isinstance(section, dict) or section.get('key') not in keys or section['key'] in seen:
            fail('SECTION_KEY')
        seen.add(section['key'])
        clean.append({
            'key': section['key'],
            'title': text(section.get('title'), 100, True),
            'enabled': boolean(section.get('enabled', True)),
            'order': number(section.get('order'), index, 0, 100),
            'layout': section.get('layout') if section.get('layout') in SECTION_LAYOUTS else 'cards',
            'preview_count': number(section.get('preview_count'), 3, 1, 6),
        })
    return clean


def _check_branching(records: list[dict]) -> None:
    """A conditional question may only depend on an earlier question of its form."""
    by_form: dict[str, dict] = {}
    for record in sorted(records, key=lambda item: item['order']):
        if record['kind'] != 'question':
            continue
        previous = by_form.setdefault(record['form_id'], {})
        if record['show_if'] and not previous.get(record['show_if']['code']):
            fail('BRANCH_MUST_REFERENCE_EARLIER_QUESTION_IN_FORM')
        previous[record['code']] = record


def normalize_config(raw) -> dict:
    """SiteConfig factory: validates a whole draft and returns its canonical form."""
    if not isinstance(raw, dict):
        fail('CONFIG_REQUIRED')
    config = default_config(text(raw.get('title'), 160, True))
    for key, limit in (('subtitle', 400), ('description', 6000), ('location', 400), ('phone', 60), ('privacy', 1500)):
        config[key] = text(raw.get(key), limit)
    for key in ('logo', 'cover', 'website'):
        config[key] = url(raw.get(key))
    for key, default in COLORS:
        config[key] = text(raw.get(key) or default, 7)
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', config[key]):
            fail('COLOR_INVALID')
    config['template'] = _choice(raw, 'template', TEMPLATES, 'fintech')
    for key, allowed, default in STYLE_CHOICES:
        config[key] = _choice(raw, key, allowed, default)
    config['radius'] = number(raw.get('radius'), 22, 0, 48)
    config['logo_dark'] = url(raw.get('logo_dark'))
    config['favicon'] = url(raw.get('favicon'))
    config['rating_criteria'] = _rating_criteria(raw)
    config['access_control'] = AccessPolicy.parse(raw.get('access_control')).to_dict()
    config['welcome'] = boolean(raw.get('welcome', True))
    config['start'], config['end'] = stamp(raw.get('start')), stamp(raw.get('end'))
    ordered_range(config['start'], config['end'], 'DATE_RANGE')
    config['surveys'], survey_ids = _surveys(raw)
    config['expected_entities'] = number(raw.get('expected_entities'), 0, 0, 100000)
    config['sections'] = _sections(raw, config['sections'])
    records = raw.get('records', [])
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        fail('RECORD_LIMIT')
    config['records'] = [normalize_record(record) for record in records]
    used_forms = {record['form_id'] for record in config['records'] if record['kind'] == 'question'}
    for form_id in sorted(used_forms - survey_ids):
        config['surveys'].append(default_survey(form_id, 'استبيان ' + form_id, ''))
        survey_ids.add(form_id)
    codes = [record['code'] for record in config['records']]
    if len(set(codes)) != len(codes):
        fail('DUPLICATE_CODE')
    _check_branching(config['records'])
    return config


def public_config_without_answer_keys(config: dict) -> dict:
    """Anonymous-safe copy: quiz answer keys never leave the server."""
    result = copy.deepcopy(config)
    for item in result.get('records', []):
        if isinstance(item, dict) and item.get('kind') == 'question':
            item.pop('correct', None)
    return result
