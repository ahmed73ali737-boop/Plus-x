"""Independent switches plus optional account/event pilot scope; prior delivery stays readable."""
from dataclasses import dataclass
import os,re
from app.core.settings import env_bool

def pilot_ids(name):
    raw=os.environ.get(name,'').strip()
    if not raw:return frozenset()
    values=raw.split(',')
    if len(values)>1000 or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value.strip()) for value in values):
        raise RuntimeError('CERTIFICATE_PILOT_SCOPE_INVALID')
    return frozenset(value.strip() for value in values)

@dataclass(frozen=True)
class CertificateFeatures:
    admin_enabled: bool = False
    accept_new_requests: bool = False
    pilot_accounts: frozenset = frozenset()
    pilot_events: frozenset = frozenset()

    def account_allowed(self,owner):
        return not self.pilot_accounts or owner in self.pilot_accounts

    def link_allowed(self,owner,event):
        return self.account_allowed(owner) and (not self.pilot_events or event in self.pilot_events)

def certificate_features():
    return CertificateFeatures(admin_enabled=env_bool('PX_SELF_CERTIFICATES_ADMIN'),
        accept_new_requests=env_bool('PX_SELF_CERTIFICATES_ACCEPT_NEW'),
        pilot_accounts=pilot_ids('PX_SELF_CERTIFICATE_PILOT_ACCOUNTS'),
        pilot_events=pilot_ids('PX_SELF_CERTIFICATE_PILOT_EVENTS'))
