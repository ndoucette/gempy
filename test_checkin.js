const test=require('node:test');
const assert=require('node:assert/strict');
const ci=require('./static/checkin.js');

test('counts keep failures and blocked jobs out of completed progress',()=>{
  const result=ci.counts([{status:'complete'},{status:'partial'},{status:'waiting'},{status:'capturing'},{status:'queued'}]);
  assert.deepEqual(result,{total:5,complete:1,active:1,waiting:1,queued:1,attention:1,cancelled:0});
});
test('account grouping preserves queue order and identifies current character',()=>{
  const rows=ci.accounts([{id:'1',account:'a',account_label:'A',character:'First',status:'complete'},
    {id:'2',account:'a',account_label:'A',character:'Second',status:'capturing'},
    {id:'3',account:'b',account_label:'B',character:'Third',status:'waiting'}]);
  assert.equal(rows.length,2);assert.equal(rows[0].current.character,'Second');assert.equal(rows[0].counts.complete,1);
});
test('demo is explicitly local and internally consistent',()=>{
  const state=ci.demo();assert.equal(state.preview,true);assert.equal(state.run.jobs.length,24);
  assert.deepEqual(ci.counts(state.run.jobs),{total:24,complete:16,active:3,waiting:1,queued:4,attention:0,cancelled:0});
});
test('unknown status stays visible instead of being counted complete',()=>{
  assert.equal(ci.label('future_state'),'Unknown state');assert.equal(ci.counts([{status:'future_state'}]).attention,1);
});
