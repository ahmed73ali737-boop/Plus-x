import {h,api} from './ui.mjs';

// Server totals are independent of the 500-row history window.
export function attendanceDashboard(host,eventId,initial){
  const values={};
  const fields=[['inside_count','تذاكر داخل الفعالية'],['admitted_people','مرات دخول الأشخاص بالدعوات'],['total_checkins','حركات الدخول والخروج']];
  const status=h('p',{class:'muted small',role:'status','aria-live':'polite'});
  const panel=h('section',{class:'admission-live'},h('div',{class:'kpi-grid'},fields.map(([key,label])=>{values[key]=h('strong',{},initial?.[key]??0);return h('div',{class:'kpi'},h('span',{},label),values[key]);})),h('p',{class:'muted small'},'تُحدّث الأعداد كل 10 ثوانٍ. التذكرة قد تضم مرافقين؛ مرات الدخول تشمل الزيارات في أيام مختلفة.'),status,h('button',{type:'button',class:'btn secondary',onclick:()=>refresh()},'إعادة تحديث العدادات'));
  host.append(panel);
  let timer,inFlight=null,disposed=false,lastUpdated=initial?new Date().toLocaleTimeString('ar'):null;
  panel.dataset.state=initial?'current':'stale';
  function describe(stale){status.textContent=(stale?'تعذر تحديث العدادات؛ القيم المعروضة قديمة. ':'')+(lastUpdated?'آخر تحديث: '+lastUpdated:'لم تصل العدادات بعد.');}
  describe(!initial);
  function schedule(){clearTimeout(timer);if(!disposed&&panel.isConnected)timer=setTimeout(refresh,10000);}
  function refresh(){
    clearTimeout(timer);
    if(disposed||!panel.isConnected)return Promise.resolve();
    if(inFlight)return inFlight;
    inFlight=(async()=>{
      try{
        const data=await api('/api/admin/events/'+encodeURIComponent(eventId)+'/guest-checkins');
        if(disposed||!panel.isConnected)return;
        for(const[key]of fields)values[key].textContent=data[key]??0;
        panel.dataset.state='current';lastUpdated=new Date().toLocaleTimeString('ar');describe(false);
      }catch{
        if(!disposed&&panel.isConnected){panel.dataset.state='stale';describe(true);}
      }finally{inFlight=null;schedule();}
    })();
    return inFlight;
  }
  schedule();
  return {refresh,dispose(){disposed=true;clearTimeout(timer);}};
}
