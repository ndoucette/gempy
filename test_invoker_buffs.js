const {test} = require('node:test');
const assert = require('node:assert/strict');
const buffs = require('./static/invoker-buffs.js');

const now = 1800000000;
const names = ['Natural Colors', 'Resist Elements', 'Mobility', 'Mass Blur', 'Foresight'];
const effect = (name, seconds) => ({name, end_time:now + seconds});
function session(spells=names.map(name=>effect(name,7200)), extra={}) {
  return {running:true, telemetry:{status:'fresh', received_at:new Date(now*1000).toISOString(),
    snapshot:{character:{profession:'Sorcerer'}, skills:{sorcerer:{ranks:100,category:'spell_research'}},
      collected_at:now, effects:{spells, buffs:[]}, ...extra}}};
}
const evaluate = (s, nextIn=3600, options={}) => buffs.evaluate(s,{nextIn,remaining:0},{now,...options});

test('selects stable markers from learned ranks, regardless of active effects',()=>{
  const s=session();
  assert.deepEqual(buffs.markers(s.telemetry.snapshot).map(x=>x.name),names);
  s.telemetry.snapshot.skills={ranger:{ranks:18},minor_mental:{ranks:4}};
  assert.deepEqual(buffs.markers(s.telemetry.snapshot).map(x=>x.name),
    ['Mass Blur','Mindward',"Thurfel's Ward",'Strength']);
  s.telemetry.snapshot.effects.spells=[];
  assert.deepEqual(buffs.markers(s.telemetry.snapshot).map(x=>x.name),
    ['Mass Blur','Mindward',"Thurfel's Ward",'Strength']);
});

test('profession fallback excludes possible self casts when ranks are unavailable',()=>{
  const data={character:{profession:'Wizard'}};
  assert.deepEqual(buffs.markers(data).map(x=>x.name),
    ['Natural Colors','Resist Elements','Mobility','Foresight','Mindward']);
  assert.equal(buffs.markers({}).length,0);
});

test('earliest selected expiry controls coverage and two-hour spells are ignored',()=>{
  const s=session([...names.map(name=>effect(name,7200)),effect('Spirit Defense',10),effect('Mantle of Faith',1)]);
  s.telemetry.snapshot.effects.spells[0].end_time=now+5000;
  const result=evaluate(s);
  assert.equal(result.remaining,5000);
  assert.equal(result.state,'covered');
  assert.equal(result.mixed,true);
  assert.equal(result.markers.length,5);
});

test('gap and five-minute buffer boundaries produce actionable coverage',()=>{
  const s=session(names.map(name=>effect(name,1920)));
  assert.equal(evaluate(s,3600).gap,1680);
  assert.equal(evaluate(s,3600).state,'gap');
  assert.equal(evaluate(s,1620).state,'covered');
  assert.equal(evaluate(s,1621).state,'gap');
  assert.equal(evaluate(s,1621).gap,0);
  assert.equal(evaluate(s,1621).shortfall,1);
});

test('spellburst-trimmed spellups use surviving markers without a partial warning',()=>{
  const result=evaluate(session(names.slice(0,3).map(name=>effect(name,7200))));
  assert.equal(result.state,'covered');
  assert.equal(result.remaining,7200);
  assert.equal(result.markers.filter(x=>x.status==='missing').length,2);
  assert.equal(evaluate(session([])).state,'missing');
  assert.equal(evaluate(session(names.map(name=>effect(name,0)))).state,'missing');
  assert.equal(evaluate(session(names.slice(0,3).map(name=>effect(name,1800)))).state,'gap');
});

test('Cragstone: dropping Mass Blur leaves a valid renewal estimate from four markers',()=>{
  const spells=names.filter(name=>name!=='Mass Blur').map(name=>effect(name,12508));
  const s=session(spells,{character:{profession:'Paladin'},skills:{paladin:{ranks:50},minor_spiritual:{ranks:40}}});
  const result=evaluate(s);
  assert.equal(result.state,'covered');
  assert.equal(result.remaining,12508);
  assert.equal(result.markers.find(x=>x.name==='Mass Blur').status,'missing');
});

test('Prepotente: a lone Mass Blur alongside renewing songs is not an invoker spellup',()=>{
  const spells=[effect('Mass Blur',6402),effect('Fortitude Song',130),effect('Song of Luck',130),
    effect("Kai's Triumph Song",130),effect('Song of Valor',130),effect('Song of Mirrors',130),
    {name:'Divine Shield'}];
  const s=session(spells,{character:{profession:'Bard'},skills:{bard:{ranks:100},minor_elemental:{ranks:75}}});
  const result=evaluate(s);
  assert.equal(result.state,'missing');
  assert.equal(result.remaining,null);
  assert.equal(result.markers.find(x=>x.name==='Mass Blur').remaining,6402);
  assert.equal(result.markers.filter(x=>x.status==='active').length,1);
});

test('requires three marker spells before assigning a spellup renewal timer',()=>{
  for(const count of [1,2]) {
    const result=evaluate(session(names.slice(0,count).map(name=>effect(name,7200))));
    assert.equal(result.state,'missing');
    assert.equal(result.remaining,null);
  }
  assert.equal(evaluate(session(names.slice(0,3).map(name=>effect(name,7200)))).state,'covered');
});

test('unavailable, stale and aged-out reports never assert missing or covered',()=>{
  for(const effects of [null,{}, {spells:null}]) assert.equal(evaluate(session([],{effects})).state,'unknown');
  const s=session();s.telemetry.status='stale';
  assert.equal(evaluate(s).state,'unknown');
  s.telemetry.status='fresh';
  assert.equal(evaluate(s,3600,{now:now+21,staleSeconds:20}).state,'unknown');
  s.running=false;
  assert.equal(evaluate(s).state,'unknown');
});

test('a missing timer is unknown, not absent, and relative timers use collection time',()=>{
  const s=session([{name:'Natural Colors'}]);
  assert.equal(evaluate(s).state,'unknown');
  s.telemetry.snapshot.effects.spells=names.map(name=>({name,remaining_seconds:7200}));
  assert.equal(evaluate(s,3600,{now:now+10}).remaining,7190);
  s.telemetry.snapshot.effects.spells[0].end_time=NaN;
  assert.equal(evaluate(s).remaining,7200);
});

test('normalizes effect names and can find a marker in the buffs category',()=>{
  const s=session(names.slice(1).map(name=>effect(name,7200)));
  s.telemetry.snapshot.effects.buffs=[effect(' natural   COLORS ',5000)];
  assert.equal(evaluate(s).remaining,5000);
  assert.equal(evaluate(s).state,'covered');
});

test('a current scheduled visit is usable only when the travel buffer fits',()=>{
  const s=session(names.map(name=>effect(name,600)));
  const at = remaining=>buffs.evaluate(s,{remaining,nextIn:7200},{now});
  assert.equal(at(301).state,'covered');
  assert.equal(at(301).visitNow,true);
  assert.equal(at(300).state,'gap');
  assert.equal(at(300).visitNow,false);
  assert.equal(at(0).gap,6600);
});

test('missing schedule prevents a green recommendation without hiding the timer',()=>{
  const result=buffs.evaluate(session(),{}, {now});
  assert.equal(result.state,'unknown');
  assert.equal(result.remaining,7200);
});

test('duration stays readable at expiry and does not overstate remaining minutes',()=>{
  assert.equal(buffs.duration(1),'<1m');
  assert.equal(buffs.duration(3599),'59m');
  assert.equal(buffs.duration(7200),'2h');
  assert.equal(buffs.duration(8280),'2h 18m');
  assert.equal(buffs.duration(0),'0m');
});
