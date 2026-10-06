from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_smoke_uses_dom_semantic_heading_with_windows_diagnostics():
    source = (ROOT / "tests/browser_smoke.py").read_text(encoding="utf-8")
    assert 'wait_semantic_heading(page, "#events h2", "الفعاليات الجارية والقادمة")' in source
    assert 'get_by_role("heading", name="الفعاليات الجارية والقادمة").wait_for()' not in source
    assert "browser-platform-diagnostic.json" in source
    assert "browser-platform-failure.png" in source
    assert 'sys.stdout.reconfigure(encoding="utf-8"' in source


def test_ci_forces_utf8_for_windows_and_linux_python_processes():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'PYTHONUTF8: "1"' in workflow
