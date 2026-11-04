"""UHEF help gate: every routed screen and every Studio tab is documented in web/uhef-knowledge.json.

The expected screens are read from the real router (web/app.mjs), the account router
(web/account-page.mjs) and the Studio tab list (web/admin.mjs); a new route or tab without help
fails here. The same rules run in the browser engine (EventnaHelp.problems in web/uhef-help.js)."""
import copy, json, re, shutil, subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
KNOWLEDGE = WEB / 'uhef-knowledge.json'
INPUT_KINDS = {'input', 'select', 'textarea', 'file'}

# Each branch of the router in web/app.mjs, as source text that must still exist, and its screen.
APP_ROUTES = [
    ("location.pathname==='/certificates'", 'selfcert.admin'),
    ("location.pathname==='/account'", 'account.profile'),
    ("location.pathname==='/start'", 'access.start'),
    ("location.pathname==='/admin'", 'admin.login'),
    ("parts[0]==='certificate'&&parts.length===2", 'cert.access'),
    ("parts[0]==='verify'&&parts[1]==='certificate'&&parts.length===3", 'cert.verify'),
    ("parts[0]==='invite'&&parts.length===2", 'invite.rsvp'),
    ("parts[0]==='e'&&parts[2]==='register'", 'invite.register'),
    ("parts[0]==='live'&&parts.length===2", 'live.wall'),
    ("parts[0]==='e'&&parts[2]==='guest'", 'guest.register'),
    ("parts[0]==='e'&&parts[2]==='scan'", 'gate.scan'),
    ("parts.includes('p')", 'public.agency'),
    ("parts[0]==='e'?parts[1]", 'public.event'),
    (":'platform'", 'public.platform'),
    ("class:'error-page'", 'app.error'),
]
EXTRA = {'guest.pass': ("guestPage(parts[1],parts[3]||'')", 'app.mjs'),
         'admin.password': ('function forcePasswordChange', 'admin.mjs')}


def knowledge():
    return json.loads(KNOWLEDGE.read_text(encoding='utf-8'))


def admin_tabs():
    source = (WEB / 'admin.mjs').read_text(encoding='utf-8')
    block = re.search(r"const tabs=\[(.*?)\];", source).group(1)
    return re.findall(r"\['([a-z_]+)','([^']+)'\]", block)


def expected_screens():
    app = (WEB / 'app.mjs').read_text(encoding='utf-8')
    keys = {}
    for token, key in APP_ROUTES:
        assert token in app, 'router branch changed, update help mapping: ' + token
        keys[key] = 'web/app.mjs'
    for key, (token, name) in EXTRA.items():
        assert token in (WEB / name).read_text(encoding='utf-8'), token
        keys[key] = 'web/' + name
    kinds = re.search(r"\[('request','receive','verify')\]\.includes\(parts\[1\]\)", app)
    assert kinds, 'self-certificate public kinds changed'
    for kind in re.findall(r"'([a-z]+)'", kinds.group(1)):
        keys['selfcert.' + kind] = 'web/app.mjs'
    account = (WEB / 'account-page.mjs').read_text(encoding='utf-8')
    for sub in re.findall(r"location\.pathname==='/account/([a-z]+)'\)return", account):
        keys['account.' + sub] = 'web/account-page.mjs'
    for tab, _label in admin_tabs():
        keys['admin.' + tab] = 'web/admin.mjs'
    return keys


def problems(K, keys):
    """Python twin of EventnaHelp.problems (web/uhef-help.js)."""
    out = []
    if K.get('schema') != 'uhef.knowledge/1.0':
        out.append('schema must be uhef.knowledge/1.0')
    screens, journeys = K.get('screens', {}), K.get('journeys', {})
    for key in keys:
        s = screens.get(key)
        if not s:
            out.append(key + ': not documented'); continue
        for field in ('name', 'purpose', 'why', 'whenToUse'):
            if not s.get(field):
                out.append(f'{key}: {field} is missing')
        for field, label in (('prerequisites', 'before'), ('afterwards', 'after'), ('steps', 'steps'), ('faq', 'FAQ'), ('parts', 'parts')):
            if not s.get(field):
                out.append(f'{key}: no {label}')
        for part in s.get('parts', []):
            if not part.get('use'):
                out.append(f'{key}: part "{part.get("name")}" has no roadmap')
            for target in part.get('to', []):
                if target not in screens:
                    out.append(f'{key}: part "{part.get("name")}" leads to unknown {target}')
        rel = s.get('related', {})
        for target in rel.get('prev', []) + rel.get('next', []):
            if target not in screens:
                out.append(f'{key}: related screen {target} is unknown')
        if rel.get('journey') and rel['journey'] not in journeys:
            out.append(f'{key}: unknown journey {rel["journey"]}')
        for ident, e in s.get('elements', {}).items():
            if e.get('kind', 'input') in INPUT_KINDS and not e.get('howTo'):
                out.append(f'{key}: field {ident} lacks howTo')
    for ident, j in journeys.items():
        if not j.get('guide'):
            out.append(f'journey {ident}: no operations guide')
        for step in j.get('steps', []):
            if step.get('screen') not in screens:
                out.append(f'journey {ident}: unknown screen {step.get("screen")}')
            if not step.get('actor'):
                out.append(f'journey {ident}: step without actor')
    return out


def test_every_routed_screen_and_studio_tab_is_documented():
    K = knowledge()
    keys = expected_screens()
    assert len(keys) >= 46
    assert problems(K, sorted(keys)) == []
    stale = sorted(set(K['screens']) - set(keys))
    assert stale == [], 'documented screens with no route: %s' % stale


def test_studio_tabs_bind_by_their_visible_label():
    screens = knowledge()['screens']
    for tab, label in admin_tabs():
        assert screens['admin.' + tab]['adminTab'] == label
        assert screens['admin.' + tab]['name'] == label


def test_quoted_ui_labels_exist_in_the_web_sources():
    """«…» in the knowledge names a real label; every one must appear in web/*.mjs."""
    sources = '\n'.join(p.read_text(encoding='utf-8') for p in WEB.glob('*.mjs'))
    raw = KNOWLEDGE.read_text(encoding='utf-8')
    quoted = set(re.findall(r'«([^»]+)»', raw))
    assert len(quoted) > 150
    missing = sorted(q for q in quoted if q not in sources and q.replace('\\n', '\n') not in sources)
    assert missing == []


def test_main_journeys_have_actors_and_reach_many_screens():
    K = knowledge()
    assert len(K['journeys']) >= 6
    for ident, j in K['journeys'].items():
        assert len(j['steps']) >= 3, ident
        assert all(step['actor'] and step['action'] for step in j['steps'])
    covered = {s['screen'] for j in K['journeys'].values() for s in j['steps']}
    assert {'guest.register', 'gate.scan', 'invite.rsvp', 'admin.account_requests', 'selfcert.request'} <= covered


def test_gate_catches_gaps():
    K = knowledge()
    keys = sorted(expected_screens())
    broken = copy.deepcopy(K)
    del broken['screens']['admin.audit']
    broken['screens']['gate.scan']['parts'][0]['use'] = []
    broken['screens']['public.event']['parts'][0]['to'] = ['nowhere.screen']
    broken['screens']['guest.register']['elements']['phone']['howTo'] = ''
    broken['screens']['live.wall']['related']['journey'] = 'missing-journey'
    broken['journeys']['guest-admission']['steps'][0]['screen'] = 'ghost.screen'
    found = '\n'.join(problems(broken, keys))
    for needle in ('admin.audit: not documented', 'gate.scan: part', 'has no roadmap', 'leads to unknown nowhere.screen',
                   'field phone lacks howTo', 'unknown journey missing-journey', 'unknown screen ghost.screen'):
        assert needle in found, needle
    assert problems(K, keys + ['admin.not_a_tab']) == ['admin.not_a_tab: not documented']


def test_shell_loads_help_and_precaches_it():
    html = (WEB / 'index.html').read_text(encoding='utf-8')
    assert '<script src="/assets/uhef-help.js" defer></script>' in html
    assert '<link rel="stylesheet" href="/assets/uhef-help.css">' in html
    sw = (WEB / 'sw.js').read_text(encoding='utf-8')
    for name in ('uhef-help.js', 'uhef-help.css', 'uhef-knowledge.json'):
        assert "'/assets/" + name + "'" in sw
    script = (WEB / 'uhef-help.js').read_text(encoding='utf-8')
    assert '/api/' not in script and 'innerHTML' not in script and 'eval(' not in script
    assert "'/assets/uhef-knowledge.json'" in script


def test_help_assets_are_served_with_script_csp(tmp_path):
    from fastapi.testclient import TestClient
    from app.server import create_app
    with TestClient(create_app('sqlite:///' + str(tmp_path / 'help.sqlite'), seed_demo=False)) as client:
        page = client.get('/admin')
        assert page.status_code == 200 and "script-src 'self'" in page.headers['content-security-policy']
        assert 'javascript' in client.get('/assets/uhef-help.js').headers['content-type']
        assert client.get('/assets/uhef-help.css').status_code == 200
        assert client.get('/assets/uhef-knowledge.json').json()['schema'] == 'uhef.knowledge/1.0'


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_browser_engine_agrees_with_the_gate():
    keys = json.dumps(sorted(expected_screens()))
    script = ("const H=require(process.argv[1]);const K=require(process.argv[2]);"
              "process.stdout.write(JSON.stringify(H.problems(K," + keys + ")));")
    out = subprocess.run(['node', '-e', script, str(WEB / 'uhef-help.js'), str(KNOWLEDGE)], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == []
