import test from 'node:test';import assert from 'node:assert/strict';
import {knowledgeFor,systemPrompt,runAI,createApp} from '../server.mjs';
test('knowledge includes hotel for checkout',()=>assert.match(knowledgeFor([{role:'user',content:'Checkout kab hai?'}]),/Name: Hotel Ganga View/));
test('safety: no actions',()=>assert.match(systemPrompt('Check-out: 11 AM'),/CANNOT place or confirm orders/));
test('uses one direct provider call and conversation',async()=>{
 let seen;const fake=async(url,opts)=>{seen={url,body:JSON.parse(opts.body)};return {ok:true,json:async()=>({choices:[{message:{content:'Ji checkout 11 baje hai.'}}]})}};
 const result=await runAI({provider:'groq',apiKey:'test',messages:[{role:'user',content:'Checkout time?'}]},fake);
 assert.equal(result.status,200);assert.match(seen.url,/api.groq.com/);assert.equal(seen.body.messages.length,2)
});
test('quota returns explicit failure',async()=>{const result=await runAI({provider:'cohere',apiKey:'test',messages:[{role:'user',content:'hi'}]},async()=>({ok:false,status:429}));assert.equal(result.status,502);assert.match(result.error,/quota/)});
test('health never implies integrations',async()=>{const app=createApp();await new Promise(ok=>app.listen(0,ok));try{let j=await(await fetch('http://127.0.0.1:'+app.address().port+'/health')).json();assert.equal(j.whatsapp,false);assert.equal(j.sheets,false)}finally{await new Promise(ok=>app.close(ok))}});
