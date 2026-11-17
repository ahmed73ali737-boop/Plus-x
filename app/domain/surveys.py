"""Survey and poll answer rules, evaluated against a published site configuration."""
from __future__ import annotations

import re
from datetime import datetime

from app.domain.errors import NotFound, fail
from app.domain.values import number, text, url

CHOICE_TYPES = ('single_choice', 'dropdown', 'image_choice')
NUMERIC_TYPES = ('number', 'currency', 'rating', 'nps', 'slider', 'emoji')
INTEGER_TYPES = ('rating', 'nps', 'emoji')
TIME_PATTERN = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?')


def visible(question: dict, answers: dict) -> bool:
    """A conditional question is shown only when its branch rule matches."""
    rule = question.get('show_if')
    if not rule:
        return True
    answer = answers.get(rule['code'])
    expected = rule['equals']
    return expected in answer if isinstance(answer, list) else str(answer).lower() == expected.lower()


def _is_empty(value) -> bool:
    return value is None or value == '' or value == [] or value == {}


def _multi_choice(question: dict, value, keys: list[str]):
    qtype = question['qtype']
    if not isinstance(value, list) or any(item not in keys for item in value) or len(set(value)) != len(value):
        fail('ANSWER_OPTIONS')
    if qtype == 'multiple_choice':
        if question.get('selection_min', 0) and len(value) < question['selection_min']:
            fail('SELECTION_MIN_NOT_MET')
        if question.get('selection_max', 0) and len(value) > question['selection_max']:
            fail('SELECTION_MAX_EXCEEDED')
    if qtype == 'ranking' and set(value) != set(keys):
        fail('RANKING_MUST_INCLUDE_ALL_OPTIONS')
    return value


def _allocation(value, keys: list[str]):
    if not isinstance(value, dict) or set(value) - set(keys):
        fail('ALLOCATION_ANSWER')
    value = {key: number(amount, 0, 0, 100) for key, amount in value.items()}
    if round(sum(value.values()), 6) != 100:
        fail('ALLOCATION_TOTAL_100')
    return value


def _matrix(question: dict, value):
    if not isinstance(value, dict) or any(key not in question['rows'] for key in value):
        fail('MATRIX_ANSWER')
    if question['required'] and set(value) != set(question['rows']):
        fail('MATRIX_ROWS_REQUIRED')
    return {key: number(score, 0, question['min'], question['max']) for key, score in value.items()}


def _date(value):
    value = text(value, 40, True)
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        fail('DATE_INVALID')
    return value


def _time(value):
    value = text(value, 20, True)
    if not TIME_PATTERN.fullmatch(value):
        fail('TIME_INVALID')
    return value


def _datetime(value):
    value = text(value, 50, True)
    try:
        datetime.fromisoformat(value)
    except ValueError:
        fail('DATETIME_INVALID')
    return value


def _email(value):
    value = text(value, 200, True).lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        fail('EMAIL_INVALID')
    return value


def _phone(value):
    value = text(value, 40, True)
    if not re.fullmatch(r'[+0-9 ()-]{5,40}', value):
        fail('PHONE_INVALID')
    return value


def _consent(value):
    if value not in (True, 'true', 'yes', '1', 1):
        fail('CONSENT_REQUIRED')
    return True


def answer_value(question: dict, value):
    """Validate one answer against its question; None when optional and empty."""
    qtype = question['qtype']
    keys = [option['key'] for option in question['options']]
    if _is_empty(value):
        if question['required']:
            fail('ANSWER_REQUIRED:' + question['code'])
        return None
    if qtype in CHOICE_TYPES or qtype == 'quiz':
        if value not in keys:
            fail('ANSWER_OPTION')
        return value
    if qtype in ('multiple_choice', 'ranking'):
        return _multi_choice(question, value, keys)
    if qtype == 'allocation':
        return _allocation(value, keys)
    if qtype == 'yes_no':
        if value not in ('yes', 'no'):
            fail('ANSWER_YES_NO')
        return value
    if qtype in NUMERIC_TYPES:
        value = number(value, 0, question['min'], question['max'])
        if qtype in INTEGER_TYPES and int(value) != value:
            fail('INTEGER_REQUIRED')
        return value
    if qtype == 'matrix':
        return _matrix(question, value)
    parsers = {'date': _date, 'time': _time, 'datetime': _datetime, 'email': _email,
               'phone': _phone, 'url': url, 'consent': _consent}
    if qtype in parsers:
        return parsers[qtype](value)
    return text(value, 4000 if qtype == 'long_text' else 500)


def survey_answers(config: dict, form_id: str, answers) -> dict:
    """Validate a complete survey submission for one form of a published config."""
    if not isinstance(answers, dict):
        fail('ANSWERS_INVALID')
    questions = sorted(
        [record for record in config['records']
         if record['kind'] == 'question' and record['enabled'] and record['form_id'] == form_id],
        key=lambda record: record['order'],
    )
    if not questions:
        fail('FORM_NOT_FOUND', NotFound)
    if set(answers) - {question['code'] for question in questions}:
        fail('UNKNOWN_QUESTION')
    clean = {}
    for question in questions:
        if visible(question, answers):
            value = answer_value(question, answers.get(question['code']))
            if value is not None:
                clean[question['code']] = value
    if not clean:
        fail('EMPTY_ANSWERS')
    return clean


def ballot_items(qtype, value) -> list:
    """Countable items of one answer; rankings count each option at its rank."""
    if qtype == 'ranking':
        return [f'{item} / rank {index + 1}' for index, item in enumerate(value)]
    return value if isinstance(value, list) else [value]
