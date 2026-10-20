import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

class Element {
  constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat(Infinity).filter(x=>x!=null);this.value=attrs.value??'';this.dataset={};this.isConnected=true;this.handlers={};this.textContent='';}
  append(...children){this.children.push(...children.flat(Infinity));}
  replaceChildren(...children){this.children=[];this.append(...children);}
  addEventListener(name,fn){this.handlers[name]=fn;}
}
const walk=n=>[n,...n.children.filter(x=>x instanceof Element).flatMap(walk)];
const text=n=>n instanceof Element?[n.textContent,...n.children.map(text)].join(' '):String(n);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
async function runtime(){
  const timers=new Map(),storage=new Map(),posts=[],toasts=[];let next=1,post=async()=>({status:'accepted'}),get=async()=>({inside_count:1,admitted_people:2,total_checkins:501});
  const h=(tag,attrs,...children)=>new Element(tag,attrs,children);
  const ui={h,api:async(path,body)=>{if(body){posts.push(body);return post(body);}if(path.endsWith('/guests'))return{guests:[{name:'Guest',guest_number:'G-test',guest_type:'visitor'}]};return get();},
    field:(label,type,value,attrs)=>{const input=h('input',{label,type,value,...attrs});return{input,node:h('label',{},input)};},
    button:(label,fn)=>{const b=h('button',{},label);b.action=fn;return b;},toast:(...v)=>toasts.push(v)};
  const context=vm.createContext({console,Date,JSON,Number,String,Promise,Map,encodeURIComponent,crypto:{randomUUID:()=>`scan-${next++}`},sessionStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setTimeout:(fn,delay)=>{assert.equal(delay,10000);const id=next++;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
  const modules=new Map();
  async function load(name){if(modules.has(name))return modules.get(name);const m=new vm.SourceTextModule(await readFile(new URL('../web/'+name,import.meta.url),'utf8'),{context});modules.set(name,m);await m.link(async s=>s==='./ui.mjs'?new vm.SyntheticModule(Object.keys(ui),function(){for(const[k,v]of Object.entries(ui))this.setExport(k,v);},{context}):s==='./invitations.mjs'?new vm.SyntheticModule(['renderReception'],function(){this.setExport('renderReception',async()=>{});},{context}):load(s.slice(2)));return m;}
  const live=await load('admission-live.mjs');await live.evaluate();const desk=await load('admission-desk.mjs');await desk.evaluate();
  const host=h('main',{});
  return{host,timers,storage,posts,toasts,context,live:live.namespace,desk:desk.namespace,setPost:fn=>post=fn,setGet:fn=>get=fn,async mount(){await desk.namespace.admissionDesk({host,current:{id:'event',permissions:['guests.checkin']},user:{}});return{button:walk(host).find(x=>x.tag==='button'&&x.action),quantity:walk(host).find(x=>x.attrs.type==='number'),card:walk(host).find(x=>x.tag==='article')};}};
}

test('P04-T05 authentication and conflict errors preserve pending identity',async()=>{
 for(const status of [401,403,409,500]){const r=await runtime();const b=await r.mount();r.setPost(async()=>{throw Object.assign(Error('failure'),{status});});await assert.rejects(b.button.action());assert.equal(r.storage.size,1);r.setPost(async()=>({status:'duplicate'}));await b.button.action();assert.equal(r.posts[0].scan_id,r.posts[1].scan_id);assert.equal(r.storage.size,0);}
});
test('P04-T02/T03 lost response freezes quantity until same request is retried',async()=>{
 const r=await runtime(),b=await r.mount();r.setPost(async()=>{throw Error('ACK lost');});await assert.rejects(b.button.action());b.quantity.value='2';await assert.rejects(b.button.action());assert.equal(r.posts.length,1);b.quantity.value='1';r.setPost(async()=>({status:'duplicate'}));await b.button.action();assert.equal(r.posts[0].scan_id,r.posts[1].scan_id);
});
test('P04-T04 double invocation sends one request while in flight',async()=>{
 const r=await runtime(),b=await r.mount(),d=deferred();r.setPost(()=>d.promise);const first=b.button.action();const second=b.button.action();d.resolve({status:'accepted'});await Promise.allSettled([first,second]);assert.equal(r.posts.length,1);
});
test('P04-T06 confirmed POST survives failed dashboard refresh',async()=>{
 const r=await runtime(),b=await r.mount();r.setGet(async()=>{throw Error('GET failed');});await b.button.action();assert.equal(r.storage.size,0);assert.equal(b.card.dataset.state,'confirmed');assert.equal(walk(r.host).find(x=>x.tag==='section').dataset.state,'stale');assert.ok(r.toasts.some(x=>x[0]==='تم تأكيد الدخول'));
});
test('P04-T04 corrupt or unavailable storage fails closed before POST',async()=>{
 for(const bad of ['{','{"scan_id":"a","quantity":0}']){const r=await runtime();r.storage.set('px-desk-pending:event:G-test',bad);const b=await r.mount();await assert.rejects(b.button.action());assert.equal(r.posts.length,0);assert.equal(r.storage.size,1);}
 const r=await runtime();r.context.sessionStorage.setItem=()=>{throw Error('unavailable');};const b=await r.mount();await assert.rejects(b.button.action());assert.equal(r.posts.length,0);
});
test('P04-T07 refresh calls coalesce and keep one timer',async()=>{
 const r=await runtime(),d=deferred();let calls=0;r.setGet(()=>{calls++;return d.promise;});const board=r.live.attendanceDashboard(r.host,'event',{});const a=board.refresh(),b=board.refresh();d.resolve({inside_count:4,admitted_people:8,total_checkins:600});await Promise.all([a,b]);assert.equal(calls,1);assert.equal(r.timers.size,1);assert.match(text(r.host),/600/);
});
test('P04-T08 detached panel does not write or rearm after in-flight request',async()=>{
 const r=await runtime(),d=deferred();r.setGet(()=>d.promise);const board=r.live.attendanceDashboard(r.host,'event',{}),panel=r.host.children[0];const p=board.refresh();panel.isConnected=false;d.resolve({inside_count:99});await p;assert.doesNotMatch(text(r.host),/99/);assert.equal(r.timers.size,0);
});
test('P04-T07 stale visible then recovery and explicit disposal',async()=>{
 const r=await runtime();const board=r.live.attendanceDashboard(r.host,'event',{});r.setGet(async()=>{throw Error('down');});await board.refresh();assert.match(text(r.host),/تعذر/);r.setGet(async()=>({inside_count:2}));await board.refresh();assert.equal(r.host.children[0].dataset.state,'current');board.dispose();assert.equal(r.timers.size,0);await board.refresh();assert.equal(r.timers.size,0);
});

test('P04-T07 fake clock runs one refresh per ten second tick',async()=>{
 const r=await runtime();let calls=0;r.setGet(async()=>{calls++;return{inside_count:calls};});r.live.attendanceDashboard(r.host,'event',{});
 for(let i=0;i<3;i++){assert.equal(r.timers.size,1);const[id,fn]=r.timers.entries().next().value;r.timers.delete(id);await fn();assert.equal(calls,i+1);assert.equal(r.timers.size,1);}
});
