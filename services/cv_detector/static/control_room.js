'use strict';
const $ = (selector, root=document) => root.querySelector(selector);
const text = (selector, value, root=document) => { $(selector,root).textContent = value ?? '—'; };
const number = value => value == null ? '—' : Number(value).toLocaleString(undefined,{maximumFractionDigits:0});
const status = (el,label,kind) => {el.textContent=label;el.classList.remove('healthy','warning','incident');el.classList.add('status-pill');if(kind)el.classList.add(kind);};
let lastState=null;
function draw(state,twin){
  lastState=state;
  const now=Date.now()/1000;
  text('#clock',new Date().toLocaleTimeString());
  $('#connection').classList.remove('error');
  $('#connection').firstChild.textContent='';
  $('#connection').innerHTML='';
  const dot=document.createElement('span'); dot.className='dot';
  const clock=document.createElement('span'); clock.id='clock';clock.textContent=new Date().toLocaleTimeString();
  $('#connection').append(dot,document.createTextNode('Live · local'),clock);
  text('#scenario',state.scenario || 'unavailable');
  const plc=state.plc;
  status($('#line-status'),plc?.LineStatus ?? 'UNAVAILABLE',!plc?'':plc.LineStatus==='RUNNING'?'healthy':plc.BlockedSensor?'incident':'warning');
  text('#health-score',state.health.score);
  $('#health-bar').style.width=`${Math.max(0,Math.min(100,state.health.score))}%`;
  const unknown=Object.values(state.health.components).filter(c=>c.healthy==null).length;
  text('#health-caption',unknown?`${unknown} signal groups unavailable`:`${Object.values(state.health.components).filter(c=>c.healthy).length} / 10 signal groups healthy`);
  text('#plc-count',number(plc?.BottleCount));text('#entry-count',number(state.counts.entered));
  text('#exit-count',number(state.counts.exited));text('#flow',number(state.counts.flow_per_minute));
  text('#difference',state.counts.ready?`${state.counts.difference>0?'+':''}${state.counts.difference}`:'—');
  $('#difference').className=state.counts.mismatch?'incident':'';
  text('#reconcile-status',state.counts.ready?`${state.counts.mismatch?'Mismatch · ':''}ΔPLC − Δentry · baseline ${state.counts.epoch}`:'Synchronization unavailable');
  status($('#yolo-status'),!state.yolo.enabled?'DISABLED':state.yolo.ready?'READY':'UNAVAILABLE',state.yolo.ready?'healthy':'warning');
  text('#model-name',state.yolo.model);
  let online=0;
  for(const camera of state.cameras){
    const card=$(`[data-camera="${camera.camera}"]`);
    const up=camera.up && now-camera.updated<3;
    if(up)online++;
    const fresh=up && now-camera.processed<3 && camera.tracking_ready;
    status($('.camera-state',card),up?'ONLINE':'OFFLINE',up?'healthy':'incident');
    $('.offline-overlay',card).style.display=up?'none':'flex';
    text('.objects',fresh?camera.objects:'—',card);
    text('.fps',up?camera.fps.toFixed(1):'—',card);
    text('.latency',fresh?`${Math.round(camera.inference_ms)} ms`:'—',card);
    text('.track-state',fresh?'ACTIVE':'WAITING',card);
    const anomalies=[...camera.reasons,...camera.anomalies];
    text('.camera-anomaly',!up?'Camera unavailable':anomalies.length?anomalies.join(' · ').replaceAll('_',' '):fresh?'● No active visual anomaly':'Waiting for inference',card);
    $('.camera-anomaly',card).className=`camera-anomaly ${anomalies.length?'warning':''}`;
    if(card.dataset.view==='heatmap' && up) $('.video img',card).src=`/cameras/${camera.camera}/heatmap.jpg?t=${Date.now()}`;
  }
  text('#camera-availability',`${online} / 3 ONLINE`);
  for(const node of twin.nodes){
    const el=$(`[data-node="${node.id}"]`);
    if(!el)continue;
    el.className=`twin-node ${node.state}`;
    text('small',node.state,el);
  }
  text('#conveyor-speed',plc?`${plc.ConveyorSpeed.toFixed(2)} m/s`:null);
  text('#temperature',plc?`${plc.MotorTemperature.toFixed(1)} °C`:null);
  text('#vibration',plc?`${plc.Vibration.toFixed(2)} g`:null);
  text('#quality',plc?`${(plc.QualityScore*100).toFixed(1)}%`:null);
  const container=$('#incidents');container.replaceChildren();
  text('#incident-count',state.incidents?.length);
  if(state.incidents==null || !state.incidents.length){
    const p=document.createElement('p');p.className='empty';
    p.textContent=state.incidents==null?'Incident service unavailable':'No active incidents. The line is being monitored.';
    container.append(p);
  }else for(const incident of state.incidents.slice(0,3)){
    const a=document.createElement('a');a.href=`http://localhost:8090/incidents/${incident.id}`;a.className='incident-row';
    const meta=document.createElement('small');meta.textContent=`${incident.number} · ${incident.severity} · ${incident.status}`;
    const title=document.createElement('b');title.textContent=incident.title;a.append(meta,title);container.append(a);
  }
  const tbody=$('#events');tbody.replaceChildren();
  const events=state.events.filter(e=>e.event).slice(-6).reverse();
  for(const e of events){
    const row=document.createElement('tr');
    const values=[new Date(e.timestamp*1000).toLocaleTimeString(),e.camera.toUpperCase(),e.event.replaceAll('_',' '),e.track_id==null?'—':`#${e.track_id}`,e.state||'CROSSED',`${(e.duration_seconds||0).toFixed(1)} s`];
    for(const value of values){const td=document.createElement('td');td.textContent=value;row.append(td);}tbody.append(row);
  }
  if(!events.length){const row=document.createElement('tr');const td=document.createElement('td');td.colSpan=6;td.className='empty';td.textContent='No observed track transitions in the recent window';row.append(td);tbody.append(row);}
}
async function poll(){
  try{
    const responses=await Promise.all([fetch('/api/state',{signal:AbortSignal.timeout(5000)}),fetch('/api/twin',{signal:AbortSignal.timeout(5000)})]);
    if(responses.some(r=>!r.ok))throw new Error('Unavailable');
    const [state,twin]=await Promise.all(responses.map(r=>r.json()));draw(state,twin);
  }catch{
    $('#connection').classList.add('error');$('#connection').textContent='Connection lost · retrying';
    for(const card of document.querySelectorAll('.camera-card')){
      $('.offline-overlay',card).style.display='flex';$('.offline-overlay',card).textContent='Connection unavailable';
      status($('.camera-state',card),'UNAVAILABLE','incident');
    }
  }finally{setTimeout(poll,1500);}
}
for(const card of document.querySelectorAll('.camera-card')){
  card.dataset.view='annotated';
  for(const button of card.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{
    card.dataset.view=button.dataset.view;
    for(const other of card.querySelectorAll('[data-view]')){other.classList.toggle('active',other===button);other.setAttribute('aria-pressed',String(other===button));}
    $('.video img',card).src=button.dataset.view==='heatmap'?`/cameras/${card.dataset.camera}/heatmap.jpg?t=${Date.now()}`:`/cameras/${card.dataset.camera}/annotated.mjpg`;
  });
  $('.expand',card).addEventListener('click',()=>{$('.video',card).requestFullscreen?.().catch(()=>{});});
  $('.video img',card).addEventListener('error',()=>{if(card.dataset.view==='annotated')setTimeout(()=>{$('.video img',card).src=`/cameras/${card.dataset.camera}/annotated.mjpg?t=${Date.now()}`;},3000);});
}
poll();
