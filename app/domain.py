"""Pilot domain rules. No arbitrary HTML, script expressions, or trusted client roles."""
from __future__ import annotations
import copy, json, re, math
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import HTTPException

KINDS = ('participant','sponsor','session','place','fact','service','question','poll','offer','ad','media','contact','news')
QTYPES = ('single_choice','multiple_choice','dropdown','image_choice','yes_no','short_text','long_text','number','currency','rating','nps','slider','ranking','matrix','emoji','date','time','datetime','email','phone','url','consent','allocation','quiz')
SECTIONS = [('event','الفعالية والمشاركون'),('facts','الحقائق والأرقام'),('about','عن الجهة'),('services','الخدمات'),('questions','الأسئلة والاستبيانات'),('polls','التصويت'),('ratings','التقييم والملاحظات'),('contact','التواصل والمتابعة'),('offers','الإعلانات والعروض'),('media','الصور والفيديو')]
CODE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
def fail(code: str, status: int = 422):
    raise HTTPException(status_code=status, detail=code)
def now(): return datetime.now(timezone.utc).isoformat()
def text(v, maximum=500, required=False):
    if v is None: v=''
    if not isinstance(v, (str,int,float)) or isinstance(v,bool): fail('TEXT_REQUIRED')
    v=str(v).strip()
    if len(v)>maximum or ('\x00' in v) or (required and not v): fail('TEXT_LENGTH')
    return v

def boolean(v):
    if isinstance(v,bool): return v
    if isinstance(v,str): v=v.strip().lower()
    if v in (1,'1','true','TRUE','نعم'): return True
    if v in (None,'',0,'0','false','FALSE','لا'): return False
    fail('BOOLEAN_INVALID')

def number(v, default=0, low=-1e12, high=1e12):
    if v is None or v=='': return default
    if isinstance(v,bool): fail('NUMBER_INVALID')
    try: n=float(v)
    except (ValueError,TypeError): fail('NUMBER_INVALID')
    if not math.isfinite(n) or n<low or n>high: fail('NUMBER_RANGE')
    return int(n) if n.is_integer() else n

def url(v, contact=False):
    v=text(v,2048)
    if not v: return ''
    if v.startswith('/media/') and '..' not in v: return v
    p=urlparse(v)
    if contact and p.scheme in ('mailto','tel'): return v
    if p.scheme!='https' or not p.netloc or p.username or p.password: fail('HTTPS_URL_REQUIRED')
    return v

def stamp(v):
    v=text(v,80)
    if v.startswith("'"): v=v[1:]
    if v:
        try:
            d=datetime.fromisoformat(v.replace('Z','+00:00'))
            if d.tzinfo is None: fail('TIMEZONE_REQUIRED')
        except ValueError: fail('DATETIME_INVALID')
    return v

def default_config(title='صفحة جديدة', kind='agency'):
    return {'title':title,'subtitle':'مرحبًا بك في تجربتنا التفاعلية','description':'','primary':'#176B73','secondary':'#0F3D46','accent':'#29B8A8','background':'#F5F8FA','surface':'#FFFFFF','text_color':'#17313B','font':'system','template':'fintech','card_style':'soft','hero_style':'split','button_style':'rounded','nav_style':'clean','density':'comfortable','content_width':'wide','heading_scale':'balanced','radius':22,'logo':'','logo_dark':'','favicon':'','cover':'','welcome':True,'start':'','end':'','location':'','phone':'','website':'','expected_entities':70 if kind=='event' else 0,'privacy':'بيانات التعريف اختيارية. لا تُشارك مع الجهات الأخرى تلقائيًا.','rating_criteria':[{'key':'overall','label':'التقييم العام','weight':100}], 'access_control':{'anti_passback':True,'allow_reentry':True,'manifest_max_age_minutes':7200,'guest_types':[{'key':'visitor','label':'زائر'},{'key':'vip','label':'VIP'},{'key':'staff','label':'طاقم'},{'key':'speaker','label':'متحدث'},{'key':'media','label':'إعلام'},{'key':'exhibitor','label':'عارض'}],'checkpoints':[{'key':'main','label':'البوابة الرئيسية','enabled':True,'allowed_guest_types':[],'start':'','end':''}]}, 'surveys':[{'id':'main','title':'استبيان الزوار','description':'شاركنا رأيك في دقائق.','completion':'شكرًا لك، تم استلام إجاباتك.','presentation':'one_page','show_progress':True,'submit_label':'إرسال الاستبيان'}], 'sections':[{'key':k,'title':n,'enabled':True,'order':i,'layout':'cards','preview_count':3} for i,(k,n) in enumerate(SECTIONS)],'records':[]}

def normalize_record(raw):
    if not isinstance(raw,dict): fail('RECORD_INVALID')
    kind=raw.get('kind')
    if kind not in KINDS: fail('RECORD_KIND_INVALID')
    code=text(raw.get('code'),64,True)
    if not CODE.fullmatch(code): fail('CODE_INVALID')
    r={'kind':kind,'code':code,'title':text(raw.get('title'),1000,True),'body':text(raw.get('body'),6000),'media':url(raw.get('media')),'url':url(raw.get('url'),True),'order':number(raw.get('order'),0,0,10000),'enabled':boolean(raw.get('enabled',True)),'start':stamp(raw.get('start')),'end':stamp(raw.get('end')),'tag':text(raw.get('tag'),100),'subtype':text(raw.get('subtype'),40)}
    if r['start'] and r['end'] and datetime.fromisoformat(r['start'])>=datetime.fromisoformat(r['end']): fail('DATE_RANGE')
    r['placement']=text(raw.get('placement') or 'offers',64)
    r['media_type']='video' if raw.get('media_type')=='video' else 'image'
    if kind=='fact':
        r.update(value=number(raw.get('value')),unit=text(raw.get('unit'),40),source=text(raw.get('source'),500),display=raw.get('display') if raw.get('display') in ('number','bar','text','percentage','trend','comparison','timeline','donut') else 'number',maximum=number(raw.get('maximum'),100,1,1e12))
    if kind in ('question','poll'):
        typ=raw.get('qtype','single_choice')
        if typ not in QTYPES: fail('QUESTION_TYPE_INVALID')
        if kind=='poll' and typ not in ('single_choice','multiple_choice','image_choice','rating','ranking','emoji'): fail('POLL_TYPE_UNSUPPORTED')
        opts=raw.get('options',[])
        if isinstance(opts,str): opts=[x.strip() for x in opts.split('|') if x.strip()]
        if not isinstance(opts,list) or len(opts)>50: fail('OPTIONS_LIMIT')
        options=[]
        for i,o in enumerate(opts):
            if isinstance(o,str): o={'key':f'o{i+1}','label':o}
            if not isinstance(o,dict): fail('OPTION_INVALID')
            key=text(o.get('key') or f'o{i+1}',64,True)
            if not CODE.fullmatch(key): fail('OPTION_KEY')
            options.append({'key':key,'label':text(o.get('label'),500,True),'media':url(o.get('media'))})
        if len({o['key'] for o in options})!=len(options): fail('DUPLICATE_OPTION')
        if typ in ('single_choice','multiple_choice','dropdown','image_choice','ranking','quiz','allocation') and len(options)<2: fail('OPTIONS_REQUIRED')
        if typ not in ('single_choice','multiple_choice','dropdown','image_choice','ranking','quiz','allocation') and options: fail('OPTIONS_NOT_APPLICABLE')
        lo=number(raw.get('min'),1 if typ in ('rating','matrix','emoji') else 0)
        hi=number(raw.get('max'),5 if typ in ('rating','matrix','emoji') else 10)
        if typ=='nps': lo,hi=0,10
        if typ in ('rating','emoji','matrix') and (lo<0 or hi>10 or int(lo)!=lo or int(hi)!=hi): fail('SCALE_INVALID')
        if lo>=hi: fail('RANGE_INVALID')
        rows=raw.get('rows',[])
        if isinstance(rows,str): rows=[x.strip() for x in rows.split('|') if x.strip()]
        if not isinstance(rows,list) or len(rows)>20: fail('MATRIX_ROWS_LIMIT')
        rows=[text(x,300,True) for x in rows]
        if typ=='matrix' and (not rows or len(set(rows))!=len(rows)): fail('MATRIX_ROWS_REQUIRED')
        show=raw.get('show_if') or None
        if show:
            if not isinstance(show,dict) or set(show)!={'code','equals'}: fail('BRANCH_RULE_INVALID')
            show={'code':text(show['code'],64,True),'equals':text(show['equals'],500)}
        r.update(qtype=typ,options=options,required=boolean(raw.get('required')),min=lo,max=hi,rows=rows,form_id=text(raw.get('form_id') or 'main',64,True),show_if=show,show_results=boolean(raw.get('show_results',True)),status=raw.get('status') if raw.get('status') in ('open','closed') else 'open',poll_style=text(raw.get('poll_style') or 'quick',30),correct=text(raw.get('correct'),100),score=number(raw.get('score'),1,0,10000))
        r.update(placeholder=text(raw.get('placeholder'),180),min_label=text(raw.get('min_label'),100),max_label=text(raw.get('max_label'),100),selection_min=number(raw.get('selection_min'),0,0,50),selection_max=number(raw.get('selection_max'),len(options) if options else 0,0,50),presentation=text(raw.get('presentation') or 'default',30))
        if typ=='multiple_choice' and r['selection_max'] and r['selection_min']>r['selection_max']: fail('SELECTION_RANGE_INVALID')
        if typ=='quiz' and r['correct'] not in {o['key'] for o in options}: fail('QUIZ_CORRECT_REQUIRED')
        if kind=='poll' and r['poll_style']=='secret': r['show_results']=False
    return r

def normalize_config(raw):
    if not isinstance(raw,dict): fail('CONFIG_REQUIRED')
    c=default_config(text(raw.get('title'),160,True))
    for key,lim in [('subtitle',400),('description',6000),('location',400),('phone',60),('privacy',1500)]: c[key]=text(raw.get(key),lim)
    for key in ['logo','cover','website']: c[key]=url(raw.get(key))
    for key,default in [('primary','#176B73'),('secondary','#0F3D46'),('accent','#29B8A8'),('background','#F5F8FA'),('surface','#FFFFFF'),('text_color','#17313B')]:
        c[key]=text(raw.get(key) or default,7)
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}',c[key]): fail('COLOR_INVALID')
    c['template']=raw.get('template') if raw.get('template') in ('fintech','technology','corporate','exhibition','minimal','dynamic','sponsor','startup','rts_tech','easy_finance','tharawat_finance') else 'fintech'
    c['font']=raw.get('font') if raw.get('font') in ('system','modern','classic','geometric') else 'system'
    c['card_style']=raw.get('card_style') if raw.get('card_style') in ('soft','bordered','glass','flat') else 'soft'
    c['hero_style']=raw.get('hero_style') if raw.get('hero_style') in ('split','centered','cover','minimal') else 'split'
    c['button_style']=raw.get('button_style') if raw.get('button_style') in ('rounded','pill','square','outline') else 'rounded'
    c['nav_style']=raw.get('nav_style') if raw.get('nav_style') in ('clean','tabs','floating') else 'clean'
    c['density']=raw.get('density') if raw.get('density') in ('compact','comfortable','spacious') else 'comfortable'
    c['content_width']=raw.get('content_width') if raw.get('content_width') in ('narrow','wide','full') else 'wide'
    c['heading_scale']=raw.get('heading_scale') if raw.get('heading_scale') in ('compact','balanced','display') else 'balanced'
    c['radius']=number(raw.get('radius'),22,0,48)
    c['logo_dark']=url(raw.get('logo_dark')); c['favicon']=url(raw.get('favicon'))
    criteria=raw.get('rating_criteria') or [{'key':'overall','label':'التقييم العام','weight':100}]
    if not isinstance(criteria,list) or not criteria or len(criteria)>10: fail('RATING_CRITERIA_INVALID')
    clean_criteria=[]; total=0
    for rc in criteria:
        if not isinstance(rc,dict): fail('RATING_CRITERIA_INVALID')
        key=text(rc.get('key'),40,True); label=text(rc.get('label'),120,True); weight=number(rc.get('weight'),0,0,100)
        if not CODE.fullmatch(key): fail('RATING_CRITERIA_INVALID')
        clean_criteria.append({'key':key,'label':label,'weight':weight}); total+=weight
    if len({x['key'] for x in clean_criteria})!=len(clean_criteria) or total<=0: fail('RATING_CRITERIA_INVALID')
    c['rating_criteria']=clean_criteria
    access=raw.get('access_control') or c['access_control']
    if not isinstance(access,dict): fail('ACCESS_CONTROL_INVALID')
    guest_types=access.get('guest_types') or c['access_control']['guest_types']
    if not isinstance(guest_types,list) or not guest_types or len(guest_types)>20: fail('GUEST_TYPES_INVALID')
    clean_types=[]; type_keys=set()
    for item in guest_types:
        if not isinstance(item,dict): fail('GUEST_TYPES_INVALID')
        key=text(item.get('key'),40,True); label=text(item.get('label') or key,100,True)
        if not CODE.fullmatch(key) or key in type_keys: fail('GUEST_TYPE_INVALID')
        type_keys.add(key);clean_types.append({'key':key,'label':label})
    checkpoints=access.get('checkpoints') or c['access_control']['checkpoints']
    if not isinstance(checkpoints,list) or not checkpoints or len(checkpoints)>50: fail('CHECKPOINTS_INVALID')
    clean_checkpoints=[]; checkpoint_keys=set()
    for item in checkpoints:
        if not isinstance(item,dict): fail('CHECKPOINT_INVALID')
        key=text(item.get('key'),40,True); label=text(item.get('label') or key,120,True)
        if not CODE.fullmatch(key) or key in checkpoint_keys: fail('CHECKPOINT_INVALID')
        checkpoint_keys.add(key)
        allowed=item.get('allowed_guest_types') or []
        if not isinstance(allowed,list) or len(allowed)>20: fail('CHECKPOINT_GUEST_TYPES_INVALID')
        allowed=[text(x,40,True) for x in allowed]
        if len(set(allowed))!=len(allowed) or any(x not in type_keys for x in allowed): fail('CHECKPOINT_GUEST_TYPES_INVALID')
        start,end=stamp(item.get('start')),stamp(item.get('end'))
        if start and end and datetime.fromisoformat(start)>=datetime.fromisoformat(end): fail('CHECKPOINT_DATE_RANGE')
        clean_checkpoints.append({'key':key,'label':label,'enabled':boolean(item.get('enabled',True)),'allowed_guest_types':allowed,'start':start,'end':end})
    c['access_control']={
        'anti_passback':boolean(access.get('anti_passback',True)),
        'allow_reentry':boolean(access.get('allow_reentry',True)),
        'manifest_max_age_minutes':number(access.get('manifest_max_age_minutes'),7200,5,10080),
        'guest_types':clean_types,
        'checkpoints':clean_checkpoints,
    }
    c['welcome']=boolean(raw.get('welcome',True))
    c['start'],c['end']=stamp(raw.get('start')),stamp(raw.get('end'))
    if c['start'] and c['end'] and datetime.fromisoformat(c['start'])>=datetime.fromisoformat(c['end']): fail('DATE_RANGE')
    surveys=raw.get('surveys') or [{'id':'main','title':'استبيان الزوار','description':'شاركنا رأيك في دقائق.','completion':'شكرًا لك، تم استلام إجاباتك.'}]
    if not isinstance(surveys,list) or not surveys or len(surveys)>50: fail('SURVEYS_INVALID')
    c['surveys']=[]; survey_ids=set()
    for sv in surveys:
        if not isinstance(sv,dict): fail('SURVEYS_INVALID')
        sid=text(sv.get('id'),64,True)
        if not CODE.fullmatch(sid) or sid in survey_ids: fail('SURVEY_ID_INVALID')
        survey_ids.add(sid)
        c['surveys'].append({'id':sid,'title':text(sv.get('title') or sid,180,True),'description':text(sv.get('description'),1000),'completion':text(sv.get('completion') or 'شكرًا لك، تم استلام إجاباتك.',500,True),'presentation':sv.get('presentation') if sv.get('presentation') in ('one_page','stepper') else 'one_page','show_progress':boolean(sv.get('show_progress',True)),'submit_label':text(sv.get('submit_label') or 'إرسال الاستبيان',80,True)})
    c['expected_entities']=number(raw.get('expected_entities'),0,0,100000)
    sections=raw.get('sections',c['sections'])
    if not isinstance(sections,list) or len(sections)>len(SECTIONS): fail('SECTIONS_INVALID')
    keys=[k for k,_ in SECTIONS]; seen=set();c['sections']=[]
    for i,s in enumerate(sections):
        if not isinstance(s,dict) or s.get('key') not in keys or s['key'] in seen: fail('SECTION_KEY')
        seen.add(s['key']);c['sections'].append({'key':s['key'],'title':text(s.get('title'),100,True),'enabled':boolean(s.get('enabled',True)),'order':number(s.get('order'),i,0,100),'layout':s.get('layout') if s.get('layout') in ('cards','featured','list','masonry','split') else 'cards','preview_count':number(s.get('preview_count'),3,1,6)})
    recs=raw.get('records',[])
    if not isinstance(recs,list) or len(recs)>2000: fail('RECORD_LIMIT')
    c['records']=[normalize_record(r) for r in recs]
    used_forms={r['form_id'] for r in c['records'] if r['kind']=='question'}
    for fid in sorted(used_forms-survey_ids):
        c['surveys'].append({'id':fid,'title':'استبيان '+fid,'description':'','completion':'شكرًا لك، تم استلام إجاباتك.','presentation':'one_page','show_progress':True,'submit_label':'إرسال الاستبيان'}); survey_ids.add(fid)
    codes=[r['code'] for r in c['records']]
    if len(set(codes))!=len(codes): fail('DUPLICATE_CODE')
    byform={}
    for r in sorted(c['records'],key=lambda x:x['order']):
        if r['kind']!='question': continue
        prev=byform.setdefault(r['form_id'],{})
        if r['show_if']:
            q=prev.get(r['show_if']['code'])
            if not q: fail('BRANCH_MUST_REFERENCE_EARLIER_QUESTION_IN_FORM')
        prev[r['code']]=r
    return c

def visible(q, answers):
    rule=q.get('show_if')
    if not rule: return True
    x=answers.get(rule['code']); v=rule['equals']
    return v in x if isinstance(x,list) else str(x).lower()==v.lower()

def answer_value(q,v):
    t=q['qtype']; keys=[o['key'] for o in q['options']]
    if v is None or v=='' or v==[] or v=={}:
        if q['required']: fail('ANSWER_REQUIRED:'+q['code'])
        return None
    if t in ('single_choice','dropdown','image_choice'):
        if v not in keys: fail('ANSWER_OPTION')
    elif t in ('multiple_choice','ranking'):
        if not isinstance(v,list) or any(x not in keys for x in v) or len(set(v))!=len(v): fail('ANSWER_OPTIONS')
        if t=='multiple_choice':
            if q.get('selection_min',0) and len(v)<q['selection_min']: fail('SELECTION_MIN_NOT_MET')
            if q.get('selection_max',0) and len(v)>q['selection_max']: fail('SELECTION_MAX_EXCEEDED')
        if t=='ranking' and set(v)!=set(keys): fail('RANKING_MUST_INCLUDE_ALL_OPTIONS')
    elif t=='allocation':
        if not isinstance(v,dict) or set(v)-set(keys): fail('ALLOCATION_ANSWER')
        v={k:number(x,0,0,100) for k,x in v.items()}
        if round(sum(v.values()),6)!=100: fail('ALLOCATION_TOTAL_100')
    elif t=='yes_no':
        if v not in ('yes','no'): fail('ANSWER_YES_NO')
    elif t in ('number','currency','rating','nps','slider','emoji'):
        v=number(v,0,q['min'],q['max'])
        if t in ('rating','nps','emoji') and int(v)!=v: fail('INTEGER_REQUIRED')
    elif t=='matrix':
        if not isinstance(v,dict) or any(k not in q['rows'] for k in v): fail('MATRIX_ANSWER')
        if q['required'] and set(v)!=set(q['rows']): fail('MATRIX_ROWS_REQUIRED')
        v={k:number(x,0,q['min'],q['max']) for k,x in v.items()}
    elif t=='date':
        v=text(v,40,True)
        try: datetime.strptime(v,'%Y-%m-%d')
        except ValueError: fail('DATE_INVALID')
    elif t=='time':
        v=text(v,20,True)
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?',v): fail('TIME_INVALID')
    elif t=='datetime':
        v=text(v,50,True)
        try: datetime.fromisoformat(v)
        except ValueError: fail('DATETIME_INVALID')
    elif t=='email':
        v=text(v,200,True).lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v): fail('EMAIL_INVALID')
    elif t=='phone':
        v=text(v,40,True)
        if not re.fullmatch(r'[+0-9 ()-]{5,40}',v): fail('PHONE_INVALID')
    elif t=='url':
        v=url(v)
    elif t=='consent':
        if v not in (True,'true','yes','1',1): fail('CONSENT_REQUIRED')
        v=True
    elif t=='quiz':
        if v not in keys: fail('ANSWER_OPTION')
    else: v=text(v,4000 if t=='long_text' else 500)
    return v

def survey_answers(config, form_id, answers):
    if not isinstance(answers,dict): fail('ANSWERS_INVALID')
    qs=sorted([q for q in config['records'] if q['kind']=='question' and q['enabled'] and q['form_id']==form_id],key=lambda x:x['order'])
    if not qs: fail('FORM_NOT_FOUND',404)
    allowed={q['code'] for q in qs}
    if set(answers)-allowed: fail('UNKNOWN_QUESTION')
    clean={}
    for q in qs:
        if visible(q,answers):
            val=answer_value(q,answers.get(q['code']))
            if val is not None: clean[q['code']]=val
    if not clean: fail('EMPTY_ANSWERS')
    return clean
