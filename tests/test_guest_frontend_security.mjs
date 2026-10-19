import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile(new URL('../web/guest.mjs',import.meta.url),'utf8');
const number='G-'+'A1'.repeat(15);
const goodManifest=()=>({event_id:'event-a',credential_version:2,generated_at:new Date().toISOString(),manifest_version:'v1',access_policy_version:'p1',access_control:{manifest_max_age_minutes:60},guests:[{guest_number:number,status:'registered'}]});

async function runtime(){
  const records=new Map();
  const key=(store,id)=>store+':'+id;
  const offline={get:async(store,id)=>records.get(key(store,id)),put:async(store,value)=>records.set(key(store,value.id),value),del:async(store,id)=>records.delete(key(store,id)),all:async store=>[...records].filter(([k])=>k.startsWith(store+':')).map(([,v])=>v),bundle:()=>{throw Error('public bundle must not be used for device context');},status:async()=>({}),activate:()=>{}};
  const ui={h:()=>({}),root:{},api:()=>{},field:()=>{},selectField:()=>{},check:()=>{},button:()=>{},toast:()=>{},brand:()=>{}};
  let handler=async()=>{throw TypeError('offline');};
  const context=vm.createContext({URL,Date,console,location:{origin:'https://test.example'},navigator:{onLine:true},fetch:(...args)=>handler(...args)});
  const module=new vm.SourceTextModule(source,{context});
  await module.link(specifier=>{const exports=specifier==='./ui.mjs'?ui:offline;return new vm.SyntheticModule(Object.keys(exports),function(){for(const [name,value]of Object.entries(exports))this.setExport(name,value);},{context});});
  await module.evaluate();
  return{api:module.namespace,offline,setFetch(fn){handler=fn;}};
}

test('QR parser accepts exact new passes and canonical URLs only',async()=>{
  const {api}=await runtime();
  assert.equal(api.parseGuestNumber(number),number);
  assert.equal(api.parseGuestNumber(number.toLowerCase()),number);
  assert.equal(api.parseGuestNumber('https://test.example/e/demo/guest/'+number),number);
  for(const input of ['G-1111-2222-3333-4444','P-1111-2222-3333-4444','prefix '+number,number+'F','javascript:'+number,'https://test.example/e/demo/guest/'+number+'/extra','https://test.example/anything/'+number])assert.equal(api.parseGuestNumber(input),'',input);
});

test('manifest validity depends on server generation time and credential version',async()=>{
  const {api}=await runtime();
  assert.equal(api.manifestReadiness(goodManifest()).valid,true);
  for(const change of [{credential_version:1},{generated_at:new Date(Date.now()-61*60000).toISOString(),cached_at:new Date().toISOString()},{generated_at:new Date(Date.now()+6*60000).toISOString()},{generated_at:'invalid'},{access_policy_version:''},{guests:[{guest_number:'G-1111-2222-3333-4444'}]}])assert.equal(api.manifestReadiness({...goodManifest(),...change}).valid,false);
});

test('controlled invitations fail closed offline while unmanaged valid records remain provisional',async()=>{
  const {api}=await runtime();
  assert.equal(api.localManifestDecision({...goodManifest(),requires_online:true},{},false).reason,'ADMISSION_ONLINE_REQUIRED');
  assert.equal(api.localManifestDecision({...goodManifest(),offline:true},{admission_managed:true},true).reason,'ADMISSION_ONLINE_REQUIRED');
  assert.equal(api.localManifestDecision(goodManifest(),{},false).status,'valid');
  assert.equal(api.localManifestDecision({...goodManifest(),requires_online:true},{},true).status,'valid');
});

test('offline manifest cannot outlive or precede device shift even while otherwise fresh',async()=>{
  const {api}=await runtime();
  const at=Date.now();
  const active={...goodManifest(),device_valid_from:new Date(at-60000).toISOString(),device_valid_until:new Date(at+60000).toISOString()};
  assert.equal(api.manifestReadiness(active,at).valid,true);
  assert.equal(api.manifestReadiness(active,at+60000).reason,'DEVICE_SHIFT_CLOSED');
  assert.equal(api.manifestReadiness(active,at-60001).reason,'DEVICE_SHIFT_CLOSED');
  assert.equal(api.manifestReadiness({...active,device_valid_until:'bad-time'},at).reason,'DEVICE_SHIFT_INVALID');
});

test('device checkpoint scope distinguishes deny-all from legacy unrestricted',async()=>{
  const {api}=await runtime();
  assert.equal(api.localManifestDecision({...goodManifest(),allowed_checkpoints:[]},{},false,'main').reason,'DEVICE_CHECKPOINT_SCOPE');
  assert.equal(api.localManifestDecision({...goodManifest(),allowed_checkpoints:['vip']},{},false,'main').reason,'DEVICE_CHECKPOINT_SCOPE');
  assert.equal(api.localManifestDecision({...goodManifest(),allowed_checkpoints:['vip']},{},false,'vip').status,'valid');
  assert.equal(api.localManifestDecision(goodManifest(),{},false,'main').status,'valid');
  assert.equal(api.localManifestDecision({...goodManifest(),allowed_checkpoints:null},{},false,'main').status,'valid');
});

for(const status of [401,403])test('HTTP '+status+' deletes cached manifest and never falls back',async()=>{
  const {api,offline,setFetch}=await runtime();
  await offline.put('guest_manifests',{id:'event-a',data:goodManifest(),token:'token-a'});
  setFetch(async()=>({ok:false,status}));
  const result=await api.loadManifest('event-a','token-a');
  assert.equal(result.blocked,true);
  assert.equal(result.error,'MANIFEST_HTTP_'+status);
  assert.equal(await offline.get('guest_manifests','event-a'),undefined);
});

test('network outage permits only fresh cache bound to the current device token',async()=>{
  const {api,offline}=await runtime();
  await offline.put('guest_manifests',{id:'event-a',data:goodManifest(),token:'token-a'});
  assert.equal((await api.loadManifest('event-a','token-a')).offline,true);
  assert.equal((await api.loadManifest('event-a','token-b')).blocked,true);
  await offline.put('guest_manifests',{id:'event-a',data:{...goodManifest(),generated_at:new Date(Date.now()-61*60000).toISOString()},token:'token-a'});
  assert.equal((await api.loadManifest('event-a','token-a')).error,'MANIFEST_EXPIRED');
});

test('private scanner context uses scoped device endpoint and clears cache after denial',async()=>{
  const {api,offline,setFetch}=await runtime();
  setFetch(async(path,options)=>{assert.equal(path,'/api/device/events/by-slug/private/gate-context');assert.equal(options.headers['X-PulseX-Device-Token'],'token-a');return{ok:true,json:async()=>({event_id:'event-a',slug:'private',title:'Private event'})};});
  const page=await api.gateContext('private','token-a');
  assert.equal(page.id,'event-a');
  assert.equal(page.config.title,'Private event');
  await offline.put('guest_manifests',{id:'event-a',data:goodManifest(),token:'token-a'});
  setFetch(async()=>({ok:false,status:403}));
  assert.equal((await api.gateContext('private','token-a')).blocked,true);
  assert.equal(await offline.get('bundles','gate-context:private'),undefined);
  assert.equal(await offline.get('guest_manifests','event-a'),undefined);
});
