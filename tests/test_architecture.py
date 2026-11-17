"""Architecture fitness tests: the dependency rule is enforced, not just documented.

domain          -> standard library (+ other domain modules) only
application     -> domain, application, framework-free app.core helpers, app.xlsx_reader
infrastructure  -> domain, app.core, persistence libraries, and app.application.ports only
api / server    -> anything (presentation + composition root), but never SQL
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
FRAMEWORKS = {'fastapi', 'starlette', 'pydantic', 'uvicorn'}
PERSISTENCE = {'sqlalchemy', 'psycopg', 'psycopg2', 'sqlite3'}
LEGACY_TABLE_ALIASES = {'app.db', 'app.invitations_db', 'app.certificates_db', 'app.self_certificates_db',
                        'app.account_requests_db'}
APPLICATION_ALLOWED_CORE = {'app.core.security', 'app.core.serialization', 'app.core.certificate_features'}


def modules(layer: str) -> list[Path]:
    return sorted((APP / layer).rglob('*.py'))


def imported_names(path: Path) -> set[str]:
    """Absolute module names imported by a file (relative imports resolved)."""
    package = '.'.join(path.relative_to(ROOT).with_suffix('').parts[:-1])
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split('.')
                base = base[:len(base) - node.level + 1]
                module = '.'.join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ''
            found.add(module)
            found |= {module + '.' + alias.name for alias in node.names}
    return found


def roots(names: set[str]) -> set[str]:
    return {name.split('.')[0] for name in names}


def offenders(layer: str, rule) -> dict[str, list[str]]:
    result = {}
    for path in modules(layer):
        bad = sorted(name for name in imported_names(path) if rule(name))
        if bad:
            result[str(path.relative_to(ROOT))] = bad
    return result


def test_domain_is_pure_python():
    def forbidden(name):
        return (name.split('.')[0] in FRAMEWORKS | PERSISTENCE
                or (name.startswith('app.') and not name.startswith('app.domain')))
    assert offenders('domain', forbidden) == {}


def test_application_depends_only_on_domain_and_ports():
    allowed_prefixes = ('app.domain', 'app.application', 'app.xlsx_reader') + tuple(APPLICATION_ALLOWED_CORE)

    def forbidden(name):
        if name.split('.')[0] in FRAMEWORKS | PERSISTENCE:
            return True
        return name.startswith('app.') and not name.startswith(allowed_prefixes) or name in LEGACY_TABLE_ALIASES
    assert offenders('application', forbidden) == {}


def test_core_helpers_used_by_application_are_framework_free():
    for name in APPLICATION_ALLOWED_CORE:
        path = ROOT / (name.replace('.', '/') + '.py')
        assert not roots(imported_names(path)) & (FRAMEWORKS | PERSISTENCE), name


def test_infrastructure_never_imports_web_framework_or_use_cases():
    def forbidden(name):
        if name.split('.')[0] in FRAMEWORKS:
            return True
        if name.startswith('app.api') or name == 'app.server':
            return True
        return name.startswith('app.application') and not name.startswith('app.application.ports')
    assert offenders('infrastructure', forbidden) == {}


@pytest.mark.parametrize('layer', ['api'])
def test_presentation_runs_no_sql(layer):
    paths = modules(layer) + [APP / 'server.py']
    for path in paths:
        names = imported_names(path)
        assert not roots(names) & PERSISTENCE, path
        assert not names & LEGACY_TABLE_ALIASES, path


# Locked G-Factory telemetry adapter (components/g-observability/source-lock.json):
# it records the HTTP status of a response as a span attribute.
HTTP_TELEMETRY_ADAPTER = APP / 'infrastructure' / 'g_observability.py'


@pytest.mark.parametrize('layer', ['domain', 'application', 'infrastructure'])
def test_inner_layers_never_speak_http(layer):
    for path in modules(layer):
        if path == HTTP_TELEMETRY_ADAPTER:
            continue
        source = path.read_text(encoding='utf-8')
        assert 'HTTPException' not in source and 'status_code' not in source, path


def test_domain_errors_never_carry_http_status_codes():
    """fail(code, kind): the second argument is an error category, never a number."""
    for layer in ('domain', 'application', 'infrastructure', 'api'):
        for path in modules(layer):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'fail' and len(node.args) > 1:
                    assert not isinstance(node.args[1], ast.Constant), f'{path}:{node.lineno}'


def test_every_port_is_implemented_by_its_sql_adapter():
    import app.application.ports as ports
    from app.infrastructure.persistence import install_sql_persistence

    install_sql_persistence()
    for name, port_name in ports.Persistence.__annotations__.items():
        protocol = getattr(ports, port_name)
        adapter = getattr(ports.persistence, name)
        declared = [member for member, value in vars(protocol).items()
                    if not member.startswith('_') and callable(value)]
        missing = [member for member in declared if not callable(getattr(adapter, member, None))]
        assert declared and not missing, (name, missing)
