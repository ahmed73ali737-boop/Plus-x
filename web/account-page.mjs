import {newRequestKey,api,brand,button,field,h,msg,root,setCSRF} from './ui.mjs';
import {openRecovery,passwordPair,validatePasswords} from './account.mjs';

export async function accountPage(){
  document.documentElement.dir='rtl';document.documentElement.lang='ar';
  document.title='حسابي | Eventna إيفنتنا';
  if(!document.querySelector('link[data-access-style]'))document.head.append(h('link',{rel:'stylesheet',href:'/assets/access.css','data-access-style':'true'}));
  const main=h('main',{class:'access-shell account-shell',id:'main-content'});
  root.replaceChildren(h('header',{class:'access-header'},brand(),h('a',{href:'/',class:'text-btn'},'تصفح الفعاليات')),main);
  if(location.pathname==='/account/invite')return platformInvitePage(main);
  if(location.pathname==='/account/request')return requestPage(main);
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
  const status=h('p',{role:'status','aria-live':'polite'}),submit=h('button',{type:'submit',class:'btn'},'إرسال طلب حسابي');
  const form=h('form',{class:'access-form'},h('span',{class:'eyebrow'},'حسابك في إيفنتنا'),h('h1',{},'ابدأ برقم هاتفك'),h('p',{class:'muted'},'الاسم ورقم الهاتف وكلمة المرور فقط. يراجع المشرف الطلب أولًا. لا حساب ولا دخول قبل الموافقة، ولا تحقق OTP.'),name.node,phone.node,pair.node,status,submit,h('div',{class:'actions'},h('a',{href:'/admin',class:'text-btn'},'لدي حساب · تسجيل الدخول'),h('a',{href:'/',class:'text-btn'},'الاستمرار كضيف')));
  let busy=false,requestKey=newRequestKey();
  form.addEventListener('input',()=>{requestKey=newRequestKey();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;
    busy=true;submit.disabled=true;status.textContent='جارٍ إرسال الطلب…';
    try{
      validatePasswords(pair);
      const state=await api('/api/auth/register',{request_key:requestKey,name:name.input.value.trim(),phone:phone.input.value,password:pair.password.input.value,confirmation:pair.confirmation.input.value});
      pair.password.input.value='';pair.confirmation.input.value='';location.href='/account/request#'+encodeURIComponent(state.tracking_token);
    }catch(error){status.textContent=msg(error);}
    finally{busy=false;submit.disabled=false;}
  });
  main.append(form);name.input.focus();
}

function profile(main,user){
  main.append(h('section',{class:'access-hero'},h('span',{class:'access-kicker'},'مرحبًا بك'),h('h1',{},user.name),h('p',{dir:'ltr'},user.phone||user.email||''),h('div',{class:'access-hero-actions'},h('a',{href:'/',class:'btn'},'استكشف الفعاليات'),user.management_access?h('a',{href:'/admin',class:'btn secondary'},'مساحة الإدارة'):h('a',{href:'/start#account',class:'btn secondary'},'طلب مساحة لجهتي'),button('تسجيل الخروج',async()=>{await api('/api/auth/logout',{});setCSRF('');location.href='/admin';},'text-btn'))));
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

async function requestPage(main){
  const token=decodeURIComponent(location.hash.slice(1)),status=h('p',{role:'status','aria-live':'polite'}),box=h('section',{class:'access-form'});
  main.append(h('h1',{},'متابعة طلب الحساب'),h('p',{class:'muted'},'احتفظ بهذا الرابط بسرية لتتابع القرار وتعيّن كلمة المرور بعد الموافقة. لا توجد رسالة بريد أو SMS آلية.'),status,box,button('تحديث الحالة',draw,'btn secondary'));
  async function draw(){try{
    const r=await api('/api/account-requests/status',{tracking_token:token});box.replaceChildren();status.textContent=({pending:'بانتظار الموافقة',approved:'تم اعتماد الطلب',rejected:'رُفض الطلب',expired:'انتهت صلاحية الطلب',cancelled:'أُلغي الطلب'})[r.status]||r.status;
    box.append(h('p',{},r.name+' · '+(r.phone||r.email||'')),h('code',{},r.id),h('p',{},'المشرف: '+r.supervisor_name),h('p',{},'النطاق: '+(r.scope_name||r.scope_id)+(r.organization_name?' · '+r.organization_name:'')));
    if(r.decision_reason)box.append(h('p',{},r.decision_reason));
    if(r.status==='pending')box.append(h('p',{},'لا يمكن الدخول أو إدارة النطاق قبل الموافقة.'),button('إلغاء طلبي',async()=>{await api('/api/account-requests/cancel',{tracking_token:token});await draw();},'text-btn'));
    if(r.setup_required&&r.setup_expired)box.append(h('p',{},'انتهت صلاحية تعيين كلمة المرور. راجع المشرف لتجديدها؛ لا يمكن تسجيل الدخول بعد.'));
    else if(r.setup_required){
      const pair=passwordPair(),feedback=h('p',{role:'status'}),submit=h('button',{type:'submit',class:'btn'},'تعيين كلمة المرور'),form=h('form',{},h('p',{},'رابط التعيين صالح حتى '+new Date(r.setup_expires_at).toLocaleString('ar-YE')+' ويستخدم مرة واحدة.'),pair.node,feedback,submit);let busy=false;
      form.addEventListener('submit',async e=>{e.preventDefault();if(busy||!form.reportValidity())return;busy=true;submit.disabled=true;try{validatePasswords(pair);await api('/api/account-requests/password',{tracking_token:token,password:pair.password.input.value,confirmation:pair.confirmation.input.value});pair.password.input.value='';pair.confirmation.input.value='';await draw();}catch(err){feedback.textContent=msg(err);}finally{busy=false;submit.disabled=false;}});box.append(form);
    }else if(r.status==='approved'&&!r.account_requested)box.append(h('p',{},'تم اعتماد ملف الجهة دون إنشاء حساب دخول.'));
    else if(r.status==='approved')box.append(h('a',{href:'/admin',class:'btn'},'تسجيل الدخول'));
    else if(r.status!=='pending')box.append(h('a',{href:'/start#account',class:'btn secondary'},'تقديم طلب جديد'));
  }catch(e){status.textContent=msg(e);}}
  await draw();
}

async function platformInvitePage(main){
  const token=decodeURIComponent(location.hash.slice(1)),status=h('p',{role:'status','aria-live':'polite'});
  main.append(h('h1',{},'طلب حساب مدير منصة مدعو'),status);
  try{
    const invite=await api('/api/account-invites/inspect',{invitation_token:token});
    const pair=passwordPair(),submit=h('button',{type:'submit',class:'btn'},'تقديم طلبي للمشرف'),form=h('form',{class:'access-form'},h('p',{},invite.name+' · '+(invite.phone||invite.email||'')),h('p',{},'البيانات مرتبطة بالدعوة. اختر كلمة مرورك، ثم انتظر الموافقة. لن تظهر كلمة المرور للمشرف.'),pair.node,submit);let busy=false;
    if(invite.submitted){location.href='/account/request#'+encodeURIComponent(token);return;}
    form.addEventListener('submit',async e=>{e.preventDefault();if(busy||!form.reportValidity())return;busy=true;submit.disabled=true;try{validatePasswords(pair);const r=await api('/api/account-invites/accept',{invitation_token:token,password:pair.password.input.value,confirmation:pair.confirmation.input.value});pair.password.input.value='';pair.confirmation.input.value='';location.href='/account/request#'+encodeURIComponent(r.tracking_token);}catch(error){status.textContent=msg(error);}finally{busy=false;submit.disabled=false;}});main.append(form);
  }catch(e){status.textContent=msg(e);}
}
