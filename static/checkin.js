/* Daily Check-in. Sample preview is local and can never submit API mutations. */
const dailyCheckin=(()=>{
  const active=new Set(['logging_in','startup','capturing','persisting','logging_out']);
  const labels={queued:'Queued',waiting:'Waiting for account',retry_wait:'Retry scheduled',logging_in:'Logging in',startup:'Running login scripts',capturing:'Capturing data',persisting:'Capture saved',logging_out:'Logging out',complete:'Complete',partial:'Incomplete capture',failed:'Failed',attention:'Needs attention',cancelled:'Cancelled',running:'Daily sweep running',paused:'Queue paused',stopping:'Stopping safely'};
  const label=status=>labels[status]||'Unknown state';
  function counts(jobs){
    const out={total:jobs.length,complete:0,active:0,waiting:0,queued:0,attention:0,cancelled:0};
    for(const j of jobs){if(j.status==='complete')out.complete++;else if(active.has(j.status))out.active++;else if(j.status==='waiting')out.waiting++;else if(['queued','retry_wait'].includes(j.status))out.queued++;else if(j.status==='cancelled')out.cancelled++;else out.attention++;}
    return out;
  }
  function accounts(jobs){
    const groups=new Map();
    for(const job of jobs){if(!groups.has(job.account))groups.set(job.account,{id:job.account,name:job.account_label,jobs:[]});groups.get(job.account).jobs.push(job);}
    return [...groups.values()].map(a=>({...a,counts:counts(a.jobs),current:a.jobs.find(j=>active.has(j.status))||a.jobs.find(j=>j.status!=='complete')||a.jobs.at(-1)}));
  }
  function demo(){
    const now=Date.now()/1000, done=[3,3,2,3,4,1],names=['Renwaldo','Voxy','Vecto','Dartwen','Cragstone','Vlatimire'];
    const phases=['startup','logging_out','capturing','waiting','complete','queued'];
    const jobs=done.flatMap((n,a)=>Array.from({length:4},(_,i)=>{
      const status=i<n?'complete':i===n?phases[a]:'queued';
      return {id:`sample-${a}-${i}`,account:'sample-'+a,account_label:'Account '+String.fromCharCode(65+a),
        character:i===n||n===4&&i===3?names[a]:a===2&&i===3?'Gringott':'Character '+(a*4+i+1),realm:'prime',
        status,captured_at:i<n?now-100:null,credit:i<n||active.has(status)?'presence_observed':'unknown',streak:12,
        owned:active.has(status),cleanup:status==='complete'?'closed':'pending',
        message:status==='waiting'?'Waiting: Dartwen is playing. Existing session preserved.':label(status),
        fields:status==='capturing'?{character:{status:'captured',observed_at:now},stats:{status:'captured',observed_at:now},skills:{status:'captured',observed_at:now},bank:{status:'unavailable',observed_at:null}}:{}};
    }));
    return {preview:true,allowed:false,now,game_day:'2026-10-23',settings:{enabled:false,time:'00:15',parallel_accounts:4,freshness_hours:22},history:[],roster:[],run:{id:'sample',status:'running',started_at:now-258,jobs}};
  }
  return {active,label,counts,accounts,demo};
})();
if(typeof module!=='undefined')module.exports=dailyCheckin;

if(typeof document!=='undefined')(()=>{
  const page=text('section');page.id='checkin';page.hidden=true;page.setAttribute('aria-labelledby','checkinHeading');
  page.innerHTML=`
    <div class="page-heading"><div><h2 id="checkinHeading">Daily Check-in</h2><p>Every character, up to date.</p></div>
      <div class="ci-actions"><button type="button" class="primary" id="ciRun">Run now</button><button type="button" class="secondary" id="ciSchedule">Schedule</button></div></div>
    <div id="ciNotice" class="ci-notice" role="status"></div><p id="ciError" class="ci-error" role="alert" hidden></p>
    <section class="ci-summary" aria-label="Check-in progress"><div class="ci-summary-top"><span id="ciRunLabel" class="ci-run-label"></span><span id="ciDay" class="ci-muted"></span></div>
      <div class="ci-summary-main"><div class="ci-progress-area"><div class="ci-progress-numbers"><strong id="ciComplete">0 / 0</strong><span class="ci-muted">characters complete</span></div>
        <progress id="ciProgress" max="1" value="0" aria-label="Characters complete"></progress><div id="ciCounts" class="ci-counts"></div></div>
        <div class="ci-actions"><button type="button" class="secondary" id="ciPause" hidden>Pause queue</button><button type="button" class="danger" id="ciStop" hidden>Stop run</button></div></div></section>
    <div class="ci-workspace"><section class="ci-queues" aria-label="Account queues"><div class="ci-section-heading"><div><h3>Account queues</h3><p id="ciSlots"></p></div>
      <label class="ci-attention-filter"><input id="ciAttention" type="checkbox"> Needs attention</label></div><div id="ciAccounts"></div></section>
      <section class="ci-detail" id="ciDetail" aria-label="Selected character progress"></section></div>
    <div class="ci-footer"><span id="ciScheduleSummary"></span><div class="ci-actions"><label>Run history <select id="ciHistory"><option value="">Latest run</option></select></label><button type="button" class="secondary" id="ciPreview">Preview with sample data</button></div></div>
    <dialog id="ciScheduleDialog" aria-labelledby="ciScheduleHeading"><form id="ciScheduleForm"><h2 id="ciScheduleHeading">Check-in schedule</h2><p>One character per account. Existing play sessions stay connected.</p>
      <label class="ci-check"><input name="enabled" type="checkbox"> Run automatically every day</label>
      <label>Daily start · Eastern time<input name="time" type="time" required value="00:15"></label>
      <label>Parallel accounts<input name="parallel_accounts" type="number" min="1" max="16" value="4" required></label>
      <label>Refresh data after (hours)<input name="freshness_hours" type="number" min="1" max="23" value="22" required></label>
      <p id="ciScheduleNote"></p><div class="ci-actions"><button class="primary" type="submit">Save schedule</button><button id="ciScheduleCancel" class="secondary" type="button">Cancel</button></div><p id="ciScheduleError" class="ci-error" role="alert" hidden></p>
    </form></dialog>`;
  document.querySelector('main').append(page);
  const nav=actionButton('Daily Check-in',()=>setTab('checkin'),'nav-button',null);nav.id='checkinTab';nav.title='Daily Check-in';nav.prepend(icon('settings-icon',20));$('rotationTab').before(nav);
  let data=null,selectedAccount=null,selectedJob=null,preview=false,busy=false,revision=0,loadFailed=false;
  const age=stamp=>!stamp?'Not captured':Math.max(0,Math.round(((data?.now||Date.now()/1000)-stamp)/60))<1?'Just now':Math.max(1,Math.round(((data?.now||Date.now()/1000)-stamp)/60))+'m ago';
  const date=stamp=>new Date(stamp*1000).toLocaleString([],{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
  function jobs(){return data?.run?.jobs||data?.roster?.map((r,i)=>({...r,id:'roster-'+i,status:'queued',realm:'prime',fields:{},message:'Ready for the next check-in.'}))||[];}
  function button(label,callback,css='secondary'){const el=actionButton(label,callback,css,null);el.type='button';return el;}
  function render(){
    if(!data){for(const id of ['ciRun','ciPause','ciStop','ciSchedule'])$(id).disabled=true;$('ciAccounts').replaceChildren();$('ciDetail').replaceChildren();return;}
    $('ciSchedule').disabled=busy||loadFailed;
    const all=jobs(),count=dailyCheckin.counts(all),run=data.run,historical=!!$('ciHistory').value;
    const ongoing=!!run&&['running','paused','stopping'].includes(run.status);
    $('ciNotice').textContent=preview?'DESIGN PREVIEW · Sample data only. Controls here do not affect game sessions.':data.disabled_reason||data.scheduler_error||'';
    $('ciNotice').hidden=!$('ciNotice').textContent;
    $('ciRunLabel').textContent=!run?'Ready for a daily check-in':run.status==='attention'?'Finished with attention':run.status==='complete'?'Daily sweep complete':dailyCheckin.label(run.status);
    $('ciRunLabel').className='ci-run-label '+(ongoing?'ci-working':run?.status==='complete'?'ci-complete':'');
    $('ciDay').textContent='Game day: '+(run?.game_day||data.game_day)+' · Eastern';
    $('ciComplete').textContent=count.complete+' / '+count.total;
    $('ciProgress').max=Math.max(1,count.total);$('ciProgress').value=count.complete;
    $('ciCounts').replaceChildren();
    for(const [key,word] of [['active','working'],['waiting','waiting'],['queued','queued'],['attention','need attention'],['cancelled','cancelled']]){
      if(count[key]||['active','waiting','queued'].includes(key))$('ciCounts').append(text('span',count[key]+' '+word,'ci-count-'+key));
    }
    if(run){const seconds=Math.max(0,Math.floor((run.finished_at||data.now)-run.started_at));$('ciCounts').append(text('span','Elapsed '+Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0'),'ci-elapsed'));}
    $('ciRun').disabled=busy||ongoing||historical||(!preview&&!data.allowed)||loadFailed;
    $('ciRun').title=!data.allowed&&!preview?'Live execution is disabled on this server.':'';
    $('ciPause').hidden=!ongoing||historical;$('ciPause').textContent=run?.status==='paused'?'Resume queue':'Pause queue';
    $('ciStop').hidden=!ongoing||historical;
    for(const id of ['ciPause','ciStop'])$(id).disabled=busy||run?.status==='stopping'||loadFailed;
    $('ciSlots').textContent=count.active+' of '+data.settings.parallel_accounts+' slots active';
    $('ciPreview').textContent=preview?'Return to real data':'Preview with sample data';
    $('ciScheduleSummary').textContent=(data.settings.enabled?'Daily at '+data.settings.time+' ET':'Schedule off')+' · Freshness catch-up at '+data.settings.freshness_hours+'h';
    const groups=dailyCheckin.accounts(all),visible=$('ciAttention').checked?groups.filter(a=>a.counts.attention||a.counts.waiting):groups;
    if(!groups.some(a=>a.id===selectedAccount))selectedAccount=(groups.find(a=>a.counts.active)||groups[0])?.id;
    const focused=document.activeElement?.dataset?.ciFocus;
    const lanes=$('ciAccounts');lanes.replaceChildren();
    for(const account of visible){
      const row=text('div','','ci-account');
      const select=button('',()=>{selectedAccount=account.id;selectedJob=account.current.id;render();},'ci-lane');
      select.dataset.ciFocus=account.id;select.setAttribute('aria-pressed',String(selectedAccount===account.id));
      const header=text('div','','ci-lane-heading');header.append(text('strong',account.name),text('span',account.counts.complete+' / '+account.counts.total,'ci-muted'));
      const line=text('div','','ci-lane-line');
      const description=text('div','','ci-lane-description');
      description.append(text('span',account.counts.complete===account.counts.total?'All characters complete':account.current.character+' · '+dailyCheckin.label(account.current.status),account.current.status==='waiting'?'ci-waiting':''));
      if(account.current.status==='waiting')description.append(text('small',account.current.message));
      const marks=text('div','','ci-marks');marks.setAttribute('aria-hidden','true');
      for(const job of account.jobs)marks.append(text('span','','ci-mark '+job.status));
      line.append(description,marks);select.append(header,line);row.append(select);
      if(selectedAccount===account.id){
        const queue=text('div','','ci-character-queue');queue.setAttribute('aria-label',account.name+' characters');
        for(const job of account.jobs){const b=button(job.character,()=>{selectedJob=job.id;render();},'ci-character');b.dataset.ciFocus=job.id;b.setAttribute('aria-pressed',String((selectedJob||account.current.id)===job.id));b.title=dailyCheckin.label(job.status);b.append(text('span',dailyCheckin.label(job.status),'ci-small'));queue.append(b);}row.append(queue);
      }
      lanes.append(row);
    }
    if(!visible.length)lanes.append(text('p',all.length?'No accounts need attention.':'Add characters in Characters to create your check-in roster.','ci-empty'));
    if(focused)[...page.querySelectorAll('[data-ci-focus]')].find(el=>el.dataset.ciFocus===focused)?.focus({preventScroll:true});
    const group=groups.find(a=>a.id===selectedAccount);
    const selected=group?.jobs.find(j=>j.id===selectedJob)||group?.current;
    renderDetail(selected,group,historical);
    if(!preview){
      const choice=$('ciHistory').value,history=$('ciHistory');
      history.replaceChildren();const latest=text('option','Latest run');latest.value='';history.append(latest);
      for(const r of data.history||[]){const opt=text('option',date(r.started_at)+' · '+dailyCheckin.label(r.status));opt.value=r.id;history.append(opt);}
      history.value=choice;
    }
    $('ciHistory').disabled=preview||busy;
  }
  function renderDetail(job,group,historical){
    const detail=$('ciDetail');detail.replaceChildren();
    if(!job){detail.append(text('h3','Your daily round, in one view'),text('p','Select an account to inspect its character queue.','ci-muted'));return;}
    detail.append(text('p',group.name,'ci-muted'),text('h3',job.character,'ci-detail-name'),text('p',dailyCheckin.label(job.status),'ci-muted'));
    const phase={queued:-1,waiting:-1,retry_wait:-1,logging_in:0,startup:1,capturing:2,persisting:3,logging_out:3,complete:4}[job.status]??-1;
    const credit=job.credit&&job.credit!=='unknown';
    const captured=job.captured_at!=null;
    const steps=[['Logged in',credit?'Today’s in-game presence observed'+(job.streak?' · reward day '+job.streak:''):'Waiting for current-day game evidence',credit||phase>0],
      ['Login scripts finished',phase>1?'Startup readiness acknowledged':'Waiting for startup acknowledgment',phase>1],
      ['Capture data',captured?'Required observations saved · '+age(job.captured_at):phase===2?'Reading character reports':'Waiting for fresh observations',captured],
      ['Save & log out',job.cleanup==='closed'?'Session confirmed closed':job.cleanup==='user_owned'?'Session kept for manual play':job.status==='complete'?'Already satisfied; no new session needed':'Waiting for capture and orderly cleanup',job.cleanup==='closed'||job.status==='complete']];
    const list=text('ol','','ci-timeline');
    steps.forEach(([name,note,done],i)=>{const li=text('li','',''+(done?'done':phase===i?'current':'pending'));const mark=text('span',done?'✓':phase===i?'●':'○','ci-step-mark');mark.setAttribute('aria-hidden','true');const body=text('div');body.append(text('strong',name),text('p',note));li.append(mark,body);list.append(li);});detail.append(list);
    if(job.message){const note=text('p',job.message,'ci-detail-note');note.setAttribute('role','status');detail.append(note);}
    const fields=Object.entries(job.fields||{});
    if(fields.length){
      const gaps=fields.filter(([,v])=>!['captured','not_applicable'].includes(v.status));
      if(gaps.length)detail.append(text('p',(gaps.every(([k])=>k==='bank')?'Optional data gap: ':'Missing capture: ')+gaps.map(([k])=>k.replaceAll('_',' ')).join(', '),'ci-gap'));
      const more=document.createElement('details');more.append(text('summary','Captured fields'));
      for(const [name,value] of fields){const row=text('div','','ci-field');row.append(text('span',name.replaceAll('_',' ')),text('span',value.status==='captured'?age(value.observed_at):value.status.replaceAll('_',' ')));more.append(row);}detail.append(more);
    }
    if(['partial','failed','attention','cancelled'].includes(job.status)){
      const retry=button('Retry character',()=>mutate('checkin/jobs/'+job.id+'/retry'));retry.disabled=busy||(!preview&&!data.allowed)||loadFailed;detail.append(retry);
    }
    if(job.owned&&['startup','capturing','persisting','attention'].includes(job.status)){
      const take=button('Keep session for play',()=>mutate('checkin/jobs/'+job.id+'/takeover'));take.disabled=busy||(!preview&&!data.allowed)||loadFailed;detail.append(take);
    }
  }
  async function load(){
    if(!active||currentView!=='checkin'||preview)return;
    const token=++revision,history=$('ciHistory').value;
    try{const value=await api(history?'checkin/runs/'+encodeURIComponent(history):'checkin');if(token!==revision||!active||currentView!=='checkin'||preview)return;data=value;loadFailed=false;$('ciError').hidden=true;render();}
    catch(error){if(token!==revision||preview||currentView!=='checkin')return;loadFailed=true;$('ciError').textContent='Could not update check-in progress. '+error.message;$('ciError').hidden=false;render();}
  }
  async function mutate(path,method='POST',body){
    if(busy||!data||loadFailed)return;
    if(preview){
      if(path.endsWith('/pause'))data.run.status='paused';else if(path.endsWith('/resume'))data.run.status='running';else if(path.endsWith('/stop')){data.run.status='stopping';data.run.jobs.filter(j=>['queued','waiting'].includes(j.status)).forEach(j=>j.status='cancelled');}
      render();return;
    }
    busy=true;render();
    try{await api(path,method,body);$('ciHistory').value='';await load();}
    catch(error){$('ciError').textContent=error.message;$('ciError').hidden=false;}
    finally{busy=false;render();}
  }
  $('ciRun').onclick=()=>mutate('checkin/runs','POST',{});
  $('ciPause').onclick=()=>mutate('checkin/runs/'+data.run.id+'/'+(data.run.status==='paused'?'resume':'pause'));
  $('ciStop').onclick=()=>mutate('checkin/runs/'+data.run.id+'/stop');
  $('ciAttention').onchange=render;$('ciHistory').onchange=load;
  $('ciPreview').onclick=()=>{preview=!preview;++revision;selectedAccount=selectedJob=null;$('ciError').hidden=true;loadFailed=false;if(preview){data=dailyCheckin.demo();render();}else{data=null;$('ciHistory').value='';$('ciPreview').textContent='Preview with sample data';$('ciNotice').textContent='Loading current check-in state…';render();load();}};
  $('ciSchedule').onclick=()=>{
    if(!data)return;
    const form=$('ciScheduleForm');for(const [k,v] of Object.entries(data.settings)){if(!form.elements[k])continue;if(k==='enabled')form.elements[k].checked=v;else form.elements[k].value=v;}
    form.elements.enabled.disabled=!data.allowed&&!preview;
    $('ciScheduleNote').textContent=preview?'Sample settings only.':data.allowed?'All times use America/New_York; daylight saving changes are handled automatically.':'Automatic logins are disabled on this server. You can prepare settings now.';
    $('ciScheduleError').hidden=true;$('ciScheduleDialog').showModal();
  };
  $('ciScheduleCancel').onclick=()=>$('ciScheduleDialog').close();
  $('ciScheduleForm').onsubmit=async event=>{
    event.preventDefault();const form=event.currentTarget;
    const values={enabled:form.elements.enabled.checked,time:form.elements.time.value,parallel_accounts:Number(form.elements.parallel_accounts.value),freshness_hours:Number(form.elements.freshness_hours.value)};
    try{if(preview)data.settings=values;else{await api('checkin/settings','PUT',values);await load();}$('ciScheduleDialog').close();render();}
    catch(error){$('ciScheduleError').textContent=error.message;$('ciScheduleError').hidden=false;}
  };
  const priorTab=setTab;setTab=function(tab){priorTab(tab);page.hidden=currentView!=='checkin';nav.setAttribute('aria-current',currentView==='checkin'?'page':'false');if(currentView==='checkin'){$('breadcrumb').textContent='Daily Check-in';if(preview)render();else load();}else{++revision;$('ciScheduleDialog').close();}};
  const priorRefresh=refresh;refresh=async function(){await priorRefresh();if(active&&currentView==='checkin')await load();};
  const option=text('option','Daily Check-in');option.value='checkin';$('settingsForm').elements.default_view.append(option);
  $('logout').addEventListener('click',()=>{++revision;data=null;preview=false;selectedAccount=selectedJob=null;$('ciAccounts').replaceChildren();$('ciDetail').replaceChildren();$('ciScheduleDialog').close();});
  if(active&&currentView==='checkin')setTab('checkin');
})();
