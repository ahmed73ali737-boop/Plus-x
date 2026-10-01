"""Restricted generic XLSX table reader adapted for Pilot 02.
No macros/formulas/external links; bounded ZIP/XML; no third-party dependencies.
This is NOT a universal Excel engine. Use named text/boolean/number sheets only.
"""
import io, json, posixpath, re, sys, zipfile
import xml.etree.ElementTree as ET
LIMIT = 3 * 1024 * 1024
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
class Rejected(ValueError): pass
def reject(message): raise Rejected(message)
def parse_xlsx(data):
    if len(data)>LIMIT: reject('FILE_LIMIT')
    try: archive=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile: reject('XLSX_NOT_ZIP')
    with archive as z:
        infos=z.infolist(); names=[i.filename for i in infos]
        if len(names)>600 or len(set(names))!=len(names): reject('ZIP_ENTRY_LIMIT_OR_DUPLICATE')
        if sum(i.file_size for i in infos)>16*1024*1024: reject('ZIP_EXPANSION_LIMIT')
        for i in infos:
            p=i.filename.lower()
            if p.startswith('/') or '..' in p.split('/') or '\\' in p: reject('ZIP_PATH_INVALID')
            if p.endswith('.bin') or 'externallinks/' in p: reject('ACTIVE_CONTENT_REJECTED')
            if i.flag_bits & 1: reject('ENCRYPTED_ZIP_REJECTED')
            if i.file_size>6*1024*1024 or i.file_size>max(i.compress_size,1)*500: reject('ZIP_EXPANSION_LIMIT')
        def xml(name):
            if name not in names: reject('XLSX_PART_MISSING')
            content=z.read(name)
            # Limit parser to UTF-8 OOXML; UTF-16/NUL encodings are rejected explicitly.
            if b'\x00' in content or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper(): reject('XML_ENTITY_REJECTED')
            try: return ET.fromstring(content)
            except ET.ParseError: reject('XML_INVALID')
        rels={}
        for rel in xml('xl/_rels/workbook.xml.rels'):
            if rel.get('TargetMode')=='External': reject('EXTERNAL_RELATIONSHIP_REJECTED')
            target=rel.get('Target','')
            if target.startswith('/'): target=target.lstrip('/')
            else: target=posixpath.normpath('xl/'+target)
            if not target.startswith('xl/') or '..' in target.split('/'): reject('RELATIONSHIP_PATH_INVALID')
            rels[rel.get('Id')]=target
        shared=[]
        if 'xl/sharedStrings.xml' in names:
            root=xml('xl/sharedStrings.xml')
            for si in root.findall('s:si',NS):
                text=''.join(e.text or '' for e in si.findall('.//s:t',NS))
                if len(text)>12000: reject('CELL_LIMIT')
                shared.append(text)
                if len(shared)>25000: reject('SHARED_STRING_LIMIT')
        result={};ignored=[]
        for sheet in xml('xl/workbook.xml').findall('s:sheets/s:sheet',NS):
            name=sheet.get('name')
            if name in ('Guide',): ignored.append(name);continue
            if name in result: reject('DUPLICATE_SHEET')
            rid=sheet.get('{'+NS['r']+'}id');target=rels.get(rid)
            if not target: reject('SHEET_RELATIONSHIP_MISSING')
            root=xml(target);rows=[];previous_row=0
            for element in root.findall('s:sheetData/s:row',NS):
                row_number=int(element.get('r','0'))
                if row_number<=previous_row or row_number>5001: reject('ROW_LIMIT_OR_ORDER')
                # Retain physical row positions for exact error row numbers.
                while len(rows)<row_number-1: rows.append([])
                previous_row=row_number; values=[]; seen=set()
                for cell in element.findall('s:c',NS):
                    if cell.find('s:f',NS) is not None: reject('FORMULA_REJECTED')
                    match=re.fullmatch(r'([A-Z]{1,3})([0-9]+)',cell.get('r',''))
                    if not match or int(match[2])!=row_number: reject('CELL_REFERENCE_INVALID')
                    col=0
                    for ch in match[1]: col=col*26+ord(ch)-64
                    if col>64 or col in seen: reject('COLUMN_LIMIT_OR_DUPLICATE')
                    seen.add(col)
                    while len(values)<col:values.append('')
                    kind=cell.get('t','n');v=cell.find('s:v',NS);raw=v.text if v is not None and v.text is not None else ''
                    if kind=='s':
                        try: idx=int(raw)
                        except ValueError: reject('SHARED_STRING_INVALID')
                        if idx<0 or idx>=len(shared): reject('SHARED_STRING_INVALID')
                        value=shared[idx]
                    elif kind=='inlineStr':value=''.join(e.text or '' for e in cell.findall('s:is//s:t',NS))
                    elif kind=='b':
                        if raw not in ('0','1'): reject('BOOLEAN_INVALID')
                        value=raw=='1'
                    elif kind in ('n','str'):value=raw
                    else: reject('CELL_TYPE_UNSUPPORTED')
                    if len(str(value))>12000:reject('CELL_LIMIT')
                    values[col-1]=value
                rows.append(values)
            # Drop empty trailing formatted rows without shifting error row numbers.
            while rows and not any(v!='' for v in rows[-1]):rows.pop()
            result[name]=rows
        if not result: reject('DATA_SHEET_REQUIRED')
        return {'workbook':result,'ignored_sheets':ignored}
def main():
    try:
        data=sys.stdin.buffer.read(LIMIT+1)
        print(json.dumps(parse_xlsx(data),ensure_ascii=False))
    except (Rejected,ValueError,KeyError,zipfile.BadZipFile):
        exc=sys.exc_info()[1]
        message=str(exc) if isinstance(exc,Rejected) else 'XLSX_INVALID'
        print(json.dumps({'error':message}));sys.exit(2)
if __name__=='__main__':main()
