// LANGKAS live bridge. The server owns persistent state; the browser never owns CLI credentials.
const live={ready:false,rev:0,base:null,dirty:false,blocked:false,saving:null,timer:null,runners:[],workspaces:[],runs:new Map(),streams:new Map(),events:new Map(),selectedWorkspace:'',providerModel:'',starting:false};
const finished=new Set(['succeeded','failed','cancelled','interrupted']);
const statusLabel={queued:'Wartet',running:'Läuft',awaiting_approval:'Freigabe erforderlich',succeeded:'Abgeschlossen',failed:'Fehlgeschlagen',cancelled:'Abgebrochen',interrupted:'Unterbrochen'};
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function mergeState(base,local,remote,path='Workspace'){
 if(equal(local,base))return clone(remote);
 if(equal(remote,base)||equal(local,remote))return clone(local);
 if(Array.isArray(base)&&Array.isArray(local)&&Array.isArray(remote)&&[...base,...local,...remote].every(x=>x&&typeof x==='object'&&typeof x.id==='string')){
  const index=a=>new Map(a.map(x=>[x.id,x])),b=index(base),l=index(local),r=index(remote);const out=[];
  for(const id of new Set([...local.map(x=>x.id),...remote.map(x=>x.id)])){
   if(!l.has(id)){if(b.has(id)&&!equal(r.get(id),b.get(id)))throw Error('Konflikt beim Löschen: '+path+'/'+id);if(!b.has(id))out.push(clone(r.get(id)));continue}
   if(!r.has(id)){if(b.has(id)&&!equal(l.get(id),b.get(id)))throw Error('Konflikt mit gelöschtem Eintrag: '+path+'/'+id);if(!b.has(id))out.push(clone(l.get(id)));continue}
   out.push(mergeState(b.get(id),l.get(id),r.get(id),path+'/'+id));
  }return out;
 }
 if(base&&local&&remote&&[base,local,remote].every(x=>typeof x==='object'&&!Array.isArray(x))){
  const out={};for(const k of new Set([...Object.keys(local),...Object.keys(remote)])){
   const b=base[k],l=local[k],r=remote[k];
   if(equal(l,b)){if(r!==undefined)out[k]=clone(r)}else if(equal(r,b)||equal(l,r)){if(l!==undefined)out[k]=clone(l)}else out[k]=mergeState(b,l,r,path+'/'+k);
  }return out;
 }
 throw Error('Gleichzeitige Änderung: '+path+'. Lokale Änderungen exportieren, dann Serverstand laden.');
}
async function request(path,method='GET',data,headers={}){
 const options={method,credentials:'same-origin',headers:{...headers}};
 if(data!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}
 const response=await fetch(path,options);let value;try{value=await response.json()}catch{throw Error('Ungültige Antwort vom Backend.')}
 if(!response.ok){const e=Error(value.error?.message||'HTTP '+response.status);e.status=response.status;e.code=value.error?.code;throw e}return value;
}
function showSync(){const el=$('#syncStatus');if(el){el.textContent=live.blocked?'Speicherkonflikt':live.saving?'Speichert …':live.dirty?'Ungespeichert':'SQLite · gespeichert';el.classList.toggle('sync-warning',live.blocked||live.dirty)}}
save=function(){if(!live.ready)return true;live.dirty=true;clearTimeout(live.timer);live.timer=setTimeout(()=>flushState().catch(showFailure),350);showSync();return true};
function showFailure(e){toast(e.message||String(e),true);showSync()}
async function flushState(){
 clearTimeout(live.timer);if(!live.ready)return;if(live.blocked)throw Error('Speicherkonflikt: lokale Änderungen exportieren oder Serverstand laden.');
 if(live.saving){await live.saving;if(live.dirty)return flushState();return}
 if(!live.dirty)return;
 live.saving=(async()=>{let retries=0;while(live.dirty){
  const snapshot=clone(store);
  try{const result=await request('/api/state','PUT',{revision:live.rev,state:snapshot});live.rev=result.revision;live.base=snapshot;live.dirty=!equal(store,snapshot);retries=0}
  catch(e){if(e.status===409&&retries++<4){const newest=await request('/api/state');try{store=mergeState(live.base,store,newest.state);live.base=clone(newest.state);live.rev=newest.revision;live.dirty=true}catch(conflict){live.blocked=true;throw conflict}}else throw e}
 }})();showSync();
 try{await live.saving}finally{live.saving=null;showSync()}
}
async function refreshState(redraw=true){
 if(live.dirty)await flushState();
 const data=await request('/api/state');
 if(live.dirty){store=mergeState(live.base,store,data.state)}else store=data.state;
 live.base=clone(data.state);live.rev=data.revision;
 updateBusy();if(redraw)render();showSync();
}
function updateModels(){
 Models.splice(0,Models.length,{id:'auto',name:'Auto · installierte CLI',provider:'local',mark:'terminal',desc:'Erste verfügbare CLI nach lokaler Priorität'},...live.runners.map(r=>({id:r.id,name:r.name,provider:'local',mark:'terminal',desc:r.available?(r.enabled?'Installiert · Anmeldung wird erst beim Lauf geprüft':'Deaktiviert'):'Nicht installiert'})));
}
function updateBusy(){const r=[...live.runs.values()].find(r=>r.chat_id===ui.id&&!finished.has(r.status));ui.busy=r?{chat:r.chat_id,message:r.message_id,runId:r.id}:null}
const originalRender=render;
render=function(){if(!live.ready)return;updateBusy();originalRender();for(const el of $$('#agentForm input[name=integrations],#agentForm input[name=subagents],#agentForm input[name=capabilities][value=web],#agentForm input[name=capabilities][value=images],#agentForm select[name=visibility],#agentForm select[name=group]')){el.disabled=true;el.title='Nicht angeschlossen / keine serverseitige Berechtigung';}const domain=$('form[data-form=general] input[name=domain]');if(domain){domain.disabled=true;domain.title='Keine E-Mail-Zugangskontrolle in der lokalen Einzelbenutzer-Version';}if(ui.view==='runs'&&ui.id)updateRunDetail(ui.id)};
Titles.runners='CLI-Runner';Titles.runs='Läufe';
const originalView=renderView;
renderView=function(){if(ui.view==='runners')return runnersView();if(ui.view==='runs')return runsView();if(['integrations','tasks'].includes(ui.view))return `<div class="page">${pageHead('Noch nicht angeschlossen','Keine OAuth-Verbindungen oder automatischen Zeitpläne. Nutze manuelle Workflows und lokale CLI-Runner.',btn('CLI-Runner','nav','terminal','primary','data-view="runners"'))}</div>`;return originalView()};
const originalSidebar=renderSidebar;
renderSidebar=function(){originalSidebar();for(const x of $$('#sidebar [data-view="integrations"],#sidebar [data-view="tasks"]'))x.remove();
 const search=$('#sidebar [data-action="search"]');search?.insertAdjacentHTML('afterend',navRow('runners','CLI-Runner','terminal')+navRow('runs','Läufe','play',String([...live.runs.values()].filter(r=>!finished.has(r.status)).length)||''));
 const note=$('#sidebar .local-note');if(note){note.dataset.action='backend-about';note.innerHTML=icon('shield','sm')+'Lokaler CLI-Arbeitsplatz'}
};
renderHeader=function(){const c=store.chats.find(c=>c.id===ui.id);$('#topbar').innerHTML=`<button class="icon-btn mobile-menu" data-action="sidebar-toggle" aria-label="Navigation öffnen">${icon('panel')}</button><div class="breadcrumbs"><span class="muted">${esc(Titles[ui.view]||'LANGKAS')}</span>${c?icon('chevron','sm')+`<span class="truncate">${esc(c.title)}</span>`:''}</div><div class="topbar-end"><button class="sync-state" id="syncStatus" data-action="sync-menu">SQLite · gespeichert</button><button class="demo-pill" data-action="backend-about"><span class="dot"></span>Backend verbunden</button></div>`;showSync()};
const originalComposer=composer;
composer=function(){return originalComposer().replace(/<button data-action="about"[^>]*>.*?<\/button>/,'<button data-action="backend-about" style="font-size:inherit;color:inherit;padding:0;text-decoration:underline">Echte CLI · lokal ausgeführt</button>').replace('title="Modell auswählen"','title="CLI-Runner auswählen"')};
const originalMessage=renderMessage;
renderMessage=function(m,c){if(m.role!=='assistant')return originalMessage(m,c);
 const r=live.runs.get(m.runId);const text=r?.output??m.text;const status=r?.status||m.status;const active=status&&!finished.has(status);const error=r?.error||m.runError;
 return `<article class="message assistant" data-message="${esc(m.id)}"><div class="message-head"><span class="model-mark">${icon('terminal','sm')}</span>${esc(modelName(r?.provider||m.model||c.model))}${badge(statusLabel[status]||'CLI-Antwort',status==='succeeded'?'green':status==='failed'?'gold':'')}</div><div class="message-content ${active?'typing':''}" id="text-${esc(m.id)}">${formatText(text|| (status==='queued'?'Auftrag wartet auf einen freien Runner.':status==='awaiting_approval'?'Dieser Lauf wartet auf deine Freigabe.':active?'CLI wird gestartet …':''))}</div>${error?callout(esc(error),'info','warning'):''}<div class="message-actions">${m.runId?btn('Lauf & Protokoll','run-open','terminal','sm ghost',`data-id="${esc(m.runId)}"`):''}${ib('copy','message-copy','Nachricht kopieren',`data-id="${esc(m.id)}"`)}${!active?ib('file','message-canvas','Im Dokument bearbeiten',`data-id="${esc(m.id)}"`):''}${status==='awaiting_approval'?btn('Freigabe prüfen','run-open','lock','sm',`data-id="${esc(m.runId)}"`):''}</div></article>`;
};
function runnerStatus(r){return !r.enabled?'Deaktiviert':r.available?'Installiert':'Nicht installiert'}
function runnersView(){return `<div class="page">${pageHead('Deine CLIs. Ein Arbeitsplatz.','LANGKAS startet deine lokal installierten Assistenten. Zugangsdaten bleiben bei der jeweiligen CLI.',btn('Erneut erkennen','runner-reload','refresh','primary'))}
 <div class="feature-band"><div class="icon-tile gold">${icon('terminal','lg')}</div><div><h3>KI, oba koa Kas.</h3><p>Keine simulierten Antworten. Auto wählt den ersten installierten, aktivierten Runner. Kein automatischer Wechsel nach einem fehlgeschlagenen Auftrag.</p></div></div>
 <div class="cards">${live.runners.map(r=>`<article class="card runner-card"><div class="between"><div class="icon-tile ${r.available&&r.enabled?'green':'gray'}">${icon('terminal')}</div>${badge(runnerStatus(r),r.available&&r.enabled?'green':'')}</div><h3>${esc(r.name)}</h3><p>${esc(r.id)} · ${esc(r.adapter)}<br>${r.permission==='workspace-write'?'Dateiänderungen möglich · Freigabe vor jedem Lauf':'Lesemodus angefordert'} · ${esc(r.timeout)} s Limit</p><div class="runner-hint">Anmeldung: nicht vorab verifiziert. Installiert bedeutet nicht angemeldet.</div>${r.note?`<p class="small">${esc(r.note)}</p>`:''}<div class="card-foot">${btn('Im Chat verwenden','runner-use','arrowRight','sm',`data-id="${esc(r.id)}" ${!r.available||!r.enabled?'disabled':''}`)}</div></article>`).join('')}</div>
 <section class="runner-options"><h2>Arbeitskontext</h2><p class="muted">Ohne Auswahl erhält jeder Lauf ein eigenes Arbeitsverzeichnis. Nur lokal registrierte Verzeichnisse sind auswählbar.</p><div class="field-row"><div class="field"><label for="runnerWorkspace">Arbeitsverzeichnis</label><select id="runnerWorkspace"><option value="">Eigenes Arbeitsverzeichnis pro Lauf</option>${live.workspaces.map(w=>`<option value="${esc(w.id)}" ${live.selectedWorkspace===w.id?'selected':''}>${esc(w.name)}</option>`).join('')}</select></div><div class="field"><label for="runnerModel">Modell-ID (optional)</label><input id="runnerModel" maxlength="150" value="${esc(live.providerModel)}" placeholder="Standardmodell der CLI verwenden"><p class="small muted">Wird an die gewählte CLI weitergegeben. Kein erfundener Modellkatalog.</p></div></div></section>
 <section class="runner-options"><h2>Weitere CLIs verbinden</h2><p>Registriere einen vertrauenswürdigen Adapter lokal im Terminal. Der Browser darf keine ausführbaren Befehle definieren.</p><pre class="setup-code">python3 -m langcas add-runner mein-cli --exec /absoluter/pfad/mein-cli --arg=-p
python3 -m langcas add-workspace projekt ~/Projekte/mein-projekt
python3 -m langcas doctor</pre><p class="small muted">Für Orca, Grok oder eigene Harnesses wird ein nichtinteraktiver Text-/JSONL-Adapter benötigt. Keine pauschale Behauptung nativer Kompatibilität; interaktive TTY- und Browser-Harnesses sind noch nicht integriert.</p>${callout('Ein Arbeitsverzeichnis ist keine Betriebssystem-Sandbox. Auch Lesemodus ist bei einem generischen Adapter nur eine Vertrauensangabe. Nur eigene, vertrauenswürdige CLIs aktivieren.','shield','warning')}</section>
 <section class="runner-options"><h2>Lokale API</h2><p>Textkompatibler Chat-Endpunkt für andere Clients. Keine Bilder, Tool-Calls oder vollständige API-Emulation.</p><pre class="setup-code">POST /v1/chat/completions
GET  /v1/models
Authorization: Bearer &lt;lokaler Zugriffsschlüssel&gt;
{"model":"auto","messages":[{"role":"user","content":"Servas!"}],"stream":true}</pre>${btn('API-Schlüssel lokal anzeigen','token-help','key')}</section></div>`}
function runControls(r){return r.status==='awaiting_approval'?`<div class="approval-box">${callout(esc(r.approval?.message||'Dieser Lauf benötigt deine Zustimmung.'),'lock','warning')}${r.approval?.preview?`<pre>${esc(r.approval.preview)}</pre>`:''}<div class="flex">${btn('Freigeben','run-approve','check','primary',`data-id="${esc(r.id)}"`)}${btn('Ablehnen','run-reject','close','',`data-id="${esc(r.id)}"`)}</div></div>`:!finished.has(r.status)?btn('Lauf abbrechen','run-cancel','stop','',`data-id="${esc(r.id)}"`):''}
function runsView(){const r=live.runs.get(ui.id);if(r)return `<div class="page">${pageHead('Lauf & Protokoll',r.id,btn('Alle Läufe','nav','arrowLeft','','data-view="runs"'))}<div id="runDetail"></div></div>`;
 const runs=[...live.runs.values()].sort((a,b)=>b.created-a.created);return `<div class="page">${pageHead('Läufe','Echte Prozesse, Ergebnisse und Freigaben. Der Verlauf bleibt auch nach einem Neustart erhalten.',btn('Aktualisieren','runs-refresh','refresh'))}<div class="run-list">${runs.map(r=>`<button class="run-row" data-action="run-open" data-id="${esc(r.id)}"><span class="icon-tile ${r.status==='succeeded'?'green':r.status==='failed'?'gold':'gray'}">${icon(r.kind==='workflow'?'workflow':'terminal')}</span><span class="grow"><strong>${esc(store.chats.find(c=>c.id===r.chat_id)?.title||r.id)}</strong><small>${esc(modelName(r.provider))} · ${dt(r.created,{dateStyle:'short',timeStyle:'short'})}</small></span>${badge(statusLabel[r.status],r.status==='succeeded'?'green':'')}${icon('chevron','sm')}</button>`).join('')||empty('Noch keine Läufe','Starte einen Chat oder führe einen Workflow aus.','','terminal')}</div></div>`}
function updateRunDetail(id){const r=live.runs.get(id),el=$('#runDetail');if(!r||!el)return;const logs=live.events.get(id)||[];el.innerHTML=`<div class="between"><span class="flex">${badge(statusLabel[r.status],r.status==='succeeded'?'green':'')}<strong>${esc(modelName(r.provider))}</strong></span>${btn('Chat öffnen','open-chat','chat','sm',`data-id="${esc(r.chat_id)}"`)}</div>${runControls(r)}${r.error?callout(esc(r.error),'info','warning'):''}<section class="runner-options"><h3>Ausgabe</h3><div class="run-output">${formatText(r.output||'Noch keine Ausgabe.')}</div></section><section class="runner-options"><div class="between"><h3>Ereignisse</h3>${btn('JSON exportieren','run-export','download','sm',`data-id="${esc(r.id)}"`)}</div><div class="run-events">${logs.filter(e=>e.type!=='delta').slice(-150).map(e=>`<div class="run-event"><code>${esc(e.seq)}</code><strong>${esc(e.type)}</strong><span>${esc(JSON.stringify(e.data))}</span></div>`).join('')||'<p class="muted small">Protokoll wird geladen …</p>'}</div></section>`}
function paintRun(r){if(ui.view==='runs'&&ui.id===r.id)updateRunDetail(r.id);if(ui.view==='chat'&&ui.id===r.chat_id){const c=store.chats.find(c=>c.id===r.chat_id),m=c?.messages.find(m=>m.id===r.message_id),node=m&&$(`[data-message="${m.id}"]`);if(m&&node){node.outerHTML=renderMessage(m,c);scrollChat()}}}
function watchRun(r,replay=false){
 if(live.streams.has(r.id))return;
 if((live.events.get(r.id)||[]).some(e=>e.type==='done'))return;
 live.runs.set(r.id,r);const logs=live.events.get(r.id)||[];live.events.set(r.id,logs);
 const last=logs.at(-1)?.seq||0;
 if(!last){r.output=''} // The durable event stream rebuilds output exactly once, including after reload.
 const stream=new EventSource('/api/runs/'+encodeURIComponent(r.id)+'/events?since='+last);live.streams.set(r.id,stream);
 const receive=type=>event=>{let data;try{data=JSON.parse(event.data)}catch{return}const seq=Number(event.lastEventId);if(logs.some(e=>e.seq===seq))return;logs.push({seq,type,data});
  if(type==='delta')r.output+=data.text||'';
  if(type==='status')Object.assign(r,data);
  if(type==='done'){Object.assign(r,data);stream.close();live.streams.delete(r.id);updateBusy();refreshState().catch(showFailure)}
  if(type==='status'&&data.status==='awaiting_approval'){
   if(ui.view==='runs'&&ui.id===r.id)updateRunDetail(r.id);
   toast('Lauf wartet auf deine Freigabe. Öffne „Läufe“.');
  }
  paintRun(r);
 };
 for(const t of ['status','delta','process','tool','log','stderr','session','step','artifact','done'])stream.addEventListener(t,receive(t));
 stream.onerror=()=>{if(finished.has(r.status)&&logs.some(e=>e.type==='done')){stream.close();live.streams.delete(r.id)}else{const el=$('#syncStatus');if(el)el.textContent='Verbindung wird wiederhergestellt …'}};
}
async function loadRuns(){const data=await request('/api/runs');for(const r of data.runs){if(!live.streams.has(r.id))live.runs.set(r.id,r)}for(const r of data.runs.filter(r=>!finished.has(r.status)).slice(0,2))watchRun(live.runs.get(r.id));updateBusy()}
async function openRun(id){let r=live.runs.get(id);if(!r){r=await request('/api/runs/'+encodeURIComponent(id));live.runs.set(id,r)}navigate('runs',id);watchRun(r,true)}
async function submitRun(payload,destination='chat'){
 await flushState();const r=await request('/api/runs','POST',payload,{'Idempotency-Key':uid('request')});live.runs.set(r.id,r);await refreshState(false);
 ui.draft='';ui.attachments=[];ui.agent=payload.agent||null;ui.project=payload.project||null;if(live.runners.some(x=>x.id===r.provider))ui.model=r.provider;
 if(destination==='runs')navigate('runs',r.id);else navigate('chat',r.chat_id);
 watchRun(r);updateBusy();render();return r;
}
sendMessage=async function(textOverride=null){if(live.starting||ui.busy)return;const text=(textOverride??$('#composerInput')?.value??ui.draft).trim();if(!text&&!ui.attachments.length)return;live.starting=true;
 try{await submitRun({prompt:text||'Analysiere die angehängten Textdateien.',provider:ui.model||'auto',model:live.providerModel,workspace:live.selectedWorkspace||null,chat_id:store.chats.some(c=>c.id===ui.id)?ui.id:null,agent:ui.agent||null,project:ui.project||null,files:ui.attachments.slice()})}catch(e){showFailure(e)}finally{live.starting=false}
};
stopGeneration=async function(){const r=[...live.runs.values()].find(r=>r.chat_id===ui.id&&!finished.has(r.status));if(r){const next=await request('/api/runs/'+r.id+'/cancel','POST',{});Object.assign(r,next);await refreshState();paintRun(r)}};
generate=async function(){throw Error('Antworten werden nur durch einen neuen, expliziten CLI-Auftrag erzeugt.')};
startFlow=async function(){const w=store.workflows.find(w=>w.id===ui.id);if(!w)return;const prompt=$('#flowInput')?.value||w.nodes[0]?.config||'';try{await submitRun({prompt,provider:live.runners.some(r=>r.id===ui.model)?ui.model:'auto',model:live.providerModel,workspace:live.selectedWorkspace||null,workflow:w.id},'runs')}catch(e){showFailure(e)}};
testAgent=async function(){captureAgent();const text=$('#agentTestInput')?.value.trim();if(!text)return;if(!ui.editAgent?.name){toast('Bitte gib dem Agenten einen Namen.',true);return}const id=ui.editAgent.id;saveAgent(false);try{await submitRun({prompt:text,provider:ui.editAgent.model||'auto',model:live.providerModel,agent:id,workspace:live.selectedWorkspace||null},'chat')}catch(e){showFailure(e)}};
const originalInferDraft=inferAgentDraft;
inferAgentDraft=function(...args){const changes=originalInferDraft(...args);ui.editAgent.model='auto';ui.editAgent.integrations=[];ui.editAgent.capabilities=(ui.editAgent.capabilities||[]).filter(x=>['files','knowledge','canvas'].includes(x));return changes};
const oldAgentSide=renderAgentSide;
renderAgentSide=function(a){return oldAgentSide(a).replace('Lokale Vorschau mit Beispieldaten. Keine externe Anfrage.','Echter CLI-Test. Speichert den Entwurf und öffnet einen Chat.').replace('Teste den aktuellen Entwurf lokal.','Teste den Entwurf mit deiner CLI.').replace('Chat Agent Builder','Vorlagen-Assistent').replace('Agent Builder','Vorlagen-Assistent · ohne KI').replace('Beschreibe deinen Agenten in natürlicher Sprache.','Erzeugt einen regelbasierten Entwurf. Der Test startet deine CLI.')};
// Essential settings are real persistence. Enterprise features stay explicitly outside the live product.
const originalSettingsBody=settingsBody;
const implementedSettings=new Set(['profile','preferences','instructions','memory','general','branding','chat','data']);
SettingGroups.splice(0,SettingGroups.length,['PERSÖNLICH',[['profile','Profil','user'],['preferences','Darstellung','settings'],['instructions','Eigene Anweisungen','pen'],['memory','Erinnerungen','brain']]],['ARBEITSPLATZ',[['general','Allgemein','settings'],['branding','Branding','pen'],['chat','Chat','chat'],['models','CLI-Runner','terminal'],['security','Zugriff','lock'],['api','API','key'],['audit','Audit-Log','history'],['data','Sicherung','download']]]);
settingsBody=function(){if(ui.setting==='data')return `<h1>Daten & Sicherung</h1><p class="muted">Dein Workspace wird vom Backend in SQLite gespeichert, nicht in localStorage.</p>${callout('Die JSON-Sicherung enthält Workspace-Inhalte. Laufprotokolle, CLI-Konfiguration und Zugriffsschlüssel gehören nicht dazu. Für eine vollständige Sicherung: Server beenden und den gesamten LANGKAS-Datenordner kopieren.','lock')}${settingRow('Workspace-Größe',bytes(new Blob([JSON.stringify(store)]).size)+' · ohne separate Laufprotokolle',badge('SQLite'))}${settingRow('Workspace exportieren','Synchronisiert vor dem Export und lädt eine JSON-Datei herunter.',btn('JSON exportieren','data-export','download','sm'))}${settingRow('Workspace importieren','Eine validierte Sicherung ersetzt den aktuellen Workspace. Aktive Läufe werden geschützt.',btn('Importieren','data-import','upload','sm'))}${settingRow('Backend prüfen','Prüft Erreichbarkeit, Anmeldung und gespeicherte Revision. Kein KI-Aufruf und kein E2E-Siegel.',btn('Prüfen','live-health','check','sm'))}<div id="healthResult"></div>`;if(implementedSettings.has(ui.setting))return originalSettingsBody();if(['models','api','endpoint'].includes(ui.setting))return `<h1>CLI-Runner & API</h1><p class="muted">Runner werden lokal konfiguriert, nicht durch einen Web-Request.</p>${btn('Runner verwalten','nav','terminal','primary','data-view="runners"')}`;if(ui.setting==='audit')return `<h1>Backend-Audit</h1><p>Dieses Protokoll stammt aus SQLite, nicht aus simulierten UI-Einträgen.</p>${btn('Protokoll laden','audit-load','refresh')}<div id="backendAudit"></div>`;return `<h1>Lokaler Zugriff</h1>${callout('Ein lokaler Eigentümer, HttpOnly-Sitzung und Loopback-Bindung. Kein SSO, keine Team-Rollen und keine öffentliche Freigabe. Daten liegen unverschlüsselt in deinem geschützten Benutzerverzeichnis.','shield')}<div class="section-gap">${btn('Browser abmelden','logout','lock')}</div>`};
const unsupported=()=>toast('Nicht angeschlossen: Diese Funktion gehört noch zur UI-Vorlage. Keine externe Aktion ausgeführt.',true);
Object.assign(Actions,{
 send:()=>sendMessage(),'stop-generation':()=>stopGeneration(),'flow-run':()=>startFlow(),'agent-test':()=>testAgent(),
 'backend-about':()=>modal('LANGKAS · KI, oba koa Kas.',callout('Lokale Web-Oberfläche → Python-Backend → installierte CLI → SQLite. Antworten, Dokumente und Laufprotokolle werden tatsächlich gespeichert.','terminal')+'<p style="margin-top:18px">Lesemodus ist eine angeforderte CLI-Berechtigung, keine allgemeine Betriebssystem-Sandbox. Nur vertrauenswürdige Adapter starten. Keine nativen Browser-Harnesses, kein Mehrbenutzerbetrieb, keine SSO-/Billing-Integrationen.</p>',btn('CLI-Runner','nav','terminal','','data-view="runners"')),
 'about':()=>Actions['backend-about'](),
 'model-menu':e=>popover(e,`<div class="popover-title">CLI-Runner auswählen</div>${Models.map(m=>{const r=live.runners.find(r=>r.id===m.id);return `<button class="menu-item" data-action="live-model-select" data-id="${esc(m.id)}" ${r&&(!r.available||!r.enabled)?'disabled':''}>${icon('terminal','sm')}<span><strong>${esc(m.name)}</strong><small class="muted" style="display:block">${esc(m.desc)}</small></span></button>`}).join('')}`+menuItem('Runner konfigurieren','nav','settings','data-view="runners"')),
 'live-model-select':e=>{ui.model=e.dataset.id;closePopover();render()},
 'runner-use':e=>{newChat();ui.model=e.dataset.id;render()},
 'runner-reload':async()=>{try{const reload=await request('/api/config/reload','POST',{});const b=await request('/api/runners');live.runners=b.runners;live.workspaces=b.workspaces;updateModels();render();toast(reload.restart_required?'Konfiguration geladen. Für die geänderte Parallelität den Server neu starten.':'Installierte Runner und lokale Konfiguration neu eingelesen.')}catch(e){showFailure(e)}},
 'runs-refresh':async()=>{await loadRuns();render()},'run-open':e=>openRun(e.dataset.id),
 'run-cancel':async e=>{const r=await request('/api/runs/'+e.dataset.id+'/cancel','POST',{});live.runs.set(r.id,r);await refreshState();paintRun(r)},
 'run-approve':async e=>{const r=await request('/api/runs/'+e.dataset.id+'/approve','POST',{approve:true});Object.assign(live.runs.get(r.id)||{},r);paintRun(r)},
 'run-reject':async e=>{const r=await request('/api/runs/'+e.dataset.id+'/approve','POST',{approve:false});Object.assign(live.runs.get(r.id)||{},r);await refreshState()},
 'run-export':e=>download('langkas-run-'+e.dataset.id+'.json',JSON.stringify({run:live.runs.get(e.dataset.id),events:live.events.get(e.dataset.id)||[]},null,2),'application/json'),
 'sync-menu':()=>modal('Workspace-Synchronisierung',`<p>${live.blocked?'Es gibt gleichzeitig geänderte Daten. Sichere deine lokalen Änderungen vor dem Neuladen.':'Änderungen werden automatisch in SQLite gespeichert. Andere Tabs werden beim Speichern konfliktgeprüft.'}</p>`,btn('Lokal exportieren','live-export','download')+btn('Serverstand laden','live-reload','refresh')+btn('Jetzt speichern','live-save','check','primary')),
 'live-export':()=>download('langkas-lokale-sicherung.json',JSON.stringify(store,null,2),'application/json'),
 'live-save':async()=>{try{await flushState();closeModal();toast('Workspace gespeichert.')}catch(e){showFailure(e)}},
 'live-reload':()=>confirmAction('Serverstand laden?','Ungespeicherte lokale Änderungen werden verworfen. Vorher bei Bedarf exportieren.',async()=>{live.dirty=false;live.blocked=false;await refreshState();closeModal()}),
 'token-help':()=>modal('Lokaler Zugriffsschlüssel','<p>Im Projektverzeichnis im Terminal ausführen:</p><pre class="setup-code">python3 -m langcas token</pre><p>Der Schlüssel wird absichtlich nicht per API ausgegeben. Behandle ihn wie ein Passwort für deine lokalen CLIs.</p>',btn('Schließen','modal-close')),
 'audit-load':async()=>{const r=await request('/api/audit');$('#backendAudit').innerHTML=r.events.map(x=>`<div class="run-event"><span>${esc(dt(x.at,{dateStyle:'short',timeStyle:'short'}))}</span><strong>${esc(x.action)}</strong><span>${esc(x.detail)}</span></div>`).join('')},
 logout:async()=>{await flushState();await request('/api/auth/logout','POST',{});for(const s of live.streams.values())s.close();live.streams.clear();live.ready=false;location.reload()},
 'message-regenerate':unsupported,'message-edit':unsupported,'share-current':unsupported,'chat-share':unsupported,
 'flow-run-detail':e=>openRun(e.dataset.id),'flow-stop':unsupported,'flow-approve':unsupported,'flow-reject':unsupported,
 'workflow-publish':e=>{const w=store.workflows.find(w=>w.id===e.dataset.id);if(w){w.active=!w.active;save();render();toast('Vorlage gespeichert. Ausführung bleibt manuell.')}},
 'api-create':unsupported,'endpoint-save':unsupported,'endpoint-test':unsupported,'connection-connect':unsupported,
});
Object.assign(Actions,{
 'data-export':async()=>{try{await flushState();const data=await request('/api/export');download('langkas-workspace.json',JSON.stringify(data.state,null,2),'application/json')}catch(e){showFailure(e)}},
 'data-import':()=>{const file=document.createElement('input');file.type='file';file.accept='.json,application/json';file.hidden=true;document.body.append(file);file.onchange=async()=>{try{const f=file.files?.[0];if(!f)return;if(f.size>7000000)throw Error('Sicherung größer als 7 MB.');const json=JSON.parse(await f.text());const state=json.state||json;confirmAction('Workspace ersetzen?','Diese Sicherung ersetzt Chats, Dokumente und Einstellungen. Separate Laufprotokolle bleiben erhalten.',async()=>{try{await flushState();await request('/api/import','POST',{revision:live.rev,state});const data=await request('/api/state');store=data.state;live.base=clone(store);live.rev=data.revision;live.dirty=false;live.blocked=false;updateModels();await loadRuns();closeModal();newChat();render();toast('Workspace importiert.')}catch(e){showFailure(e)}},'Importieren')}catch(e){showFailure(e)}finally{file.remove()}};file.click()},
 'live-health':async()=>{try{const health=await request('/health'),data=await request('/api/state');$('#healthResult').innerHTML=callout('Backend: '+esc(health.status)+' · SQLite-Revision '+esc(data.revision)+'. Kein Modell aufgerufen.','check')}catch(e){showFailure(e)}},
 'self-test':()=>toast('Die bisherigen Demo-Selbsttests wurden im Live-Modus ersetzt. Ausführliche Tests: siehe README und Testbericht.')
});
// Errors from expected API failures are visible without uncaught promise rejections.
Actions['chat-tool']=e=>{if(e.dataset.tool==='knowledge')attachPicker();else unsupported()};
for(const name of ['runs-refresh','run-open','run-cancel','run-approve','run-reject','audit-load','logout','flow-run-detail']){const fn=Actions[name];Actions[name]=async e=>{try{return await fn(e)}catch(error){showFailure(error)}}}
document.addEventListener('change',e=>{if(e.target.id==='runnerWorkspace')live.selectedWorkspace=e.target.value;if(e.target.id==='runnerModel')live.providerModel=e.target.value.trim()});
window.addEventListener('beforeunload',e=>{if(live.dirty||live.saving){e.preventDefault();e.returnValue=''}});
async function authenticate(){const input=$('#localToken');const token=input?.value.trim();if(!token)return;const err=$('#authError');try{await request('/api/auth/login','POST',{token});input.value='';await liveBoot()}catch(e){err.textContent=e.message;input?.focus()}}
function authScreen(message=''){
 live.ready=false;$('#main').inert=true;$('#sidebar').inert=true;
 let el=$('#authGate');if(!el){el=document.createElement('div');el.id='authGate';document.body.append(el)}
 el.innerHTML=`<section class="auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle"><div class="auth-brand">${brand()}<strong>LANGKAS</strong></div><span class="eyebrow">DEIN LOKALER KI-ARBEITSPLATZ</span><h1 id="authTitle">Servas. Verbinde deine CLIs.</h1><p>Chats, Agenten und Workflows – mit echten Prozessen und gespeichertem Verlauf. Kein Konto bei einem neuen Cloud-Dienst.</p><div class="auth-steps"><span class="auth-step">1</span><div><strong>Schlüssel im Terminal anzeigen</strong><code>python3 -m langcas token</code></div></div><form id="localLogin"><label for="localToken">2 · Lokalen Zugriffsschlüssel einfügen</label><input id="localToken" type="password" autocomplete="off" spellcheck="false" required placeholder="Zugriffsschlüssel" minlength="32"><button class="btn primary full" type="submit">Arbeitsplatz öffnen ${icon('arrowRight','sm')}</button></form><p class="auth-error" id="authError" role="alert">${esc(message)}</p><div class="auth-bottom">${icon('shield','sm')}Nur dieser Rechner · Keine CLI-Schlüssel im Browser</div></section>`;
 $('#localLogin').addEventListener('submit',e=>{e.preventDefault();authenticate()});$('#localToken').focus();
}
async function liveBoot(){
 if(location.protocol==='file:'){authScreen('Starte das Backend mit „python3 -m langcas serve --open“. Diese Live-Oberfläche benötigt localhost.');return}
 try{const data=await request('/api/bootstrap');store=data.state;live.base=clone(store);live.rev=data.revision;live.runners=data.runners;live.workspaces=data.workspaces;live.ready=true;live.dirty=false;live.blocked=false;updateModels();ui.model=store.prefs.defaultModel||'auto';$('#authGate')?.remove();$('#main').inert=false;$('#sidebar').inert=false;await loadRuns();route();if(!live.runners.some(r=>r.available&&r.enabled))toast('Noch keine CLI installiert oder aktiviert. Öffne „CLI-Runner“.');}
 catch(e){authScreen(e.status===401?'':e.message)}
}
liveBoot();
