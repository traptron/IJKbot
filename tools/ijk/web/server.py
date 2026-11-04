"""Local web control center for the existing ijk CLI."""
import asyncio
from collections import deque
import contextlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import webbrowser
import tempfile
import uuid
import yaml
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType

from tools.ijk.discovery import discover_robot, is_ssh_responsive
from tools.ijk.env import configure_cyclonedds, build_shell_command, build_base_environment
from tools.ijk.web.maps import MapCatalog
from tools.ijk.runner import Runner
from tools.ijk.web.ros_bridge import Bridge
from tools.ijk.web.services import ControlServices
from tools.ijk.web.navigation import Navigation

ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).parent / 'static'
PROFILES = {'competition', 'showcase', 'teleop', 'mapping', 'navigate'}
BENCH = {'lidar', 'camera', 'qr', 'driver'}


class ControlCenterServer(ControlServices):
    def __init__(self, config, robot_ip=None, mock=False, local=False):
        self.config, self.robot_ip, self.mock, self.local = config, robot_ip, mock, local
        self.bridge = Bridge(config, mock, robot_ip)
        self.proc = None
        self.active_profile = None
        self.active_options = {}
        self.process_state = 'idle'
        self.last_error = None
        self.maps = MapCatalog(ROOT / 'src/nav2/maps')
        self.jobs = {}
        self.save_task = None
        self.save_proc = None
        self.save_timeout = 30
        self.log_history = deque(maxlen=300)
        self.log_clients = set()
        self.teleop_client = None
        self.last_command = 0.0
        self.moving = False
        self.estopped = False
        self.lock = asyncio.Lock()
        self.emergency_lock = asyncio.Lock()
        self.init_services()
        self.control_clients = set()
        self.app = web.Application(middlewares=[self.origin_guard])
        self.app.add_routes([
            web.get('/', self.index), web.static('/static/', STATIC),
            web.get('/api/status', self.status), web.post('/api/profile/start', self.start),
            web.post('/api/profile/stop', self.stop), web.post('/api/estop', self.estop),
            web.post('/api/reset', self.reset), web.post('/api/discovery', self.discovery),
            web.post('/api/ops/{action}', self.ops), web.get('/ws/teleop', self.teleop),
            web.get('/ws/logs', self.logs),
            web.get('/api/maps', self.list_maps),
            web.get('/api/maps/{map_id}/preview', self.map_preview),
            web.post('/api/maps/save', self.save_map),
            web.get('/api/jobs/{job_id}', self.get_job),
        ])
        self.app.add_routes(self.extra_routes)
        self.app.on_startup.append(self.on_startup)
        self.app.on_shutdown.append(self.on_shutdown)
        self.app.on_cleanup.append(self.on_cleanup)

    @web.middleware
    async def origin_guard(self, request, handler):
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            raise web.HTTPForbidden(text='Origin запрещен')
        response = await handler(request)
        if request.path == '/' or request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-cache'
        return response

    async def on_startup(self, app):
        self.watchdog_task = asyncio.create_task(self.watchdog())
        self.control_task = asyncio.create_task(self.control_tick())

    async def on_shutdown(self, app):
        for ws in list(self.log_clients | self.telemetry_clients | self.control_clients):
            await ws.close(code=1001, message=b"Server shutdown")

    async def on_cleanup(self, app):
        self.estopped = True
        self.bridge.publish(emergency=True)
        self.bridge.publish()
        self.bridge.lease('stop', self.lease_token or '', self.lease_seq)
        await self.navigation.close()
        for task in (self.control_task, self.safety_task, self.link_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError): await task
        await self.cancel_save()
        await self.stop_process()
        self.watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.watchdog_task
        self.bridge.close()

    async def watchdog(self):
        while True:
            if self.estopped:
                self.bridge.publish(emergency=True)
            if self.moving and time.monotonic() - self.last_command > .35:
                self.bridge.publish()
                self.moving = False
                await self.log('Управление остановлено: таймаут связи.')
            await asyncio.sleep(.05)

    async def log(self, line):
        self.log_history.append(line)
        for ws in list(self.log_clients):
            with contextlib.suppress(ConnectionError, RuntimeError):
                await ws.send_str(line)

    async def index(self, request):
        return web.FileResponse(STATIC / 'index.html')

    async def status(self, request):
        runner = Runner(self.config, self.robot_ip, self.mock, self.local)
        online, tmux = False, False
        if self.robot_ip and not self.mock and not self.local:
            online = await asyncio.to_thread(is_ssh_responsive, self.robot_ip, self.config.network.default_user, 2)
            if online:
                tmux = await asyncio.to_thread(runner.is_remote_tmux_running)
        return web.json_response({'robot_ip': self.robot_ip, 'ssh_online': online,
            'tmux_running': tmux, 'active_profile': self.active_profile,
            'domain_id': self.config.network.domain_id, 'mock': self.mock,
            'ros_available': bool(self.bridge.node), 'ros_error': self.bridge.error,
            'estopped': self.estopped, 'process_state': self.process_state,
            'active_options': self.active_options, 'last_error': self.last_error,
            'map_job': next((job for job in reversed(list(self.jobs.values())) if job.get('type','map_save')=='map_save'), None)})

    def command(self, parts):
        cmd = [sys.executable, '-u', str(ROOT / 'tools/ijk/cli.py')]
        if self.mock: cmd.append('--mock')
        if self.local: cmd.append('--local')
        if self.robot_ip and not self.mock and not self.local: cmd += ['--host', self.robot_ip]
        else: cmd.append('--no-discovery')
        return cmd + parts

    async def run_process(self, name, parts):
        async with self.lock:
            if self.navigation.busy() or self.navigation.cancel_uncertain:
                raise web.HTTPConflict(text='Сначала подтвердите отмену старой цели навигации')
            if self.save_task and not self.save_task.done():
                raise web.HTTPConflict(text='Дождитесь сохранения карты')
            if self.proc and self.proc.returncode is None:
                raise web.HTTPConflict(text='Уже выполняется: ' + str(self.active_profile))
            if self.estopped:
                raise web.HTTPConflict(text='Сначала снимите аварийную остановку')
            if not (self.mock or self.local or self.robot_ip):
                raise web.HTTPConflict(text='Робот не найден. Выполните поиск.')
            self.process_state = 'starting'
            self.last_error = None
            self.proc = await asyncio.create_subprocess_exec(*self.command(parts), cwd=ROOT,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            proc = self.proc
            self.active_profile = name
            self.process_state = 'running'
            asyncio.create_task(self.read_output(proc, name))
            await self.log('Запуск: ' + name)

    async def read_output(self, proc, name):
        while line := await proc.stdout.readline():
            await self.log(line.decode('utf-8', errors='replace').rstrip())
        code = await proc.wait()
        if self.proc is proc:
            self.active_profile = None
            self.proc = None
            self.active_options = {}
            stopped = self.process_state == 'stopping'
            self.process_state = 'idle' if code == 0 or stopped else 'error'
            self.last_error = None if code == 0 or stopped else f'{name}: код завершения {code}'
        await self.log(f'{name}: процесс завершился (код {code}).')

    async def stop_process(self):
        async with self.lock:
            proc = self.proc
            if proc:
                self.process_state = 'stopping'
            if proc and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(proc.pid, signal.SIGINT)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
            self.proc = None
            self.active_profile = None
            self.active_options = {}
            self.process_state = 'idle'
            self.last_error = None

    async def start(self, request):
        data = await self.json_body(request)
        profile = data.get('profile')
        options = data.get('options', {})
        if not isinstance(profile, str) or not isinstance(options, dict):
            raise web.HTTPBadRequest(text='Некорректные параметры профиля')
        if self.save_task and not self.save_task.done():
            raise web.HTTPConflict(text='Дождитесь сохранения карты')
        if profile in PROFILES:
            allowed = {'record', 'bag_name'}
            if profile != 'teleop': allowed.add('rviz')
            if profile == 'navigate': allowed.update({'map', 'use_amcl'})
            if set(options) - allowed:
                raise web.HTTPBadRequest(text='Параметр не поддерживается профилем')
            for key in ('record', 'rviz', 'use_amcl'):
                if key in options and type(options[key]) is not bool:
                    raise web.HTTPBadRequest(text=f'{key}: требуется true или false')
            resolved = {'record': options.get('record', False)}
            parts = []
            if resolved['record']: parts.append('--record')
            bag = options.get('bag_name', '')
            if not isinstance(bag, str): raise web.HTTPBadRequest(text='Имя записи должно быть строкой')
            if bag:
                try: MapCatalog.validate_name(bag)
                except ValueError as exc: raise web.HTTPBadRequest(text=str(exc))
                if not resolved['record']: raise web.HTTPBadRequest(text='Имя записи задано без записи rosbag')
                parts += ['--bag-name', bag]
            resolved['bag_name'] = bag
            parts.append(profile)
            if profile == 'teleop': parts += ['--web', '--speed', '0.25']
            else:
                resolved['rviz'] = options.get('rviz', True)
                if not resolved['rviz']: parts.append('--no-rviz')
            if profile == 'navigate':
                configured = self.config.profiles.get('navigate')
                map_id = options.get('map', configured.map if configured else 'polygon_empty_4x4.yaml')
                try: self.maps.inspect(map_id)
                except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as exc:
                    raise web.HTTPBadRequest(text=f'Карта недоступна: {exc}')
                resolved['map'] = map_id
                resolved['use_amcl'] = options.get('use_amcl', True)
                parts += ['--map', str(self.maps.path(map_id))]
                if resolved['use_amcl']: parts.append('--use-amcl')
        elif profile in BENCH and not options:
            parts, resolved = ['bench', profile], {}
        else:
            raise web.HTTPBadRequest(text='Неизвестный профиль')
        try:
            await self.run_process(profile, parts)
        except OSError as exc:
            self.process_state, self.last_error = 'error', str(exc)
            raise web.HTTPServiceUnavailable(text=str(exc))
        if self.active_profile == profile:
            self.active_options = resolved
            self.confirmed = None
        return web.json_response({'ok': True, 'options': resolved})

    async def json_body(self, request):
        try:
            data = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Ожидается JSON-объект')
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text='Ожидается JSON-объект')
        return data

    async def stop(self, request):
        self.bridge.publish(emergency=True)
        await self.navigation.interrupt('cancelled', 'Профиль остановлен')
        if self.save_task and not self.save_task.done():
            raise web.HTTPConflict(text='Дождитесь сохранения карты или используйте E-STOP')
        self.bridge.publish()
        self.moving = False
        await self.stop_process()
        if not self.navigation.busy() and not self.navigation.cancel_uncertain:
            self.navigation = Navigation(self.bridge, self.log)
        self.confirmed = None
        return web.json_response({'ok': True})

    async def emergency_stop(self):
        self.estopped = True
        self.moving = False
        self.bridge.publish()
        self.bridge.publish(emergency=True)
        async with self.emergency_lock:
            self.bridge.lease('stop', self.lease_token or '', self.lease_seq)
            await self.navigation.interrupt('cancelled','E-STOP')
            self.confirmed = None
            if self.link_task and not self.link_task.done():
                self.link_task.cancel()
                with contextlib.suppress(asyncio.CancelledError): await self.link_task
            await self.log('АВАРИЙНАЯ ОСТАНОВКА')
            await self.cancel_save()
            await self.stop_process()
            if not self.mock:
                runner = Runner(self.config, self.robot_ip, self.mock, self.local)
                await asyncio.to_thread(runner.emergency_stop)

    async def estop(self, request):
        await self.emergency_stop()
        return web.json_response({'ok': True})

    async def reset(self, request):
        if self.emergency_lock.locked():
            raise web.HTTPConflict(text='Дождитесь завершения аварийной остановки')
        self.estopped = False
        self.bridge.publish()
        await self.log('Аварийная остановка снята; движение не возобновлено.')
        return web.json_response({'ok': True})

    async def discovery(self, request):
        if self.proc and self.proc.returncode is None:
            raise web.HTTPConflict(text='Остановите профиль перед поиском')
        self.robot_ip = await asyncio.to_thread(discover_robot, self.config)
        if self.robot_ip and not self.mock:
            self.bridge.publish()
            self.moving = False
            self.bridge.close()
            self.bridge = Bridge(self.config, self.mock, self.robot_ip)
            self.navigation = Navigation(self.bridge, self.log)
            self.confirmed = None
            if self.control_id: await self.lose_control("Настройки соединения изменились")
        return web.json_response({'robot_ip': self.robot_ip})

    async def ops(self, request):
        action = request.match_info['action']
        if action not in {'timesync', 'save-map', 'wifi'}:
            raise web.HTTPBadRequest(text='Неизвестное действие')
        if action == 'save-map':
            return await self.save_map(request)
        data = await self.json_body(request)
        parts = ['ops', action]
        if action == 'wifi':
            profile = data.get('profile', 'list')
            if profile not in {'scan', 'list', 'dev', 'tplink'}:
                raise web.HTTPBadRequest(text='Недопустимый профиль Wi-Fi')
            parts += ['--profile', profile]
        await self.run_process('ops ' + action, parts)
        return web.json_response({'ok': True})

    async def list_maps(self, request):
        return web.json_response({'maps': await asyncio.to_thread(self.maps.list),
            'default_map': self.config.profiles['navigate'].map if 'navigate' in self.config.profiles else None})

    async def map_preview(self, request):
        try:
            bitmap = await asyncio.to_thread(self.maps.preview, request.match_info['map_id'])
        except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as exc:
            raise web.HTTPNotFound(text=str(exc))
        return web.Response(body=bitmap, content_type='image/png', headers={'Cache-Control': 'no-store'})

    async def get_job(self, request):
        job = self.jobs.get(request.match_info['job_id'])
        if job is None: raise web.HTTPNotFound(text='Операция не найдена')
        return web.json_response(job)

    async def save_map(self, request):
        data = await self.json_body(request)
        try:
            name = self.maps.validate_name(data.get('name'))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        stop_after = data.get('stop_after', False)
        if type(stop_after) is not bool:
            raise web.HTTPBadRequest(text='stop_after: требуется true или false')
        if self.estopped: raise web.HTTPConflict(text='Аварийная остановка активна')
        if stop_after and self.active_profile != 'mapping':
            raise web.HTTPConflict(text='Сохранить и остановить можно только активный Mapping')
        if self.save_task and not self.save_task.done():
            raise web.HTTPConflict(text='Карта уже сохраняется')
        self.maps.directory.mkdir(parents=True, exist_ok=True)
        if any((self.maps.directory / f'{name}.{suffix}').exists() for suffix in ('yaml', 'pgm')):
            raise web.HTTPConflict(text='Карта с таким именем уже есть. Выберите новое имя.')
        job = {'id': uuid.uuid4().hex, 'type': 'map_save', 'state': 'running', 'name': name,
               'stop_after': stop_after, 'error': None, 'map_id': None}
        self.jobs[job['id']] = job
        # Bound job history; running jobs are never evicted.
        self.prune_jobs()
        self.save_task = asyncio.create_task(self.save_job(job, self.proc))
        return web.json_response(job, status=202)

    async def run_map_saver(self, target):
        if self.mock:
            raise RuntimeError('В mock-режиме /map не публикуется. Для сохранения нужен активный SLAM.')
        command, _ = build_shell_command([
            'ros2', 'run', 'nav2_map_server', 'map_saver_cli', '-t', '/map',
            '-f', str(target), '--fmt', 'pgm', '--occ', '0.65', '--free', '0.15',
            '--ros-args', '-p', 'save_map_timeout:=25.0'], repo_dir=ROOT)
        self.save_proc = await asyncio.create_subprocess_exec(*command, cwd=ROOT,
            env=build_base_environment(self.config.network.domain_id, self.config.network.rmw, self.robot_ip),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        proc = self.save_proc
        async def output():
            while line := await proc.stdout.readline():
                await self.log('[карта] ' + line.decode('utf-8', errors='replace').rstrip())
        reader = asyncio.create_task(output())
        try:
            if await proc.wait() != 0:
                raise RuntimeError('Не удалось получить /map или сохранить карту. Подробности в журнале.')
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGTERM)
                try: await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError): await reader
            self.save_proc = None

    async def save_job(self, job, profile_proc):
        try:
            await self.log(f"Сохранение карты: {job['name']}")
            with tempfile.TemporaryDirectory(prefix='.saving-', dir=self.maps.directory) as directory:
                target = Path(directory) / job['name']
                await asyncio.wait_for(self.run_map_saver(target), self.save_timeout)
                temporary = MapCatalog(Path(directory))
                info = temporary.inspect(target.name + '.yaml')
                image = Path(directory) / info['image']
                yaml_file = target.with_suffix('.yaml')
                data = yaml.safe_load(yaml_file.read_text(encoding='utf-8'))
                data['image'] = image.name
                yaml_file.write_text(yaml.safe_dump(data), encoding='utf-8')
                if self.estopped: raise asyncio.CancelledError()
                # Exclusive hard links never overwrite an existing file. YAML is published last.
                published_image = self.maps.directory / image.name
                os.link(image, published_image)
                try: os.link(yaml_file, self.maps.directory / yaml_file.name)
                except BaseException:
                    published_image.unlink()
                    raise
                job['map_id'] = yaml_file.name
            if job['stop_after']:
                if self.proc is not profile_proc or self.active_profile != 'mapping':
                    raise RuntimeError('Карта сохранена, но профиль изменился; остановка отменена')
                self.bridge.publish()
                self.moving = False
                await self.stop_process()
            job['state'] = 'succeeded'
            await self.log(f"Карта сохранена: {job['map_id']}")
        except asyncio.CancelledError:
            job['state'], job['error'] = 'cancelled', 'Сохранение отменено'
        except Exception as exc:
            job['state'] = 'failed'
            job['error'] = 'Тайм-аут сохранения (30 секунд)' if isinstance(exc, asyncio.TimeoutError) else str(exc)
            await self.log('Ошибка сохранения карты: ' + job['error'])

    async def cancel_save(self):
        if self.save_task and not self.save_task.done():
            self.save_task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.save_task

    async def teleop(self, request):
        ws = web.WebSocketResponse(heartbeat=5, max_msg_size=2048)
        await ws.prepare(request)
        self.control_clients.add(ws)
        await ws.send_json({'type':'observer','owned':self.control_id is not None})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT: continue
                try:
                    data = json.loads(msg.data)
                    if data.get('type') == 'estop':
                        await self.emergency_stop()
                    elif data.get('type') == 'claim':
                        try: await self.claim_control(ws)
                        except ValueError as exc: await ws.send_json({'type':'error','message':str(exc)})
                    elif data.get('type') == 'release':
                        await self.release_control(ws)
                        await ws.send_json({'type':'released'})
                    elif data.get('type') == 'heartbeat' and self.teleop_client is ws:
                        self.control_seen = time.monotonic()
                    elif data.get('type') == 'twist' and not self.estopped:
                        if self.teleop_client is not ws or time.monotonic()-self.control_seen>.35:
                            await ws.send_json({'type':'error','message':'Возьмите управление и поддерживайте heartbeat'})
                            continue
                        v, w = float(data['v']), float(data['w'])
                        legacy = float(data.get('speed_limit', .25))
                        linear = float(data.get('linear_limit', legacy))
                        angular = float(data.get('angular_limit', .8 * legacy / .25))
                        if not all(math.isfinite(value) for value in (v, w, legacy, linear, angular)): raise ValueError()
                        if linear < 0 or angular < 0: raise ValueError()
                        linear, angular = min(.25, linear), min(.8, angular)
                        v,w=max(-linear,min(linear,v)),max(-angular,min(angular,w))
                        if v or w:
                            reason = None
                            if self.link_task and not self.link_task.done(): reason = 'Дождитесь завершения теста связи'
                            elif not self.lease_ready(): reason = 'Нет подтверждённой управляющей сессии Pi'
                            elif not self.mock: reason = self.driver_reason(self.bridge.telemetry.snapshot()['topics'])
                            if reason:
                                self.bridge.publish()
                                await ws.send_json({'type':'error','message':reason})
                                continue
                            if self.navigation.state in ('running','waiting') or self.navigation.busy():
                                self.bridge.publish(emergency=True)
                                await self.navigation.interrupt('paused','Ручное управление')
                                if self.navigation.busy() or self.navigation.cancel_uncertain: continue
                        self.bridge.publish(v,w)
                        self.last_command,self.moving = time.monotonic(),bool(v or w)
                except (ValueError,TypeError,KeyError,AttributeError):
                    await ws.close(code=1003,message=b'Invalid command')
                    break
        finally:
            await self.release_control(ws)
            self.control_clients.discard(ws)
        return ws

    async def logs(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        for line in self.log_history: await ws.send_str(line)
        self.log_clients.add(ws)
        try:
            async for _ in ws: pass
        finally:
            self.log_clients.discard(ws)
        return ws


def start_web_server(config, host='0.0.0.0', port=8080, no_browser=False, robot_ip=None, mock=False, local=False):
    server = ControlCenterServer(config, robot_ip, mock, local)
    if server.bridge.error:
        print(f'[ui] ROS недоступен: {server.bridge.error}. Управление движением отключено.', flush=True)
    print(f'[ui] Web Control Center: http://{host}:{port} (локально: http://127.0.0.1:{port})', flush=True)
    if not no_browser:
        webbrowser.open(f'http://127.0.0.1:{port}')
    web.run_app(server.app, host=host, port=port)
