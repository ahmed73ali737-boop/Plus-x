function records(page,kind){return (page?.config?.records||[]).filter(r=>r.enabled&&(!kind||r.kind===kind)).sort((a,b)=>(a.order||0)-(b.order||0));}
function first(page,kind){return records(page,kind)[0]||null;}
function text(v,fallback=''){return String(v||fallback).trim();}
function targetFor(ctx,page,r,fallback){return r?.code?ctx.itemLink(page.id,r.code):ctx.sectionLink(fallback);}
function action(ctx,label,href,klass='expo-btn primary'){return ctx.h('a',{class:klass,href},label,ctx.icon('arrow',18));}
function miniMetric(ctx,label,value,sub=''){return ctx.h('div',{class:'expo-mini-metric'},ctx.h('small',{},label),ctx.h('strong',{},String(value)),sub?ctx.h('span',{},sub):null);}
function guestHref(page){const slug=page.kind==='event'?page.slug:page.event?.slug||'';return slug?`/e/${slug}/guest`:'#';}

function rts(page,ctx){
 const services=records(page,'service').slice(0,6),facts=records(page,'fact').slice(0,3),poll=first(page,'poll'),questions=first(page,'question');
 const capabilities=services.length?services:[{title:'Digital Transformation'},{title:'FinTech Platforms'},{title:'Payment & Collection'},{title:'Integration'}];
 const hero=ctx.h('section',{class:'expo-stage expo-rts-stage','aria-label':'RTS exhibition experience'},
   ctx.h('div',{class:'expo-rts-copy'},
     ctx.h('div',{class:'expo-status-line'},ctx.h('span',{class:'expo-live-dot'}),ctx.h('span',{},'RTS / LIVE DIGITAL SYSTEMS'),ctx.h('small',{},page.offline?'OFFLINE EXPERIENCE':'CONNECTED EXPERIENCE')),
     ctx.h('p',{class:'expo-overline'},'FROM SOLUTIONS → PLATFORMS → ECOSYSTEMS'),
     ctx.h('h1',{},text(page.config.title,'RTS')),
     ctx.h('p',{class:'expo-rts-tagline'},text(page.config.subtitle,'نحو أعمال أكثر اتصالًا ومرونة.')),
     ctx.h('p',{class:'expo-rts-description'},text(page.config.description)),
     ctx.h('div',{class:'expo-actions'},action(ctx,'استكشف القدرات',ctx.sectionLink('services')),poll?action(ctx,'شارك في التصويت',targetFor(ctx,page,poll,'polls'),'expo-btn ghost'):questions?action(ctx,'شاركنا رأيك',ctx.sectionLink('questions'),'expo-btn ghost'):null,action(ctx,'بطاقة الزائر',guestHref(page),'expo-btn line'))),
   ctx.h('div',{class:'expo-rts-system','aria-label':'RTS system map'},
     ctx.h('div',{class:'expo-rts-system-head'},ctx.h('span',{},'SYSTEM MAP'),ctx.h('span',{class:'expo-rts-pulse'},'● LIVE')),
     ctx.h('div',{class:'expo-rts-core'},ctx.h('span',{class:'expo-rts-ring ring-a'}),ctx.h('span',{class:'expo-rts-ring ring-b'}),ctx.h('div',{class:'expo-rts-core-label'},ctx.h('small',{},'RTS CORE'),ctx.h('strong',{},String(capabilities.length).padStart(2,'0')),ctx.h('span',{},'connected capabilities'))),
     ctx.h('div',{class:'expo-rts-nodes'},capabilities.slice(0,5).map((r,i)=>ctx.h('a',{href:r.code?targetFor(ctx,page,r,'services'):'#services',class:'expo-rts-node','data-node':String(i+1)},ctx.h('span',{},String(i+1).padStart(2,'0')),ctx.h('strong',{},r.title)))),
     ctx.h('div',{class:'expo-rts-telemetry'},miniMetric(ctx,'CAPABILITIES',capabilities.length,'active'),miniMetric(ctx,'LIVE POLLS',records(page,'poll').filter(r=>r.status==='open').length,'open'),miniMetric(ctx,'DATA MODE',page.offline?'LOCAL':'SYNC','ready'))));
 const strip=ctx.h('section',{class:'expo-rts-strip'},
   ctx.h('div',{class:'expo-rts-strip-title'},ctx.h('small',{},'RTS CAPABILITY RAIL'),ctx.h('strong',{},'اختر نقطة وادخل التجربة مباشرة')),
   ctx.h('div',{class:'expo-rts-cap-grid'},capabilities.slice(0,6).map((r,i)=>ctx.h('a',{class:'expo-rts-cap',href:r.code?targetFor(ctx,page,r,'services'):'#services'},ctx.h('span',{},`0${i+1}`.slice(-2)),ctx.h('strong',{},r.title),ctx.h('small',{},r.body||'Explore capability')))),
   facts.length?ctx.h('div',{class:'expo-rts-facts'},facts.map(f=>miniMetric(ctx,f.title,`${f.value}${f.unit?` ${f.unit}`:''}`,f.source||''))):null);
 return {hero,after:strip,mode:'rts'};
}

function easy(page,ctx){
 const services=records(page,'service').slice(0,6),poll=first(page,'poll'),offer=first(page,'offer');
 const quick=services.length?services:[
   {title:'الخصوصية والرقم البديل'},{title:'الحصالة والكسر المباشر'},{title:'بطاقات Wi‑Fi'},{title:'حسابات الأطفال'}
 ];
 const hero=ctx.h('section',{class:'expo-stage expo-easy-stage','aria-label':'Easy exhibition experience'},
   ctx.h('div',{class:'expo-easy-copy'},
     ctx.h('span',{class:'expo-easy-badge'},ctx.h('span',{class:'expo-live-dot'}),'EASY LIVE · EXHIBITION MODE'),
     ctx.h('h1',{},text(page.config.title,'Easy')),
     ctx.h('p',{class:'expo-easy-tagline'},text(page.config.subtitle,'كل يومك المالي في لمسة.')),
     ctx.h('p',{class:'expo-easy-description'},text(page.config.description)),
     ctx.h('div',{class:'expo-actions'},action(ctx,'ابدأ جولة Easy',ctx.sectionLink('services'),'expo-btn easy-primary'),poll?action(ctx,'صوّت الآن',targetFor(ctx,page,poll,'polls'),'expo-btn easy-soft'):null,action(ctx,'بطاقة الزائر',guestHref(page),'expo-btn easy-line')),
     ctx.h('div',{class:'expo-easy-trust'},ctx.h('span',{},'● تجربة بدون تسجيل إجباري'),ctx.h('span',{},page.offline?'● جاهزة دون إنترنت':'● مزامنة عند الاتصال'))),
   ctx.h('div',{class:'expo-easy-device-wrap'},
     ctx.h('div',{class:'expo-easy-halo halo-a'}),ctx.h('div',{class:'expo-easy-halo halo-b'}),
     ctx.h('div',{class:'expo-easy-phone'},
       ctx.h('div',{class:'expo-easy-phone-top'},ctx.h('span',{class:'expo-easy-avatar'},'E'),ctx.h('div',{},ctx.h('small',{},'مرحبًا بك في'),ctx.h('strong',{},'Easy Experience')),ctx.h('span',{class:'expo-easy-signal'},'◉')),
       ctx.h('div',{class:'expo-easy-balance'},ctx.h('small',{},'اختَر ما يهمك اليوم'),ctx.h('strong',{},'كل شيء أقرب'),ctx.h('span',{},'استكشف · صوّت · قيّم')),
       ctx.h('div',{class:'expo-easy-quick'},quick.slice(0,4).map((r,i)=>ctx.h('a',{href:r.code?targetFor(ctx,page,r,'services'):'#services',class:'expo-easy-quick-item'},ctx.h('span',{class:'expo-easy-quick-icon'},['↗','◌','⌁','◎'][i]||'•'),ctx.h('strong',{},r.title)))),
       offer?ctx.h('a',{class:'expo-easy-offer',href:targetFor(ctx,page,offer,'offers')},ctx.h('span',{},'عرض المعرض'),ctx.h('strong',{},offer.title),ctx.icon('arrow',17)):null)));
 const rail=ctx.h('section',{class:'expo-easy-journey'},
   ctx.h('div',{class:'expo-easy-journey-head'},ctx.h('span',{class:'expo-overline'},'ONE TAP JOURNEY'),ctx.h('h2',{},'اكتشف Easy بطريقتك'),ctx.h('p',{},'ليست صفحة تعريفية؛ كل بطاقة تقود لتفاعل أو قرار أو ملاحظة قابلة للقياس.')),
   ctx.h('div',{class:'expo-easy-feature-grid'},quick.slice(0,6).map((r,i)=>ctx.h('a',{class:'expo-easy-feature',href:r.code?targetFor(ctx,page,r,'services'):'#services'},ctx.h('span',{class:'expo-easy-feature-num'},String(i+1).padStart(2,'0')),ctx.h('strong',{},r.title),ctx.h('p',{},r.body||'افتح التجربة وتعرّف على التفاصيل.'),ctx.h('span',{class:'expo-easy-open'},'افتح التجربة ←')))));
 return {hero,after:rail,mode:'easy'};
}

function tharawat(page,ctx){
 const services=records(page,'service').slice(0,5),facts=records(page,'fact').slice(0,3),poll=first(page,'poll'),offer=first(page,'offer');
 const hero=ctx.h('section',{class:'expo-stage expo-tharawat-stage','aria-label':'Tharawat exhibition experience'},
   ctx.h('div',{class:'expo-tharawat-copy'},
     ctx.h('div',{class:'expo-tharawat-monogram'},'ث'),
     ctx.h('span',{class:'expo-tharawat-edition'},'THARAWAT · EXHIBITION EDITION'),
     ctx.h('h1',{},text(page.config.title,'ثروات')),
     ctx.h('p',{class:'expo-tharawat-tagline'},text(page.config.subtitle,'رؤية مالية تتفاعل مع اللحظة.')),
     ctx.h('p',{class:'expo-tharawat-description'},text(page.config.description)),
     ctx.h('div',{class:'expo-actions'},action(ctx,'استكشف الرؤية',ctx.sectionLink('services'),'expo-btn tharawat-primary'),poll?action(ctx,'شارك بصوتك',targetFor(ctx,page,poll,'polls'),'expo-btn tharawat-ghost'):null,action(ctx,'بطاقة الزائر',guestHref(page),'expo-btn tharawat-line'))),
   ctx.h('div',{class:'expo-tharawat-horizon'},
     ctx.h('div',{class:'expo-tharawat-orbit'},ctx.h('span',{class:'orbit orbit-1'}),ctx.h('span',{class:'orbit orbit-2'}),ctx.h('div',{class:'expo-tharawat-orbit-core'},ctx.h('small',{},'LIVE PERSPECTIVE'),ctx.h('strong',{},facts[0]?`${facts[0].value}${facts[0].unit?` ${facts[0].unit}`:''}`:'360°'),ctx.h('span',{},facts[0]?.title||'Connected view'))),
     ctx.h('div',{class:'expo-tharawat-notes'},
       (facts.length?facts:[{title:'رؤية مترابطة',value:'01'},{title:'قرارات أوضح',value:'02'}]).slice(0,3).map((f,i)=>ctx.h('a',{href:f.code?targetFor(ctx,page,f,'facts'):'#facts',class:'expo-tharawat-note'},ctx.h('span',{},`0${i+1}`.slice(-2)),ctx.h('strong',{},f.title),ctx.h('small',{},f.source||'Insight'))),
       offer?ctx.h('a',{href:targetFor(ctx,page,offer,'offers'),class:'expo-tharawat-note offer'},ctx.h('span',{},'NOW'),ctx.h('strong',{},offer.title),ctx.h('small',{},'Explore opportunity')):null)));
 const salon=ctx.h('section',{class:'expo-tharawat-salon'},
   ctx.h('div',{class:'expo-tharawat-salon-head'},ctx.h('span',{class:'expo-tharawat-rule'}),ctx.h('div',{},ctx.h('small',{},'THARAWAT DISCOVERY SALON'),ctx.h('h2',{},'من المعلومة إلى مساحة حوار')),ctx.h('span',{class:'expo-tharawat-rule'})),
   ctx.h('div',{class:'expo-tharawat-service-grid'},(services.length?services:[{title:'منظومة ثروات الرقمية'},{title:'حلول مالية للأفراد والأعمال'}]).map((r,i)=>ctx.h('a',{class:'expo-tharawat-service',href:r.code?targetFor(ctx,page,r,'services'):'#services'},ctx.h('span',{class:'expo-tharawat-index'},String(i+1).padStart(2,'0')),ctx.h('div',{},ctx.h('strong',{},r.title),ctx.h('p',{},r.body||'اكتشف الرؤية والخدمة والمسار المرتبط بها.')),ctx.h('span',{class:'expo-tharawat-arrow'},'↙')))));
 return {hero,after:salon,mode:'tharawat'};
}

export function exhibitionExperience(page,ctx){
 const tpl=page?.config?.template||'';
 if(tpl==='rts_tech')return rts(page,ctx);
 if(tpl==='easy_finance')return easy(page,ctx);
 if(tpl==='tharawat_finance')return tharawat(page,ctx);
 return null;
}
