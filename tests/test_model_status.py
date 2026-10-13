"""轻量连接检测回归测试；不会访问真实模型或消耗生成额度。"""
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.llm.client import LLMClient
from backend.server import app


def models_response(models):
    return io.BytesIO(json.dumps({"data": models}).encode("utf-8"))


class ModelStatusTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = LLMClient(provider="compatible", base_url="http://127.0.0.1:8080/v1", model="test-model")

    def test_probe_only_gets_model_list_without_generating(self):
        with patch("backend.llm.client._urlopen", return_value=models_response([{"id": "test-model"}])) as send, \
             patch.object(self.client, "chat") as chat:
            result = self.client.connection_status()
        self.assertEqual(result["state"], "connected")
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://127.0.0.1:8080/v1/models")
        self.assertIsNone(request.data)
        self.assertEqual(send.call_args.kwargs["timeout"], 1.5)
        chat.assert_not_called()

    def test_available_service_but_missing_model_is_not_green(self):
        with patch("backend.llm.client._urlopen", return_value=models_response([{"id": "another-model"}])):
            self.assertEqual(self.client.connection_status()["state"], "unavailable")

    def test_model_loading_and_sleeping_are_not_green(self):
        for value in ["loading", "downloading", "unloaded", "sleeping"]:
            with self.subTest(value=value), patch("backend.llm.client._urlopen", return_value=models_response([
                {"id": "test-model", "status": {"value": value}},
            ])):
                self.assertEqual(self.client.connection_status()["state"], "unknown")
        with patch("backend.llm.client._urlopen", return_value=models_response([
            {"id": "test-model", "status": {"value": "loaded"}},
        ])):
            self.assertEqual(self.client.connection_status()["state"], "connected")

    def test_timeout_is_short_and_not_retried(self):
        with patch("backend.llm.client._urlopen", side_effect=TimeoutError()) as send, patch("time.sleep") as sleep:
            result = self.client.connection_status()
        self.assertEqual(result["state"], "unavailable")
        self.assertIn("超时", result["message"])
        self.assertEqual(send.call_count, 1)
        sleep.assert_not_called()

    def test_unsupported_endpoint_is_unknown_and_not_inference_fallback(self):
        for code in [404, 405]:
            error = urllib.error.HTTPError("http://localhost", code, "unsupported", {}, io.BytesIO())
            with self.subTest(code=code), patch("backend.llm.client._urlopen", side_effect=error), patch.object(self.client, "chat") as chat:
                self.assertEqual(self.client.connection_status()["state"], "unknown")
                chat.assert_not_called()

    def test_authorization_failure_does_not_echo_private_content(self):
        error = urllib.error.HTTPError("http://localhost", 401, "secret", {}, io.BytesIO(b"secret"))
        with patch("backend.llm.client._urlopen", side_effect=error):
            result = self.client.connection_status()
        self.assertEqual(result["state"], "unavailable")
        self.assertIn("授权", result["detail"])
        self.assertNotIn("secret", json.dumps(result))

    def test_invalid_json_does_not_turn_light_green(self):
        with patch("backend.llm.client._urlopen", return_value=io.BytesIO(b"<html>error</html>")):
            self.assertEqual(self.client.connection_status()["state"], "unknown")

    def test_config_error_and_recovery(self):
        client = LLMClient(provider="deepseek", api_key="")
        with patch("backend.llm.client._urlopen") as send:
            self.assertEqual(client.connection_status()["state"], "unavailable")
        send.assert_not_called()
        with patch("backend.llm.client._urlopen", side_effect=urllib.error.URLError("offline")):
            self.assertEqual(self.client.connection_status()["state"], "unavailable")
        with patch("backend.llm.client._urlopen", return_value=models_response([{"id": "test-model"}])):
            self.assertEqual(self.client.connection_status()["state"], "connected")

    def test_backend_health_uses_probe_not_generation(self):
        status = {"state": "unavailable", "message": "模型未连接", "detail": "offline", "model": "test-model"}
        with patch("backend.server.LLMClient") as client, patch("backend.server.connection_probe.get", return_value=status) as probe:
            result = app.test_client().get("/api/health")
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json["llm_available"])
        self.assertEqual(result.json["model_status"], status)
        client.return_value.health.assert_not_called()
        client.return_value.connection_status.assert_not_called()
        probe.assert_called_once_with(client.return_value)

    def test_external_probe_allows_tls_and_proxy_latency(self):
        client = LLMClient(provider='compatible', base_url='https://api.deepseek.com', model='deepseek-flash', api_key='test-only')
        with patch('backend.llm.client._urlopen', return_value=models_response([{'id':'deepseek-flash'}])) as send:
            self.assertEqual(client.connection_status()['state'], 'connected')
        self.assertEqual(send.call_args.kwargs['timeout'], 8.0)
        self.assertEqual(send.call_args.args[0].full_url, 'https://api.deepseek.com/models')

    def test_proxy_is_refreshed_and_local_services_bypass_it(self):
        from backend.llm.client import _urlopen
        import urllib.request
        with patch('urllib.request.ProxyHandler') as handler, patch('urllib.request.build_opener') as build:
            _urlopen(urllib.request.Request('https://api.deepseek.com/models'), 8)
            handler.assert_called_with(None)
            _urlopen(urllib.request.Request('http://127.0.0.1:11434/v1/models'), 1.5)
            handler.assert_called_with({})
            _urlopen(urllib.request.Request('https://api.deepseek.com/models'), 8)
            self.assertEqual(build.call_count, 3)


class BackgroundProbeTests(unittest.TestCase):
    def test_slow_probe_does_not_block_and_config_change_drops_old_result(self):
        import threading
        import time
        from types import SimpleNamespace
        from backend.model_connection import ConnectionProbe
        probe = ConnectionProbe(interval=0)
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set(); release.wait(2)
            return {'state':'unavailable','message':'old offline','model':'old'}
        old = SimpleNamespace(provider='intranet',base_url='http://llm.novastar.tech:31000/v1',model='old',api_key='fake',connection_status=slow)
        new = SimpleNamespace(provider='compatible',base_url='https://api.deepseek.com',model='new',api_key='fake',connection_status=lambda:{'state':'connected','message':'new online','model':'new'})
        before = time.monotonic()
        self.assertEqual(probe.get(old)['state'], 'unknown')
        self.assertLess(time.monotonic()-before, .2)
        self.assertTrue(entered.wait(1))
        for _ in range(10): self.assertEqual(probe.get(new)['state'], 'unknown')
        release.set()
        for _ in range(100):
            value = probe.get(new)
            self.assertNotEqual(value.get('message'), 'old offline')
            if value['state']=='connected': break
            time.sleep(.01)
        self.assertEqual(value['state'], 'connected')


if __name__ == "__main__":
    unittest.main()
