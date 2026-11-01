"""One asynchronous waypoint task. Pending acceptance is never abandoned on cancellation."""
import asyncio
import copy
import time
import uuid


class Navigation:
    def __init__(self,bridge,log):
        self.bridge,self.log=bridge,log
        self.task=None
        self.goal=None
        self.pending=None
        self.intent=None
        self.state='idle'
        self.points=[]
        self.index=0
        self.error=None
        self.distance=None
        self.map_id=None
        self.fingerprint=None
        self.label=''
        self.cancel_uncertain=False
        self.wait_remaining=0.

    def snapshot(self):
        return {'state':self.state,'index':self.index,'total':len(self.points),'label':self.label,
                'point':self.points[self.index].get('label','') if self.index<len(self.points) else None,
                'distance_remaining_m':self.distance,'error':self.error,'map_id':self.map_id,
                'points':copy.deepcopy(self.points),
                'pending':bool(self.pending and not self.pending.done()),'cancel_uncertain':self.cancel_uncertain}

    def busy(self): return self.state in ('running','waiting','pausing','cancelling') or bool(self.task and not self.task.done())

    async def start(self,map_id,fingerprint,points,label):
        if self.busy() or self.cancel_uncertain: raise ValueError('Предыдущая цель ещё не завершена или её отмена не подтверждена')
        self.map_id,self.fingerprint,self.points,self.label=map_id,fingerprint,copy.deepcopy(points),label
        self.index,self.error,self.distance,self.wait_remaining=0,None,None,0.
        await self.resume()

    async def resume(self):
        if self.busy() or self.cancel_uncertain: raise ValueError('Дождитесь подтверждения отмены прежней цели')
        if self.index>=len(self.points): raise ValueError('Маршрут завершён или не выбран')
        self.intent,self.error,self.state=None,None,'running'
        self.task=asyncio.create_task(self.run())

    async def interrupt(self,kind='paused',reason=None):
        if self.state in ('idle','complete','cancelled','failed') and not self.busy(): return
        self.intent=kind
        if reason: self.error=reason
        self.state='pausing' if kind=='paused' else 'cancelling'
        # Wait briefly, but keep the worker alive if goal acceptance is delayed.
        if self.task:
            try: await asyncio.wait_for(asyncio.shield(self.task),2)
            except asyncio.TimeoutError: pass

    def feedback(self,distance): self.distance=distance

    async def run(self):
        try:
            while self.index<len(self.points):
                if not self.wait_remaining:
                    self.state='running'
                    self.pending=asyncio.create_task(self.bridge.send_goal(self.points[self.index],self.feedback))
                    started=time.monotonic()
                    while not self.pending.done():
                        if time.monotonic()-started>10 and not self.intent:
                            self.intent='failed';self.error='Тайм-аут принятия цели; ожидается безопасная отмена'
                        if self.intent: self.state='pausing' if self.intent=='paused' else 'cancelling'
                        await asyncio.sleep(.05)
                    self.goal=await self.pending
                    self.pending=None
                    result=asyncio.create_task(self.goal.result())
                    try:
                        deadline=time.monotonic()+300
                        while not result.done() and not self.intent:
                            if time.monotonic()>deadline:
                                self.intent='failed';self.error='Превышено время движения к точке (300 с)'
                            await asyncio.sleep(.05)
                        if self.intent:
                            try: await asyncio.wait_for(self.goal.cancel(),5)
                            except Exception as exc:
                                self.cancel_uncertain=True
                                raise RuntimeError('Отмена Nav2 не подтверждена: '+str(exc))
                            return
                        await result
                    finally:
                        if not result.done(): result.cancel()
                        try: await result
                        except (Exception,asyncio.CancelledError): pass
                    self.goal=None
                    self.wait_remaining=self.points[self.index].get('wait_s',0)
                self.state='waiting'
                while self.wait_remaining>0 and not self.intent:
                    before=time.monotonic();await asyncio.sleep(min(.1,self.wait_remaining))
                    self.wait_remaining=max(0,self.wait_remaining-(time.monotonic()-before))
                if self.intent:return
                self.index+=1;self.distance=None
            self.state='complete'
            await self.log('Маршрут завершён: '+self.label)
        except asyncio.CancelledError:
            # Shutdown does not release the onboard guard. Late acceptance must still be cancelled.
            if self.goal:
                try: await self.goal.cancel()
                except Exception: self.cancel_uncertain=True
            raise
        except Exception as exc:
            self.state='failed';self.error=str(exc)
            await self.log('Ошибка навигации: '+self.error)
        finally:
            if self.intent and not self.cancel_uncertain:self.state=self.intent
            if self.state in ('paused','cancelled','failed'): await self.log(f'Навигация: {self.state}: {self.error or "команда оператора"}')
            if not self.cancel_uncertain:self.goal=None

    async def retry_cancel(self):
        if self.task and not self.task.done():raise ValueError('Цель ещё ожидает принятия')
        if not self.cancel_uncertain:return
        if self.goal is None:raise ValueError('Нет дескриптора старой цели; требуется перезапуск Nav2')
        try:await asyncio.wait_for(self.goal.cancel(),5)
        except Exception as exc:raise ValueError('Отмена по-прежнему не подтверждена: '+str(exc))
        self.cancel_uncertain=False;self.goal=None;self.intent='cancelled';self.state='cancelled';self.error=None

    async def close(self):
        await self.interrupt('cancelled','Завершение веб-пульта')
        if self.task and not self.task.done():
            # Keep pending acceptance observable until ROS executor shuts down. No disarm is sent.
            return
