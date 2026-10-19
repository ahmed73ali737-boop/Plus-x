import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {IDBFactory} from './offline-runtime/node_modules/fake-indexeddb/build/esm/index.js';

// Execute the actual browser module against a deterministic IndexedDB model.
// These are JS runtime contracts, not browser/network outage or field tests.
const source=await readFile(new URL('../web/offline.mjs',import.meta.url),'utf8');
async function runtime({http=401,network=false,collect,onHeartbeat}={}){
  const window=new EventTarget();let events=0,calls=0;
  window.addEventListener('px-device-authorization-revoked',()=>events++);
  let api;
  const context=vm.createContext({indexedDB:new IDBFactory(),window,Event,CustomEvent,URL,URLSearchParams,Date,Promise,setTimeout,clearTimeout,console,
    navigator:{onLine:true,userAgent:'test'},location:{search:''},
    fetch:async path=>{
      if(path==='/api/health')return{ok:true,json:async()=>({version:'1.0.1'})};
      if(network)throw new TypeError('offline');
      if(onHeartbeat)await onHeartbeat(api);
      return{ok:http===200,status:http,json:async()=>({status:'ok'})};
    }});
  const ui={api:async(path,body)=>{calls++;return collect?collect(path,body,calls):{receipts:[]};},toast:()=>{},download:()=>{}};
  const module=new vm.SourceTextModule(source,{context});
  await module.link(()=>new vm.SyntheticModule(Object.keys(ui),function(){for(const [name,value]of Object.entries(ui))this.setExport(name,value);},{context}));
  await module.evaluate();api=module.namespace;
  return{api,events:()=>events,calls:()=>calls};
}
async function seed(api){
  await api.put('bundles',{id:'device-auth',data:{token:'revoked-token'}});
  await api.put('bundles',{id:'gate-context:event-a',token:'revoked-token',data:{event_id:'event-a'}});
  await api.put('guest_manifests',{id:'event-a',token:'revoked-token',data:{guests:[]}});
  await api.put('guest_manifests',{id:'event-b',token:'other-device-token',data:{guests:[]}});
  await api.put('checkin_outbox',{id:'pending-checkin',status:'pending',event_id:'event-a'});
  await api.put('outbox',{id:'pending-interaction',status:'pending',envelope:{id:'pending-interaction'}});
}
for(const http of [401,403])test('heartbeat '+http+' invalidates only denied device authority, preserving pending work',async()=>{
  const r=await runtime({http});await seed(r.api);
  const result=await r.api.deviceHeartbeat();
  assert.equal(result.authorization_failed,true);assert.equal(result.paired,false);assert.notEqual(result.offline,true);
  assert.equal(await r.api.get('bundles','device-auth'),undefined);
  assert.equal(await r.api.get('bundles','gate-context:event-a'),undefined);
  assert.equal(await r.api.get('guest_manifests','event-a'),undefined);
  assert.ok(await r.api.get('guest_manifests','event-b'));
  assert.ok(await r.api.get('checkin_outbox','pending-checkin'));
  assert.ok(await r.api.get('outbox','pending-interaction'));
  assert.equal(r.events(),1);
});
for(const setting of [{network:true},{http:500}])test('transport/server failure retains cached authority and pending work '+JSON.stringify(setting),async()=>{
  const r=await runtime(setting);await seed(r.api);const result=await r.api.deviceHeartbeat();
  assert.equal(result.offline,true);assert.equal(result.paired,true);
  assert.ok(await r.api.get('bundles','device-auth'));assert.ok(await r.api.get('guest_manifests','event-a'));
  assert.ok(await r.api.get('checkin_outbox','pending-checkin'));assert.equal(r.events(),0);
});
test('late denial for an old token must not erase a newly paired device',async()=>{
  const r=await runtime({http:401,onHeartbeat:async api=>{
    await api.put('bundles',{id:'device-auth',data:{token:'new-device'}});
    await api.put('guest_manifests',{id:'new-event',token:'new-device',data:{guests:[]}});
  }});await seed(r.api);await r.api.deviceHeartbeat();
  assert.equal((await r.api.get('bundles','device-auth')).data.token,'new-device');
  assert.ok(await r.api.get('guest_manifests','new-event'));assert.equal(await r.api.get('guest_manifests','event-a'),undefined);
  assert.equal(r.events(),0);
});
test('full batch with unrelated receipts stops without deleting or retry-spinning',async()=>{
  const r=await runtime({collect:async(path,body,calls)=>{if(calls>1)throw Error('retry spin detected');return{receipts:[{id:'not-in-batch',status:'accepted'}]};}});
  for(let i=0;i<50;i++)await r.api.put('outbox',{id:String(i),status:'pending',envelope:{id:String(i)}});
  await r.api.sync();assert.equal(r.calls(),1);assert.equal((await r.api.status()).pending,50);
});
test('accepted and duplicate receipts drain only matching items; rejection remains inspectable',async()=>{
  const r=await runtime({collect:async()=>({receipts:[{id:'a',status:'accepted'},{id:'b',status:'duplicate'},{id:'c',status:'rejected',error:'POLICY_DENIED'}]})});
  for(const id of ['a','b','c'])await r.api.put('outbox',{id,status:'pending',envelope:{id}});
  await r.api.sync();assert.equal(await r.api.get('outbox','a'),undefined);assert.equal(await r.api.get('outbox','b'),undefined);
  assert.equal((await r.api.get('outbox','c')).status,'rejected');assert.equal((await r.api.status()).rejected,1);
});
test('nonterminal/unknown receipts retain pending work',async()=>{
  const r=await runtime({collect:async()=>({receipts:[{id:'a',status:'pending'},{id:'b',status:'unexpected'}]})});
  for(const id of ['a','b'])await r.api.put('outbox',{id,status:'pending',envelope:{id}});
  await r.api.sync();assert.equal((await r.api.status()).pending,2);assert.equal((await r.api.status()).rejected,0);
});
test('storage cleanup failure still emits a fail-closed authorization denial',async()=>{
  const r=await runtime();await seed(r.api);const database=await r.api.db();const transaction=database.transaction.bind(database);
  database.transaction=(names,mode,...rest)=>{if(mode==='readwrite'&&Array.isArray(names)&&names.includes('guest_manifests'))throw Error('storage unavailable');return transaction(names,mode,...rest);};
  const result=await r.api.deviceHeartbeat();assert.equal(result.authorization_failed,true);assert.equal(result.cache_cleanup_failed,true);assert.equal(result.paired,false);assert.equal(r.events(),1);
});
