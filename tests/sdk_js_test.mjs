import assert from 'node:assert/strict';
import { PulseXClient, PulseXError } from '../sdk/javascript/index.mjs';

const calls=[];
const fakeFetch=async (url,opts={})=>{
  calls.push({url,opts});
  if(url.endsWith('/api/auth/login')) return {ok:true,status:200,json:async()=>({user:{id:'u1'},csrf:'csrf-js'})};
  if(url.endsWith('/api/admin/sites')) return {ok:true,status:200,json:async()=>({sites:[]})};
  if(url.endsWith('/api/admin/sites/agency-01/devices') && opts.method==='GET') return {ok:true,status:200,json:async()=>({devices:[]})};
  return {ok:true,status:200,json:async()=>({status:'ok'})};
};
const c=new PulseXClient({baseUrl:'http://localhost:4310',fetchImpl:fakeFetch});
const u=await c.login('a@example.test','password-long-enough');
assert.equal(u.id,'u1');
assert.equal(c.csrf,'csrf-js');
assert.deepEqual(await c.adminSites(),{sites:[]});
assert.equal(calls[0].opts.method,'POST');
assert.deepEqual(await c.devices('agency-01'),{devices:[]});
console.log(JSON.stringify({status:'passed',checks:5}));
