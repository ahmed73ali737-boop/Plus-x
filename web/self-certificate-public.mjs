import {root,h,button,api,field,check} from './ui.mjs';
import {P,message,footer,browserSeed} from './self-certificate-client.mjs';
const states={registered:'سُجل طلبك ويجري تجهيزه.',processing:'يجري إعداد صورة شهادتك.',failed:'تعذر تجهيز شهادتك. احتفظ بالرابط وراجع الجهة المنظمة.'};
const preparedFiles=new WeakMap();
const issuedDate=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?'غير متاح':new Intl.DateTimeFormat('ar',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(date)+' UTC';};
function shell(title){const main=h('main',{class:'selfcert-public'},h('a',{href:'/',class:'text-btn'},'Eventna إيفنتنا'),h('h1',{},title));root.replaceChildren(h('div',{class:'selfcert-page'},main,footer()));return main;}
function notice(main,text){const n=h('p',{class:'notice',role:'status'},text);main.append(n);return n;}
export async function selfCertificatePublic(kind,token){
 const main=shell(kind==='request'?'طلب شهادة مشاركة':kind==='verify'?'التحقق من الشهادة':'شهادة المشاركة');
 try{
  if(kind!=='request'){const value=await api(P+'/'+kind+'/'+encodeURIComponent(token));return showCertificate(main,value,kind==='receive');}
  let seed;
  try{seed=await browserSeed();}catch{throw new Error('BROWSER_STORAGE_REQUIRED');}
  const path=P+'/request/'+encodeURIComponent(token);
  let data;
  try{data=await api(path+'/prepare',{browser_seed:seed});}
  catch(e){if(e.message!=='BROWSER_SESSION_EXPIRED')throw e;seed=await browserSeed(true);data=await api(path+'/prepare',{browser_seed:seed});}
  await api(path+'/mine');
  main.append(h('h2',{},data.event_name),h('p',{class:'muted'},'تصدر الشهادة بناءً على إقرارك بالمشاركة. يجمع الاسم والهاتف لصاحب الخدمة لإدارة سجل الطلبات. لا تحتاج إلى إنشاء حساب.'));
  const area=h('section');main.append(area);
  let disposed=false,timer,inFlight=false,current=null,panel=null,statusNode,connectionNode,receive,refresh,rounds=0,failures=0,started=performance.now();
  function stop(){disposed=true;clearTimeout(timer);document.removeEventListener('visibilitychange',visibility);}
  function visibility(){if(!document.hidden&&!disposed&&current&&['registered','processing'].includes(current.status))queryMine();}
  document.addEventListener('visibilitychange',visibility);
  window.addEventListener('pagehide',stop,{once:true});
  function schedule(){
   clearTimeout(timer);
   if(disposed||!main.isConnected||!current||!['registered','processing'].includes(current.status))return;
   if(performance.now()-started>600000){connectionNode.textContent='تأخر التجهيز؛ يمكنك تحديث الحالة أو العودة لاحقًا لمتابعة الطلب نفسه.';return;}
   timer=setTimeout(()=>{if(document.hidden){schedule();return;}queryMine();},Math.min(10000,1500*Math.pow(1.3,rounds++)));
  }
  async function queryMine(){
   if(!main.isConnected){stop();return;}if(disposed||inFlight)return;
   clearTimeout(timer);inFlight=true;if(refresh)refresh.disabled=true;
   try{const next=await api(path+'/mine');failures=0;connectionNode.textContent='';follow(next);}
   catch{failures++;connectionNode.textContent='انقطع الاتصال. مدخلاتك وطلبك لم يتغيرا؛ حدّث الحالة عند عودة الاتصال.';if(failures<10)schedule();}
   finally{inFlight=false;if(refresh)refresh.disabled=false;}
  }
  function follow(value){
   current=value;
   if(!panel){
    statusNode=h('p',{class:'notice',role:'status'});connectionNode=h('p',{class:'muted',role:'status'});
    receive=h('a',{class:'btn',hidden:true},'عرض الشهادة وتنزيلها');
    refresh=h('button',{type:'button',class:'btn secondary',onclick:()=>{started=performance.now();rounds=0;queryMine();}},'تحديث حالة الطلب نفسه');
    panel=h('section',{class:'selfcert-follow'},statusNode,connectionNode,receive,refresh,h('p',{class:'muted'},'يمكنك العودة بهذا المتصفح خلال سنة من تهيئته. احفظ رابط الاستلام الخاص عندما تجهز الشهادة؛ مسح بيانات المتصفح قد ينهي التذكّر قبل السنة.'));
    area.replaceChildren(panel);
   }
   const issued=value.status==='issued'&&value.receive_url;
   const label=issued?'شهادتك جاهزة.':states[value.status]||'تعذر ربط هذا المتصفح بالطلب السابق. استخدم رابط الاستلام الخاص إن حفظته.';
   if(statusNode.textContent!==label)statusNode.textContent=label;
   receive.hidden=!issued;refresh.hidden=Boolean(issued);
   if(issued){receive.href=value.receive_url;clearTimeout(timer);}
   else schedule();
  }
  if(data.mine.status!=='unregistered'){follow(data.mine);return;}
  if(!data.can_request){notice(area,'هذا الرابط لا يستقبل طلبات جديدة حاليًا. يمكنك استخدام رابط الاستلام الخاص بشهادة سابقة.');return;}
  const name=field('الاسم الكامل','text','',{maxLength:250,autocomplete:'name',required:true,'aria-describedby':'selfcert-name-help selfcert-name-error'});
  const phone=field('رقم الهاتف','tel','',{maxLength:60,autocomplete:'tel',inputmode:'tel',dir:'ltr',required:true,'aria-describedby':'selfcert-phone-error'});
  const consent=check(data.consent_text,false);consent.input.required=true;
  const nameError=h('span',{class:'selfcert-field-error',id:'selfcert-name-error'});
  const phoneError=h('span',{class:'selfcert-field-error',id:'selfcert-phone-error'});
  name.node.append(h('small',{id:'selfcert-name-help'},'من كلمة إلى خمس كلمات، كما تريد ظهوره على الشهادة.'),nameError);phone.node.append(phoneError);
  const form=h('form',{class:'selfcert-form'},name.node,phone.node,consent.node);
  const error=h('p',{class:'selfcert-error',role:'alert'});
  const submit=h('button',{type:'submit',class:'btn'},'طلب الشهادة');
  form.append(error,submit,h('a',{href:'/',class:'text-btn'},'تراجع'));
  for(const input of [name.input,phone.input])input.addEventListener('input',()=>{input.removeAttribute('aria-invalid');(input===name.input?nameError:phoneError).textContent='';});
  form.addEventListener('submit',async event=>{
   event.preventDefault();submit.disabled=true;error.textContent='';nameError.textContent='';phoneError.textContent='';
   try{
    if(name.input.value.trim().split(/\s+/u).length>5)throw new Error('NAME_WORD_LIMIT');
    const result=await api(path,{name:name.input.value,phone:phone.input.value,consent:consent.input.checked,request_nonce:data.request_nonce});
    follow(result);
   }catch(e){
    error.textContent=message(e);
    if(e.message.startsWith('NAME_')||e.message==='INVALID_NAME'){nameError.textContent=message(e);name.input.setAttribute('aria-invalid','true');name.input.focus();}
    if(e.message==='PHONE_INVALID'){phoneError.textContent=message(e);phone.input.setAttribute('aria-invalid','true');phone.input.focus();}
    if(e.message==='REQUEST_NONCE_EXPIRED'){
     try{data=await api(path+'/prepare',{browser_seed:seed});error.textContent='جُددت جلسة الطلب. راجع مدخلاتك واضغط طلب الشهادة مرة أخرى.';}
     catch{error.textContent='تعذر تجديد الاتصال؛ احتفظ بمدخلاتك وحاول مجددًا.';}
    }
   }finally{submit.disabled=false;}
  });
  area.append(form,h('p',{class:'muted'},'مسح بيانات المتصفح ينهي التذكّر قبل السنة. رابط الاستلام الخاص يبقى وسيلة مستقلة للوصول؛ لا تنشره علنًا.'));
 }catch(e){notice(main,message(e));main.append(button('إعادة المحاولة',()=>location.reload(),'btn secondary'));}
}
function certificateHeader(main,value){
 const valid=value.status==='valid',title=main.querySelector('h1');
 const badge=h('span',{class:'selfcert-validity'+(valid?' is-valid':' is-invalid')},valid?'الشهادة سليمة':'تعذر التحقق من الشهادة');
 const heading=h('div',{class:'selfcert-certificate-heading'},title,badge);
 const details=h('dl',{class:'selfcert-certificate-details'},
  h('div',{},h('dt',{},'الفعالية'),h('dd',{},value.event_name)),
  h('div',{},h('dt',{},'وقت الإصدار'),h('dd',{},h('bdi',{},issuedDate(value.issued_at)))));
 const verification=h('section',{class:'selfcert-verification','aria-labelledby':'selfcert-verification-title'},
  h('h3',{id:'selfcert-verification-title'},'رمز التحقق الخاص بالشهادة'),
  h('code',{class:'selfcert-serial',dir:'ltr','aria-labelledby':'selfcert-verification-title'},value.serial),
  h('p',{class:'muted'},'يعرّف هذا الرمز الشهادة في صفحة التحقق العامة.'),
  h('a',{class:'text-btn',href:value.verification_url},'فتح صفحة التحقق'));
 main.append(h('header',{class:'selfcert-certificate-header'},heading,h('h2',{class:'selfcert-recipient'},value.name_printed),details,verification),
  h('p',{class:'notice',role:'status'},valid?'منحت هذه الشهادة بناءً على إقرار المشارك بالمشاركة.':'تعذر التحقق من سلامة الملف. راجع الجهة المنظمة.'));
}
async function showCertificate(main,value,privateView){
 certificateHeader(main,value);
 if(!privateView||value.status!=='valid')return;
 main.append(h('img',{class:'selfcert-result',src:value.image_url,alt:'معاينة شهادة '+value.name_printed}),
  h('a',{class:'btn',href:value.download_url,download:''},'تنزيل الصورة الأصلية'));
 const status=notice(main,'مشاركة الصورة اختيارية وتنشر الاسم الظاهر عليها. يُرفق النص المعتمد حيث يدعمه التطبيق ورابط التحقق العام؛ يظل رابط الاستلام خاصًا.');
 const link=value.verification_url;
 main.append(h('div',{class:'selfcert-share'},
  button('واتساب',e=>shareWeb(value,status,'واتساب',e.currentTarget)),
  button('إكس',e=>shareWeb(value,status,'إكس',e.currentTarget)),
  button('فيسبوك',()=>openShare('https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(link),status,'فُتحت مشاركة رابط التحقق. لإرفاق الصورة استخدم تنزيل الصورة أو مشاركة الجهاز؛ قد لا يقبل التطبيق النص المعتمد.')),
  button('إنستغرام',e=>shareFile(value,status,'إنستغرام',e.currentTarget)),
  button('مشاركة الصورة عبر الجهاز',e=>shareFile(value,status,'التطبيق المطلوب',e.currentTarget),'btn secondary')));
}
function openShare(url,status,label){
 // noopener may return null even after opening: never treat it as proof of posting.
 window.open(url,'_blank','noopener,noreferrer');
 status.textContent=label+' فتح نافذة المشاركة لا يؤكد النشر؛ إذا لم تفتح فاسمح بالنوافذ المنبثقة أو استخدم تنزيل الصورة.';
}
function shareWeb(value,status,target,control){
 const text=value.share_text+'\n'+value.verification_url;
 const url=target==='واتساب'?'https://wa.me/?text='+encodeURIComponent(text):
  'https://twitter.com/intent/tweet?text='+encodeURIComponent(value.share_text)+'&url='+encodeURIComponent(value.verification_url);
 // Conservative UI routing budgets, not promises about a platform's limits.
 // Route long text to the full device payload instead of silently truncating it.
 const fits=url.length<=2000&&(target!=='إكس'||Array.from(value.share_text).length<=180);
 if(!fits){
  if(navigator.share&&navigator.canShare)return shareFile(value,status,target,control);
  status.textContent='النص المعتمد أطول من مسار المشاركة المباشر هنا. يمكنك تنزيل الصورة أو مشاركة رابط التحقق عبر الخيارات المتاحة.';return;
 }
 openShare(url,status,'جُهّز النص المعتمد ورابط التحقق في مسار '+target+'. هذا المسار لا يرفق الصورة تلقائيًا؛ يمكنك تنزيلها لإرفاقها.');
}
async function shareFile(value,status,target,control){
 let prepared=preparedFiles.get(value);
 if(prepared?.busy)return;
 if(!navigator.share||!navigator.canShare){status.textContent='مشاركة الملفات غير متاحة هنا. نزّل الصورة وأرفقها في '+target+'، أو استخدم مشاركة رابط التحقق المتاحة.';return;}
 if(!prepared){prepared={file:null,busy:false};preparedFiles.set(value,prepared);}
 const controls=[...control.closest('.selfcert-share').querySelectorAll('button')];
 prepared.busy=true;controls.forEach(node=>{node.disabled=true;});
 let sharing=false;
 try{
  if(!prepared.file){
   status.textContent='جارٍ تجهيز الصورة الأصلية للمشاركة…';
   const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),35000);
   let content;
   try{
    const response=await fetch(value.download_url,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error('FINAL_FILE_UNAVAILABLE');
    content=await response.blob();
   }finally{clearTimeout(timeout);}
   const file=new File([content],'certificate-'+value.serial+'.png',{type:'image/png'});
   if(!navigator.canShare({files:[file]})){status.textContent='هذا المتصفح لا يشارك ملفات PNG. نزّل الصورة وأرفقها في التطبيق بنفسك.';return;}
   prepared.file=file;
   if(control.isConnected)control.textContent=target==='التطبيق المطلوب'?'مشاركة الصورة الجاهزة عبر الجهاز':'مشاركة الصورة إلى '+target;
   status.textContent='الصورة جاهزة. اضغط زر المشاركة مرة أخرى لاختيار '+target+' من قائمة الجهاز إن ظهر.';
   return;
  }
  const full={files:[prepared.file],text:value.share_text+'\n'+value.verification_url};
  const withText=navigator.canShare(full),payload=withText?full:{files:[prepared.file]};
  // No await/fetch before share: preserve the fresh click's transient activation.
  sharing=true;
  const operation=navigator.share(payload);
  status.textContent=withText?'اختر '+target+' من قائمة الجهاز إذا ظهر. قبول الصورة والنص معًا يعتمد على التطبيق.':
   'هذا المتصفح يقبل الصورة فقط في المشاركة؛ لا يمكن تمرير النص المعتمد بهذا المسار.';
  await operation;
  status.textContent='أغلقت واجهة المشاركة. لا يؤكد النظام نشر الصورة.'+(withText?'':' طلب المشاركة احتوى الصورة وحدها دون النص.');
 }catch(e){status.textContent=e.name==='AbortError'?(sharing?'أُلغيت المشاركة؛ شهادتك لم تتغير.':'انتهت مهلة تجهيز الصورة. تحقق من الاتصال وأعد المحاولة أو نزّل الصورة.'):message(e);}
 finally{prepared.busy=false;controls.forEach(node=>{node.disabled=false;});}
}
