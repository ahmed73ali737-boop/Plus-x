/** Shared administration shell; certificate lifecycle stays separate from admission. */
import {h,root,api,field,selectField,button,toast,modal} from './ui.mjs';
const states={valid:'صالحة',revoked:'ملغاة',expired:'منتهية',integrity_error:'تعذر تأكيد سلامة السجل'};
const errors={CERTIFICATE_DUPLICATE_OR_CONCURRENT_REQUEST:'توجد شهادة لهذا المشارك والمنجز. راجع السجل قبل إعادة الإصدار.',CERTIFICATE_REQUEST_CONFLICT:'تغيّرت بيانات طلب سابق. ابدأ طلبًا جديدًا.',CERTIFICATE_NOT_VALID:'هذه الشهادة غير صالحة للتحميل.',CERTIFICATE_NOT_FOUND:'الرابط أو رقم الشهادة غير موجود.',CERTIFICATE_VARIABLE_UNKNOWN:'أحد متغيرات القالب غير معروف.',CERTIFICATE_DATA_INVALID:'راجع بيانات الشهادة والحقول المطلوبة.'};
async function call(...args){try{return await api(...args);}catch(e){throw new Error(errors[e.message]||e.message);}}
const link=(label,url)=>h('a',{class:'btn secondary',href:url,target:'_blank',rel:'noopener noreferrer'},label);
function image(svg){const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));const img=h('img',{src:url,alt:'معاينة الشهادة',style:'width:100%;height:auto'});img.onload=()=>URL.revokeObjectURL(url);return img;}

export async function renderCertificates({host,current}){
 const base='/api/admin/events/'+encodeURIComponent(current.id);
 const [templates,register]=await Promise.all([call(base+'/certificate-templates'),call(base+'/certificates')]);
 host.replaceChildren(h('h2',{},'الشهادات'),h('p',{class:'muted'},'صمّم نسخة قالب، عاين بيانات المشارك، ثم أصدر الشهادة. تبقى البيانات والتصميم ثابتين بعد الإصدار.'));
 host.append(h('p',{class:'notice'},'الإصدار الفردي والتحقق والإلغاء متاحة. الإرسال الآلي والاستيراد المجمع والمحافظ الرقمية لم تُفعّل بعد.'));
 const editor=h('section',{class:'card'}),name=field('اسم نسخة القالب','text','شهادة مشاركة',{maxlength:160,required:true});
 const design=structuredClone(templates.default_design);
 const title=h('h3',{},'قالب جديد');const layerRows=h('div');
 const inputs=[];
 for(const layer of design.layers){
  const content=field('النص أو المتغير','text',layer.text,{maxlength:600});
  const x=field('الموضع الأفقي X','number',layer.x,{min:0,max:design.width});
  const y=field('الموضع الرأسي Y','number',layer.y,{min:0,max:design.height});
  const size=field('حجم الخط','number',layer.size,{min:10,max:100});
  layerRows.append(h('div',{class:'grid'},content.node,x.node,y.node,size.node));inputs.push({layer,content,x,y,size});
 }
 const readDesign=()=>{for(const i of inputs)Object.assign(i.layer,{text:i.content.input.value,x:Number(i.x.input.value),y:Number(i.y.input.value),size:Number(i.size.input.value)});return design;};
 editor.append(title,name.node,h('p',{class:'muted'},'المتغيرات: {{participant_name}}، {{course_title}}، {{issuer_name}}، {{issue_date}}، {{serial}}. المواضع بالبكسل على مساحة 1120 × 792. هذه نسخة محرر مبسطة.'),layerRows,
  button('معاينة القالب',async()=>{const p=await call(base+'/certificates/preview',{design:readDesign()});modal('معاينة غير صالحة للإثبات',image(p.svg));}),
  button('حفظ نسخة القالب',async()=>{if(!name.input.reportValidity())return;await call(base+'/certificate-templates',{name:name.input.value,design:readDesign()});await renderCertificates({host,current});}));
 host.append(editor);
 const form=h('form',{class:'card'}),picker=selectField('القالب',templates.items.map(t=>[t.id,t.name]),templates.items.at(-1)?.id);
 const fields={};for(const [key,label]of [['participant_name','اسم المشارك'],['course_title','الدورة أو المنجز'],['issuer_name','الجهة المصدرة'],['grade','التقدير (اختياري)'],['training_hours','ساعات التدريب (اختياري)'],['recipient_key','معرّف المشارك الثابت'],['award_key','رمز المنجز الثابت']]){
  fields[key]=field(label,key==='training_hours'?'number':'text','',{maxlength:key==='recipient_key'?160:key==='award_key'?80:250,...(key==='training_hours'?{min:0,max:100000,step:'any'}:{}),required:!['grade','training_hours'].includes(key)});
 }
 form.addEventListener('submit',event=>event.preventDefault());
 let requestKey=crypto.randomUUID();
 const payload=()=>({template_id:picker.input.value,request_key:requestKey,recipient_key:fields.recipient_key.input.value,award_key:fields.award_key.input.value,data:Object.fromEntries(Object.entries(fields).filter(([k])=>!['recipient_key','award_key'].includes(k)).map(([k,v])=>[k,v.input.value]))});
 // Changing a request after a successful/uncertain submission requires a new key.
 form.addEventListener('input',()=>{requestKey=crypto.randomUUID();});
 const result=h('div',{'aria-live':'polite'});
 form.append(h('h3',{},'إصدار شهادة فردية'),h('p',{class:'muted'},'استخدم معرّف مشارك داخليًا ثابتًا، ورمزًا ثابتًا لكل دورة أو منجز. لا يلزم حساب أو OTP للمشارك.'),picker.node,...Object.values(fields).map(f=>f.node),
 button('معاينة بيانات المشارك',async()=>{if(!form.reportValidity())return;const t=templates.items.find(t=>t.id===picker.input.value);if(!t)return;const p=await call(base+'/certificates/preview',{design:t.design,data:payload().data});modal('راجع الاسم والمنجز قبل الإصدار',image(p.svg));}),
 button('اعتماد وإصدار شهادة ثابتة',async()=>{if(!form.reportValidity()||!picker.input.value)return;const issued=await call(base+'/certificates',payload());result.replaceChildren(h('p',{},issued.created?'أُصدرت الشهادة. احفظ رابط الاستلام الخاص أدناه.':'سبق تنفيذ الطلب؛ لم تُنشأ شهادة مكررة.'),h('code',{},issued.certificate.serial),link('التحقق العام',issued.verification_url));if(issued.access_url)result.append(link('رابط استلام المشارك',issued.access_url));toast('حُفظت الشهادة');}),result);
 if(templates.items.length)host.append(form);else host.append(h('p',{},'احفظ قالبًا لإتاحة الإصدار.'));
 const list=h('section',{class:'card'},h('h3',{},'سجل الشهادات'),h('p',{},'آخر 100 شهادة. رابط الاستلام الخاص يظهر عند إنشائه؛ استبداله يُبطل الرابط السابق.'));
 const refresh=button('تحديث السجل',()=>renderCertificates({host,current}));list.append(refresh);
 for(const cert of register.items){const row=h('article',{class:'card mini'},h('h4',{},cert.snapshot.data.participant_name),h('p',{},cert.snapshot.data.course_title+' · '+states[cert.validity]),h('code',{},cert.serial),link('التحقق','/verify/certificate/'+cert.serial));
 if(cert.validity==='valid')row.append(button('استبدال رابط الاستلام',async()=>{const r=await call(base+'/certificates/'+cert.id+'/access-link',{});modal('رابط خاص جديد — أُبطل الرابط السابق',link('فتح الشهادة',r.access_url));}),button('إلغاء الشهادة',async()=>{const reason=field('سبب الإلغاء','textarea','',{required:true,maxlength:500});const dialog=modal('إلغاء نهائي للشهادة',h('div',{},h('p',{},'يبقى رقم الشهادة في سجل التحقق بحالة ملغاة.'),reason.node,button('تأكيد الإلغاء',async()=>{if(!reason.input.reportValidity())return;await call(base+'/certificates/'+cert.id+'/revoke',{reason:reason.input.value});dialog.close();await renderCertificates({host,current});})));}));list.append(row);}
 if(!register.items.length)list.append(h('p',{},'لم تُصدر شهادات بعد.'));host.append(list);
}

export async function certificatePage(value,verify=false){
 document.title=verify?'التحقق من الشهادة — إيفنتنا':'شهادتك — إيفنتنا';
 let robots=document.querySelector('meta[name="robots"]');if(!robots){robots=document.createElement('meta');robots.name='robots';document.head.append(robots);}robots.content='noindex,nofollow';
 const row=await call('/api/public/certificates/'+(verify?'verify/':'access/')+encodeURIComponent(value));
 const main=h('main',{class:'container'},h('section',{class:'card'},h('h1',{},verify?'التحقق من الشهادة':'شهادتك'),h('p',{role:'status'},states[row.status]),h('h2',{},row.participant_name),h('p',{},row.course_title),h('p',{},row.issuer_name),h('code',{},row.serial),h('p',{},'تاريخ الإصدار: '+row.issued_at.slice(0,10))));root.replaceChildren(main);
 if(verify){main.append(h('p',{},'تؤكد هذه الصفحة السجل الحالي لدى الجهة المصدرة. طابق البيانات مع الشهادة المعروضة عليك.'));return;}
 if(row.status!=='valid'){main.append(h('p',{},'التحميل غير متاح لهذه الحالة. تواصل مع الجهة المصدرة.'));return;}
 const src='/api/public/certificates/access/'+encodeURIComponent(value)+'/image.svg';
 const img=h('img',{src,alt:'الشهادة الصادرة',style:'width:100%;height:auto'});main.append(img,h('a',{class:'btn secondary',href:src,download:row.serial+'.svg'},'تحميل النسخة المتجهية SVG'),button('تحميل صورة PNG',async()=>{
  const response=await fetch(src,{cache:'no-store'});if(!response.ok)throw new Error('تعذر تحميل الشهادة؛ حدّث حالتها.');
  const blob=await response.blob(),url=URL.createObjectURL(blob),pic=new Image();
  try{pic.src=url;await pic.decode();const canvas=document.createElement('canvas');canvas.width=pic.naturalWidth*2;canvas.height=pic.naturalHeight*2;canvas.getContext('2d').drawImage(pic,0,0,canvas.width,canvas.height);const output=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!output)throw new Error('تعذر تصدير الصورة');const png=URL.createObjectURL(output),a=h('a',{href:png,download:row.serial+'.png'});a.click();setTimeout(()=>URL.revokeObjectURL(png),1000);}finally{URL.revokeObjectURL(url);}
 }),link('التحقق العام',row.verification_url),link('مشاركة رابط التحقق على LinkedIn','https://www.linkedin.com/sharing/share-offsite/?url='+encodeURIComponent(row.verification_url)));
 main.append(h('p',{class:'muted'},'شارك رابط التحقق العام. رابط الاستلام يمنح حامله إمكانية تحميل الشهادة. تصدير PDF من الخادم وإضافة LinkedIn إلى الملف والمحافظ الرقمية غير متاحة في هذه النسخة.'));
}
