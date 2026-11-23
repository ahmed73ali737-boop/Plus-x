"""Platform administrator settings for the messaging provider, with the environment as the fallback and a reachability test."""
import json

from app.application.ports import persistence
from app.domain import now
from app.domain import messaging_provider as rules

KEY = 'messaging'


require_platform = rules.require_platform


def stored(tx):
    row = persistence.integration_settings.get(tx, KEY)
    return rules.parse(row['value']) if row else None


def effective_config(tx):
    """(url, key) from the stored choice when there is one (even 'disabled'), else from the environment; None = not configured."""
    setting = stored(tx)
    if setting is None:
        return persistence.phone_verifier.environment_config()
    if setting['provider'] != 'channel_gateway':
        return None
    key = persistence.phone_verifier.key_from_ref(setting['key_ref'])
    return (setting['url'], key) if key else None


def view(tx):
    setting = stored(tx)
    env = persistence.phone_verifier.environment_config() is not None
    out = {'providers': {k: {'title': v['title'], 'fields': list(v['fields'])} for k, v in rules.PROVIDERS.items()},
           'source': 'settings' if setting else ('environment' if env else 'none'),
           'setting': setting or dict(rules.DEFAULT)}
    out['active'] = effective_config(tx) is not None
    if setting and setting['provider'] == 'channel_gateway':
        out['key_ref_resolves'] = bool(persistence.phone_verifier.key_from_ref(setting['key_ref']))
    return out


def save(tx, user, body):
    require_platform(user)
    setting = rules.validate(body)
    persistence.integration_settings.put(tx, KEY, json.dumps(setting), now(), user['id'])
    return view(tx)


def test(tx, user):
    require_platform(user)
    cfg = effective_config(tx)
    if cfg is None:
        return {'configured': False, 'reachable': False}
    return {'configured': True, **persistence.phone_verifier.probe(cfg)}
