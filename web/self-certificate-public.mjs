import {root,h,button,api,field,check} from './ui.mjs';
import {P,message,footer,browserSeed,copy} from './self-certificate-client.mjs';
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
async function showCertificate(main,value,privateView){
 main.append(h('h2',{},value.name_printed),h('p',{},value.event_name),h('p',{dir:'ltr'},value.serial),
  h('p',{},'وقت الإصدار: ',h('bdi',{},issuedDate(value.issued_at))),h('p',{class:'notice'},value.status==='valid'?'الشهادة سليمة، ومنحت بناءً على إقرار المشارك.':'تعذر التحقق من سلامة الملف. راجع الجهة المنظمة.'));
 if(!privateView||value.status!=='valid')return;
 main.append(h('img',{class:'selfcert-result',src:value.image_url,alt:'معاينة شهادة '+value.name_printed}),
  h('a',{class:'btn',href:value.download_url,download:''},'تنزيل الصورة الأصلية'),
  h('a',{class:'text-btn',href:value.verification_url},'صفحة التحقق العامة'));
 const text=field('نص المشاركة','textarea',value.share_text,{readOnly:true});main.append(text.node,button('نسخ نص المشاركة',()=>copy(value.share_text),'btn secondary'));
 const status=notice(main,'مشاركة الصورة اختيارية وتنشر الاسم الظاهر عليها. يُشارك رابط التحقق فقط، ويظل رابط الاستلام خاصًا.');
 const safeText=limitText(value.share_text,650),link=value.verification_url,open=url=>window.open(url,'_blank','noopener,noreferrer');
 const instagram=button('إنستغرام',e=>shareFile(value,status,'إنستغرام',e.currentTarget));
 const device=button('مشاركة الصورة عبر الجهاز',e=>shareFile(value,status,'التطبيق المطلوب',e.currentTarget),'btn secondary');
 main.append(h('div',{class:'selfcert-share'},
  button('واتساب',()=>{open('https://wa.me/?text='+encodeURIComponent(safeText+'\n'+link));status.textContent='فُتح محرر النص والرابط. لإرفاق الصورة نزّلها ثم أرفقها بنفسك؛ لم يتم إثبات نشر.';}),
  button('إكس',()=>{open('https://twitter.com/intent/tweet?text='+encodeURIComponent(limitText(value.share_text,180))+'&url='+encodeURIComponent(link));status.textContent='راجع النص وأرفق الصورة المنزلة إذا أردت. فتح المحرر لا يعني النشر.';}),
  button('فيسبوك',()=>{open('https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(link));status.textContent='يمكنك مشاركة رابط التحقق؛ لا يمكن فرض النص داخل فيسبوك. انسخ النص ونزّل الصورة للإرفاق اليدوي.';}),
  instagram,device));
}
function limitText(text,count){const segments=typeof Intl.Segmenter==='function'?[...new Intl.Segmenter('ar',{granularity:'grapheme'}).segment(text)].map(x=>x.segment):Array.from(text);return segments.slice(0,count).join('')+(segments.length>count?'…':'');}
async function shareFile(value,status,target,control){
 try{
  if(!navigator.share||!navigator.canShare){status.textContent='المشاركة بالملفات غير متاحة هنا. نزّل الصورة وانسخ النص ثم أرفقهما في '+target+' بنفسك.';return;}
  let prepared=preparedFiles.get(value);
  if(!prepared){
   status.textContent='جارٍ تجهيز الصورة الأصلية للمشاركة…';
   const response=await fetch(value.download_url,{credentials:'same-origin',cache:'no-store'});
   if(!response.ok)throw new Error('FINAL_FILE_UNAVAILABLE');
   const file=new File([await response.blob()],'certificate-'+value.serial+'.png',{type:'image/png'});
   if(!navigator.canShare({files:[file]})){status.textContent='هذا المتصفح لا يشارك ملفات PNG. نزّل الصورة وأرفقها في التطبيق بنفسك.';return;}
   prepared={file};preparedFiles.set(value,prepared);
   if(control.isConnected)control.textContent=target==='إنستغرام'?'مشاركة الصورة إلى إنستغرام':'مشاركة الصورة الجاهزة عبر الجهاز';
   status.textContent='الصورة جاهزة. اضغط زر المشاركة مرة أخرى لاختيار '+target+' من قائمة الجهاز إن ظهر.';
   return;
  }
  // No asynchronous fetch occurs before this call: preserve this click's
  // transient user activation on browsers that require it.
  const operation=navigator.share({files:[prepared.file],text:value.share_text+'\n'+value.verification_url});
  status.textContent='اختر '+target+' من قائمة الجهاز إذا ظهر. قبول الصورة والنص معًا يعتمد على التطبيق.';
  await operation;
  status.textContent='أغلقت واجهة المشاركة. لا يؤكد النظام نشر الصورة.';
 }catch(e){status.textContent=e.name==='AbortError'?'أُلغيت المشاركة؛ شهادتك لم تتغير.':message(e);}
}
