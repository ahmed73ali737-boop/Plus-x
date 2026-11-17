"""Eventna domain layer: entities, value objects and business rules.

Pure Python (standard library only). No web framework, ORM, driver or HTTP
status code may be imported here; tests/test_architecture.py enforces this.
The names re-exported below are the stable public vocabulary of the domain.
"""
from app.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    Gone,
    InvalidInput,
    NotFound,
    PreconditionRequired,
    RateLimited,
    Unauthenticated,
    Unavailable,
    fail,
)
from app.domain.site_config import (
    KINDS,
    QTYPES,
    SECTIONS,
    default_config,
    normalize_config,
    normalize_record,
)
from app.domain.surveys import answer_value, survey_answers, visible
from app.domain.values import CODE, boolean, now, number, stamp, text, url

__all__ = [
    'CODE', 'KINDS', 'QTYPES', 'SECTIONS',
    'Conflict', 'DomainError', 'Forbidden', 'Gone', 'InvalidInput', 'NotFound',
    'PreconditionRequired', 'RateLimited', 'Unauthenticated', 'Unavailable',
    'answer_value', 'boolean', 'default_config', 'fail', 'normalize_config',
    'normalize_record', 'now', 'number', 'stamp', 'survey_answers', 'text', 'url', 'visible',
]
