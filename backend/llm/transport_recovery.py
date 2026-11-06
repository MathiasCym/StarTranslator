"""One shared, cancellable cooldown and recovery probe for every language."""
import threading
import time


class TransportStopped(Exception):
    def __init__(self,epoch,cancelled=False):self.epoch,self.cancelled=epoch,cancelled


class RecoveryGate:
    def __init__(self,cooldown=15):
        self.cooldown=cooldown;self.condition=threading.Condition()
        self.failures=0;self.until=0;self.owner=None;self.epoch=0

    def before(self,cancel=None,notify=None):
        notified=False;identity=threading.get_ident()
        with self.condition:
            while self.failures:
                if cancel and cancel.is_set():raise TransportStopped(self.epoch,True)
                if self.failures>=2:raise TransportStopped(self.epoch)
                remaining=self.until-time.monotonic()
                if self.owner==identity:return
                if self.owner is None and remaining<=0:self.owner=identity;return
                if not notified and notify:
                    notify('模型连接中断，正在等待恢复；已完成译文已保留')
                    notified=True
                self.condition.wait(min(.2,max(.01,remaining)) if remaining>0 else .2)
            if cancel and cancel.is_set():raise TransportStopped(self.epoch,True)

    def success(self):
        with self.condition:
            self.epoch+=1;self.failures=0;self.until=0;self.owner=None;self.condition.notify_all()

    def failure(self):
        with self.condition:
            identity=threading.get_ident()
            if not self.failures:self.failures=1;self.until=time.monotonic()+self.cooldown
            elif self.owner==identity:self.failures=2
            if self.owner==identity:self.owner=None
            self.condition.notify_all();return self.epoch

    def release(self):
        with self.condition:
            if self.owner==threading.get_ident():self.owner=None;self.condition.notify_all()

    def recovered(self,epoch):
        with self.condition:return self.epoch>epoch and self.failures==0

    def may_recover(self,epoch):
        with self.condition:return self.failures<2 and epoch<=self.epoch
