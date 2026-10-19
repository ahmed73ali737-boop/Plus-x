/** Focused DOM-contract tests; browser, camera, PostgreSQL and field acceptance are separate gates. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../web/invitations.mjs',import.meta.url),'utf8')
  .replace(/^import .*?;\s*$/gm,'').replace(/export async function /g,'async function ');
class Element {
  constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs={...attrs};this.children=children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false);this.handlers={};this.value=attrs.value??'';this.checked=!!attrs.checked;this.disabled=false;this.isConnected=true;this.textContent='';this.classList={add:(...c)=>{this.attrs.class=((this.attrs.class||'')+' '+c.join(' ')).trim();},remove:(...c)=>{this.attrs.class=(this.attrs.class||'').split(' ').filter(x=>!c.includes(x)).join(' ');}};}
  append(...children){this.children.push(...children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false));}
  replaceChildren(...children){this.children=[];this.append(...children);}
  addEventListener(name,fn){this.handlers[name]=fn;}
  setAttribute(key,value){this.attrs[key]=value;}
  reportValidity(){return true;}
  focus(){}
  select(){}
  querySelector(selector){if(selector==='[type="submit"]')return walk(this).find(x=>x.attrs.type==='submit');return null;}
}
const walk=node=>[node,...node.children.filter(x=>x instanceof Element).flatMap(walk)];
const text=node=>node instanceof Element?(node.textContent+' '+node.children.map(text).join(' ')):String(node??'');
const h=(tag,attrs={},...children)=>new Element(tag,attrs,children);
const root=h('main'),toasts=[],dialogs=[],calls=[],downloads=[];let responses=new Map();
const button=(label,fn,cls='btn')=>{const el=h('button',{type:'button',class:cls},label);el.action=fn;return el;};
const field=(label,type='text',value='',attrs={})=>{const input=h('input',{type,value,'aria-label':label,...attrs});return{input,node:h('label',{},label,input)};};
const selectField=(label,options,value)=>{const input=h('select',{'aria-label':label,value},options.map(([value,label])=>h('option',{value},label)));return{input,node:h('label',{},label,input)};};
const check=(label,value=false)=>{const input=h('input',{type:'checkbox',checked:value});return{input,node:h('label',{},input,label)};};
const ctx={h,root,field,selectField,check,button,brand:()=>h('a',{},'PulseX'),toast:v=>toasts.push(v),msg:e=>e.message,
  modal:(title,body)=>{const node=h('dialog',{},title,body);node.close=()=>{node.closed=true;};dialogs.push(node);return node;},
  download:(...args)=>downloads.push(args),isoToLocalInput:v=>v||'',localInputToISO:v=>new Date(v).toISOString(),
  api:async(path,body,method)=>{calls.push({path,body,method});const value=responses.get(path);if(value instanceof Error)throw value;if(typeof value==='function')return value(body,method);if(!value)throw new Error('UNEXPECTED_API '+path);return structuredClone(value);},
  navigator:{},location:{origin:'https://example.test',assign:path=>{ctx.location.assigned=path;}},
  document:{documentElement:{},body:h('body'),title:''},window:{print(){}},URL,Intl,Date,Set,Number,String,JSON,encodeURIComponent,FileReader:class{readAsDataURL(){this.result='data:text/csv;base64,YQ==';this.onload();}}};
runInNewContext(source+'\nthis.exports={renderInvitations,invitationPage,invitationRegistrationPage,renderReception};',ctx);
const el=(node,label)=>walk(node).find(x=>x.attrs['aria-label']===label);
const btn=(node,label)=>walk(node).find(x=>x.tag==='button'&&text(x).trim()===label);
const form=node=>walk(node).find(x=>x.tag==='form');
const submit=async node=>{await form(node).handlers.submit({preventDefault(){}});};
const choose=node=>{node.checked=true;};
const base='/api/admin/events/event-1';
const policy={visibility:'private',enabled:true,timezone:'Asia/Aden',registration_mode:'manual',entry_mode:'daily',max_companions:3,days:[{date:'2026-11-01',capacity:100},{date:'2026-11-02',capacity:100}]};
const publicView={event:{id:'event-1',slug:'expo',title:'معرض التقنية'},policy,invitation:{name:'زائر الاختبار',status:'invited',max_companions:2,allowed_days:['2026-11-02'],days:[],companions:0}};
let count=0;const pass=()=>count++;

// Role filtering never requests admin data for a participant account.
responses.set(base+'/permissions',{permissions:[]});let host=h('div');await ctx.exports.renderInvitations({host,current:{id:'event-1',kind:'event',slug:'expo'},user:{role:'agency'}});assert.equal(calls.length,1);assert.match(text(host),/لا يملك صلاحية/);pass();
calls.length=0;responses=new Map([[base+'/permissions',{permissions:['invitations.manage','invitations.review','policy.manage']}],[base+'/admission-policy',{policy}],[base+'/guest-lists',{lists:[{id:'vip',name:'كبار الزوار'}]}],[base+'/invitations',{invitations:[{id:'i1',revision:3,name:'مدعو',phone:'+967777123456',status:'pending_approval',companions:1,max_companions:2,days:['2026-11-02'],list_id:'vip'}]}]]);
host=h('div');await ctx.exports.renderInvitations({host,current:{id:'event-1',kind:'event',slug:'expo'},user:{role:'organizer'}});assert.equal(calls.length,4);assert.ok(btn(host,'اعتماد'));assert.equal(walk(host).find(x=>x.tag==='a'&&text(x).includes('صفحة التسجيل')),undefined);pass();
responses.set(base+'/invitations/i1/review',body=>{assert.equal(body.decision,'approve');assert.equal(body.revision,3);return{ok:true};});await btn(host,'اعتماد').action();assert.equal(calls.filter(x=>x.path.endsWith('/review')).length,1);pass();
await btn(host,'إعدادات الحضور').action();assert.equal(el(host,'المنطقة الزمنية').value,'Asia/Aden');assert.equal(el(host,'صلاحية الدخول').value,'daily');assert.equal(el(host,'آخر موعد للرد — اختياري').attrs.type,'datetime-local');pass();
const beforePolicy=calls.length;el(host,'المنطقة الزمنية').value='invalid-time-zone';await submit(host);assert.equal(calls.length,beforePolicy);assert.match(text(host),/منطقة زمنية صحيح/);pass();
await btn(host,'المدعوون').action();await btn(host,'إضافة مدعو').action();let dialog=dialogs.at(-1);assert.equal(el(dialog,'رقم الهاتف').attrs.type,'tel');el(dialog,'اسم المدعو').value='مدعو جديد';el(dialog,'رقم الهاتف').value='+967777111222';responses.set(base+'/invitations',body=>body?{token:'safe-token',invitation_url:'/invite/safe-token'}:{invitations:[]});await submit(dialog);assert.ok(calls.find(x=>x.path===base+'/invitations'&&x.body?.name==='مدعو جديد'));assert.ok(walk(dialogs.at(-1)).some(x=>x.tag==='a'&&x.attrs.href==='/invite/safe-token'));pass();

// Public view is token scoped. No list/admin API is requested.
responses.set('/api/public/invitations/test-token',publicView);calls.length=0;await ctx.exports.invitationPage('test-token');assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/public/invitations/test-token');assert.match(text(root),/زائر الاختبار/);assert.equal(walk(root).filter(x=>x.name==='attendance_days').length,1);assert.equal(walk(root).find(x=>x.name==='attendance_days').value,'2026-11-02');pass();
const initialCalls=calls.length;await submit(root);assert.equal(calls.length,initialCalls);assert.match(text(root),/يلزم الموافقة/);pass();
choose(walk(root).find(x=>x.attrs.type==='checkbox'&&!x.name));el(root,'عدد المرافقين').value='1';responses.set('/api/public/invitations/test-token/rsvp',body=>{assert.equal(body.response,'accepted');assert.equal(body.companions,1);assert.deepEqual(Array.from(body.days),['2026-11-02']);return{ok:true};});await submit(root);assert.equal(calls.filter(x=>x.path.endsWith('/rsvp')).length,1);pass();
responses.set('/api/public/invitations/test-token',{...publicView,invitation:{...publicView.invitation,status:'approved',response:'accepted',days:['2026-11-02']},qr_image_url:'/api/public/invitations/test-token/qr',pass_url:'/e/expo/guest/G-abc',guest_number:'G-abc'});await ctx.exports.invitationPage('test-token');assert.equal(walk(root).find(x=>x.tag==='img').attrs.src,'/api/public/invitations/test-token/qr');assert.ok(walk(root).find(x=>x.tag==='a'&&x.attrs.href==='/e/expo/guest/G-abc'));pass();
responses.set('/api/public/invitations/test-token',{...publicView,invitation:{...publicView.invitation,status:'pending_approval'},qr_image_url:'/unexpected-qr'});await ctx.exports.invitationPage('test-token');assert.equal(walk(root).filter(x=>x.tag==='img').length,0);assert.match(text(root),/قيد مراجعة المنظم/);pass();
responses.set('/api/public/invitations/test-token',{...publicView,invitation:{...publicView.invitation,status:'revoked'}});await ctx.exports.invitationPage('test-token');assert.equal(form(root),undefined);assert.match(text(root),/أُلغيت الدعوة/);pass();
responses.set('/api/public/invitations/test-token',new Error('INVITATION_NOT_FOUND'));await ctx.exports.invitationPage('test-token');assert.match(text(root),/رابط الدعوة غير صالح/);assert.ok(btn(root,'إعادة المحاولة'));pass();

// Public registration persists server output and navigates only to an own-origin link.
responses.set('/api/public/events/expo/registration',body=>body?{token:'registration-token',invitation_url:'/invite/registration-token'}:{event:publicView.event,policy:{...policy,visibility:'public'}});await ctx.exports.invitationRegistrationPage('expo');assert.equal(el(root,'رقم الهاتف').attrs.type,'tel');el(root,'الاسم').value='مشارك';el(root,'رقم الهاتف').value='+967777222333';choose(walk(root).find(x=>x.attrs.type==='checkbox'&&!x.name));choose(walk(root).find(x=>x.name==='attendance_days'));await submit(root);assert.equal(ctx.location.assigned,'/invite/registration-token');pass();

// Preview errors never expose a commit button, and a changed file clears preview state.
responses.set(base+'/invitations',{invitations:[]});host=h('div');await ctx.exports.renderInvitations({host,current:{id:'event-1',kind:'event',slug:'expo'},user:{role:'organizer'}});await btn(host,'استيراد المدعوين').action();el(host,'ملف المدعوين').files=[{name:'guests.csv',size:100}];responses.set(base+'/invitations/import/preview',{rows:[],valid_count:0,errors:[{row:2,error:'PHONE_INVALID'}]});await submit(host);assert.match(text(host),/صحح الأخطاء/);assert.equal(walk(host).filter(x=>x.tag==='button'&&text(x).includes('اعتماد استيراد')).length,0);pass();
responses.set(base+'/invitations/import/preview',{import_id:'preview-1',rows:[{name:'أ',phone:'+967777333444',days:['2026-11-02']}],valid_count:1,errors:[]});await submit(host);assert.ok(btn(host,'اعتماد استيراد 1 مدعوًا'));el(host,'ملف المدعوين').handlers.change();assert.equal(btn(host,'اعتماد استيراد 1 مدعوًا'),undefined);pass();

// Missing QR URLs are not mistaken for the website root. Empty allowed_days inherits event days.
responses.set('/api/public/invitations/test-token',{...publicView,invitation:{...publicView.invitation,status:'approved',response:'accepted',allowed_days:[]}});await ctx.exports.invitationPage('test-token');assert.equal(walk(root).filter(x=>x.tag==='img').length,0);assert.equal(walk(root).filter(x=>x.name==='attendance_days').length,2);pass();
// Reception can register with its own permission, without loading any invitation list.
calls.length=0;responses.set(base+'/on-site-registration',body=>body?{invitation:{name:body.name,status:'pending_approval'},token:'onsite-token',invitation_url:'/invite/onsite-token'}:{event:publicView.event,policy});host=h('main');await ctx.exports.renderReception({host,current:{id:'event-1',kind:'event',permissions:['guests.register']},user:{role:'member'}});assert.equal(calls.length,1);assert.equal(calls[0].path,base+'/on-site-registration');el(host,'اسم الزائر').value='زائر موقع';el(host,'رقم هاتف الزائر').value='+967777444555';choose(walk(host).find(x=>x.attrs.type==='checkbox'&&!x.name));choose(walk(host).find(x=>x.name==='attendance_days'));await submit(host);const receptionCall=calls.find(x=>x.body?.name==='زائر موقع');assert.equal(receptionCall.body.approve,false);assert.match(text(host),/بانتظار الاعتماد/);assert.equal(el(host,'اسم الزائر').value,'');pass();
// A policy without dated sessions can still accept a legitimate public registration.
responses.set('/api/public/events/undated/registration',body=>body?{token:'undated-token',invitation_url:'/invite/undated-token'}:{event:publicView.event,policy:{...policy,visibility:'public',days:[]}});await ctx.exports.invitationRegistrationPage('undated');el(root,'الاسم').value='ضيف دون يوم محدد';el(root,'رقم الهاتف').value='+967777000888';choose(walk(root).find(x=>x.attrs.type==='checkbox'));await submit(root);assert.equal(ctx.location.assigned,'/invite/undated-token');pass();
// Committee shifts and account creation are scoped actions, not global role changes.
const committeeSource=readFileSync(new URL('../web/committee.mjs',import.meta.url),'utf8').replace(/^import .*?;\s*$/gm,'').replace(/export async function /g,'async function ');const committeeContext={...ctx};runInNewContext(committeeSource+'\nthis.renderCommittee=renderCommittee;',committeeContext);responses.set(base+'/committee',{assignments:[],roles:['reception','scanner']});host=h('main');await committeeContext.renderCommittee({host,current:{id:'event-1',permissions:['committee.manage']},user:{role:'organizer'}});await btn(host,'إضافة عضو إلى اللجنة').action();dialog=dialogs.at(-1);el(dialog,'بريد حساب العضو').value='crew@example.test';el(dialog,'بداية المناوبة — اختياري').value='2026-11-02T12:00';el(dialog,'نهاية المناوبة — اختياري').value='2026-11-01T12:00';const beforeAssignment=calls.length;await submit(dialog);assert.equal(calls.length,beforeAssignment);assert.match(text(dialog),/تنتهي المناوبة بعد بدايتها/);pass();
el(dialog,'بداية المناوبة — اختياري').value='';el(dialog,'نهاية المناوبة — اختياري').value='';const createCheckbox=walk(dialog).find(x=>x.attrs.type==='checkbox');createCheckbox.checked=true;createCheckbox.handlers.change();el(dialog,'اسم العضو الجديد').value='عضو جديد';responses.set(base+'/committee',body=>body?{temporary_password:'test-temporary-credential'}:{assignments:[],roles:['reception','scanner']});await submit(dialog);assert.ok(calls.find(x=>x.path===base+'/committee'&&x.body?.create_account===true&&x.body.role==='reception'));assert.equal(el(dialogs.at(-1),'كلمة المرور المؤقتة').value,'test-temporary-credential');pass();

// Public event details come only from the supplied projection and use the event timezone.
responses.set('/api/public/invitations/test-token',publicView);await ctx.exports.invitationPage('test-token');assert.equal(walk(root).filter(x=>x.attrs['aria-label']==='تفاصيل الفعالية').length,0);assert.doesNotMatch(text(root),/undefined|null/);pass();
const eventProjection={...publicView.event,description:'تجارب ومشاركات حية',location:'صنعاء — القاعة الرئيسية',start:'2026-11-01T06:00:00Z',end:'2026-11-01T14:00:00Z'};responses.set('/api/public/invitations/test-token',{...publicView,event:eventProjection});await ctx.exports.invitationPage('test-token');const details=walk(root).find(x=>x.attrs['aria-label']==='تفاصيل الفعالية');assert.ok(details);assert.match(text(details),/صنعاء — القاعة الرئيسية/);assert.match(text(details),/تجارب ومشاركات حية/);assert.match(text(details),/بتوقيت عدن/);assert.equal(walk(details).find(x=>x.tag==='time').children[0],new Intl.DateTimeFormat('ar-YE',{timeZone:'Asia/Aden',dateStyle:'long',timeStyle:'short'}).format(new Date(eventProjection.start)));assert.equal(walk(details).filter(x=>x.tag==='a').length,0);pass();
responses.set('/api/public/events/details/registration',{event:{...eventProjection,start:'invalid',end:null},policy:{...policy,visibility:'public'}});await ctx.exports.invitationRegistrationPage('details');const registrationDetails=walk(root).find(x=>x.attrs['aria-label']==='تفاصيل الفعالية');assert.ok(registrationDetails);assert.equal(walk(registrationDetails).filter(x=>x.tag==='time').length,0);assert.match(text(registrationDetails),/القاعة الرئيسية/);assert.doesNotMatch(text(registrationDetails),/undefined|null|Invalid Date/);pass();
console.log(JSON.stringify({suite:'INVITATIONS_UI_CONTRACT',passed:count,failed:0,scope:'Isolated DOM contract; not real browser or field acceptance'}));
