import assert from 'node:assert/strict';
import {orderedRecords,moveRecord,validateQuestionOrder,STORYBOARD_PAGE_SIZE} from '../web/storyboard-core.mjs';

const base = [
 {code:'b',kind:'service',title:'B',order:10,media:'private.png',enabled:true},
 {code:'a',kind:'question',form_id:'main',title:'Anchor',order:1,show_if:null,enabled:true},
 {code:'c',kind:'question',form_id:'main',title:'Conditional',order:11,show_if:{code:'a',equals:'yes'},enabled:true},
 {code:'d',kind:'poll',order:12,poll_style:'secret',show_results:false}
];
assert.equal(STORYBOARD_PAGE_SIZE,25);
assert.deepEqual(orderedRecords(base).map(r=>r.code),['a','b','c','d']);
const copy=structuredClone(base);
const move=moveRecord(base,1,3);
assert.deepEqual(move.map(r=>r.code),['a','c','d','b']);
assert.deepEqual(move.map(r=>r.order),[1,2,3,4]);
assert.equal(move[2].poll_style,'secret');
assert.equal(move[2].show_results,false);
assert.deepEqual(base,copy,'must not mutate original draft');
assert.equal(validateQuestionOrder(move),true);
assert.throws(()=>moveRecord(base,0,3),/BRANCH_MUST_REFERENCE_EARLIER_QUESTION_IN_FORM/);
assert.throws(()=>moveRecord(base,-1,0),RangeError);
assert.throws(()=>moveRecord(base,0,4),RangeError);
assert.throws(()=>moveRecord(base,0,0.5),RangeError);
const equal=[{code:'x',order:2},{code:'y',order:2},{code:'z',order:1}];
assert.deepEqual(orderedRecords(equal).map(r=>r.code),['z','x','y']);
assert.equal(moveRecord(equal,1,2)[1].code,'y');
assert.throws(()=>orderedRecords({}),/INVALID_STORYBOARD_RECORDS/);
assert.throws(()=>orderedRecords(Array(2001).fill({})),/INVALID_STORYBOARD_RECORDS/);
console.log('STORYBOARD_CORE_PASS');
