"""Web telemetry, control ownership, annotations, safe navigation and network jobs."""
import asyncio
import contextlib
import copy
import json
import math
import shlex
import sys
import time
import uuid

from aiohttp import web, WSMsgType
from pydantic import ValidationError
from tools.ijk.web.annotations import Annotations, Conflict
from tools.ijk.web.navigation import Navigation
from tools.ijk.web import commands


class ControlServices:
    def init_services(self):
        self.annotations=Annotations(self.maps)
        self.navigation=Navigation(self.bridge,self.log)
        self.control_id=None
        self.claim_lock=asyncio.Lock()
        self.lease_token=None
        self.control_seen=0.
        self.control_broken=False
        self.was_armed=False
        self.lease_seq=0
        self.probe_seq=0
        self.confirmed=None
        self.telemetry_clients=set()
        self.plans={}
        self.link_task=None
        self.stationary_since=None
        self.safety_task=None
        self.extra_routes=[
            web.get('/api/telemetry',self.get_telemetry),web.get('/ws/telemetry',self.ws_telemetry),
            web.get('/api/maps/{map_id}/annotations',self.get_annotations),
            web.put('/api/maps/{map_id}/annotations',self.update_annotations),
            web.post('/api/navigation/capture',self.capture_pose),
            web.post('/api/navigation/confirm',self.confirm_localization),
            web.post('/api/navigation/prepare',self.prepare_navigation),
            web.post('/api/navigation/execute',self.execute_navigation),
            web.post('/api/navigation/{operation:pause|resume|cancel}',self.navigation_operation),
            web.post('/api/commands/interpret',self.interpret_command),
            web.post('/api/link/test',self.link_test),
        ]

    def require_owner(self,request):
        if not self.control_id or request.headers.get('X-Control-Id')!=self.control_id:
            raise web.HTTPForbidden(text='Сначала возьмите управление в этой вкладке')
        if self.estopped: raise web.HTTPConflict(text='Аварийная остановка активна')
        if self.teleop_client is None or time.monotonic()-self.control_seen>.35:
            raise web.HTTPConflict(text='Нет свежей управляющей сессии')

    def lease_ready(self):
        sample=self.bridge.telemetry.snapshot()['topics']['guard']
        data=sample['data'] or {}
        return (not self.control_broken and sample['age_s'] is not None and sample['age_s']<.3
                and data.get('state')=='armed' and data.get('token')==self.lease_token)

    def driver_reason(self,topics):
        sample=topics['diagnostics']
        drive=(sample['data'] or {}).get('sts3215_drive')
        if not drive or time.monotonic()-drive['received']>3: return 'Нет свежей диагностики приводов'
        if drive['level']>=2: return 'Ошибка привода: '+drive['message']
        if topics['odom']['stale']: return 'Нет свежей одометрии'
        return None

    def navigation_context(self,map_id,confirmed=True,full=False):
        if self.active_profile!='navigate' or not self.active_options.get('use_amcl'):
            raise ValueError('Нужен профиль Navigate с включённым AMCL')
        if self.active_options.get('map')!=map_id: raise ValueError('Выбрана другая карта, чем в активном Navigate')
        snapshot=self.bridge.telemetry.snapshot()['topics']
        if snapshot['pose']['stale']: raise ValueError('Нет свежего TF map → base_footprint')
        nav=snapshot['nav']['data'] or {}
        if snapshot['nav']['stale'] or not nav.get('amcl_active') or not snapshot['amcl']['data']:
            raise ValueError('AMCL ещё не локализовал робота')
        document=self.annotations.load(map_id) if full else self.annotations.identity(map_id)
        if not document['valid']: raise ValueError('Карта изменилась; проверьте места и маршруты')
        if confirmed and self.confirmed!=(id(self.proc),map_id,document['fingerprint']):
            raise ValueError('Подтвердите соответствие маркера реальному положению робота')
        return document,snapshot

    def autonomous_reason(self):
        if self.estopped:return 'Аварийная остановка'
        if self.link_task and not self.link_task.done():return 'Дождитесь завершения теста связи'
        if self.control_broken:return 'Потеря управляющей связи; требуется явное продолжение'
        if not self.lease_ready():return 'Нет подтверждённой управляющей сессии на Pi'
        try:
            _,topics=self.navigation_context(self.active_options.get('map'))
            reason=self.driver_reason(topics)
            if reason:return reason
            if topics['scan']['stale']:return 'Нет свежего скана лидара'
            nav=topics['nav']['data'] or {}
            if not nav.get('ready') or not nav.get('navigator_active'):return 'Nav2 ещё не готов принимать цели'
            if nav.get('external_goal'):return 'Nav2 выполняет внешнюю задачу; завершите её в RViz'
        except (ValueError,OSError,KeyError) as exc:return str(exc)
        return None

    def telemetry_snapshot(self):
        result=self.bridge.telemetry.snapshot()
        topics=result['topics']
        # Convert monotonic timestamps to ages for clients on other computers.
        for item in (topics['diagnostics']['data'] or {}).values():
            item['age_s']=max(0,time.monotonic()-item.pop('received'))
            item['stale']=item['age_s']>3
        reason=self.autonomous_reason() if self.active_profile=='navigate' else self.driver_reason(self.bridge.telemetry.snapshot()['topics'])
        if self.estopped:reason='Аварийная остановка'
        elif self.control_broken:reason='Потеря управляющей связи; движение заблокировано'
        elif not self.active_profile:reason='Ожидание команды'
        if self.navigation.state=='failed' and not self.estopped and not self.control_broken:
            reason=self.navigation.error or 'Ошибка навигационной задачи'
        result.update({'mock':self.mock,'estopped':self.estopped,'ros_error':self.bridge.error,'navigation':self.navigation.snapshot(),
            'summary':reason or ('Ожидание команды' if self.navigation.state not in ('running','waiting') else 'Выполняется маршрут'),
            'autonomy_ready':self.active_profile=='navigate' and self.autonomous_reason() is None,
            'control':{'owned':self.control_id is not None,'ready':self.lease_ready(),
                'broken':self.control_broken,'browser_age_s':None if not self.control_id else time.monotonic()-self.control_seen},
            'localization_confirmed':bool(self.confirmed and self.confirmed[0]==id(self.proc))})
        return result

    async def control_tick(self):
        while True:
            self.probe_seq+=1;self.bridge.probe(self.probe_seq)
            if self.control_id:
                self.lease_seq+=1
                if time.monotonic()-self.control_seen<=.3 and not self.control_broken and not self.estopped:
                    self.bridge.lease('heartbeat' if self.was_armed else 'arm',self.lease_token,self.lease_seq)
                    if self.lease_ready():self.was_armed=True
                    elif self.was_armed:await self.lose_control('Нет подтверждения lease от Pi')
                elif not self.control_broken:
                    await self.lose_control('Потеря heartbeat управляющего браузера')
            topics=self.bridge.telemetry.snapshot()['topics']
            if self.confirmed and (topics['pose']['stale'] or topics['nav']['stale'] or not (topics['nav']['data'] or {}).get('amcl_active')):
                self.confirmed=None
            if self.link_task and not self.link_task.done():
                self.bridge.publish(emergency=True)
                if (topics['nav']['data'] or {}).get('external_goal') and not self.control_broken:
                    await self.lose_control('Во время теста связи появилась внешняя цель Nav2')
            odom=topics['odom']
            if not odom['stale'] and abs(odom['data']['v'])<.01 and abs(odom['data']['w'])<.01:
                if self.stationary_since is None:self.stationary_since=time.monotonic()
            else:self.stationary_since=None
            if self.navigation.state in ('running','waiting'):
                reason=self.autonomous_reason()
                if reason:
                    self.bridge.publish(emergency=True)
                    self.schedule_pause(reason)
            if self.navigation.state in ('pausing','cancelling') or self.navigation.cancel_uncertain:
                self.bridge.publish(emergency=True)
            await asyncio.sleep(.1)

    def schedule_pause(self,reason):
        if self.safety_task is None or self.safety_task.done():
            self.safety_task=asyncio.create_task(self.navigation.interrupt('paused',reason))

    async def lose_control(self,reason):
        self.control_broken=True
        self.bridge.publish()
        self.bridge.lease('stop',self.lease_token or '',self.lease_seq)
        self.moving=False
        self.schedule_pause(reason)
        await self.log('Управление заблокировано: '+reason)

    async def claim_control(self,ws):
        async with self.claim_lock:
            await self._claim_control(ws)

    async def _claim_control(self,ws):
        if self.estopped:raise ValueError('Снимите аварийную остановку')
        if self.teleop_client is not None and self.teleop_client is not ws:
            raise ValueError('Управление занято другой вкладкой')
        if self.navigation.busy() or self.navigation.cancel_uncertain:
            raise ValueError('Дождитесь отмены старой цели или остановите профиль')
        await self.prepare_rearm()
        self.teleop_client=ws
        self.control_id=uuid.uuid4().hex
        self.control_seen=time.monotonic()
        self.rearm()
        await ws.send_json({'type':'claimed','control_id':self.control_id})

    async def prepare_rearm(self):
        snapshot=self.bridge.telemetry.snapshot()['topics']
        guard=(snapshot['guard']['data'] or {})
        nav=(snapshot['nav']['data'] or {})
        if nav.get('external_goal') or ((self.control_broken or guard.get('state')=='latched') and self.active_profile not in ('teleop','mapping','showcase')):
            try:await self.bridge.cancel_all_goals()
            except Exception as exc:raise ValueError(str(exc))

    def rearm(self):
        self.control_broken,self.was_armed=False,False
        self.lease_token=uuid.uuid4().hex
        self.lease_seq+=1
        self.bridge.lease('arm',self.lease_token,self.lease_seq)

    async def release_control(self,ws):
        if self.teleop_client is not ws:return
        await self.lose_control('Управляющая вкладка отключена')
        self.teleop_client=None
        self.control_id=None

    async def get_telemetry(self,request):
        return web.json_response(self.telemetry_snapshot())

    async def ws_telemetry(self,request):
        ws=web.WebSocketResponse(heartbeat=10,max_msg_size=2048)
        await ws.prepare(request)
        self.telemetry_clients.add(ws)
        async def send():
            while not ws.closed:
                await ws.send_json({'type':'telemetry',**self.telemetry_snapshot()})
                await asyncio.sleep(.2)
        sender=asyncio.create_task(send())
        try:
            async for msg in ws:
                if msg.type==WSMsgType.TEXT:
                    try:
                        data=json.loads(msg.data)
                        if data.get('type')=='ping':await ws.send_json({'type':'pong','seq':data.get('seq')})
                    except (ValueError,AttributeError):pass
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError,ConnectionError):await sender
            self.telemetry_clients.discard(ws)
        return ws

    async def get_annotations(self,request):
        try:return web.json_response(await asyncio.to_thread(self.annotations.load,request.match_info['map_id']))
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))

    async def update_annotations(self,request):
        self.require_owner(request)
        data=await self.json_body(request)
        revalidate=data.pop('revalidate',False)
        if type(revalidate) is not bool:raise web.HTTPBadRequest(text='revalidate: требуется true или false')
        map_id=request.match_info['map_id']
        try:
            old=self.annotations.load(map_id)
            previous={r['id']:r['points'] for r in old['routes']}
            if not revalidate and any(r.get('points')!=previous.get(r.get('id')) for r in data.get('routes',[])):
                self.navigation_context(map_id,confirmed=False)
            return web.json_response(await asyncio.to_thread(self.annotations.update,map_id,data,revalidate))
        except Conflict as exc:raise web.HTTPConflict(text=str(exc))
        except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:raise web.HTTPBadRequest(text=str(exc))

    async def capture_pose(self,request):
        self.require_owner(request)
        data=await self.json_body(request)
        try:
            _,topics=self.navigation_context(data.get('map_id'),confirmed=False)
            return web.json_response(topics['pose']['data'])
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPConflict(text=str(exc))

    async def confirm_localization(self,request):
        self.require_owner(request)
        data=await self.json_body(request)
        if data.get('confirmed') is not True:raise web.HTTPBadRequest(text='Нужно явное подтверждение положения')
        try:
            document,_=self.navigation_context(data.get('map_id'),confirmed=False)
            self.confirmed=(id(self.proc),data['map_id'],document['fingerprint'])
            return web.json_response({'ok':True})
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPConflict(text=str(exc))

    def new_plan(self,document,plan,label,source='manual'):
        identifier=uuid.uuid4().hex
        self.plans[identifier]={'id':identifier,'map_id':document['map_id'],'fingerprint':document['fingerprint'],
            'revision':document['revision'],'source':source,'created':time.monotonic(),'plan':plan,'label':label}
        while len(self.plans)>50:del self.plans[next(iter(self.plans))]
        return {'id':identifier,'map_id':document['map_id'],'plan':plan,'label':label}

    async def prepare_navigation(self,request):
        self.require_owner(request)
        data=await self.json_body(request)
        try:
            document=self.annotations.load(data.get('map_id'))
            if not document['valid']:raise ValueError('Карта изменилась; проверьте места')
            kind=data.get('kind')
            if kind not in ('place','route'):raise ValueError('Выберите место или маршрут')
            item=next((v for v in document[kind+'s'] if v['id']==data.get('id')),None)
            if item is None:raise ValueError('Объект не найден')
            plan={'target_landmark_id':item['id'],'search_strategy':'named_route',
                'reasoning':'Посетить '+item['name'],'steps':[{'kind':kind,'id':item['id']}]}
            return web.json_response(self.new_plan(document,plan,item['name']))
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))

    async def interpret_command(self,request):
        self.require_owner(request)
        data=await self.json_body(request)
        if not isinstance(data.get('text'),str) or not 1<=len(data['text'].strip())<=1000:
            raise web.HTTPBadRequest(text='Введите команду длиной до 1000 символов')
        try:
            document=self.annotations.load(data.get('map_id'))
            if not document['valid']:raise ValueError('Проверьте места на изменённой карте')
            plan=await commands.interpret(data['text'],document)
            if plan.search_strategy=='clarify':return web.json_response({'id':None,'plan':plan.model_dump()})
            return web.json_response(self.new_plan(document,plan.model_dump(),data['text'],source='llm'))
        except TimeoutError:raise web.HTTPGatewayTimeout(text='Ollama не ответила за 20 секунд; движение не запущено')
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))
        except Exception as exc:raise web.HTTPServiceUnavailable(text='Ollama недоступна или вернула неверный ответ: '+str(exc))

    async def execute_navigation(self,request):
        self.require_owner(request)
        data=await self.json_body(request)
        if data.get('confirmed') is not True:raise web.HTTPBadRequest(text='Сначала подтвердите план')
        item=self.plans.get(data.get('plan_id'))
        if not item or time.monotonic()-item['created']>300:raise web.HTTPConflict(text='План устарел; подготовьте его заново')
        reason=self.autonomous_reason()
        if reason:raise web.HTTPConflict(text=reason)
        try:
            document,topics=self.navigation_context(item['map_id'],full=True)
            if document['revision']!=item['revision'] or document['fingerprint']!=item['fingerprint']:
                raise ValueError('Места или карта изменились; подготовьте план заново')
            plan=commands.validate_plan(item['plan'],document,check_ambiguity=item['source']=='llm')
            points=[]
            for step in plan.steps:
                if step.kind=='return':points.append({**topics['pose']['data'],'label':'Возврат к началу команды','wait_s':0})
                elif step.kind=='place':
                    place=next(v for v in document['places'] if v['id']==step.id)
                    points.append({k:place[k] for k in ('x','y','yaw')}|{'label':place['name'],'wait_s':0})
                else:points.extend(next(v for v in document['routes'] if v['id']==step.id)['points'])
            if len(points)>200:raise ValueError('В задаче слишком много точек (максимум 200)')
            await self.navigation.start(item['map_id'],document['fingerprint'],points,item['label'])
            self.plans.pop(item['id'],None)
            return web.json_response(self.navigation.snapshot())
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPConflict(text=str(exc))

    async def navigation_operation(self,request):
        self.require_owner(request)
        operation=request.match_info['operation']
        if operation=='resume':
            if self.navigation.busy() or self.navigation.cancel_uncertain:raise web.HTTPConflict(text='Дождитесь отмены старой цели')
            if self.control_broken or not self.lease_ready():
                try:await self.prepare_rearm()
                except ValueError as exc:raise web.HTTPConflict(text=str(exc))
                self.rearm()
                # Only an explicit resume may create a fresh lease after link loss.
                for _ in range(6):
                    if self.lease_ready():break
                    await asyncio.sleep(.05)
            reason=self.autonomous_reason()
            if reason:raise web.HTTPConflict(text=reason)
            try:
                document,_=self.navigation_context(self.navigation.map_id)
                if document['fingerprint']!=self.navigation.fingerprint:raise ValueError('Карта изменилась; задача отменена')
                await self.navigation.resume()
            except (ValueError,OSError) as exc:raise web.HTTPConflict(text=str(exc))
        else:
            self.bridge.publish(emergency=True)
            if operation=='cancel' and self.navigation.cancel_uncertain:
                try:await self.navigation.retry_cancel()
                except ValueError as exc:raise web.HTTPConflict(text=str(exc))
            await self.navigation.interrupt('paused' if operation=='pause' else 'cancelled','Команда оператора')
        return web.json_response(self.navigation.snapshot())

    def prune_jobs(self):
        while len(self.jobs)>50:
            oldest=next((key for key,value in self.jobs.items() if value['state']!='running'),None)
            if oldest is None:break
            del self.jobs[oldest]

    async def link_test(self,request):
        self.require_owner(request)
        if not self.robot_ip or self.mock or self.local:raise web.HTTPConflict(text='Тест SSH доступен только для подключённой Pi')
        if self.navigation.busy() or (self.bridge.telemetry.snapshot()['topics']['nav']['data'] or {}).get('external_goal'):
            raise web.HTTPConflict(text='Сначала приостановите автономную задачу')
        if self.stationary_since is None or time.monotonic()-self.stationary_since<1:
            raise web.HTTPConflict(text='Нужна свежая одометрия: робот должен стоять не менее секунды')
        if self.link_task and not self.link_task.done():raise web.HTTPConflict(text='Тест уже выполняется')
        job={'id':uuid.uuid4().hex,'type':'link_test','state':'running','error':None,'result':None}
        self.jobs[job['id']]=job
        self.prune_jobs()
        self.link_task=asyncio.create_task(self.link_job(job))
        return web.json_response(job,status=202)

    async def link_job(self,job):
        proc=None
        try:
            # One authenticated connection; startup is excluded. No files or shell input from the client.
            script='import sys,time; n=1048576; r=sys.stdin.buffer; w=sys.stdout.buffer; w.write(b"READY\\n"); w.flush(); data=r.read(n); w.write(b"ACK\\n"); w.flush(); r.read(1); w.write(bytes(n)); w.flush()'
            proc=await asyncio.create_subprocess_exec('ssh','-o','BatchMode=yes','-o','ConnectTimeout=3',
                f'{self.config.network.default_user}@{self.robot_ip}','python3 -u -c '+shlex.quote(script),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            if await asyncio.wait_for(proc.stdout.readline(),5)!=b'READY\n':raise RuntimeError('Нет ответа измерителя на Pi')
            start=time.monotonic();proc.stdin.write(bytes(1048576));await asyncio.wait_for(proc.stdin.drain(),2)
            if await asyncio.wait_for(proc.stdout.readline(),max(.01,2-(time.monotonic()-start)))!=b'ACK\n':raise RuntimeError('Ошибка передачи на Pi')
            upload=time.monotonic()-start
            start=time.monotonic();proc.stdin.write(b'G');await proc.stdin.drain()
            data=await asyncio.wait_for(proc.stdout.readexactly(1048576),2)
            download=time.monotonic()-start
            job['result']={'upload_mbps':1048576*8/upload/1e6,'download_mbps':len(data)*8/download/1e6,
                'bytes_each_direction':1048576,'transport':'SSH/TCP, полезные данные, без установки соединения'}
            job['state']='succeeded'
        except asyncio.CancelledError:job['state'],job['error']='cancelled','Тест отменён'
        except Exception as exc:job['state'],job['error']='failed','Тест связи не завершён: '+str(exc)
        finally:
            if proc and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):proc.kill()
                await proc.wait()
            await self.log('Тест связи: '+job['state'])
