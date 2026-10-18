/* Profiles use durable observations; live vitals continue using session telemetry. */
const characterProfiles = (() => {
  const cache = new Map();
  const key = (name, gameRealm) => gameRealm + ':' + name.toLowerCase();
  let profileLoad = 0, rosterLoad = 0;
  let skillQuery = '', showUntrained = false;
  const expanded = new Set();
  const sectionNames = new Set(['overview', 'stats', 'skills']);
  const label = name => name.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
  const stamp = value => value ? new Date(value * 1000).toLocaleString() : 'Not yet reported';
  const renewalFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone:'America/Los_Angeles', weekday:'long', month:'numeric', day:'numeric',
    hour:'numeric', minute:'2-digit', hour12:true, timeZoneName:'short'
  });
  const renewalTime = value => {
    if(typeof value!=='number'||!Number.isFinite(value)||value<=0)return null;
    const parts=Object.fromEntries(renewalFormatter.formatToParts(new Date(value*1000)).map(part=>[part.type,part.value]));
    return `${parts.weekday} ${parts.month}/${parts.day} at ${parts.hour}:${parts.minute}${parts.dayPeriod.toLowerCase()} ${parts.timeZoneName}`;
  };
  const profileFor = session => cache.get(key(session.character, session.realm));
  const ageText = value => {
    const minutes=Math.max(0,Math.floor((Date.now()/1000-value)/60));
    return minutes<60 ? minutes+'m ago' : minutes<1440 ? Math.floor(minutes/60)+'h ago' : Math.floor(minutes/1440)+'d ago';
  };

  function disclosure(title,identity,className='profile-disclosure') {
    const details=text('details','',className), summary=text('summary',title);
    summary.dataset.focusId=identity;
    details.open=expanded.has(identity);details.append(summary);
    details.ontoggle=()=>{if(details.isConnected)details.open?expanded.add(identity):expanded.delete(identity);};
    return details;
  }

  function observation(node,observed,session) {
    node.title='Last observed: '+stamp(observed);
    if(observed && (freshness(session)!=='fresh' || Date.now()/1000-observed>600))
      node.append(text('span','Updated '+ageText(observed),'observation-age'));
  }

  function resourceNumbers(resource,parent,showLimits=false) {
    if(resource.weekly==null&&resource.total==null) {parent.append(text('p','Not reported','monitor-empty'));return;}
    const values=text('dl','','resource-values');
    for(const [name,field,cls] of [['Weekly','weekly','resource-weekly'],['Stored','total','resource-stored']]) {
      const amount=number(resource[field])+(showLimits?' / '+number(field==='weekly'?50000:200000):'');
      const item=text('div');item.append(text('dt',name),text('dd',amount,cls));values.append(item);
    }
    parent.append(values);
  }

  function cycleCard(bonuses,parent) {
    const active=typeof bonuses.lumnis_stage==='number';
    parent.append(text('span',lumnisText(bonuses),'cycle-badge '+(active?'is-active':bonuses.lumnis_stage==='ready'?'is-ready':'is-neutral')));
    parent.append(text('p',donationText(bonuses),'donation-status'));
    const reset=bonuses.lumnis_reset_at, formatted=renewalTime(reset);
    const renewal=text('p',bonuses.lumnis_stage==='ready' ? 'Ready on next XP absorption'
      : formatted ? reset>Date.now()/1000 ? formatted : 'Awaiting game update'
      : 'Renewal not reported','cycle-renewal');
    renewal.title=formatted ? 'Reported renewal: '+formatted : 'Waiting for the game to report the next Lumnis renewal.';
    parent.append(renewal);
  }

  function tutelageState(bonuses) {
    let state=bonuses.fashlonae_state;
    // Correct legacy reports immediately when their native numeric state is known.
    if(!['active','inactive','expended','unavailable','unknown'].includes(state)) {
      state=bonuses.fashlonae_source==='native_dialog'&&[0,1,2].includes(bonuses.fashlonae_raw)
        ? {0:'inactive',1:'expended',2:'active'}[bonuses.fashlonae_raw]
        : ['eligible','ineligible'].includes(state)?'inactive':'unknown';
    }
    // Tutelage renews with Lumnis, but its weekly allowance starts afterward.
    // Preserve raw observations; an old expended flag is not exhaustion this cycle.
    if(['inactive','expended'].includes(state)&&[2,3,4,5,'ready'].includes(bonuses.lumnis_stage))return 'waiting';
    return state;
  }

  function tutelageSummary(bonuses,parent,profile,lastKnown=false) {
    const box=text('div','','tutelage-summary'), heading=text('div','','bonus-heading');
    const observed=bonuses.fashlonae_observed_at||profile?.field_observed_at?.bonuses?.fashlonae_state;
    const old=lastKnown || (observed && Date.now()/1000-observed>600);
    const state=tutelageState(bonuses);
    const words={active:old?'Last known active ×5':'Active ×5',waiting:'Waiting for Lumnis',inactive:'Inactive',expended:'Expended for the week',unavailable:'Unavailable',unknown:'Not reported'};
    const name=text('span','Tutelage','bonus-label');name.title='Fash’lo’nae’s Tutelage';
    heading.append(name,text('span',words[state]||'Not reported','tutelage-state'+(state==='active'&&!old?' is-active':'')));
    box.append(heading);
    if(state!=='unavailable'&&bonuses.fashlonae_days_remaining!=null) {
      const days=text('span','('+number(bonuses.fashlonae_days_remaining)+')','tutelage-duration');
      days.setAttribute('aria-label',number(bonuses.fashlonae_days_remaining)+' days remaining');
      const collected=bonuses.fashlonae_days_observed_at||profile?.field_observed_at?.bonuses?.fashlonae_days_remaining;
      days.title='Days remaining as reported by the game. Last observed: '+stamp(collected);
      heading.append(days);
    }
    box.title='Fash’lo’nae’s Tutelage · '+(state==='waiting'?'Renews with Lumnis and starts after Lumnis finishes. ':state==='inactive'?'Currently inactive. ':state==='expended'?'Weekly bonus XP allowance used. ':state==='unavailable'?'Unavailable in the native experience report. ':'')+'Last observed: '+stamp(observed);
    if(old&&observed)box.append(text('span','Updated '+ageText(observed),'observation-age'));
    parent.append(box);
  }

  function lumnisText(bonus = {}) {
    if (typeof bonus.lumnis_stage === 'number') return 'Active ×' + bonus.lumnis_stage;
    return {ready:'Ready to start', expired:'Exhausted', unavailable:'Unavailable', unknown:'Unknown'}[bonus.lumnis_stage] || 'Unknown';
  }
  function bonusIcon(kind,state,description,session,count=null,lastKnown=false) {
    const wrap=text('span','','bonus-icon-wrap');
    const button=actionButton('',()=>showDetails(session),'bonus-icon '+kind+'-icon is-'+state,null);
    button.dataset.state=state;
    button.classList.toggle('is-stale',lastKnown);
    button.setAttribute('aria-label',(kind==='lumnis'?'Lumnis':'Tutelage')+' details for '+session.character+' on '+session.realm);
    const tip=text('span',description,'bonus-tooltip');tip.id='bonus-'+kind+'-'+session.id;
    tip.setAttribute('role','tooltip');button.setAttribute('aria-describedby',tip.id);
    const colored=['active','eligible','ready'].includes(state),img=document.createElement('img');
    img.src='/assets/images/saga/'+kind+(colored?'':'-grayscale')+'.webp';img.alt='';img.width=36;img.height=36;
    button.append(img);
    if(count!==null){const multiplier=text('span',String(count),'bonus-multiplier');multiplier.setAttribute('aria-hidden','true');button.append(multiplier);}
    wrap.append(button,tip);return wrap;
  }
  function liveBonusIcons(bonuses,cycle,session,profile) {
    cycleCard(bonuses,cycle);
    cycle.querySelector('.cycle-badge').remove();cycle.querySelector('.donation-status').remove();
    const stage=bonuses.lumnis_stage,active=Number.isFinite(stage)&&stage>0;
    const lumnisState=active?'active':stage==='ready'?'ready':stage==='expired'?'expired':'unknown';
    const stale=freshness(session)!=='fresh';
    const lumnisDescription='Lumnis · '+(stale?'Last known: ':'')+(active?'Active ×'+stage:stage==='expired'?'Expired for the week':lumnisText(bonuses))+
      ' · ['+(bonuses.lumnis_donations==null?'?':number(bonuses.lumnis_donations))+'/3] prepaid · '+cycle.querySelector('.cycle-renewal').textContent;
    const raw=tutelageState(bonuses),state=['waiting','inactive'].includes(raw)?'eligible':raw==='expended'?'expired':raw;
    const observed=bonuses.fashlonae_observed_at||profile?.field_observed_at?.bonuses?.fashlonae_state;
    const old=stale||!!(observed&&Date.now()/1000-observed>600);
    const words={active:'Active',eligible:raw==='waiting'?'Eligible — waiting for Lumnis to finish':'Eligible',expired:'Expired for the week',unavailable:'Unavailable',unknown:'Not reported'};
    const tutelageDescription='Fash’lo’nae’s Tutelage · '+(old?'Last known: ':'')+(words[state]||'Not reported')+
      (raw!=='unavailable'&&bonuses.fashlonae_days_remaining!=null?' · '+number(bonuses.fashlonae_days_remaining)+' days remaining':'');
    const hasTutelage=['active','eligible','expired'].includes(state)&&bonuses.fashlonae_state!=='ineligible';
    cycle.classList.toggle('has-tutelage',hasTutelage);
    cycle.prepend(bonusIcon('lumnis',lumnisState,lumnisDescription,session,active?stage:null,stale));
    if(hasTutelage)cycle.prepend(bonusIcon('tutelage',state,tutelageDescription,session,null,old));
    const renewal=cycle.querySelector('.cycle-renewal'),reset=bonuses.lumnis_reset_at;
    if(stage!=='ready'&&Number.isFinite(reset)&&reset>Date.now()/1000) {
      const hours=Math.floor((reset-Date.now()/1000)/3600);
      renewal.textContent='Resets in '+Math.floor(hours/24)+'d '+hours%24+'h';
    }
  }
  function donationText(bonus = {}) {
    const count = bonus.lumnis_donations;
    return count == null ? 'Prepaid unknown' : number(count)+' prepaid';
  }
  function profileNote(profile, section, field) {
    const observed = field ? profile?.field_observed_at?.[section]?.[field] : profile?.observed_at?.[section];
    return text('p', 'Last observed: ' + stamp(observed), 'profile-note');
  }
  function balanceSummary(data, parent, open, profile, offline=false) {
    const summary = text('div', '', 'profile-summary roster-summary');
    const bonuses = data.bonuses || {}, resource = data.resources || {};
    const cycle=text('div','','roster-cycle');cycleCard(bonuses,cycle);
    tutelageSummary(bonuses,cycle,profile,offline);
    const balances=text('div','','roster-balances');balances.append(text('div',resource.type||'Resources','resource-name'));resourceNumbers(resource,balances);
    summary.append(cycle,balances);
    if(open)summary.append(actionButton('View profile',open,'profile-link',null));
    parent.append(summary);
  }

  function latestBalances(session) {
    const saved=profileFor(session), live=telemetryData(session), result={...(saved?.snapshot||{})};
    for(const section of ['bonuses','resources']) {
      const incoming=live[section];if(!incoming)continue;
      const availability=live.metadata?.availability?.[section];
      if(availability?.available===false)continue;
      const observed=incoming.observed_at || availability?.collected_at || 0;
      result[section]={...(result[section]||{})};
      const wasNotRedeemed=result[section].fashlonae_state==='unavailable';
      for(const [field,value] of Object.entries(incoming)) {
        if(value==null)continue;
        let fieldTime=field==='lumnis_donations' ? incoming.donations_observed_at||observed : observed;
        if(field.startsWith('fashlonae_'))fieldTime=incoming[field==='fashlonae_days_remaining'?'fashlonae_days_observed_at':'fashlonae_observed_at']||observed;
        if(fieldTime >= (saved?.field_observed_at?.[section]?.[field]||0)
          || (!fieldTime && freshness(session)==='fresh'))result[section][field]=value;
      }
      if(section==='bonuses'&&['expired','ready','unavailable'].includes(result[section].lumnis_stage))delete result[section].lumnis_points_remaining;
      if(section==='bonuses'&&result[section].fashlonae_state==='unavailable')result[section].fashlonae_days_remaining=0;
      else if(section==='bonuses'&&wasNotRedeemed&&['active','inactive','expended','eligible'].includes(result[section].fashlonae_state)&&incoming.fashlonae_days_remaining==null)delete result[section].fashlonae_days_remaining;
    }
    return result;
  }

  function makeTable(headers, rows, caption) {
    const wrap = text('div', '', 'table-scroll'), table = text('table', '', 'profile-table');
    if (caption) table.append(text('caption', caption));
    const head = text('thead'), heading = text('tr');
    for (const title of headers) {const cell = text('th', title);cell.scope = 'col';heading.append(cell);}
    head.append(heading);table.append(head);
    const body = text('tbody');
    for (const values of rows) {const row = text('tr');values.forEach((value, i) => {const cell = text(i === 0 ? 'th' : 'td', number(value));if(i===0)cell.scope='row';row.append(cell);});body.append(row);}
    table.append(body);wrap.append(table);return wrap;
  }

  function resourceSection(data, profile, parent) {
    const resource = data.resources || {};
    const section = inspectorSection(resource.type || 'Profession resources', parent);
    section.classList.add('profile-resource-card');
    resourceNumbers(resource,section);
    const limits=disclosure('Balances & reporting',key(detailSession.character,detailSession.realm)+':reporting');
    section.append(limits);
    limits.append(profileNote(profile, 'resources', 'weekly'));
    if (profile?.field_observed_at?.resources?.total !== profile?.field_observed_at?.resources?.weekly)
      limits.append(text('p', 'Stored balance last observed: ' + stamp(profile?.field_observed_at?.resources?.total), 'profile-note'));
    if (resource.max_weekly != null) pair('Weekly cap', resource.max_weekly, limits);
    if (resource.max_total != null) pair('Storage cap', resource.max_total, limits);
    if (resource.weekly != null && resource.max_weekly != null) pair('Remaining this cycle', Math.max(0, resource.max_weekly - resource.weekly), limits);
    if (resource.voln_favor != null) pair('Voln favor', resource.voln_favor, limits);
    limits.append(text('p', 'Weekly earnings and stored balance are separate counters. Spending reduces the stored balance.', 'detail-note'));
  }

  const previousRenderDetail = renderDetail;
  renderDetail = async function() {
    if(['bonuses','status','experience'].includes(detailSection))detailSection='overview';
    if (!sectionNames.has(detailSection)) return previousRenderDetail();
    ++detailRequest;
    const focusId=$('detailContent').contains(document.activeElement)?document.activeElement?.dataset.focusId:null;
    if(focusId)queueMicrotask(()=>[...$('detailContent').querySelectorAll('[data-focus-id]')].find(node=>node.dataset.focusId===focusId)?.focus({preventScroll:true}));
    const content = $('detailContent');content.replaceChildren();
    for (const button of document.querySelectorAll('[data-detail]')) button.setAttribute('aria-pressed', String(button.dataset.detail === detailSection));
    const profile = profileFor(detailSession), data = profile?.snapshot || {};
    if (!profile) {content.append(text('p', 'Loading profile…', 'profile-note'));return;}
    const character = data.character || {};
    $('detailSubtitle').textContent = [detailSession.realm === 'test' ? 'Test realm' : detailSession.realm === 'fallen' ? 'Fallen realm' : 'Prime realm',
      accountFor(detailSession.character), character.profession, character.level != null ? 'Level ' + number(character.level) : '',
      detailSession.running ? detailSession.attachment : 'Offline'].filter(Boolean).join(' · ');
    if(profile.updated_at==null)content.append(text('p','No profile data yet. Launch this character with the updated Gempy reporter to collect it.','profile-note'));
    else if(!detailSession.running)content.append(text('p','Offline · Showing the last reported build and balances.','profile-note'));
    if (detailSection === 'overview') {
      const identity=text('div','','profile-facts');
      for (const [name,value] of [['Profession',character.profession],['Level',character.level],['Race',character.race]]) {
        const fact=text('div');fact.append(text('span',name),text('strong',number(value)));identity.append(fact);
      }
      identity.title='Character last observed: '+stamp(profile.observed_at?.character);content.append(identity);
      const cards=text('div','','profile-overview-grid');content.append(cards);
      resourceSection(data,profile,cards);
      const cycle=inspectorSection('Gift of Lumnis',cards);cycle.classList.add('profile-cycle-card');
      const bonus=data.bonuses||{};cycleCard(bonus,cycle);
      const details=disclosure('Cycle & donation details',key(detailSession.character,detailSession.realm)+':cycle');cycle.append(details);
      pair('Future cycles prepaid',bonus.lumnis_donations,details);
      pair('Current enhanced blessing',[4,5].includes(bonus.lumnis_stage)?'Confirmed by current phase':'Not confirmed by current phase',details);
      const reset=bonus.lumnis_reset_at;
      pair('Next renewal (Pacific)',renewalTime(reset),details);
      if(reset&&reset<=Date.now()/1000)details.append(text('p','The reported refresh time has passed. A new game report is needed to confirm the cycle.','detail-note'));
      details.append(profileNote(profile,'bonuses','lumnis_stage'),profileNote(profile,'bonuses','lumnis_donations'),text('p','Prepaid donations cover future cycles; they do not establish whether the current cycle was enhanced.','detail-note'));
      const tutelage=inspectorSection('Fash’lo’nae’s Tutelage',cards);tutelage.classList.add('profile-tutelage-card');
      tutelageSummary(bonus,tutelage,profile,freshness(detailSession)!=='fresh');
      const tutelageDetails=disclosure('Tutelage details',key(detailSession.character,detailSession.realm)+':tutelage');
      const stateWords={active:'Active ×5',waiting:'Waiting for Lumnis',inactive:'Inactive',expended:'Expended for the week',unavailable:'Unavailable',unknown:'Not reported'};
      pair('Reported status',stateWords[tutelageState(bonus)],tutelageDetails);
      pair('Reported days remaining',tutelageState(bonus)==='unavailable'?null:bonus.fashlonae_days_remaining,tutelageDetails);
      tutelageDetails.append(profileNote(profile,'bonuses','fashlonae_state'),profileNote(profile,'bonuses','fashlonae_days_remaining'),
        text('p','Tutelage renews with Lumnis and waits until Lumnis finishes. Active means the game confirms the ×5 multiplier. Inactive means it is not currently applying. Expended for the week means the weekly bonus XP allowance is used. Days remaining describe the benefit duration and can remain positive after the weekly allowance is spent.','detail-note'));
      tutelage.append(tutelageDetails);
      const statuses=disclosure('Live status',key(detailSession.character,detailSession.realm)+':status');
      const statusContent=text('div','','disclosure-content');statuses.append(statusContent);content.append(statuses);
      previousRenderDetail(statusContent,'status');
      const experience=disclosure('Experience & training',key(detailSession.character,detailSession.realm)+':experience');
      const experienceContent=text('div','','disclosure-content');experience.append(experienceContent);content.append(experience);
      previousRenderDetail(experienceContent,'experience');
      const boosts=disclosure('Other experience bonuses',key(detailSession.character,detailSession.realm)+':boosts');
      pair('RPA',bonus.rpa===true?'Observed active':bonus.rpa===false?'Inactive':null,boosts);pair('50% experience scroll',bonus.exp_scroll_expires_elven,boosts);content.append(boosts);
      return;
    }
    if (detailSection === 'stats') {
      const section = inspectorSection('Current stats', content);section.append(profileNote(profile, 'stats'));
      const rows = Object.entries(data.stats || {}).map(([name, value]) => [label(name), value.base_value, value.base_bonus, value.value, value.bonus, value.enhanced_value, value.enhanced_bonus]);
      if (!rows.length) {section.append(text('p', 'Stats have not been reported yet. The reporter collects INFO FULL automatically.', 'profile-note'));return;}
      section.append(makeTable(['Stat', 'Base', 'Bonus', 'Normal', 'Bonus', 'Enhanced', 'Bonus'], rows, 'Base, normal and enhanced values are shown separately. A dash means unavailable.'));
      return;
    }
    if (detailSection === 'skills') {
      const section = inspectorSection('Skills & spell research', content);section.append(profileNote(profile, 'skills'));
      const filters = text('div', '', 'profile-filters'), search = document.createElement('input');
      search.type='search';search.placeholder='Find a skill…';search.setAttribute('aria-label','Find a skill');search.value=skillQuery;
      const toggle = text('label', 'Show untrained'), check = document.createElement('input');check.type='checkbox';check.checked=showUntrained;toggle.prepend(check);
      const results = text('div');
      function drawSkills() {
        results.replaceChildren();
        const all = Object.entries(data.skills || {});
        const filtered = all.filter(([name, value]) => (showUntrained || value.ranks > 0) && label(name).toLowerCase().includes(skillQuery.toLowerCase())).sort(([a],[b]) => a.localeCompare(b));
        if (!filtered.length) results.append(text('p', !all.length ? 'Skills have not been reported yet. The reporter collects SKILL automatically.' : 'No matching skills.', 'profile-note'));
        else results.append(makeTable(['Skill', 'Ranks', 'Bonus', 'Type'], filtered.map(([name, value]) => [label(name), value.ranks, value.bonus, value.category === 'spell_research' ? 'Spell research' : 'Skill'])));
      }
      search.oninput=()=>{skillQuery=search.value;drawSkills();};check.onchange=()=>{showUntrained=check.checked;drawSkills();};
      filters.append(search,toggle);section.append(filters, results);drawSkills();return;
    }
  };

  async function loadProfile(session) {
    const request=++profileLoad, identity=key(session.character,session.realm);
    try {
      const profile=await api('profiles/'+encodeURIComponent(session.realm)+'/'+encodeURIComponent(session.character));
      if(request!==profileLoad || !active)return;
      cache.set(identity,profile);
      const editing=$('detailContent').contains(document.activeElement)&&document.activeElement.matches('input,select,textarea');
      if($('characterDetails').open && detailSession && key(detailSession.character,detailSession.realm)===identity && !editing)renderDetail();
    } catch(error) {
      if(request===profileLoad && $('characterDetails').open && detailSession && key(detailSession.character,detailSession.realm)===identity)
        $('detailContent').replaceChildren(text('p','Could not load profile: '+error.message,'profile-note'),actionButton('Retry',()=>loadProfile(session),'secondary',null));
    }
  }
  const previousShowDetails=showDetails;
  showDetails=function(session,section='overview') {
    if(!$('characterDetails').open){skillQuery='';showUntrained=false;}
    previousShowDetails(session,section);loadProfile(session);
  };

  const previousCharacters=renderCharacters;
  renderCharacters=function() {
    previousCharacters();
    for(const row of $('accounts').querySelectorAll('.character')) {
      const heading=row.querySelector('.character-name'), name=heading.textContent;
      const session=matchingSession(name)||{id:'profile:'+realm+':'+name,character:name,realm,running:false,attachment:'Offline',telemetry:{status:'unavailable'}};
      const open=()=>showDetails(session);
      const button=actionButton(name,open,'profile-name',null);button.setAttribute('aria-label','Profile for '+name+' on '+realm);heading.replaceChildren(button);
      const profile=profileFor(session), data=profile?.snapshot || {};
      const info=row.querySelector('.character-info');
      const identity=[data.character?.level!=null?'Level '+number(data.character.level):'',data.character?.profession].filter(Boolean).join(' · ');
      if(identity)info.append(text('div',identity,'character-meta'));
      if(profile?.updated_at) {
        const resource=data.resources||{},summary=text('p','','roster-quick-balances');
        summary.append(text('span',resource.type||'Resources'),
          text('span','Weekly '+number(resource.weekly)),text('span','Stored '+number(resource.total)));
        info.append(summary);
        const details=disclosure('Cycle & resource details for '+name,key(name,realm)+':roster','roster-disclosure');
        balanceSummary(data,details,()=>showDetails(session),profile,freshness(session)!=='fresh');
        info.append(details);
      }
      else info.append(text('div','Profile not yet reported','profile-summary'));
      const state=info.querySelector('.character-meta');
      if(!liveSession(session))state.textContent='Offline · '+(realm==='test'?'Test':'Prime');
    }
  };
  const previousSessions=renderSessions;
  renderSessions=function() {
    const focused=document.activeElement,focusLabel=focused?.getAttribute('aria-label'),restore=$('sessionList').contains(focused);
    previousSessions();
    const heading=$('sessionList').querySelector('.monitor-heading');
    heading?.remove();
    for(const row of $('sessionList').querySelectorAll('.live-card')) {
      const session=sessions.find(item=>item.id===row.dataset.sessionId);if(!session)continue;
      const data=latestBalances(session);
      const live=telemetryData(session), saved=profileFor(session);
      const identity=row.querySelector('.row-identity'),vitals=row.querySelector('.row-vitals'),location=row.querySelector('.row-location'),actions=row.querySelector('.session-actions');
      const char=live.character||saved?.snapshot?.character||{};
      const subtitle=identity.querySelector('.live-sub'),profileButton=actions.querySelector('.inspect-button');
      profileButton.textContent='Level '+(char.level==null?'—':number(char.level));
      profileButton.classList.add('level-profile');profileButton.title='Open character profile';
      subtitle.replaceChildren(profileButton);
      if(char.profession)subtitle.append(document.createTextNode(' · '+char.profession));
      const xp=live.experience||saved?.snapshot?.experience||{};
      if(char.level===100) {
        subtitle.append(document.createTextNode(' · '+number(xp.physical_training_points)+' PTP · '+number(xp.mental_training_points)+' MTP'));
      } else if(Number.isFinite(char.level)&&char.level>=0&&char.level<=99) {
        const percent=Number.isFinite(xp.percent_capped)?xp.percent_capped.toFixed(2)+'%':'—';
        subtitle.append(document.createTextNode(' · '+percent+' to cap'));
      }
      subtitle.title=accountFor(session.character);
      const inlineActions=text('div','','character-actions'),open=actions.querySelector('.launch-button'),disconnect=actions.querySelector('.icon-button');
      open.title=open.textContent.trim();open.replaceChildren(icon('external',14));
      inlineActions.append(open,disconnect);
      identity.querySelector('.live-card-heading').append(inlineActions);
      actions.querySelector('.row-secondary').remove();
      if(actions.children.length)identity.append(actions);
      const room=location.querySelector('.room');room.textContent=room.textContent.replace(/^\[|\]$/g,'');
      if(live.location?.room_id!=null)room.append(text('span',' · Lich '+live.location.room_id,'character-room-id'));
      room.title=room.textContent;
      identity.querySelector('.live-sub').before(room);
      const fresh=identity.querySelector('.freshness');
      if(freshness(session)==='fresh')fresh.remove();
      else fresh.replaceChildren(text('span','','dot'),document.createTextNode(freshness(session)==='stale'?'Reporting delayed':'No live report'));
      const alerts=[];
      if(freshness(session)==='fresh')for(const [kind,title] of [['health','health'],['spirit','spirit']]) {
        const value=live.vitals?.[kind];
        if(value?.max>0&&typeof value.current==='number'&&value.current/value.max<=.25) {
          alerts.push((value.current/value.max<=.1?'Critical ':'Low ')+title);
          const bar=vitals.querySelectorAll('.vital')[kind==='health'?0:3];bar?.classList.add('vital-alert');
        }
      }
      if(alerts.length) {row.classList.add('needs-attention');identity.append(text('div',alerts.join(' · '),'vital-warning'));}
      const progress=identity.querySelector('.character-progress');
      if(progress)vitals.prepend(progress);
      const cycle=text('div','','row-cycle');cycle.setAttribute('aria-label','XP bonuses for '+session.character);
      liveBonusIcons(data.bonuses||{},cycle,session,saved);
      subtitle.after(cycle);
      const rates=text('section','','row-xp-rates');rates.setAttribute('aria-label','XP per hour for '+session.character);
      const rateValues=text('dl','','resource-values');
      for(const [label,field,cls] of [['Session XP/Hour','hourly_rate','session-xp-rate'],['60 min XP/Hour','last_hour_gain','recent-xp-rate']]) {
        const item=text('div');item.append(text('dt',label),text('dd',number(live.experience?.[field]),cls));rateValues.append(item);
      }
      rates.title='Normal and ascension XP combined. Session average starts when the reporter starts (normally at login). Past 60 minutes uses XP recorded so far during the first hour.';
      rates.append(rateValues);identity.append(rates);
      const resources=text('div','','row-resources');resources.setAttribute('aria-label','Resources for '+session.character);
      resources.append(text('div',data.resources?.type||'Resources','resource-name'));resourceNumbers(data.resources||{},resources,true);
      observation(resources,live.resources?.observed_at||saved?.observed_at?.resources,session);
      identity.append(resources);
      row.replaceChildren(identity,vitals);
    }
    if(restore&&focusLabel)[...$('sessionList').querySelectorAll('[aria-label]')].find(node=>node.getAttribute('aria-label')===focusLabel)?.focus({preventScroll:true});
  };
  const previousRefresh=refresh;
  refresh=async function() {
    await previousRefresh();
    if(!active)return;
    if(['sessions','characters'].includes(currentView))await loadRoster();
    if(detailSession&&$('characterDetails').open)await loadProfile(detailSession);
  };
  async function loadRoster() {
    const gameRealm=realm,request=++rosterLoad;
    try {
      const realms=currentView==='sessions' ? [...new Set([gameRealm,...sessions.map(session=>session.realm)])] : [gameRealm];
      const results=await Promise.all(realms.map(value=>api('profiles?realm='+encodeURIComponent(value))));
      if(!active||request!==rosterLoad||realm!==gameRealm)return;
      for(const result of results)for(const profile of result.profiles)cache.set(key(profile.character,profile.realm),profile);
      const focused=document.activeElement, name=focused?.getAttribute('aria-label');
      const restore=$('accounts').contains(focused);
      if(currentView==='characters')renderCharacters();
      else if(currentView==='sessions')renderSessions();
      if(restore&&name)[...$('accounts').querySelectorAll('button')].find(button=>button.getAttribute('aria-label')===name)?.focus({preventScroll:true});
    } catch(error) {if(request===rosterLoad&&active)message('Could not load profiles: '+error.message,'error');}
  }
  const previousSetTab=setTab;
  setTab=function(tab){previousSetTab(tab);if(tab==='characters')loadRoster();};
  for(const button of document.querySelectorAll('[data-realm]'))button.addEventListener('click',loadRoster);
  $('logout').addEventListener('click',()=>{cache.clear();++profileLoad;++rosterLoad;});
  $('characterDetails').addEventListener('close',()=>{++profileLoad;});
  function liveSession(session) {return !!session.running;}
  function choices() {
    const all=new Map();
    const add=(name,gameRealm)=>all.set(key(name,gameRealm),{character:name,realm:gameRealm});
    for(const names of Object.values(accounts))for(const name of names)for(const gameRealm of ['prime','test'])add(name,gameRealm);
    for(const profile of cache.values())add(profile.character,profile.realm);
    for(const session of sessions)add(session.character,session.realm);
    if(detailSession)add(detailSession.character,detailSession.realm);
    return [...all.values()].sort((a,b)=>a.realm.localeCompare(b.realm)||a.character.localeCompare(b.character));
  }
  function sessionFor(name,gameRealm) {
    return sessions.find(s=>s.realm===gameRealm&&s.character.toLowerCase()===name.toLowerCase())||
      {id:'profile:'+gameRealm+':'+name,character:name,realm:gameRealm,running:false,attachment:'Offline',telemetry:{status:'unavailable'}};
  }
  return {choices,sessionFor,tutelageState,
    get skillQuery(){return skillQuery;},set skillQuery(value){skillQuery=value;},
    get showUntrained(){return showUntrained;},set showUntrained(value){showUntrained=value;}};
})();
