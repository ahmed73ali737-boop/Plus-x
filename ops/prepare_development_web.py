"""Prepare an isolated development image for the fixed /plusx mount.

The root deployment's checked-in web assets remain untouched. No shared host
root routes are claimed. This adapter is intentionally development-only.
"""
from pathlib import Path
import re


def prepare(root: Path):
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix not in {'.html', '.mjs', '.js', '.css', '.webmanifest'}:
            continue
        source = path.read_text()
        source = re.sub(r'''(["'`(])/(?!/)(?=(?:assets|api|media|templates|admin|account|certificates|certificate|verify|invite|start|live|e|sw\.js)(?:[/"'`?#)]|$))''', r'\1/plusx/', source)
        source = source.replace('location.pathname.split', 'location.pathname.slice(6).split')
        source = source.replace("href:'/'", "href:'/plusx/'").replace('href="/"', 'href="/plusx/"')
        source = source.replace("href='/'", "href='/plusx/'")
        # Only this image owns these namespaces. Never migrate/delete the old
        # shared database: it may contain another app's pending work.
        source = source.replace("'pulsex-pilot-02'", "'plusx-development-pilot-02'")
        source = source.replace("'px-media-v02'", "'plusx-development-media-v02'")
        source = source.replace("const MOUNT='/'", "const MOUNT='/plusx/'")
        source = source.replace("kind==='platform')return'/'", "kind==='platform')return'/plusx/'")
        if path.name == 'guest.mjs':
            source = source.replace(r"/^\/E\/", r"/^\/PLUSX\/E\/")
        if path.name == 'ui.mjs':
            # Runtime bundle values (for example seeded media) also use root URLs.
            source = source.replace("String(v));", "String(['href','src','poster'].includes(k)&&typeof v==='string'&&v.startsWith('/')&&!v.startsWith('//')&&!v.startsWith('/plusx/')?'/plusx'+v:v));")
        if path.name == 'manifest.webmanifest':
            source = source.replace('"/"', '"/plusx/"')
        if path.name == 'sw.js':
            source = source.replace("'px-shell-", "'plusx-development-shell-")
        path.write_text(source)


if __name__ == '__main__':
    prepare(Path('/app/web'))
