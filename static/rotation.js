/* Weekly goals use game observations; the vault supplies membership, not balances. */
(() => {
  const page=text('section');page.id='rotation';page.hidden=true;page.setAttribute('aria-labelledby','rotationHeading');
  page.innerHTML=`<div class="page-heading"><div><h2 id="rotationHeading">Weekly rotation</h2><p>Your enchanting crew, ready for the next reset.</p></div><button id="rotationRefresh" class="secondary">Refresh</button></div>
    <div id="rotationError" class="rotation-error" role="status" hidden></div>
    <div class="rotation-scoreboard"><div class="rotation-score"><span>Wizards finished</span><strong id="rotationDone">— / —</strong><progress id="rotationOverall" max="8" value="0" aria-label="Wizards finished"></progress></div><div><span>Still hunting</span><strong id="rotationHunting">—</strong></div><div><span>Reset within 24h</span><strong id="rotationSoon">—</strong></div><div><span>Need a report</span><strong id="rotationUnknown">—</strong></div></div>
    <details id="rotationMainsGroup" class="rotation-mains-section" open><summary class="rotation-section-heading"><h3 id="rotationMainsHeading">Main characters</h3><span>Lumnis overview · separate from wizard goals</span></summary><div id="rotationMains" class="rotation-mains"></div></details>
    <div class="rotation-section-heading"><div><h3>Wizard rotation</h3><p>Finished = Lumnis spent + weekly essence cap reached.</p></div><span id="rotationEssenceCoverage"></span></div>
    <div class="rotation-filters"><input id="rotationSearch" type="search" aria-label="Find a rotation character" placeholder="Find a wizard…"><select id="rotationState" aria-label="Rotation status"><option value="all">All wizards</option><option value="needs_hunting">Needs hunting</option><option value="done">Finished</option><option value="needs_update">Needs updated report</option></select><select id="rotationAccount" aria-label="Rotation account"><option value="">All accounts</option></select><select id="rotationRealm" aria-label="Rotation realm"><option value="prime">Prime</option><option value="test">Test</option></select><label><input id="rotationGroup" type="checkbox"> Group by account</label></div>
    <div id="rotationContent" aria-live="polite"></div><p class="rotation-footnote">Each character follows their own Lumnis renewal. Completion uses reports from that cycle; a passed reset needs fresh observations. Tutelage is shown separately.</p>`;
  document.querySelector('main').append(page);
  const formatter=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true,timeZoneName:'short'});
  const stamp=value=>value?formatter.format(new Date(value*1000)):'Not reported';
  const labels={done:'Finished',needs_hunting:'Needs hunting',needs_update:'Needs updated report'};
  let data=null,request=0;
  const phone=window.matchMedia('(max-width:650px)');
  $('rotationMainsGroup').open=!phone.matches;
  phone.addEventListener('change',event=>{$('rotationMainsGroup').open=!event.matches;});

  function sessionFor(row) {
    return sessions.find(s=>s.realm===row.realm&&s.character.toLowerCase()===row.character.toLowerCase())||
      {id:'rotation:'+row.realm+':'+row.character,character:row.character,realm:row.realm,running:false,attachment:'Offline',telemetry:{status:'unavailable'}};
  }
  function openProfile(row) {showDetails(sessionFor(row));}
  function addCharacter(row) {
    $('addCharacter').elements.character.value=row.character;$('addCharacter').elements.account.value=row.account;
    $('addCharacterStatus').textContent='';$('addCharacterDialog').showModal();
  }
  function stateBadge(row,main=false) {
    return text('span',main?(row.state==='done'?'Lumnis spent':row.state==='needs_hunting'?'Lumnis remaining':'Not reported'):labels[row.state],
      'rotation-badge '+row.state);
  }
  function deadline(row) {
    const block=text('div','','rotation-deadline');
    if(row.reset_passed)block.append(text('strong','Reset passed'),text('span','Update the game report'));
    else if(row.reset_at) {
      block.append(text('strong',humanDuration(row.reset_at-Date.now()/1000)+' until reset'),text('span','Renews '+stamp(row.reset_at)));
    } else block.append(text('strong','Reset not reported'),text('span','Run the reporter to establish this cycle'));
    return block;
  }
  function tutelage(row) {
    const bonus=row.bonuses||{};
    const state=characterProfiles.tutelageState(bonus);
    const words={active:'Active ×5',waiting:'Waiting for Lumnis',inactive:'Inactive',expended:'Expended this week',unavailable:'Unavailable'};
    const label=text('span','Tutelage: '+(words[state]||'Not reported'),'rotation-tutelage');
    label.title='Last reported Tutelage status. It does not affect wizard completion.';return label;
  }
  function profileButton(row) {
    if (!row.registered && row.has_profile) {
      const links=text('span','','rotation-profile-links');
      links.append(profileButton({...row,registered:true}),profileButton({...row,has_profile:false}));return links;
    }
    const button=actionButton(row.registered||row.has_profile?'Profile':'Add to roster',()=>row.registered||row.has_profile?openProfile(row):addCharacter(row),'rotation-profile',null);
    button.setAttribute('aria-label',(row.registered||row.has_profile?'Profile for ':'Add ')+row.character+' in rotation');return button;
  }
  function card(row) {
    const card=text('article','','rotation-card '+row.state+(row.urgency==='soon'?' due-soon':''));card.dataset.character=row.character;
    const header=text('header','','rotation-card-header'),identity=text('div');
    const name=actionButton(row.character,()=>row.registered||row.has_profile?openProfile(row):addCharacter(row),'rotation-character',null);
    name.setAttribute('aria-label','Inspect '+row.character+' in rotation');
    identity.append(name,text('span',row.account+' · '+(row.account_role==='utility'?'Utility':'Main account'),'rotation-account-label'));
    header.append(identity,stateBadge(row));card.append(header);
    const goal=text('div','','rotation-goal');
    const symbol=row.lumnis.done===true?'✓':row.lumnis.done===false?'○':'?';
    const stage=typeof row.lumnis.stage==='number'?'Active ×'+row.lumnis.stage:row.lumnis.stage==='ready'?'Ready to start':'Not reported';
    goal.append(text('span',symbol,'goal-check '+(row.lumnis.done?'is-done':'')),text('span','Lumnis'),text('strong',row.lumnis.done===true?'Spent this cycle':row.lumnis.done===false?stage:'Report needed'));
    card.append(goal);
    const essence=text('div','','rotation-essence'),heading=text('div','','rotation-essence-heading');
    heading.append(text('span','Weekly essence'),text('span',row.resources.done===true?'✓ Cap reached':row.resources.current?number(Math.max(0,row.resources.target-row.resources.weekly))+' to cap':'Not reported','rotation-cap-note'));
    essence.append(heading);
    const amount=text('div','','rotation-amount');amount.append(text('strong',number(row.resources.weekly),'rotation-earned'),text('span',' / '+number(row.resources.target)));
    essence.append(amount);
    const bar=document.createElement('progress');bar.max=row.resources.target;bar.value=row.resources.current?Math.min(row.resources.target,row.resources.weekly):0;
    bar.setAttribute('aria-label','Weekly essence for '+row.character);bar.setAttribute('aria-valuetext',row.resources.current?number(row.resources.weekly)+' of '+number(row.resources.target):'Current-cycle earnings not reported');
    if(!row.resources.current)essence.classList.add('unreported');essence.append(bar);
    const stored=text('div','','rotation-storage');stored.append(text('span','Stored'),text('strong',number(row.resources.total),'rotation-stored'));essence.append(stored);
    if(!row.resources.current&&row.resources.weekly!=null)essence.append(text('p','Previous report · needs this cycle’s update','rotation-old-report'));
    card.append(essence,deadline(row),tutelage(row));
    if(row.account_occupant)card.append(text('p',row.account_occupant+' is online on this account','rotation-occupant'));
    const actions=text('div','','rotation-actions');actions.append(profileButton(row));
    if(row.registered) {
      const key=row.running?'session:'+row.session_id:'character:'+row.character+':'+row.realm;
      const launch=actionButton(busy.has(key)?'Working…':row.running?'Open client':row.account_occupant?'Account in use':'Launch',()=>
        row.running?clientOperation('sessions/'+encodeURIComponent(row.session_id)+'/attach',{},key):clientOperation('launch',{character:row.character,realm:row.realm},key),'rotation-launch',null);
      launch.disabled=!row.can_launch||busy.has(key);launch.setAttribute('aria-label',(row.running?'Open client for ':'Launch ')+row.character+' from rotation');actions.append(launch);
    }
    card.append(actions);return card;
  }
  function render() {
    if(!data)return;
    const focused=document.activeElement,restore=page.contains(focused)&&!focused.closest('.rotation-filters'),focusLabel=focused?.getAttribute('aria-label');
    const summary=data.summary;
    $('rotationDone').textContent=summary.done+' / '+summary.total;$('rotationHunting').textContent=number(summary.needs_hunting);
    $('rotationSoon').textContent=number(summary.due_soon);$('rotationUnknown').textContent=number(summary.needs_update);
    $('rotationOverall').max=Math.max(1,summary.total);$('rotationOverall').value=summary.done;
    $('rotationOverall').setAttribute('aria-valuetext',summary.done+' of '+summary.total+' wizards finished');
    $('rotationNavCount').textContent=summary.done+'/'+summary.total;
    $('rotationEssenceCoverage').textContent=number(summary.weekly_earned)+' essence reported · '+summary.resource_reports+'/'+summary.total+' current reports';
    const selectedAccount=$('rotationAccount').value;
    const names=[...new Set([...data.mains,...data.wizards].map(r=>r.account))].sort();
    const options=text('option','All accounts');options.value='';$('rotationAccount').replaceChildren(options);
    for(const name of names){const option=text('option',name);option.value=name;$('rotationAccount').append(option);}
    if(names.includes(selectedAccount))$('rotationAccount').value=selectedAccount;
    const mains=$('rotationMains');mains.replaceChildren();
    for(const row of data.mains) {
      const main=text('article','','rotation-main'),header=text('div','','rotation-main-heading');
      header.append(text('h4',row.character),profileButton(row));
      main.append(header,text('p',row.account,'rotation-account-label'),stateBadge(row,true),deadline(row),tutelage(row));mains.append(main);
    }
    const out=$('rotationContent');out.replaceChildren();
    if(!data.configured){out.append(emptyState('No weekly rotation configured','Your main characters and enchanting crew will appear here once the rotation is set up.'));return;}
    const query=$('rotationSearch').value.trim().toLowerCase(),state=$('rotationState').value,account=$('rotationAccount').value;
    const rows=data.wizards.filter(r=>(state==='all'||r.state===state)&&(!account||r.account===account)&&(r.character+' '+r.account).toLowerCase().includes(query));
    const groups=$('rotationGroup').checked?names.map(name=>[name,rows.filter(r=>r.account===name)]):
      [['Hunt next',rows.filter(r=>r.state==='needs_hunting')],['Needs updated report',rows.filter(r=>r.state==='needs_update')],['Finished this cycle',rows.filter(r=>r.state==='done')]];
    for(const [name,items] of groups) {
      if(!items.length)continue;
      const group=text('section','',$('rotationGroup').checked?'rotation-account-group':'rotation-status-group');
      const header=text('div','','rotation-group-heading');header.append(text('h4',name),text('span',items.length+' wizard'+(items.length===1?'':'s')));group.append(header);
      const grid=text('div','','rotation-grid');items.forEach(row=>grid.append(card(row)));group.append(grid);out.append(group);
    }
    if(!rows.length)out.append(emptyState('No wizards match','Change the account, status or search filter.'));
    if(restore&&focusLabel)[...page.querySelectorAll('[aria-label]')].find(node=>node.getAttribute('aria-label')===focusLabel)?.focus({preventScroll:true});
  }
  async function load() {
    if(!active||currentView!=='rotation')return;
    const id=++request,realm=$('rotationRealm').value;
    try {
      const result=await api('rotation?realm='+encodeURIComponent(realm));
      if(!active||id!==request||currentView!=='rotation'||realm!==$('rotationRealm').value)return;
      data=result;$('rotationError').hidden=true;render();
    } catch(error) {if(id===request&&currentView==='rotation'){$('rotationError').textContent='Could not update rotation: '+error.message;$('rotationError').hidden=false;}}
  }
  const previousSetTab=setTab;
  setTab=function(tab) {
    previousSetTab(tab);page.hidden=tab!=='rotation';$('rotationTab').setAttribute('aria-current',tab==='rotation'?'page':'false');
    if(tab==='rotation'){$('breadcrumb').textContent='Weekly rotation';$('clientToolbar').hidden=false;load();}
    else ++request;
  };
  $('rotationTab').onclick=()=>setTab('rotation');$('rotationRefresh').onclick=load;
  $('rotationRealm').onchange=load;
  for(const id of ['rotationState','rotationAccount','rotationGroup','rotationSearch'])$(id).addEventListener('input',render);
  const defaultView=$('settingsForm').elements.default_view,option=text('option','Weekly rotation');option.value='rotation';defaultView.append(option);
  const previousRefresh=refresh;refresh=async function(){await previousRefresh();if(active&&currentView==='rotation')await load();};
  $('logout').addEventListener('click',()=>{++request;data=null;$('rotationMains').replaceChildren();$('rotationContent').replaceChildren();$('rotationNavCount').textContent='';});
})();
