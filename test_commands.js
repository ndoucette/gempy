const assert=require('node:assert/strict');
const {test}=require('node:test');
const {ConsoleState,validateCommand,pacificTime}=require('./static/commands.js');
const hero={session_id:'11:22',bridge_generation:'generation-1',character:'Hero',realm:'prime',ready:true};
const mage={session_id:'33:44',bridge_generation:'generation-2',character:'Mage',realm:'test',ready:true};
test('selection binds generation and does not inherit reconnects or new logins',()=>{
 const c=new ConsoleState();c.roster([hero]);c.select(hero);c.roster([{...hero,bridge_generation:'new'},mage]);
 assert.equal(c.recipients()[0].available,false);assert.equal(c.targets.size,1);
 assert.equal(c.recipients()[0].bridge_generation,'generation-1');
 c.roster([]);assert.equal(c.targets.size,1);
});
test('all online snapshots eligible sessions in both realms and leaves exclusions explicit',()=>{
 const c=new ConsoleState();c.roster([hero,mage,{...hero,session_id:'55:66',ready:false,reason:'Check-in controlled'}]);
 c.all();assert.equal(c.targets.size,2);assert.equal(c.excluded().length,1);
 c.roster([hero,mage,{...mage,session_id:'77:88'}]);assert.equal(c.targets.size,2);
});
test('single literal line validates UTF-8 and control characters without normalization',()=>{
 for(const value of ['', ' ', 'look\n', 'look\t', 'look\x00', 'look\x7f','look\x85','é'.repeat(513)])assert.ok(validateCommand(value));
 assert.equal(validateCommand('  ;pause  all;look  '),'');assert.equal(validateCommand('é'.repeat(512)),'');
});
test('submission locks duplicate requests and retains selected tuples after acceptance',async()=>{
 let release;const calls=[];const api=async(path,method,body)=>{calls.push([path,body]);if(path.endsWith('/prepare'))return {request_id:'id',admission_token:'token'};return new Promise(r=>release=r)};
 const c=new ConsoleState();c.roster([hero]);c.select(hero);c.command=' ;pause  all';
 const pending=c.send(api);await new Promise(r=>setImmediate(r));await c.send(api);
 assert.equal(calls.length,2);assert.equal(calls[1][1].command,' ;pause  all');assert.equal(calls[1][1].targets[0].ready,undefined);
 release({request_id:'id',command:c.command,accepted_at:1,targets:[{...hero,state:'sending'}]});await pending;
 assert.equal(c.command,'');assert.equal(c.targets.size,1);assert.equal(c.pending,null);
});
test('ambiguous acceptance only looks up original ID and keeps draft until receipt',async()=>{
 const calls=[];let found=false;
 const api=async(path)=>{calls.push(path);if(path.endsWith('/prepare'))return {request_id:'original',admission_token:'token'};
 if(path==='command-batches')throw Error('Network lost');
 if(!found)throw Object.assign(Error('not found'),{status:404});
 return {request_id:'original',command:'look',accepted_at:1,targets:[{...hero,state:'unconfirmed'}]};};
 const c=new ConsoleState();c.roster([hero]);c.select(hero);c.command='look';await c.send(api);
 assert.equal(c.command,'look');assert.equal(c.pending.request_id,'original');await c.send(api);await c.resolve(api);
 found=true;await c.resolve(api);assert.equal(c.command,'');assert.equal(c.pending,null);
 assert.equal(calls.filter(p=>p==='command-batches').length,1);assert.equal(calls.filter(p=>p.endsWith('/prepare')).length,1);
});
test('validation rejection retains draft and allows a corrected explicit send',async()=>{
 const c=new ConsoleState();c.roster([hero]);c.select(hero);c.command='look';
 await c.send(async p=>p.endsWith('/prepare')?{request_id:'id'}:Promise.reject(Object.assign(Error('invalid'),{status:400})));
 assert.equal(c.command,'look');assert.equal(c.pending,null);assert.equal(c.error,'invalid');
});
test('history recall only fills command and not-sent selection requires original identity',()=>{
 const c=new ConsoleState();c.roster([hero,{...mage,bridge_generation:'replacement'}]);
 c.history=[{command:'look',targets:[{...hero,state:'not_sent'},{...mage,state:'not_sent'},{...hero,session_id:'55:66',state:'unconfirmed'}]}];
 c.use(c.history[0]);assert.equal(c.command,'look');assert.equal(c.targets.size,0);
 c.selectNotSent(c.history[0]);assert.deepEqual([...c.targets.keys()],['11:22']);
 c.history=Array.from({length:25},(_,i)=>({command:String(i)})).concat([{command:'1'}]);assert.equal(c.recentCommands().length,20);
});
test('leaving Live and logout clear target/draft and ignore late acceptance',async()=>{
 let release;const c=new ConsoleState();c.roster([hero]);c.select(hero);c.command='look';
 const running=c.send(async p=>p.endsWith('/prepare')?{request_id:'id'}:new Promise(r=>release=r));
 await new Promise(r=>setImmediate(r));c.reset();release({request_id:'id',command:'look',targets:[]});await running;
 assert.equal(c.targets.size,0);assert.equal(c.command,'');assert.equal(c.pending,null);
});
test('Pacific timestamps show date and daylight/standard time independently of browser zone',()=>{
 assert.match(pacificTime(Date.parse('2026-07-01T12:00:00Z')/1000),/Jul 1, 2026.*5:00.*PDT/);
 assert.match(pacificTime(Date.parse('2026-12-01T12:00:00Z')/1000),/Dec 1, 2026.*4:00.*PST/);
});
test('preparation freezes recipient and history actions before POST acceptance',async()=>{
 let admit;const c=new ConsoleState();c.roster([hero,mage]);c.select(hero);c.command='look';
 const run=c.send(async path=>path.endsWith('/prepare')?new Promise(r=>admit=r):({request_id:'id',command:'look',targets:[]}));
 c.select(mage);c.all();c.use({command:'quit'});c.selectNotSent({command:'exit',targets:[{...mage,state:'not_sent'}]});
 assert.deepEqual([...c.targets.keys()],['11:22']);assert.equal(c.command,'look');
 admit({request_id:'id'});await run;
});
