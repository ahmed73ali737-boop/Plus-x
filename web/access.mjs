import {h,root,api,field,selectField,check,brand,msg} from './ui.mjs';

function style(){if(!document.querySelector('link[data-access-style]'))document.head.append(h('link',{rel:'stylesheet',href:'/assets/access.css','data-access-style':'true'}));}
export async function accessPage(){
  style();document.documentElement.dir='rtl';document.documentElement.lang='ar';document.title='ابدأ تجربتك | Eventna إيفنتنا';
  root.replaceChildren();
  const main=h('main',{class:'access-shell',id:'main-content'});
  root.append(h('a',{class:'skip-link',href:'#main-content'},'انتقل إلى المحتوى'),h('header',{class:'access-header'},brand(),h('a',{href:'/',class:'text-btn'},'استكشف الفعاليات')),main);
  const hero=h('section',{class:'access-hero'},h('span',{class:'access-kicker'},'EVENTNA · LIVE EXPERIENCES'),h('h1',{},'تجربتك تبدأ\nمن هنا.'),h('p',{},'استكشف وشارك كضيف، أو ادخل إلى مساحة جهتك لإدارة الفعاليات والمحتوى.'),h('div',{class:'access-hero-actions'},h('a',{href:'/',class:'btn'},'الاستمرار كضيف'),h('a',{href:'/admin',class:'btn secondary'},'تسجيل الدخول')));
  const choices=h('section',{class:'access-choices','aria-label':'اختر طريقة الاستخدام'},
    h('article',{class:'access-choice'},h('span',{class:'access-number'},'01'),h('h2',{},'أنا زائر'),h('p',{},'تصفح الفعاليات وشارك في الاستبيانات والتصويت دون إنشاء حساب. بطاقة الحضور تخضع لسياسة كل فعالية.'),h('a',{href:'/',class:'text-btn'},'تصفح كضيف ←')),
    h('article',{class:'access-choice'},h('span',{class:'access-number'},'02'),h('h2',{},'لدي حساب'),h('p',{},'ادخل برقم الهاتف وكلمة المرور. الأدوات المتاحة لك يحددها دورك وصلاحياتك.'),h('a',{href:'/admin',class:'text-btn'},'الدخول إلى مساحتي ←')),
    h('article',{class:'access-choice'},h('span',{class:'access-number'},'03'),h('h2',{},'أريد إنشاء مساحة'),h('p',{},'قدّم طلب حساب لجهة منظمة أو مشاركة. إنشاء الفعالية أو الصفحة يتم بعد اعتماد الحساب وبحسب صلاحياته.'),h('a',{href:'/account/signup',class:'text-btn'},'إنشاء حساب برقم الهاتف ←'),h('a',{href:'#account',class:'text-btn'},'طلب صلاحيات جهة ←')));
  const downloadState=h('div',{role:'status','aria-live':'polite'},h('h3',{},'تنزيل Android متوقف مؤقتًا'),h('p',{class:'notice'},'أُوقف توزيع حزمة المعاينة بعد بلاغ تحذير أمني على الهاتف، حتى اكتمال التحقيق والمراجعة. لا تتجاوز تحذير الحماية.'),h('a',{href:'/',class:'btn secondary'},'استخدم نسخة الويب'),h('p',{class:'muted small'},'يمكنك فتح الموقع في المتصفح واختيار إضافة إلى الشاشة الرئيسية إن كان الخيار متاحًا.'));
  const downloads=h('section',{class:'access-download',id:'download'},h('div',{},h('span',{class:'access-kicker'},'خذ التجربة معك'),h('h2',{},'Eventna إيفنتنا على Android'),h('p',{},'تتوفر الفعاليات وبطاقة الزائر من المتصفح أثناء مراجعة حزمة Android.')),downloadState);
  const formHost=h('section',{class:'access-account',id:'account'},h('span',{class:'access-kicker'},'مساحتك القادمة'),h('h2',{},'إنشاء طلب حساب جهة'),h('p',{},'هذا طلب مراجعة؛ لا ينشئ حسابًا نشطًا ولا يمنح صلاحية إدارة فورًا. الزائر يستطيع المشاركة كضيف دون هذا الطلب.'));
  main.append(hero,choices,downloads,formHost);
  const role=selectField('نوع الحساب',[['organizer','جهة منظمة لفعالية'],['participant','جهة مشاركة في فعالية']],'organizer');
  const event=selectField('الفعالية المطلوبة',[['','اختر فعالية عامة']],'');event.node.hidden=true;
  const org=field('اسم الجهة أو المؤسسة','text','',{required:true,maxlength:200,autocomplete:'organization'}),name=field('اسم المسؤول','text','',{required:true,maxlength:160,autocomplete:'name'}),phone=field('رقم الهاتف','tel','',{required:true,maxlength:40,autocomplete:'tel',inputmode:'tel',dir:'ltr',placeholder:'777123456 أو +967777123456'});
  const consent=check('أوافق على إرسال هذه البيانات للمنظم لمراجعة طلب الحساب.',false);
  const output=h('p',{role:'status','aria-live':'polite'}),submit=h('button',{type:'submit',class:'btn'},'إرسال طلب المراجعة');
  const form=h('form',{class:'access-form'},h('div',{class:'access-form-grid'},role.node,event.node,org.node,name.node,phone.node),consent.node,output,submit);
  let events=[],loadingEvents=null;
  async function eventOptions(){
    if(loadingEvents)return loadingEvents;
    loadingEvents=(async()=>{try{const platform=await api('/api/public/site/platform');events=platform.events||[];for(const row of events)event.input.append(h('option',{value:row.id},row.title||row.slug));}catch{output.textContent='تعذر تحميل الفعاليات. أعد فتح الصفحة عند عودة الاتصال لإرسال طلب مشاركة.';}})();
    return loadingEvents;
  }
  role.input.addEventListener('change',async()=>{event.node.hidden=role.input.value!=='participant';event.input.required=role.input.value==='participant';if(event.input.required)await eventOptions();});
  let sending=false;
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(sending)return;
    if(!form.reportValidity())return;
    if(!consent.input.checked){output.textContent='يلزم الموافقة على إرسال البيانات قبل تقديم الطلب.';return;}
    const participant=role.input.value==='participant';
    if(participant&&!events.some(row=>row.id===event.input.value)){output.textContent='اختر فعالية متاحة قبل إرسال طلب المشاركة.';return;}
    sending=true;submit.disabled=true;output.textContent='جارٍ إرسال الطلب…';
    try{
      const payload={site_id:participant?event.input.value:'platform',requested_role:role.input.value,organization_name:org.input.value.trim(),contact_name:name.input.value.trim(),phone:phone.input.value.trim(),participation_type:'exhibitor',wants_account:true};
      const result=await api('/api/signup-request',payload);
      if(result.status!=='pending'||result.grants_access!==false)throw new Error('UNEXPECTED_SIGNUP_RESPONSE');
      form.replaceChildren(h('div',{class:'notice',role:'status'},h('h3',{},'تم استلام طلبك للمراجعة'),h('p',{},'لم يُفعّل حساب أو تُمنح صلاحيات بعد. راجع الجهة المنظمة لمتابعة الاعتماد؛ لا توجد رسالة بريد أو SMS آلية موعودة.'),h('a',{href:'/',class:'btn secondary'},'تصفح كضيف أثناء الانتظار')));
    }catch(error){output.textContent=msg(error)+' — لم يكتمل إرسال الطلب. راجع البيانات والاتصال قبل المحاولة مجددًا.';}
    finally{sending=false;submit.disabled=false;}
  });
  formHost.append(form);

}
