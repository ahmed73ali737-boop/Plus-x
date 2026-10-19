import {h,api,field,button,toast} from './ui.mjs';
import {attendanceDashboard} from './admission-live.mjs';
import {renderReception} from './invitations.mjs';

export async function admissionDesk({host,current,user}){
  const permissions=current.permissions||[];
  if(permissions.includes('guests.register'))await renderReception({host,current,user});
  const [data,summary]=await Promise.all([api('/api/admin/events/'+current.id+'/guests'),api('/api/admin/events/'+current.id+'/guest-checkins')]);
  const live=attendanceDashboard(host,current.id,summary);
  const search=field('بحث بالاسم أو رقم التذكرة','search'),list=h('div',{class:'guest-admin-grid'});
  function draw(){const q=search.input.value.trim().toLowerCase();list.replaceChildren(...data.guests.filter(g=>!q||[g.name,g.guest_number].some(x=>String(x||'').toLowerCase().includes(q))).map(g=>{
    const card=h('article',{class:'card mini'},h('h3',{},g.name||'زائر'),h('code',{},g.guest_number),h('p',{},({visitor:'زائر',vip:'كبار الزوار',staff:'طاقم',speaker:'متحدث',media:'إعلام',exhibitor:'عارض'})[g.guest_type]||g.guest_type));
    if(permissions.includes('guests.checkin')){const quantity=field('عدد الداخلين الآن','number','1',{min:1,max:51});card.append(quantity.node,button('تسجيل الدخول',async()=>{const key='px-desk-pending:'+current.id+':'+g.guest_number;const saved=sessionStorage.getItem(key);const pending=saved?JSON.parse(saved):{scan_id:crypto.randomUUID(),quantity:Number(quantity.input.value)};if(pending.quantity!==Number(quantity.input.value))throw new Error('أعد محاولة العملية المعلقة بنفس العدد أولًا.');sessionStorage.setItem(key,JSON.stringify(pending));let result;try{result=await api('/api/admin/events/'+current.id+'/guest-checkins',{guest_number:g.guest_number,...pending,mode:'entry',checkpoint:'main'});}catch(error){if(error.status&&error.status<500)sessionStorage.removeItem(key);throw error;}sessionStorage.removeItem(key);await live.refresh();toast(result.status==='accepted'?'تم تأكيد الدخول':result.status==='duplicate'?'سبق تسجيل العملية':'لم يُقبل الدخول: '+result.status,result.status!=='accepted'&&result.status!=='duplicate');}));}
    return card;
  }));}
  search.input.addEventListener('input',draw);draw();host.append(search.node,list);
}
