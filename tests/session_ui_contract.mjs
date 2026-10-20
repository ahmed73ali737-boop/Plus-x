/** A deliberate focused DOM contract, not real browser acceptance. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../web/admin.mjs',import.meta.url),'utf8');
const start=source.indexOf('function forcePasswordChange(){');
const end=source.indexOf('function loginPage(){',start);
assert.ok(start>=0 && end>start,'missing forced-reset UI function');
let authorized=false,revokeCalls=0,cleared=0;
const root={children:[],replaceChildren(...parts){this.children=parts;},append(...parts){this.children.push(...parts);}};
const h=(tag,attrs,...children)=>({tag,attrs,children,addEventListener(){}});
const button=(label,fn)=>({tag:'button',label,fn});
const ctx={root,h,button,passwordPair:()=>({node:{tag:'div'},password:{input:{value:''}},confirmation:{input:{value:''}}}),field:label=>({node:{tag:'input',label},input:{value:''}}),
  api:async(path,body)=>{assert.equal(path,'/api/auth/sessions/revoke-all');assert.equal(Object.keys(body).length,0);revokeCalls++;return{ok:true};},
  confirm:()=>authorized,location:{href:'initial'},setCSRF:()=>{cleared++;},
  toast:()=>{},msg:x=>x};
runInNewContext(source.slice(start,end)+'\nthis.forcePasswordChange=forcePasswordChange;',ctx);
ctx.forcePasswordChange();
const form=root.children[0].children.find(e=>e?.tag==='form');
assert.ok(form,'forced password form absent');
const revoke=form.children.find(e=>e?.tag==='button' && e.label==='إنهاء جميع الجلسات الآن');
assert.ok(revoke,'missing revoke action in forced-reset UI');
await revoke.fn();
assert.equal(revokeCalls,0,'cancel must not revoke sessions');
assert.equal(ctx.location.href,'initial');
authorized=true;
await revoke.fn();
assert.equal(revokeCalls,1);
assert.equal(cleared,1);
assert.equal(ctx.location.href,'/admin');
console.log('FORCE_RESET_SESSION_REVOKE_UI_PASS');
