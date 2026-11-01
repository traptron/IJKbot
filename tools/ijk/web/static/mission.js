'use strict';
(()=>{
  let telemetry=null, socket=null, reconnects=0, pingSeq=0, pings=new Map(), rtts=[], lastFrame=0;
  let documentMap=null, documentData=null, placeDraft=null, placeId=null, routeId=null, routePoints=[], prepared=null, reviewed=false;
  let metadataBusy=false, linkJob=null, interpretationBusy=false;
  const mapCanvas=$('#mission-map'), radar=$('#radar'), mapImage=new Image();
  const camera={zoom:0,x:0,y:0}, pointers=new Map();
  let pick=false,pickStart=null,pinchDistance=0;
  const safe=fn=>async()=>{try{notice();await fn();}catch(e){notice(e.message);}};
  const selected=()=>settings.profiles.navigate.map;
  const uid=prefix=>prefix+'_'+crypto.randomUUID().replaceAll('-','');
  const fmt=(value,digits=1)=>Number.isFinite(Number(value))&&value!==null&&value!==undefined?Number(value).toFixed(digits):'нет данных';
  const age=s=>s?.age_s==null?'нет данных':s.age_s<1?`${Math.round(s.age_s*1000)} мс`:`${s.age_s.toFixed(1)} с`;
  const setText=(id,text)=>{$(id).textContent=text;};
  function row(container,label,value,stale=false){const div=document.createElement('div');div.className='telemetry-row'+(stale?' stale':'');const key=document.createElement('span'),val=document.createElement('strong');key.textContent=label;val.textContent=value;div.append(key,val);container.append(div);}
  function connect(){
    socket=new WebSocket(wsUrl('/ws/telemetry'));
    socket.onmessage=event=>{
      const data=JSON.parse(event.data);
      if(data.type==='pong'){
        if(pings.has(data.seq)){rtts.push({t:performance.now(),ms:performance.now()-pings.get(data.seq)});pings.delete(data.seq);}
        rtts=rtts.filter(v=>performance.now()-v.t<30000);return;
      }
      if(data.type!=='telemetry')return;
      telemetry=data;lastFrame=performance.now();controlLeaseReady=!!data.control.ready;
      $('#claim-control').textContent=controlId?'Восстановить управление':'Взять управление';
      $('#claim-control').disabled=!!state.estopped||(!controlId&&data.control.owned);
      $('#release-control').hidden=!controlId;
      setText('#lease-status',controlId?(data.control.ready?'Вы управляете · Pi подтверждает связь':data.control.broken?'Связь потеряна · требуется восстановление':'Ожидание подтверждения Pi'):data.control.owned?'Управляет другая вкладка':'Наблюдение');
      setText('#health-summary',data.summary);setText('#health-detail',data.summary);
      renderSignals();
      renderTelemetry();renderNavigation();drawRadar();drawMap();updateControls();
    };
    socket.onclose=()=>{reconnects++;controlLeaseReady=false;setText('#health-summary','Телеметрия отключена');setTimeout(connect,1500);};
  }
  setInterval(()=>{
    if(socket?.readyState===WebSocket.OPEN){const seq=++pingSeq;pings.set(seq,performance.now());socket.send(JSON.stringify({type:'ping',seq}));}
    for(const [key,start]of pings)if(performance.now()-start>3000)pings.delete(key);
    if(lastFrame&&performance.now()-lastFrame>1500){controlLeaseReady=false;setText('#health-summary','Телеметрия устарела');$$('.telemetry-row,.health-signal').forEach(row=>row.classList.add('stale'));updateControls();drawRadar();drawMap();}
    const samples=rtts.map(v=>v.ms).sort((a,b)=>a-b);
    setText('#browser-link',`Браузер ↔ сервер: RTT p50 ${fmt(samples[Math.floor(samples.length/2)])} мс · p95 ${fmt(samples[Math.max(0,Math.ceil(samples.length*.95)-1)])} мс · переподключений ${reconnects} · ответов ${samples.length}`);
  },500);
  function renderSignals(){
    const topics=telemetry.topics,drive=topics.diagnostics.data?.sts3215_drive,nav=topics.nav.data||{},container=$('#health-signals');
    container.replaceChildren();
    const signals=[['E-STOP',telemetry.estopped?'АКТИВЕН':'снят',telemetry.estopped],
      ['Приводы',!drive||drive.stale?'нет данных':drive.level>=2?'ошибка':drive.level===1?'предупреждение':'готовы',!drive||drive.stale||drive.level>=2],
      ['Odom',topics.odom.stale?'нет свежих данных':'свежая',topics.odom.stale],
      ['Scan',topics.scan.stale?'нет свежих данных':'свежий',topics.scan.stale],
      ['TF map',topics.pose.stale?'недоступен':'доступен',topics.pose.stale],
      ['AMCL',!topics.nav.stale&&nav.amcl_active&&topics.amcl.data?'активен':'не готов',topics.nav.stale||!nav.amcl_active||!topics.amcl.data],
      ['Nav2',!topics.nav.stale&&nav.ready&&nav.navigator_active?'готов':'не готов',topics.nav.stale||!nav.ready||!nav.navigator_active],
      ['Задача',['idle','complete','cancelled'].includes(telemetry.navigation.state)?'Ожидание команды':telemetry.navigation.point||telemetry.navigation.label||'Ожидание команды',false]];
    for(const [name,value,unavailable]of signals){const chip=document.createElement('span');chip.className='health-signal'+(unavailable?' stale':'');chip.textContent=`${name}: ${value}`;container.append(chip);}
  }
  function renderTelemetry(){
    const topics=telemetry.topics,drive=topics.diagnostics.data?.sts3215_drive;
    const servo=$('#servo-data');servo.replaceChildren();
    row(servo,'Драйвер',drive?drive.message:'нет данных',!drive||drive.stale);
    row(servo,'Состояние',drive?['Норма','Предупреждение','Ошибка','Нет данных'][drive.level]||String(drive.level):'нет данных',!drive||drive.stale);
    for(const id of [1,2]){
      const values=drive?.values||{};
      row(servo,`Привод ${id} · питание`,`${fmt(values[`servo_${id}/voltage_v`])} В`,!drive||drive.stale);
      row(servo,`Привод ${id} · температура`,`${fmt(values[`servo_${id}/temperature_c`])} °C`,!drive||drive.stale);
      row(servo,`Привод ${id} · скорость`,`${fmt(values[`servo_${id}/speed_ticks_s`])} ticks/s`,!drive||drive.stale);
    }
    row(servo,'Возраст диагностики',drive?`${fmt(drive.age_s)} с`:'нет данных',!drive||drive.stale);
    const pi=$('#pi-data');pi.replaceChildren();const system=topics.system.data||{};
    for(const [label,value]of [['CPU',`${fmt(system.cpu_temp_c)} °C`],['Загрузка CPU',`${fmt(system.cpu_percent)} %`],['Доступная память',`${fmt(system.memory_available_mb)} / ${fmt(system.memory_total_mb)} МиБ`],['Сигнал Wi-Fi',`${fmt(system.wifi_dbm)} dBm`]])row(pi,label,value,topics.system.stale);
    const link=$('#link-data');link.replaceChildren();const net=telemetry.link,stale=net.echo_age_s==null||net.echo_age_s>.5;
    for(const [label,value]of [['DDS RTT p50',`${fmt(net.rtt_p50_ms)} мс`],['DDS RTT p95',`${fmt(net.rtt_p95_ms)} мс`],['Колебание RTT',`${fmt(net.jitter_ms)} мс`],['Пропущенные ответы',`${fmt(net.missing_percent)} % (${net.received}/${net.samples})`],['Последний ответ Pi',net.echo_age_s==null?'нет данных':`${fmt(net.echo_age_s)} с назад`]])row(link,label,value,stale);
    const topic=$('#topic-data');topic.replaceChildren();
    const labels={odom:'Одометрия',scan:'Лидар /scan',pose:'TF map → base_footprint',diagnostics:'Диагностика',system:'Состояние Pi',guard:'Контроль связи Pi',nav:'Nav2 / AMCL',amcl:'Последняя оценка AMCL'};
    for(const [key,sample]of Object.entries(topics))row(topic,labels[key]||key,`${age(sample)} · ${sample.hz==null?'—':fmt(sample.hz)} Гц${sample.stale?' · нет свежих данных':''}`,sample.stale);
    if(topics.odom.data)row(topic,'Скорость по одометрии',`${fmt(topics.odom.data.v,2)} м/с · ${fmt(topics.odom.data.w,2)} рад/с`,topics.odom.stale);
    $('#link-test').disabled=!controlId||!!linkJob||!topics.odom.data||topics.odom.stale||['running','waiting','pausing','cancelling'].includes(telemetry.navigation.state);
  }
  async function pollLink(id){
    try{
      const job=await get('/api/jobs/'+id);
      if(job.state==='running'){setText('#link-job','Измерение полезной скорости SSH…');setTimeout(()=>pollLink(id),500);return;}
      linkJob=null;
      setText('#link-job',job.state==='succeeded'?`На Pi: ${fmt(job.result.upload_mbps)} Мбит/с · с Pi: ${fmt(job.result.download_mbps)} Мбит/с. ${job.result.transport}`:job.error||'Тест отменён');
      if(telemetry)renderTelemetry();
    }catch(e){linkJob=null;notice(e.message);}
  }
  $('#link-test').onclick=safe(async()=>{const job=await api('/api/link/test');linkJob=job.id;pollLink(job.id);});
  function surface(canvas){const rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;if(rect.width<10)return null;const width=Math.round(rect.width*dpr),height=Math.round(rect.height*dpr);if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,rect.width,rect.height);return {ctx,width:rect.width,height:rect.height};}
  function drawRadar(){
    const screen=surface(radar);if(!screen)return;const {ctx,width,height}=screen;
    const radius=Number($('#radar-range').value),scale=(Math.min(width,height)-35)/(2*radius),cx=width/2,cy=height/2;
    ctx.strokeStyle='#294742';ctx.fillStyle='#78928e';ctx.font='11px system-ui';
    for(let n=1;n<=4;n++){ctx.beginPath();ctx.arc(cx,cy,n*radius/4*scale,0,Math.PI*2);ctx.stroke();}
    ctx.fillText('ВПЕРЁД',cx-25,15);
    const scan=telemetry?.topics.scan,valid=scan&&!scan.stale&&performance.now()-lastFrame<1500;
    if(valid){ctx.fillStyle='#6be1c5';for(const [x,y]of scan.data.points){if(Math.hypot(x,y)<=radius)ctx.fillRect(cx-y*scale-1,cy-x*scale-1,2,2);}}
    ctx.strokeStyle='#e1eef2';ctx.strokeRect(cx-.125*scale,cy-.05*scale,.25*scale,.23*scale);
    ctx.beginPath();ctx.moveTo(cx,cy+5);ctx.lineTo(cx,cy-10);ctx.stroke();
    setText('#radar-info',valid?`Ближайшее видимое препятствие от центра: ${fmt(scan.data.nearest_m,2)} м · скан ${age(scan)} · радиус ${radius} м`:'Нет свежего скана или TF. Старые точки скрыты.');
  }
  $('#radar-range').oninput=drawRadar;
  const mapInfo=()=>catalog.find(m=>m.id===selected()&&m.valid);
  function worldToPixel(p){const m=mapInfo(),[ox,oy,a]=m.origin,dx=p.x-ox,dy=p.y-oy;return {x:(Math.cos(a)*dx+Math.sin(a)*dy)/m.resolution,y:m.height-(-Math.sin(a)*dx+Math.cos(a)*dy)/m.resolution};}
  function pixelToWorld(p){const m=mapInfo(),[ox,oy,a]=m.origin,x=p.x*m.resolution,y=(m.height-p.y)*m.resolution;return {x:ox+Math.cos(a)*x-Math.sin(a)*y,y:oy+Math.sin(a)*x+Math.cos(a)*y};}
  function fitMap(){const m=mapInfo(),rect=mapCanvas.getBoundingClientRect();if(!m||rect.width<10)return;camera.zoom=Math.min((rect.width-30)/m.width,(rect.height-30)/m.height);camera.x=(rect.width-m.width*camera.zoom)/2;camera.y=(rect.height-m.height*camera.zoom)/2;drawMap();}
  mapImage.onload=fitMap;
  function arrow(ctx,p,color,label){const m=mapInfo(),point=worldToPixel(p),angle=p.yaw-m.origin[2],size=12/camera.zoom;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=2/camera.zoom;ctx.beginPath();ctx.arc(point.x,point.y,4/camera.zoom,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.moveTo(point.x,point.y);ctx.lineTo(point.x+Math.cos(angle)*size,point.y-Math.sin(angle)*size);ctx.stroke();if(label){ctx.font=`${12/camera.zoom}px system-ui`;ctx.fillText(label,point.x+6/camera.zoom,point.y-6/camera.zoom);}}
  function drawMap(){
    const screen=surface(mapCanvas);if(!screen)return;const {ctx,width,height}=screen;
    if(!mapInfo()||!mapImage.complete||!mapImage.naturalWidth){ctx.fillStyle='#8da1ad';ctx.font='14px system-ui';ctx.fillText('Выберите доступную карту',15,30);return;}
    if(!camera.zoom){fitMap();return;}
    ctx.translate(camera.x,camera.y);ctx.scale(camera.zoom,camera.zoom);ctx.imageSmoothingEnabled=false;ctx.drawImage(mapImage,0,0);
    if(documentData){for(const place of documentData.places)arrow(ctx,place,'#197cb4',place.name);}
    const shownPoints=telemetry?.navigation.map_id===selected()&&['running','waiting','paused','pausing'].includes(telemetry.navigation.state)?telemetry.navigation.points||routePoints:routePoints;
    if(shownPoints.length){ctx.strokeStyle='#bd672b';ctx.lineWidth=2/camera.zoom;ctx.beginPath();shownPoints.forEach((p,i)=>{const v=worldToPixel(p);i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y);});ctx.stroke();shownPoints.forEach((p,i)=>arrow(ctx,p,'#bd672b',`${i+1}. ${p.label}`));}
    if(placeDraft)arrow(ctx,placeDraft,'#bd234e','Новое место');
    const pose=telemetry?.topics.pose;
    if(state.active_options?.map===selected()&&pose?.data&&!pose.stale&&performance.now()-lastFrame<1500){arrow(ctx,pose.data,'#b620dc','Робот');setText('#map-pose',`Робот в map: X ${fmt(pose.data.x,2)}, Y ${fmt(pose.data.y,2)}, угол ${fmt(pose.data.yaw*180/Math.PI)}° · TF ${age(pose)}`);}
    else setText('#map-pose','Нет свежего положения робота на выбранной карте');
  }
  function eventPoint(event){const rect=mapCanvas.getBoundingClientRect();return {x:event.clientX-rect.left,y:event.clientY-rect.top};}
  function mapWorld(point){return pixelToWorld({x:(point.x-camera.x)/camera.zoom,y:(point.y-camera.y)/camera.zoom});}
  mapCanvas.addEventListener('pointerdown',event=>{
    if(!mapInfo()||!camera.zoom)return;mapCanvas.setPointerCapture(event.pointerId);const p=eventPoint(event);pointers.set(event.pointerId,p);
    if(pointers.size===2){const [a,b]=[...pointers.values()];pinchDistance=Math.hypot(a.x-b.x,a.y-b.y);pickStart=null;}
    else if(pick)pickStart=mapWorld(p);
  });
  mapCanvas.addEventListener('pointermove',event=>{
    if(!pointers.has(event.pointerId))return;const previous=pointers.get(event.pointerId),now=eventPoint(event);pointers.set(event.pointerId,now);
    if(pointers.size>=2){const [a,b]=[...pointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y),cx=(a.x+b.x)/2,cy=(a.y+b.y)/2;if(pinchDistance>1){const zoom=Math.min(50,Math.max(.1,camera.zoom*distance/pinchDistance)),wx=(cx-camera.x)/camera.zoom,wy=(cy-camera.y)/camera.zoom;camera.zoom=zoom;camera.x=cx-wx*zoom;camera.y=cy-wy*zoom;}pinchDistance=distance;}
    else if(pickStart){const end=mapWorld(now);placeDraft={...pickStart,yaw:Math.atan2(end.y-pickStart.y,end.x-pickStart.x)};showPlacePose();}
    else if(!pick){camera.x+=now.x-previous.x;camera.y+=now.y-previous.y;}
    drawMap();
  });
  function pointerUp(event){
    if(pickStart&&pointers.size===1&&event.type==='pointerup'){const end=mapWorld(eventPoint(event));placeDraft={...pickStart,yaw:Math.hypot(end.x-pickStart.x,end.y-pickStart.y)<.02?0:Math.atan2(end.y-pickStart.y,end.x-pickStart.x)};pick=false;$('#map-pick').textContent='Выбрать место на карте';showPlacePose();}
    pointers.delete(event.pointerId);pickStart=null;pinchDistance=0;drawMap();
  }
  for(const type of ['pointerup','pointercancel','lostpointercapture'])mapCanvas.addEventListener(type,pointerUp);
  mapCanvas.addEventListener('wheel',event=>{event.preventDefault();if(!camera.zoom)return;const p=eventPoint(event),wx=(p.x-camera.x)/camera.zoom,wy=(p.y-camera.y)/camera.zoom;camera.zoom=Math.min(50,Math.max(.1,camera.zoom*Math.exp(-event.deltaY*.001)));camera.x=p.x-wx*camera.zoom;camera.y=p.y-wy*camera.zoom;drawMap();},{passive:false});
  $('#map-pick').onclick=()=>{pick=!pick;$('#map-pick').textContent=pick?'Укажите точку и направление':'Выбрать место на карте';};
  $('#map-reset').onclick=fitMap;
  const observer=new ResizeObserver(()=>{drawRadar();if(!camera.zoom)fitMap();else drawMap();});observer.observe(mapCanvas);observer.observe(radar);
  function showPlacePose(){setText('#place-coordinate',placeDraft?`X ${fmt(placeDraft.x,2)} · Y ${fmt(placeDraft.y,2)}`:'Выберите точку на карте или сохраните текущую позицию');$('#place-yaw').value=placeDraft?Math.round(placeDraft.yaw*180/Math.PI):0;}
  $('#place-yaw').oninput=()=>{if(placeDraft){placeDraft.yaw=Number($('#place-yaw').value)*Math.PI/180;drawMap();}};
  function newPlace(){placeId=null;placeDraft=null;$('#place-name').value='';showPlacePose();drawMap();}
  function newRoute(){routeId=null;routePoints=[];$('#route-name').value='';renderRoutePoints();drawMap();}
  $('#new-place').onclick=newPlace;$('#new-route').onclick=newRoute;
  async function annotationsReload(){
    const id=selected();if(!id||!mapInfo()){documentData=null;documentMap=null;renderDocument();return;}
    const response=await get('/api/maps/'+encodeURIComponent(id)+'/annotations');
    if(id!==selected())return;
    const changed=documentMap!==id;documentData=response;documentMap=id;reviewed=false;
    if(changed){newPlace();newRoute();camera.zoom=0;mapImage.src=mapInfo().preview_url;}
    renderDocument();drawMap();
  }
  $('#reload-annotations').onclick=safe(annotationsReload);
  window.addEventListener('ijk-map-changed',()=>{if(documentMap!==selected())annotationsReload().catch(e=>notice(e.message));});
  async function persist(places,routes){
    if(!documentData||documentMap!==selected())throw new Error('Выберите карту и обновите места');
    if(metadataBusy)throw new Error('Сохранение мест уже выполняется');
    metadataBusy=true;
    try{
      const response=await fetch('/api/maps/'+encodeURIComponent(selected())+'/annotations',{method:'PUT',headers:{'Content-Type':'application/json',...(controlId?{'X-Control-Id':controlId}:{})},body:JSON.stringify({revision:documentData.revision,fingerprint:documentData.current_fingerprint,places,routes,revalidate:reviewed})});
      if(!response.ok)throw new Error(await response.text());documentData=await response.json();reviewed=false;renderDocument();drawMap();
    }finally{metadataBusy=false;}
  }
  $('#review-annotations').onclick=safe(async()=>{reviewed=true;await persist(documentData.places,documentData.routes);});
  const capture=()=>api('/api/navigation/capture',{map_id:selected()});
  $('#capture-place').onclick=safe(async()=>{placeDraft=await capture();showPlacePose();drawMap();});
  $('#save-place').onclick=safe(async()=>{
    if(!placeDraft)throw new Error('Укажите положение места');if(!$('#place-name').value.trim())throw new Error('Введите название места');
    const place={...placeDraft,id:placeId||uid('place'),name:$('#place-name').value.trim()};
    await persist([...documentData.places.filter(v=>v.id!==placeId),place],documentData.routes);placeId=place.id;
  });
  function renderDocument(){
    const places=$('#places-list'),routes=$('#routes-list');places.replaceChildren();routes.replaceChildren();
    setText('#annotation-status',documentData?`${selected()} · версия ${documentData.revision} · ${documentData.valid?'Места соответствуют карте':'КАРТА ИЗМЕНИЛАСЬ: проверьте точки перед использованием'}`:'Выберите карту в разделе «Карты»');
    $('#review-annotations').hidden=!documentData||documentData.valid;
    $('#route-place').replaceChildren(new Option('Выберите место',''));
    if(!documentData)return;
    function item(container,name,description,buttons){const row=document.createElement('div'),text=document.createElement('span'),title=document.createElement('b'),info=document.createElement('small'),actions=document.createElement('div');title.textContent=name;info.textContent=description;text.append(title,info);actions.className='item-actions';for(const [label,fn]of buttons){const button=document.createElement('button');button.className='secondary';button.textContent=label;button.onclick=safe(fn);actions.append(button);}row.append(text,actions);container.append(row);}
    for(const place of documentData.places){
      $('#route-place').add(new Option(place.name,place.id));
      item(places,place.name,`X ${fmt(place.x,2)} · Y ${fmt(place.y,2)} · ${fmt(place.yaw*180/Math.PI)}°`,[
        ['Ехать сюда',()=>prepare('place',place.id)],['Изменить',async()=>{placeId=place.id;placeDraft={x:place.x,y:place.y,yaw:place.yaw};$('#place-name').value=place.name;showPlacePose();drawMap();}],
        ['Удалить',()=>persist(documentData.places.filter(v=>v.id!==place.id),documentData.routes)]]);
    }
    for(const route of documentData.routes)item(routes,route.name,`${route.points.length} остановок`,[
      ['Подготовить',()=>prepare('route',route.id)],['Изменить',async()=>{routeId=route.id;routePoints=structuredClone(route.points);$('#route-name').value=route.name;renderRoutePoints();drawMap();}],
      ['Удалить',()=>persist(documentData.places,documentData.routes.filter(v=>v.id!==route.id))]]);
  }
  function renderRoutePoints(){
    const list=$('#route-points');list.replaceChildren();
    routePoints.forEach((point,index)=>{
      const row=document.createElement('div'),label=document.createElement('span');label.textContent=`${index+1}. ${point.label||'Остановка'} · ${fmt(point.x,2)}, ${fmt(point.y,2)}`;
      const controls=document.createElement('div');controls.className='item-actions';const wait=document.createElement('input');wait.type='number';wait.min='0';wait.max='60';wait.step='1';wait.value=point.wait_s||0;wait.setAttribute('aria-label',`Ожидание в точке ${index+1}, секунд`);wait.onchange=()=>{point.wait_s=Math.max(0,Math.min(60,Number(wait.value)||0));wait.value=point.wait_s;};controls.append(wait);
      const caption=document.createElement('input');caption.type='text';caption.maxLength=80;caption.value=point.label||'';caption.setAttribute('aria-label',`Название остановки ${index+1}`);caption.oninput=()=>{point.label=caption.value;drawMap();};controls.prepend(caption);
      for(const [text,delta]of [['↑',-1],['↓',1],['×',0]]){const button=document.createElement('button');button.className='secondary';button.textContent=text;button.setAttribute('aria-label',`${text==='×'?'Удалить':text==='↑'?'Поднять':'Опустить'} точку ${index+1}`);button.onclick=()=>{if(delta){const next=index+delta;if(next>=0&&next<routePoints.length)[routePoints[index],routePoints[next]]=[routePoints[next],routePoints[index]];}else routePoints.splice(index,1);renderRoutePoints();drawMap();};controls.append(button);}row.append(label,controls);list.append(row);
    });
  }
  $('#capture-waypoint').onclick=safe(async()=>{const pose=await capture();routePoints.push({...pose,label:`Остановка ${routePoints.length+1}`,wait_s:0});renderRoutePoints();drawMap();});
  $('#add-route-place').onclick=safe(async()=>{const place=documentData?.places.find(p=>p.id===$('#route-place').value);if(!place)throw new Error('Выберите место');routePoints.push({x:place.x,y:place.y,yaw:place.yaw,label:place.name,wait_s:0});renderRoutePoints();drawMap();});
  $('#save-route').onclick=safe(async()=>{if(!$('#route-name').value.trim()||!routePoints.length)throw new Error('Нужны название и хотя бы одна остановка');const route={id:routeId||uid('route'),name:$('#route-name').value.trim(),points:routePoints};await persist(documentData.places,[...documentData.routes.filter(r=>r.id!==routeId),route]);routeId=route.id;});
  $('#confirm-localization').onclick=safe(async()=>{await api('/api/navigation/confirm',{map_id:selected(),confirmed:$('#localization-check').checked});notice('Положение робота подтверждено для текущего запуска Navigate');});
  async function prepare(kind,id){prepared=await api('/api/navigation/prepare',{map_id:selected(),kind,id});showPlan();}
  function showPlan(){
    const container=$('#command-plan');container.replaceChildren();if(!prepared)return;
    const text=document.createElement('p');text.textContent=prepared.plan.reasoning;container.append(text);
    const list=document.createElement('ol');
    for(const step of prepared.plan.steps){
      const line=document.createElement('li');
      const item=documentData?.[step.kind+'s']?.find(v=>v.id===step.id);
      line.textContent=step.kind==='return'?'Вернуться к месту начала команды':item?.name||step.id;
      if(step.kind==='route'&&item){
        const children=document.createElement('ol');
        item.points.forEach((point,index)=>{const child=document.createElement('li');child.textContent=`${point.label||'Остановка '+(index+1)} · ${fmt(point.x,2)}, ${fmt(point.y,2)}${point.wait_s?' · ждать '+point.wait_s+' с':''}`;children.append(child);});
        line.append(children);
      }
      list.append(line);
    }
    container.append(list);$('#execute-plan').hidden=!prepared.id;
  }
  $('#interpret-command').onclick=safe(async()=>{if(interpretationBusy)return;interpretationBusy=true;$('#interpret-command').disabled=true;try{prepared=await api('/api/commands/interpret',{map_id:selected(),text:$('#command-text').value});showPlan();}finally{interpretationBusy=false;$('#interpret-command').disabled=false;}});
  $('#execute-plan').onclick=safe(async()=>{if(!prepared?.id)throw new Error('Сначала подготовьте план');await api('/api/navigation/execute',{plan_id:prepared.id,confirmed:true});prepared=null;$('#execute-plan').hidden=true;setText('#command-plan','Задача запущена');});
  for(const action of ['pause','resume','cancel'])$('#nav-'+action).onclick=safe(()=>api('/api/navigation/'+action));
  function renderNavigation(){
    for(const id of ['save-place','capture-place','save-route','capture-waypoint','interpret-command','execute-plan','review-annotations'])$('#'+id).disabled=!controlId||(id==='interpret-command'&&interpretationBusy);
const nav=telemetry.navigation,labels={idle:'Ожидание команды',running:'Движение',waiting:'Ожидание в точке',pausing:'Отмена цели перед паузой',paused:'На паузе',cancelling:'Отменяется',cancelled:'Отменено',complete:'Завершено',failed:'Ошибка'};setText('#navigation-state',`${labels[nav.state]||nav.state}${nav.total?` · ${Math.min(nav.index+1,nav.total)}/${nav.total} · ${nav.point||nav.label}`:''}${nav.distance_remaining_m!=null?` · осталось ${fmt(nav.distance_remaining_m,2)} м`:''}${nav.error?' · '+nav.error:''}`);$('#nav-pause').disabled=!controlId||!['running','waiting'].includes(nav.state);$('#nav-resume').disabled=!controlId||nav.state!=='paused'||nav.pending||nav.cancel_uncertain;$('#nav-cancel').disabled=!controlId||['idle','complete','cancelled'].includes(nav.state);$('#confirm-localization').disabled=!controlId;}
  connect();if(selected())annotationsReload().catch(e=>notice(e.message));
})();
