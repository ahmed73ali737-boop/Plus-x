import {h,api} from './ui.mjs';

// These counters are server totals, independent of the 500-row history window.
export function attendanceDashboard(host,eventId,initial){
  const values={};
  const fields=[['inside_count','تذاكر داخل الفعالية'],['admitted_people','مرات دخول الأشخاص بالدعوات'],['total_checkins','حركات الدخول والخروج']];
  const panel=h('section',{class:'admission-live'},h('div',{class:'kpi-grid'},fields.map(([key,label])=>{values[key]=h('strong',{},initial?.[key]??0);return h('div',{class:'kpi'},h('span',{},label),values[key]);})),h('p',{class:'muted small'},'تُحدّث الأعداد كل 10 ثوانٍ. التذكرة قد تضم مرافقين؛ مرات الدخول تشمل الزيارات في أيام مختلفة.'));
  host.append(panel);
  let timer;
  async function refresh(){clearTimeout(timer);if(!panel.isConnected)return;try{const data=await api('/api/admin/events/'+encodeURIComponent(eventId)+'/guest-checkins');for(const [key]of fields)values[key].textContent=data[key]??0;panel.dataset.state='current';}catch{panel.dataset.state='stale';}if(panel.isConnected)timer=setTimeout(refresh,10000);}
  timer=setTimeout(refresh,10000);
  return {refresh};
}
