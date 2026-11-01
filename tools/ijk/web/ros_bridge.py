"""ROS subscriptions/TF/actions in a dedicated executor; no ROS callbacks block aiohttp."""
import asyncio
import json
import math
import os
import threading
import time
import uuid

from tools.ijk.env import configure_cyclonedds
from tools.ijk.web.telemetry import Telemetry, radar_points


async def ros_future(future):
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    def complete(source):
        def deliver():
            if result.done(): return
            try: result.set_result(source.result())
            except Exception as exc: result.set_exception(exc)
        with __import__('contextlib').suppress(RuntimeError): loop.call_soon_threadsafe(deliver)
    future.add_done_callback(complete)
    return await result


class Goal:
    def __init__(self, handle):
        self.handle = handle
        self.result_future = handle.get_result_async()

    async def result(self):
        response = await ros_future(self.result_future)
        if response.status != 4:
            raise RuntimeError(f'Nav2: цель не достигнута (статус {response.status}, код {getattr(response.result,"error_code",None)})')

    async def cancel(self):
        # A goal that has already finished cannot resume motion.
        if self.result_future.done(): return
        response = await ros_future(self.handle.cancel_goal_async())
        if not response.goals_canceling and not self.result_future.done():
            raise RuntimeError('Nav2 не подтвердил отмену цели')
        await ros_future(self.result_future)


class Bridge:
    def __init__(self, config, mock, robot_ip=None):
        self.node, self.error, self.executor = None, None, None
        self.mock = mock
        self.telemetry = Telemetry()
        self.client_id = uuid.uuid4().hex
        self.own_goals = set()
        self.active_status = set()
        self.status_time = 0.
        self.last_scan = 0.
        self.nav_states = {}
        self.state_pending = {}
        self.mock_guard = None
        if mock: return
        try:
            os.environ['ROS_DOMAIN_ID'] = str(config.network.domain_id)
            os.environ['RMW_IMPLEMENTATION'] = config.network.rmw
            if config.network.rmw == 'rmw_cyclonedds_cpp' and robot_ip:
                uri = configure_cyclonedds(robot_ip)
                if uri: os.environ['CYCLONEDDS_URI'] = uri
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.action import ActionClient
            from rclpy.qos import qos_profile_sensor_data
            from std_msgs.msg import String
            from geometry_msgs.msg import Twist, PoseWithCovarianceStamped
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import LaserScan
            from diagnostic_msgs.msg import DiagnosticArray
            from action_msgs.msg import GoalStatusArray
            from action_msgs.srv import CancelGoal
            from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
            from nav2_msgs.action import NavigateToPose
            from lifecycle_msgs.srv import GetState
            from tf2_ros import Buffer, TransformListener
            self.rclpy, self.String, self.Twist, self.Action = rclpy, String, Twist, NavigateToPose
            self.context = Context()
            rclpy.init(args=[], context=self.context)
            self.node = rclpy.create_node('ijk_web_bridge', context=self.context)
            self.joy = self.node.create_publisher(Twist, '/cmd_vel_joy', 10)
            self.emergency = self.node.create_publisher(Twist, '/cmd_vel_emergency', 10)
            self.lease_pub = self.node.create_publisher(String, '/ijk/web/lease', 10)
            self.probe_pub = self.node.create_publisher(String, '/ijk/web/probe', 10)
            self.tf = Buffer(node=self.node)
            self.listener = TransformListener(self.tf, self.node, spin_thread=False)
            self.action = ActionClient(self.node, NavigateToPose, '/navigate_to_pose')
            self.CancelGoal=CancelGoal
            self.cancel_all=self.node.create_client(CancelGoal,'/navigate_to_pose/_action/cancel_goal')
            self.node.create_subscription(Odometry, '/odom', self.odom, qos_profile_sensor_data)
            self.node.create_subscription(LaserScan, '/scan', self.scan, qos_profile_sensor_data)
            self.node.create_subscription(DiagnosticArray, '/diagnostics', self.diagnostics, 10)
            self.node.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', lambda m:self.telemetry.put('amcl',{'received':True}), qos_profile_sensor_data)
            for topic,key in [('/ijk/system','system'),('/ijk/web/guard','guard')]:
                self.node.create_subscription(String,topic,lambda m,k=key:self.json_message(k,m),10)
            self.node.create_subscription(String, '/ijk/web/echo', self.echo, 10)
            self.node.create_subscription(GoalStatusArray, '/navigate_to_pose/_action/status', self.action_status, QoSProfile(depth=10,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE))
            self.state_clients = {name:self.node.create_client(GetState,f'/{name}/get_state') for name in ('amcl','bt_navigator')}
            self.GetState = GetState
            self.node.create_timer(.1,self.pose)
            self.node.create_timer(1.,self.lifecycle)
            self.executor = SingleThreadedExecutor(context=self.context)
            self.executor.add_node(self.node)
            self.thread = threading.Thread(target=self.executor.spin,daemon=True,name='ijk-web-ros')
            self.thread.start()
        except Exception as exc:
            self.error = str(exc)
            self.close()

    def publish(self,v=0.,w=0.,emergency=False):
        if self.node and not self.error:
            message = self.Twist()
            message.linear.x, message.angular.z = float(v), float(w)
            (self.emergency if emergency else self.joy).publish(message)

    def lease(self,kind,token,seq):
        if self.mock:
            previous = self.mock_guard or {'state':'disarmed','token':None}
            if kind=='stop': self.mock_guard={**previous,'state':'latched','reason':'E-STOP'}
            elif kind=='arm' and token!=previous.get('token'):
                self.mock_guard={'state':'armed','token':token,'reason':'Mock lease'}
            elif previous.get('token')==token and previous.get('state')=='armed' and kind=='disarm':
                self.mock_guard={**previous,'state':'disarmed'}
            if self.mock_guard: self.telemetry.put('guard',self.mock_guard.copy())
        elif self.node and not self.error:
            self.lease_pub.publish(self.String(data=json.dumps({'type':kind,'token':token,'seq':seq})))

    def probe(self,seq):
        self.telemetry.probe(seq)
        if self.node and not self.error:
            self.probe_pub.publish(self.String(data=json.dumps({'seq':seq,'client':self.client_id})))

    def echo(self,msg):
        try:
            data=json.loads(msg.data)
            if data.get('client')==self.client_id and type(data.get('seq')) is int: self.telemetry.echo(data['seq'])
        except (ValueError,AttributeError): pass

    def json_message(self,key,msg):
        try:
            data=json.loads(msg.data)
            if isinstance(data,dict): self.telemetry.put(key,data)
        except ValueError: pass

    def header_age(self,header,maximum):
        from rclpy.time import Time
        age=(self.node.get_clock().now().nanoseconds-Time.from_msg(header.stamp).nanoseconds)/1e9
        return max(0,age) if -.5<=age<=maximum else None

    def odom(self,msg):
        v,w=msg.twist.twist.linear.x,msg.twist.twist.angular.z
        age=self.header_age(msg.header,1.)
        if age is not None and math.isfinite(v) and math.isfinite(w): self.telemetry.put('odom',{'v':v,'w':w},age)

    def diagnostics(self,msg):
        age=self.header_age(msg.header,3.)
        if age is None:return
        # Preserve diagnostics from all publishers instead of letting mux hide drive status.
        with self.telemetry.lock:
            old=self.telemetry.samples.get('diagnostics',{}).get('value') or {}
            data={k:v for k,v in old.items() if time.monotonic()-v['received']<15}
            for item in msg.status:
                level=item.level if isinstance(item.level,int) else item.level[0]
                data[item.name]={'level':level,'message':item.message,'values':{v.key:v.value for v in item.values},'received':time.monotonic()-age}
            self.telemetry.put('diagnostics',data,age)

    def pose(self):
        try:
            from rclpy.time import Time
            transform=self.tf.lookup_transform('map','base_footprint',Time())
            age=(self.node.get_clock().now().nanoseconds-Time.from_msg(transform.header.stamp).nanoseconds)/1e9
            if age>1.5 or age < -.5: return
            p,q=transform.transform.translation,transform.transform.rotation
            if not all(math.isfinite(v) for v in (p.x,p.y,p.z,q.x,q.y,q.z,q.w)) or abs(sum(v*v for v in (q.x,q.y,q.z,q.w))-1)>.01:return
            self.telemetry.put('pose',{'x':p.x,'y':p.y,'yaw':math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))},max(0,age))
        except Exception: pass

    def scan(self,msg):
        if time.monotonic()-self.last_scan<.1: return
        self.last_scan=time.monotonic()
        age=self.header_age(msg.header,1.)
        if age is None:return
        try:
            from rclpy.time import Time
            t=self.tf.lookup_transform('base_footprint',msg.header.frame_id,Time.from_msg(msg.header.stamp)).transform
            points=radar_points(msg.ranges,msg.range_min,msg.range_max,msg.angle_min,msg.angle_increment,
                (t.translation.x,t.translation.y,t.translation.z),(t.rotation.x,t.rotation.y,t.rotation.z,t.rotation.w))
            self.telemetry.put('scan',{'points':points,'nearest_m':min((math.hypot(*p) for p in points),default=None),'frame':'base_footprint'},age)
        except Exception:
            # No untransformed points: drawing mirrored/raw data would mislead the operator.
            pass

    def lifecycle(self):
        for name,client in self.state_clients.items():
            pending=self.state_pending.get(name)
            if pending:
                if time.monotonic()-pending[0]<2:continue
                client.remove_pending_request(pending[1])
                self.state_pending.pop(name,None)
            if not client.service_is_ready():continue
            future=client.call_async(self.GetState.Request())
            self.state_pending[name]=(time.monotonic(),future)
            def done(f,n=name):
                if self.state_pending.get(n,(None,None))[1] is not f:return
                self.state_pending.pop(n,None)
                try: self.nav_states[n]=(f.result().current_state.id==3,time.monotonic())
                except Exception: self.nav_states.pop(n,None)
            future.add_done_callback(done)
        old=self.telemetry.snapshot()['topics']['nav']['data'] or {}
        self.telemetry.put('nav',{'ready':self.action.server_is_ready(),
            'amcl_active':self.nav_states.get('amcl',(False,0))[0] and time.monotonic()-self.nav_states.get('amcl',(False,0))[1]<3,
            'navigator_active':self.nav_states.get('bt_navigator',(False,0))[0] and time.monotonic()-self.nav_states.get('bt_navigator',(False,0))[1]<3,
            'external_goal':old.get('external_goal',False)})

    def action_status(self,msg):
        self.status_time=time.monotonic()
        self.active_status={bytes(item.goal_info.goal_id.uuid) for item in msg.status_list if item.status in (1,2,3)}
        old=self.telemetry.snapshot()['topics']['nav']['data'] or {}
        old['external_goal']=any(bytes(item.goal_info.goal_id.uuid) not in self.own_goals and item.status in (1,2,3) for item in msg.status_list)
        self.telemetry.put('nav',old)
        # Result and status use separate DDS streams. Keep ownership until the
        # terminal status arrives so an older active status cannot look external.
        for item in msg.status_list:
            if item.status in (4,5,6):self.own_goals.discard(bytes(item.goal_info.goal_id.uuid))

    async def cancel_all_goals(self):
        """Explicit recovery first stops any goals left behind by a lost web session."""
        if self.mock:return
        if not self.node or not self.cancel_all.service_is_ready():
            raise RuntimeError('Не удаётся подтвердить отмену старой цели Nav2. Остановите и заново запустите профиль.')
        started=time.monotonic()
        result=await asyncio.wait_for(ros_future(self.cancel_all.call_async(self.CancelGoal.Request())),3)
        if result.return_code!=0:raise RuntimeError('Nav2 отказал в отмене старой цели')
        deadline=time.monotonic()+3
        while self.active_status or (result.goals_canceling and self.status_time<started):
            if time.monotonic()>deadline:raise RuntimeError('Nav2 ещё не завершил старую цель; управление остаётся заблокированным')
            await asyncio.sleep(.05)

    async def send_goal(self,pose,feedback):
        if not self.node or self.error: raise RuntimeError('ROS ActionClient недоступен')
        from unique_identifier_msgs.msg import UUID
        goal=self.Action.Goal()
        goal.pose.header.frame_id='map'
        goal.pose.header.stamp=self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x,goal.pose.pose.position.y=float(pose['x']),float(pose['y'])
        goal.pose.pose.orientation.z=math.sin(pose['yaw']/2)
        goal.pose.pose.orientation.w=math.cos(pose['yaw']/2)
        identifier=uuid.uuid4().bytes
        self.own_goals.add(identifier)
        loop=asyncio.get_running_loop()
        def report(msg):
            value=msg.feedback.distance_remaining
            if math.isfinite(value): loop.call_soon_threadsafe(feedback,float(value))
        try:
            handle=await ros_future(self.action.send_goal_async(goal,feedback_callback=report,goal_uuid=UUID(uuid=list(identifier))))
            if not handle.accepted: raise RuntimeError('Nav2 отклонил цель')
            wrapped=Goal(handle)
            return wrapped
        except Exception:
            self.own_goals.discard(identifier)
            raise

    def close(self):
        if self.executor:
            self.executor.shutdown(timeout_sec=3)
            if hasattr(self,'thread'): self.thread.join(timeout=3)
        # Node.destroy_node does not destroy ActionClient waitables. Leaving one
        # alive retains a DDS participant and its old network interface when the
        # bridge is recreated after discovery on a different network.
        if hasattr(self,'action'):
            self.action.destroy()
            del self.action
        if hasattr(self,'listener'):
            self.listener.unregister()
            del self.listener
        if self.node:
            self.node.destroy_node()
            self.node=None
        if hasattr(self,'context') and self.context.ok(): self.context.shutdown()
