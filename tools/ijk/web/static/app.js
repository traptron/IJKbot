'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const names = {teleop:'Teleop', mapping:'Mapping', navigate:'Navigate', showcase:'Showcase', competition:'Competition'};
const storageKey = 'ijk.control.v1';
const defaults = () => ({version:1, profile:'teleop', linear:.15, angular:.48, seenJob:null,
  profiles:Object.fromEntries(Object.keys(names).map(p => [p,{record:false,bag_name:'',rviz:true,use_amcl:true,map:null}]))});
let settings = defaults();
try {
  const saved = JSON.parse(localStorage.getItem(storageKey));
  if (saved?.version === 1) {
    if (Object.hasOwn(names,saved.profile)) settings.profile = saved.profile;
    for (const key of ['linear','angular']) if (Number.isFinite(saved[key]) && saved[key]>=0) settings[key] = Math.min(key==='linear'?.25:.8,saved[key]);
    if (typeof saved.seenJob === 'string') settings.seenJob=saved.seenJob;
    for (const p of Object.keys(names)) {
      const item = saved.profiles?.[p]; if (!item) continue;
      for (const key of ['record','rviz','use_amcl']) if (typeof item[key] === 'boolean') settings.profiles[p][key] = item[key];
      for (const key of ['bag_name','map']) if (typeof item[key] === 'string') settings.profiles[p][key] = item[key];
    }
  }
} catch (_) { /* Storage may be unavailable; controls remain usable. */ }
function remember() { try { localStorage.setItem(storageKey, JSON.stringify(settings)); } catch (_) {} }
function notice(message='') { $('#alert').textContent=message; $('#alert').hidden=!message; }
async function api(path,data={}) {
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',...(controlId?{'X-Control-Id':controlId}:{})},body:JSON.stringify(data)});
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
async function get(path) { const response=await fetch(path); if (!response.ok) throw new Error(await response.text()); return response.json(); }
let controlId=null, controlLeaseReady=false, pendingClaim=false;
let state={}, catalog=[], requestBusy=false, saving=false, teleop, pointer=null, x=0,y=0, paused=false;
let watchedJob=null, handledJobs=new Set(settings.seenJob?[settings.seenJob]:[]);
const wsUrl=path=>`${location.protocol==='https:'?'wss':'ws'}://${location.host}${path}`;
function connectTeleop() {
  teleop=new WebSocket(wsUrl('/ws/teleop'));
  teleop.onopen=()=>{updateControls();if(pendingClaim){pendingClaim=false;teleop.send(JSON.stringify({type:'claim'}));}};
  teleop.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.type==='claimed'){controlId=message.control_id;notice();}
    if(message.type==='released'){controlId=null;controlLeaseReady=false;}
    if(message.type==='error')notice(message.message);
    updateControls();
  };
  teleop.onclose=()=>{ controlId=null;controlLeaseReady=false;release();updateControls();setTimeout(connectTeleop,2000); };
}
function connectLogs() {
  const socket=new WebSocket(wsUrl('/ws/logs'));
  socket.onmessage=event=>{
    if (paused) return;
    const log=$('#log'); log.textContent=(log.textContent+event.data+'\n').split('\n').slice(-1000).join('\n'); log.scrollTop=log.scrollHeight;
  };
  socket.onclose=()=>setTimeout(connectLogs,2000);
}
function send() {
  const enabled=canDrive();
  const v=enabled?-y*settings.linear:0, w=enabled?-x*settings.angular:0;
  $('#v').textContent=v.toFixed(2); $('#w').textContent=w.toFixed(2);
  if (controlId && teleop?.readyState===WebSocket.OPEN) teleop.send(JSON.stringify({type:'twist',v,w,linear_limit:settings.linear,angular_limit:settings.angular}));
}
function release() { pointer=null; x=y=0; $('#stick').style.transform='translate(-50%,-50%)'; send(); }
function canDrive() { return !!controlId&&controlLeaseReady&&!state.estopped&&(state.mock||state.ros_available)&&teleop?.readyState===WebSocket.OPEN; }
const joystick=$('#joystick');
function move(event) {
  if(event.pointerId!==pointer) return;
  const rect=joystick.getBoundingClientRect(), radius=rect.width*.35;
  let dx=event.clientX-rect.left-rect.width/2,dy=event.clientY-rect.top-rect.height/2;
  const size=Math.hypot(dx,dy); if(size>radius){dx*=radius/size;dy*=radius/size;}
  x=dx/radius;y=dy/radius;
  $('#stick').style.transform=`translate(calc(-50% + ${dx}px),calc(-50% + ${dy}px))`;send();
}
joystick.addEventListener('pointerdown',e=>{if(pointer!==null||!canDrive())return;pointer=e.pointerId;joystick.setPointerCapture(pointer);move(e);});
joystick.addEventListener('pointermove',move);
for(const event of ['pointerup','pointercancel','lostpointercapture']) joystick.addEventListener(event,e=>{if(e.pointerId===pointer)release();});
$$('[data-drive]').forEach(button=>{
  button.addEventListener('pointerdown',e=>{
    if(pointer!==null||!canDrive())return;
    pointer=e.pointerId;button.setPointerCapture(pointer);
    [x,y]={forward:[0,-1],back:[0,1],left:[-1,0],right:[1,0]}[button.dataset.drive];send();
  });
  for(const event of ['pointerup','pointercancel','lostpointercapture'])button.addEventListener(event,e=>{if(e.pointerId===pointer)release();});
});
$('#direction-stop').onclick=release;
window.addEventListener('blur',release);
document.addEventListener('visibilitychange',()=>{if(document.hidden)release();});
setInterval(()=>{if(pointer!==null)send();},50);
for(const key of ['linear','angular']) {
  const maximum=key==='linear'?.25:.8;
  const show=()=>{ $(`#${key}-limit`).value=settings[key]; $(`#${key}-number`).value=settings[key].toFixed(2); };
  for(const suffix of ['limit','number'])$(`#${key}-${suffix}`).addEventListener('input',event=>{
    if(event.target.value===''||!Number.isFinite(Number(event.target.value)))return;
    settings[key]=Math.round(Math.max(0,Math.min(maximum,Number(event.target.value)))*100)/100;
    show();remember(); if(pointer!==null)send();
  });
  $(`#${key}-number`).addEventListener('blur',show);show();
}
function readOptions() {
  const options=settings.profiles[settings.profile];
  options.rviz=$('#use-rviz').checked; options.record=$('#record').checked;
  options.bag_name=$('#bag-name').value.trim(); options.use_amcl=$('#use-amcl').checked;
  $('#bag-option').hidden=!options.record;remember();
}
function showOptions() {
  const p=settings.profile,options=settings.profiles[p];
  $('#profile').value=p; $('#navigate-options').hidden=p!=='navigate';$('#rviz-option').hidden=p==='teleop';
  $('#use-rviz').checked=options.rviz;$('#record').checked=options.record;$('#bag-name').value=options.bag_name;
  $('#use-amcl').checked=options.use_amcl;$('#bag-option').hidden=!options.record;renderMaps();updateControls();
}
$('#profile').onchange=event=>{readOptions();settings.profile=event.target.value;remember();showOptions();};
for(const selector of ['#use-rviz','#record','#bag-name','#use-amcl']) $(selector).onchange=readOptions;
function renderMaps() {
  const selected=settings.profiles.navigate.map;
  for(const select of $$('.map-select')) {
    select.replaceChildren();
    const placeholder=new Option('Выберите карту','');select.add(placeholder);
    for(const map of catalog) {
      const option=new Option(map.valid?map.name:`${map.name} — недоступна`,map.id);option.disabled=!map.valid;select.add(option);
    }
    if(selected&&!catalog.some(map=>map.id===selected)) {
      const missing=new Option(`${selected} — не найдена`,selected);missing.disabled=true;select.add(missing);
    }
    select.value=selected||'';
  }
  const chosen=catalog.find(map=>map.id===selected);
  for(const text of $$('.map-info')) text.textContent=chosen?.valid?
    `${chosen.width} × ${chosen.height} пикс. · ${chosen.resolution} м/пикс. · ${(chosen.width*chosen.resolution).toFixed(2)} × ${(chosen.height*chosen.resolution).toFixed(2)} м · ${new Date(chosen.modified).toLocaleString()}`:
    chosen?`Карта повреждена: ${chosen.error}`:selected?'Выбранная карта не найдена. Выберите доступную.':'Карта не выбрана';
  for(const image of $$('.map-preview')) { image.hidden=!chosen?.valid;if(chosen?.valid) image.src=chosen.preview_url;else image.removeAttribute('src'); }
  const list=$('#map-list');list.replaceChildren();
  for(const map of catalog) {
    const row=document.createElement('div'), text=document.createElement('span'), title=document.createElement('b'), info=document.createElement('small'), button=document.createElement('button');
    title.textContent=map.name;info.textContent=map.valid?`${map.width} × ${map.height} · ${map.resolution} м/пикс. · ${new Date(map.modified).toLocaleString()}`:map.error;
    text.append(title,info);button.textContent=map.id===selected?'Выбрана':'Выбрать';button.disabled=!map.valid;
    button.onclick=()=>selectMap(map.id);row.append(text,button);list.append(row);
  }
  if(!catalog.length)list.textContent='Сохранённых карт пока нет.';
}
function selectMap(id){settings.profiles.navigate.map=id||null;remember();renderMaps();updateControls();window.dispatchEvent(new Event('ijk-map-changed'));}
$$('.map-select').forEach(select=>select.onchange=()=>selectMap(select.value));
async function loadMaps(){const data=await get('/api/maps');catalog=data.maps;if(settings.profiles.navigate.map===null&&data.default_map)settings.profiles.navigate.map=data.default_map;remember();renderMaps();updateControls();window.dispatchEvent(new Event('ijk-map-changed'));}
$('#reload-maps').onclick=()=>loadMaps().catch(e=>notice(e.message));
const phaseLabels={idle:'Процесс не запущен',starting:'Запускается',running:'Процесс запущен',stopping:'Останавливается',error:'Ошибка процесса'};
function updateControls() {
  const busy=requestBusy||saving, active=!!state.active_profile;
  const invalidMap=settings.profile==='navigate'&&!catalog.some(map=>map.id===settings.profiles.navigate.map&&map.valid);
  $('#start-profile').disabled=busy||active||!!state.estopped||invalidMap;
  $('#start-profile').textContent=requestBusy?'Выполняется…':`Запустить ${names[settings.profile]}`;
  $('#stop-profile').disabled=busy||!active;$('#bench-stop').disabled=busy||!active;
  $$('[data-start]').forEach(b=>b.disabled=busy||active||!!state.estopped);
  $('#mapping-save').hidden=state.active_profile!=='mapping';
  for(const selector of ['#quick-save','#save-map','#save-stop'])$(selector).disabled=busy||!!state.estopped;
  $('#discard-stop').disabled=busy;
  $('#estop-alert').hidden=!state.estopped;
  $('#drive-status').textContent=state.estopped?'Движение заблокировано':!canDrive()?'Канал управления недоступен':state.mock?'Симуляция: команды на оборудование не публикуются':state.active_profile==='mapping'?'Mapping работает. Можно рулить джойстиком и сохранять карту.':state.active_profile?'Можно управлять джойстиком. Отпустите для остановки.':'Для движения запустите Teleop или Mapping. Канал управления подключен.';
}
function displayState() {
  $('#ip').textContent=`${state.robot_ip||'Не найден'} · ${state.ssh_online?'SSH доступен':'SSH недоступен'}`;
  $('#domain').textContent=`${state.ros_available?'Подключён':state.mock?'Mock':'Недоступен'} · ${state.domain_id??'—'}`;
  $('#tmux').textContent=state.tmux_running?'Работает':'Не запущен';
  $('#active').textContent=state.active_profile||'Не запущен';
  $('#connection').textContent=state.mock?'● СИМУЛЯЦИЯ':state.ssh_online?'● PI В СЕТИ':'○ PI НЕДОСТУПНА';
  $('#process-state').textContent=phaseLabels[state.process_state]||'Процесс не запущен';
  const o=state.active_options||{}, rows=[];
  if(state.active_profile)rows.push(`Профиль: ${names[state.active_profile]||state.active_profile}`);
  if(o.map)rows.push(`Карта: ${o.map}`);
  if('use_amcl'in o)rows.push(`AMCL: ${o.use_amcl?'включён':'выключен'}`);
  if('rviz'in o)rows.push(`RViz: ${o.rviz?'включён':'выключен'}`);
  if('record'in o)rows.push(`Rosbag: ${o.record?o.bag_name||'автоматическое имя':'выключен'}`);
  if(state.last_error)rows.push(state.last_error);
  $('#running-options').textContent=rows.join('\n');updateControls();
}
async function refresh(){state=await get('/api/status');if(state.estopped)release();displayState();if(state.map_job&&!handledJobs.has(state.map_job.id)&&watchedJob!==state.map_job.id)watchJob(state.map_job.id);}
async function refreshLoop(){try{await refresh();}catch(e){notice(`Статус недоступен: ${e.message}`);}setTimeout(refreshLoop,2000);}
async function act(fn){if(requestBusy)return;requestBusy=true;updateControls();try{notice();await fn();await refresh();}catch(e){notice(e.message);}finally{requestBusy=false;updateControls();}}
$('#start-profile').onclick=()=>act(async()=>{
  readOptions();const profile=settings.profile,stored=settings.profiles[profile],options={record:stored.record};
  if(stored.record&&stored.bag_name)options.bag_name=stored.bag_name;
  if(profile!=='teleop')options.rviz=stored.rviz;
  if(profile==='navigate'){options.map=stored.map;options.use_amcl=stored.use_amcl;}
  state.process_state='starting';displayState();await api('/api/profile/start',{profile,options});
});
$$('[data-start]').forEach(b=>b.onclick=()=>act(()=>api('/api/profile/start',{profile:b.dataset.start})));
function newMapName(){const now=new Date(),pad=n=>String(n).padStart(2,'0');return `map_${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;}
function resetNames(){for(const id of ['map-name','quick-map-name','stop-map-name'])$('#'+id).value=newMapName();}
function jobText(job){return job.state==='running'?`Сохраняется карта «${job.name}»…`:job.state==='succeeded'?`Сохранена карта «${job.name}»${job.stop_after?'; Mapping остановлен':''}`:job.error||'Сохранение отменено';}
async function watchJob(id){
  watchedJob=id;saving=true;updateControls();
  try{
    let job=await get('/api/jobs/'+id);
    for(const target of ['#quick-job','#map-job'])$(target).textContent=jobText(job);
    if(job.state==='running'){setTimeout(()=>watchJob(id),650);return;}
    handledJobs.add(id);settings.seenJob=id;remember();watchedJob=null;saving=false;
    if(job.map_id){await loadMaps();selectMap(job.map_id);resetNames();}
    if(job.state==='succeeded'){
      if($('#mapping-stop').open)$('#mapping-stop').close();notice();
    }else{notice(jobText(job));$('#stop-error').textContent=jobText(job);}
    await refresh();
  }catch(e){notice(`Не удалось получить результат сохранения: ${e.message}`);watchedJob=null;saving=false;}
  updateControls();
}
async function saveMap(name,stopAfter=false){
  if(saving)return;
  saving=true;updateControls();
  try{notice();const job=await api('/api/maps/save',{name:name.trim(),stop_after:stopAfter});watchJob(job.id);}
  catch(e){saving=false;$('#stop-error').textContent=e.message;notice(e.message);updateControls();}
}
$('#quick-save').onclick=()=>saveMap($('#quick-map-name').value);
$('#save-map').onclick=()=>saveMap($('#map-name').value);
function requestStop(){
  release();if(state.active_profile==='mapping'){
    $('#stop-map-name').value=$('#quick-map-name').value||newMapName();$('#stop-error').textContent='';$('#mapping-stop').showModal();
  }else stopNow();
}
async function stopNow(){await act(async()=>{state.process_state='stopping';displayState();await api('/api/profile/stop');$('#mapping-stop').close();});}
$('#stop-profile').onclick=requestStop;$('#bench-stop').onclick=requestStop;
$('#cancel-stop').onclick=()=>$('#mapping-stop').close();
$('#discard-stop').onclick=stopNow;
$('#save-stop').onclick=()=>saveMap($('#stop-map-name').value,true);
$('#estop').onclick=async()=>{release();try{await api('/api/estop');await refresh();}catch(e){notice(e.message);}};
$('#reset').onclick=()=>act(()=>api('/api/reset'));
$('#discover').onclick=()=>act(()=>api('/api/discovery'));
$$('[data-op]').forEach(b=>b.onclick=()=>act(()=>api('/api/ops/'+b.dataset.op,{profile:'list'})));
$$('.tab').forEach(b=>b.onclick=()=>{$$('.tab').forEach(t=>t.classList.toggle('selected',t===b));$$('.page').forEach(p=>p.hidden=p.id!==b.dataset.tab);});
$('#clear').onclick=()=>{$('#log').textContent='';};
$('#pause').onclick=()=>{paused=!paused;$('#pause').textContent=paused?'Продолжить':'Пауза';};
resetNames();showOptions();connectTeleop();connectLogs();loadMaps().catch(e=>notice(e.message));refreshLoop();

setInterval(()=>{
  if(controlId&&!document.hidden&&teleop?.readyState===WebSocket.OPEN)teleop.send(JSON.stringify({type:'heartbeat'}));
},100);
$('#claim-control').onclick=()=>{if(teleop?.readyState===WebSocket.OPEN)teleop.send(JSON.stringify({type:'claim'}));else{pendingClaim=true;notice('Подключается управляющий канал…');}};
$('#release-control').onclick=()=>{release();if(teleop?.readyState===WebSocket.OPEN)teleop.send(JSON.stringify({type:'release'}));};
