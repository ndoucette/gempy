/* Long-duration invoker markers only. Source: https://gswiki.play.net/Half-elven_invoker
 * Stable selection is independent of active effects: a dispel must not replace a marker.
 * This estimates coverage, not the identity of the caster (pills also qualify).
 */
const invokerBuffs = (() => {
  const candidates = [
    ['Natural Colors','ranger',1], ['Resist Elements','ranger',2], ['Mobility','ranger',18],
    ['Mass Blur','wizard',11], ['Foresight','minor_mental',4], ['Mindward','minor_mental',8],
    ["Thurfel's Ward",'major_elemental',3], ['Strength','major_elemental',9]
  ].map(([name,circle,rank])=>({name,circle,rank}));
  const professions = {
    ranger:['ranger'], wizard:['wizard','major_elemental'], monk:['minor_mental'],
    savant:['minor_mental'], warrior:[], rogue:[], bard:[], cleric:[], empath:[],
    sorcerer:[], paladin:[]
  };
  const normalize = name => String(name||'').trim().toLowerCase().replace(/[’']/g,'').replace(/\s+/g,' ');
  const finite = value => typeof value==='number'&&Number.isFinite(value);

  function markers(data) {
    const skills=data.skills, profession=String(data.character?.profession||'').toLowerCase();
    const hasRanks=!!skills&&typeof skills==='object'&&!Array.isArray(skills);
    if(!hasRanks&&!Object.hasOwn(professions,profession))return [];
    return candidates.filter(spell=> {
      const ranks=skills?.[spell.circle]?.ranks;
      if(finite(ranks)&&ranks>=0)return ranks<spell.rank;
      if(hasRanks&&!Object.hasOwn(skills,spell.circle))return true;
      return Object.hasOwn(professions,profession)&&!professions[profession].includes(spell.circle);
    }).slice(0,5);
  }

  function evaluate(session,timing,{now=Date.now()/1000,staleSeconds=20,buffer=300}={}) {
    const telemetry=session.telemetry||{}, data=telemetry.snapshot||telemetry.data||{};
    const selected=markers(data), effects=data.effects;
    const received=typeof telemetry.received_at==='string'?Date.parse(telemetry.received_at)/1000:telemetry.received_at;
    const collected=finite(data.collected_at)?data.collected_at:
      finite(data.metadata?.timestamp)?data.metadata.timestamp:
      finite(received)?received:finite(telemetry.age_seconds)?now-telemetry.age_seconds:null;
    const age=finite(received)?Math.max(0,now-received):
      finite(collected)?Math.max(0,now-collected):telemetry.age_seconds;
    const fresh=session.running!==false&&(telemetry.status||telemetry.state)==='fresh'&&finite(age)&&age<=staleSeconds;
    const available=Array.isArray(effects?.spells)&&data.metadata?.availability?.effects?.available!==false;
    const reported=available?[...effects.spells,...(Array.isArray(effects.buffs)?effects.buffs:[])]:[];
    const details=selected.map(spell=> {
      const matches=reported.filter(effect=>normalize(effect?.name)===normalize(spell.name));
      const expiries=matches.map(effect=>finite(effect.end_time)?effect.end_time:
        finite(effect.remaining_seconds)&&finite(collected)?collected+effect.remaining_seconds:null).filter(finite);
      const end=expiries.length?Math.max(...expiries):null;
      const remaining=end===null?null:Math.max(0,end-now);
      return {...spell,remaining,status:!available?'unknown':!matches.length?'missing':
        remaining===null?'unknown':remaining>0?'active':'missing'};
    });
    const present=details.filter(spell=>spell.status==='active');
    // A stray outside buff (especially Mass Blur) is not evidence of a spellup.
    // Keep every marker in details, but only assign a renewal timer with a quorum.
    const detected=present.length>=3;
    const remaining=detected?Math.min(...present.map(spell=>spell.remaining)):null;
    const mixed=detected&&Math.max(...present.map(spell=>spell.remaining))-remaining>300;
    const visitNow=finite(timing?.remaining)&&timing.remaining>buffer;
    const wait=visitNow?0:timing?.nextIn;
    const scheduled=finite(wait)&&wait>=0;
    const gap=remaining!==null&&scheduled?Math.max(0,wait-remaining):null;
    const shortfall=remaining!==null&&scheduled?Math.max(0,wait+buffer-remaining):null;
    let state,reason='';
    if(!fresh){state='unknown';reason='Waiting for a fresh spell report.';}
    else if(!available){state='unknown';reason='Active spells have not been reported.';}
    else if(!selected.length){state='unknown';reason='Waiting for profession or spell-circle ranks.';}
    else if(details.some(spell=>spell.status==='unknown')){state='unknown';reason='A marker spell has no usable timer.';}
    else if(!detected){
      state='missing';
      if(present.length)reason='Only '+present.length+' of '+details.length+' markers active; no invoker spellup detected.';
    }
    else if(!scheduled){state='unknown';reason='The next invoker visit is unavailable.';}
    // Once detected, track renewal time, not completeness: spells may be
    // deliberately dropped for spellburst. Missing markers stay in details.
    else state=shortfall>0?'gap':'covered';
    return {state,remaining,markers:details,mixed,gap,shortfall,visitNow,wait,buffer,reason,fresh,
      selection:data.skills?'learned spell ranks':'profession'};
  }

  function duration(seconds) {
    if(!finite(seconds)||seconds<=0)return '0m';
    if(seconds<60)return '<1m';
    const minutes=Math.floor(seconds/60),hours=Math.floor(minutes/60);
    return hours?hours+'h'+(minutes%60?' '+minutes%60+'m':''):minutes+'m';
  }
  return {markers,evaluate,duration};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=invokerBuffs;

(() => {
  if(typeof document==='undefined')return;
  const {evaluate,duration}=invokerBuffs;
  let inspected=null;
  const dialog=text('dialog','','invoker-buff-dialog');dialog.id='invokerBuffDetails';
  dialog.setAttribute('aria-labelledby','invokerBuffTitle');
  const heading=text('div','','invoker-buff-dialog-heading'),title=text('h2','Invoker buffs');
  title.id='invokerBuffTitle';
  const close=actionButton('Close',()=>dialog.close(),'secondary',null);
  heading.append(title,close);
  const body=text('div','','invoker-buff-dialog-body');dialog.append(heading,body);document.body.append(dialog);
  const identity=session=>session.realm+':'+session.character.toLowerCase();
  const findSession=key=>sessions.find(session=>identity(session)===key);
  const model=session=>evaluate(session,invokerCountdown.state(),{staleSeconds:Number(dashboardSettings.stale_seconds)||20});
  function value(result) {
    return result.state==='unknown'?'Unknown':result.state==='missing'?'Missing':
      duration(result.remaining);
  }
  function explanation(result) {
    if(result.state==='unknown')return result.reason;
    if(result.state==='missing')return result.reason||'No tracked markers active';
    const parts=[];
    if(result.gap>0)parts.push(duration(Math.ceil(result.gap/60)*60)+' gap before next invoker');
    else if(result.shortfall>0)parts.push('Within 5m travel buffer');
    else if(result.visitNow)parts.push('Invoker scheduled now');
    else parts.push('Covers next invoker');
    return parts.join(' · ');
  }
  function renderDetails() {
    const session=findSession(inspected);
    if(!session){body.replaceChildren(text('p','This character is no longer reporting.'));return;}
    const result=model(session);
    title.textContent=session.character+' · Invoker buffs';
    const summary=text('p','', 'invoker-buff-detail-summary');summary.dataset.state=result.state;
    summary.append(text('strong',value(result)),text('span',explanation(result)));
    const list=text('dl','','invoker-marker-list');
    for(const spell of result.markers) {
      const row=text('div','','invoker-marker-'+spell.status);
      row.append(text('dt',spell.name),text('dd',spell.status==='active'?duration(spell.remaining):
        spell.status==='missing'?'Not active':'Unknown'));list.append(row);
    }
    const notes=[
      'At least three active markers are needed to detect a spellup. The timer uses the earliest expiry of up to five long-duration spells you cannot self-cast. The two-hour spells are ignored.',
      'This tracks renewal time, not a complete spell list. Inactive markers may have been dropped for spellburst and do not trigger a warning.',
      'Markers selected using '+result.selection+'. Spells from a pill or another caster also count.'
    ];
    if(!result.fresh)notes.unshift('These are the last reported effects; current coverage is unknown.');
    if(result.mixed)notes.push('Mixed durations: one or more markers expire over five minutes apart. The earliest controls the timer.');
    notes.push('Coverage uses the same scheduled visits as the header, with a five-minute travel buffer. The schedule does not confirm the invoker is present.');
    body.replaceChildren(summary,list,...notes.map(note=>text('p',note,'invoker-buff-note')));
  }
  function show(session) {
    inspected=identity(session);renderDetails();dialog.showModal();
  }
  dialog.addEventListener('close',()=>{
    const session=findSession(inspected);
    const row=[...$('sessionList').querySelectorAll('.live-card')].find(row=>row.dataset.sessionId===session?.id);
    row?.querySelector('.invoker-buff-button')?.focus({preventScroll:true});
    inspected=null;
  });
  function update() {
    if(!active)return;
    if(currentView==='sessions')for(const strip of $('sessionList').querySelectorAll('.invoker-buff-strip')) {
      const session=findSession(strip.dataset.characterKey);if(!session)continue;
      const result=model(session);strip.dataset.state=result.state;
      strip.querySelector('.invoker-buff-value').textContent=value(result);
      strip.querySelector('.invoker-buff-status').textContent=explanation(result);
    }
    if(dialog.open)renderDetails();
  }
  const previousSessions=renderSessions;
  renderSessions=function() {
    const focused=document.activeElement?.closest('.invoker-buff-strip')?.dataset.characterKey;
    previousSessions();
    for(const row of $('sessionList').querySelectorAll('.live-card')) {
      const session=sessions.find(session=>session.id===row.dataset.sessionId);if(!session)continue;
      const strip=text('div','','invoker-buff-strip');strip.dataset.characterKey=identity(session);
      const button=actionButton('',()=>show(session),'invoker-buff-button',null);
      button.setAttribute('aria-label','Invoker buff details for '+session.character+' on '+session.realm);
      button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls',dialog.id);
      const line=text('span','','invoker-buff-heading'),label=text('span','Invoker buffs','invoker-buff-label');
      const spark=text('span','✦','invoker-buff-spark');spark.setAttribute('aria-hidden','true');label.prepend(spark);
      const time=text('strong','','invoker-buff-value'),status=text('span','','invoker-buff-status');
      time.id='invoker-buff-time-'+identity(session);status.id='invoker-buff-status-'+identity(session);
      button.setAttribute('aria-describedby',time.id+' '+status.id);
      line.append(label,time);
      button.append(line,status);strip.append(button);
      row.querySelector('.live-sub').after(strip);
      if(focused===identity(session))button.focus({preventScroll:true});
    }
    update();
  };
  setInterval(update,1000);
  document.addEventListener('visibilitychange',update);
  $('logout').addEventListener('click',()=>{if(dialog.open)dialog.close();inspected=null;});
})();
