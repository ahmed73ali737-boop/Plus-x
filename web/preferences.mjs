import {h,api,button,selectField,check,modal,setCSRF} from './ui.mjs';
const defaults={theme:'system',text_size:'normal',reduce_motion:false,notifications_enabled:true};
let config={...defaults};
try{config={...defaults,...JSON.parse(localStorage.getItem('eventna-preferences')||'{}')};}catch{}
const media=matchMedia('(prefers-color-scheme: dark)');
function apply(){
  document.documentElement.dataset.appearance=config.theme==='system'?(media.matches?'dark':'light'):config.theme;
  document.documentElement.dataset.textSize=config.text_size;
  document.documentElement.dataset.reduceMotion=String(config.reduce_motion);
}
media.addEventListener('change',apply);apply();
function persist(){try{localStorage.setItem('eventna-preferences',JSON.stringify(config));}catch{}apply();}
export async function preferencePanel(host,{authenticated=false,user=null}={}){
  const state=h('p',{role:'status','aria-live':'polite'});
  if(authenticated){try{config=await api('/api/account/preferences');persist();}catch{state.textContent='تعذر تحميل إعدادات الحساب. أعد المحاولة عند عودة الاتصال.';}}
  const theme=selectField('المظهر',[['system','حسب الجهاز'],['light','فاتح'],['dark','داكن']],config.theme);
  const size=selectField('حجم النص',[['normal','عادي'],['large','كبير']],config.text_size);
  const motion=check('تقليل الحركة والمؤثرات',config.reduce_motion);
  const enabled=check('إظهار تنبيهات الرسائل الجديدة',config.notifications_enabled);
  const save=button('حفظ الإعدادات',async()=>{
    const next={theme:theme.input.value,text_size:size.input.value,reduce_motion:motion.input.checked,notifications_enabled:enabled.input.checked};
    if(authenticated)await api('/api/account/preferences',next,'PUT');
    config=next;persist();state.textContent=authenticated?'حُفظت إعدادات حسابك.':'حُفظت الإعدادات على هذا الجهاز.';
  });
  host.append(h('section',{class:'card preference-card'},h('h2',{},'على راحتك'),h('p',{class:'muted'},'اختر المظهر وحجم النص المناسبين لك.'),theme.node,size.node,motion.node,enabled.node,save,state));
  if(!authenticated){host.append(h('p',{},'إعدادات الضيف محفوظة على هذا الجهاز. سجّل الدخول لحفظ إعداداتك في حسابك.'),h('a',{href:'/admin',class:'text-btn'},'الدخول إلى حسابي'));return;}
  const inbox=h('section',{class:'card preference-card','aria-label':'صندوق الإشعارات'});host.append(inbox);
  async function refresh(){
    const result=await api('/api/account/notifications');
    inbox.replaceChildren(h('h2',{},'صندوق الإشعارات'),h('p',{class:'muted'},'رسائل من إدارة المنصة. تصل إلى هذا الصندوق؛ لا تتضمن SMS أو إشعارات الهاتف أثناء إغلاق التطبيق.'),button('تحديث الرسائل',refresh,'btn secondary'));
    if(!result.items.length)inbox.append(h('p',{class:'empty'},'ليس لديك رسائل حتى الآن.'));
    for(const item of result.items){
      const article=h('article',{class:'inbox-message'+(item.read_at?'':' unread')},h('h3',{},item.title),h('p',{class:'inbox-body'},item.body),h('small',{class:'muted'},new Date(item.created_at).toLocaleString('ar-YE')));
      if(!item.read_at)article.append(button('تحديد كمقروء',async()=>{await api('/api/account/notifications/'+encodeURIComponent(item.id)+'/read',{});await refresh();},'text-btn'));
      inbox.append(article);
    }
  }
  try{await refresh();}catch{inbox.append(h('p',{role:'alert'},'تعذر تحميل الرسائل. تحقق من الاتصال.'),button('إعادة المحاولة',refresh));}
  if(user?.role==='platform'){
    const email=h('input',{type:'email',required:true,maxlength:200,autocomplete:'off'}),title=h('input',{required:true,maxlength:160}),body=h('textarea',{required:true,maxlength:2000,rows:4});
    const output=h('p',{role:'status','aria-live':'polite'}),send=h('button',{type:'submit',class:'btn'},'إرسال إلى صندوق الحساب');
    const form=h('form',{class:'card preference-card'},h('h2',{},'رسالة من الإدارة'),h('label',{class:'field'},'بريد المستلم',email),h('label',{class:'field'},'العنوان',title),h('label',{class:'field'},'الرسالة',body),send,output);
    let sending=false;
    form.addEventListener('submit',async e=>{e.preventDefault();if(sending||!form.reportValidity())return;sending=true;send.disabled=true;try{await api('/api/admin/notifications',{email:email.value.trim(),title:title.value.trim(),body:body.value.trim()});output.textContent='وصلت الرسالة إلى صندوق الحساب.';form.reset();try{await refresh();}catch{output.textContent='وصلت الرسالة إلى صندوق الحساب. تعذر تحديث العرض؛ استخدم تحديث الرسائل.';}}catch{output.textContent='تعذر الإرسال. تحقق من بريد الحساب والاتصال.';}finally{sending=false;send.disabled=false;}});
    host.append(form);
  }
}
export function installPreferences(){
  const launcher=button('المظهر والإشعارات',async()=>{
    const host=h('div',{});const dialog=modal('إعدادات التطبيق',host);
    dialog.querySelector('header button')?.setAttribute('aria-label','إغلاق الإعدادات');
    let user=null;
    try{const me=await api('/api/auth/me');if(!me.user.must_change_password){user=me.user;setCSRF(me.csrf);}}catch{}
    if(dialog.isConnected)await preferencePanel(host,{authenticated:!!user,user});
  },'btn secondary preferences-launcher');
  document.body.append(launcher);
  let owner=null;
  async function refreshBadge(){
    if(document.hidden)return;
    try{
      if(!owner){const me=await api('/api/auth/me');if(me.user.must_change_password)return;owner=me.user.id;config=await api('/api/account/preferences');persist();}
      if(!config.notifications_enabled){launcher.textContent='المظهر والإشعارات';launcher.setAttribute('aria-label','المظهر والإشعارات');return;}
      const result=await api('/api/account/notifications');
      const unread=result.items.filter(item=>!item.read_at).length;
      launcher.textContent=unread?'الإشعارات ('+unread+') · الإعدادات':'المظهر والإشعارات';
      launcher.setAttribute('aria-label',unread?'لديك '+unread+' رسالة غير مقروءة. افتح الإعدادات':'المظهر والإشعارات');
    }catch{owner=null;launcher.textContent='المظهر والإشعارات';launcher.setAttribute('aria-label','المظهر والإشعارات');}
  }
  refreshBadge();
  setInterval(refreshBadge,45000);
  document.addEventListener('visibilitychange',refreshBadge);
}
