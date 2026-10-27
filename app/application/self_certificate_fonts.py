"""Pinned local fonts with immutable catalog history and bounded stat-aware caches."""
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json,re,os
from pathlib import Path
from fontTools.ttLib import TTFont
from PIL import ImageFont
from app.domain import fail

RESOURCE_ROOT=Path(os.environ.get('PX_SELF_CERTIFICATE_RESOURCE_ROOT') or Path(__file__).resolve().parents[1]/'resources').resolve()
ROOT=RESOURCE_ROOT/'fonts'
MANIFEST_HASH='55b610806ba10b908aae4009f542f5cdbe072abc7eeca66d446b26e76cc73c33'
HISTORICAL_CATALOGS=('55b610806ba10b908aae4009f542f5cdbe072abc7eeca66d446b26e76cc73c33',)
SHAPING='portable-reshaper-bidi-v1'
_ISOLATED_MANIFEST=None
_ISOLATED_BYTES={}
_ISOLATED_COVERAGE={}

@lru_cache(maxsize=24)
def _verified(path,modified,changed,size,digest,maximum):
    if size>maximum:fail('FONT_FILE_UNAVAILABLE',503)
    try:raw=Path(path).read_bytes()
    except OSError:fail('FONT_FILE_UNAVAILABLE',503)
    if len(raw)!=size or sha256(raw).hexdigest()!=digest:fail('FONT_FILE_UNAVAILABLE',503)
    return raw

def _read(path,digest,maximum=8*1024*1024):
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):fail('FONT_MANIFEST_INVALID')
    try:
        stat=path.stat()
        return _verified(str(path),stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,digest,maximum)
    except OSError:fail('FONT_FILE_UNAVAILABLE',503)

def catalog(digest=None):
    digest=digest or MANIFEST_HASH
    path=ROOT/'noto-manifest.json' if digest==MANIFEST_HASH else ROOT/'catalogs'/(digest+'.json')
    try:raw=_read(path,digest,128*1024)
    except Exception:fail('FONT_CATALOG_UNAVAILABLE',503)
    return {r['id']:r for r in json.loads(raw)}

def font_bytes(ident,digest=None):
    if digest is None:
        row=catalog().get(ident)
        if not row:fail('FONT_UNAVAILABLE')
        digest=row['sha256']
    if _ISOLATED_MANIFEST is not None:
        raw=_ISOLATED_BYTES.get((ident,digest))
        if raw is None:fail('FONT_MANIFEST_INVALID')
        return raw
    return _read(ROOT/(digest+'.ttf'),digest)

@lru_cache(maxsize=20)
def _coverage(raw):
    with TTFont(BytesIO(raw)) as font:return frozenset(font.getBestCmap())

def coverage(ident,digest=None):
    if _ISOLATED_MANIFEST is not None:
        if digest is None:digest=(_ISOLATED_MANIFEST['primary_sha256'] if ident==_ISOLATED_MANIFEST['primary_id'] else _ISOLATED_MANIFEST['fallback_sha256'])
        value=_ISOLATED_COVERAGE.get((ident,digest))
        if value is None:fail('FONT_MANIFEST_INVALID')
        return value
    return _coverage(font_bytes(ident,digest))

def choices():
    return [dict(id=r['id'],family=r['family'],weight=r['weight'])
        for r in catalog().values() if r['family']!='NotoKufiArabic']

def _manifest(ident,rows):
    row=rows.get(ident)
    if not row or row['family']=='NotoKufiArabic':fail('FONT_SHAPING_UNSUPPORTED')
    fallback=('NotoSans' if 'Arabic' in row['family'] else 'NotoSansArabic')+'-'+row['weight']
    return dict(primary_id=ident,primary_sha256=row['sha256'],fallback_id=fallback,
        fallback_sha256=rows[fallback]['sha256'],shaping=SHAPING)

def manifest(ident):
    if not isinstance(ident,str):fail('FONT_SHAPING_UNSUPPORTED')
    saved=_manifest(ident,catalog())
    font_bytes(ident,saved['primary_sha256']);font_bytes(saved['fallback_id'],saved['fallback_sha256'])
    return saved

def validate_manifest(saved):
    if _ISOLATED_MANIFEST is not None:
        if saved!=_ISOLATED_MANIFEST:fail('FONT_MANIFEST_INVALID')
        return saved
    if not isinstance(saved,dict) or saved.get('shaping')!=SHAPING:fail('FONT_MANIFEST_INVALID')
    candidates=(MANIFEST_HASH,*[h for h in HISTORICAL_CATALOGS if h!=MANIFEST_HASH])
    for digest in candidates:
        try:expected=_manifest(saved.get('primary_id'),catalog(digest))
        except Exception:continue
        if saved==expected:
            font_bytes(saved['primary_id'],saved['primary_sha256'])
            font_bytes(saved['fallback_id'],saved['fallback_sha256'])
            return saved
    fail('FONT_MANIFEST_INVALID')

def prepare_isolated_resources(saved):
    global _ISOLATED_MANIFEST,_ISOLATED_BYTES,_ISOLATED_COVERAGE
    _ISOLATED_MANIFEST=None;_ISOLATED_BYTES={};_ISOLATED_COVERAGE={}
    validate_manifest(saved)
    for role in ('primary','fallback'):
        ident,digest=saved[role+'_id'],saved[role+'_sha256']
        raw=font_bytes(ident,digest)
        _ISOLATED_BYTES[(ident,digest)]=raw
        _ISOLATED_COVERAGE[(ident,digest)]=_coverage(raw)
    _ISOLATED_MANIFEST=dict(saved)

def supports(value,saved):
    validate_manifest(saved)
    available=coverage(saved['primary_id'],saved['primary_sha256'])|coverage(saved['fallback_id'],saved['fallback_sha256'])
    return all(ord(c) in available for c in value)

def runs(value,saved,size,direction):
    from arabic_reshaper import ArabicReshaper
    from bidi import get_display
    validate_manifest(saved)
    shaped=ArabicReshaper(configuration={'delete_harakat':False,'shift_harakat_position':True}).reshape(value)
    try:visual=get_display(shaped,base_dir='R' if direction=='rtl' else 'L')
    except (AssertionError,KeyError):fail('NAME_DIRECTION_UNSUPPORTED')
    primary,fallback=saved['primary_id'],saved['fallback_id']
    hashes={primary:saved['primary_sha256'],fallback:saved['fallback_sha256']}
    maps={ident:coverage(ident,digest) for ident,digest in hashes.items()}
    grouped=[]
    for char in visual:
        ident=primary if ord(char) in maps[primary] else fallback
        if ord(char) not in maps[ident]:fail('NAME_GLYPH_UNSUPPORTED')
        if grouped and grouped[-1][0]==ident:grouped[-1][1]+=char
        else:grouped.append([ident,char])
    return [(ImageFont.truetype(BytesIO(font_bytes(ident,hashes[ident])),size,layout_engine=ImageFont.Layout.BASIC),text) for ident,text in grouped]
