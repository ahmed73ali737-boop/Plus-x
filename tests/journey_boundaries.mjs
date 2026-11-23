import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const read=name=>readFile(process.env.JOURNEY_WEB+'/'+name,'utf8');
test('worker ignores other mounts, APIs and mutations; media fallback is scoped',async()=>{
 const handlers={},opened=[],deleted=[];
 const cache={match:async()=>({local:true})};
 const context=vm.createContext({URL,self:{location:{origin:'https://host'},clients:{claim:async()=>{}},addEventListener:(n,f)=>handlers[n]=f},caches:{open:async n=>(opened.push(n),cache),keys:async()=>['px-shell-v1','other-cache','plusx-development-shell-old'],delete:async n=>deleted.push(n),match:()=>{throw Error('global cache lookup');}},fetch:async()=>{throw Error('offline');}});
 vm.runInContext(await read('sw.js'),context);
 for(const [path,method,mode] of [['/other/','GET','navigate'],['/plusx-other/','GET','navigate'],['/plusx/api/private','GET','navigate'],['/plusx/e/demo','POST','navigate']]){
  handlers.fetch({request:{url:'https://host'+path,method,mode},respondWith:()=>assert.fail(path)});
 }
 let response;
 handlers.fetch({request:{url:'https://host/plusx/media/a.png',method:'GET'},respondWith:p=>response=p});
 assert.ok((await response).local);assert.equal(opened.at(-1),'plusx-development-media-v02');
 let done;handlers.activate({waitUntil:p=>done=p});await done;
 assert.deepEqual(deleted,['plusx-development-shell-old']);
});
test('transformed scanner accepts mounted QR, rejects sibling paths and foreign origin',async()=>{
 const context=vm.createContext({URL,location:{origin:'https://host'},navigator:{onLine:true}});
 const module=new vm.SourceTextModule(await read('guest.mjs'),{context});
 await module.link(spec=>new vm.SyntheticModule(spec==='./ui.mjs'?['h','root','api','field','selectField','check','button','toast','brand']:['get','put','del','all','bundle','status','activate'],function(){},{context}));
 await module.evaluate();const parse=module.namespace.parseGuestNumber,n='G-'+'A1'.repeat(15);
 assert.equal(parse('https://host/plusx/e/demo/guest/'+n),n);
 for(const path of ['https://host/other/e/demo/guest/','https://evil/plusx/e/demo/guest/','https://host/plusx-other/e/demo/guest/'])assert.equal(parse(path+n),'');
});
test('storage names and platform share link are mount isolated',async()=>{
 assert.match(await read('offline.mjs'),/indexedDB.open\('plusx-development-pilot-02'/);
 assert.match(await read('offline.mjs'),/caches.open\('plusx-development-media-v02'/);
 assert.match(await read('admin.mjs'),/kind==='platform'\)return'\/plusx\/'/);
});
test('prepare remaps public media and rejects API, sibling, external and redirected responses',async()=>{
 const {IDBFactory}=await import('./offline-runtime/node_modules/fake-indexeddb/build/esm/index.js');
 const fetched=[],stored=[],names=[];
 const urls=['/media/a.png','https://host/media/b.png','/plusx/media/c.png','/api/private','/other/media/d.png','https://evil/media/e.png','/media/../api/private','/media/redirect.png'];
 const bundle={slug:'demo',agencies:[],config:{logo:urls[0],records:urls.slice(1).map(media=>({media}))}};
 const context=vm.createContext({URL,Date,Promise,setTimeout,indexedDB:new IDBFactory(),window:{isSecureContext:true},location:{origin:'https://host'},navigator:{serviceWorker:{register:async p=>assert.equal(p,'/plusx/sw.js'),ready:Promise.resolve()},storage:{}},caches:{open:async n=>(names.push(n),{put:async u=>stored.push(u)})},fetch:async u=>(fetched.push(u),{ok:true,redirected:u.endsWith('redirect.png')})});
 const module=new vm.SourceTextModule(await read('offline.mjs'),{context});
 await module.link(()=>new vm.SyntheticModule(['api','toast','download'],function(){this.setExport('api',async()=>bundle);},{context}));await module.evaluate();
 const result=await module.namespace.prepare(bundle);
 assert.equal(result.assets,3);assert.equal(result.missing.length,5);
 assert.deepEqual(stored,['https://host/plusx/media/a.png','https://host/plusx/media/b.png','https://host/plusx/media/c.png']);
 assert.equal(fetched.length,4);assert.deepEqual(names,['plusx-development-media-v02']);
});
