import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('adapter', 'ops/prepare_development_web.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_development_prefix_transformation(tmp_path):
    script = tmp_path / 'app.mjs'
    script.write_text("fetch('/api/health');location.pathname==='/admin';"
                      "location.pathname.split('/');const link='/e/'+slug;"
                      "const external='https://example.org/';")
    worker = tmp_path / 'sw.js'
    worker.write_text("const CACHE='px-shell-v45';key.startsWith('px-shell-');")
    adapter.prepare(tmp_path)
    source = script.read_text()
    assert "fetch('/plusx/api/health')" in source
    assert "==='/plusx/admin'" in source
    assert "slice(6).split('/')" in source
    assert "'/plusx/e/'" in source
    assert 'https://example.org/' in source
    assert 'px-shell-' not in worker.read_text()
    assert 'plusx-development-shell-' in worker.read_text()


def test_html_and_runtime_media_stay_under_mount(tmp_path):
    html = tmp_path / 'index.html'
    html.write_text('<a href="/">Home</a><script src="/assets/app.mjs"></script>')
    ui = tmp_path / 'ui.mjs'
    ui.write_text('e.setAttribute(k,v===true?\'\':String(v));')
    manifest = tmp_path / 'manifest.webmanifest'
    manifest.write_text('{"scope":"/","start_url":"/","src":"/assets/icon.png"}')
    adapter.prepare(tmp_path)
    assert 'href="/plusx/"' in html.read_text()
    assert 'src="/plusx/assets/app.mjs"' in html.read_text()
    assert "!v.startsWith('/plusx/')" in ui.read_text()
    assert '"scope":"/plusx/"' in manifest.read_text()
    assert '/plusx/assets/icon.png' in manifest.read_text()
