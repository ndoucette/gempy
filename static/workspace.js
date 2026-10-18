/* Navigation state and entry points shared by the existing task views. */
(() => {
  const sidebar=document.querySelector('.sidebar');
  let sidebarCollapsed=false;
  try{sidebarCollapsed=localStorage.getItem('gempy.sidebarCollapsed')==='true';}catch{}
  const sidebarToggle=actionButton('',()=>{
    sidebarCollapsed=!sidebarCollapsed;
    renderSidebar();
    try{localStorage.setItem('gempy.sidebarCollapsed',String(sidebarCollapsed));}catch{}
  },'sidebar-toggle','arrow');
  sidebar.id='mainSidebar';sidebarToggle.id='sidebarToggle';
  sidebarToggle.setAttribute('aria-controls','mainSidebar');
  sidebar.prepend(sidebarToggle);
  function renderSidebar() {
    document.documentElement.classList.toggle('sidebar-collapsed',sidebarCollapsed);
    const label=sidebarCollapsed?'Expand sidebar':'Collapse sidebar';
    sidebarToggle.setAttribute('aria-label',label);
    sidebarToggle.setAttribute('aria-expanded',String(!sidebarCollapsed));
    sidebarToggle.title=label;
  }
  for(const [id,label] of [['sessionsTab','Live'],['rotationTab','Rotation'],['progressTab','Progress'],['charactersTab','Characters'],['settingsTab','Settings'],['logout','Log out']])$(id).title=label;
  renderSidebar();
  const views=new Set(['sessions','rotation','progress','characters','settings']);
  const sections=new Set(['overview','stats','skills','history']);
  const periods=new Set(['day','week','month','year','custom']);
  const fields=['search','accountFilter',
    'progressPeriod','progressStart','progressEnd','progressRealm','progressAccount','progressSearch',
    'rotationSearch','rotationState','rotationAccount','rotationRealm','rotationGroup'];
  let restoring=false,booting=true,ignoreClose=false,handledClose=false,returnFocus=null;
  const title=value=>value.charAt(0).toUpperCase()+value.slice(1);
  const identity=session=>session.realm+':'+session.character;
  function parseIdentity(value) {
    const match=/^(prime|test|fallen):([A-Za-z]{1,50})$/.exec(value||'');
    return match?characterProfiles.sessionFor(match[2],match[1]):null;
  }
  function savedFilters() {
    try{
      const state=JSON.parse(sessionStorage.getItem('gempy.workspace')||'{}');
      return state&&typeof state==='object'&&!Array.isArray(state)?state:{};
    }catch{return {};}
  }
  function saveFilters() {
    if(booting)return;
    const state={realm,progressSort,progressSortDirection};
    for(const id of fields){const el=$(id);state[id]=el.type==='checkbox'?el.checked:el.value;}
    try{sessionStorage.setItem('gempy.workspace',JSON.stringify(state));}catch{}
  }
  function restoreFilters() {
    const state=savedFilters();
    for(const id of fields){
      const el=$(id);
      // Rotation options arrive with its data, after startup restoration.
      if(id==='rotationAccount'&&state[id]&&!Array.from(el.options).some(option=>option.value===state[id])){
        const option=text('option',state[id]);option.value=state[id];el.append(option);
      }
      if(typeof state[id]==='string')el.value=state[id];else if(el.type==='checkbox'&&typeof state[id]==='boolean')el.checked=state[id];
    }
    if(['prime','test'].includes(state.realm)){
      realm=state.realm;
      for(const button of document.querySelectorAll('[data-realm]'))button.setAttribute('aria-pressed',String(button.dataset.realm===realm));
      $('testBanner').hidden=realm!=='test';
    }
    if(['character','realm','normal_xp','ascension_xp','total_xp','atp_equivalent','coverage'].includes(state.progressSort))progressSort=state.progressSort;
    if([1,-1].includes(state.progressSortDirection))progressSortDirection=state.progressSortDirection;
  }

  function selector(label,id) {
    const field=text('label',label,'workspace-field'),select=document.createElement('select');select.id=id;select.setAttribute('aria-label',label);field.append(select);return field;
  }
  const controls=text('div','','profile-controls');controls.id='profileControls';
  controls.append(selector('Character to inspect','inspectCharacter'),selector('Compare with','compareCharacter'));
  $('detailTabs').before(controls);
  const status=text('p','','workspace-status');status.setAttribute('role','status');
  controls.append(status);

  function fill(select,items,placeholder,value) {
    const signature=JSON.stringify(items.map(item=>[identity(item),accountFor(item.character)]));
    if(select.dataset.options!==signature){
      select.replaceChildren();
      if(placeholder){const option=text('option',placeholder);option.value='';select.append(option);}
      for(const gameRealm of ['prime','test','fallen']){
        const group=document.createElement('optgroup');group.label=title(gameRealm);
        for(const item of items.filter(item=>item.realm===gameRealm)){
          const option=text('option',item.character+' · '+title(gameRealm)+(accountFor(item.character)?' · '+accountFor(item.character):''));
          option.value=identity(item);group.append(option);
        }
        if(group.children.length)select.append(group);
      }
      select.dataset.options=signature;
    }
    select.value=value;
  }
  function updateSelectors() {
    const items=characterProfiles.choices();
    const comparison=parseIdentity(comparisonIdentity);
    if(comparison&&!items.some(item=>identity(item).toLowerCase()===comparisonIdentity.toLowerCase()))items.push(comparison);
    if(detailSession){
      fill($('inspectCharacter'),items,null,identity(detailSession));
      fill($('compareCharacter'),items.filter(item=>identity(item).toLowerCase()!==identity(detailSession).toLowerCase()),'No comparison',comparisonIdentity);
      const description='Inspecting '+detailSession.character+' in '+title(detailSession.realm)+(comparison?' compared with '+comparison.character+' in '+title(comparison.realm):'');
      if(status.textContent!==description)status.textContent=description;
    }
    $('characterDetails').classList.toggle('is-comparing',!!comparisonIdentity);
  }
  $('inspectCharacter').onchange=()=>{const session=parseIdentity($('inspectCharacter').value);if(session)showDetails(session,detailSection);};
  $('compareCharacter').onchange=()=>{
    comparisonIdentity=$('compareCharacter').value;
    delete $('detailContent').dataset.comparison;
    updateSelectors();renderDetail();writeRoute();
  };

  function writeRoute(replace=false) {
    if(restoring||booting||!active)return;
    const params=new URLSearchParams({view:currentView});
    if($('characterDetails').open&&detailSession){
      params.set('character',identity(detailSession));params.set('section',detailSection);
      if(comparisonIdentity){params.set('compare',comparisonIdentity);params.set('basis',comparisonBasis);}
      params.set('period',detailHistoryPeriod);
      if(detailHistoryPeriod==='custom'){params.set('start',detailHistoryStart);params.set('end',detailHistoryEnd);}
    }
    const hash='#'+params.toString();
    if(location.hash!==hash)history[replace?'replaceState':'pushState'](null,'',hash);
    saveFilters();
  }
  function applyRoute() {
    if(!active)return;
    restoring=true;
    try {
      const params=new URLSearchParams(location.hash.slice(1));
      setTab(views.has(params.get('view'))?params.get('view'):currentView);
      const session=parseIdentity(params.get('character'));
      if(session){
        const comparison=parseIdentity(params.get('compare'));
        comparisonIdentity=comparison&&identity(comparison).toLowerCase()!==identity(session).toLowerCase()?identity(comparison):'';
        comparisonBasis=['base','normal','enhanced'].includes(params.get('basis'))?params.get('basis'):'normal';
        if(periods.has(params.get('period')))detailHistoryPeriod=params.get('period');
        detailHistoryStart=/^\d{4}-\d{2}-\d{2}$/.test(params.get('start')||'')?params.get('start'):'';
        detailHistoryEnd=/^\d{4}-\d{2}-\d{2}$/.test(params.get('end')||'')?params.get('end'):'';
        showDetails(session,sections.has(params.get('section'))?params.get('section'):'overview');
      } else if($('characterDetails').open){ignoreClose=true;$('characterDetails').close();comparisonIdentity='';}
    } finally {restoring=false;}
    writeRoute(true);
  }
  const originalTab=setTab;
  setTab=function(tab){originalTab(tab);writeRoute();};
  const originalShow=showDetails;
  showDetails=function(session,section='overview') {
    if(!$('characterDetails').open){
      returnFocus={node:document.activeElement,id:document.activeElement?.id,label:document.activeElement?.getAttribute('aria-label')};
      if(!restoring)comparisonIdentity='';
    }
    if(comparisonIdentity.toLowerCase()===identity(session).toLowerCase())comparisonIdentity='';
    originalShow(session,section);
    updateSelectors();writeRoute();
  };
  for(const button of document.querySelectorAll('[data-detail]'))button.addEventListener('click',()=>writeRoute());
  document.addEventListener('gempy:scope',()=>writeRoute(true));
  function restoreFocus() {
    let target=returnFocus?.node;
    if(!target?.isConnected)target=returnFocus?.id?$(returnFocus.id):[...document.querySelectorAll('[aria-label]')].find(node=>node.getAttribute('aria-label')===returnFocus?.label);
    (target||$(currentView+'Tab'))?.focus({preventScroll:true});
  }
  function closeProfile() {
    handledClose=true;
    $('characterDetails').close();comparisonIdentity='';updateSelectors();writeRoute();restoreFocus();
  }
  $('detailClose').onclick=closeProfile;
  $('characterDetails').addEventListener('cancel',event=>{event.preventDefault();closeProfile();});
  $('characterDetails').addEventListener('close',()=>{
    if(handledClose){handledClose=false;return;}
    if($('characterDetails').open)return;
    comparisonIdentity='';updateSelectors();
    if(ignoreClose){ignoreClose=false;return;}
    writeRoute();
    if(document.activeElement===document.body)restoreFocus();
  });
  window.addEventListener('popstate',applyRoute);
  window.addEventListener('hashchange',()=>{if(active)applyRoute();});

  const originalCharacters=renderCharacters;
  renderCharacters=function(){
    const focus=document.activeElement,focusId=focus?.dataset.focusId;
    originalCharacters();updateSelectors();
    if(!$('accounts').querySelector('.character')&&($('search').value||$('accountFilter').value))
      $('accounts').append(actionButton('Clear roster filters',()=>{ $('search').value='';$('accountFilter').value='';saveFilters();renderCharacters(); },'secondary',null));
    if(focusId)[...$('accounts').querySelectorAll('[data-focus-id]')].find(node=>node.dataset.focusId===focusId)?.focus({preventScroll:true});
  };
  const originalProgress=renderProgress;
  renderProgress=function(){
    originalProgress();
    const filtered=$('progressSearch').value||$('progressAccount').value||$('progressRealm').value;
    if(progressData?.characters?.length&&filtered&&!$('progressContent').querySelector('tbody tr')){
      const empty=$('progressContent').querySelector('.empty');
      empty?.replaceChildren(text('h3','No characters match these filters'),text('p','Recorded history is available. Clear the filters to see it.'),
        actionButton('Clear progress filters',()=>{for(const id of ['progressSearch','progressAccount','progressRealm'])$(id).value='';saveFilters();renderProgress();},'secondary',null));
    }
    saveFilters();
  };
  // Earlier handlers captured the undecorated renderers. Resolve at interaction
  // time so searches keep profile actions, balances and empty-state recovery.
  $('search').oninput=()=>renderCharacters();
  $('accountFilter').onchange=()=>renderCharacters();
  $('progressSearch').oninput=()=>renderProgress();
  $('progressAccount').onchange=()=>renderProgress();
  $('progressRealm').onchange=()=>renderProgress();
  for(const id of fields)for(const event of ['input','change'])$(id).addEventListener(event,saveFilters);
  for(const button of document.querySelectorAll('[data-realm]'))button.addEventListener('click',saveFilters);
  const originalStart=start;
  start=async function(){
    booting=true;$('app').inert=true;
    try {await originalStart();restoreFilters();renderCharacters();renderSessions();updateSelectors();}
    finally {booting=false;$('app').inert=false;}
    applyRoute();
  };
  $('logout').addEventListener('click',()=>{comparisonIdentity='';returnFocus=null;});
  updateSelectors();
})();
