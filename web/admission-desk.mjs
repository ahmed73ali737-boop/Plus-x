import {h,api,field,button,toast} from './ui.mjs';
import {attendanceDashboard} from './admission-live.mjs';
import {renderReception} from './invitations.mjs';

// One owner per event/pass even if search redraws the card during a request.
const sending=new Set();
const pendingError='تعذر قراءة أو حفظ العملية المعلقة. أوقف المسح واطلب التحقق من سجل الدخول؛ لا تبدأ عملية جديدة.';
function loadPending(key){
  let raw,pending;
  try{raw=sessionStorage.getItem(key);pending=raw===null?null:JSON.parse(raw);}catch{throw new Error(pendingError);}
  if(pending&&(!pending.scan_id||typeof pending.scan_id!=='string'||!Number.isInteger(pending.quantity)||pending.quantity<1||pending.quantity>51))throw new Error(pendingError);
  if(raw!==null&&!pending)throw new Error(pendingError);
  return pending;
}
export async function admissionDesk({host,current,user}){
  const permissions=current.permissions||[];
  if(permissions.includes('guests.register'))await renderReception({host,current,user});
  const [data,summary]=await Promise.all([api('/api/admin/events/'+current.id+'/guests'),api('/api/admin/events/'+current.id+'/guest-checkins')]);
  const live=attendanceDashboard(host,current.id,summary);
  const search=field('بحث بالاسم أو رقم التذكرة','search'),list=h('div',{class:'guest-admin-grid'});
  function draw(){const q=search.input.value.trim().toLowerCase();list.replaceChildren(...data.guests.filter(g=>!q||[g.name,g.guest_number].some(x=>String(x||'').toLowerCase().includes(q))).map(g=>{
    const card=h('article',{class:'card mini'},h('h3',{},g.name||'زائر'),h('code',{},g.guest_number),h('p',{},({visitor:'زائر',vip:'كبار الزوار',staff:'طاقم',speaker:'متحدث',media:'إعلام',exhibitor:'عارض'})[g.guest_type]||g.guest_type));
    if(permissions.includes('guests.checkin')){
      const key='px-desk-pending:'+current.id+':'+g.guest_number;
      const quantity=field('عدد الداخلين الآن','number','1',{min:1,max:51});
      const state=h('p',{'role':'status','aria-live':'polite'});
      card.dataset.state='idle';
      try{const saved=loadPending(key);if(saved){quantity.input.value=String(saved.quantity);card.dataset.state='unknown-outcome';state.textContent='عملية معلقة: أعد المحاولة بنفس العدد للتحقق من نتيجتها.';}}catch(error){state.textContent=error.message;}
      card.append(quantity.node,state,button('تسجيل الدخول',async()=>{
        if(sending.has(key))return;
        const count=Number(quantity.input.value);
        if(!Number.isInteger(count)||count<1||count>51)throw new Error('أدخل عددًا صحيحًا من 1 إلى 51.');
        const pending=loadPending(key)||{scan_id:crypto.randomUUID(),quantity:count};
        if(pending.quantity!==count)throw new Error('أعد محاولة العملية المعلقة بنفس العدد أولًا.');
        // A request is never sent until its replay identity is durable for this tab.
        try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{throw new Error(pendingError);}
        sending.add(key);card.dataset.state='sending';state.textContent='جارٍ التحقق من الدخول…';
        try{
          let result;
          try{result=await api('/api/admin/events/'+current.id+'/guest-checkins',{guest_number:g.guest_number,...pending,mode:'entry',checkpoint:'main'});}
          catch(error){card.dataset.state='unknown-outcome';state.textContent=[401,403].includes(error.status)?'توقفت الصلاحية. أعد المصادقة قبل التحقق من العملية المعلقة بنفس العدد.':'لم تتأكد نتيجة العملية. أعد المحاولة بنفس العدد؛ لا تنشئ مسحًا جديدًا.';throw error;}
          const confirmed=['accepted','duplicate'].includes(result.status);
          // Unexpected responses cannot prove rollback. All HTTP errors retain identity.
          const rejected=['already_inside','already_outside','invalid','rejected'].includes(result.status);
          if(!confirmed&&!rejected){card.dataset.state='unknown-outcome';state.textContent='رد غير معروف؛ احتفظ بالعملية المعلقة وتحقق من سجل الدخول.';throw new Error(state.textContent);}
          card.dataset.state=confirmed?'confirmed':'rejected';
          state.textContent=result.status==='accepted'?'تم تأكيد الدخول':result.status==='duplicate'?'سبق تسجيل العملية':'لم يُقبل الدخول: '+result.status;
          toast(state.textContent,!confirmed);
          try{sessionStorage.removeItem(key);}catch{state.textContent+=' — تعذر تنظيف التخزين؛ أي إعادة محاولة تستخدم المعرف نفسه.';}
          // Display failures must never reverse a committed admission result.
          try{await live.refresh();}catch{/* The panel owns its stale state. */}
        }finally{sending.delete(key);}
      }));
    }
    return card;
  }));}
  search.input.addEventListener('input',draw);draw();host.append(search.node,list);
}
