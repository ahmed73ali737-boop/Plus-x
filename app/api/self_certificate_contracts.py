"""HTTP contracts (pydantic) for the self-certificate API.

Explicit public projections. Never serialize database rows to public pages.
The participant submission rule itself is app.domain.self_certificates.
"""
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.self_certificates import participant_submission

class LinkState(StrEnum):
    ACTIVE = 'active'
    PAUSED = 'paused'

class RequestState(StrEnum):
    REGISTERED = 'registered'
    PROCESSING = 'processing'
    FAILED = 'failed'
    ISSUED = 'issued'

class PublicCertificate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    serial: str
    name_printed: str
    event_name: str
    issued_at: str
    status: str
    basis: str = 'self_declaration'

class PublicRequestState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: RequestState
    error_code: str | None = None
    certificate: PublicCertificate | None = None
    receive_url: str | None = None
    verification_url: str | None = None

class ParticipantInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=250)
    phone: str = Field(min_length=1, max_length=60)
    consent: bool
    request_nonce: str = Field(min_length=20, max_length=200)

    @field_validator('consent', mode='before')
    @classmethod
    def affirmative_consent(cls, value):
        if value is not True:
            raise ValueError('CONSENT_REQUIRED')
        return value

    @field_validator('name', 'phone')
    @classmethod
    def nonblank_text(cls, value, info):
        if not value.strip():
            raise ValueError('INVALID_NAME' if info.field_name == 'name' else 'PHONE_REQUIRED')
        return value

def parse_participant_input(body):
    """Service guard runs before any request/job insertion; no PII in errors."""
    return participant_submission(body)

PUBLIC_CERTIFICATE_FIELDS = ('serial', 'name_printed', 'event_name', 'issued_at', 'status')

def public_certificate(values):
    return PublicCertificate(**{k: values[k] for k in PUBLIC_CERTIFICATE_FIELDS}).model_dump()
