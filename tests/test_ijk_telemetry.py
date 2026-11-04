"""Pure safety, coordinate and metadata checks; no real UART or ROS traffic."""
import asyncio
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.bringup.scripts.web_guard import WebGuard
from tools.ijk.web.telemetry import Telemetry, radar_points
from tools.ijk.web.annotations import Annotations, Conflict
from tools.ijk.web.maps import MapCatalog
from tools.ijk.web.navigation import Navigation
from tools.ijk.web.commands import validate_plan
from tools.ijk.web.ros_bridge import Bridge
from PIL import Image
import yaml


class Clock:
    def __init__(self):self.value=0.
    def __call__(self):return self.value


class ActionStatusTests(unittest.TestCase):
    def test_own_goal_stays_owned_until_terminal_status(self):
        from types import SimpleNamespace as Item
        bridge=Bridge(None,True)
        identifier=bytes(range(16));bridge.own_goals.add(identifier)
        def status(value):
            return Item(status_list=[Item(status=value,goal_info=Item(goal_id=Item(uuid=list(identifier))))])
        bridge.action_status(status(2))
        self.assertFalse(bridge.telemetry.snapshot()['topics']['nav']['data']['external_goal'])
        self.assertIn(identifier,bridge.own_goals)
        bridge.action_status(status(4))
        self.assertNotIn(identifier,bridge.own_goals)


class GuardTests(unittest.TestCase):
    def test_lease_latches_and_stale_heartbeat_cannot_rearm(self):
        clock=Clock();guard=WebGuard(clock)
        token='a'*32
        self.assertFalse(guard.tick())
        guard.receive({'type':'arm','token':token,'seq':0})
        clock.value=.4;guard.receive({'type':'heartbeat','token':token,'seq':1})
        clock.value=.91;self.assertTrue(guard.tick())
        guard.receive({'type':'heartbeat','token':token,'seq':2})
        guard.receive({'type':'arm','token':token,'seq':3})
        self.assertTrue(guard.tick())
        guard.receive({'type':'arm','token':'b'*32,'seq':4})
        self.assertFalse(guard.tick())
        guard.receive({'type':'arm','token':token,'seq':99})
        self.assertEqual(guard.token,'b'*32)

    def test_stop_disarm_and_out_of_order_packets(self):
        guard=WebGuard();token='1'*32
        guard.receive({'type':'arm','token':token,'seq':10})
        guard.receive({'type':'disarm','token':token,'seq':9})
        self.assertEqual(guard.state,'armed')
        guard.receive({'type':'stop'})
        guard.receive({'type':'disarm','token':token,'seq':11})
        self.assertTrue(guard.tick())
        guard.receive({'type':'arm','token':'2'*32,'seq':1})
        guard.receive({'type':'disarm','token':'2'*32,'seq':2})
        self.assertEqual(guard.state,'disarmed')
        guard.receive({'type':'arm','token':'2'*32,'seq':99})
        self.assertEqual(guard.state,'disarmed')

    def test_restart_latches_armed_session(self):
        guard=WebGuard()
        guard.restore({'state':'armed','token':'a'*32})
        guard.receive({'type':'arm','token':'a'*32,'seq':999})
        self.assertTrue(guard.tick())
        guard.receive({'type':'arm','token':'b'*32,'seq':1})
        self.assertFalse(guard.tick())

    def test_bad_packet_never_arms(self):
        guard=WebGuard()
        for packet in ({},{'type':'arm','token':'bad','seq':0},{'type':'arm','token':'a'*32,'seq':True}):guard.receive(packet)
        self.assertEqual(guard.state,'disarmed')


class TelemetryTests(unittest.TestCase):
    def test_independent_freshness_and_link_losses(self):
        clock=Clock();data=Telemetry(clock)
        data.put('odom',{'v':0,'w':0});data.put('system',{'cpu_temp_c':55})
        for seq in range(10):
            clock.value=seq*.1;data.probe(seq)
            if seq%2==0:clock.value+=.01;data.echo(seq)
        clock.value=1.6
        snap=data.snapshot()
        self.assertTrue(snap['topics']['odom']['stale'])
        self.assertFalse(snap['topics']['system']['stale'])
        self.assertAlmostEqual(snap['link']['missing_percent'],50)
        self.assertAlmostEqual(snap['link']['rtt_p50_ms'],10)
        clock.value=40
        self.assertEqual(data.snapshot()['link']['samples'],0)

    def test_radar_respects_roll_and_yaw_and_drops_bad_ranges(self):
        # RPY=(pi,0,pi): (x,y,z) -> (-x,y,-z), the installed upside-down mount.
        points=radar_points([1,1,float('nan'),float('inf'),.01],.1,10,0,math.pi/2,(.2,0,.12),(0,1,0,0))
        self.assertAlmostEqual(points[0][0],-.8)
        self.assertAlmostEqual(points[1][1],1)
        self.assertEqual(len(points),2)
        self.assertLessEqual(len(radar_points([1]*1080,.1,10,0,.01,(0,0,0),(0,0,0,1))),360)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        Image.new('L',(100,100),254).save(self.root/'room.pgm')
        (self.root/'room.yaml').write_text(yaml.safe_dump({'image':'room.pgm','resolution':.05,'origin':[0,0,0]}))
        self.store=Annotations(MapCatalog(self.root))

    def tearDown(self):self.temp.cleanup()

    def payload(self):
        document=self.store.load('room.yaml')
        return {k:document[k] for k in ('revision','fingerprint','places','routes')}

    def test_atomic_revision_map_binding_and_route_snapshots(self):
        data=self.payload()
        data['places']=[{'id':'door','name':'Дверь','x':1,'y':1,'yaw':0}]
        data['routes']=[{'id':'tour','name':'Маршрут','points':[{'x':1,'y':1,'yaw':0,'label':'Дверь','wait_s':3}]}]
        first=self.store.update('room.yaml',data)
        with self.assertRaises(Conflict):self.store.update('room.yaml',data)
        data=self.payload();data['places'][0]['x']=2
        second=self.store.update('room.yaml',data)
        self.assertEqual(second['routes'][0]['points'][0]['x'],1)
        Image.new('L',(100,100),0).save(self.root/'room.pgm')
        self.assertFalse(self.store.load('room.yaml')['valid'])
        data=self.payload()
        with self.assertRaises(Conflict):self.store.update('room.yaml',data)
        data['fingerprint']=self.store.fingerprint('room.yaml')
        self.assertTrue(self.store.update('room.yaml',data,True)['valid'])

    def test_bounds_nonfinite_ids_and_map_paths(self):
        for x in (float('nan'),20):
            data=self.payload();data['places']=[{'id':'door','name':'Дверь','x':x,'y':1,'yaw':0}]
            with self.assertRaises(ValueError):self.store.update('room.yaml',data)
        with self.assertRaises(ValueError):self.store.load('../room.yaml')

    def test_commands_accept_only_catalog_ids_and_no_execution(self):
        document={'places':[{'id':'door','name':'Дверь'}],'routes':[]}
        valid={'target_landmark_id':'door','search_strategy':'named_route','reasoning':'Посетить дверь','steps':[{'kind':'place','id':'door'},{'kind':'return','id':None}]}
        self.assertEqual(len(validate_plan(valid,document).steps),2)
        for mutation in ({'steps':[{'kind':'place','id':'unknown'}]}, {'steps':[{'kind':'place','id':'door','x':3}]}, {'search_strategy':'clarify'}):
            with self.assertRaises(ValueError):validate_plan({**valid,**mutation},document)
        with self.assertRaises(ValueError):validate_plan(valid,{'places':document['places']+[{'id':'door2','name':'Дверь'}],'routes':[]})


class FakeGoal:
    def __init__(self):
        self.done=asyncio.Event();self.cancelled=0;self.fail=False
    async def result(self):
        await self.done.wait()
        if self.fail:raise RuntimeError('Цель недоступна')
    async def cancel(self):self.cancelled+=1;self.done.set()


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.goals=[]
        class Bridge:pass
        self.bridge=Bridge()
        async def send(pose,feedback):
            goal=FakeGoal();self.goals.append(goal);feedback(.4);return goal
        self.bridge.send_goal=send
        self.nav=Navigation(self.bridge,AsyncMock())

    async def asyncTearDown(self):
        await self.nav.close()
        if self.nav.task and not self.nav.task.done():self.nav.task.cancel()

    async def wait(self,predicate):
        for _ in range(100):
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('Navigation did not reach expected state')

    async def test_sequence_wait_and_pause_resume(self):
        await self.nav.start('room.yaml','fp',[{'x':1,'y':1,'yaw':0,'wait_s':.2},{'x':2,'y':1,'yaw':0}],'Маршрут')
        await self.wait(lambda:len(self.goals)==1)
        self.goals[0].done.set()
        await self.wait(lambda:self.nav.state=='waiting')
        await self.nav.interrupt('paused')
        self.assertGreater(self.nav.wait_remaining,0)
        await self.nav.resume()
        await self.wait(lambda:len(self.goals)==2)
        self.goals[1].done.set()
        await self.wait(lambda:self.nav.state=='complete')

    async def test_late_acceptance_is_cancelled_before_resume(self):
        accepted=asyncio.Event();goal=FakeGoal()
        async def send(pose,feedback):await accepted.wait();return goal
        self.bridge.send_goal=send
        await self.nav.start('room.yaml','fp',[{'x':1,'y':1,'yaw':0}],'Поздняя цель')
        await asyncio.sleep(.02)
        interruption=asyncio.create_task(self.nav.interrupt('paused'))
        await asyncio.sleep(.1)
        with self.assertRaises(ValueError):await self.nav.resume()
        accepted.set();await interruption
        self.assertEqual(goal.cancelled,1)
        self.assertEqual(self.nav.state,'paused')

    async def test_failure_does_not_skip_to_next_point(self):
        await self.nav.start('room.yaml','fp',[{'x':1,'y':1,'yaw':0},{'x':2,'y':1,'yaw':0}],'Ошибка')
        await self.wait(lambda:len(self.goals)==1)
        self.goals[0].fail=True;self.goals[0].done.set()
        await self.wait(lambda:self.nav.state=='failed')
        self.assertEqual(len(self.goals),1)

    async def test_unconfirmed_cancel_blocks_replacement(self):
        await self.nav.start('room.yaml','fp',[{'x':1,'y':1,'yaw':0}],'Ошибка отмены')
        await self.wait(lambda:len(self.goals)==1)
        self.goals[0].cancel=AsyncMock(side_effect=RuntimeError('Нет ответа'))
        await self.nav.interrupt('paused')
        self.assertTrue(self.nav.cancel_uncertain)
        with self.assertRaises(ValueError):await self.nav.start('room.yaml','fp',[{'x':2,'y':1,'yaw':0}],'Замена')
