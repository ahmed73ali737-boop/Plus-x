from hashlib import sha256
import pytest
from fastapi import HTTPException
from app.application.self_certificate_storage import CertificateStore

def test_private_storage_roundtrip_integrity_and_missing_file(tmp_path):
    store=CertificateStore(tmp_path/'private')
    asset=store.put(b'immutable synthetic certificate')
    assert store.read(asset)==b'immutable synthetic certificate'
    assert asset['sha256']==sha256(b'immutable synthetic certificate').hexdigest()
    assert '/' in asset['storage_key']
    store.path(asset['storage_key']).write_bytes(b'tampered')
    with pytest.raises(HTTPException) as exc:store.read(asset)
    assert exc.value.detail=='FINAL_FILE_UNAVAILABLE'
    store.path(asset['storage_key']).unlink()
    with pytest.raises(HTTPException):store.read(asset)

@pytest.mark.parametrize('key',['../secret','/etc/passwd','ab/../../secret','C:\\secret','ab/'+'a'*64+'/extra','ab/'+'A'*64])
def test_storage_rejects_user_paths(tmp_path,key):
    store=CertificateStore(tmp_path/'private')
    with pytest.raises(HTTPException):store.path(key)

def test_cleanup_configuration_cannot_remove_fresh_in_flight_assets(tmp_path):
    from app.application.self_certificate_storage import cleanup_unreferenced
    with pytest.raises(ValueError):cleanup_unreferenced(None,CertificateStore(tmp_path),minimum_age_hours=0)
