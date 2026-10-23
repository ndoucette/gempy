/* All-character overview: durable observations, independent of live sessions. */
const characterStatus = (() => {
  const columns = [['name','Name'],['level','Level'],['account','Account'],['profession','Profession'],
    ['reset','Lumnis Reset'],['active','Lumnis Active'],['weekly','Weekly Resource Cap Progress'],
    ['tutelage','Tutelage'],['total','Total Resource'],['suffused','Suffused Resource'],['bank','Bank Balance'],['deeds','Deeds']];
  const numeric = value => typeof value==='number' && Number.isFinite(value) && value>=0 ? value : null;
  function rows(accounts, profiles, realm, now=Date.now()/1000) {
    const lookup=new Map(profiles.filter(p=>p.realm===realm).map(p=>[p.character.toLowerCase(),p]));
    return Object.entries(accounts).flatMap(([account,names])=>names.map(name=>{
      const profile=lookup.get(name.toLowerCase())||{}, data=profile.snapshot||{};
      const bonuses=data.bonuses||{}, resource=data.resources||{}, wealth=data.wealth||{};
      const stage=bonuses.lumnis_stage, resetAt=numeric(bonuses.lumnis_reset_at);
      const passed=resetAt>0&&resetAt<=now&&(profile.field_observed_at?.bonuses?.lumnis_stage||0)<resetAt;
      const active=passed?null:[2,3,4,5].includes(stage)?stage:['ready','expired'].includes(stage)?0:null;
      const reset=stage==='unavailable'?null:stage==='ready'||passed?0:resetAt>now?resetAt-now:null;
      const state=bonuses.fashlonae_state;
      const tutelage=['active','inactive','expended','eligible'].includes(state)?true:['unavailable','ineligible'].includes(state)?false:null;
      const reported=numeric(resource.weekly), earned=reset===0&&reported!==null?0:reported, cap=numeric(resource.max_weekly);
      return {name,account,realm,profile,level:numeric(data.character?.level),profession:data.character?.profession||null,
        reset,active,tutelage,earned,cap,weekly:earned!==null&&cap>0?earned/cap:null,
        total:numeric(resource.total),suffused:numeric(resource.suffused),bank:numeric(wealth.bank_balance),deeds:numeric(wealth.deeds)};
    }));
  }
  function select(rows, filters={}, sort='name', direction=1) {
    const query=(filters.query||'').trim().toLowerCase();
    const range=row=>{
      if(!['level','reset','active','weekly','total','suffused','bank','deeds'].includes(filters.rangeField))return true;
      const lower=filters.rangeMin!==''&&filters.rangeMin!=null?Number(filters.rangeMin):null;
      const upper=filters.rangeMax!==''&&filters.rangeMax!=null?Number(filters.rangeMax):null;
      if(lower===null&&upper===null)return true;
      const raw=row[filters.rangeField],value=filters.rangeField==='weekly'?raw*100:filters.rangeField==='reset'?raw/3600:raw;
      return raw!==null&&(lower===null||value>=lower)&&(upper===null||value<=upper);
    };
    return rows.filter(row=>(!query||[row.name,row.account,row.profession].join(' ').toLowerCase().includes(query))&&
      (!filters.account||row.account===filters.account)&&(!filters.profession||row.profession===filters.profession)&&
      (!filters.lumnis||(filters.lumnis==='active'?row.active>0:filters.lumnis==='ready'?row.reset===0:filters.lumnis==='inactive'?row.active===0:row.active===null&&row.reset!==0))&&
      (!filters.tutelage||(filters.tutelage==='yes'?row.tutelage===true:filters.tutelage==='no'?row.tutelage===false:row.tutelage===null))&&range(row))
      .sort((a,b)=>{
        const av=a[sort],bv=b[sort];
        if(av==null||bv==null)return av==null&&bv==null?a.name.localeCompare(b.name):av==null?1:-1;
        const comparison=typeof av==='string'?av.localeCompare(bv,undefined,{numeric:true,sensitivity:'base'}):Number(av)-Number(bv);
        return comparison*direction||a.name.localeCompare(b.name);
      });
  }
  function createLoader(fetcher,apply,fail){
    let pending=null;
    return {
      load(scope){
        if(pending?.scope===scope)return pending.promise;
        const entry={scope};pending=entry;
        entry.promise=Promise.resolve().then(()=>fetcher(scope)).then(
          result=>{if(pending===entry)apply(result,scope);},
          error=>{if(pending===entry)fail(error,scope);}
        ).finally(()=>{if(pending===entry)pending=null;});
        return entry.promise;
      },
      invalidate(){pending=null;}
    };
  }
  return {columns,rows,select,createLoader};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=characterStatus;
if(typeof document!=='undefined')(() => {
  const page=text('section');page.id='status';page.hidden=true;page.setAttribute('aria-labelledby','statusHeading');
  page.innerHTML=`<div class="page-heading"><div><h2 id="statusHeading">Character status</h2><p>Your whole roster, at a glance.</p></div><button id="statusRefresh" class="secondary" type="button">Refresh</button></div>
    <div class="status-filters">
      <label class="status-search">Search<input id="statusSearch" type="search" placeholder="Name, account or profession"></label>
      <label>Account<select id="statusAccount"><option value="">All accounts</option></select></label>
      <label>Profession<select id="statusProfession"><option value="">All professions</option></select></label>
      <label>Lumnis<select id="statusLumnis"><option value="">All Lumnis</option><option value="ready">Ready</option><option value="active">Active</option><option value="inactive">Inactive</option><option value="unknown">Unknown</option></select></label>
      <label>Tutelage<select id="statusTutelage"><option value="">All Tutelage</option><option value="yes">Has Tutelage</option><option value="no">No Tutelage</option><option value="unknown">Unknown</option></select></label>
      <label>Realm<select id="statusRealm"><option value="prime">Prime</option><option value="test">Test</option></select></label>
      <button id="statusClear" class="secondary" type="button">Clear filters</button>
    </div>
    <details class="status-range"><summary>Numeric filter</summary><div class="status-filters">
      <label>Column<select id="statusRangeField"><option value="">No numeric filter</option><option value="level">Level</option><option value="reset">Lumnis reset (hours)</option><option value="active">Lumnis multiplier</option><option value="weekly">Weekly completion (%)</option><option value="total">Total resource</option><option value="suffused">Suffused resource</option><option value="bank">Bank balance</option><option value="deeds">Deeds</option></select></label>
      <label>Minimum<input id="statusRangeMin" type="number" min="0" step="any" placeholder="No minimum"></label>
      <label>Maximum<input id="statusRangeMax" type="number" min="0" step="any" placeholder="No maximum"></label></div></details>
    <div class="status-summary"><span id="statusCount" role="status"></span><span>Latest reported values · Hover a value for its observation time</span></div>
    <p id="statusError" role="alert" hidden></p>
    <div class="status-scroll" role="region" aria-label="Character status table, scroll horizontally for more columns" tabindex="0">
      <table class="status-table"><caption class="status-sr-only">All configured characters in the selected realm</caption><thead><tr id="statusHeaders"></tr></thead><tbody id="statusRows"></tbody></table>
    </div><p id="statusEmpty" hidden></p><p class="status-note">— means not reported. Values remain available between sessions; a passed Lumnis reset is shown as Ready until a new game report arrives.</p>`;
  document.querySelector('main').append(page);
  const nav=actionButton('Status',()=>setTab('status'),'nav-button',null);nav.id='statusTab';nav.title='Status';nav.prepend(icon('characters-icon',20));
  $('rotationTab').before(nav);
  const fieldIds={query:'statusSearch',account:'statusAccount',profession:'statusProfession',lumnis:'statusLumnis',tutelage:'statusTutelage',realm:'statusRealm',rangeField:'statusRangeField',rangeMin:'statusRangeMin',rangeMax:'statusRangeMax'};
  let state={query:'',account:'',profession:'',lumnis:'',tutelage:'',realm:'prime',sort:'name',direction:1,rangeField:'',rangeMin:'',rangeMax:''};
  try{const saved=JSON.parse(sessionStorage.getItem('gempy.status')||'{}');for(const key of Object.keys(state))if(typeof saved[key]===typeof state[key])state[key]=saved[key];}catch{}
  if(!['prime','test'].includes(state.realm))state.realm='prime';
  if(!characterStatus.columns.some(([key])=>key===state.sort))state.sort='name';
  if(![1,-1].includes(state.direction))state.direction=1;
  for(const key of ['lumnis','tutelage','rangeField'])if(![...$(fieldIds[key]).options].some(o=>o.value===state[key]))state[key]='';
  const save=()=>{try{sessionStorage.setItem('gempy.status',JSON.stringify(state));}catch{}};
  let profiles=[],loaded=false;
  page.querySelector('.status-range').open=!!state.rangeField;
  const headers=new Map();
  for(const [key,label] of characterStatus.columns){
    const th=text('th');th.scope='col';th.dataset.column=key;
    const button=actionButton(label,()=>{state.direction=state.sort===key?-state.direction:1;state.sort=key;save();render();},'status-sort',null);
    button.setAttribute('aria-label','Sort by '+label);th.append(button);$('statusHeaders').append(th);headers.set(key,th);
  }
  function options(id,values,label,selected){
    const valuesSorted=[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b));
    // Preserve the user's filter even when its matching data disappears.
    if(selected&&!valuesSorted.includes(selected))valuesSorted.push(selected);
    const select=$(id),signature=JSON.stringify(valuesSorted);
    if(select.dataset.options!==signature){
      const option=text('option',label);option.value='';select.replaceChildren(option);
      for(const value of valuesSorted){const opt=text('option',value);opt.value=value;select.append(opt);}
      select.dataset.options=signature;
    }
    select.value=selected;
  }
  const observationFields={level:['character','level'],profession:['character','profession'],reset:['bonuses','lumnis_reset_at'],active:['bonuses','lumnis_stage'],weekly:['resources','weekly'],tutelage:['bonuses','fashlonae_state'],total:['resources','total'],suffused:['resources','suffused'],bank:['wealth','bank_balance'],deeds:['wealth','deeds']};
  function observe(cell,row,key){
    const [section,field]=observationFields[key]||[];
    if(!section)return;
    const time=row.profile.field_observed_at?.[section]?.[field];
    cell.title=time?'Last observed: '+new Date(time*1000).toLocaleString():'Not yet reported';
    if(key==='weekly'&&row.reset===0&&row.earned!==null)cell.title='Lumnis is ready. Weekly earnings reset on the next XP gain; showing 0 for the new cycle. '+cell.title;
  }
  function square(value,label){
    const wrap=text('span','','status-indicator');wrap.setAttribute('aria-label',label);wrap.title=label;
    const dot=text('span','','status-square '+(value===null?'is-unknown':value?'is-on':'is-off'));dot.setAttribute('aria-hidden','true');wrap.append(dot);return wrap;
  }
  function render(){
    const all=characterStatus.rows(accounts,profiles,state.realm),rows=characterStatus.select(all,state,state.sort,state.direction);
    options('statusAccount',Object.keys(accounts),'All accounts',state.account);
    options('statusProfession',all.map(r=>r.profession),'All professions',state.profession);
    for(const [key,th] of headers){th.setAttribute('aria-sort',state.sort===key?(state.direction===1?'ascending':'descending'):'none');}
    const focused=document.activeElement,focusName=focused?.dataset.statusCharacter;
    const body=$('statusRows'),fragment=document.createDocumentFragment();
    for(const row of rows){
      const tr=text('tr');tr.dataset.character=row.name;
      for(const [key] of characterStatus.columns){
        const cell=text(key==='name'?'th':'td');cell.dataset.column=key;observe(cell,row,key);
        if(key==='name'){
          cell.scope='row';const button=actionButton(row.name,()=>showDetails(characterProfiles.sessionFor(row.name,row.realm)),'status-name',null);
          button.dataset.statusCharacter=row.name;button.setAttribute('aria-label','Inspect '+row.name);cell.append(button);
        }else if(key==='active'){
          const indicator=square(row.active===null?null:row.active>0,row.active===null?'Lumnis unknown':row.active>0?'Lumnis active, times '+row.active:'Lumnis inactive');
          if(row.active>0)indicator.append(text('span','×'+row.active));cell.append(indicator);
        }else if(key==='tutelage'){
          cell.append(square(row.tutelage,row.tutelage===null?'Tutelage unknown':row.tutelage?'Has Tutelage':'No Tutelage'));
        }else if(key==='weekly'){
          cell.append(text('span',row.earned===null?'—':number(row.earned)+(row.cap!==null?' / '+number(row.cap):''),'status-resource-amount'));
          if(row.weekly!==null){const bar=document.createElement('progress');bar.max=row.cap;bar.value=Math.min(row.earned,row.cap);bar.setAttribute('aria-label','Weekly resource progress for '+row.name);bar.setAttribute('aria-valuetext',number(row.earned)+' of '+number(row.cap));cell.append(bar);}
        }else if(key==='reset'){
          cell.append(text('span',row.reset===null?'—':row.reset===0?'Ready':humanDuration(row.reset),'status-reset'+(row.reset===0?' is-ready':'')));
        }else cell.textContent=row[key]===null?'—':typeof row[key]==='number'?number(row[key]):row[key];
        tr.append(cell);
      }
      fragment.append(tr);
    }
    body.replaceChildren(fragment);
    if(focusName)[...body.querySelectorAll('[data-status-character]')].find(el=>el.dataset.statusCharacter===focusName)?.focus({preventScroll:true});
    $('statusCount').textContent=rows.length+' of '+all.length+' characters';
    $('statusEmpty').hidden=rows.length>0;
    $('statusEmpty').textContent=!all.length?'No configured characters. Add characters in the Characters view.':'No characters match these filters.';
  }
  const loader=characterStatus.createLoader(
    gameRealm=>api('profiles?realm='+encodeURIComponent(gameRealm)),
    (result,gameRealm)=>{if(active&&currentView==='status'&&gameRealm===state.realm){profiles=result.profiles;loaded=true;$('statusError').hidden=true;render();}},
    error=>{if(active&&currentView==='status'){$('statusError').textContent='Could not update status. '+(loaded?'Showing previous reports. ':'')+error.message;$('statusError').hidden=false;}}
  );
  function load(){
    if(!active||currentView!=='status')return;
    render();
    return loader.load(state.realm);
  }
  for(const [key,id] of Object.entries(fieldIds)){
    if(!['account','profession'].includes(key))$(id).value=state[key];
    $(id).addEventListener(['query','rangeMin','rangeMax'].includes(key)?'input':'change',()=>{
      state[key]=$(id).value;save();
      if(key==='realm'){loader.invalidate();profiles=[];loaded=false;$('statusError').hidden=true;render();load();}else render();
    });
  }
  $('statusClear').onclick=()=>{
    for(const key of Object.keys(fieldIds))if(key!=='realm'){state[key]='';$(fieldIds[key]).value='';}
    save();render();
  };
  $('statusRefresh').onclick=load;
  const previousSetTab=setTab;
  setTab=function(tab){previousSetTab(tab);page.hidden=currentView!=='status';nav.setAttribute('aria-current',currentView==='status'?'page':'false');if(currentView==='status')load();else loader.invalidate();};
  const previousRefresh=refresh;
  refresh=async function(){await previousRefresh();if(active&&currentView==='status')await load();};
  const option=text('option','Character status');option.value='status';$('settingsForm').elements.default_view.append(option);
  $('logout').addEventListener('click',()=>{loader.invalidate();profiles=[];loaded=false;$('statusRows').replaceChildren();$('statusError').hidden=true;});
  // Authentication may finish while external modules are still loading.
  if(active&&currentView==='status')setTab('status');
})();
