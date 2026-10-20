import {api,brand,button,field,h,msg,root,setCSRF} from './ui.mjs';
import {openRecovery,passwordPair,validatePasswords} from './account.mjs';

export async function accountPage(){
  document.documentElement.dir='rtl';document.documentElement.lang='ar';
  document.title='حسابي | Eventna إيفنتنا';
  if(!document.querySelector('link[data-access-style]'))document.head.append(h('link',{rel:'stylesheet',href:'/assets/access.css','data-access-style':'true'}));
  const main=h('main',{class:'access-shell account-shell',id:'main-content'});
  root.replaceChildren(h('header',{class:'access-header'},brand(),h('a',{href:'/',class:'text-btn'},'تصفح الفعاليات')),main);
  if(location.pathname==='/account/signup')return signup(main);
  if(location.pathname==='/account/login'){location.replace('/admin');return;}
  try{
    const state=await api('/api/auth/me');setCSRF(state.csrf);
    if(state.user.must_change_password){location.replace('/admin');return;}
    return profile(main,state.user);
  }catch(error){
    if(error.status===401){location.replace('/admin');return;}
    main.append(h('p',{role:'alert',class:'notice'},msg(error)),button('إعادة المحاولة',()=>location.reload()));
  }
}

function signup(main){
  const name=field('الاسم','text','',{required:true,maxlength:160,autocomplete:'name'});
  const phone=field('رقم الهاتف','tel','',{required:true,maxlength:40,autocomplete:'tel',inputmode:'tel',dir:'ltr',placeholder:'777123456 أو +967777123456'}),pair=passwordPair();
  const status=h('p',{role:'status','aria-live':'polite'}),submit=h('button',{type:'submit',class:'btn'},'إنشاء حسابي');
  const form=h('form',{class:'access-form'},h('span',{class:'eyebrow'},'حسابك في إيفنتنا'),h('h1',{},'ابدأ برقم هاتفك'),h('p',{class:'muted'},'الاسم ورقم الهاتف وكلمة المرور فقط. بعد الإنشاء تفتح صفحة حسابك مباشرة.'),name.node,phone.node,pair.node,status,submit,h('div',{class:'actions'},h('a',{href:'/admin',class:'text-btn'},'لدي حساب · تسجيل الدخول'),h('a',{href:'/',class:'text-btn'},'الاستمرار كضيف')));
  let busy=false;
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;
    busy=true;submit.disabled=true;status.textContent='جارٍ إنشاء الحساب…';
    try{
      validatePasswords(pair);
      const state=await api('/api/auth/register',{name:name.input.value.trim(),phone:phone.input.value,password:pair.password.input.value,confirmation:pair.confirmation.input.value});
      setCSRF(state.csrf);pair.password.input.value='';pair.confirmation.input.value='';location.href='/account';
    }catch(error){status.textContent=msg(error);}
    finally{busy=false;submit.disabled=false;}
  });
  main.append(form);name.input.focus();
}

function profile(main,user){
  main.append(h('section',{class:'access-hero'},h('span',{class:'access-kicker'},'مرحبًا بك'),h('h1',{},user.name),h('p',{dir:'ltr'},user.phone||user.email||''),h('div',{class:'access-hero-actions'},h('a',{href:'/',class:'btn'},'استكشف الفعاليات'),user.role!=='attendee'?h('a',{href:'/admin',class:'btn secondary'},'مساحة الإدارة'):h('a',{href:'/start#account',class:'btn secondary'},'طلب مساحة لجهتي'),button('تسجيل الخروج',async()=>{await api('/api/auth/logout',{});setCSRF('');location.href='/admin';},'text-btn'))));
  const current=field('كلمة المرور الحالية','password','',{required:true,autocomplete:'current-password',maxlength:256}),pair=passwordPair(),status=h('p',{role:'status','aria-live':'polite'}),submit=h('button',{type:'submit',class:'btn'},'حفظ كلمة المرور');
  const form=h('form',{class:'access-form'},h('h2',{},'أمان حسابي'),h('p',{class:'muted'},'تغيير كلمة المرور ينهي الجلسات على جميع الأجهزة. بعدها تدخل بالكلمة الجديدة.'),current.node,pair.node,status,submit,button('نسيت كلمة المرور',openRecovery,'text-btn'));
  let busy=false;
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;busy=true;submit.disabled=true;
    try{validatePasswords(pair,current.input.value);await api('/api/auth/password',{current:current.input.value,password:pair.password.input.value,confirmation:pair.confirmation.input.value});setCSRF('');location.href='/admin';}
    catch(error){status.textContent=msg(error);}finally{busy=false;submit.disabled=false;}
  });
  main.append(form);
  if(!user.phone){
    const phone=field('رقم الهاتف للدخول','tel','',{required:true,inputmode:'tel',autocomplete:'tel',dir:'ltr'}),password=field('كلمة مرور الحساب الحالية','password','',{required:true,autocomplete:'current-password'}),output=h('p',{role:'status','aria-live':'polite'});
    const link=h('form',{class:'access-form'},h('h2',{},'الدخول برقم الهاتف'),h('p',{class:'muted'},'أضف رقمك لحسابك الحالي. يبقى حسابك وصلاحياتك كما هما، ويُطلب الدخول من جديد.'),phone.node,password.node,output,h('button',{type:'submit',class:'btn'},'ربط الهاتف بحسابي'));
    let linking=false;
    link.addEventListener('submit',async event=>{event.preventDefault();if(linking||!link.reportValidity())return;linking=true;const submit=link.querySelector('button[type=submit]');submit.disabled=true;try{await api('/api/auth/phone',{phone:phone.input.value,current:password.input.value});setCSRF('');location.href='/admin';}catch(error){output.textContent=msg(error);}finally{linking=false;submit.disabled=false;}});
    main.append(link);
  }
}
