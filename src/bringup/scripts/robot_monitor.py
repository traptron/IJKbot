#!/usr/bin/env python3
"""Onboard web-control lease, DDS echo and read-only Pi system telemetry."""
import json
import os
import tempfile
import uuid
from pathlib import Path
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist
from web_guard import WebGuard


def read_system(previous=None):
    values = {'cpu_temp_c': None, 'cpu_percent': None, 'memory_available_mb': None,
              'memory_total_mb': None, 'wifi_dbm': None}
    cpu = None
    try: values['cpu_temp_c'] = float(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
    except (OSError, ValueError): pass
    try:
        fields = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        cpu = (sum(fields), fields[3] + fields[4])
        if previous and cpu[0] > previous[0]:
            values['cpu_percent'] = max(0, min(100, 100*(1-(cpu[1]-previous[1])/(cpu[0]-previous[0]))))
    except (OSError, ValueError, IndexError): pass
    try:
        mem = {line.split(':')[0]: int(line.split()[1])/1024 for line in Path('/proc/meminfo').read_text().splitlines()}
        values['memory_available_mb'], values['memory_total_mb'] = mem.get('MemAvailable'), mem.get('MemTotal')
    except (OSError, ValueError, IndexError): pass
    try:
        for line in Path('/proc/net/wireless').read_text().splitlines()[2:]:
            fields = line.split()
            level = float(fields[3].rstrip('.'))
            if -150 <= level < 0: values['wifi_dbm'] = level
    except (OSError, ValueError, IndexError): pass
    return values, cpu


class RobotMonitor(Node):
    def __init__(self):
        super().__init__('ijk_robot_monitor')
        self.guard = WebGuard()
        session=self.declare_parameter('launch_session','').value or uuid.uuid4().hex
        if not isinstance(session,str) or not __import__('re').fullmatch('[a-f0-9]{32}',session):
            raise ValueError('Invalid monitor launch session')
        self.state_file=Path(tempfile.gettempdir())/f'ijk-guard-{os.getuid()}-{session}.json'
        try:self.guard.restore(json.loads(self.state_file.read_text()))
        except FileNotFoundError:pass
        except (OSError,ValueError,AttributeError):self.guard.receive({'type':'stop'})
        self.persisted=None
        self.previous_cpu = None
        self.echo = self.create_publisher(String, '/ijk/web/echo', 10)
        self.guard_pub = self.create_publisher(String, '/ijk/web/guard', 10)
        self.system = self.create_publisher(String, '/ijk/system', 10)
        self.zero = self.create_publisher(Twist, '/cmd_vel_emergency', 10)
        self.velocity = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_subscription(Twist, '/cmd_vel_mux', self.forward, 10)
        self.create_subscription(String, '/ijk/web/lease', self.lease, 10)
        self.create_subscription(String, '/ijk/web/probe', self.probe, 10)
        self.create_timer(.05, self.tick)
        self.create_timer(1., self.metrics)
        self.last_state = None

    def lease(self, msg):
        try:
            data = json.loads(msg.data)
            if isinstance(data, dict):
                self.guard.receive(data)
                self.persist()
        except (ValueError, TypeError): pass

    def persist(self):
        value={'state':self.guard.state,'token':self.guard.token}
        if value==self.persisted:return
        path=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',dir=self.state_file.parent,prefix='.ijk-guard-',delete=False) as output:
                path=Path(output.name);json.dump(value,output);output.flush();os.fsync(output.fileno())
            os.replace(path,self.state_file);self.persisted=value
        except OSError as exc:
            self.guard.receive({'type':'stop'})
            self.get_logger().error('Guard state persistence failed: '+str(exc))
        finally:
            if path and path.exists():path.unlink()

    def forward(self, msg):
        # The driver receives no stale commands if this relay dies: its own 200 ms watchdog stops it.
        self.velocity.publish(Twist() if self.guard.tick() else msg)

    def probe(self, msg):
        try:
            data = json.loads(msg.data)
            if isinstance(data, dict) and type(data.get('seq')) is int and isinstance(data.get('client'), str):
                self.echo.publish(String(data=json.dumps({'seq': data['seq'], 'client': data['client']})))
        except (ValueError, TypeError): pass

    def tick(self):
        if self.guard.tick():
            self.zero.publish(Twist())
            self.velocity.publish(Twist())
        self.persist()
        state = self.guard.snapshot()
        if state['state'] != self.last_state:
            self.get_logger().info(f"Web guard: {state['state']}: {state['reason']}")
            self.last_state = state['state']
        self.guard_pub.publish(String(data=json.dumps(state)))

    def metrics(self):
        values, self.previous_cpu = read_system(self.previous_cpu)
        self.system.publish(String(data=json.dumps(values, allow_nan=False)))


def main():
    rclpy.init()
    node = RobotMonitor()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally:
        if rclpy.ok() and node.guard.state != 'disarmed':
            node.zero.publish(Twist());node.velocity.publish(Twist())
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()
