/* Identity-bound command drafts. No target selection is persisted to browser storage. */
const commandConsole = (() => {
  const keys=['session_id','bridge_generation','character','realm'];
  const tuple=t=>Object.fromEntries(keys.map(k=>[k,t[k]]));
  const same=(a,b)=>!!a&&!!b&&keys.every(k=>a[k]===b[k]);
  const labels={sending:'Sending',sent:'Sent to Lich',not_sent:'Not sent',unconfirmed:'Unconfirmed'};
  function validateCommand(value) {
    return typeof value!=='string'||!value.trim()||/[\x00-\x1f\x7f-\x9f\u2028\u2029]/.test(value)||new TextEncoder().encode(value).length>1024
      ?'Use one line without control characters, up to 1,024 UTF-8 bytes.':'';
  }
  const pacific=new Intl.DateTimeFormat('en-US',{timeZone:'America/Los_Angeles',year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
  const pacificTime=seconds=>pacific.format(new Date(seconds*1000));
  class ConsoleState {
    constructor(){this.targets=new Map();this.online=[];this.command='';this.open=false;this.pending=null;this.sending=false;this.error='';this.history=[];this.epoch=0;}
    get busy(){return this.sending||!!this.pending;}
    roster(rows){this.online=rows;}
    select(target){if(this.busy)return;if(target?.ready)this.targets.set(target.session_id,tuple(target));}
    all(){if(this.busy)return;this.targets.clear();this.online.filter(t=>t.ready).forEach(t=>this.select(t));}
    excluded(){return this.online.filter(t=>!t.ready);}
    recipients(){return [...this.targets.values()].map(t=>({...t,available:this.online.some(c=>c.ready&&same(c,t))}));}
    use(batch){if(this.busy)return;this.command=batch.command;this.open=true;this.error='';}
    selectNotSent(batch){if(this.busy)return;this.targets.clear();batch.targets.filter(t=>t.state==='not_sent').forEach(t=>{const current=this.online.find(c=>c.ready&&same(c,t));if(current)this.select(current);});this.use(batch);}
    recentCommands(){return [...new Set(this.history.map(b=>b.command))].slice(0,20);}
    record(batch){this.history=[batch,...this.history.filter(b=>b.request_id!==batch.request_id)].sort((a,b)=>b.accepted_at-a.accepted_at).slice(0,1000);}
    accepted(batch,payload){this.record(batch);if(this.command===payload.command)this.command='';this.pending=null;this.sending=false;this.error='';}
    async send(api){
      if(this.sending||this.pending)return;
      this.error=validateCommand(this.command)||(!this.targets.size?'Select at least one character.':'');if(this.error)return;
      const epoch=this.epoch,payload={command:this.command,targets:[...this.targets.values()].map(tuple)};
      this.sending=true;
      try {
        const admission=await api('command-batches/prepare','POST',{});
        if(epoch!==this.epoch)return;
        this.pending={...admission,...payload};
        const batch=await api('command-batches','POST',this.pending);
        if(epoch===this.epoch)this.accepted(batch,payload);
      } catch(error) {
        if(epoch!==this.epoch)return;
        // Only an explicit validation/auth rejection is safe to treat as unaccepted.
        if(this.pending&&![400,401,403,409,413,422].includes(error.status)){
          this.error='Checking delivery. The request will not be sent again.';
        }else{this.pending=null;this.error=error.message;}
      } finally {if(epoch===this.epoch)this.sending=false;}
    }
    async resolve(api){
      if(!this.pending||this.sending)return;
      const payload=this.pending,epoch=this.epoch;
      try{const batch=await api('command-batches/'+encodeURIComponent(payload.request_id));if(epoch===this.epoch&&this.pending===payload)this.accepted(batch,payload);}
      catch(error){if(epoch===this.epoch)this.error=error.status===404?'Checking delivery. No receipt yet; inspect clients before any new send.':'Checking delivery. Receipt lookup is unavailable.';}
    }
    reset(){this.epoch++;this.targets.clear();this.command='';this.open=false;this.pending=null;this.sending=false;this.error='';}
  }
  return {ConsoleState,validateCommand,pacificTime,same,labels};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=commandConsole;

(() => {
  if(typeof document==='undefined')return;
  const {ConsoleState,pacificTime,same,labels}=commandConsole, state=new ConsoleState();
  const header=text('div','','command-toolbar');
  header.innerHTML='<div><h2>Live characters</h2><p id="commandRosterCount" class="command-muted"></p></div><button id="commandToggle" type="button" class="secondary" aria-controls="commandPanel" aria-expanded="false">Commands</button>';
  const panel=text('section','','command-panel');panel.id='commandPanel';panel.hidden=true;panel.setAttribute('aria-label','Send a command');
  panel.innerHTML=`<div class="command-panel-head"><strong>Command <span id="commandCount" class="command-muted">0 selected</span></strong><div><button type="button" id="commandAll">All online (0)</button><button type="button" id="commandClear">Clear</button></div></div>
    <div class="command-body"><div class="command-compose"><details id="commandRecipientsDisclosure" open><summary id="commandRecipientsSummary">To · 0 selected</summary><div id="commandRecipients" class="command-recipients"></div></details>
      <label for="commandInput" class="command-label">GAME OR LICH COMMAND</label><div class="command-input-wrap"><span aria-hidden="true">&gt;</span><input id="commandInput" type="text" autocomplete="off" spellcheck="false" placeholder="Game or Lich command, e.g. look or ;pause all" aria-describedby="commandHint commandError"></div>
      <p id="commandHint" class="command-muted">Send once to each selected character. View game output in the client.</p><p id="commandError" class="command-error" role="alert" hidden></p>
      <div class="command-compose-actions"><select id="commandRecent" aria-label="Recall a recent command"><option value="">Recent commands</option></select><div><button type="button" id="commandSend" class="primary" disabled>Send to 0 characters</button><span class="command-shortcut">Ctrl / ⌘ ↵</span></div></div>
      <p id="commandExclusions" class="command-muted"></p><a id="commandTakeover" href="?view=checkin" hidden>Take over in Daily Check-in</a><p id="commandNotice" role="status" class="command-muted" hidden></p>
    </div><div class="command-latest" aria-label="Latest command delivery"><div class="command-label">LATEST DELIVERY</div><div id="commandLatest"></div></div></div>
    <details class="command-history"><summary>Recent deliveries</summary><div id="commandHistory"></div></details><p id="commandAnnouncement" class="command-sr" role="status" aria-live="polite" aria-atomic="true"></p>`;
  $('sessionList').before(header,panel);
  const input=$('commandInput'), controls=new Map();
  let loading=false,historyLoaded=false,recipientSignature='',historySignature='',recentSignature='',rosterRevision=0;
  const notice=message=>{$('commandNotice').textContent=message;$('commandNotice').hidden=!message;};
  function render(){
    panel.hidden=!state.open;$('commandToggle').setAttribute('aria-expanded',String(state.open));
    const ready=state.online.filter(t=>t.ready),targets=state.recipients();
    $('commandRosterCount').textContent=sessions.length+' online · '+ready.length+' available for commands';
    $('commandAll').textContent='All online ('+ready.length+')';$('commandAll').disabled=!ready.length||state.busy;
    $('commandClear').disabled=!targets.length||state.busy;
    $('commandCount').textContent=targets.length+' selected';$('commandRecipientsSummary').textContent='To · '+targets.length+' selected'+(targets.length>6?' · Show recipient names':'');
    const signature=JSON.stringify([targets,state.busy]);
    if(signature!==recipientSignature){
      const wasEmpty=!recipientSignature;recipientSignature=signature;
      const holder=$('commandRecipients');holder.replaceChildren();
      if(!targets.length)holder.append(text('span','Select characters below.','command-muted'));
      for(const target of targets){
        const chip=text('span','','command-chip');chip.append(text('span',target.character),text('span',target.realm,'realm-badge'));
        if(!target.available)chip.append(text('span','Unavailable','command-unavailable'));
        const remove=actionButton('×',()=>{state.targets.delete(target.session_id);render();},'command-remove',null);remove.setAttribute('aria-label','Remove '+target.character+' on '+target.realm);remove.disabled=state.busy;chip.append(remove);holder.append(chip);
      }
      if(targets.length>6&&(wasEmpty||!$('commandRecipientsDisclosure').matches(':focus-within')))$('commandRecipientsDisclosure').open=false;
    }
    const excluded=state.excluded();$('commandExclusions').textContent=excluded.length?excluded.length+' excluded: '+excluded.map(t=>t.character+' ('+t.realm+') — '+t.reason).join('; '):'';
    $('commandTakeover').hidden=!excluded.some(t=>t.checkin_controlled);
    $('commandError').textContent=state.error;$('commandError').hidden=!state.error;
    if(input.value!==state.command)input.value=state.command;
    input.disabled=state.busy;
    $('commandSend').textContent=state.sending?'Sending…':state.pending?'Checking delivery…':targets.length===1?'Send to '+targets[0].character:'Send to '+targets.length+' characters';
    $('commandSend').disabled=state.sending||state.busy||!targets.length||!!commandConsole.validateCommand(state.command);
    $('commandRecent').disabled=state.busy;
    const recents=state.recentCommands(),recentKey=JSON.stringify(recents);
    if(recentKey!==recentSignature){recentSignature=recentKey;$('commandRecent').replaceChildren(text('option','Recent commands'));$('commandRecent').firstChild.value='';for(const command of recents){const option=text('option',command);option.value=command;$('commandRecent').append(option);}}
    const historyKey=JSON.stringify(state.history.slice(0,20));
    if(historyKey!==historySignature){
      historySignature=historyKey;renderHistory();
      const latest=state.history[0];if(latest)$('commandAnnouncement').textContent=latest.targets.map(t=>t.character+': '+(labels[t.state]||'Unconfirmed')).join('. ');
    }
    for(const button of panel.querySelectorAll('.command-delivery-actions button'))button.disabled=state.busy;
    mountControls();
  }
  function openClient(target){
    if(!state.online.some(t=>same(t,target)))return;
    clientOperation('sessions/'+encodeURIComponent(target.session_id)+'/attach',{},'session:'+target.session_id);
  }
  function delivery(batch){
    const box=text('div','','command-delivery');box.dataset.commandKey=batch.request_id;box.append(text('time',pacificTime(batch.accepted_at),'command-muted'),text('pre',batch.command,'command-literal'));
    for(const target of batch.targets){
      const row=text('div','','command-result-row'),name=text('span',target.character+' · '+target.realm),result=text('span',labels[target.state]||'Unconfirmed','command-result-state');result.dataset.state=target.state;row.dataset.commandKey=target.session_id+':'+target.bridge_generation;
      row.append(name,result);if(target.reason)row.append(text('small',target.reason,'command-muted'));
      if(state.online.some(t=>same(t,target))){const link=actionButton('Open client',()=>openClient(target),'command-client',null);link.dataset.commandKey='client';link.setAttribute('aria-label','Open client for '+target.character+' on '+target.realm+' from delivery');row.append(link);}
      box.append(row);
    }
    const actions=text('div','','command-delivery-actions');actions.append(actionButton('Use command again',()=>{if(state.busy)return;state.use(batch);render();input.focus();},'secondary',null));
    if(batch.targets.some(t=>t.state==='not_sent'&&state.online.some(c=>c.ready&&same(c,t))))actions.append(actionButton('Select not-sent characters',()=>{if(state.busy)return;state.selectNotSent(batch);notice('Selected only definitively not-sent sessions that still match. Review recipients before sending.');render();input.focus();},'secondary',null));
    actions.dataset.commandKey='actions';for(const button of actions.children)button.dataset.commandKey=button.textContent;
    box.append(actions);return box;
  }
  // Reconcile receipt nodes in place so polling does not discard keyboard focus
  // or a screen reader's current row. Keys bind actions to batch/session identity.
  function patchReceipt(current,fresh){
    if(current.nodeType!==fresh.nodeType||current.nodeName!==fresh.nodeName){current.replaceWith(fresh);return fresh;}
    if(current.nodeType===Node.TEXT_NODE){if(current.data!==fresh.data)current.data=fresh.data;return current;}
    for(const attr of [...current.attributes])if(!fresh.hasAttribute(attr.name))current.removeAttribute(attr.name);
    for(const attr of fresh.attributes)if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);
    current.onclick=fresh.onclick;
    const old=[...current.childNodes],used=new Set();
    [...fresh.childNodes].forEach((child,index)=>{
      const key=child.dataset?.commandKey;
      let match=key?old.find(node=>node.dataset?.commandKey===key):old[index];
      if(used.has(match)||(!key&&match?.dataset?.commandKey))match=null;
      const node=match?patchReceipt(match,child):child;used.add(node);
      if(current.childNodes[index]!==node)current.insertBefore(node,current.childNodes[index]||null);
    });
    for(const child of [...current.childNodes])if(!used.has(child))child.remove();
    return current;
  }
  function renderHistory(){
    const latest=$('commandLatest'),history=$('commandHistory'),focus=document.activeElement;
    const previous=new Map([...panel.querySelectorAll('.command-delivery')].map(node=>[node.dataset.commandKey,node]));
    if(!state.history.length){latest.replaceChildren(text('p','No deliveries yet.','command-muted'));history.replaceChildren();return;}
    const retained=new Set();
    state.history.slice(0,20).forEach((batch,index)=>{
      const fresh=delivery(batch),old=previous.get(batch.request_id),node=old?patchReceipt(old,fresh):fresh;
      retained.add(node);const parent=index===0?latest:history,position=index===0?0:index-1;
      if(parent.children[position]!==node)parent.insertBefore(node,parent.children[position]||null);
    });
    for(const parent of [latest,history])for(const child of [...parent.children])if(!retained.has(child))child.remove();
    if(state.history.length===1)history.append(text('p','No earlier deliveries.','command-muted'));
    if(focus?.isConnected&&panel.contains(focus)&&document.activeElement!==focus){
      if(history.contains(focus))history.parentElement.open=true;
      focus.focus({preventScroll:true});
    }
  }
  function mountControls(){
    for(const row of $('sessionList').querySelectorAll('.live-card')){
      const id=row.dataset.sessionId;let control=controls.get(id);
      if(!control){
        const check=document.createElement('input');check.type='checkbox';check.className='command-select';check.dataset.commandControl='select';
        check.addEventListener('change',()=>{const target=state.online.find(t=>t.session_id===id);if(check.checked)state.select(target);else state.targets.delete(id);state.error='';notice('');render();});
        const button=actionButton('Command',()=>{const target=state.online.find(t=>t.session_id===id);if(!target?.ready||state.busy)return;const changed=state.targets.size>0&&!(state.targets.size===1&&same(state.targets.get(id),target));state.targets.clear();state.select(target);state.open=true;notice(changed?'Recipients changed to '+target.character+' on '+target.realm+'. Review before sending.':'');render();input.focus();},'command-card-button',null);button.dataset.commandControl='button';
        const status=text('p','','command-card-status');control={check,button,status};controls.set(id,control);
      }
      const target=state.online.find(t=>t.session_id===id),selected=state.targets.has(id);
      const identity=row.querySelector('.row-identity'),heading=row.querySelector('.live-card-heading');
      if(!row.contains(control.check))heading.prepend(control.check);
      if(!row.contains(control.button))(row.querySelector('.character-actions')||heading).prepend(control.button);
      if(!row.contains(control.status))identity.append(control.status);
      control.check.hidden=!state.open;control.check.checked=selected;control.check.disabled=state.busy||(!target?.ready&&!selected);
      control.check.setAttribute('aria-label','Select '+(target?.character||'character')+' on '+(target?.realm||'unknown'));
      control.button.disabled=!target?.ready||state.busy;control.button.setAttribute('aria-label','Send command to '+(target?.character||'character')+' on '+(target?.realm||'unknown'));
      control.status.textContent=selected&&!same(state.targets.get(id),target)?'Selected connection unavailable':target?.ready?'Command ready':target?.reason||'Control unavailable · checking bridge';
      control.button.title=control.status.textContent;row.classList.toggle('command-selected',selected);
    }
    for(const id of controls.keys())if(!sessions.some(s=>s.id===id))controls.delete(id);
  }
  async function load(){
    if(!active||currentView!=='sessions'||loading)return;
    loading=true;const epoch=state.epoch,revision=++rosterRevision;
    try{
      const result=await api('command-targets');if(epoch!==state.epoch||!active||currentView!=='sessions')return;
      const previous=JSON.stringify(state.online);state.roster(result.targets);if(previous!==JSON.stringify(state.online))historySignature='';
      await state.resolve(api);
      if(epoch!==state.epoch)return;
      if(state.open){
        const history=await api('command-batches?limit='+(historyLoaded?20:1000));
        if(epoch!==state.epoch)return;
        historyLoaded=true;for(const batch of history.batches)state.record(batch);
        // Reconcile only this view's newest uncertain/pending receipts; never submit again.
        for(const batch of state.history.slice(0,20).filter(b=>b.targets.some(t=>['sending','unconfirmed'].includes(t.state)))){
          try{const receipt=await api('command-batches/'+encodeURIComponent(batch.request_id));if(epoch===state.epoch)state.record(receipt);}catch{}
        }
      }
    }catch(error){if(epoch===state.epoch){state.roster(state.online.map(t=>({...t,ready:false,reason:'Control availability could not be refreshed.'})));state.error=error.message;}}
    finally{loading=false;if(epoch===state.epoch&&revision===rosterRevision)render();}
  }
  $('commandToggle').onclick=()=>{state.open=!state.open;render();if(state.open){load();input.focus();}};
  $('commandAll').onclick=()=>{state.all();state.error='';notice('Selected a snapshot across all Live realms. Newly logged-in characters are not added.');render();};
  $('commandClear').onclick=()=>{state.targets.clear();notice('');render();};
  $('commandTakeover').onclick=event=>{event.preventDefault();setTab('checkin');};
  input.oninput=()=>{state.command=input.value;state.error='';render();};
  input.addEventListener('paste',event=>{const value=event.clipboardData?.getData('text')||'';if(/[\r\n\u2028\u2029]/.test(value)){event.preventDefault();state.error='Paste a single command. Multiple lines will not be sent.';render();}});
  const send=async()=>{const pending=state.send(api);render();await pending;render();if(state.pending)await load();else if(state.open)await load();};
  input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();if(event.ctrlKey||event.metaKey)send();}};
  $('commandSend').onclick=send;
  $('commandRecent').onchange=()=>{if($('commandRecent').value){state.command=$('commandRecent').value;$('commandRecent').value='';state.error='';render();input.focus();}};
  const priorRender=renderSessions;
  renderSessions=function(){const focus=document.activeElement,restore=focus?.dataset?.commandControl;priorRender();mountControls();if(restore&&focus.isConnected)focus.focus({preventScroll:true});};
  const priorTab=setTab;
  setTab=function(tab){const wasLive=currentView==='sessions';priorTab(tab);if(wasLive&&currentView!=='sessions'){state.reset();recipientSignature='';notice('');render();}if(currentView==='sessions')load();};
  const priorLogin=showLogin;
  showLogin=function(){state.reset();state.history=[];state.roster([]);historyLoaded=false;historySignature='';recipientSignature='';notice('');render();priorLogin();};
  document.addEventListener('gempy:sessions',load);
  render();if(active)load();
})();
