/* Side-by-side evidence for two explicit character/realm identities. */
(() => {
  const single=renderDetail;
  let request=0;
  const label=value=>value.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
  const stamp=value=>value?new Date(value*1000).toLocaleString():'Not yet reported';
  const identity=profile=>profile.character+' · '+label(profile.realm);
  const lumnis=value=>typeof value==='number'?'Active ×'+value:
    ({expired:'Exhausted',ready:'Ready to start',unavailable:'Unavailable',unknown:'Unknown'}[value]||'—');

  function table(profiles,rows,caption,parent) {
    const wrap=text('div','','table-scroll comparison-scroll');wrap.tabIndex=0;
    wrap.setAttribute('role','region');wrap.setAttribute('aria-label',caption);
    const table=text('table','','profile-table comparison-table');table.append(text('caption',caption));
    const head=text('thead'),heading=text('tr');
    for(const name of ['Measure',...profiles.map(identity)]){const cell=text('th',name);cell.scope='col';heading.append(cell);}
    head.append(heading);table.append(head);
    const body=text('tbody');
    for(const [name,...values] of rows){const row=text('tr'),heading=text('th',name);heading.scope='row';row.append(heading);for(const value of values)row.append(text('td',number(value)));body.append(row);}
    table.append(body);wrap.append(table);parent.append(wrap);
  }

  function observed(profiles,section,field,parent) {
    const note=text('div','','comparison-observations');
    for(const profile of profiles)note.append(text('p',identity(profile)+' · Last observed: '+stamp(
      field?profile.field_observed_at?.[section]?.[field]:profile.observed_at?.[section]),'profile-note'));
    parent.append(note);
  }

  function build(profiles,history) {
    const content=$('detailContent');
    const focus=document.activeElement,focusKey=content.contains(focus)?focus.dataset.focusId:null;
    content.replaceChildren();
    const summary=text('p','Comparing last reported values. A dash means not reported; zero is a reported value.','profile-note');
    content.append(summary);
    const identities=text('div','','comparison-identities');
    for(const profile of profiles) {
      const session=characterProfiles.sessionFor(profile.character,profile.realm);
      identities.append(text('span',identity(profile)+' · '+(session.running?'Online':'Offline')+
        (profile.updated_at?'':' · Not yet reported')));
    }
    content.append(identities);
    const values=fn=>profiles.map(p=>fn(p.snapshot||{}));
    if(detailSection==='overview') {
      const definitions=[['Character','character',[
        ['Profession',d=>d.character?.profession],['Level',d=>d.character?.level],['Race',d=>d.character?.race]]],
        ['Profession resources','resources',[
          ['Resource type',d=>d.resources?.type],['Earned this cycle (weekly)',d=>d.resources?.weekly],
          ['Total stored',d=>d.resources?.total],['Weekly cap',d=>d.resources?.max_weekly],['Storage cap',d=>d.resources?.max_total]]],
        ['Experience bonuses','bonuses',[
          ['Lumnis phase',d=>lumnis(d.bonuses?.lumnis_stage)],['Phase points remaining',d=>d.bonuses?.lumnis_points_remaining],
          ['Future cycles prepaid',d=>d.bonuses?.lumnis_donations],
          ['Reported renewal',d=>d.bonuses?.lumnis_reset_at?stamp(d.bonuses.lumnis_reset_at):null],
          ['Tutelage status',d=>({active:'Active ×5',waiting:'Waiting for Lumnis',inactive:'Inactive',expended:'Expended for the week',unavailable:'Unavailable',unknown:'Not reported'}[characterProfiles.tutelageState(d.bonuses||{})])],['Tutelage days remaining',d=>d.bonuses?.fashlonae_days_remaining]]]];
      for(const [title,section,rows] of definitions){const group=inspectorSection(title,content);observed(profiles,section,null,group);table(profiles,rows.map(([name,fn])=>[name,...values(fn)]),title,group);}
      const details=text('details','','profile-disclosure');details.append(text('summary','Field observation times'));
      for(const section of ['resources','bonuses']){
        const keys=[...new Set(profiles.flatMap(p=>Object.keys(p.field_observed_at?.[section]||{})))].sort();
        table(profiles,keys.map(key=>[label(key),...profiles.map(p=>stamp(p.field_observed_at?.[section]?.[key]))]),label(section)+' observations',details);
      }
      content.append(details,text('p','Weekly earnings are separate from stored balances. Different resource types are not interchangeable. Passed renewals need a new game observation; values here are not reset automatically. Choose No comparison for full live status, training, effects and cycle details.','detail-note'));
    } else if(detailSection==='stats') {
      const controls=text('div','','profile-filters'),field=text('label','Stat values'),select=document.createElement('select');
      for(const value of ['base','normal','enhanced']){const option=text('option',label(value));option.value=value;select.append(option);}
      select.setAttribute('aria-label','Stat values');select.value=comparisonBasis;select.dataset.focusId='comparison-basis';select.onchange=()=>{comparisonBasis=select.value;build(profiles,history);document.dispatchEvent(new Event('gempy:scope'));};field.append(select);controls.append(field);content.append(controls);
      observed(profiles,'stats',null,content);
      const fields=comparisonBasis==='normal'?['value','bonus']:[comparisonBasis+'_value',comparisonBasis+'_bonus'];
      const keys=[...new Set(profiles.flatMap(p=>Object.keys(p.snapshot?.stats||{})))];
      const rows=keys.map(key=>[label(key),...values(d=>{const value=d.stats?.[key];return value?number(value[fields[0]])+' (bonus '+number(value[fields[1]])+')':null;})]);
      table(profiles,rows,label(comparisonBasis)+' stats · Value (bonus)',content);
      if(!rows.length)content.append(text('p','Stats have not been reported for either character.','profile-note'));
    } else if(detailSection==='skills') {
      observed(profiles,'skills',null,content);
      const controls=text('div','','profile-filters'),search=document.createElement('input');search.type='search';search.setAttribute('aria-label','Find a skill');search.placeholder='Find a skill…';search.value=characterProfiles.skillQuery;
      search.dataset.focusId='comparison-skill';
      const field=text('label','Show untrained'),check=document.createElement('input');check.type='checkbox';check.checked=characterProfiles.showUntrained;check.dataset.focusId='comparison-untrained';field.prepend(check);
      const results=text('div');
      function draw() {
        results.replaceChildren();
        const keys=[...new Set(profiles.flatMap(p=>Object.keys(p.snapshot?.skills||{})))].sort().filter(key=>
          label(key).toLowerCase().includes(characterProfiles.skillQuery.toLowerCase())&&
          (characterProfiles.showUntrained||profiles.some(p=>p.snapshot?.skills?.[key]?.ranks>0)));
        const rows=keys.map(key=>[label(key),...values(d=>{const skill=d.skills?.[key];return skill?number(skill.ranks)+' ranks · '+number(skill.bonus)+' bonus'+(skill.category==='spell_research'?' · Spell research':''):null;})]);
        table(profiles,rows,'Skills · Reported ranks and bonuses',results);
        if(!rows.length)results.append(text('p','No matching reported skills. Change your search or show untrained skills.','profile-note'));
      }
      search.oninput=()=>{characterProfiles.skillQuery=search.value;draw();};check.onchange=()=>{characterProfiles.showUntrained=check.checked;draw();};controls.append(search,field);content.append(controls,results);draw();
    } else if(detailSection==='history') {
      const controls=text('div','','profile-filters'),field=text('label','Character history period'),select=document.createElement('select');
      for(const [value,name] of [['day','Today'],['week','This week'],['month','This month'],['year','This year'],['custom','Custom range']]){const option=text('option',name);option.value=value;select.append(option);}
      select.setAttribute('aria-label','Character history period');select.value=detailHistoryPeriod;select.dataset.focusId='comparison-period';select.onchange=()=>{detailHistoryPeriod=select.value;renderDetail();document.dispatchEvent(new Event('gempy:scope'));};field.append(select);controls.append(field);
      if(detailHistoryPeriod==='custom')for(const [name,value,set] of [['History range start',detailHistoryStart,v=>detailHistoryStart=v],['History range end',detailHistoryEnd,v=>detailHistoryEnd=v]]){
        const field=text('label',name),input=document.createElement('input');input.type='date';input.value=value;input.onchange=()=>{set(input.value);renderDetail();document.dispatchEvent(new Event('gempy:scope'));};field.append(input);controls.append(field);
      }
      content.append(controls);
      if(!history){content.append(text('p','Choose a valid start and end date.','detail-note'));return;}
      content.append(text('p',historyScope(history),'history-scope'));
      const records=profiles.map(p=>history.characters.find(row=>row.realm===p.realm&&row.character.toLowerCase()===p.character.toLowerCase()));
      table(profiles,[['Normal XP','normal_xp'],['Ascension XP','ascension_xp'],['Combined XP','total_xp'],['ATP equivalent','atp_equivalent'],['Coverage','coverage']].map(([name,key])=>[name,...records.map(row=>row?.[key])]),'Experience gained in the same period',content);
      content.append(text('p','Observed = sampled counters; imported = source totals; gap = gains span missing reports. A dash means no history for this period.','detail-note'));
    }
    if(focusKey)[...content.querySelectorAll('[data-focus-id]')].find(node=>node.dataset.focusId===focusKey)?.focus({preventScroll:true});
  }

  renderDetail=async function() {
    const id=++request;
    if(!comparisonIdentity)return single();
    ++detailRequest;
    const primary=detailSession, [realm,name]=comparisonIdentity.split(':');
    for(const button of document.querySelectorAll('[data-detail]'))button.setAttribute('aria-pressed',String(button.dataset.detail===detailSection));
    $('detailSubtitle').textContent=primary.realm+' · '+accountFor(primary.character)+' · Comparing with '+name+' · '+realm;
    const signature=[primary.realm,primary.character,comparisonIdentity,detailSection,historyQuery()].join('|');
    const content=$('detailContent');
    if(content.dataset.comparison!==signature){content.replaceChildren(text('p','Loading comparison…','profile-note'));content.dataset.comparison=signature;}
    try {
      const validPeriod=detailHistoryPeriod!=='custom'||(detailHistoryStart&&detailHistoryEnd&&detailHistoryStart<=detailHistoryEnd);
      const [first,second,history]=await Promise.all([
        api('profiles/'+encodeURIComponent(primary.realm)+'/'+encodeURIComponent(primary.character)),
        api('profiles/'+encodeURIComponent(realm)+'/'+encodeURIComponent(name)),
        detailSection==='history'&&validPeriod?api('progress?'+historyQuery()):null]);
      if(id!==request||!active||!$('characterDetails').open)return;
      build([first,second],history);
    } catch(error) {
      if(id===request&&active&&$('characterDetails').open)content.replaceChildren(text('p','Could not load comparison: '+error.message,'profile-note'),actionButton('Retry comparison',()=>renderDetail(),'secondary',null));
    }
  };
  $('characterDetails').addEventListener('close',()=>{++request;delete $('detailContent').dataset.comparison;});
})();
