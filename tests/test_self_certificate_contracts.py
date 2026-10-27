import pytest
from pydantic import ValidationError
from app.application.self_certificate_contracts import public_certificate, ParticipantInput, PublicRequestState
from app.core.certificate_features import certificate_features

def test_public_certificate_projection_never_serializes_private_fields():
    result=public_certificate(dict(serial='TEST',name_printed='اسم مطبوع',event_name='اختبار',issued_at='2026-10-22',status='issued',phone='0770000000',owner_account_id='private',browser_token='secret',participant_name_original='original',stamp_asset_id='private'))
    assert set(result)=={'serial','name_printed','event_name','issued_at','status','basis'}
    assert result['basis']=='self_declaration'

def test_public_input_rejects_owner_injection_and_boolean_coercion():
    payload=dict(name='اسم',phone='0770000000',consent=True,request_nonce='x'*32)
    assert ParticipantInput(**payload).consent is True
    for change in ({'owner_account_id':'another'},{'consent':'true'},{'request_nonce':''}):
        with pytest.raises(ValidationError): ParticipantInput(**{**payload,**change})
    with pytest.raises(ValidationError): PublicRequestState(status='issued',phone='private')

def test_rollout_defaults_disabled_and_switches_are_independent(monkeypatch):
    for name in ('PX_SELF_CERTIFICATES_ADMIN','PX_SELF_CERTIFICATES_ACCEPT_NEW'): monkeypatch.delenv(name,raising=False)
    assert not certificate_features().admin_enabled
    assert not certificate_features().accept_new_requests
    monkeypatch.setenv('PX_SELF_CERTIFICATES_ADMIN','true')
    assert certificate_features().admin_enabled and not certificate_features().accept_new_requests

@pytest.mark.parametrize('consent',[False,None,0,1,'true','false'])
def test_v2_consent_requires_the_actual_true_boolean(consent):
    with pytest.raises(ValidationError):
        ParticipantInput(name='محمد',phone='0770000000',consent=consent,request_nonce='n'*32)

@pytest.mark.parametrize('field',['name','phone'])
def test_v2_whitespace_only_input_is_not_a_participant(field):
    with pytest.raises(ValidationError):
        ParticipantInput(**{**dict(name='محمد',phone='0770000000',consent=True,request_nonce='n'*32),field:'  \t '})

