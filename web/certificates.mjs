import {certificateImport} from './certificate-import.mjs';
import {certificateEditor} from './certificate-editor.mjs';
/** Shared administration shell; certificate lifecycle stays separate from admission. */
import {h,root,api,field,selectField,button,toast,modal} from './ui.mjs';
const states={valid:'صالحة',revoked:'ملغاة',expired:'منتهية',integrity_error:'تعذر تأكيد سلامة السجل'};
const errors={CERTIFICATE_TEXT_OVERFLOW:'يوجد نص يتجاوز مساحة الشهادة. قلّل حجم الخط أو عدّل موضع الطبقة ثم أعد المعاينة.',CERTIFICATE_DUPLICATE_OR_CONCURRENT_REQUEST:'توجد شهادة لهذا المشارك والمنجز. راجع السجل قبل إعادة الإصدار.',CERTIFICATE_REQUEST_CONFLICT:'تغيّرت بيانات طلب سابق. ابدأ طلبًا جديدًا.',CERTIFICATE_NOT_VALID:'هذه الشهادة غير صالحة للتحميل.',CERTIFICATE_NOT_FOUND:'الرابط أو رقم الشهادة غير موجود.',CERTIFICATE_VARIABLE_UNKNOWN:'أحد متغيرات القالب غير معروف.',CERTIFICATE_DATA_INVALID:'راجع بيانات الشهادة والحقول المطلوبة.'};
async function call(...args){try{return await api(...args);}catch(e){throw new Error(errors[e.message]||e.message);}}
const link=(label,url)=>h('a',{class:'btn secondary',href:url,target:'_blank',rel:'noopener noreferrer'},label);
function image(svg){const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));const img=h('img',{src:url,alt:'معاينة الشهادة',style:'width:100%;height:auto'});img.onload=()=>URL.revokeObjectURL(url);return img;}

export async function renderCertificates({host,current}){
 const base='/api/admin/events/'+encodeURIComponent(current.id);
 const [templates,register]=await Promise.all([call(base+'/certificate-templates'),call(base+'/certificates')]);
 host.replaceChildren(h('h2',{},'الشهادات'),h('p',{class:'muted'},'صمّم نسخة قالب، عاين بيانات المشارك، ثم أصدر الشهادة. تبقى البيانات والتصميم ثابتين بعد الإصدار.'));
 host.append(h('p',{class:'notice'},'الإصدار الفردي والمجمع والتحقق وPDF والصور متاحة. إرسال البريد وWhatsApp وSMS والمحافظ الرقمية يتطلب موصلات مزوّدي الخدمة.'));
 host.append(certificateEditor({base,templates,onSave:()=>renderCertificates({host,current})}));
 const form=h('form',{class:'card'}),picker=selectField('القالب',templates.items.map(t=>[t.id,t.name]),templates.items.at(-1)?.id);
 const fields={};for(const [key,label]of [['participant_name','اسم المشارك'],['course_title','الدورة أو المنجز'],['issuer_name','الجهة المصدرة'],['grade','التقدير (اختياري)'],['training_hours','ساعات التدريب (اختياري)'],['recipient_key','معرّف المشارك الثابت'],['award_key','رمز المنجز الثابت']]){
  fields[key]=field(label,key==='training_hours'?'number':'text','',{maxlength:key==='recipient_key'?160:key==='award_key'?80:250,...(key==='training_hours'?{min:0,max:100000,step:'any'}:{}),required:!['grade','training_hours'].includes(key)});
 }
 const zone=field('المنطقة الزمنية للشهادة','text',Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',{required:true,maxlength:80,dir:'ltr',placeholder:'Asia/Aden'});
 form.addEventListener('submit',event=>event.preventDefault());
 let requestKey=crypto.randomUUID();
 const payload=()=>({timezone:zone.input.value,template_id:picker.input.value,request_key:requestKey,recipient_key:fields.recipient_key.input.value,award_key:fields.award_key.input.value,data:Object.fromEntries(Object.entries(fields).filter(([k])=>!['recipient_key','award_key'].includes(k)).map(([k,v])=>[k,v.input.value]))});
 // Changing a request after a successful/uncertain submission requires a new key.
 form.addEventListener('input',()=>{requestKey=crypto.randomUUID();});
 const result=h('div',{'aria-live':'polite'});
 form.append(h('h3',{},'إصدار شهادة فردية'),h('p',{class:'muted'},'استخدم معرّف مشارك داخليًا ثابتًا، ورمزًا ثابتًا لكل دورة أو منجز. لا يلزم حساب أو OTP للمشارك.'),picker.node,zone.node,...Object.values(fields).map(f=>f.node),
 button('معاينة بيانات المشارك',async()=>{if(!form.reportValidity())return;const t=templates.items.find(t=>t.id===picker.input.value);if(!t)return;const p=await call(base+'/certificates/preview',{design:t.design,data:payload().data});modal('راجع الاسم والمنجز قبل الإصدار',image(p.svg));}),
 button('اعتماد وإصدار شهادة ثابتة',async()=>{if(!form.reportValidity()||!picker.input.value)return;const issued=await call(base+'/certificates',payload());result.replaceChildren(h('p',{},issued.created?'أُصدرت الشهادة. احفظ رابط الاستلام الخاص أدناه.':'سبق تنفيذ الطلب؛ لم تُنشأ شهادة مكررة.'),h('code',{},issued.certificate.serial),link('التحقق العام',issued.verification_url));if(issued.access_url)result.append(link('رابط استلام المشارك',issued.access_url));toast('حُفظت الشهادة');}),result);
 if(templates.items.length)host.append(form);else host.append(h('p',{},'احفظ قالبًا لإتاحة الإصدار.'));
 if(templates.items.length)host.append(certificateImport({base,templates:templates.items,onRefresh:()=>renderCertificates({host,current})}));
 const batches=await call(base+'/certificates/batches');if(batches.items.length)host.append(h('section',{class:'card'},h('h3',{},'تقدم الدفعات'),...batches.items.map(b=>h('p',{},b.import_id+' · '+({pending:'مجدولة / قيد الانتظار',running:'جارٍ الإصدار',done:'صدرت',failed:'فشلت'}[b.state]||b.state)+' · '+b.count))));
 const list=h('section',{class:'card'},h('h3',{},'سجل الشهادات'),h('p',{},'آخر 100 شهادة. رابط الاستلام الخاص يظهر عند إنشائه؛ استبداله يُبطل الرابط السابق.'));
 const refresh=button('تحديث السجل',()=>renderCertificates({host,current}));list.append(refresh);
 for(const cert of register.items){const row=h('article',{class:'card mini'},h('h4',{},cert.snapshot.data.participant_name),h('p',{},cert.snapshot.data.course_title+' · '+states[cert.validity]),h('code',{},cert.serial),link('التحقق','/verify/certificate/'+cert.serial));
 if(cert.validity==='valid')row.append(button('تصحيح واستبدال',async()=>{const fs={};for(const [key,label]of [['participant_name','اسم المشارك المصحح'],['course_title','المنجز المصحح'],['issuer_name','الجهة المصدرة']])fs[key]=field(label,'text',cert.snapshot.data[key],{required:true,maxlength:250});const reason=field('سبب الاستبدال','textarea','',{required:true,maxlength:500});const requestKey=crypto.randomUUID();const content=h('div',{},h('p',{},'سيُلغى الإصدار السابق، وتصدر شهادة برقم جديد مع حفظ الرابط بينهما.'),...Object.values(fs).map(f=>f.node),reason.node);content.append(button('إصدار التصحيح وإلغاء السابق',async()=>{if(!Object.values(fs).every(f=>f.input.reportValidity())||!reason.input.reportValidity())return;const result=await call(base+'/certificates/'+cert.id+'/replace',{request_key:requestKey,timezone:cert.snapshot.issue_timezone||Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',reason:reason.input.value,data:{...Object.fromEntries(Object.entries(cert.snapshot.data).filter(([k])=>!['serial','issue_date'].includes(k))),...Object.fromEntries(Object.entries(fs).map(([k,f])=>[k,f.input.value]))}});content.replaceChildren(h('p',{},'أُصدر التصحيح وأُلغي السابق.'),h('code',{},result.certificate.serial));if(result.access_url)content.append(link('استلام الشهادة المصححة',result.access_url));}));modal('تصحيح الشهادة',content);}),button('استبدال رابط الاستلام',async()=>{const r=await call(base+'/certificates/'+cert.id+'/access-link',{});modal('رابط خاص جديد — أُبطل الرابط السابق',link('فتح الشهادة',r.access_url));}),button('إلغاء الشهادة',async()=>{const reason=field('سبب الإلغاء','textarea','',{required:true,maxlength:500});const dialog=modal('إلغاء نهائي للشهادة',h('div',{},h('p',{},'يبقى رقم الشهادة في سجل التحقق بحالة ملغاة.'),reason.node,button('تأكيد الإلغاء',async()=>{if(!reason.input.reportValidity())return;await call(base+'/certificates/'+cert.id+'/revoke',{reason:reason.input.value});dialog.close();await renderCertificates({host,current});})));}));list.append(row);}
 if(!register.items.length)list.append(h('p',{},'لم تُصدر شهادات بعد.'));host.append(list);
}

export async function certificatePage(value,verify=false){
 document.title=verify?'التحقق من الشهادة — إيفنتنا':'شهادتك — إيفنتنا';
 let robots=document.querySelector('meta[name="robots"]');if(!robots){robots=document.createElement('meta');robots.name='robots';document.head.append(robots);}robots.content='noindex,nofollow';
 const row=await call('/api/public/certificates/'+(verify?'verify/':'access/')+encodeURIComponent(value));
 const main=h('main',{class:'container certificate-page'},h('section',{class:'card mini'},h('h1',{},verify?'التحقق من الشهادة':'شهادتك'),h('p',{role:'status'},states[row.status]),h('h2',{},row.participant_name),h('p',{},row.course_title),h('p',{},row.issuer_name),h('code',{},row.serial),h('p',{},'تاريخ الإصدار: '+row.issue_date+' ('+row.issue_timezone+')')));root.replaceChildren(main);
 if(verify){main.append(h('p',{},'تؤكد هذه الصفحة السجل الحالي لدى الجهة المصدرة. طابق البيانات مع الشهادة المعروضة عليك.'));return;}
 if(row.status!=='valid'){main.append(h('p',{},'التحميل غير متاح لهذه الحالة. تواصل مع الجهة المصدرة.'));return;}
 const src='/api/public/certificates/access/'+encodeURIComponent(value)+'/image.svg';
 const img=h('img',{src,alt:'الشهادة الصادرة',style:'width:100%;height:auto'});main.append(img,h('a',{class:'btn secondary',href:src,download:row.serial+'.svg'},'تحميل SVG'),h('a',{class:'btn',href:'/api/public/certificates/access/'+encodeURIComponent(value)+'/download.pdf',download:row.serial+'.pdf'},'تحميل PDF للطباعة'),h('a',{class:'btn secondary',href:'/api/public/certificates/access/'+encodeURIComponent(value)+'/download.png',download:row.serial+'.png'},'تحميل صورة PNG'),link('التحقق العام',row.verification_url),link('مشاركة رابط التحقق على LinkedIn','https://www.linkedin.com/sharing/share-offsite/?url='+encodeURIComponent(row.verification_url)));
 main.append(h('p',{class:'muted'},'شارك رابط التحقق العام. رابط الاستلام يمنح حامله إمكانية تحميل الشهادة. PDF صورة عالية الدقة بخط عربي ثابت. الإضافة المباشرة لملف LinkedIn والمحافظ الرقمية تحتاج إعداد المزوّد.'));
}
