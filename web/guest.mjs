import {h,root,api,field,selectField,check,button,toast,brand} from './ui.mjs';
import {bundle,get,put,del,all,status as offlineStatus,activate} from './offline.mjs';

function cleanLocalPhone(raw,countryCode='+967'){
  const digitMap={'٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9','۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9'};
  const ascii=x=>String(x||'').replace(/[٠-٩۰-۹]/g,d=>digitMap[d]);
  let v=ascii(raw).trim().replace(/[\s().-]+/g,'');
  if(v.startsWith('00'))v='+'+v.slice(2);
  let digits;
  if(v.startsWith('+'))digits=v.slice(1);
  else{
    digits=v.replace(/\D/g,'').replace(/^0+/,'');
    const cc=ascii(countryCode||'+967').replace(/\D/g,'');
    if(!digits.startsWith(cc)||digits.length<cc.length+6)digits=cc+digits;
  }
  if(!/^\d{8,15}$/.test(digits))throw new Error('أدخل رقم هاتف صحيحًا مع رمز الدولة.');
  return '+'+digits;
}
async function localPhoneFingerprint(phone){
  if(!crypto?.subtle)throw new Error('التسجيل دون اتصال يحتاج متصفحًا آمنًا يدعم Web Crypto.');
  const buf=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(phone));
  return [...new Uint8Array(buf)].map(x=>x.toString(16).padStart(2,'0')).join('');
}
function newProvisionalNumber(){
  const hex=crypto.randomUUID().replace(/-/g,'').toUpperCase();
  return 'P-'+hex.slice(0,4)+'-'+hex.slice(4,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16);
}

function newPassToken(){return crypto.randomUUID()+'.'+crypto.randomUUID();}
function localPhoneKey(slug,fingerprint){return 'phone-map:'+slug+':'+fingerprint;}
function applyTheme(page){
  const c=page.config||{};
  document.documentElement.style.setProperty('--accent',c.primary||'#176B73');
  document.documentElement.style.setProperty('--secondary',c.secondary||'#0F3D46');
  document.documentElement.style.setProperty('--theme-accent',c.accent||c.primary||'#29B8A8');
  document.documentElement.style.setProperty('--page-bg',c.background||'#F5F8FA');
  document.documentElement.style.setProperty('--surface',c.surface||'#fff');
  document.documentElement.style.setProperty('--text-color',c.text_color||'#17313B');
  document.body.dataset.template=c.template||'exhibition';
  document.body.classList.add('public-site','guest-surface');
}
function guestKey(slug,number){return slug+':'+number;}
async function dataUrl(url){
  const r=await fetch(url,{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error('QR_FETCH_FAILED');
  const b=await r.blob();return await new Promise((ok,no)=>{const fr=new FileReader();fr.onload=()=>ok(fr.result);fr.onerror=()=>no(fr.error);fr.readAsDataURL(b);});
}
async function cacheQr(slug,g){
  try{
    const qr='/api/public/events/'+encodeURIComponent(slug)+'/guests/'+encodeURIComponent(g.guest_number)+'/qr';
    g.qr_data_url=await dataUrl(qr);await put('guests',{...g,id:guestKey(slug,g.guest_number)});
  }catch{}
  return g;
}
async function syncGuestRegistrations(slug){
  if(!navigator.onLine)return{synced:0};
  const pending=(await all('guest_outbox')).filter(x=>x.slug===slug&&x.status==='pending').slice(0,100);
  if(!pending.length)return{synced:0};
  let synced=0;
  try{
    const out=await api('/api/public/events/'+encodeURIComponent(slug)+'/guests/sync',{items:pending.map(x=>x.body)});
    for(const receipt of out.receipts||[]){
      const item=pending.find(x=>x.body.client_id===receipt.client_id);if(!item)continue;
      if(receipt.status==='accepted'){
        const {pass_token:receiptPassToken,...safeReceipt}=receipt;
        await put('guest_receipts',{id:item.id,...safeReceipt,at:new Date().toISOString()});
        await del('guest_outbox',item.id);
        const local=item.local_id?await get('guests',item.local_id):null;
        const canonicalId=guestKey(slug,receipt.guest_number);
        const canonical={...(local||{}),id:canonicalId,slug,guest_number:receipt.guest_number,pass_token:receiptPassToken||local?.pass_token||item.body.pass_token||'',status:'registered',synced:true,provisional:false,verification_required:false,created:receipt.created,updated_at:new Date().toISOString()};
        delete canonical.phone;
        await put('guests',canonical);await cacheQr(slug,canonical);
        if(local&&item.local_id!==canonicalId)await put('guests',{...local,id:item.local_id,phone:'',pass_token:'',status:'reconciled',redirect_to:canonicalId,synced:true,provisional:false,updated_at:new Date().toISOString()});
        if(item.phone_key)await put('guests',{id:item.phone_key,kind:'phone_map',provisional_id:item.local_id,redirect_to:canonicalId,updated_at:new Date().toISOString()});
        synced++;
      }else if(receipt.status==='verification_required'){
        await put('guest_receipts',{id:item.id,...receipt,at:new Date().toISOString()});
        await del('guest_outbox',item.id);
        const local=item.local_id?await get('guests',item.local_id):null;
        if(local)await put('guests',{...local,phone:'',pass_token:'',status:'verification_required',verification_required:true,synced:true,provisional:false,qr_data_url:'',updated_at:new Date().toISOString()});
        synced++;
      }else await put('guest_outbox',{...item,status:'rejected',error:receipt.error});
    }
  }catch{}
  return{synced};
}
async function registerGuestOfflineFirst(slug,values){
  const phone=cleanLocalPhone(values.phone,values.country_code);
  const fingerprint=await localPhoneFingerprint(phone);
  const phoneKey=localPhoneKey(slug,fingerprint);
  const mapping=await get('guests',phoneKey);
  let existing=mapping?.provisional_id?await get('guests',mapping.provisional_id):null;
  if(mapping?.redirect_to){const canonical=await get('guests',mapping.redirect_to);if(canonical&&parseGuestNumber(canonical.guest_number))return canonical;if(canonical)existing=canonical;}
  if(existing?.redirect_to){const canonical=await get('guests',existing.redirect_to);if(canonical&&parseGuestNumber(canonical.guest_number))return canonical;if(canonical)existing=canonical;}
  if(existing?.verification_required||existing?.status==='verification_required')return existing;
  const provisionalNumber=existing?.provisional?existing.guest_number:newProvisionalNumber();
  const id=guestKey(slug,provisionalNumber);
  const pass_token=existing?.pass_token||newPassToken();
  const local={id,slug,guest_number:provisionalNumber,phone,pass_token,name:values.name||existing?.name||'',job_title:values.job_title||existing?.job_title||'',organization:values.organization||existing?.organization||'',status:'pending_sync',verification_required:false,synced:false,provisional:true,qr_data_url:'',updated_at:new Date().toISOString()};
  await put('guests',local);
  await put('guests',{id:phoneKey,kind:'phone_map',provisional_id:id,redirect_to:null,updated_at:new Date().toISOString()});
  const pending=(await all('guest_outbox')).find(x=>x.slug===slug&&x.local_id===id&&x.status==='pending');
  if(!pending){
    const client_id=crypto.randomUUID();
    await put('guest_outbox',{id:client_id,slug,local_id:id,phone_key:phoneKey,status:'pending',body:{client_id,phone,country_code:values.country_code,name:local.name,job_title:local.job_title,organization:local.organization,pass_token:local.pass_token,consent:true}});
  }
  await syncGuestRegistrations(slug);
  const reconciled=await get('guests',id);
  if(reconciled?.redirect_to){const canonical=await get('guests',reconciled.redirect_to);if(canonical)return canonical;}
  return reconciled||local;
}
function guestHeader(page,slug){
  const title=page.config?.title||'PulseX';const mark=title.trim().slice(0,1).toUpperCase()||'P';
  return h('header',{class:'topbar site-topbar'},h('div',{class:'topbar-inner'},brand(title,mark,'/e/'+slug),h('nav',{class:'toplinks'},h('a',{href:'/e/'+slug},'الفعالية'),h('a',{href:'/e/'+slug+'/guest'},'بطاقة الزائر'),h('a',{href:'/e/'+slug+'/scan'},'المسح')),h('span',{class:'tag'},navigator.onLine?'متصل':'دون اتصال')));
}
async function reconcileGuestPass(slug,g){
  await syncGuestRegistrations(slug);
  const cur=await get('guests',guestKey(slug,g.guest_number));
  if(cur?.redirect_to){
    const target=await get('guests',cur.redirect_to);
    if(target?.guest_number){
      location.replace('/e/'+slug+'/guest/'+encodeURIComponent(target.guest_number));
      return true;
    }
  }
  return false;
}
async function renderPass(page,slug,g){
  root.replaceChildren(guestHeader(page,slug));
  const host=h('main',{class:'guest-shell'});
  root.append(host);
  if(!g){
    host.append(h('section',{class:'guest-empty card'},h('h1',{},'تعذر العثور على بطاقة الزائر'),h('p',{class:'muted'},'سجّل برقم هاتفك أو جهّز هذه البطاقة على الجهاز قبل العمل دون اتصال.'),h('a',{class:'btn',href:'/e/'+slug+'/guest'},'إنشاء / استرجاع البطاقة')));
    return;
  }
  if(g.verification_required||g.status==='verification_required'){
    host.append(h('section',{class:'guest-empty card guest-verification-required'},
      h('span',{class:'eyebrow'},'GUEST PASS · PROTECTED'),
      h('h1',{},'البطاقة موجودة بالفعل'),
      h('p',{class:'lead'},'هذا الهاتف مسجل في الفعالية، لكن هذا الجهاز لا يملك إثبات البطاقة السابقة. لن نعرض QR أو رقم الزائر اعتمادًا على معرفة رقم الهاتف فقط.'),
      h('p',{class:'notice'},'افتح البطاقة من الجهاز الذي أنشأها أول مرة، أو راجع الاستقبال/المنظم للتحقق واستعادة البطاقة.'),
      h('div',{class:'actions'},h('a',{class:'btn secondary',href:'/e/'+slug},'العودة إلى الفعالية'),h('a',{class:'btn',href:'/e/'+slug+'/guest'},'محاولة رقم آخر'))
    ));
    return;
  }
  if(!g.provisional&&(!parseGuestNumber(g.guest_number)||!['registered','active'].includes(g.status||'registered'))){
    host.append(h('section',{class:'guest-empty card'},h('h1',{},'البطاقة غير صالحة للدخول'),h('p',{class:'notice'},'أُلغيت البطاقة أو استُبدلت بنسخة جديدة. راجع المنظم لاستلام البطاقة المعتمدة.')));return;
  }
  if(navigator.onLine&&!g.qr_data_url&&!g.provisional)g=await cacheQr(slug,g);
  if(g.provisional){
    const reconcileAndRender=async()=>{if(await reconcileGuestPass(slug,g))return;const latest=await get('guests',guestKey(slug,g.guest_number));if(latest?.verification_required||latest?.status==='verification_required')await renderPass(page,slug,latest);};
    window.addEventListener('online',reconcileAndRender,{once:true});
    if(navigator.onLine){await reconcileAndRender();if(!document.body.contains(host))return;}
  }
  host.append(h('section',{class:'guest-pass-wrap'},
    h('div',{class:'guest-pass'},
      h('div',{class:'guest-pass-glow'}),
      h('div',{class:'guest-pass-head'},h('div',{},h('span',{class:'eyebrow'},'PULSEX GUEST PASS'),h('h1',{},g.name||'زائر')),h('span',{class:'live-pill'},g.synced?'مسجّلة بالخادم':'محفوظة محليًا')),
      h('p',{class:'guest-event'},page.config.title),
      h('div',{class:'guest-number'},h('span',{},g.provisional?'رقم محلي مؤقت':'رقم الزائر'),h('strong',{},g.guest_number)),
      g.qr_data_url?h('img',{src:g.qr_data_url,alt:'QR '+g.guest_number,class:'guest-qr'}):h('div',{class:'qr-pending'},h('strong',{},g.provisional?'بانتظار خادم الفعالية لإنشاء QR النهائي':'QR ينتظر المزامنة'),h('small',{},g.provisional?'هذا الرقم المحلي لا يكشف هاتفك ولا يُستخدم كبطاقة دخول نهائية. عند الاتصال بخادم الفعالية سيستبدل برقم QR آمن.':'عند الوصول لخادم الفعالية سيظهر QR تلقائيًا.')),
      h('div',{class:'guest-meta'},g.organization?h('span',{},g.organization):null,g.job_title?h('span',{},g.job_title):null),
      h('div',{class:'guest-pass-actions'},h('a',{class:'btn secondary',href:'/e/'+slug},'موقع الفعالية'),g.provisional?null:button('طباعة البطاقة',()=>window.print(),'btn secondary'),button('تحديث البطاقة',async()=>{if(await reconcileGuestPass(slug,g))return;const latest=await get('guests',guestKey(slug,g.guest_number));if(latest?.verification_required||latest?.status==='verification_required'){await renderPass(page,slug,latest);return;}location.reload();},'btn'))
    ),
    h('aside',{class:'guest-help'},h('h2',{},'كيف تستخدمها؟'),h('ol',{},h('li',{},'احتفظ بهذه البطاقة على هاتفك.'),h('li',{},'عند البوابة اعرض QR أو رقم الزائر.'),h('li',{},'يحتاج الدخول بالدعوة أو لعدد محدد من المرافقين اتصال البوابة بخادم الفعالية. ويمكن تجهيز سجل محلي للفعاليات التي تسمح سياستها بذلك.')),h('p',{class:'notice'},'رقم الهاتف هو مفتاح منع التكرار. لا نضع رقم الهاتف داخل QR، ولكل فعالية بطاقة مستقلة.'))
  ));
}
export async function guestPage(slug,number=''){
  if(number){
    let g=await get('guests',guestKey(slug,number.toUpperCase()));
    if(g?.redirect_to){
      const target=await get('guests',g.redirect_to);
      if(target?.guest_number){location.replace('/e/'+slug+'/guest/'+encodeURIComponent(target.guest_number));return;}
    }
    // A private-event pass is an independent bearer endpoint. Do not fetch the
    // private event's public bundle merely to render its minimal pass surface.
    if(!g?.provisional&&!parseGuestNumber(number)){g=null;}
    else if(navigator.onLine&&!g?.provisional){
      try{const p=await api('/api/public/events/'+encodeURIComponent(slug)+'/guests/'+encodeURIComponent(number));g={...(g||{}),id:guestKey(slug,p.guest_number),slug,...p,guest_number:p.guest_number,synced:true};await put('guests',g);}catch(e){
        if([401,403,404,410].includes(e.status)){await del('guests',guestKey(slug,number.toUpperCase()));g=null;}
      }
    }
    const page={slug,config:{title:g?.event_title||'بطاقة الفعالية'}};applyTheme(page);document.title='بطاقة الزائر | '+page.config.title;activate();
    return renderPass(page,slug,g);
  }
  const page=await bundle(slug);applyTheme(page);document.title='بطاقة الزائر | '+page.config.title;activate();
  root.replaceChildren(guestHeader(page,slug));
  const host=h('main',{class:'guest-shell'});
  const country=field('رمز الدولة','tel','+967',{maxlength:6,inputmode:'tel',dir:'ltr'});
  const phone=field('رقم الهاتف','tel','',{required:true,autocomplete:'tel',inputmode:'tel',dir:'ltr',placeholder:'مثال: 777123456'});
  const name=field('الاسم — اختياري','text','',{autocomplete:'name',maxlength:160});
  const org=field('الجهة / الشركة — اختياري','text','',{maxlength:200});
  const job=field('المسمى الوظيفي — اختياري','text','',{maxlength:160});
  const consent=check('أوافق على استخدام رقم الهاتف لإنشاء هوية زائر فريدة ومنع التسجيل المكرر.');
  const form=h('form',{class:'guest-register-card card',onsubmit:async e=>{e.preventDefault();if(!consent.input.checked){toast('الموافقة مطلوبة لإنشاء بطاقة مرتبطة بالهاتف.',true);return;}const submit=e.currentTarget.querySelector('button[type=submit]');submit.disabled=true;try{const g=await registerGuestOfflineFirst(slug,{country_code:country.input.value,phone:phone.input.value,name:name.input.value.trim(),organization:org.input.value.trim(),job_title:job.input.value.trim()});history.replaceState({},'', '/e/'+slug+'/guest/'+g.guest_number);await renderPass(page,slug,g);}catch(err){toast(err.message||String(err),true);submit.disabled=false;}}},
    h('span',{class:'eyebrow'},'ONE PHONE · ONE GUEST'),h('h1',{},'بطاقتك للفعالية'),h('p',{class:'lead'},'أدخل رقم هاتفك مرة واحدة. لن ننشئ سجلًا ثانيًا للهاتف نفسه؛ وعلى جهازك الأصلي ستفتح بطاقتك نفسها، بينما جهاز جديد يحتاج إثبات البطاقة أو مساعدة المنظم.'),
    h('div',{class:'phone-grid'},country.node,phone.node),name.node,org.node,job.node,consent.node,
    h('p',{class:'muted small'},navigator.onLine?'سيتم التحقق من عدم التكرار وإثبات ملكية البطاقة على هذا الجهاز.':'أنت دون اتصال: سنحفظ طلبًا محليًا مؤقتًا، ولا يصدر QR نهائي إلا بعد المصالحة مع خادم الفعالية.'),
    h('button',{type:'submit',class:'btn guest-submit'},'إنشاء / فتح بطاقة الزائر'));
  host.append(form,h('section',{class:'guest-side'},h('div',{class:'guest-orbit'},h('span',{},'QR'),h('small',{},'SCAN · ENTER · ENGAGE')),h('h2',{},'الدخول أسرع. التجربة تستمر.'),h('p',{},'البطاقة تعمل مع المسح عند البوابة، وربط التفاعلات، والاستبيانات، والتصويت، والمتابعة داخل الفعالية.')));
  root.append(host);
}
export function parseGuestNumber(value){
  const raw=String(value||'').trim().toUpperCase();
  if(/^G-[0-9A-F]{30}$/.test(raw))return raw;
  try{const u=new URL(value,location.origin);if(!['http:','https:'].includes(u.protocol))return '';const m=u.pathname.toUpperCase().match(/^\/E\/[^/]+\/GUEST\/(G-[0-9A-F]{30})\/?$/);if(m)return m[1];}catch{}
  return '';
}
function gatePresenceKey(eventId,guestNumber){return eventId+':'+guestNumber;}
export function manifestReadiness(manifest,at=Date.now()){
  if(!manifest||typeof manifest!=='object'||!Array.isArray(manifest.guests))return{valid:false,reason:'MANIFEST_INCOMPLETE'};
  if(manifest.blocked)return{valid:false,reason:manifest.error||'DEVICE_NOT_PAIRED'};
  if(manifest.credential_version!==2)return{valid:false,reason:'MANIFEST_LEGACY'};
  if((manifest.guests||[]).some(g=>!/^G-[0-9A-F]{30}$/.test(g.guest_number||'')))return{valid:false,reason:'MANIFEST_LEGACY'};
  const limit=Number(manifest.access_control?.manifest_max_age_minutes),generated=Date.parse(manifest.generated_at||'');
  const age=(at-generated)/60000;
  if(!Number.isFinite(limit)||limit<=0||!Number.isFinite(age)||age< -5||age>limit)return{valid:false,reason:'MANIFEST_EXPIRED'};
  for(const field of ['device_valid_from','device_valid_until']){
    const raw=manifest[field];if(raw===undefined||raw===null||raw==='')continue;
    const time=Date.parse(raw);if(!Number.isFinite(time))return{valid:false,reason:'DEVICE_SHIFT_INVALID'};
    if((field==='device_valid_from'&&at<time)||(field==='device_valid_until'&&at>=time))return{valid:false,reason:'DEVICE_SHIFT_CLOSED'};
  }
  if(manifest.allowed_checkpoints!==undefined&&manifest.allowed_checkpoints!==null&&(!Array.isArray(manifest.allowed_checkpoints)||manifest.allowed_checkpoints.length===0))return{valid:false,reason:'DEVICE_CHECKPOINT_SCOPE'};
  if(!manifest.manifest_version||!manifest.access_policy_version)return{valid:false,reason:'MANIFEST_INCOMPLETE'};
  return{valid:true,age};
}
export function localManifestDecision(manifest,guest,online=navigator.onLine,checkpoint=''){
  const ready=manifestReadiness(manifest);if(!ready.valid)return{status:'invalid',reason:ready.reason};
  if(Array.isArray(manifest.allowed_checkpoints)&&checkpoint&&!manifest.allowed_checkpoints.includes(checkpoint))return{status:'invalid',reason:'DEVICE_CHECKPOINT_SCOPE'};
  if((manifest.requires_online||guest.admission_managed)&&(!online||manifest.offline))return{status:'invalid',reason:'ADMISSION_ONLINE_REQUIRED'};
  return{status:'valid'};
}
function emptyManifest(eventId,error='MANIFEST_UNAVAILABLE'){return{event_id:eventId,guests:[],blocked:true,error,offline:true,access_control:{checkpoints:[]}};}
export async function loadManifest(eventId,token){
  if(!eventId||!token)return emptyManifest(eventId,'DEVICE_NOT_PAIRED');
  try{
    const r=await fetch('/api/device/events/'+encodeURIComponent(eventId)+'/guest-manifest',{credentials:'same-origin',cache:'no-store',headers:{'X-PulseX-Device-Token':token}});
    if(!r.ok){await del('guest_manifests',eventId);return emptyManifest(eventId,'MANIFEST_HTTP_'+r.status);}
    let data;
    try{data=await r.json();}catch{await del('guest_manifests',eventId);return emptyManifest(eventId,'MANIFEST_INCOMPLETE');}
    if(!data||data.event_id!==eventId){await del('guest_manifests',eventId);return emptyManifest(eventId,'MANIFEST_EVENT_SCOPE');}
    const cached_at=new Date().toISOString();
    const state=manifestReadiness(data);if(!state.valid){await del('guest_manifests',eventId);return emptyManifest(eventId,state.reason);}
    await put('guest_manifests',{id:eventId,data,cached_at,token});
    for(const guest of data.guests||[])await put('gate_presence',{id:gatePresenceKey(eventId,guest.guest_number),event_id:eventId,guest_number:guest.guest_number,state:guest.presence||'outside',last_direction:guest.last_direction||'',last_checkpoint:guest.last_checkpoint||'',updated_at:guest.presence_updated_at||cached_at,source:'manifest'});
    return {...data,cached_at,offline:false};
  }catch{
    const cached=await get('guest_manifests',eventId);
    if(!cached||cached.token!==token)return emptyManifest(eventId,'MANIFEST_UNAVAILABLE');
    if(cached.data?.event_id!==eventId){await del('guest_manifests',eventId);return emptyManifest(eventId,'MANIFEST_EVENT_SCOPE');}
    const state=manifestReadiness(cached.data);if(!state.valid)return emptyManifest(eventId,state.reason);
    return{...cached.data,cached_at:cached.cached_at,offline:true};
  }
}
export async function gateContext(slug,token){
  const key='gate-context:'+slug;
  if(!token)return{slug,config:{title:'بوابة الفعالية'},blocked:true,error:'DEVICE_NOT_PAIRED'};
  try{
    const r=await fetch('/api/device/events/by-slug/'+encodeURIComponent(slug)+'/gate-context',{credentials:'same-origin',cache:'no-store',headers:{'X-PulseX-Device-Token':token}});
    if(!r.ok){const cached=await get('bundles',key);if(cached?.data?.event_id)await del('guest_manifests',cached.data.event_id);await del('bundles',key);return{slug,config:{title:'بوابة الفعالية'},blocked:true,error:'GATE_CONTEXT_HTTP_'+r.status};}
    const data=await r.json();await put('bundles',{id:key,data,token});return{id:data.event_id,slug,config:{title:data.title||'بوابة الفعالية'}};
  }catch{
    const cached=await get('bundles',key);
    if(cached?.token===token&&cached.data?.event_id)return{id:cached.data.event_id,slug,config:{title:cached.data.title||'بوابة الفعالية'}};
    return{slug,config:{title:'بوابة الفعالية'},blocked:true,error:'GATE_CONTEXT_UNAVAILABLE'};
  }
}
let checkinSyncing=null;
async function syncCheckins(eventId,token){
  if(checkinSyncing)return checkinSyncing;
  checkinSyncing=(async()=>{
    const pending=()=>all('checkin_outbox').then(xs=>xs.filter(x=>x.event_id===eventId&&x.status==='pending'));
    if(!token)return{synced:0,pending:(await pending()).length,error:'DEVICE_NOT_PAIRED'};
    if(!navigator.onLine)return{synced:0,pending:(await pending()).length,offline:true};
    const items=(await pending()).slice(0,100);if(!items.length)return{synced:0,pending:0};
    try{
      const r=await fetch('/api/device/events/'+encodeURIComponent(eventId)+'/guest-checkins',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-PulseX-Device-Token':token},body:JSON.stringify({items:items.map(x=>x.payload)})});
      if(!r.ok){if([401,403].includes(r.status)){await del('guest_manifests',eventId);return{synced:0,pending:(await pending()).length,error:'MANIFEST_HTTP_'+r.status,authorization_failed:true};}throw new Error('CHECKIN_SYNC_'+r.status);}
      const out=await r.json();let synced=0,rejected=0;
      for(const rc of out.receipts||[]){
        const item=items.find(x=>x.payload.scan_id===rc.scan_id);if(!item)continue;
        const terminal=['accepted','duplicate','already_inside','already_outside'];
        const priorReceipt=await get('checkin_receipts',item.id);
        if(priorReceipt?.status&&terminal.includes(priorReceipt.status)){await del('checkin_outbox',item.id);continue;}
        const accepted=terminal.includes(rc.status);
        if(accepted)synced++;else rejected++;
        await put('checkin_receipts',{id:item.id,...rc,at:new Date().toISOString()});
        if(rc.presence)await put('gate_presence',{id:gatePresenceKey(eventId,item.payload.guest_number),event_id:eventId,guest_number:item.payload.guest_number,state:rc.presence,last_direction:rc.direction||item.payload.direction||'',last_checkpoint:rc.checkpoint||item.payload.checkpoint||'',updated_at:new Date().toISOString(),source:'server'});
        if(accepted)await del('checkin_outbox',item.id);
        else{
          if(item.previous_presence)await put('gate_presence',{...item.previous_presence,id:gatePresenceKey(eventId,item.payload.guest_number),event_id:eventId,guest_number:item.payload.guest_number,updated_at:new Date().toISOString(),source:'server-rejected'});
          await put('checkin_outbox',{...item,status:'rejected',error:rc.error||rc.reason||rc.status});
        }
      }
      return{synced,rejected,pending:(await pending()).length,receipts:out.receipts||[]};
    }catch(e){return{synced:0,pending:(await pending()).length,error:String(e?.message||e)};}
  })();
  try{return await checkinSyncing;}finally{checkinSyncing=null;}
}
export async function scanPage(slug){
  const auth=(await get('bundles','device-auth'))?.data||{};const token=auth.token||'';
  const page=await gateContext(slug,token);applyTheme(page);document.body.dataset.surface='gate';document.title='ماسح الزوار | '+page.config.title;activate();
  let manifest=page.blocked?emptyManifest(page.id,page.error):await loadManifest(page.id,token);
  root.replaceChildren(guestHeader(page,slug));const host=h('main',{class:'scanner-shell'});root.append(host);

  const status=h('p',{class:'muted small'});
  const syncState=h('span',{class:'tag'},'المزامنة: جاهزة');
  const preflight=h('div',{class:'scanner-preflight'});
  const input=field('امسح QR أو ابحث بالاسم / الجهة / رقم الزائر','text','',{placeholder:'QR أو G-... أو اسم الزائر',autocomplete:'off'});
  const mode=selectField('وضع المسح',[['entry','دخول'],['exit','خروج'],['validate','تحقق فقط']],'entry');
  const checkpoint=selectField('نقطة الوصول',[], '');
  const result=h('div',{class:'scan-result empty',role:'status','aria-live':'polite','aria-atomic':'true'},'بانتظار المسح');
  let currentGuest=null;
  let showSerial=0;
  const authorizationRevoked=()=>{
    manifest=emptyManifest(page.id,'DEVICE_NOT_PAIRED');currentGuest=null;showSerial++;
    result.className='scan-result denied';result.replaceChildren(h('p',{class:'warning'},'أوقف الخادم تفويض الجهاز. أعد الربط بعد مراجعة المنظم. العمليات المعلقة محفوظة ولم تُحذف.'));
    refreshCheckpointOptions();refreshPreflight().catch(()=>{});
  };
  window.addEventListener('px-device-authorization-revoked',authorizationRevoked);
  window.addEventListener('beforeunload',()=>window.removeEventListener('px-device-authorization-revoked',authorizationRevoked),{once:true});

  function access(){return manifest.access_control||{anti_passback:true,allow_reentry:true,manifest_max_age_minutes:7200,checkpoints:[{key:'main',label:'البوابة الرئيسية',enabled:true,allowed_guest_types:[]}]};}
  function checkpoints(){const scoped=Array.isArray(manifest.allowed_checkpoints);const xs=(access().checkpoints||[]).filter(x=>x.enabled!==false&&(!scoped||manifest.allowed_checkpoints.includes(x.key)));return xs.length||scoped?xs:[{key:'main',label:'البوابة الرئيسية',enabled:true,allowed_guest_types:[]}];}
  function refreshCheckpointOptions(){
    const old=checkpoint.input.value;checkpoint.input.replaceChildren(...checkpoints().map(cp=>h('option',{value:cp.key},cp.label||cp.key)));
    if(!checkpoints().length){checkpoint.input.append(h('option',{value:'',disabled:true},'لا توجد بوابة مخوّلة'));checkpoint.input.value='';return;}
    checkpoint.input.value=checkpoints().some(cp=>cp.key===old)?old:checkpoints()[0].key;
  }
  refreshCheckpointOptions();

  function reasonText(reason){
    return ({
      CHECKPOINT_NOT_FOUND:'نقطة الوصول غير معرفة.',
      CHECKPOINT_DISABLED:'نقطة الوصول موقوفة.',
      CHECKPOINT_WINDOW_CLOSED:'نقطة الوصول خارج وقت السماح.',
      GUEST_TYPE_NOT_ALLOWED:'نوع هذا الزائر غير مسموح في نقطة الوصول.',
      GUEST_NOT_ACTIVE:'تسجيل الزائر غير فعال.',
      REENTRY_NOT_ALLOWED:'سياسة الفعالية لا تسمح بإعادة الدخول بعد الخروج.',
      ACCESS_POLICY_CHANGED:'تغيرت سياسة الوصول منذ تجهيز الجهاز؛ راجع الحركة قبل اعتمادها.',
      OFFLINE_SCAN_TIME_INVALID:'وقت المسح غير صالح.',
      OFFLINE_SCAN_TIME_FUTURE:'ساعة الجهاز متقدمة أكثر من الحد المسموح.',
      SCAN_ID_CONFLICT:'معرّف المسح استُخدم سابقًا لحركة مختلفة.',
      GUEST_NOT_REGISTERED:'الزائر غير مسجل في هذه الفعالية.',
      DEVICE_NOT_PAIRED:'اربط جهاز البوابة من لوحة الإدارة ثم افتح الماسح متصلًا بخادم الفعالية.',
      MANIFEST_LEGACY:'سجل قديم: يلزم تحديث بطاقات الزوار وتجهيز البوابة من جديد.',
      MANIFEST_EXPIRED:'انتهت صلاحية سجل الزوار أو توقيت الجهاز غير صحيح؛ اتصل بالخادم لتحديثه.',
      MANIFEST_INCOMPLETE:'سجل الزوار غير مكتمل؛ أعد تجهيزه من الخادم.',
      MANIFEST_UNAVAILABLE:'لا يوجد سجل زوار صالح مرتبط بهذا الجهاز.',
      ONLINE_ADMISSION_REQUIRED:'هذه الدعوة تحتاج تأكيد الخادم؛ لا تسمح بالدخول أثناء الانقطاع.',
      OFFLINE_SCAN_EXPIRED:'الحركة المحلية قديمة وتحتاج مراجعة المشرف؛ لم تُعتمد.',
      ADMISSION_ONLINE_REQUIRED:'هذه الدعوة تحتاج تأكيد الخادم. اتصل بشبكة الفعالية المحلية أو بالإنترنت؛ لا تسمح بالدخول قبل التأكيد.',
      ADMISSION_ALREADY_USED:'اكتمل العدد المسموح بهذه الدعوة لهذا اليوم.',
      ADMISSION_QUANTITY_INVALID:'عدد الأشخاص غير صالح أو يتجاوز المتبقي في الدعوة.',
      MANIFEST_HTTP_401:'انتهى ربط الجهاز. أعد ربطه من لوحة الإدارة.',
      MANIFEST_HTTP_403:'الجهاز غير مخوّل لهذه الفعالية. لا يمكن استخدام السجل المحلي.',
      GATE_CONTEXT_HTTP_401:'انتهى ربط الجهاز. أعد ربطه من لوحة الإدارة.',
      GATE_CONTEXT_HTTP_403:'الجهاز غير مخوّل لهذه الفعالية. لا يمكن استخدام السجل المحلي.',
      GATE_CONTEXT_UNAVAILABLE:'افتح الماسح متصلًا بخادم الفعالية لتجهيز الجهاز أول مرة.',
      DEVICE_SHIFT_CLOSED:'الجهاز خارج وقت المناوبة المسموح. لا يمكن اعتماد الدخول من السجل المحلي.',
      DEVICE_SHIFT_INVALID:'توقيت مناوبة الجهاز غير صالح؛ راجع المشرف.',
      DEVICE_CHECKPOINT_SCOPE:'هذه البوابة غير مخوّلة لهذا الجهاز؛ راجع المشرف.',
    })[reason]||reason||'غير مسموح.';
  }
  function feedback(ok){try{navigator.vibrate?.(ok?60:[80,45,80]);}catch{}}
  function localAccess(g){
    if(!token)return{status:'invalid',reason:'DEVICE_NOT_PAIRED'};
    const decision=localManifestDecision(manifest,g,navigator.onLine,checkpoint.input.value);if(decision.status!=='valid')return decision;
    const cp=(access().checkpoints||[]).find(x=>x.key===checkpoint.input.value);
    if(!cp)return{status:'invalid',reason:'CHECKPOINT_NOT_FOUND'};
    if(cp.enabled===false)return{status:'invalid',reason:'CHECKPOINT_DISABLED'};
    const nowMs=Date.now(),start=cp.start?Date.parse(cp.start):NaN,end=cp.end?Date.parse(cp.end):NaN;
    if((Number.isFinite(start)&&nowMs<start)||(Number.isFinite(end)&&nowMs>=end))return{status:'invalid',reason:'CHECKPOINT_WINDOW_CLOSED'};
    const allowed=cp.allowed_guest_types||[];if(allowed.length&&!allowed.includes(g.guest_type||'visitor'))return{status:'invalid',reason:'GUEST_TYPE_NOT_ALLOWED'};
    if(!['registered','active'].includes(g.status||'registered'))return{status:'invalid',reason:'GUEST_NOT_ACTIVE'};
    return{status:'valid'};
  }
  async function authoritativeValidate(g){
    const local=localAccess(g);if(local.status!=='valid'||!navigator.onLine||!token)return local;
    try{
      const r=await fetch('/api/device/events/'+encodeURIComponent(page.id)+'/guests/'+encodeURIComponent(g.guest_number)+'/validate?checkpoint='+encodeURIComponent(checkpoint.input.value)+'&mode='+encodeURIComponent(mode.input.value),{credentials:'same-origin',cache:'no-store',headers:{'X-PulseX-Device-Token':token}});
      if(!r.ok){const e=await r.json().catch(()=>({}));if([401,403].includes(r.status)){await del('guest_manifests',page.id);manifest=emptyManifest(page.id,'MANIFEST_HTTP_'+r.status);}return{status:'invalid',reason:e.detail||('HTTP_'+r.status)};}
      return await r.json();
    }catch{return(manifest.requires_online||g.admission_managed)?{status:'invalid',reason:'ADMISSION_ONLINE_REQUIRED'}:{...local,offline:true};}
  }
  async function refreshPreflight(){
    const local=await offlineStatus();let persisted=false;try{persisted=await navigator.storage?.persisted?.()||false;}catch{}
    const readiness=manifestReadiness(manifest),age=(Date.now()-Date.parse(manifest.generated_at||''))/60000,fresh=readiness.valid;
    status.textContent=!fresh?reasonText(readiness.reason):manifest.requires_online&&(!navigator.onLine||manifest.offline)?reasonText('ADMISSION_ONLINE_REQUIRED'):manifest.offline?'Offline · حركات محلية مؤقتة حتى تأكيد الخادم':'الجهاز مرتبط · سجل الزوار محدث';
    status.className='muted small'+(!fresh||manifest.offline?' warning':'');
    const checks=[
      ['الربط',token?'جاهز':'غير مربوط',!!token],
      ['سجل الزوار',(manifest.guest_count??(manifest.guests||[]).length)+' زائر',(manifest.guests||[]).length>0],
      ['نسخة السجل',manifest.manifest_version?manifest.manifest_version.slice(0,8):'—',!!manifest.manifest_version],
      ['نسخة السياسة',manifest.access_policy_version?manifest.access_policy_version.slice(0,8):'—',!!manifest.access_policy_version],
      ['حداثة السجل',Number.isFinite(age)?Math.round(age)+' د':'غير مجهز',fresh],
      ['نقاط الوصول',String(checkpoints().length),checkpoints().length>0],
      ['الطابور',local.pending?local.pending+' معلّق':'0 معلّق',local.pending===0],
      ['المرفوض',local.rejected?local.rejected+' يحتاج مراجعة':'0',local.rejected===0],
      ['التخزين',persisted?'مستمر':'قد يفرغه المتصفح',persisted],
      ['الكاميرا','BarcodeDetector'in window?'مدعومة':'ماسح/بحث يدوي',true],
      ['الشبكة',navigator.onLine?'متصل':'Offline',true],
    ];
    preflight.replaceChildren(...checks.map(([label,value,ok])=>h('div',{class:'preflight-chip'+(ok?' ready':' warning')},h('small',{},label),h('strong',{},value))));if(manifest.cached_at)preflight.append(h('small',{class:'muted preflight-time'},'آخر تجهيز: '+new Date(manifest.cached_at).toLocaleString('ar-YE')));
  }
  async function refreshSync(notify=false){
    const out=await syncCheckins(page.id,token);
    if(out.authorization_failed){manifest=emptyManifest(page.id,out.error);await del('bundles','gate-context:'+slug);}
    syncState.textContent=out.pending?'معلّق: '+out.pending:out.error?'المزامنة تحتاج اتصال':'تمت المزامنة';
    if(notify)toast(out.pending?'ما زالت '+out.pending+' حركة محفوظة محليًا.':'تمت مزامنة حركات البوابة.');
    await refreshPreflight();return out;
  }
  function matchesFor(raw){
    const exact=parseGuestNumber(raw);if(exact)return(manifest.guests||[]).filter(x=>x.guest_number===exact);
    // Malformed/legacy QR values must never become a fuzzy name search.
    if(/^G-|^P-|https?:|\/guest\//i.test(String(raw||'').trim()))return[];
    const q=String(raw||'').trim().toLowerCase();if(q.length<2)return[];
    return(manifest.guests||[]).filter(g=>[g.guest_number,g.name,g.organization,g.job_title].some(v=>String(v||'').toLowerCase().includes(q)));
  }
  function chooseMatches(matches){
    result.className='scan-result';
    result.replaceChildren(h('h3',{},'وجدت أكثر من زائر'),h('p',{class:'muted'},'اختر السجل الصحيح قبل تنفيذ أي حركة.'),h('div',{class:'scan-match-list'},matches.slice(0,8).map(g=>button((g.name||'زائر')+' · '+g.guest_number,()=>{input.input.value=g.guest_number;show(g.guest_number);},'btn secondary'))));
  }
  async function findGuest(raw,refresh=true){
    let matches=matchesFor(raw);
    if(!matches.length&&navigator.onLine&&token&&refresh){manifest=await loadManifest(page.id,token);refreshCheckpointOptions();await refreshPreflight();matches=matchesFor(raw);}
    return matches;
  }
  async function show(raw){
    const serial=++showSerial;
    const matches=await findGuest(raw);
    if(serial!==showSerial)return;
    if(matches.length>1){currentGuest=null;chooseMatches(matches);feedback(false);return;}
    const g=matches[0];currentGuest=g||null;
    if(!g){const ready=manifestReadiness(manifest);result.className='scan-result denied';result.replaceChildren(h('p',{class:'warning'},ready.valid?'لم أجد زائرًا مطابقًا في سجل البوابة. استخدم الاسم أو رقم الزائر، أو حدّث السجل عند توفر الاتصال.':reasonText(ready.reason)));feedback(false);return;}

    const validation=await authoritativeValidate(g);
    if(serial!==showSerial)return;
    if(validation.status!=='valid'){
      result.className='scan-result denied';result.replaceChildren(h('span',{class:'tag'},'غير مسموح'),h('h2',{},g.name||'زائر'),h('strong',{class:'scan-number'},g.guest_number),h('p',{class:'warning'},reasonText(validation.reason)));feedback(false);return;
    }

    const selectedMode=mode.input.value;
    const presence=await get('gate_presence',gatePresenceKey(page.id,g.guest_number))||{state:g.presence||'outside',last_direction:g.last_direction||'',last_checkpoint:g.last_checkpoint||''};
    if(serial!==showSerial)return;
    if(selectedMode==='validate'){
      const provisional=validation.offline||manifest.offline||!navigator.onLine;
      result.className='scan-result '+(provisional?'ready':'success');result.replaceChildren(h('span',{class:'tag status-current'},provisional?'تحقق محلي مؤقت':'البيانات صالحة — لم يُسجل دخول'),h('h2',{},g.name||'زائر'),h('strong',{class:'scan-number'},g.guest_number),h('p',{},[g.organization,g.job_title,g.guest_type].filter(Boolean).join(' · ')),h('p',{class:'muted'},'الحالة الحالية: '+(validation.presence||presence.state||'outside')+' · نقطة الوصول: '+checkpoint.input.value));feedback(!provisional);return;
    }

    const policy=access();
    const managed=!!(manifest.requires_online||g.admission_managed||validation.admission?.managed);
    const quantity=field('عدد الأشخاص الداخلين الآن','number','1',{min:1,max:validation.admission?.remaining||51,step:1,inputmode:'numeric'});
    let pendingScanId='';
    const check=button(selectedMode==='exit'?'تسجيل خروج':'تسجيل دخول',async()=>{
      if(serial!==showSerial)return;
      const admission=await authoritativeValidate(g);if(serial!==showSerial)return;if(admission.status!=='valid'){toast(reasonText(admission.reason),true);feedback(false);return;}
      const count=managed&&selectedMode==='entry'?Number(quantity.input.value):1;
      if(!Number.isInteger(count)||count<1||count>51||(Number.isFinite(admission.admission?.remaining)&&count>admission.admission.remaining)){toast(reasonText('ADMISSION_QUANTITY_INVALID'),true);return;}
      const latest=await get('gate_presence',gatePresenceKey(page.id,g.guest_number))||presence;
      if(serial!==showSerial)return;
      if(!managed&&policy.anti_passback!==false&&selectedMode==='entry'&&latest.state==='inside'){toast('الزائر داخل الفعالية بالفعل. استخدم «تحقق فقط» أو «خروج».',true);feedback(false);return;}
      if(policy.anti_passback!==false&&selectedMode==='exit'&&latest.state!=='inside'){toast('الزائر خارج الفعالية بالفعل.',true);feedback(false);return;}
      if(selectedMode==='entry'&&policy.allow_reentry===false&&latest.last_direction==='exit'){toast('سياسة الفعالية لا تسمح بإعادة الدخول بعد الخروج.',true);feedback(false);return;}
      const pending=(await all('checkin_outbox')).find(x=>x.event_id===page.id&&x.status==='pending'&&x.payload.guest_number===g.guest_number&&x.payload.mode===selectedMode);
      if(serial!==showSerial)return;
      const scan_id=pending?.id||pendingScanId||crypto.randomUUID(),point=checkpoint.input.value;pendingScanId=scan_id;
      const previous={state:latest.state||'outside',last_direction:latest.last_direction||'',last_checkpoint:latest.last_checkpoint||''};
      const scannedOffline=!navigator.onLine||manifest.offline||!!admission.offline;
      if(managed&&scannedOffline){toast(reasonText('ADMISSION_ONLINE_REQUIRED'),true);return;}
      if(!pending)await put('checkin_outbox',{id:scan_id,event_id:page.id,status:'pending',previous_presence:previous,payload:{scan_id,guest_number:g.guest_number,mode:selectedMode,direction:selectedMode,checkpoint:point,quantity:count,client_time:new Date().toISOString(),offline_scan:scannedOffline,manifest_generated_at:manifest.generated_at,access_policy_version:manifest.access_policy_version||''}});
      if(!managed)await put('gate_presence',{id:gatePresenceKey(page.id,g.guest_number),event_id:page.id,guest_number:g.guest_number,state:selectedMode==='entry'?'inside':'outside',last_direction:selectedMode,last_checkpoint:point,updated_at:new Date().toISOString(),source:'local-pending'});
      const out=await refreshSync(false),receipt=await get('checkin_receipts',scan_id),label=selectedMode==='exit'?'الخروج':'الدخول';
      if(receipt?.status==='already_inside'||receipt?.status==='already_outside'){toast(receipt.status==='already_inside'?'لم تُسجل حركة جديدة: الزائر داخل الفعالية بالفعل.':'لم تُسجل حركة جديدة: الزائر خارج الفعالية بالفعل.',true);feedback(false);return;}
      const rejected=await get('checkin_outbox',scan_id);
      if(rejected?.status==='rejected'){toast('رفض الخادم الحركة: '+reasonText(rejected.error),true);feedback(false);return;}
      if(!receipt||!['accepted','duplicate'].includes(receipt.status)){toast(managed?'الطلب محفوظ وبانتظار تأكيد الخادم. لا تسمح بالدخول بعد؛ استخدم مزامنة الآن للتحقق.':'الحركة محفوظة محليًا ومؤقتة حتى تأكيد الخادم؛ لا يمكن ضمان عدم التكرار بين الأجهزة المنقطعة.',true);feedback(false);return;}
      pendingScanId='';toast('أكد الخادم تسجيل '+label+'.');feedback(true);
      g.presence=selectedMode==='entry'?'inside':'outside';g.last_direction=selectedMode;g.last_checkpoint=point;
      if(managed){manifest=await loadManifest(page.id,token);await show(g.guest_number);}
    },'btn');
    result.className='scan-result ready';result.replaceChildren(...[h('span',{class:'tag'},g.guest_type||'visitor'),h('h2',{},g.name||'زائر'),h('strong',{class:'scan-number'},g.guest_number),h('p',{},[g.organization,g.job_title].filter(Boolean).join(' · ')),h('p',{class:'muted'},'الحالة الحالية: '+presence.state+' · '+(checkpoint.input.selectedOptions[0]?.textContent||checkpoint.input.value)),managed&&selectedMode==='entry'?quantity.node:null,managed&&selectedMode==='entry'?h('p',{class:'notice'},'يلزم تأكيد الخادم لكل دفعة. المتبقي: '+(validation.admission?.remaining??'يحدده الخادم')):null,check].filter(Boolean));
  }

  const tools=h('div',{class:'scanner-tools'},input.node,mode.node,checkpoint.node,button('بحث / فتح',()=>show(input.input.value),'btn secondary'),button('تحديث سجل الزوار',async()=>{manifest=await loadManifest(page.id,token);refreshCheckpointOptions();await refreshPreflight();toast('تم تحديث السجل: '+(manifest.guests||[]).length+' زائر · '+(manifest.manifest_version||'').slice(0,8));},'btn secondary'),button('مزامنة الآن',()=>refreshSync(true),'btn secondary'),syncState);
  input.input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();show(input.input.value);}});
  // Native Android QR decoding is only another input channel. The same scoped
  // manifest, verification, anti-passback and server confirmation still apply.
  const nativeScan=e=>{if(typeof e.detail==='string'&&e.detail.length<=4096){input.input.value=e.detail;show(e.detail);}};
  window.addEventListener('pulsex:native-scan',nativeScan);
  window.addEventListener('beforeunload',()=>window.removeEventListener('pulsex:native-scan',nativeScan),{once:true});
  mode.input.addEventListener('change',()=>currentGuest&&show(currentGuest.guest_number));
  checkpoint.input.addEventListener('change',()=>currentGuest&&show(currentGuest.guest_number));

  const video=h('video',{class:'scanner-video',autoplay:true,playsinline:true,muted:true});
  const cameraBox=h('section',{class:'scanner-camera'},video,h('div',{class:'scan-frame'}));
  host.append(h('section',{class:'scanner-panel'},h('span',{class:'eyebrow'},'OFFLINE ACCESS CONTROL'),h('h1',{},'بوابة الدخول والتحقق'),status,h('div',{class:'between preflight-head'},h('h3',{},'جاهزية البوابة'),button('إعادة الفحص',refreshPreflight,'text-btn')),preflight,tools,cameraBox,result));
  await refreshPreflight();

  const retry=async()=>{const out=await refreshSync(false);return out;};
  const reconnect=()=>setTimeout(async()=>{manifest=await loadManifest(page.id,token);refreshCheckpointOptions();await retry();},350);
  const retryTimer=setInterval(()=>{if(navigator.onLine)retry();},3000);
  window.addEventListener('online',reconnect);
  window.addEventListener('beforeunload',()=>{clearInterval(retryTimer);window.removeEventListener('online',reconnect);},{once:true});
  await refreshSync(false);

  if('BarcodeDetector'in window&&navigator.mediaDevices?.getUserMedia){
    try{
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});video.srcObject=stream;const detector=new BarcodeDetector({formats:['qr_code']});
      let busy=false,lastRaw='',lastAt=0;
      const tick=async()=>{if(busy)return;busy=true;try{for(const code of await detector.detect(video)){if(code.rawValue){const now=Date.now();if(code.rawValue!==lastRaw||now-lastAt>1500){lastRaw=code.rawValue;lastAt=now;input.input.value=code.rawValue;await show(code.rawValue);}break;}}}catch{}finally{busy=false;}};setInterval(tick,650);
    }catch{cameraBox.append(h('p',{class:'notice'},'تعذر فتح الكاميرا. استخدم البحث اليدوي أو ماسح QR متصل بالجهاز.'));}
  }else cameraBox.append(h('p',{class:'notice'},'المتصفح لا يدعم مسح QR بالكاميرا مباشرة. استخدم البحث اليدوي أو قارئ QR متصلًا بالجهاز.'));
}
