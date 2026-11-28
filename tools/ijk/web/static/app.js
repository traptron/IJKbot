'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const names = {teleop:'Teleop', mapping:'Mapping', navigate:'Navigate', showcase:'Showcase', competition:'Competition'};
const storageKey = 'ijk.control.v1';
const defaults = () => ({version:1, profile:'teleop', linear:.15, angular:.48, seenJob:null,
  profiles:Object.fromEntries(Object.keys(names).map(p => [p,{record:false,bag_name:'',rviz:true,terrain_3d:false,use_amcl:true,map:null}]))});
let settings = defaults();
try {
  const saved = JSON.parse(localStorage.getItem(storageKey));
  if (saved?.version === 1) {
    if (Object.hasOwn(names,saved.profile)) settings.profile = saved.profile;
    for (const key of ['linear','angular']) if (Number.isFinite(saved[key]) && saved[key]>=0) settings[key] = Math.min(key==='linear'?.25:.8,saved[key]);
    if (typeof saved.seenJob === 'string') settings.seenJob=saved.seenJob;
    for (const p of Object.keys(names)) {
      const item = saved.profiles?.[p]; if (!item) continue;
      for (const key of ['record','rviz','use_amcl','terrain_3d']) if (typeof item[key] === 'boolean') settings.profiles[p][key] = item[key];
      for (const key of ['bag_name','map']) if (typeof item[key] === 'string') settings.profiles[p][key] = item[key];
    }
  }
} catch (_) { /* Storage may be unavailable; controls remain usable. */ }
function remember() { try { localStorage.setItem(storageKey, JSON.stringify(settings)); } catch (_) {} }
function notice(message='',kind='error') {const box=$('#alert');box.textContent=message;box.hidden=!message;box.dataset.kind=kind;box.setAttribute('role',kind==='error'?'alert':'status');}
async function api(path,data={}) {
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',...(controlId?{'X-Control-Id':controlId}:{})},body:JSON.stringify(data)});
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
async function get(path) { const response=await fetch(path); if (!response.ok) throw new Error(await response.text()); return response.json(); }
let controlId=null, controlLeaseReady=false, manualDriveReason=null, pendingClaim=false;
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
function driveBlockReason() {
  if(modeBusy)return 'Переключается режим управления';
  if(state.estopped)return 'Движение заблокировано аварийной остановкой';
  if(state.control_error)return 'Ошибка управляющего цикла: '+state.control_error;
  if(teleop?.readyState!==WebSocket.OPEN)return 'Подключается управляющий канал';
  if(!state.mock&&state.local===false&&!state.robot_ip)return 'Робот не найден. Выполните поиск.';
  if(!controlId)return 'Нажмите «Взять управление», чтобы включить джойстик';
  if(manualDriveReason)return manualDriveReason;
  if(!controlLeaseReady)return 'Ожидаем подтверждения управляющей сессии';
  if(!state.mock&&!state.ros_available)return 'ROS-мост недоступен';
  return '';
}
function canDrive() { return !driveBlockReason(); }
const joystick=$('#joystick');
function move(event) {
  if(event.pointerId!==pointer) return;
  const rect=joystick.getBoundingClientRect(), radius=rect.width*.35;
  let dx=event.clientX-rect.left-rect.width/2,dy=event.clientY-rect.top-rect.height/2;
  const size=Math.hypot(dx,dy); if(size>radius){dx*=radius/size;dy*=radius/size;}
  x=dx/radius;y=dy/radius;
  $('#stick').style.transform=`translate(calc(-50% + ${dx}px),calc(-50% + ${dy}px))`;send();
}
joystick.addEventListener('pointerdown',e=>{if(pointer!==null)return;if(!canDrive()){notice(driveBlockReason());return;}pointer=e.pointerId;joystick.setPointerCapture(pointer);move(e);});
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
  if(settings.profile==='mapping')options.terrain_3d=$('#terrain-3d').checked;
  options.bag_name=$('#bag-name').value.trim(); options.use_amcl=$('#use-amcl').checked;
  $('#bag-option').hidden=!options.record;remember();
}
function showOptions() {
  const p=settings.profile,options=settings.profiles[p];
  $('#mapping-options').hidden=p!=='mapping';$('#terrain-3d').checked=options.terrain_3d;
  $('#profile').value=p; $('#navigate-options').hidden=p!=='navigate';$('#rviz-option').hidden=p==='teleop';
  $('#use-rviz').checked=options.rviz;$('#record').checked=options.record;$('#bag-name').value=options.bag_name;
  $('#use-amcl').checked=options.use_amcl;$('#bag-option').hidden=!options.record;renderMaps();updateControls();
}
$('#profile').onchange=event=>{readOptions();settings.profile=event.target.value;remember();showOptions();};
for(const selector of ['#use-rviz','#record','#bag-name','#use-amcl','#terrain-3d']) $(selector).onchange=readOptions;
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
    row.dataset.selected=String(map.id===selected);button.className='secondary';button.setAttribute('aria-pressed',String(map.id===selected));title.textContent=map.name;info.textContent=map.valid?`${map.width} × ${map.height} · ${map.resolution} м/пикс. · ${new Date(map.modified).toLocaleString()}`:map.error;
    text.append(title,info);button.textContent=map.id===selected?'Выбрана':'Выбрать';button.disabled=!map.valid;
    button.onclick=()=>selectMap(map.id);row.append(text,button);list.append(row);
  }
  if(!catalog.length)list.textContent='Сохранённых карт пока нет.';
}
function selectMap(id){notice(id?'Для следующего Navigate выбрана карта '+id:'Выбор карты снят','success');settings.profiles.navigate.map=id||null;remember();renderMaps();updateControls();window.dispatchEvent(new Event('ijk-map-changed'));}
$$('.map-select').forEach(select=>select.onchange=()=>selectMap(select.value));
async function loadMaps(){const data=await get('/api/maps');catalog=data.maps;if(settings.profiles.navigate.map===null&&data.default_map)settings.profiles.navigate.map=data.default_map;remember();renderMaps();updateControls();window.dispatchEvent(new Event('ijk-map-changed'));}
$('#reload-maps').onclick=()=>act(loadMaps,'Обновляем каталог карт…','Каталог карт обновлён');
const phaseLabels={idle:'Процесс не запущен',starting:'Запускается',running:'Процесс запущен',stopping:'Останавливается',error:'Ошибка процесса'};
let maintenanceBusy=false, maintenanceStarting=false, maintenanceId=null, modeBusy=false, controlOwned=false;
function updateControls() {
  const busy=requestBusy||saving||modeBusy, active=!!state.active_profile;
  if(modeBusy)$('#claim-control').disabled=true;
  if(!modeBusy)$('#simulation-toggle').checked=!!state.mock;
  $('#simulation-toggle').disabled=busy||active||maintenanceBusy||controlOwned;
  $('#simulation-toggle').setAttribute('aria-busy',String(modeBusy));
  $('#discover').disabled=busy||maintenanceBusy||active;
  $$('[data-op]').forEach(b=>b.disabled=busy||maintenanceBusy||active||!!state.estopped);
  const invalidMap=settings.profile==='navigate'&&!catalog.some(map=>map.id===settings.profiles.navigate.map&&map.valid);
  $('#start-profile').disabled=busy||active||!!state.estopped||invalidMap;
  $('#start-profile').textContent=requestBusy?'Выполняется…':`Запустить ${names[settings.profile]}`;
  $('#stop-profile').disabled=busy||!active;$('#bench-stop').disabled=busy||!active;
  $$('[data-start]').forEach(b=>b.disabled=busy||active||!!state.estopped);
  $('#mapping-save').hidden=state.active_profile!=='mapping';
  for(const selector of ['#quick-save','#save-map','#save-stop'])$(selector).disabled=busy||!!state.estopped;
  $('#discard-stop').disabled=busy;
  $('#estop-alert').hidden=!state.estopped;
  const blocked=driveBlockReason();
  if(blocked&&pointer!==null)release();
  joystick.dataset.enabled=String(!blocked);joystick.setAttribute('aria-disabled',String(!!blocked));
  $$('[data-drive]').forEach(button=>button.disabled=!!blocked);
  $('#drive-status').textContent=blocked||(state.mock?'Симуляция: можно двигать стик, команды на оборудование не публикуются':state.active_profile==='mapping'?'Mapping работает. Можно рулить джойстиком и сохранять карту.':state.active_profile?'Отпустите стик для остановки.':'Для движения робота запустите Teleop или Mapping.');
}
function displayState() {
  $('#ip').textContent=`${state.robot_ip||'Не найден'} · ${state.ssh_online?'SSH доступен':'SSH недоступен'}`;
  $('#domain').textContent=`${state.ros_available?'Подключён':state.mock?'Mock':'Недоступен'} · ${state.domain_id??'—'}`;
  $('#tmux').textContent=state.tmux_running?'Работает':'Не запущен';
  $('#active').textContent=state.active_profile||'Не запущен';
  $('#connection').textContent=state.mock?'Симуляция':state.ssh_online?'Робот в сети':'Робот недоступен';
  $('#connection').dataset.state=state.mock?'mock':state.ssh_online?'online':'offline';
  $('#process-state').textContent=phaseLabels[state.process_state]||'Процесс не запущен';
  const o=state.active_options||{}, rows=[];
  if(state.active_profile)rows.push(`Профиль: ${names[state.active_profile]||state.active_profile}`);
  if(o.map)rows.push(`Карта: ${o.map}`);
  if('use_amcl'in o)rows.push(`AMCL: ${o.use_amcl?'включён':'выключен'}`);
  if(o.terrain_3d)rows.push('3D-карта · лидар и RealSense');
  if('rviz'in o)rows.push(`RViz: ${o.rviz?'включён':'выключен'}`);
  if('record'in o)rows.push(`Rosbag: ${o.record?o.bag_name||'автоматическое имя':'выключен'}`);
  if(state.last_error)rows.push(state.last_error);
  $('#running-options').textContent=rows.join('\n');updateControls();
}
async function refresh(){state=await get('/api/status');if(state.estopped)release();displayState();if(state.map_job&&!handledJobs.has(state.map_job.id)&&watchedJob!==state.map_job.id)watchJob(state.map_job.id);}
async function refreshLoop(){try{await refresh();}catch(e){notice(`Статус недоступен: ${e.message}`);}setTimeout(refreshLoop,2000);}
async function act(fn,label='Выполнение действия…',complete='Действие выполнено'){if(requestBusy)return;requestBusy=true;updateControls();try{notice(label,'running');await fn();await refresh();notice(complete,'success');}catch(e){notice(e.message);}finally{requestBusy=false;updateControls();}}
$('#start-profile').onclick=()=>act(async()=>{
  readOptions();const profile=settings.profile,stored=settings.profiles[profile],options={record:stored.record};
  if(stored.record&&stored.bag_name)options.bag_name=stored.bag_name;
  if(profile!=='teleop')options.rviz=stored.rviz;
  if(profile==='mapping' && stored.terrain_3d)options.terrain_3d=true;
  if(profile==='navigate'){options.map=stored.map;options.use_amcl=stored.use_amcl;}
  state.process_state='starting';displayState();await api('/api/profile/start',{profile,options});
},'Запускаем выбранный профиль…','Процесс профиля запущен. Готовность оборудования смотрите в «Состоянии»');
$$('[data-start]').forEach(b=>b.onclick=()=>act(()=>api('/api/profile/start',{profile:b.dataset.start}),'Запуск подсистемы…','Процесс подсистемы запущен; проверьте его вывод в журнале'));
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
      if($('#mapping-stop').open)$('#mapping-stop').close();notice(jobText(job),'success');
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
async function stopNow(){await act(async()=>{state.process_state='stopping';displayState();await api('/api/profile/stop');$('#mapping-stop').close();},'Останавливаем профиль…','Профиль остановлен');}
$('#stop-profile').onclick=requestStop;$('#bench-stop').onclick=requestStop;
$('#cancel-stop').onclick=()=>$('#mapping-stop').close();
$('#discard-stop').onclick=stopNow;
$('#save-stop').onclick=()=>saveMap($('#stop-map-name').value,true);
$('#estop').onclick=async()=>{release();try{await api('/api/estop');await refresh();}catch(e){notice(e.message);}};
$('#reset').onclick=()=>act(()=>api('/api/reset'),'Снимаем аварийную блокировку…','Блокировка снята. Движение не возобновлено');
const maintenanceNames={discovery:'Поиск робота',timesync:'Синхронизация времени',wifi:'Список Wi-Fi'};
function renderMaintenance(job){
  const labels={running:'Выполняется',succeeded:'Завершено',failed:'Ошибка',cancelled:'Остановлено'};
  maintenanceBusy=job.state==='running';
  $('#maintenance-panel').dataset.state=job.state;
  $('#maintenance-title').textContent=maintenanceNames[job.action]||'Обслуживание';
  $('#maintenance-state').textContent=labels[job.state]||job.state;
  $('#maintenance-summary').textContent=job.message;
  const elapsed=Math.max(0,(job.finished_at||Date.now()/1000)-job.started_at);
  $('#maintenance-time').textContent=(maintenanceBusy?'Прошло: ':'Длительность: ')+elapsed.toFixed(1)+' с';
  const output=$('#maintenance-output'),atBottom=output.scrollTop+output.clientHeight>=output.scrollHeight-24;
  const text=(job.output||[]).join('\n');if(output.textContent!==text){output.textContent=text;if(atBottom)output.scrollTop=output.scrollHeight;}
  $$('[data-op],#discover').forEach(button=>button.setAttribute('aria-busy',String(maintenanceBusy&&((button.dataset.op||'discovery')===job.action))));
  updateControls();
}
let maintenanceTerminal=null;
async function pollMaintenance(){
  try{
    const {job}=await get('/api/maintenance');
    if(job&&!(maintenanceStarting&&job.id===maintenanceId)){
      renderMaintenance(job);
      if(!maintenanceStarting)maintenanceId=job.id;
      if(job.state!=='running'&&maintenanceTerminal!==job.id){
        maintenanceTerminal=job.id;
        if(document.querySelector('#ops').hidden===false)notice(job.message,job.state==='succeeded'?'success':'error');
      }
    }
  }catch(e){if(maintenanceBusy){$('#maintenance-summary').textContent='Не удаётся получить ход операции: '+e.message;}}
}
setInterval(pollMaintenance,800);pollMaintenance();
async function runMaintenance(action){
  if(requestBusy||maintenanceBusy)return;
  maintenanceStarting=true;requestBusy=true;maintenanceBusy=true;
  const name=maintenanceNames[action];
  renderMaintenance({action,state:'running',started_at:Date.now()/1000,message:'Запрос отправляется на сервер…',output:[]});
  notice(name+': запускаем…','running');
  try{const response=await api(action==='discovery'?'/api/discovery':'/api/ops/'+action,{profile:'list'});maintenanceId=response.job_id;}
  catch(e){notice(e.message);renderMaintenance({action,state:'failed',started_at:Date.now()/1000,finished_at:Date.now()/1000,message:e.message,output:[e.message]});}
  finally{maintenanceStarting=false;requestBusy=false;await pollMaintenance();updateControls();}
}
$('#discover').onclick=()=>runMaintenance('discovery');
$$('[data-op]').forEach(b=>b.onclick=()=>runMaintenance(b.dataset.op));
$('#open-ops-logs').onclick=()=>document.querySelector('[data-tab="logs"]').click();
const pageCopy={control:['Управление','Ручное движение и настройки запуска'],maps:['Карты','Сохранённые пространства для навигации'],health:['Состояние','Приводы, датчики и качество связи'],routes:['Места и маршруты','Точки назначения на выбранной карте'],bench:['Стенд','Проверка отдельных подсистем'],ops:['Обслуживание','Подключение и настройки системы'],logs:['Журнал','События и вывод процессов']};
const mobileNavigation=matchMedia('(max-width:900px)');
function syncNavigation(){document.querySelector('.sidebar').toggleAttribute('inert',mobileNavigation.matches&&!document.body.classList.contains('nav-open'));}
mobileNavigation.addEventListener('change',syncNavigation);syncNavigation();
function closeNavigation(){document.body.classList.remove('nav-open');$('#nav-toggle').setAttribute('aria-expanded','false');$('#nav-backdrop').hidden=true;syncNavigation();}
$('#nav-toggle').onclick=()=>{const open=!document.body.classList.contains('nav-open');document.body.classList.toggle('nav-open',open);$('#nav-toggle').setAttribute('aria-expanded',String(open));$('#nav-backdrop').hidden=!open;syncNavigation();};
$('#nav-backdrop').onclick=closeNavigation;
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeNavigation();});
$$('.tab').forEach(b=>b.onclick=()=>{
  $$('.tab').forEach(t=>{t.classList.toggle('selected',t===b);if(t===b)t.setAttribute('aria-current','page');else t.removeAttribute('aria-current');});
  $$('.page').forEach(p=>p.hidden=p.id!==b.dataset.tab);
  $('#page-title').textContent=pageCopy[b.dataset.tab][0];$('#page-description').textContent=pageCopy[b.dataset.tab][1];document.title=pageCopy[b.dataset.tab][0]+' · IJKbot';
  closeNavigation();window.scrollTo({top:0,behavior:'instant'});
});
$('#clear').onclick=()=>{$('#log').textContent='';};
$('#pause').onclick=()=>{paused=!paused;$('#pause').textContent=paused?'Продолжить':'Пауза';};
resetNames();showOptions();connectTeleop();connectLogs();loadMaps().catch(e=>notice(e.message));refreshLoop();

setInterval(()=>{
  if(controlId&&!document.hidden&&teleop?.readyState===WebSocket.OPEN)teleop.send(JSON.stringify({type:'heartbeat'}));
},100);
$('#claim-control').onclick=()=>{notice('Запрос управления…');if(teleop?.readyState===WebSocket.OPEN)teleop.send(JSON.stringify({type:'claim'}));else{pendingClaim=true;notice('Подключается управляющий канал…');}};
$('#release-control').onclick=()=>{release();if(teleop?.readyState===WebSocket.OPEN)teleop.send(JSON.stringify({type:'release'}));};

$('#simulation-toggle').onchange=async event=>{
  if(modeBusy)return;
  const requested=event.target.checked;
  modeBusy=true;updateControls();
  notice(requested?'Включаем симуляцию…':'Подключаем реальный ROS-мост…','running');
  try{
    const result=await api('/api/mode',{mock:requested});
    state.mock=result.mock;controlId=null;controlLeaseReady=false;release();
    await refresh();
    notice(result.mock?'Симуляция включена. Команды не отправляются оборудованию':'Симуляция выключена. Для движения нужны профиль и подтверждённая связь с роботом','success');
  }catch(e){notice(e.message);}
  finally{modeBusy=false;updateControls();}
};
