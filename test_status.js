const assert = require('node:assert/strict');
const {test} = require('node:test');
const status = require('./static/status.js');
const accounts = {Main: ['Hero', 'New'], Utility: ['Mage']};
const profiles = [
  {character:'hero', realm:'prime', snapshot:{character:{level:100,profession:'Paladin'}, resources:{weekly:25000,max_weekly:50000,total:0,suffused:123}, wealth:{bank_balance:0,deeds:1}, bonuses:{lumnis_stage:3,lumnis_reset_at:2000,fashlonae_state:'expended'}}},
  {character:'Mage', realm:'prime', snapshot:{character:{level:80,profession:'Wizard'},resources:{weekly:100,max_weekly:100}, bonuses:{lumnis_stage:'ready',fashlonae_state:'unavailable'}}},
  {character:'Hero', realm:'test', snapshot:{wealth:{bank_balance:999}}},
  {character:'Retired', realm:'prime', snapshot:{}}
];
test('configured rows include unreported characters and isolate realms',()=>{
  const rows=status.rows(accounts,profiles,'prime',1000);
  assert.deepEqual(rows.map(r=>r.name),['Hero','New','Mage']);
  assert.equal(rows[0].account,'Main'); assert.equal(rows[0].bank,0);
  assert.equal(rows[1].bank,null);assert.equal(rows[0].weekly,0.5);
  assert.equal(rows[0].suffused,123);assert.equal(rows[0].total,0);
});
test('Lumnis countdown, active multiplier, ready and passed reset',()=>{
  let row=status.rows(accounts,profiles,'prime',1000)[0];
  assert.equal(row.reset,1000);assert.equal(row.active,3);assert.equal(row.tutelage,true);
  row=status.rows(accounts,profiles,'prime',2100)[0];
  assert.equal(row.reset,0);assert.equal(row.active,null);
  row=status.rows(accounts,profiles,'prime',1000)[2];
  assert.equal(row.reset,0);assert.equal(row.active,0);assert.equal(row.tutelage,false);
});
test('missing values sort last both ways, numeric sort and stable name tiebreak',()=>{
  const rows=status.rows(accounts,profiles,'prime',1000);
  for(const dir of [1,-1]){
    const sorted=status.select(rows,{},'level',dir);
    assert.equal(sorted.at(-1).name,'New');
    assert.equal(sorted[0].name,dir===1?'Mage':'Hero');
  }
  assert.deepEqual(status.select(rows,{},'weekly',1).map(r=>r.name),['Mage','Hero','New']);
  assert.deepEqual(rows.map(r=>r.name),['Hero','New','Mage']);
});
test('composable search, account, profession and bonus filters',()=>{
  const rows=status.rows(accounts,profiles,'prime',1000);
  assert.equal(status.select(rows,{query:'wizard'})[0].name,'Mage');
  assert.equal(status.select(rows,{query:'main',account:'Main',profession:'Paladin',lumnis:'active',tutelage:'yes'}).length,1);
  assert.equal(status.select(rows,{lumnis:'ready',tutelage:'no'})[0].name,'Mage');
  assert.equal(status.select(rows,{lumnis:'unknown'})[0].name,'New');
});
test('column contract preserves all twelve requested columns',()=>{
  assert.deepEqual(status.columns.map(c=>c[1]),['Name','Level','Account','Profession','Lumnis Reset','Lumnis Active','Weekly Resource Cap Progress','Tutelage','Total Resource','Suffused Resource','Bank Balance','Deeds']);
});
test('newer active report invalidates an obsolete reset date',()=>{
  const profile={character:'Hero',realm:'prime',snapshot:{bonuses:{lumnis_stage:3,lumnis_reset_at:1000}},field_observed_at:{bonuses:{lumnis_stage:2000}}};
  const row=status.rows({Main:['Hero']},[profile],'prime',2100)[0];
  assert.equal(row.active,3);assert.equal(row.reset,null);
  assert.equal(status.select([row],{lumnis:'ready'}).length,0);
});
test('numeric range filters combine with account filters and preserve zero',()=>{
  const rows=status.rows(accounts,profiles,'prime',1000);
  assert.equal(status.select(rows,{rangeField:'level',rangeMin:'90',rangeMax:'100'})[0].name,'Hero');
  assert.equal(status.select(rows,{rangeField:'weekly',rangeMax:'0'})[0].name,'Mage');
  assert.equal(status.select(rows,{rangeField:'bank',rangeMax:'0'})[0].name,'Hero');
  assert.equal(status.select(rows,{account:'Utility',rangeField:'level',rangeMin:'90'}).length,0);
});

test('weekly progress resets for ready Lumnis and elapsed resets without changing stored balances',()=>{
  const ready=status.rows(accounts,profiles,'prime',1000)[2];
  assert.equal(ready.earned,0);assert.equal(ready.weekly,0);
  const elapsed=status.rows(accounts,profiles,'prime',2100)[0];
  assert.equal(elapsed.earned,0);assert.equal(elapsed.weekly,0);
  assert.equal(elapsed.total,0);assert.equal(elapsed.suffused,123);
  assert.equal(profiles[0].snapshot.resources.weekly,25000);
  const resumed={...profiles[0],field_observed_at:{bonuses:{lumnis_stage:2050}}};
  assert.equal(status.rows(accounts,[resumed],'prime',2100)[0].earned,25000);
});
test('same-scope pending loads coalesce; invalidation discards old responses',async()=>{
  const pending=[],applied=[];
  const loader=status.createLoader(scope=>new Promise(resolve=>pending.push({scope,resolve})),(data)=>applied.push(data),()=>{});
  const first=loader.load('prime');
  assert.equal(loader.load('prime'),first);
  await Promise.resolve();assert.equal(pending.length,1);
  pending[0].resolve('prime result');await first;
  assert.deepEqual(applied,['prime result']);
  const old=loader.load('prime');await Promise.resolve();loader.invalidate();
  const newer=loader.load('test');await Promise.resolve();
  pending[2].resolve('test result');await newer;pending[1].resolve('old prime');await old;
  assert.deepEqual(applied,['prime result','test result']);
});
