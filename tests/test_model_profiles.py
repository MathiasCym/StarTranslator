# -*- coding: utf-8 -*-
"""已保存模型配置与其密钥加密的回归测试（不联网）。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import model_profiles
from backend.glossary import store
from backend.llm import secret
from backend.llm.client import LLMClient


def _profile(**over):
    base = {"name": "兼容", "provider": "compatible",
            "base_url": "http://127.0.0.1:9999/v1", "model": "m", "api_key": "sk-secret"}
    base.update(over)
    return base


class SecretTests(unittest.TestCase):
    def test_roundtrip_dpapi_or_plain(self):
        stored = secret.encrypt("sk-abcdef")
        self.assertTrue(stored)
        self.assertEqual(secret.decrypt(stored), "sk-abcdef")

    def test_empty_stays_empty(self):
        self.assertEqual(secret.encrypt(""), "")
        self.assertEqual(secret.decrypt(""), "")

    @unittest.skipUnless(secret.available(), "需要 Windows DPAPI")
    def test_dpapi_ciphertext_is_not_plaintext(self):
        stored = secret.encrypt("sk-abcdef")
        self.assertTrue(secret.is_encrypted(stored))
        self.assertNotIn("sk-abcdef", stored)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"NOVATERM_DATA_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_save_lists_active_and_never_exposes_key(self):
        result = model_profiles.save_profile(_profile())
        self.assertEqual(result["active"], "")
        self.assertFalse((Path(self.temp.name) / "model-settings.json").exists())
        listed = model_profiles.list_profiles()
        self.assertEqual(len(listed["profiles"]), 1)
        entry = listed["profiles"][0]
        self.assertTrue(entry["has_key"])
        self.assertNotIn("key", entry)
        self.assertNotIn("sk-secret", json.dumps(listed))

    def test_stored_key_is_encrypted_on_disk(self):
        saved = model_profiles.save_profile(_profile(api_key="sk-plain-secret"))
        model_profiles.activate(saved["profile"]["id"])
        raw = (Path(self.temp.name) / "model-profiles.json").read_text(encoding="utf-8")
        if secret.available():
            self.assertNotIn("sk-plain-secret", raw)
        self.assertEqual(model_profiles.active_key(), "sk-plain-secret")

    def test_many_profiles_reload_activate_edit_and_delete_without_limit(self):
        ids = [model_profiles.save_profile(_profile(name=f"p{i}",
               base_url=f"http://127.0.0.1:{9000+i}/v1", api_key=f'key-{i}'))['profile']['id']
               for i in range(25)]
        listed = model_profiles.list_profiles()
        self.assertIsNone(listed['max'])
        self.assertEqual(len(listed['profiles']), 25)
        model_profiles.activate(ids[-1])
        self.assertEqual(model_profiles.active_key(), 'key-24')
        model_profiles.save_profile(_profile(id=ids[5], name='edited', api_key='edited-key'))
        self.assertEqual(model_profiles.active_key(), 'key-24')
        model_profiles.activate(ids[5])
        self.assertEqual(model_profiles.active_key(), 'edited-key')
        model_profiles.delete_profile(ids[-1])
        self.assertEqual(len(model_profiles.list_profiles()['profiles']), 24)

    def test_activate_switches_and_updates_client_settings(self):
        first = model_profiles.save_profile(_profile(name="first", api_key="key-one"))["profile"]["id"]
        second = model_profiles.save_profile(
            _profile(name="second", base_url="http://127.0.0.1:9998/v1", api_key="key-two"))["profile"]["id"]
        model_profiles.activate(first)
        self.assertEqual(model_profiles.active_key(), "key-one")
        model_profiles.activate(second)
        self.assertEqual(model_profiles.active_key(), "key-two")

    def test_edit_without_key_keeps_existing_secret(self):
        pid = model_profiles.save_profile(_profile(api_key="keep-me"))["profile"]["id"]
        # 不带 api_key 字段 → 保留原密钥
        model_profiles.save_profile({"id": pid, "name": "改名", "provider": "compatible",
                                     "base_url": "http://127.0.0.1:9999/v1", "model": "m2"})
        model_profiles.activate(pid)
        self.assertEqual(model_profiles.active_key(), "keep-me")
        # 带空字符串 api_key → 显式清空
        model_profiles.save_profile({"id": pid, "name": "改名", "provider": "compatible",
                                     "base_url": "http://127.0.0.1:9999/v1", "model": "m2", "api_key": ""})
        self.assertEqual(model_profiles.active_key(), "keep-me")
        model_profiles.activate(pid)
        self.assertEqual(model_profiles.active_key(), "")

    def test_delete_active_requires_explicit_switch(self):
        first = model_profiles.save_profile(_profile(name="a"))["profile"]["id"]
        second = model_profiles.save_profile(_profile(name="b", base_url="http://127.0.0.1:9997/v1"))["profile"]["id"]
        model_profiles.activate(second)
        with self.assertRaisesRegex(ValueError, "正在使用"):
            model_profiles.delete_profile(second)
        self.assertEqual(model_profiles.active_profile()["id"], second)
        model_profiles.activate(first)
        model_profiles.delete_profile(second)
        self.assertEqual(model_profiles.active_profile()["id"], first)

    def test_save_active_changes_nothing_until_explicit_use(self):
        pid = model_profiles.save_profile(_profile(api_key='old-key'))['profile']['id']
        model_profiles.activate(pid)
        before = (Path(self.temp.name) / 'model-settings.json').read_bytes()
        model_profiles.save_profile(_profile(id=pid, model='new-model', base_url='http://127.0.0.1:8888/v1', api_key='new-key'))
        self.assertEqual((Path(self.temp.name) / 'model-settings.json').read_bytes(), before)
        self.assertEqual(model_profiles.active_profile()['model'], 'm')
        self.assertEqual(model_profiles.active_key(), 'old-key')
        self.assertTrue(model_profiles.list_profiles()['profiles'][0]['pending'])
        client = LLMClient()
        self.assertEqual(client.base_url, 'http://127.0.0.1:9999/v1')
        self.assertEqual(client.api_key, 'old-key')
        model_profiles.activate(pid)
        self.assertEqual(LLMClient().model, 'new-model')
        self.assertEqual(LLMClient().api_key, 'new-key')
        self.assertFalse(model_profiles.list_profiles()['profiles'][0]['pending'])

    def test_legacy_active_snapshot_survives_save_and_reload(self):
        legacy = {'id':'legacy', 'name':'old', 'provider':'compatible',
                  'base_url':'http://127.0.0.1:9999/v1', 'model':'old-model', 'key':secret.encrypt('old-key')}
        store.atomic_json(Path(self.temp.name)/'model-profiles.json', {'active':'legacy','profiles':[legacy]})
        model_profiles.save_profile(_profile(id='legacy', model='new-model', api_key='new-key'))
        self.assertEqual(model_profiles.active_profile()['model'], 'old-model')
        self.assertEqual(model_profiles.active_key(), 'old-key')
        self.assertTrue(model_profiles.list_profiles()['profiles'][0]['pending'])

    def test_save_inactive_preserves_active_connection(self):
        first = model_profiles.save_profile(_profile(api_key='a'))['profile']['id']
        model_profiles.activate(first)
        model_profiles.save_profile(_profile(name='inactive',api_key='b'))
        self.assertEqual(model_profiles.active_profile()['id'],first)
        self.assertEqual(model_profiles.active_key(),'a')

    def test_invalid_provider_rejected(self):
        with self.assertRaisesRegex(ValueError, "请选择"):
            model_profiles.save_profile(_profile(provider="bogus"))


class ClientProfileIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"NOVATERM_DATA_DIR": self.temp.name}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("NOVATERM_LLM_API_KEY", None)
        os.environ.pop("NOVATERM_LLM_BASE_URL", None)

    def test_active_profile_key_reaches_client_for_matching_connection(self):
        saved = model_profiles.save_profile(_profile(base_url="http://127.0.0.1:9999/v1", api_key="sk-live"))
        model_profiles.activate(saved["profile"]["id"])
        client = LLMClient()
        self.assertEqual(client.provider, "compatible")
        self.assertEqual(client.base_url, "http://127.0.0.1:9999/v1")
        self.assertEqual(client.api_key, "sk-live")

    def test_key_not_used_when_connection_differs(self):
        saved = model_profiles.save_profile(_profile(base_url="http://127.0.0.1:9999/v1", api_key="sk-live"))
        model_profiles.activate(saved["profile"]["id"])
        # 指向另一个地址的连接不应拿到该配置的密钥
        client = LLMClient(provider="compatible", base_url="http://127.0.0.1:8888/v1", model="m")
        self.assertEqual(client.api_key, "")

    def test_settings_file_never_contains_the_secret(self):
        saved = model_profiles.save_profile(_profile(api_key="sk-live"))
        model_profiles.activate(saved["profile"]["id"])
        raw = (Path(self.temp.name) / "model-settings.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-live", raw)


if __name__ == "__main__":
    unittest.main()
