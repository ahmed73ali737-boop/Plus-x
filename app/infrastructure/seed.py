from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import func, insert, select

from app.application.audit_service import new_id
from app.core.security import hash_password, new_temporary_password
from app.db import assignments, event_participations, memberships, organizations, sites, users, versions
from app.domain import default_config, normalize_config, now


def seed_demo_data(engine, credentials_path=None, count=10):
    creds = []
    with engine.begin() as c:
        if c.execute(select(func.count()).select_from(sites)).scalar():
            return []
        platform = default_config('PulseX — مساحة التجارب الحيّة', 'platform')
        platform['subtitle'] = 'منصة واحدة. فعاليات متصلة. تجارب تستحق المشاركة.'
        platform['description'] = 'استكشف الفعاليات والجهات والخدمات وشارك برأيك. هذه بيانات عرض تجريبية وليست معرضًا فعليًا.'
        platform['welcome'] = False

        event = default_config('معرض التجربة التفاعلية', 'event')
        event['subtitle'] = 'خمسة أيام من اللقاءات والأفكار والتفاعل'
        event['description'] = 'تجربة أولية للمنظم وعشر جهات من أصل 70 جهة مستهدفة. استعرض المشاركين وقيّم التجربة بحرية.'
        event['start'] = '2026-09-29T09:00:00+03:00'
        event['end'] = '2026-10-03T20:00:00+03:00'
        event['location'] = 'مكان تجريبي — يحدده المنظم'
        event['cover'] = '/media/venue-demo.svg'
        event['records'] = [
            {'kind':'session','code':'welcome-talk','title':'جلسة الافتتاح — نموذج','body':'نبذة الجلسة والمتحدث والمكان يحددها المنظم.','start':'2026-09-29T10:00:00+03:00','end':'2026-09-29T11:00:00+03:00'},
            {'kind':'sponsor','code':'sponsor-demo','title':'الراعي التجريبي','body':'مثال توضيحي؛ استبدله ببيانات الراعي الفعلية.'},
            {'kind':'fact','code':'expected','title':'جهات مستهدفة','value':70,'unit':'جهة','source':'افتراض نطاق المستخدم — ليس حضورًا فعليًا','display':'number'},
            {'kind':'place','code':'venue','title':'مخطط القاعة التجريبي','body':'يمكن رفع صورة القاعة أو مخطّط الأجنحة.','media':'/media/venue-demo.svg'},
            {'kind':'question','code':'event-rate','title':'كيف تقيّم تجربتك العامة؟','qtype':'rating','form_id':'event-feedback','required':True},
            {'kind':'question','code':'event-note','title':'ما ملاحظتك للمنظم؟','qtype':'long_text','form_id':'event-feedback'},
        ]

        seed_sites = [('platform', None, None, 'platform', 'platform', platform), ('event-demo', 'platform', 'event-demo', 'event', 'demo', event)]
        for i in range(1, count + 1):
            sid = f'agency-{i:02}'
            cfg = default_config(f'الجهة التجريبية {i:02}')
            cfg['subtitle'] = 'نقرّب خدماتنا منك. ونستمع إلى رأيك.'
            cfg['description'] = 'هذه صفحة تعريفية قابلة للتخصيص بالكامل بواسطة الجهة. جميع الأسماء والأرقام المعروضة هنا بيانات تجريبية.'
            cfg['primary'] = ['#176B73', '#2759A5', '#8047A1', '#9B6724'][i % 4]
            cfg['cover'] = '/media/brand-demo.svg'
            cfg['records'] = [
                {'kind':'service','code':'service-1','title':'خدمات رقمية أقرب إليك','body':'أضف تفاصيل خدمتك وصورة أو فيديو ورابطًا للتواصل.','media':'/media/brand-demo.svg'},
                {'kind':'service','code':'service-2','title':'حلول للمنشآت','body':'مكان لعرض المنتجات والخدمات والميزات.'},
                {'kind':'fact','code':'fact-1','title':'مؤشر توضيحي','value':85,'unit':'%','source':'بيانات اصطناعية لتجربة العرض','display':'bar','maximum':100},
                {'kind':'question','code':'q-interest','title':'أي الخدمات تهمك أكثر؟','qtype':'single_choice','form_id':'main','required':True,'order':1,'options':['حلول الأفراد','حلول الأعمال','الخدمات الرقمية']},
                {'kind':'question','code':'q-rate','title':'كيف كانت زيارتك لجناحنا؟','qtype':'rating','form_id':'main','order':2},
                {'kind':'question','code':'q-note','title':'ملاحظة تساعدنا على التحسين','qtype':'long_text','form_id':'main','order':3},
                {'kind':'poll','code':'p-first','title':'ما الأولوية التي تهمك؟','qtype':'single_choice','options':['سهولة الاستخدام','سرعة الخدمة','وضوح المعلومات'],'status':'open','show_results':True},
                {'kind':'offer','code':'offer-1','title':'اكتشف عروض المشاركة','body':'عرض توضيحي وليس التزامًا تجاريًا أو عملية دفع.'},
                {'kind':'ad','code':'ad-1','title':'مساحة إعلان الجهة','body':'محتوى ترويجي قابل للتغيير من لوحة الإدارة.','placement':'all','media':'/media/ad-demo.svg'},
                {'kind':'contact','code':'contact-1','title':'فريق الجهة','body':'أضف طرق التواصل المعتمدة.'},
            ]
            if i == 8:
                cfg.update(title='ثروات', subtitle='رؤية مالية تتفاعل مع اللحظة، لا صفحة تعريفية ثابتة.', description='مساحة ثروات الحيّة داخل الفعالية: استكشف المبادرات والخدمات والرؤى، شارك في التصويت، واترك ملاحظتك ضمن تجربة متغيرة مع تفاعل الجمهور.', template='tharawat_finance', primary='#7A5B19', secondary='#1E1A12', accent='#C9A552', background='#FBF8F0', cover='')
                cfg['records'][0].update(title='منظومة ثروات الرقمية', body='استكشف المبادرات والمنصات والخدمات من نقطة واحدة، ثم انتقل مباشرة إلى التفاعل المناسب.', order=1)
                cfg['records'][1].update(title='حلول مالية للأفراد والأعمال', body='رحلة مختصرة من التعرف إلى الاهتمام ثم طلب المتابعة، مع حفظ قرار الزائر بوضوح.', order=2)
                cfg['records'][2].update(title='نبض التجربة', value=91, source='قيمة عرض تجريبية لواجهة ثروات الحيّة', display='trend')
                cfg['records'][3].update(title='أي مساحة مالية تهمك أكثر؟', options=['الخدمات المالية الرقمية','المنصات والحلول المؤسسية','الاستثمار والنمو','الشراكات والتكامل'])
                cfg['records'][6].update(title='ما الذي تريد أن تستكشفه أولًا؟', options=['الخدمات والمنصات','الرؤية والابتكار','فرص التعاون'])
                cfg['records'][7].update(title='فرصة للاستكشاف', body='محتوى حي يتبدل مع أولويات الفعالية بدل بطاقة عرض ثابتة.')
                cfg['records'].extend([
                    {'kind':'service','code':'service-3','title':'رؤية وابتكار مالي','body':'مساحة تربط احتياج السوق بالمنتج والتقنية والقرار، وتحوّل العرض إلى حوار قابل للقياس.','order':3},
                    {'kind':'service','code':'service-4','title':'شراكات وتكاملات','body':'استكشف مسارات التعاون والتكامل مع الأنظمة والقنوات والجهات ضمن رحلة واضحة من الاهتمام إلى المتابعة.','order':4},
                    {'kind':'service','code':'service-5','title':'بيانات ورؤى قابلة للتنفيذ','body':'قراءة التفاعل والاهتمامات والملاحظات كإشارات عملية تساعد على اتخاذ القرار بعد المعرض.','order':5},
                ])
            elif i == 9:
                cfg.update(title='Easy', subtitle='محفظتك وخدماتك اليومية — اكتشفها وتفاعل معها في لمسة.', description='تجربة Easy في المعرض مصممة لتكون عملية وسريعة: خدمات المحفظة، الخصوصية، الحصالة، بطاقات Wi-Fi وحسابات الأطفال، مع تصويت وأسئلة لحظية.', template='easy_finance', primary='#12A594', secondary='#073F45', accent='#E8B74A', background='#F4FBF9', cover='')
                cfg['records'][0].update(title='الخصوصية والرقم البديل', body='اكتشف كيف يمكن إنجاز التعاملات مع خيارات خصوصية أكثر وضوحًا.', order=1)
                cfg['records'][1].update(title='الحصالة والكسر المباشر', body='حوّل الباقي تلقائيًا إلى حصالتك ضمن تجربة ادخار يومية بسيطة ومرئية.', order=2)
                cfg['records'][2].update(title='خدمات في لمسة', value=6, unit='تجارب', source='محتوى توضيحي لرحلة Easy في المعرض', display='number')
                cfg['records'][3].update(title='أي خدمة في Easy تريد تجربتها أولًا؟', options=['الخصوصية والرقم البديل','الحصالة والكسر المباشر','بطاقات Wi-Fi','حسابات الأطفال','الدفع والتحويل'])
                cfg['records'][6].update(title='ما الذي يصنع التجربة الأسهل بالنسبة لك؟', options=['سرعة التنفيذ','وضوح الخطوات','الأمان والخصوصية','تنوع الخدمات'])
                cfg['records'][7].update(title='جرّب مسار Easy', body='اختر الخدمة التي تهمك ثم صوّت وقيّم التجربة مباشرة.')
                cfg['records'].extend([
                    {'kind':'service','code':'service-3','title':'بطاقات Wi‑Fi','body':'شراء بطاقات Wi‑Fi والوصول إليها ضمن نفس الرحلة اليومية للمحفظة.','order':3},
                    {'kind':'service','code':'service-4','title':'حسابات الأطفال','body':'مساحة عائلية لإدارة حسابات الأطفال ومتابعتها بصورة أبسط وأكثر وضوحًا.','order':4},
                    {'kind':'service','code':'service-5','title':'الدفع والتحويل','body':'مدفوعات وتحويلات مصممة للوصول إلى الإجراء المطلوب بأقل خطوات ممكنة.','order':5},
                    {'kind':'service','code':'service-6','title':'تقاريرك وسجلّك','body':'عرض أوضح للحركة والتفاصيل لمساعدة المستخدم على الفهم والمتابعة من نفس التطبيق.','order':6},
                ])
            elif i == 10:
                cfg.update(title='RTS', subtitle='من الحلول إلى المنصات إلى الأنظمة البيئية الرقمية.', description='RTS تعرض تجربة تقنية حيّة للتحول الرقمي والتكنولوجيا المالية وبوابات الدفع والتحصيل والمنصات المتكاملة، مع مؤشرات وتفاعل مباشر بدل موقع تعريفي جامد.', template='rts_tech', primary='#0B5CFF', secondary='#071D49', accent='#00C2FF', background='#F4F8FF', cover='')
                cfg['records'][0].update(title='Digital Transformation', body='الاستراتيجية والرقمنة والأتمتة والتكامل والتحديث ضمن رحلة تنفيذ مترابطة.', order=1)
                cfg['records'][1].update(title='FinTech & Payment Platforms', body='محافظ ومدفوعات وتحصيل ومنصات مالية وتكاملات قابلة للتوسع.', order=2)
                cfg['records'][2].update(title='RTS Live Capabilities', value=6, unit='مسارات', source='بيانات عرض تجريبية لمساحة RTS التفاعلية', display='comparison')
                cfg['records'][3].update(title='أي قدرة تقنية تريد استكشافها؟', options=['التحول الرقمي','FinTech والمدفوعات','بوابات الدفع والتحصيل','التكامل والمنصات','أنظمة الأعمال'])
                cfg['records'][6].update(title='أين ترى أعلى قيمة للتحول؟', options=['أتمتة العمليات','تجربة العميل','التكامل والبيانات','المدفوعات والتحصيل'])
                cfg['records'][7].update(title='ادخل التجربة التقنية', body='استكشف قدرة، شاهد المؤشر، ثم شارك رأيك أو طلب المتابعة.')
                cfg['records'].extend([
                    {'kind':'service','code':'service-3','title':'Payment & Collection','body':'بوابات دفع وفوترة وتحصيل وتسوية وربط للقنوات والخدمات ضمن بنية قابلة للتوسع.','order':3},
                    {'kind':'service','code':'service-4','title':'Integration & Platforms','body':'تكامل الأنظمة وواجهات API والمنصات المشتركة لبناء منظومات مترابطة بدل حلول معزولة.','order':4},
                    {'kind':'service','code':'service-5','title':'Business Systems','body':'أنظمة الأعمال والمحاسبة والمبيعات والإقراض والتحصيل والخدمات المؤسسية ضمن تصميم مرن.','order':5},
                    {'kind':'service','code':'service-6','title':'Data, Automation & Insights','body':'تحويل البيانات والعمليات إلى تدفقات قابلة للأتمتة والقياس والتحسين المستمر.','order':6},
                ])
            seed_sites.append((sid, 'event-demo', 'event-demo', 'agency', sid, cfg))

        for sid, parent, event_id, kind, slug, cfg in seed_sites:
            cfg = normalize_config(cfg)
            c.execute(insert(sites).values(id=sid, parent_id=parent, event_id=event_id, kind=kind, slug=slug, draft=cfg, draft_rev=1, published_version=1))
            c.execute(insert(versions).values(site_id=sid, version=1, config=cfg, published_at=now()))

        organizer_org = 'org-organizer'
        c.execute(insert(organizations).values(id=organizer_org, slug='organizer', name='الجهة المنظمة', profile={'description':'الملف الدائم للجهة المنظمة','logo':'','primary':'#176B73'}, status='active', created_at=now()))
        orgmap = {}
        for i in range(1, count + 1):
            oid = f'org-{i:02}'
            site_id = f'agency-{i:02}'
            orgmap[site_id] = oid
            brand_orgs={
                8:('ثروات','ملف ثروات الدائم وربطه بمشاركاتها عبر الفعاليات','#7A5B19'),
                9:('Easy','ملف Easy الدائم للمحفظة والخدمات المالية الرقمية','#12A594'),
                10:('RTS','ملف RTS الدائم للتقنية والتحول الرقمي والتكنولوجيا المالية','#0B5CFF'),
            }
            org_name,org_desc,org_primary=brand_orgs.get(i,(f'المؤسسة التجريبية {i:02}','ملف مؤسسة دائم يمكن ربطه بأكثر من فعالية',['#176B73','#2759A5','#8047A1','#9B6724'][i % 4]))
            c.execute(insert(organizations).values(id=oid, slug=f'organization-{i:02}', name=org_name, profile={'description':org_desc,'logo':'','primary':org_primary}, status='active', created_at=now()))
            c.execute(insert(event_participations).values(id=new_id(), event_id='event-demo', organization_id=oid, agency_site_id=site_id, participation_type='exhibitor', status='active', booth=f'A-{i:02}', summary='مشاركة تجريبية مرتبطة بالمؤسسة الدائمة', services=[], valid_from=event['start'], valid_until=event['end'], created_at=now()))

        accounts = [('platform','platform','admin@pulsex.test','مدير المنصة'), ('organizer','event-demo','organizer@pulsex.test','الجهة المنظمة')]
        accounts += [('agency', f'agency-{i:02}', f'agency{i:02}@pulsex.test', f'مسؤول الجهة {i:02}') for i in range(1, count + 1)]
        for role, scope, email, name in accounts:
            password = new_temporary_password()
            creds.append({'email': email, 'password': password, 'role': role, 'scope_id': scope})
            user_id = new_id()
            c.execute(insert(users).values(id=user_id, email=email, name=name, role=role, scope_id=scope, password_hash=hash_password(password), active=1))
            oid = organizer_org if role == 'organizer' else orgmap.get(scope)
            if oid:
                c.execute(insert(memberships).values(user_id=user_id, organization_id=oid, role='owner' if role in ('organizer','agency') else 'member', status='active', created_at=now()))
            if role == 'organizer':
                c.execute(insert(assignments).values(id=new_id(), user_id=user_id, site_id='event-demo', role='event_manager', status='active', valid_from=event['start'], valid_until=event['end'], created_at=now()))

    if credentials_path:
        path = Path(credentials_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(creds, ensure_ascii=False, indent=2), encoding='utf-8')
        path.chmod(0o600)
    return creds
