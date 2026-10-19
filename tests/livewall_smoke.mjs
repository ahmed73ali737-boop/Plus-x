/** Mock DOM contract only; native browser/venue acceptance is separate. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const raw=readFileSync(new URL('../web/livewall.mjs', import.meta.url),'utf8')
  .replace(/^import \{h, root, api, button\} from '\.\/ui\.mjs';\s*/m,'')
  .replace('export async function liveWallPage','async function liveWallPage');
const visible = {kind:'poll',code:'public-poll',title:'تصويت معتمد',enabled:true,show_results:true,options:[{key:'a',label:'الأول'}]};
const hidden = {kind:'poll',code:'hidden-poll',title:'تصويت غير منشور',enabled:true,show_results:false,options:[]};
const secret = {kind:'poll',code:'secret-poll',title:'تصويت سري',enabled:true,show_results:true,poll_style:'secret',options:[]};
const page = {version:1,config:{title:'اختبار المعرض',primary:'#176B73',records:[visible,hidden,secret]}};
const result = {version:1,as_of:'2026-10-14T07:00:00Z',polls:{'public-poll':{ballots:2,counts:{a:2}},'hidden-poll':{ballots:3,counts:{a:3}},'secret-poll':{ballots:4,counts:{a:4}}}};
let online=true, intervalCallback;
const h=(tag,attrs={},...children)=>({tag,attrs,children,textContent:'',replaceChildren(...next){this.children=next;}});
const root={nodes:[],replaceChildren(...next){this.nodes=next;}};
const document={hidden:false,title:'',body:{classList:{add(){}}},documentElement:{style:{setProperty(){}}},addEventListener(){}};
const window={addEventListener(){}};
async function api(path){if(!online)throw Error('disconnected');return path.endsWith('/results')?result:page;}
const context={h,root,api,button:(label)=>h('button',{},label),document,window,
  setInterval:fn=>(intervalCallback=fn,1),clearInterval:()=>{},
  Date,Number,String,Object,Set,Math,encodeURIComponent,Error};
runInNewContext(raw+'\nthis.liveWallPage=liveWallPage;',context);
await context.liveWallPage('agency-01');
let html=JSON.stringify(root.nodes);
assert.match(html,/تصويت معتمد/);
assert.doesNotMatch(html,/تصويت غير منشور|تصويت سري/);
page.config.records=[{...visible,show_results:false},hidden,secret];
await intervalCallback();
html=JSON.stringify(root.nodes);
assert.doesNotMatch(html,/تصويت معتمد/);
assert.match(html,/لا توجد نتائج معتمدة/);
page.config.records=[visible,hidden,secret];
online=false;
await intervalCallback();
html=JSON.stringify(root.nodes);
assert.match(html,/النتائج غير متاحة الآن/);
assert.doesNotMatch(html,/تصويت معتمد/);
console.log('LIVEWALL_CONTRACT_PASS');
