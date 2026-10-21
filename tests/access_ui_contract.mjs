import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
class Element{
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat(Infinity).filter(x=>x!=null);this.value=attrs.value??'';this.checked=!!attrs.checked;this.handlers={};}
 append(...xs){this.children.push(...xs.flat(Infinity));}
 replaceChildren(...xs){this.children=[];this.append(...xs);}
 addEventListener(name,fn){this.handlers[name]=fn;}
 reportValidity(){return true;}
}
const walk=n=>[n,...n.children.filter(x=>x instanceof Element).flatMap(walk)];
const text=n=>n instanceof Element?n.children.map(text).join(' '):String(n??'');
async function runtime(failDownload=false){
 const h=(t,a,...c)=>new Element(t,a,c),root=h('main',{}),head=h('head',{}),calls=[];let pending=null;
 const location={href:'initial'};const ctx=vm.createContext({location,crypto:{randomUUID:()=> 'a'.repeat(32)},encodeURIComponent,document:{head,documentElement:{},querySelector:()=>null},Number,Error});
 const ui={newRequestKey:()=> 'a'.repeat(48),h,root,msg:e=>e.message,brand:()=>h('a',{href:'/'},'PulseX'),
  field:(label,type,value,attrs)=>{const input=h('input',{label,type,value,...attrs});return{input,node:h('label',{},input)};},
  selectField:(label,options,value)=>{const input=h('select',{label,value},options.map(([v,l])=>h('option',{value:v},l)));return{input,node:h('label',{},input)};},
  check:label=>{const input=h('input',{type:'checkbox',label});return{input,node:h('label',{},input)};},
  api:async(path,body)=>{calls.push({path,body});if(path==='/api/downloads/android'){if(failDownload)throw Error('offline');return{channel:'preview',download_url:'/downloads/eventna-android-preview.apk',bytes:299736,sha256:'a'.repeat(64),min_android:8};}if(path==='/api/public/site/platform')return{events:[{id:'event-demo',title:'Event'}]};if(path==='/api/signup-request')return pending?pending:{status:'pending',grants_access:false,tracking_token:'test-tracking-capability'};throw Error(path);}};
 const mod=new vm.SourceTextModule(await readFile(new URL('../web/access.mjs',import.meta.url),'utf8'),{context:ctx});
 await mod.link(specifier=>{const exports=ui;return new vm.SyntheticModule(Object.keys(exports),function(){for(const[k,v]of Object.entries(exports))this.setExport(k,v);},{context:ctx});});await mod.evaluate();await mod.namespace.accessPage();
 return{root,calls,location,form:()=>walk(root).find(x=>x.tag==='form'),field:label=>walk(root).find(x=>x.attrs.label===label),setPending(p){pending=p;}};
}
test('public entry withdraws reported APK and offers web access',async()=>{
 const r=await runtime();const links=walk(r.root).filter(x=>x.tag==='a');
 assert.ok(links.some(x=>x.attrs.href==='/'&&text(x).includes('ضيف')));
 assert.ok(links.some(x=>x.attrs.href==='/admin'));
 assert.equal(links.filter(x=>String(x.attrs.href).endsWith('.apk')).length,0);
 assert.ok(links.some(x=>x.attrs.href==='/'&&text(x).includes('نسخة الويب')));
 assert.match(text(r.root),/تنزيل Android متوقف مؤقتًا/);assert.equal(r.calls.length,0);
});
test('consent blocks POST; account request remains pending without privileges',async()=>{
 const r=await runtime();await r.form().handlers.submit({preventDefault(){}});assert.equal(r.calls.filter(x=>x.body).length,0);
 r.field('أوافق على إرسال هذه البيانات للمنظم لمراجعة طلب الحساب.').checked=true;
 await r.form().handlers.submit({preventDefault(){}});
 assert.equal(r.calls.filter(x=>x.body).length,1);assert.equal(r.location.href,'/account/request#test-tracking-capability');assert.doesNotMatch(text(r.root),/تم تفعيل حساب/);
});
test('participant requires selection from published event options',async()=>{
 const r=await runtime();r.field('نوع الحساب').value='participant';await r.field('نوع الحساب').handlers.change();
 r.field('أوافق على إرسال هذه البيانات للمنظم لمراجعة طلب الحساب.').checked=true;
 await r.form().handlers.submit({preventDefault(){}});assert.equal(r.calls.filter(x=>x.body).length,0);
 r.field('الفعالية المطلوبة').value='event-demo';await r.form().handlers.submit({preventDefault(){}});
 assert.equal(r.calls.find(x=>x.body).body.site_id,'event-demo');
});
test('download failure never invents a working APK link',async()=>{
 const r=await runtime(true);assert.equal(walk(r.root).filter(x=>x.attrs.href==='/downloads/eventna-android-preview.apk').length,0);
});
test('double submit sends one request',async()=>{
 const r=await runtime();r.field('أوافق على إرسال هذه البيانات للمنظم لمراجعة طلب الحساب.').checked=true;
 let resolve;r.setPending(new Promise(r=>resolve=r));const first=r.form().handlers.submit({preventDefault(){}});const second=r.form().handlers.submit({preventDefault(){}});resolve({status:'pending',grants_access:false,tracking_token:'test-tracking-capability'});await Promise.all([first,second]);assert.equal(r.calls.filter(x=>x.body).length,1);
});
