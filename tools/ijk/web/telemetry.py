"""Bounded, monotonic telemetry snapshots and DDS link statistics."""
from collections import deque
import copy
import math
import statistics
import threading
import time


class Telemetry:
    limits = {'odom':1., 'scan':1., 'pose':1., 'diagnostics':3., 'system':3., 'guard':1., 'nav':2.5, 'amcl':None}

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.samples = {}
        self.sent = {}
        self.replies = {}
        self.last_echo = None

    def put(self, name, value, age_s=0.):
        with self.lock:
            now = self.clock()
            item = self.samples.setdefault(name, {'times':deque(maxlen=500), 'value':None, 'last':now})
            item['times'].append(now)
            item['value'], item['last'] = value, now-max(0,age_s)

    def probe(self, seq):
        with self.lock:
            self.sent[seq] = self.clock()
            self._prune()

    def echo(self, seq):
        with self.lock:
            if seq in self.sent and seq not in self.replies:
                self.replies[seq] = max(0, (self.clock()-self.sent[seq])*1000)
                self.last_echo = self.clock()

    def _prune(self):
        cutoff = self.clock()-30
        for seq in list(self.sent):
            if self.sent[seq] < cutoff:
                del self.sent[seq]
                self.replies.pop(seq, None)

    def snapshot(self):
        with self.lock:
            self._prune()
            now = self.clock()
            samples = {}
            for name, threshold in self.limits.items():
                item = self.samples.get(name)
                times = [t for t in item['times'] if now-t <= 5] if item else []
                age = now-item['last'] if item else None
                samples[name] = {'data':copy.deepcopy(item['value']) if item else None, 'age_s':age,
                    'stale':age is None or (threshold is not None and age>threshold),
                    'hz':(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else None}
            mature = [seq for seq,t in self.sent.items() if now-t>=.5]
            rtts = [rtt for seq,rtt in self.replies.items() if seq in self.sent]
            ordered = sorted(rtts)
            link = {'samples':len(mature), 'received':sum(seq in self.replies for seq in mature),
                'missing_percent':100*sum(seq not in self.replies for seq in mature)/len(mature) if mature else None,
                'rtt_p50_ms':statistics.median(rtts) if rtts else None,
                'rtt_p95_ms':ordered[min(len(ordered)-1, math.ceil(len(ordered)*.95)-1)] if ordered else None,
                'jitter_ms':statistics.mean(abs(b-a) for a,b in zip(rtts,rtts[1:])) if len(rtts)>1 else None,
                'echo_age_s':None if self.last_echo is None else now-self.last_echo, 'window_s':30}
            return {'topics':samples, 'link':link}


def radar_points(ranges, minimum, maximum, angle_min, angle_step, translation, quaternion):
    """Transform a horizontal scan in full 3D before projecting into base XY."""
    if not all(math.isfinite(v) for v in (minimum,maximum,angle_min,angle_step)) or minimum>maximum:return []
    qx,qy,qz,qw = quaternion
    norm = math.sqrt(sum(v*v for v in quaternion))
    if not norm or not all(math.isfinite(v) for v in (*translation,*quaternion)): return []
    qx,qy,qz,qw = (v/norm for v in quaternion)
    r00, r01 = 1-2*(qy*qy+qz*qz), 2*(qx*qy-qz*qw)
    r10, r11 = 2*(qx*qy+qz*qw), 1-2*(qx*qx+qz*qz)
    stride = max(1, math.ceil(len(ranges)/360))
    points = []
    for i in range(0,len(ranges),stride):
        distance = ranges[i]
        if not math.isfinite(distance) or distance<minimum or distance>maximum: continue
        angle = angle_min+i*angle_step
        x,y = distance*math.cos(angle),distance*math.sin(angle)
        points.append([translation[0]+r00*x+r01*y, translation[1]+r10*x+r11*y])
    return points
