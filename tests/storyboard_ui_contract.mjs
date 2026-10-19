/** Isolated DOM-like contract, not Playwright/real-browser or OS acceptance. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {orderedRecords,moveRecord,STORYBOARD_PAGE_SIZE} from '../web/storyboard-core.mjs';

const body=readFileSync(new URL('../web/storyboard.mjs',import.meta.url),'utf8')
  .replace(/^import .*?;\s*$/gm,'')
  .replace('export function storyboard', 'function storyboard');
const makeNode=(tag,attrs={},children=[])=>({tag,attrs,children,handlers:{},isConnected:true,
  textContent:'',disabled:false,append(...nodes){this.children.push(...nodes);},
  replaceChildren(...nodes){this.children=nodes;},addEventListener(name,fn){this.handlers[name]=fn;}});
const h=(tag,attrs={},...children)=>makeNode(tag,attrs,children);
const button=(label,fn)=>Object.assign(makeNode('button',{},[label]),{label,click:fn});
let toasts=[];
const context={h,button,toast:(value)=>toasts.push(value),msg:e=>e.message,
  labels:{service:'الخدمات',question:'الأسئلة',poll:'التصويت'},orderedRecords,moveRecord,STORYBOARD_PAGE_SIZE};
runInNewContext(body+'\nthis.storyboard=storyboard;',context);
const host=makeNode('main');
const current={draft_rev:1,draft:{records:[
  {kind:'service',code:'a',title:'أ',order:1,enabled:true},
  {kind:'service',code:'b',title:'ب',order:2,enabled:true},
  {kind:'poll',code:'c',title:'ج',order:3,show_results:false,poll_style:'secret',enabled:true},
]}};
let saves=0,rejectNext=false;
async function saveDraft(){saves++;if(rejectNext){rejectNext=false;throw Object.assign(new Error('DRAFT_CHANGED_REFRESH_REQUIRED'),{status:409});}current.draft_rev++;}
context.storyboard({host,current,saveDraft});
const panel=host.children[0],list=panel.children[2],status=panel.children[1];
assert.equal(list.children.length,3);
assert.deepEqual(current.draft.records.map(r=>r.code),['a','b','c']);
await list.children[0].children[2].children[1].click();
assert.equal(current.draft_rev,2);
assert.equal(saves,1);
assert.deepEqual(current.draft.records.map(r=>r.code),['b','a','c']);
assert.equal(current.draft.records[2].poll_style,'secret');
rejectNext=true;
await list.children[2].children[2].children[0].click();
assert.equal(saves,2);
assert.deepEqual(current.draft.records.map(r=>r.code),['b','a','c'],'failed save must roll back');
assert.match(status.textContent,/أعد تحميل المسودة/);
const dnd={setData(k,v){this.value=v;},getData(){return this.value;},effectAllowed:'',dropEffect:''};
list.children[2].handlers.dragstart({dataTransfer:dnd,preventDefault(){}});
list.children[0].handlers.drop({preventDefault(){},dataTransfer:dnd});
await new Promise(setImmediate);
assert.deepEqual(current.draft.records.map(r=>r.code),['c','b','a']);
assert.equal(saves,3);
// Conditionals cannot precede their anchor, without sending an invalid draft.
const host2=makeNode('main');const conditional={draft:{records:[
  {kind:'question',code:'parent',title:'Parent',form_id:'main',order:1,show_if:null},
  {kind:'question',code:'child',title:'Child',form_id:'main',order:2,show_if:{code:'parent',equals:'yes'}},
]}};
let conditionalWrites=0;
context.storyboard({host:host2,current:conditional,saveDraft:async()=>{conditionalWrites++;}});
const secondList=host2.children[0].children[2];
await secondList.children[1].children[2].children[0].click();
assert.equal(conditionalWrites,0);
assert.match(host2.children[0].children[1].textContent,/السؤال المشروط/);
// A paginated editor can move the last item on a page into the next one by controls.
const more=makeNode('main'), many={draft:{records:Array.from({length:26},(_,i)=>({kind:'fact',code:'k'+i,title:'معلومة',order:i+1}))}};
context.storyboard({host:more,current:many,saveDraft:async()=>{}});
const list3=more.children[0].children[2];
assert.equal(list3.children.length,25);
await list3.children[24].children[2].children[1].click();
assert.equal(more.children[0].children[2].children.length,1);
console.log('STORYBOARD_UI_CONTRACT_PASS');
