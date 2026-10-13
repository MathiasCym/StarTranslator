"""Nonblocking, per-configuration connection probes for the status indicator."""
import hashlib
import threading
import time


class ConnectionProbe:
    def __init__(self, interval=1.0, stale_after=20.0):
        self.interval = interval
        self.stale_after = stale_after
        self.lock = threading.Lock()
        self.key = None
        self.value = None
        self.finished = 0.0
        self.active = None

    def get(self, client):
        key = (client.provider, client.base_url, client.model,
               hashlib.sha256(client.api_key.encode('utf-8')).digest())
        now = time.monotonic()
        with self.lock:
            if key != self.key:
                self.key, self.value, self.finished = key, None, 0.0
            if self.value is None or (self.active and now - self.finished > self.stale_after):
                result = {'state': 'unknown', 'message': '正在检测模型连接',
                          'detail': '正在检测当前配置的接口，请稍候。', 'model': client.model}
            else:
                result = dict(self.value)
            if self.active is None and now - self.finished >= self.interval:
                token = object()
                self.active = token
                threading.Thread(target=self._run, args=(client, key, token), daemon=True).start()
            return result

    def _run(self, client, key, token):
        try:
            result = client.connection_status()
        except Exception:
            result = {'state': 'unavailable', 'message': '模型连接检测失败',
                      'detail': '当前接口未能完成检测，将自动重试。', 'model': client.model}
        with self.lock:
            if key == self.key:
                self.value, self.finished = result, time.monotonic()
            if self.active is token:
                self.active = None


connection_probe = ConnectionProbe()
