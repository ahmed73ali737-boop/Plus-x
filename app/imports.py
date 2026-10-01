"""Bounded CSV/XLSX input; reused and generalized from the prior restricted OOXML reader."""
import base64, csv, io, json, importlib.util
from pathlib import Path
from fastapi import HTTPException
from .domain import fail, normalize_record, boolean
spec=importlib.util.spec_from_file_location('restricted_xlsx',Path(__file__).with_name('xlsx_reader.py'))
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
SHEETS={'Participants':'participant','Sponsors':'sponsor','Sessions':'session','Places':'place','Facts':'fact','Services':'service','Polls':'poll','Offers':'offer','Ads':'ad','Media':'media','Contacts':'contact','News':'news','Questions':'question','QuestionBank':'question'}
COMMON=['code','title','body','media','media_type','url','order','enabled','start','end','tag','placement','value','unit','source','display','maximum','qtype','required','min','max','form_id','options','rows','show_if_code','show_if_equals','status','show_results','subtype','poll_style','correct','score']

def objects(rows):
    if not rows: return []
    headers=[str(x).strip() for x in rows[0]]
    if len(set(headers))!=len(headers) or any(not h for h in headers): fail('DUPLICATE_OR_EMPTY_HEADERS')
    out=[]
    for rowno,row in enumerate(rows[1:],2):
        if not any(x!='' for x in row): continue
        if len(row)>len(headers): fail('ROW_WIDTH')
        out.append((rowno,{h:row[i] if i<len(row) else '' for i,h in enumerate(headers)}))
    return out

def parse(body):
    if 'csv' in body:
        val=body['csv']
        if not isinstance(val,str) or len(val.encode())>3*1024*1024: fail('CSV_LIMIT')
        if '\x00' in val: fail('CSV_NUL')
        try: table=list(csv.reader(io.StringIO(val.lstrip('\ufeff')),strict=True))
        except csv.Error: fail('CSV_INVALID')
        kind=body.get('kind')
        if kind not in SHEETS.values(): fail('IMPORT_KIND')
        tables={next(k for k,v in SHEETS.items() if v==kind):table}
    else:
        name=body.get('name','')
        if not isinstance(name,str) or not name.lower().endswith('.xlsx'): fail('XLSX_REQUIRED')
        try: data=base64.b64decode(body.get('base64',''),validate=True)
        except Exception: fail('BASE64_INVALID')
        try: tables=reader.parse_xlsx(data)['workbook']
        except reader.Rejected as e: fail(str(e))
        except Exception: fail('XLSX_INVALID')
    options={}
    for rowno,o in objects(tables.get('Options',[])):
        key=o.get('question_code','');options.setdefault(key,[]).append({'key':o.get('option_key') or o.get('key'),'label':o.get('label_ar') or o.get('label'),'media':o.get('media','')})
    records=[];errors=[];unknown=[]
    for sheet,rows in tables.items():
        if sheet not in SHEETS:
            if sheet not in ('Options','Guide'):unknown.append(sheet)
            continue
        if len(rows)>501: fail('MAX_500_ROWS_PER_SHEET')
        for rowno,r in objects(rows):
            try:
                if sheet=='QuestionBank':
                    raw={'kind':'question','code':r.get('external_code'),'title':r.get('text_ar'),'qtype':r.get('type_code'),'required':r.get('required'),'min':r.get('min_value'),'max':r.get('max_value'),'tag':r.get('category'),'order':rowno,'options':options.get(r.get('external_code'),[])}
                else:
                    if set(r)-set(COMMON): fail('UNKNOWN_COLUMN:'+','.join(set(r)-set(COMMON)))
                    raw={**r,'kind':SHEETS[sheet]}
                    if raw.get('show_if_code'):raw['show_if']={'code':raw['show_if_code'],'equals':str(raw.get('show_if_equals',''))}
                    if options.get(raw.get('code')):raw['options']=options[raw['code']]
                    if raw.get('enabled')=='': raw['enabled']=True
                    if raw.get('show_results')=='': raw['show_results']=True
                    if not raw.get('qtype'):raw['qtype']='single_choice'
                    if not raw.get('order'):raw['order']=rowno
                records.append(normalize_record(raw))
            except HTTPException as e:errors.append({'sheet':sheet,'row':rowno,'error':e.detail})
    if len(records)>2000: fail('IMPORT_TOTAL_LIMIT')
    if not records and not errors: errors.append({'sheet':'','row':0,'error':'NO_RECORDS'})
    codes=set()
    for r in records:
        if r['code'] in codes:errors.append({'sheet':'','row':0,'error':'DUPLICATE_CODE:'+r['code']})
        codes.add(r['code'])
    return records,errors,unknown
