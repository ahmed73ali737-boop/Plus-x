import {root,h,button,api,field,selectField,modal,setCSRF,newRequestKey} from './ui.mjs';
import {A,message,copy} from './self-certificate-client.mjs';
import {openSelfCertificateEditor} from './self-certificate-editor.mjs';

const titles={models:'النماذج',links:'الإصدار والروابط',history:'سجل الطلبات والشهادات'};
const descriptions={models:'صمّم نموذجك مرة واحدة، ثم استخدمه لإنشاء روابط طلب الشهادات.',links:'أنشئ رابطًا وQR للمشاركين، وتحكم في استقبال الطلبات لكل رابط.',history:'تابع الطلبات والصور الصادرة، ونزّل سجل حسابك كاملًا.'};
const states={registered:'مسجل',processing:'قيد التوليد',failed:'متعثر',issued:'صادر'};
const formatDate=value=>{if(!value)return '—';const date=new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)?value:value+'Z');return Number.isNaN(date.getTime())?value:new Intl.DateTimeFormat('ar',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(date)+' UTC';};

export async function selfCertificateAdmin(){
 let access;
 try{const me=await api('/api/auth/me');setCSRF(me.csrf);access=await api(A+'/access');}
 catch(e){if(e.status===401){location.href='/admin';return;}root.replaceChildren(h('main',{class:'selfcert-admin'},h('p',{},message(e)),h('a',{href:'/admin'},'الإدارة')));return;}
 let tab=access.can_manage?'models':'history',offset=0,timer,drawVersion=0,modelPage=0,query='',stateFilter='',disposed=false;
 const exportKeys=new Map();let exportRows=new Map();
 const search=field('البحث في بيانات حسابي','search','',{maxLength:160,placeholder:'اسم النموذج، أو الاسم والهاتف في السجل'});
 const state=selectField('حالة الطلب',[['','جميع الحالات'],...Object.entries(states)],'');
 const filters=h('form',{class:'selfcert-filter',role:'search'},search.node,state.node,h('button',{type:'submit',class:'btn secondary'},'تطبيق البحث'),button('مسح البحث',async()=>{query='';stateFilter='';search.input.value='';state.input.value='';offset=0;await draw();},'text-btn'));
 filters.addEventListener('submit',async e=>{e.preventDefault();query=search.input.value.trim();stateFilter=state.input.value;offset=0;await draw();});
 const content=h('section',{class:'selfcert-content','aria-live':'polite'}),error=h('p',{role:'alert',class:'selfcert-error'});
 const tabs=h('nav',{class:'selfcert-tabs','aria-label':'أقسام خدمة الشهادات'});
 const summary=h('div',{class:'selfcert-summary'}),tabButtons={};
 const badge=(text,state='')=>h('span',{class:'selfcert-badge '+state},text);
 const header=h('header',{class:'selfcert-heading'},h('a',{href:'/admin',class:'selfcert-brand'},'Eventna',h('small',{},'إيفنتنا · استوديو الشهادات')),h('a',{href:'/admin',class:'btn secondary'},'العودة للإدارة'));
 const main=h('main',{class:'selfcert-admin'},h('section',{class:'selfcert-hero'},h('div',{},h('span',{class:'eyebrow'},'خدمة الشهادات'),h('h1',{},'من تصميمك إلى شهادة يعتز بها المشارك'),h('p',{},'مكتبة خاصة بحسابك، وروابط طلب مستقلة، وسجل يجمع كل شهادة.')),badge(access.can_manage?'المكتبة متاحة':'السجل السابق متاح',access.can_manage?'active':'paused')),summary,tabs,filters,error,content,h('p',{class:'selfcert-privacy'},'مكتبتك وسجلك خاصان بحسابك. يمكنك إدارة النماذج دون فعالية؛ إنشاء الرابط يحتاج فعالية مخولًا بها.'),h('a',{href:'/admin?certificates=legacy',class:'selfcert-legacy-link'},'السجل وأدوات الإصدار السابقة'));
 root.replaceChildren(h('div',{class:'selfcert-dashboard'},header,main));
 for(const key of Object.keys(titles)){
  const b=button(titles[key],async()=>{tab=key;offset=0;query='';stateFilter='';search.input.value='';state.input.value='';await draw();},'selfcert-tab');
  b.setAttribute('aria-current',key===tab?'page':'false');tabButtons[key]=b;tabs.append(b);
 }
 function empty(title,detail,action){return h('div',{class:'selfcert-empty'},h('span',{class:'selfcert-empty-symbol','aria-hidden':'true'},'◇'),h('h3',{},title),h('p',{},detail),action);}
 function pager(total){
  const previous=button('السابق',async()=>{offset=Math.max(0,offset-30);await draw();},'btn secondary');
  const next=button('التالي',async()=>{offset+=30;await draw();},'btn secondary');
  previous.disabled=offset===0;next.disabled=offset+30>=total;
  return h('div',{class:'selfcert-pagination'},h('span',{},total?'عرض '+(offset+1)+'–'+Math.min(offset+30,total)+' من '+total:'0 سجل'),h('div',{class:'selfcert-toolbar'},previous,next));
 }
 async function updateSummary(version){
  const counts=await Promise.allSettled([access.can_manage?api(A+'/models?limit=1'):Promise.resolve(null),api(A+'/links?limit=1'),api(A+'/requests?limit=1')]);
  if(version!==drawVersion)return;
  summary.replaceChildren(...counts.map((result,index)=>h('article',{class:'selfcert-stat'},h('span',{},['نماذجي','روابط الطلب','جميع الطلبات'][index]),h('strong',{},result.status==='fulfilled'&&result.value?String(result.value.total):'—'),h('small',{},['نماذج محفوظة في مكتبتك','روابط محفوظة بحسابك','تشمل جميع حالات الطلب'][index]))));
 }
 async function draw(){
  const version=++drawVersion;clearTimeout(timer);error.textContent='';filters.hidden=tab==='links';state.node.hidden=tab!=='history';
  for(const [key,b]of Object.entries(tabButtons))b.setAttribute('aria-current',key===tab?'page':'false');
  content.replaceChildren(h('p',{class:'selfcert-loading',role:'status'},'جارٍ تحميل '+titles[tab]+'…'));
  updateSummary(version).catch(()=>{});
  try{
   if(tab==='models'){
    if(!access.can_manage){content.replaceChildren(empty('إدارة النماذج غير متاحة حاليًا','يمكنك متابعة سجلك السابق من قسم سجل الطلبات والشهادات.'));return;}
    const data=await api(A+'/models?offset='+offset+'&limit=30&q='+encodeURIComponent(query));if(version!==drawVersion)return;
    content.replaceChildren(h('div',{class:'selfcert-section-heading'},h('div',{},h('h2',{},'مكتبة النماذج'),h('p',{},descriptions.models)),button('إضافة نموذج شهادة',()=>openSelfCertificateEditor(null,draw))));
    const grid=h('div',{class:'selfcert-model-grid'});
    for(const row of data.items){
     const visual=h('div',{class:'selfcert-model-visual'},row.background_asset_id?h('img',{src:A+'/assets/'+encodeURIComponent(row.background_asset_id),alt:'خلفية نموذج '+row.name,loading:'lazy'}):h('span',{'aria-hidden':'true'},'◇'),h('span',{class:'selfcert-model-caption'},'خلفية النموذج'));
     grid.append(h('article',{class:'selfcert-model-card'},visual,h('div',{class:'selfcert-model-body'},h('h3',{},row.name),h('p',{class:'muted'},'آخر تحديث: '+formatDate(row.updated_at)),h('div',{class:'selfcert-toolbar'},button('فتح وتعديل',async()=>{try{await openSelfCertificateEditor(await api(A+'/models/'+row.id),draw);}catch(e){error.textContent=message(e);}},'btn secondary'),button('حذف النموذج',async()=>{if(!confirm('حذف هذا النموذج نهائيًا من المكتبة؟ الروابط القائمة والشهادات السابقة ستبقى دون تغيير.'))return;try{await api(A+'/models/'+row.id+'?row_version='+row.row_version,undefined,'DELETE');await draw();}catch(e){error.textContent=message(e);}},'text-btn selfcert-delete')))));
    }
    content.append(data.items.length?grid:empty('ابدأ بأول نموذج شهادة','ارفع الخلفية، وحدد موضع الاسم والختم، ثم احفظ البروفة من المحرر.'),pager(data.total));
   }else if(tab==='links'){
    const data=await api(A+'/links?offset='+offset+'&limit=30');if(version!==drawVersion)return;
    content.replaceChildren(h('div',{class:'selfcert-section-heading'},h('div',{},h('h2',{},'روابط طلب الشهادات'),h('p',{},descriptions.links)),access.can_manage?button('إنشاء رابط وQR لطلب الشهادات',()=>createLink()):null));
    const grid=h('div',{class:'selfcert-link-grid'});
    for(const row of data.items){
     const article=h('article',{class:'selfcert-link-card'},h('div',{class:'selfcert-link-top'},badge(row.status==='active'?'يستقبل طلبات جديدة':'الاستقبال متوقف',row.status),h('span',{class:'selfcert-link-label'},'رابط طلب شهادة')),h('h3',{},row.event_name_snapshot),h('p',{class:'muted'},'النموذج: '+row.model_name_snapshot),h('div',{class:'selfcert-link-address',dir:'ltr'},row.request_url),h('div',{class:'selfcert-toolbar'},h('a',{href:row.request_url,target:'_blank',rel:'noopener noreferrer',class:'btn secondary'},'فتح صفحة الطلب'),button('نسخ رابط الطلب',()=>copy(row.request_url),'btn secondary'),button('عرض QR وتنزيله',()=>showQR(row),'btn secondary')));
     if(access.can_manage)article.append(button(row.status==='active'?'إيقاف الجديد':'استئناف الجديد',async()=>{try{await api(A+'/links/'+row.id+'/state',{status:row.status==='active'?'paused':'active',row_version:row.row_version});await draw();}catch(e){error.textContent=message(e);}},'text-btn'));
     grid.append(article);
    }
    content.append(data.items.length?grid:empty('لم تنشئ روابط طلب بعد','اختر نموذجًا محفوظًا وفعالية مخولًا بها، ثم شارك الرابط أو رمز QR مع المشاركين.'),pager(data.total));
   }else{
    const [data,jobs]=await Promise.all([api(A+'/requests?offset='+offset+'&limit=30&q='+encodeURIComponent(query)+'&status='+encodeURIComponent(stateFilter)),api(A+'/exports')]);if(version!==drawVersion)return;
    content.replaceChildren(h('div',{class:'selfcert-section-heading'},h('div',{},h('h2',{},'سجل الطلبات والشهادات'),h('p',{},descriptions.history)),h('div',{class:'selfcert-toolbar'},button('تحديث السجل',draw,'btn secondary'),...['xlsx','csv'].map(format=>button('تصدير كامل السجل '+format.toUpperCase(),async()=>{try{const key=exportKeys.get(format)||newRequestKey();exportKeys.set(format,key);await api(A+'/exports',{format,idempotency_key:key});exportKeys.delete(format);await draw();}catch(e){error.textContent=message(e);}},'btn secondary')))));
    const table=h('table',{class:'selfcert-table'},h('caption',{class:'selfcert-sr-only'},'طلبات الشهادات الخاصة بحسابك'),h('thead',{},h('tr',{},['الاسم الأصلي / المطبوع','الهاتف','النموذج / الفعالية','وقت الطلب UTC','الحالة','الاستلام'].map(t=>h('th',{scope:'col'},t)))));
    const body=h('tbody');
    for(const row of data.items)body.append(h('tr',{},h('td',{},row.participant_name_original,h('small',{},row.name_printed)),h('td',{dir:'ltr'},row.phone_original),h('td',{},row.model_name_snapshot,h('small',{},row.event_name_snapshot)),h('td',{dir:'ltr'},formatDate(row.submitted_at_utc)),h('td',{},badge(states[row.status]||row.status,row.status),row.status==='failed'?button('إعادة معالجة الطلب نفسه',async()=>{try{await api(A+'/requests/'+row.id+'/retry',{});await draw();}catch(e){error.textContent=message(e);}},'text-btn'):null),h('td',{},row.receive_url?h('a',{href:row.receive_url,target:'_blank',rel:'noopener noreferrer',class:'text-btn'},'عرض الشهادة'):'—')));
    table.append(body);
    content.append(data.items.length?h('div',{class:'selfcert-table-wrap'},table):empty('لا توجد طلبات حتى الآن','ستظهر هنا أسماء المشاركين وحالة كل طلب بعد مشاركتهم عبر روابطك.'),pager(data.total));
    const exports=h('section',{class:'selfcert-exports'},h('h3',{},'ملفات التصدير'),h('p',{class:'muted'},'تجهز الملفات في الخلفية وتبقى متاحة لمدة 7 أيام، ويمكنك إنشاء تصدير جديد.'));
    exportRows=new Map();renderExportRows(exports,jobs.items);
    if(!jobs.items.length)exports.append(h('p',{},'لم تجهز ملفات تصدير بعد.'));
    content.append(exports);watchExports(exports,version,jobs.items.some(j=>['pending','processing'].includes(j.status)));
   }
  }catch(e){if(version===drawVersion){error.textContent=message(e);content.replaceChildren(empty('تعذر تحميل هذا القسم','أعد المحاولة بعد التحقق من الاتصال.',button('إعادة المحاولة',draw,'btn secondary')));}}
 }
 function renderExportRows(container,jobs){
  for(const job of jobs){
   let row=exportRows.get(job.id);
   if(!row){const statusNode=badge('',job.status),context=h('p',{class:'selfcert-export-context'}),download=h('a',{href:A+'/exports/'+job.id+'/download',class:'btn secondary',hidden:true},'تنزيل الملف');
    statusNode.setAttribute('role','status');
    const node=h('div',{class:'selfcert-export-row'},h('strong',{},job.format.toUpperCase()),statusNode,download,context);
    row={node,statusNode,context,download};exportRows.set(job.id,row);container.append(node);
   }
   const expired=job.error_code==='EXPORT_EXPIRED';
   row.statusNode.textContent=expired?'انتهت مدة الملف أو اللقطة':({pending:'بانتظار المعالجة',processing:'يجري التجهيز',done:'جاهز',failed:'تعذر التجهيز'})[job.status]||job.status;
   row.statusNode.className='selfcert-badge '+job.status;
   row.download.hidden=job.status!=='done'||expired;row.download.textContent='تنزيل '+job.row_count+' طلب';
   row.context.textContent=(job.snapshot_version>=2?'لقطة تأكيد الطلب: '+formatDate(job.snapshot_taken_at)+' · '+job.expected_rows+' طلب':'تصدير من النسخة السابقة')+
    (job.expires_at?' · انتهاء الملف: '+formatDate(job.expires_at):'')+
    (job.error_code==='EXPORT_SNAPSHOT_LEGACY_REQUIRED'?' · أنشئ تصديرًا جديدًا بلقطة ثابتة.':'');
  }
 }
 function watchExports(container,version,pending){
  clearTimeout(timer);
  if(!pending||disposed||!container.isConnected)return;
  timer=setTimeout(async()=>{
   if(disposed||tab!=='history'||version!==drawVersion||!container.isConnected)return;
   if(document.hidden){watchExports(container,version,true);return;}
   try{const jobs=await api(A+'/exports');if(version!==drawVersion)return;renderExportRows(container,jobs.items);watchExports(container,version,jobs.items.some(j=>['pending','processing'].includes(j.status)));}
   catch{watchExports(container,version,true);}
  },5000);
 }
 function showQR(row){
  const url=field('رابط الطلب','text',row.request_url,{readOnly:true,dir:'ltr'});
  modal('رابط الطلب وQR',h('section',{class:'selfcert-qr-dialog'},h('p',{},row.event_name_snapshot),url.node,h('img',{class:'selfcert-qr',src:row.qr_url,alt:'QR لفتح طلب شهادة مشاركة'}),h('div',{class:'selfcert-toolbar'},h('a',{href:row.qr_url,class:'btn',download:'certificate-request-qr.png'},'تنزيل QR'),button('نسخ الرابط',()=>copy(row.request_url),'btn secondary'))));
 }
 async function createLink(){
  if(!access.events.length){error.textContent='يمكنك إدارة النماذج، لكن يلزم تخويل فعالية لإنشاء رابط لها.';return;}
  modelPage=0;const event=selectField('الفعالية',access.events.map(e=>[e.id,e.name]),access.events[0].id);
  const model=selectField('النموذج',[],''),text=field('نص المشاركة الثابت','textarea','أعتز بمشاركتي في هذه الفعالية.',{maxLength:4000});
  const key=newRequestKey(),status=h('p',{role:'status'}),controls=h('div',{class:'selfcert-toolbar'}),selection=h('p',{class:'notice',role:'status'});
  let choices=[],pending=null;
  function summarize(){const selected=choices.find(row=>row.id===model.input.value);selection.textContent=selected?'ستثبت نسخة «'+selected.name+'» المحفوظة في '+formatDate(selected.updated_at)+' لفعالية «'+event.input.selectedOptions[0].textContent+'».':'اختر نموذجًا محفوظًا.';}
  model.input.addEventListener('change',summarize);event.input.addEventListener('change',summarize);
  const previous=button('نماذج سابقة',async()=>{modelPage=Math.max(0,modelPage-30);await load();},'btn secondary'),next=button('نماذج تالية',async()=>{modelPage+=30;await load();},'btn secondary');
  const submit=button('تأكيد إنشاء الرابط',async()=>{
   if(!pending){const selected=choices.find(row=>row.id===model.input.value);if(!selected)return;pending={event_id:event.input.value,model_id:model.input.value,share_text:text.input.value,idempotency_key:key,expected_revision_id:selected.current_revision_id};}
   submit.disabled=true;for(const input of [event.input,model.input,text.input,previous,next])input.disabled=true;
   try{const row=await api(A+'/links',pending);dialog.close();await draw();showQR(row);}
   catch(e){status.textContent=e.message==='MODEL_REVISION_CHANGED'?'تغير النموذج في جلسة أخرى. أغلق النافذة وراجع النسخة المحدثة قبل إنشاء الرابط.':message(e)+' يمكنك إعادة التأكيد لاستعادة الرابط نفسه، أو إغلاق النافذة ومراجعة قائمة الروابط.';submit.disabled=e.message==='MODEL_REVISION_CHANGED';}
  });submit.disabled=true;
  async function load(){
   try{const data=await api(A+'/models?offset='+modelPage+'&limit=30');choices=data.items;model.input.replaceChildren(...data.items.map(m=>h('option',{value:m.id},m.name)));status.textContent=data.total?'نماذج '+(modelPage+1)+'–'+Math.min(modelPage+30,data.total)+' من '+data.total:'أضف نموذجًا قبل إنشاء الرابط.';previous.disabled=modelPage===0;next.disabled=modelPage+30>=data.total;submit.disabled=!data.items.length;summarize();}
   catch(e){status.textContent=message(e);submit.disabled=true;}
  }
  controls.append(previous,next);
  const dialog=modal('إنشاء رابط وQR لطلب الشهادات',h('section',{},h('p',{class:'notice'},'يثبت الرابط نسخة النموذج عند تأكيد الإنشاء. سيظهر اسم الفعالية والنموذج في القائمة؛ تعديل النموذج أو إيقاف الجديد لا يلغي الشهادات السابقة.'),event.node,model.node,controls,selection,text.node,status,submit));
  await load();
 }
 window.addEventListener('pagehide',()=>{disposed=true;clearTimeout(timer);drawVersion++;},{once:true});
 await draw();
}
