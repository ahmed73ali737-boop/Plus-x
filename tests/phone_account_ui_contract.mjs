/** Functional DOM contracts; these do not replace the real-browser acceptance. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
class Element{
  constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat(Infinity).filter(x=>x!=null);this.value=attrs.value??'';this.type=attrs.type;this.handlers={};this.textContent='';}
  append(...parts){this.children.push(...parts.flat(Infinity));}
  replaceChildren(...parts){this.children=[];this.append(...parts);}
  addEventListener(name,fn){this.handlers[name]=fn;}
  reportValidity(){return true;}
  focus(){}
}
const walk=node=>[node,...node.children.filter(x=>x instanceof Element).flatMap(walk)];
async function runtime({path='/account/signup',pending,certificateAccess={can_manage:false,has_history:false}}={}){
  const h=(tag,attrs,...children)=>new Element(tag,attrs,children),root=h('div',{}),head=h('head',{}),calls=[],csrf=[];
  const location={pathname:path,href:'initial',replace(url){this.href=url;}};
  const ui={newRequestKey:()=> 'a'.repeat(48),h,root,brand:()=>h('a',{href:'/'},'Eventna'),setCSRF:value=>csrf.push(value),msg:error=>error.message,
    field:(label,type,value,attrs)=>{const input=h('input',{label,type,value,...attrs});return{input,node:h('label',{},input)};},
    button:(label,fn)=>{const node=h('button',{label},label);node.fn=fn;return node;},modal:()=>{},
    api:async(path,body)=>{calls.push({path,body});if(path==='/api/auth/register'){if(pending)await pending;return{status:'pending',tracking_token:'test-tracking-capability',grants_access:false};}if(path==='/api/self-certificates/access')return certificateAccess;if(path==='/api/auth/me')return{csrf:'test-csrf',user:{name:'Owner',role:'attendee',phone:'+967777123456'}};throw new Error(path);}};
  const context=vm.createContext({crypto:{randomUUID:()=>'a'.repeat(32)},location,document:{head,documentElement:{},querySelector:selector=>selector==='.access-header'?walk(root).find(node=>node.attrs.class==='access-header'):null},Number,Error,encodeURIComponent});
  const uiModule=new vm.SyntheticModule(Object.keys(ui),function(){for(const[key,value]of Object.entries(ui))this.setExport(key,value);},{context});
  const shared=new vm.SourceTextModule(await readFile(new URL('../web/account.mjs',import.meta.url),'utf8'),{context});
  const page=new vm.SourceTextModule(await readFile(new URL('../web/account-page.mjs',import.meta.url),'utf8'),{context});
  await page.link(specifier=>specifier==='./account.mjs'?shared:uiModule);await page.evaluate();await page.namespace.accountPage();
  const field=label=>walk(root).find(node=>node.attrs.label===label);
  return{root,location,calls,csrf,field,form:()=>walk(root).find(node=>node.tag==='form')};
}
const fill=(r,confirmation='Personal-Password-2026!')=>{r.field('الاسم').value='Owner';r.field('رقم الهاتف').value='777123456';r.field('كلمة المرور الجديدة — 12 إلى 256 حرفًا').value='Personal-Password-2026!';r.field('تأكيد كلمة المرور الجديدة').value=confirmation;};
test('phone signup requires no email and makes a single direct request without verification',async()=>{
  const r=await runtime();fill(r);assert.equal(r.field('رقم الهاتف').attrs.type,'tel');assert.equal(r.field('رقم الهاتف').attrs.required,true);
  assert.equal(walk(r.root).some(node=>node.attrs.type==='email'),false);
  await r.form().handlers.submit({preventDefault(){}});
  assert.equal(r.calls.length,1);assert.equal(r.calls[0].path,'/api/auth/register');assert.equal(r.calls[0].body.phone,'777123456');
  assert.equal('email' in r.calls[0].body,false);assert.equal('verification_token' in r.calls[0].body,false);assert.equal(r.location.href,'/account/request#test-tracking-capability');assert.deepEqual(r.csrf,[]);assert.ok(r.calls[0].body.request_key.length>=32);
});
test('confirmation mismatch blocks registration and does not clear entered data',async()=>{
  const r=await runtime();fill(r,'Wrong-Password-2026!');await r.form().handlers.submit({preventDefault(){}});
  assert.equal(r.calls.length,0);assert.equal(r.location.href,'initial');assert.equal(r.field('رقم الهاتف').value,'777123456');
  assert.ok(walk(r.root).some(node=>node.textContent==='PASSWORD_CONFIRMATION_MISMATCH'));
});
test('double submission while account creation is pending sends one request',async()=>{
  let release;const pending=new Promise(resolve=>release=resolve);const r=await runtime({pending});fill(r);
  const first=r.form().handlers.submit({preventDefault(){}});await r.form().handlers.submit({preventDefault(){}});release();await first;assert.equal(r.calls.length,1);
});
test('ordinary account page reads its own session and certificate eligibility without offering management',async()=>{
  const r=await runtime({path:'/account'});assert.deepEqual(r.calls.map(row=>row.path),['/api/auth/me','/api/self-certificates/access']);
  assert.equal(walk(r.root).some(node=>node.tag==='a'&&node.attrs.href==='/certificates'),false);
  assert.equal(walk(r.root).some(node=>node.tag==='a'&&node.attrs.href==='/admin'),false);
  assert.equal(walk(r.root).some(node=>node.tag==='a'&&node.attrs.href==='/start#account'),true);
});

for(const certificateAccess of [{can_manage:true,has_history:false},{can_manage:false,has_history:true}]){
  test('certificate management or retained history exposes only the certificate entry',async()=>{
    const r=await runtime({path:'/account',certificateAccess});
    assert.equal(walk(r.root).some(node=>node.tag==='a'&&node.attrs.href==='/certificates'),true);
    assert.equal(walk(r.root).some(node=>node.tag==='a'&&node.attrs.href==='/admin'),false);
    assert.deepEqual(r.calls.map(row=>row.path),['/api/auth/me','/api/self-certificates/access']);
  });
}
