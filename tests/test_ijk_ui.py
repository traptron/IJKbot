"""Web control center HTTP and motion safety checks without robot hardware."""
import asyncio
import unittest
import sys
import tempfile
import yaml
from PIL import Image
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer
from tools.ijk.config import IjkConfig
from tools.ijk.web.server import ControlCenterServer
from tools.ijk.web.maps import MapCatalog
from tools.ijk.web.annotations import Annotations


class WebControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.center = ControlCenterServer(IjkConfig(), mock=True)
        self.directory = tempfile.TemporaryDirectory()
        self.center.maps = MapCatalog(Path(self.directory.name))
        self.center.annotations = Annotations(self.center.maps)
        self.heartbeat_tasks = []
        self.published = []
        self.center.bridge.publish = lambda v=0, w=0, emergency=False: self.published.append((v, w, emergency))
        self.client = TestClient(TestServer(self.center.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        for task in self.heartbeat_tasks:
            task.cancel()
        await asyncio.gather(*self.heartbeat_tasks, return_exceptions=True)
        await self.client.close()
        self.directory.cleanup()

    async def control_socket(self):
        ws = await self.client.ws_connect('/ws/teleop')
        await ws.receive_json()
        await ws.send_json({'type':'claim'})
        message = await ws.receive_json()
        self.assertEqual(message['type'], 'claimed')
        async def heartbeat():
            while not ws.closed:
                await ws.send_json({'type':'heartbeat'})
                await asyncio.sleep(.1)
        self.heartbeat_tasks.append(asyncio.create_task(heartbeat()))
        return ws

    async def test_status_assets_and_origin(self):
        response = await self.client.get('/api/status')
        self.assertTrue((await response.json())['mock'])
        self.assertEqual((await self.client.get('/')).status, 200)
        self.assertEqual((await self.client.get('/static/app.js')).status, 200)
        self.assertEqual((await self.client.post('/api/estop', headers={'Origin': 'http://other.example'})).status, 403)

    async def test_motion_watchdog_and_estop_latch(self):
        ws = await self.control_socket()
        await ws.send_json({'type': 'twist', 'v': 9, 'w': -9})
        await asyncio.sleep(.1)
        self.assertIn((.25, -.8, False), self.published)
        await asyncio.sleep(.4)
        self.assertFalse(self.center.moving)
        self.assertEqual(self.published[-1], (0, 0, False))
        response = await self.client.post('/api/estop')
        self.assertEqual(response.status, 200)
        self.assertTrue(self.center.estopped)
        self.published.clear()
        await ws.send_json({'type': 'twist', 'v': .2, 'w': 0})
        await asyncio.sleep(.1)
        self.assertNotIn((.2, 0., False), self.published)
        await self.client.post('/api/reset')
        self.assertFalse(self.center.estopped)
        await ws.close()

    async def test_reject_second_driver_and_invalid_profile(self):
        first = await self.control_socket()
        second = await self.client.ws_connect('/ws/teleop')
        await second.receive_json()
        await second.send_json({'type':'claim'})
        self.assertEqual((await second.receive_json())['type'], 'error')
        self.assertFalse(second.closed)
        await second.close()
        response = await self.client.post('/api/profile/start', json={'profile': 'anything'})
        self.assertEqual(response.status, 400)
        await first.close()

    async def test_profile_lifecycle_and_log_stream(self):
        self.center.command = lambda parts: [sys.executable, '-u', '-c',
            'import time; print("profile ready", flush=True); time.sleep(30)']
        logs = await self.client.ws_connect('/ws/logs')
        response = await self.client.post('/api/profile/start', json={'profile': 'mapping'})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.center.active_profile, 'mapping')
        response = await self.client.post('/api/profile/start', json={'profile': 'teleop'})
        self.assertEqual(response.status, 409)
        lines = []
        for _ in range(3):
            message = await asyncio.wait_for(logs.receive(), 3)
            lines.append(message.data)
            if 'profile ready' in message.data:
                break
        self.assertTrue(any('profile ready' in line for line in lines))
        response = await self.client.post('/api/profile/stop')
        self.assertEqual(response.status, 200)
        self.assertIsNone(self.center.active_profile)
        await logs.close()

    async def test_bad_messages_disconnect_and_zero_motion(self):
        ws = await self.control_socket()
        await ws.send_json({'type': 'twist', 'v': .1, 'w': .2})
        await asyncio.sleep(.05)
        await ws.send_json({'type': 'twist', 'v': 'nan', 'w': 0})
        await ws.receive()
        await asyncio.sleep(.05)
        self.assertFalse(self.center.moving)
        self.assertEqual(self.published[-1], (0, 0, False))

    async def test_map_name_validation_and_estop_start_lock(self):
        response = await self.client.post('/api/ops/save-map', json={'name': '../outside'})
        self.assertEqual(response.status, 400)
        await self.client.post('/api/estop')
        response = await self.client.post('/api/profile/start', json={'profile': 'mapping'})
        self.assertEqual(response.status, 409)

    async def test_web_teleop_does_not_start_gamepad(self):
        commands = []
        async def fake_run(name, parts):
            commands.append((name, parts))
        self.center.run_process = fake_run
        response = await self.client.post('/api/profile/start', json={'profile': 'teleop'})
        self.assertEqual(response.status, 200)
        self.assertEqual(commands, [('teleop', ['teleop', '--web', '--speed', '0.25'])])


    def make_map(self, target):
        Image.new('L', (20, 10), 254).save(target.with_suffix('.pgm'))
        target.with_suffix('.yaml').write_text(yaml.safe_dump({
            'image': target.name + '.pgm', 'resolution': .05, 'origin': [0, 0, 0],
            'negate': 0, 'occupied_thresh': .65, 'free_thresh': .196}))

    async def finish_job(self, response):
        self.assertEqual(response.status, 202)
        job = await response.json()
        await asyncio.wait_for(self.center.save_task, 2)
        return await (await self.client.get('/api/jobs/' + job['id'])).json()

    async def test_save_during_mapping_and_preview(self):
        self.center.active_profile = 'mapping'
        async def saver(target): self.make_map(target)
        self.center.run_map_saver = saver
        job = await self.finish_job(await self.client.post('/api/maps/save', json={'name':'new_map'}))
        self.assertEqual(job['state'], 'succeeded')
        self.assertEqual(self.center.active_profile, 'mapping')
        response = await self.client.get('/api/maps')
        maps = (await response.json())['maps']
        self.assertEqual(maps[0]['id'], 'new_map.yaml')
        self.assertEqual(maps[0]['width'], 20)
        self.assertEqual((await self.client.get(maps[0]['preview_url'])).content_type, 'image/png')
        self.assertEqual((await self.client.post('/api/maps/save', json={'name':'new_map'})).status, 409)
        self.assertEqual((await self.client.post('/api/maps/save', json={'name':'../escape'})).status, 400)

    async def test_failed_save_keeps_mapping_alive_and_no_partial_files(self):
        self.center.active_profile = 'mapping'
        async def saver(target):
            target.with_suffix('.pgm').write_text('partial')
            raise RuntimeError('Нет /map')
        self.center.run_map_saver = saver
        job = await self.finish_job(await self.client.post('/api/maps/save', json={'name':'failure','stop_after':True}))
        self.assertEqual(job['state'], 'failed')
        self.assertIn('Нет /map', job['error'])
        self.assertEqual(self.center.active_profile, 'mapping')
        self.assertEqual(list(self.center.maps.directory.iterdir()), [])

    async def test_save_then_stop(self):
        self.center.active_profile = 'mapping'
        async def saver(target): self.make_map(target)
        self.center.run_map_saver = saver
        job = await self.finish_job(await self.client.post('/api/maps/save', json={'name':'finished','stop_after':True}))
        self.assertEqual(job['state'], 'succeeded')
        self.assertIsNone(self.center.active_profile)

    async def test_save_timeout(self):
        self.center.active_profile = 'mapping'
        self.center.save_timeout = .02
        async def saver(target): await asyncio.sleep(10)
        self.center.run_map_saver = saver
        job = await self.finish_job(await self.client.post('/api/maps/save', json={'name':'slow','stop_after':True}))
        self.assertEqual(job['state'], 'failed')
        self.assertIn('Тайм-аут', job['error'])
        self.assertEqual(self.center.active_profile, 'mapping')

    async def test_estop_cancels_save_and_blocks_parallel_save(self):
        entered = asyncio.Event()
        async def saver(target):
            entered.set()
            await asyncio.sleep(10)
        self.center.run_map_saver = saver
        response = await self.client.post('/api/ops/save-map', json={'name':'cancelled'})
        job = await response.json()
        await entered.wait()
        self.assertEqual((await self.client.post('/api/maps/save', json={'name':'second'})).status, 409)
        self.assertEqual((await self.client.post('/api/profile/stop')).status, 409)
        await self.client.post('/api/estop')
        state = await (await self.client.get('/api/jobs/' + job['id'])).json()
        self.assertEqual(state['state'], 'cancelled')
        self.assertEqual(list(self.center.maps.directory.iterdir()), [])

    async def test_catalog_invalid_image_and_traversal(self):
        self.center.maps.directory.joinpath('bad.yaml').write_text('image: missing.pgm')
        response = await self.client.get('/api/maps')
        self.assertFalse((await response.json())['maps'][0]['valid'])
        response = await self.client.post('/api/profile/start', json={'profile':'navigate','options':{'map':'../outside.yaml'}})
        self.assertEqual(response.status, 400)
        response = await self.client.post('/api/profile/start', json={'profile':'navigate','options':{'map':'bad.yaml'}})
        self.assertEqual(response.status, 400)

    async def test_structured_navigation_flags(self):
        self.make_map(self.center.maps.directory / 'room')
        commands = []
        async def run(name, parts): commands.append(parts)
        self.center.run_process = run
        response = await self.client.post('/api/profile/start', json={'profile':'navigate','options':{
            'map':'room.yaml','use_amcl':True,'rviz':False,'record':True,'bag_name':'route_1'}})
        self.assertEqual(response.status, 200)
        parts = commands[0]
        self.assertEqual(parts[:4], ['--record','--bag-name','route_1','navigate'])
        self.assertIn('--use-amcl', parts)
        self.assertIn('--no-rviz', parts)
        self.assertIn(str(self.center.maps.directory / 'room.yaml'), parts)
        response = await self.client.post('/api/profile/start', json={'profile':'navigate','options':{'map':'room.yaml','use_amcl':False}})
        self.assertEqual(response.status, 200)
        self.assertNotIn('--use-amcl', commands[-1])
        response = await self.client.post('/api/profile/start', json={'profile':'teleop','options':{'rviz':False}})
        self.assertEqual(response.status, 400)

    async def test_independent_zero_and_hard_limits(self):
        ws = await self.control_socket()
        for data, expected in [
            ({'v':1,'w':1,'linear_limit':.1,'angular_limit':.6},(.1,.6,False)),
            ({'v':1,'w':1,'linear_limit':0,'angular_limit':.6},(0,.6,False)),
            ({'v':1,'w':1,'linear_limit':.1,'angular_limit':0},(.1,0,False)),
            ({'v':1,'w':1,'linear_limit':99,'angular_limit':99},(.25,.8,False)),
            ({'v':1,'w':1,'speed_limit':.1},(.1,.8*.1/.25,False)),
        ]:
            await ws.send_json({'type':'twist',**data})
            await asyncio.sleep(.02)
            self.assertEqual(self.published[-1], expected)
        await ws.send_json({'type':'twist','v':0,'w':0,'angular_limit':float('nan')})
        await ws.receive()
        self.assertTrue(ws.closed)

    async def test_saver_timeout_terminates_its_process(self):
        from unittest.mock import patch
        spawned = []
        real_spawn = asyncio.create_subprocess_exec
        async def spawn(*args, **kwargs):
            process = await real_spawn(*args, **kwargs)
            spawned.append(process)
            return process
        self.center.mock = False
        with patch('tools.ijk.web.server.build_shell_command', return_value=(
                [sys.executable, '-u', '-c', 'import time; print("waiting",flush=True); time.sleep(60)'], False)), \
             patch('tools.ijk.web.server.asyncio.create_subprocess_exec', side_effect=spawn):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(self.center.run_map_saver(self.center.maps.directory / 'timeout'), .15)
        self.assertIsNotNone(spawned[0].returncode)
        self.assertIsNone(self.center.save_proc)
        self.center.mock = True

    def ready_navigation(self):
        import time
        self.make_map(self.center.maps.directory / 'room')
        self.center.active_profile='navigate'
        self.center.active_options={'map':'room.yaml','use_amcl':True,'rviz':False}
        self.center.bridge.telemetry.put('odom',{'v':0,'w':0})
        self.center.bridge.telemetry.put('scan',{'points':[[1,0]],'nearest_m':1})
        self.center.bridge.telemetry.put('pose',{'x':.2,'y':.2,'yaw':0})
        self.center.bridge.telemetry.put('amcl',{'received':True})
        self.center.bridge.telemetry.put('nav',{'ready':True,'amcl_active':True,'navigator_active':True,'external_goal':False})
        self.center.bridge.telemetry.put('diagnostics',{'sts3215_drive':{'level':0,'message':'Drive ready','values':{},'received':time.monotonic()}})
        document=self.center.annotations.load('room.yaml')
        payload={key:document[key] for key in ('revision','fingerprint','places','routes')}
        payload['places']=[{'id':'door','name':'Дверь','x':.3,'y':.2,'yaw':0}]
        self.center.annotations.update('room.yaml',payload)
        self.center.confirmed=(id(None),'room.yaml',document['fingerprint'])

    async def test_telemetry_is_readable_but_mutations_need_owner(self):
        self.make_map(self.center.maps.directory/'room')
        self.assertEqual((await self.client.get('/api/telemetry')).status,200)
        document=await (await self.client.get('/api/maps/room.yaml/annotations')).json()
        payload={key:document[key] for key in ('revision','fingerprint','places','routes')}
        response=await self.client.put('/api/maps/room.yaml/annotations',json=payload)
        self.assertEqual(response.status,403)
        ws=await self.control_socket()
        header={'X-Control-Id':self.center.control_id}
        response=await self.client.put('/api/maps/room.yaml/annotations',json=payload,headers=header)
        self.assertEqual(response.status,200)
        response=await self.client.put('/api/maps/room.yaml/annotations',json=payload,headers=header)
        self.assertEqual(response.status,409)
        await ws.close()

    async def test_prepare_execute_manual_override_and_disconnect(self):
        from test_ijk_telemetry import FakeGoal
        self.ready_navigation()
        ws=await self.control_socket();header={'X-Control-Id':self.center.control_id}
        goals=[]
        async def send(pose,feedback):
            goal=FakeGoal();goals.append(goal);return goal
        self.center.bridge.send_goal=send
        response=await self.client.post('/api/navigation/prepare',json={'map_id':'room.yaml','kind':'place','id':'door'},headers=header)
        self.assertEqual(response.status,200)
        prepared=await response.json()
        self.assertEqual(goals,[])
        response=await self.client.post('/api/navigation/execute',json={'plan_id':prepared['id']},headers=header)
        self.assertEqual(response.status,400)
        response=await self.client.post('/api/navigation/execute',json={'plan_id':prepared['id'],'confirmed':True},headers=header)
        self.assertEqual(response.status,200)
        await asyncio.sleep(.1)
        self.assertEqual(len(goals),1)
        await ws.send_json({'type':'twist','v':.1,'w':0})
        await asyncio.sleep(.15)
        self.assertEqual(self.center.navigation.state,'paused')
        self.assertEqual(goals[0].cancelled,1)
        self.assertIn((.1,0.,False),self.published)
        response=await self.client.post('/api/navigation/resume',headers=header)
        self.assertEqual(response.status,200)
        await asyncio.sleep(.1)
        await ws.close()
        await asyncio.sleep(.15)
        self.assertEqual(self.center.navigation.state,'paused')
        self.assertTrue(self.center.control_broken)
        replacement=await self.control_socket()
        self.assertEqual(self.center.navigation.state,'paused')
        await replacement.close()

    async def test_no_stale_localization_or_unconfirmed_start(self):
        self.ready_navigation()
        ws=await self.control_socket();header={'X-Control-Id':self.center.control_id}
        self.center.confirmed=None
        response=await self.client.post('/api/navigation/prepare',json={'map_id':'room.yaml','kind':'place','id':'door'},headers=header)
        plan=await response.json()
        response=await self.client.post('/api/navigation/execute',json={'plan_id':plan['id'],'confirmed':True},headers=header)
        self.assertEqual(response.status,409)
        response=await self.client.post('/api/navigation/confirm',json={'map_id':'room.yaml','confirmed':True},headers=header)
        self.assertEqual(response.status,200)
        self.center.bridge.telemetry.samples['pose']['last']-=5
        response=await self.client.post('/api/navigation/capture',json={'map_id':'room.yaml'},headers=header)
        self.assertEqual(response.status,409)
        await ws.close()

    async def test_llm_interpretation_has_no_movement_and_returns_current_start(self):
        from unittest.mock import patch,AsyncMock
        from tools.ijk.web.commands import CommandPlan
        self.ready_navigation()
        ws=await self.control_socket();header={'X-Control-Id':self.center.control_id}
        parsed=CommandPlan(target_landmark_id='door',search_strategy='named_route',reasoning='Дверь и назад',steps=[{'kind':'place','id':'door'},{'kind':'return','id':None}])
        with patch('tools.ijk.web.commands.interpret',new=AsyncMock(return_value=parsed)):
            response=await self.client.post('/api/commands/interpret',json={'map_id':'room.yaml','text':'К двери и назад'},headers=header)
        self.assertEqual(response.status,200)
        plan=await response.json()
        self.assertEqual(self.center.navigation.state,'idle')
        self.center.bridge.telemetry.put('pose',{'x':.4,'y':.2,'yaw':0})
        from test_ijk_telemetry import FakeGoal
        async def send(pose,feedback):return FakeGoal()
        self.center.bridge.send_goal=send
        response=await self.client.post('/api/navigation/execute',json={'plan_id':plan['id'],'confirmed':True},headers=header)
        self.assertEqual(response.status,200)
        self.assertEqual(self.center.navigation.points[-1]['x'],.4)
        with patch('tools.ijk.web.commands.interpret',new=AsyncMock(side_effect=RuntimeError('offline'))):
            response=await self.client.post('/api/commands/interpret',json={'map_id':'room.yaml','text':'К двери'},headers=header)
        self.assertEqual(response.status,503)
        await ws.close()

    async def test_bandwidth_test_refuses_motion_and_uses_existing_job_protocol(self):
        from unittest.mock import patch,AsyncMock
        import time
        self.ready_navigation()
        ws=await self.control_socket();header={'X-Control-Id':self.center.control_id}
        self.center.robot_ip='192.0.2.1';self.center.mock=False
        self.center.stationary_since=None
        response=await self.client.post('/api/link/test',headers=header)
        self.assertEqual(response.status,409)
        self.center.stationary_since=time.monotonic()-2
        class Input:
            def __init__(self):self.sizes=[]
            def write(self,data):self.sizes.append(len(data))
            async def drain(self):pass
        class Output:
            def __init__(self):self.lines=[b'READY\n',b'ACK\n']
            async def readline(self):return self.lines.pop(0)
            async def readexactly(self,n):return bytes(n)
        class Process:
            def __init__(self):self.stdin=Input();self.stdout=Output();self.returncode=None
            def kill(self):self.returncode=-9
            async def wait(self):self.returncode=0;return 0
        process=Process()
        with patch('tools.ijk.web.services.asyncio.create_subprocess_exec',new=AsyncMock(return_value=process)):
            response=await self.client.post('/api/link/test',headers=header)
            self.assertEqual(response.status,202)
            job=await response.json()
            await self.center.link_task
        result=await (await self.client.get('/api/jobs/'+job['id'])).json()
        self.assertEqual(result['type'],'link_test')
        self.assertEqual(result['state'],'succeeded')
        self.assertEqual(process.stdin.sizes,[1048576,1])
        status=await (await self.client.get('/api/status')).json()
        self.assertIsNone(status['map_job'])
        self.center.mock=True
        await ws.close()

    async def test_recovery_does_not_rearm_before_old_goals_cancelled(self):
        from unittest.mock import AsyncMock
        self.center.bridge.lease('arm','a'*32,1)
        self.center.bridge.lease('stop','a'*32,2)
        self.center.bridge.cancel_all_goals=AsyncMock(side_effect=RuntimeError('No Nav2 reply'))
        ws=await self.client.ws_connect('/ws/teleop');await ws.receive_json()
        await ws.send_json({'type':'claim'})
        self.assertEqual((await ws.receive_json())['type'],'error')
        guard=self.center.bridge.telemetry.snapshot()['topics']['guard']['data']
        self.assertEqual(guard['state'],'latched')
        self.assertIsNone(self.center.control_id)
        self.center.bridge.cancel_all_goals=AsyncMock()
        await ws.send_json({'type':'claim'})
        self.assertEqual((await ws.receive_json())['type'],'claimed')
        self.center.bridge.cancel_all_goals.assert_awaited_once()
        self.assertTrue(self.center.lease_ready())
        await ws.close()

    async def test_concurrent_claims_have_one_owner(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def recovery():
            entered.set();await release.wait()
        self.center.prepare_rearm=recovery
        first=await self.client.ws_connect('/ws/teleop');await first.receive_json()
        second=await self.client.ws_connect('/ws/teleop');await second.receive_json()
        await first.send_json({'type':'claim'});await entered.wait()
        await second.send_json({'type':'claim'})
        release.set()
        self.assertEqual((await first.receive_json())['type'],'claimed')
        self.assertEqual((await second.receive_json())['type'],'error')
        await second.close();await first.close()
