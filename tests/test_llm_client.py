"""不联网的模型接入回归测试：协议、凭据隔离和失败处理。"""
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.llm.client import LLMClient, LLMUnavailable, _extract_json
from backend.glossary import Glossary
from backend.matcher.judge import judge_text, judge_segments
from backend.models import Segment
from backend.server import app


def response(content="[]", finish_reason="stop"):
    return io.BytesIO(json.dumps({"choices": [{
        "message": {"content": content}, "finish_reason": finish_reason,
    }]}).encode("utf-8"))


class ModelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.environ = patch.dict(os.environ, {}, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.legacy = patch("backend.llm.client._load_api_key", return_value="company-test-secret").start()
        self.addCleanup(patch.stopall)

    def test_legacy_connection_is_preserved(self):
        client = LLMClient()
        with patch("backend.llm.client._urlopen", return_value=response()) as send:
            self.assertEqual(client.chat_json("test"), [])
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "http://llm.novastar.tech:31000/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer company-test-secret")
        self.assertEqual(json.loads(request.data)["chat_template_kwargs"], {"enable_thinking": False})

    def test_official_providers_use_separate_keys_and_correct_payloads(self):
        for provider, key_name, extra in [
            ("qwen", "DASHSCOPE_API_KEY", {"enable_thinking": False}),
            ("deepseek", "DEEPSEEK_API_KEY", {"thinking": {"type": "disabled"}}),
        ]:
            with self.subTest(provider=provider), patch.dict(os.environ, {key_name: "external-test-secret"}):
                kwargs = {"base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"} if provider == "qwen" else {}
                client = LLMClient(provider=provider, **kwargs)
                with patch("backend.llm.client._urlopen", return_value=response()) as send:
                    self.assertEqual(client.chat_json("test"), [])
                request = send.call_args.args[0]
                body = json.loads(request.data)
                self.assertEqual(request.get_header("Authorization"), "Bearer external-test-secret")
                self.assertNotIn("chat_template_kwargs", body)
                for key, value in extra.items():
                    self.assertEqual(body[key], value)
        self.legacy.assert_not_called()

    def test_missing_cloud_key_fails_without_network_or_company_key(self):
        with patch("backend.llm.client._urlopen") as send:
            client = LLMClient(provider="deepseek")
            self.assertFalse(client.health())
            self.assertIn("调用凭据", client.last_error)
        send.assert_not_called()
        self.legacy.assert_not_called()

    def test_custom_endpoint_never_inherits_company_credentials(self):
        client = LLMClient(base_url="http://127.0.0.1:8080/v1", model="local-model")
        with patch("backend.llm.client._urlopen", return_value=response()) as send:
            client.chat_json("test")
        self.assertEqual(client.provider, "compatible")
        self.assertIsNone(send.call_args.args[0].get_header("Authorization"))
        self.legacy.assert_not_called()

    def test_compatible_deepseek_keeps_requested_thinking_mode(self):
        for thinking in (False, True):
            client=LLMClient(provider='compatible',base_url='https://api.deepseek.com/v1',model='deepseek-flash',api_key='fixture')
            with patch('backend.llm.client._urlopen',return_value=response()) as send:
                client.chat('fixture',thinking=thinking)
            self.assertEqual(json.loads(send.call_args.args[0].data)['thinking'],{'type':'enabled' if thinking else 'disabled'})
        client=LLMClient(provider='compatible',base_url='https://relay.invalid/v1',model='deepseek-flash',api_key='fixture')
        with patch('backend.llm.client._urlopen',return_value=response()) as send:client.chat('fixture')
        self.assertNotIn('thinking',json.loads(send.call_args.args[0].data))

    def test_intranet_credentials_cannot_be_redirected_by_configuration(self):
        client = LLMClient(provider="intranet", base_url="https://outside.invalid/v1")
        with patch("backend.llm.client._urlopen") as send, self.assertRaises(LLMUnavailable):
            client.chat("test")
        send.assert_not_called()

    def test_remote_plain_http_is_rejected(self):
        client = LLMClient(provider="compatible", base_url="http://outside.invalid/v1", model="test")
        with patch("backend.llm.client._urlopen") as send, self.assertRaises(LLMUnavailable):
            client.chat("test")
        send.assert_not_called()

    def test_internal_novastar_plain_http_is_allowed(self):
        client = LLMClient(provider="compatible", base_url="http://llm.novastar.tech:31000/v1", model="local-plus")
        with patch("backend.llm.client._urlopen", return_value=response()) as send:
            self.assertEqual(client.chat_json("test"), [])
        self.assertTrue(send.called)

    def test_lookalike_domain_is_not_treated_as_internal(self):
        client = LLMClient(provider="compatible", base_url="http://evilnovastar.tech/v1", model="test")
        with patch("backend.llm.client._urlopen") as send, self.assertRaises(LLMUnavailable):
            client.chat("test")
        send.assert_not_called()

    def test_extra_insecure_hosts_honoured(self):
        with patch.dict(os.environ, {"NOVATERM_LLM_INSECURE_HOSTS": "gpu-box.internal, other.lan"}):
            client = LLMClient(provider="compatible", base_url="http://gpu-box.internal:8080/v1", model="test")
            with patch("backend.llm.client._urlopen", return_value=response()) as send:
                client.chat_json("test")
        self.assertTrue(send.called)

    def test_user_key_from_settings_is_used_for_compatible(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "model-settings.json").write_text(json.dumps({
                "provider": "compatible", "base_url": "http://127.0.0.1:8080/v1",
                "model": "local", "api_key": "user-own-key",
            }), encoding="utf-8")
            with patch.dict(os.environ, {"NOVATERM_DATA_DIR": folder}):
                client = LLMClient()
                with patch("backend.llm.client._urlopen", return_value=response()) as send:
                    client.chat_json("test")
        self.assertEqual(client.api_key, "user-own-key")
        self.assertEqual(send.call_args.args[0].get_header("Authorization"), "Bearer user-own-key")
        self.legacy.assert_not_called()

    def test_explicit_key_beats_settings_and_company_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "model-settings.json").write_text(json.dumps({
                "provider": "compatible", "base_url": "http://127.0.0.1:8080/v1",
                "model": "local", "api_key": "from-settings",
            }), encoding="utf-8")
            with patch.dict(os.environ, {"NOVATERM_DATA_DIR": folder}):
                client = LLMClient(api_key="explicit-key")
        self.assertEqual(client.api_key, "explicit-key")
        self.legacy.assert_not_called()

    def test_intranet_uses_ui_key_when_provided_and_cannot_redirect_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "model-settings.json").write_text(json.dumps({
                "provider": "intranet", "api_key": "ui-entered-key",
            }), encoding="utf-8")
            with patch.dict(os.environ, {"NOVATERM_DATA_DIR": folder}):
                client = LLMClient()
        # 界面里改的密钥必须生效（优先于公司文件）；provider==intranet 已锁定地址，
        # 密钥最多发往公司网关，无法被 settings 重定向到外部服务。
        self.assertEqual(client.api_key, "ui-entered-key")
        self.assertEqual(client.base_url, "http://llm.novastar.tech:31000/v1")
        self.legacy.assert_not_called()

    def test_intranet_falls_back_to_user_key_when_company_file_missing(self):
        import tempfile
        self.legacy.stop()  # 撤掉 setUp 里「公司文件存在」的预设
        self.legacy = patch("backend.llm.client._load_api_key", return_value="").start()
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "model-settings.json").write_text(json.dumps({
                "provider": "intranet", "api_key": "user-machine-key",
            }), encoding="utf-8")
            with patch.dict(os.environ, {"NOVATERM_DATA_DIR": folder}):
                client = LLMClient()
        self.assertEqual(client.provider, "intranet")
        self.assertEqual(client.base_url, "http://llm.novastar.tech:31000/v1")
        self.assertEqual(client.api_key, "user-machine-key")

    def test_model_settings_endpoint_persists_key_without_echoing_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"NOVATERM_DATA_DIR": folder}):
                api = app.test_client()
                saved = api.post("/api/model/settings", json={
                    "provider": "compatible", "base_url": "http://127.0.0.1:8080/v1",
                    "model": "local", "api_key": "secret-user-key",
                })
                self.assertEqual(saved.status_code, 200)
                self.assertTrue(saved.json["has_key"])
                self.assertNotIn("api_key", saved.json)
                fetched = api.get("/api/model/settings")
                self.assertNotIn("secret-user-key", fetched.get_data(as_text=True))
                self.assertTrue(fetched.json["has_key"])
                # 留空再存（只改模型名）不应清掉已存密钥
                api.post("/api/model/settings", json={
                    "provider": "compatible", "base_url": "http://127.0.0.1:8080/v1",
                    "model": "renamed", "api_key": "",
                })
                self.assertTrue(api.get("/api/model/settings").json["has_key"])

    def test_authentication_error_does_not_echo_upstream_content(self):
        error = urllib.error.HTTPError("https://api.deepseek.com", 401, "secret upstream details", {}, io.BytesIO(b"private text"))
        with patch("backend.llm.client._urlopen", side_effect=error) as send:
            client = LLMClient(provider="deepseek", api_key="test-key")
            self.assertFalse(client.health())
        self.assertEqual(send.call_count, 1)
        self.assertIn("授权失败", client.last_error)
        self.assertNotIn("secret", client.last_error)
        self.assertNotIn("test-key", client.last_error)
        self.assertNotIn("VPN", client.last_error)

    def test_transient_error_retries(self):
        error = urllib.error.HTTPError("https://api.deepseek.com", 503, "unavailable", {}, io.BytesIO())
        with patch("backend.llm.client._urlopen", side_effect=[error, response()]) as send, patch("time.sleep"):
            self.assertEqual(LLMClient(provider="deepseek", api_key="test-key").chat_json("test"), [])
        self.assertEqual(send.call_count, 2)

    def test_truncated_empty_and_non_json_results_are_not_clean_reports(self):
        for content, finish in [("[]", "length"), ("", "stop"), ("Something went wrong", "stop")]:
            with self.subTest(content=content), patch("backend.llm.client._urlopen", return_value=response(content, finish)):
                with self.assertRaises(LLMUnavailable):
                    LLMClient(provider="deepseek", api_key="test-key").chat_json("test")

    def test_json_array_wrappers_preserve_array(self):
        expected = [{"found": "flexibile", "suggested": "flexible"}]
        for text in [json.dumps(expected), "```json\n" + json.dumps(expected) + "\n```", "Result: " + json.dumps(expected) + " End."]:
            self.assertEqual(_extract_json(text), expected)
        self.assertIsNone(_extract_json('[{"found":"unfinished"}'))

    def test_judge_rejects_json_object_instead_of_silently_passing(self):
        client = LLMClient(provider="deepseek", api_key="test-key")
        with patch.object(client, "chat_json", return_value={"unexpected": "result"}):
            with self.assertRaises(LLMUnavailable):
                judge_text("flexibile", Glossary([]), client)

    def test_health_error_reaches_judgement(self):
        client = LLMClient(provider="deepseek")
        with self.assertRaisesRegex(LLMUnavailable, "调用凭据"):
            judge_segments([], Glossary([]), client)

    def test_truncated_response_salvages_complete_items(self):
        # 数组末尾元素被截断时，前面已完整的条目仍应保留，并标记 truncated。
        content = '[{"found": "flexibile", "suggested": "flexible"}, {"found": "manufa'
        client = LLMClient(provider="deepseek", api_key="test-key")
        with patch("backend.llm.client._urlopen", return_value=response(content, "length")):
            result, truncated = client.chat_json_recoverable("test")
        self.assertTrue(truncated)
        self.assertEqual(result, [{"found": "flexibile", "suggested": "flexible"}])

    def test_truncated_with_no_complete_item_still_fails_loudly(self):
        # 抢救不出任何条目时不能假装成功——保持抛错。
        content = '[{"found": "manufa'
        client = LLMClient(provider="deepseek", api_key="test-key")
        with patch("backend.llm.client._urlopen", return_value=response(content, "length")):
            with self.assertRaises(LLMUnavailable):
                client.chat_json_recoverable("test")

    def test_backend_returns_provider_error_without_vpn_instruction(self):
        segment = Segment(id="test", file="sample.docx", text="sample", locator="body/0/p")
        with patch("backend.server.os.path.exists", return_value=True), \
             patch("backend.server._get_glossary", return_value=Glossary([])), \
             patch("backend.server.extract", return_value=[segment]), \
             patch("backend.server.check_segments", side_effect=LLMUnavailable("模型服务余额不足，请联系软件维护方。")):
            result = app.test_client().post("/api/check", json={"paths": ["sample.docx"]})
        self.assertEqual(result.status_code, 503)
        self.assertIn("余额不足", result.json["hint"])
        self.assertNotIn("VPN", result.json["hint"])


if __name__ == "__main__":
    unittest.main()
