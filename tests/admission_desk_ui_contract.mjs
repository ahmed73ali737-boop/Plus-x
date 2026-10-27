/** Execute the actual desk/dashboard modules; DOM, transport and time are controlled. */
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import vm from 'node:vm';
const results=[];
const run=async(name,fn)=>{try{await fn();results.push({name,status:'passed'});console.log('PASS',name);}catch(e){results.push({name,status:'failed',reason:e.message,stack:e.stack});console.log('FAIL',name,e.message);}};
class Element {
  constructor(tag,attrs={},...children){this.tag=tag;this.attrs=attrs;this.children=[];this.value=attrs.value??'';this.handlers={};this.dataset={};this.isConnected=true;this.textContent='';this.append(...children);}
  append(...children){for(const x of children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false)){this.children.push(x);if(x instanceof Element)x.isConnected=this.isConnected;}}
  replaceChildren(...children){for(const x of this.children)if(x instanceof Element)x.isConnected=false;this.children=[];this.append(...children);}
  addEventListener(name,fn){this.handlers[name]=fn;}
}
const walk=n=>[n,...n.children.filter(x=>x instanceof Element).flatMap(walk)];
const text=n=>n instanceof Element?n.textContent+' '+n.children.map(text).join(' '):String(n??'');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
async function runtime(permissions=['guests.read','guests.checkin']){
  const calls=[],toasts=[],storage=new Map(),timers=new Map();let sequence=0,reception=0;
  const h=(tag,attrs={},...children)=>new Element(tag,attrs,...children);
  let handler=async(path,body)=>body?{status:'accepted'}:path.endsWith('/guests')?{guests:[{name:'Alice',guest_number:'G-'+'A'.repeat(30),guest_type:'visitor'},{name:'Bob',guest_number:'G-'+'B'.repeat(30),guest_type:'vip'}]}:{inside_count:1,admitted_people:2,total_checkins:501};
  const ui={h,api:async(path,body,...rest)=>{calls.push({path,body});return handler(path,body,...rest);},
    field:(label,type,value='',attrs={})=>{const input=h('input',{'aria-label':label,type,value,...attrs});return{input,node:h('label',{},label,input)};},
    button:(label,fn)=>{const b=h('button',{},label);b.action=fn;return b;},toast:(...v)=>toasts.push(v)};
  const context=vm.createContext({console,Number,String,JSON,encodeURIComponent,crypto:{randomUUID:()=>`synthetic-scan-${++sequence}`},sessionStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setTimeout:(fn,delay)=>{const id=++sequence;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)});
  const source=async name=>new vm.SourceTextModule(await readFile(new URL('../web/'+name,import.meta.url),'utf8'),{context});
  const live=await source('admission-live.mjs');
  const synthetic=values=>new vm.SyntheticModule(Object.keys(values),function(){for(const[k,v]of Object.entries(values))this.setExport(k,v);},{context});
  const uiModule=synthetic(ui);await live.link(()=>uiModule);await live.evaluate();
  const desk=await source('admission-desk.mjs');
  const receptionModule=synthetic({renderReception:async()=>{reception++;}});
  await desk.link(path=>path==='./ui.mjs'?uiModule:path==='./admission-live.mjs'?live:receptionModule);await desk.evaluate();
  const host=h('main');
  return{host,calls,toasts,storage,timers,setHandler:v=>handler=v,get reception(){return reception;},
    async desk(){await desk.namespace.admissionDesk({host,current:{id:'event-a',permissions},user:{role:'member'}});},
    dashboard(initial={inside_count:1,admitted_people:2,total_checkins:501}){return live.namespace.attendanceDashboard(host,'event-a',initial);},
    button:label=>walk(host).find(x=>x.tag==='button'&&text(x).trim()===label),
    input:label=>walk(host).find(x=>x.attrs['aria-label']===label),
    panel:()=>walk(host).find(x=>x.attrs.class==='admission-live'),values:()=>walk(host).filter(x=>x.tag==='strong').map(x=>String(x.textContent||x.children[0])),
    async tick(){const[id,timer]=timers.entries().next().value;timers.delete(id);await timer.fn();}}
}
await run('scanner_renders_search_and_checkin_without_reception',async()=>{const r=await runtime();await r.desk();assert.equal(r.reception,0);assert.equal(walk(r.host).filter(x=>x.tag==='button'&&x.action).length,2);assert.ok(r.input('بحث بالاسم أو رقم التذكرة'));});
await run('analyst_has_no_checkin_or_reception_controls',async()=>{const r=await runtime(['guests.read']);await r.desk();assert.equal(r.reception,0);assert.equal(walk(r.host).filter(x=>x.tag==='button'&&x.action).length,0);});
await run('reception_register_permission_mounts_reception_form',async()=>{const r=await runtime(['guests.read','guests.register']);await r.desk();assert.equal(r.reception,1);});
await run('search_filters_by_name_and_pass_and_has_empty_state',async()=>{const r=await runtime();await r.desk();const input=r.input('بحث بالاسم أو رقم التذكرة');input.value=' alice ';input.handlers.input();assert.equal(walk(r.host).filter(x=>x.tag==='article').length,1);input.value='NO-SUCH-GUEST';input.handlers.input();assert.equal(walk(r.host).filter(x=>x.tag==='article').length,0);});
await run('accepted_scan_sends_quantity_and_clears_pending',async()=>{const r=await runtime();await r.desk();r.input('عدد الداخلين الآن').value='2';await r.button('تسجيل الدخول').action();const body=r.calls.find(x=>x.body).body;assert.equal(body.quantity,2);assert.equal(body.checkpoint,'main');assert.equal(body.mode,'entry');assert.equal(r.storage.size,0);assert.equal(r.toasts.at(-1)[0],'تم تأكيد الدخول');});
await run('lost_ack_reuses_scan_id_and_quantity_until_duplicate_receipt',async()=>{const r=await runtime();await r.desk();let first=true;r.setHandler(async(path,body)=>{if(!body)return{};if(first){first=false;throw TypeError('lost ACK after server commit');}return{status:'duplicate'};});await assert.rejects(r.button('تسجيل الدخول').action(),/lost ACK/);assert.equal(r.storage.size,1);const original=r.calls.filter(x=>x.body)[0].body;await r.button('تسجيل الدخول').action();const retry=r.calls.filter(x=>x.body)[1].body;assert.equal(retry.scan_id,original.scan_id);assert.equal(retry.quantity,original.quantity);assert.equal(r.storage.size,0);assert.equal(r.toasts.at(-1)[0],'سبق تسجيل العملية');});
await run('changing_quantity_during_pending_does_not_send_new_command',async()=>{const r=await runtime();await r.desk();r.setHandler(async()=>{throw Object.assign(Error('server error'),{status:500});});await assert.rejects(r.button('تسجيل الدخول').action());const count=r.calls.length;r.input('عدد الداخلين الآن').value='2';await assert.rejects(r.button('تسجيل الدخول').action(),/بنفس العدد/);assert.equal(r.calls.length,count);assert.equal(r.storage.size,1);});
await run('http_conflict_preserves_unknown_pending_and_never_toasts_success',async()=>{const r=await runtime();await r.desk();r.setHandler(async()=>{throw Object.assign(Error('ADMISSION_ALREADY_USED'),{status:409});});await assert.rejects(r.button('تسجيل الدخول').action(),/ADMISSION_ALREADY_USED/);assert.equal(r.storage.size,1);assert.equal(r.toasts.length,0);});
await run('double_click_while_inflight_reuses_one_scan_identity',async()=>{const r=await runtime();await r.desk();const pending=deferred();r.setHandler(async(path,body)=>body?pending.promise:{});const first=r.button('تسجيل الدخول').action(),second=r.button('تسجيل الدخول').action();const bodies=r.calls.filter(x=>x.body).map(x=>x.body);assert.equal(bodies.length,1);assert.ok(bodies[0].scan_id);pending.resolve({status:'accepted'});await Promise.all([first,second]);});
await run('confirmed_scan_survives_summary_refresh_failure',async()=>{const r=await runtime();await r.desk();r.setHandler(async(path,body)=>{if(body)return{status:'accepted'};throw Error('summary unavailable');});await r.button('تسجيل الدخول').action();assert.equal(r.storage.size,0);assert.equal(r.panel().dataset.state,'stale');assert.equal(r.toasts.at(-1)[0],'تم تأكيد الدخول');});
await run('dashboard_preserves_server_totals_above_history_window',async()=>{const r=await runtime();r.dashboard({inside_count:8,admitted_people:900,total_checkins:1501});assert.deepEqual(r.values(),['8','900','1501']);});
await run('dashboard_refresh_updates_three_semantically_distinct_totals',async()=>{const r=await runtime();const live=r.dashboard();r.setHandler(async()=>({inside_count:3,admitted_people:12,total_checkins:1200}));await live.refresh();assert.deepEqual(r.values(),['3','12','1200']);assert.equal(r.panel().dataset.state,'current');});
await run('dashboard_network_failure_keeps_values_and_marks_stale',async()=>{const r=await runtime();const live=r.dashboard();r.setHandler(async()=>{throw TypeError('offline');});await live.refresh();assert.deepEqual(r.values(),['1','2','501']);assert.equal(r.panel().dataset.state,'stale');});
await run('dashboard_recovers_after_stale_without_recreating_panel',async()=>{const r=await runtime();const live=r.dashboard();r.setHandler(async()=>{throw Error('offline');});await live.refresh();r.setHandler(async()=>({inside_count:2,admitted_people:4,total_checkins:600}));await live.refresh();assert.equal(r.panel().dataset.state,'current');assert.deepEqual(r.values(),['2','4','600']);});
await run('dashboard_timer_schedules_ten_seconds_once',async()=>{const r=await runtime();r.dashboard();assert.equal(r.timers.size,1);assert.equal([...r.timers.values()][0].delay,10000);await r.tick();assert.equal(r.timers.size,1);});
await run('unmounted_dashboard_stops_future_api_calls_and_rescheduling',async()=>{const r=await runtime();r.dashboard();r.panel().isConnected=false;await r.tick();assert.equal(r.calls.length,0);assert.equal(r.timers.size,0);});
await run('manual_refresh_replaces_existing_timer',async()=>{const r=await runtime();const live=r.dashboard();await live.refresh();assert.equal(r.timers.size,1);});
await run('overlapping_refresh_newer_response_must_not_be_overwritten',async()=>{const r=await runtime();const live=r.dashboard();const old=deferred(),latest=deferred();let n=0;r.setHandler(()=>++n===1?old.promise:latest.promise);const a=live.refresh(),b=live.refresh();assert.equal(n,1,'Overlapping refreshes must share one in-flight request');assert.equal(a,b);old.resolve({inside_count:5,admitted_people:20,total_checkins:1000});await Promise.all([a,b]);assert.deepEqual(r.values(),['5','20','1000'],'An older response overwrote a newer confirmed dashboard state');});
await run('overlapping_refresh_must_not_create_duplicate_timer_loops',async()=>{const r=await runtime();const live=r.dashboard();const pending=deferred();r.setHandler(()=>pending.promise);const a=live.refresh(),b=live.refresh();pending.resolve({inside_count:1,admitted_people:1,total_checkins:1});await Promise.all([a,b]);assert.equal(r.timers.size,1,'Each overlapping refresh scheduled another timer loop');});
await mkdir('qa/hardening',{recursive:true});
const report={suite:'ADMISSION_DESK_AND_LIVE_FUNCTIONAL_CONTRACT',scope:'Actual modules; controlled DOM, API transport and timers; not native network',passed:results.filter(x=>x.status==='passed').length,failed:results.filter(x=>x.status==='failed').length,cases:results};
await writeFile('qa/hardening/admission-desk-ui-contract.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
process.exitCode=report.failed?1:0;
