import {api,h,field,button,modal} from './ui.mjs';

export function passwordPair(){
  const password=field('كلمة المرور الجديدة — 12 إلى 256 حرفًا','password','',{required:true,minlength:12,maxlength:256,autocomplete:'new-password',dir:'ltr'});
  const confirmation=field('تأكيد كلمة المرور الجديدة','password','',{required:true,minlength:12,maxlength:256,autocomplete:'new-password',dir:'ltr'});
  const reveal=button('إظهار / إخفاء كلمة المرور',()=>{const type=password.input.type==='password'?'text':'password';password.input.type=type;confirmation.input.type=type;},'text-btn');
  return {password,confirmation,node:h('div',{},password.node,confirmation.node,reveal)};
}

export function validatePasswords(pair,current){
  if(pair.password.input.value!==pair.confirmation.input.value)throw new Error('PASSWORD_CONFIRMATION_MISMATCH');
  if(current!==undefined&&pair.password.input.value===current)throw new Error('PASSWORD_MUST_DIFFER');
}

export function openRecovery(){
  modal('نسيت كلمة المرور',h('div',{},h('p',{class:'notice'},'راجع مسؤول المنصة أو جهتك لاستعادة الحساب. سيصدر المسؤول كلمة مرور مؤقتة، وتغيّرها عند أول دخول.'),h('p',{class:'muted'},'لا ترسل كلمة مرورك الحالية لأي شخص. إدخال رقم الهاتف وحده لا يغيّر كلمة المرور.'),h('a',{href:'/',class:'btn secondary'},'بيانات التواصل في الموقع')));
}

export async function resetManagedPassword(userId){
  if(!confirm('سيتم إنهاء جلسات هذا الحساب وإصدار كلمة مرور مؤقتة جديدة. هل تريد المتابعة؟'))return;
  const result=await api('/api/admin/users/'+encodeURIComponent(userId)+'/password/reset',{});
  const secret=field('كلمة المرور المؤقتة','text',result.temporary_password,{readonly:true,dir:'ltr',autocomplete:'off'});
  modal('استعادة الحساب من الإدارة',h('div',{},h('p',{class:'notice'},'تظهر الكلمة مرة واحدة هنا. سلّمها لصاحب الحساب عبر قناة آمنة؛ يجب تغييرها عند أول دخول.'),secret.node));
}
