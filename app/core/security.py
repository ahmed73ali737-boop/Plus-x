from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from app.domain import fail


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int = 12
    max_length: int = 256
    scrypt_n: int = 16384
    scrypt_r: int = 8
    scrypt_p: int = 1


DEFAULT_PASSWORD_POLICY = PasswordPolicy()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str, policy: PasswordPolicy = DEFAULT_PASSWORD_POLICY) -> str:
    if not isinstance(password, str) or not policy.min_length <= len(password) <= policy.max_length:
        fail('PASSWORD_12_TO_256_CHARACTERS')
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(
        password.encode(),
        salt=salt.encode(),
        n=policy.scrypt_n,
        r=policy.scrypt_r,
        p=policy.scrypt_p,
    ).hex()
    return f'{salt}:{derived}'


def verify_password(password: str, encoded: str, policy: PasswordPolicy = DEFAULT_PASSWORD_POLICY) -> bool:
    if not isinstance(password, str) or len(password) > policy.max_length:
        return False
    try:
        salt, expected = encoded.split(':', 1)
        actual = hashlib.scrypt(
            password.encode(),
            salt=salt.encode(),
            n=policy.scrypt_n,
            r=policy.scrypt_r,
            p=policy.scrypt_p,
        ).hex()
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def new_temporary_password() -> str:
    return secrets.token_urlsafe(18)
