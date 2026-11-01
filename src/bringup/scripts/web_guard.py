"""Monotonic, latched lease for web control. No ROS dependency in the state machine."""
import time
import re


class WebGuard:
    def __init__(self, clock=time.monotonic, timeout=.5):
        self.clock, self.timeout = clock, timeout
        self.token = None
        self.seq = -1
        self.last = None
        self.state = 'disarmed'
        self.retired = set()
        self.reason = 'Веб-управление не включено'

    def restore(self, data):
        """A process restart must never revive a previously armed web session."""
        if data.get('state') in ('armed','latched'):
            self.token=data.get('token')
            self.seq=data.get('seq',-1)
            self.state,self.reason='latched','Узел контроля перезапущен; требуется явное восстановление'

    def receive(self, data):
        kind, token, seq = data.get('type'), data.get('token'), data.get('seq')
        if kind == 'stop':
            self.state, self.reason = 'latched', 'Аварийная остановка'
            return
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token) or type(seq) is not int or seq < 0:
            return
        self.tick()
        if kind == 'arm' and token != self.token and token not in self.retired:
            if self.token: self.retired.add(self.token)
            self.token, self.seq = token, seq
            self.state, self.reason, self.last = 'armed', 'Управляющая сессия активна', self.clock()
        elif token == self.token and seq > self.seq and self.state == 'armed':
            if kind in ('heartbeat', 'arm'):
                self.seq, self.last = seq, self.clock()
            elif kind == 'disarm':
                self.retired.add(token)
                self.state, self.reason = 'disarmed', 'Управление освобождено'
                self.seq = seq

    def tick(self):
        if self.state == 'armed' and self.clock() - self.last > self.timeout:
            self.state, self.reason = 'latched', 'Потеря управляющей связи (>0,5 с)'
        return self.state == 'latched'

    def snapshot(self):
        self.tick()
        return {'state': self.state, 'token': self.token, 'reason': self.reason,
                'age_s': None if self.last is None else self.clock() - self.last}
