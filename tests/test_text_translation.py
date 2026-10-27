"""No-network direction, quality, recovery, queue and session-isolation tests."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import workflow, task_queue, text_translation as text, lan_service
from backend.glossary.loader import Glossary
from backend.models import GlossaryEntry
from backend.llm.client import LLMUnavailable


class Client:
    def __init__(self, values): self.values = iter(values); self.calls = []
    def chat_json(self, prompt, **options):
        self.calls.append((prompt, options))
        value = next(self.values)
        if isinstance(value, Exception): raise value
        return value


OK = {'ok': True, 'issues': []}


class TextTranslationTests(unittest.TestCase):
    def setUp(self):
        self.g = Glossary([GlossaryEntry('点间距', 'pixel pitch', variants=['pixel spacing'], priority=1),
            GlossaryEntry('像素间距', 'pixel pitch'), GlossaryEntry('陈一鸣', 'Chen Yiming', category='person')])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'NOVATERM_DATA_DIR': self.temp.name}); env.start(); self.addCleanup(env.stop)
        self.previous = dict(workflow.JOBS)
        with workflow.LOCK:
            self.assertFalse(any(j['status'] in ('running', 'queued') for j in workflow.JOBS.values()))
            workflow.JOBS.clear()
        self.addCleanup(self.restore)
        glossary = patch('backend.text_translation.store.load_glossary', return_value=self.g)
        glossary.start(); self.addCleanup(glossary.stop)

    def restore(self):
        with workflow.LOCK:
            workflow.JOBS.clear(); workflow.JOBS.update(self.previous)
            task_queue.MAINTENANCE = False

    def run_job(self, source, direction, client, **options):
        with patch('backend.text_translation.LLMClient', return_value=client):
            job = workflow.start({'kind': 'text', 'text': source, 'direction': direction, **options})
            return asyncio.run(task_queue.wait(job['id'], .005))

    def test_both_directions_and_review(self):
        for direction, source, target in [('zh-en', '点间距为 2.6 mm。', 'The pixel pitch is 2.6 mm.'),
                ('en-zh', 'The pixel pitch is 2.6 mm.', '点间距为 2.6 mm。')]:
            with self.subTest(direction=direction):
                client = Client([{'translation': target}, OK])
                job = self.run_job(source, direction, client)
                self.assertEqual(job['result']['translation'], target)
                self.assertTrue(job['result']['complete'])
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(job['done'], job['total'])
                self.assertFalse(list(Path(self.temp.name).rglob('*')), 'Free text must not create document/checkpoint/history files')

    def test_reviewer_correction_is_validated_without_retranslating_accepted_facts(self):
        client=Client([{'translation':'灰度精度为10位。'},
            {'ok':False,'issues':['采用已确认术语灰阶'],'corrected_translation':'灰阶精度为10位。'},OK])
        job=self.run_job('The grayscale accuracy is 10-bit.','en-zh',client)
        self.assertTrue(job['result']['complete']);self.assertEqual(job['result']['translation'],'灰阶精度为10位。')
        self.assertEqual(len(client.calls),3)
        self.assertEqual(sum('待译原文' in prompt for prompt,_ in client.calls),1)

    def test_reverse_calendar_units_codes_and_identifiers(self):
        text.validate('The pixel pitch is2.5 mm.','点间距为2.5毫米。','en-zh')
        text.validate('The temperature is-10 to40 °C.','温度为-10至40°C。','en-zh')
        text.validate('The controller model to40 supports 60 Hz.','控制器型号to40支持60Hz。','en-zh')
        for original,target in [('The pixel pitch is2.5 mm.','点间距为2.5。'),
                ('The controller model to40 supports 60 Hz.','控制器型号to41支持60Hz。'),('is2.5','是2.5')]:
            with self.assertRaises(ValueError):text.validate(original,target,'en-zh')
        for source,target in [('The grayscale accuracy is 10-bit.','灰阶精度为10位。'),
                ('灰阶精度为10bit。','灰阶精度为10位。'),('灰阶精度为10位。','灰阶精度为10-bit。'),
                ('The grayscale accuracy is 10-bit.','灰阶精度为10比特。')]:
            text.validate(source,target,'en-zh')
        with self.assertRaises(ValueError):text.validate('10位专家','10-bit experts','en-zh')
        text.validate('John Smith', 'John Smith', 'en-zh')
        text.validate('Aegisolve, Inc.', 'Aegisolve, Inc.', 'en-zh')
        with self.assertRaises(ValueError): text.validate('The screen is waterproof.', 'The screen is waterproof.', 'en-zh')
        text.validate('H2 strategy: 9 May 2025, 2 million LED panels.', '下半年战略：2025年5月9日，200万块 LED 屏。', 'en-zh')
        text.validate('MEETING AGENDA', '会议议程', 'en-zh')
        text.validate('HDMI 2.1 at 60 Hz, see https://example.com/中文?q=1', 'HDMI 2.1，60 赫兹，参见 https://example.com/中文?q=1', 'en-zh')
        for source, target in [('The A8 controller supports 60 Hz.', 'A9 控制器支持 60 赫兹。'),
                ('The screen is 2 mm.', '屏幕为 2。'), ('Output 2.', '输出 3。'),
                ('See https://example.com/中文', '参见 https://example.com/english')]:
            with self.subTest(source=source), self.assertRaises(ValueError): text.validate(source, target, 'en-zh')

    def test_zh_en_residual_never_accepted_but_chinese_urls_are(self):
        text.validate('查看 https://example.com/中文', 'See https://example.com/中文', 'zh-en')
        client = Client([{'translation': 'Still 中文'}, {'translation': 'Still 中文'}])
        job = self.run_job('仍有中文', 'zh-en', client)
        self.assertFalse(job['result']['complete']); self.assertEqual(len(client.calls), 2)
        self.assertNotIn('Still 中文', job['result']['translation'])

    def test_model_detected_omission_regenerates_with_source(self):
        client = Client([{'translation': '屏幕。'}, {'ok': False, 'issues': ['遗漏防水条件']},
            {'translation': '屏幕防水。'}, OK])
        job = self.run_job('The screen is waterproof.', 'en-zh', client)
        self.assertEqual(job['result']['translation'], '屏幕防水。')
        self.assertIn('遗漏防水条件', client.calls[2][0])

    def test_invalid_review_is_not_success(self):
        client = Client([{'translation': '译文'}, {'ok': 'true'}, {'translation': '译文'}, {'ok': True}])
        self.assertFalse(self.run_job('Translation', 'en-zh', client)['result']['complete'])

    def test_separators_and_newlines_unchanged(self):
        source = '  第一段。 \r\n\r\n\t第二段。\n'
        client = Client([{'translation': 'First paragraph.'}, OK, {'translation': 'Second paragraph.'}, OK])
        job = self.run_job(source, 'zh-en', client)
        self.assertEqual(job['result']['translation'], '  First paragraph. \r\n\r\n\tSecond paragraph.\n')

    def test_disconnect_retry_reuses_only_verified_blocks(self):
        job = self.run_job('第一段\n第二段', 'zh-en', Client([{'translation': 'First paragraph'}, OK, LLMUnavailable('disconnected')]))
        self.assertEqual(job['status'], 'failed'); self.assertEqual(job['done'], 1)
        self.assertIn('First paragraph', job['result']['translation'])
        client = Client([{'translation': 'Second paragraph'}, OK])
        final = self.run_job('第一段\n第二段', 'zh-en', client, retry_of=job['id'])
        self.assertTrue(final['result']['complete'])
        self.assertEqual(final['result']['translation'], 'First paragraph\nSecond paragraph')
        self.assertEqual(len(client.calls), 2)
        with self.assertRaises(ValueError): self.run_job('Changed', 'en-zh', Client([]), retry_of=job['id'])

    def test_rejected_content_remains_retryable(self):
        job = self.run_job('数字 2', 'zh-en', Client([{'translation': 'Number 3'}, {'translation': 'Number 4'}]))
        self.assertFalse(job['result']['complete'])
        result = self.run_job('数字 2', 'zh-en', Client([{'translation': 'Number 2'}, OK]), retry_of=job['id'])
        self.assertTrue(result['result']['complete'])

    def test_glossary_inverse_keeps_ambiguity_and_person_category(self):
        context = text.glossary_context('pixel pitch and Chen Yiming', self.g, 'en-zh')
        self.assertEqual({v['中文'] for v in context}, {'点间距', '像素间距', '陈一鸣'})
        self.assertEqual(next(v for v in context if v['中文'] == '陈一鸣')['分类'], 'person')
        self.assertFalse(text.glossary_context('micropixel pitchfork', self.g, 'en-zh'))

    def test_cancel_and_maintenance_share_normal_pool(self):
        event = threading.Event()
        class Slow:
            def chat_json(self, *args, **kwargs):
                event.set(); self.cancel.wait(3)
                raise LLMUnavailable('cancelled')
        with patch('backend.text_translation.LLMClient', return_value=Slow()):
            job = workflow.start({'kind': 'text', 'text': '原文'})
            self.assertTrue(event.wait(2))
            with workflow.LOCK:
                self.assertEqual(workflow.JOBS[job['id']]['status'], 'running')
            workflow.cancel(job['id'])
            result = asyncio.run(task_queue.wait(job['id'], .005))
            self.assertEqual(result['status'], 'cancelled')
        task_queue.MAINTENANCE = True
        with patch('backend.text_translation.LLMClient', return_value=Client([])), self.assertRaises(ValueError):
            workflow.start({'kind': 'text', 'text': '原文'})

    def test_input_boundaries(self):
        for data in [{'text': ''}, {'text': None}, {'text': 'x'*20001}, {'text': 'hello', 'direction': []},
                {'text': 'hello', 'direction': 'auto'}, {'text': 'hello', 'retry_of': []}]:
            with self.subTest(data=str(data)[:70]), self.assertRaises(ValueError): text.start(data)

    def test_lan_owner_csrf_and_no_paths_or_model_overrides(self):
        old_sessions = dict(lan_service.SESSIONS); lan_service.SESSIONS.clear()
        self.addCleanup(lambda: (lan_service.SESSIONS.clear(), lan_service.SESSIONS.update(old_sessions)))
        app = lan_service.create_app(testing=True)
        owner, stranger = app.test_client(), app.test_client()
        csrf = owner.get('/shared/session').json['csrf']; stranger_csrf = stranger.get('/shared/session').json['csrf']
        with patch('backend.text_translation.LLMClient', return_value=Client([{'translation': 'Hello'}, OK])):
            forbidden = owner.post('/shared/text/jobs', json={'text': '你好'})
            self.assertEqual(forbidden.status_code, 403)
            response = owner.post('/shared/text/jobs', json={'text': '你好', 'direction': 'zh-en',
                'paths': ['C:/secret'], '_client': 'bad'}, headers={'X-Star-CSRF': csrf})
            self.assertEqual(response.status_code, 200)
            job = asyncio.run(task_queue.wait(response.json['id'], .005))
        url = '/shared/text/jobs/' + job['id']
        self.assertEqual(owner.get(url).json['result']['translation'], 'Hello')
        self.assertEqual(stranger.get(url).status_code, 400)
        self.assertEqual(stranger.post(url+'/cancel', headers={'X-Star-CSRF': stranger_csrf}).status_code, 400)
        self.assertEqual(stranger.post('/shared/text/jobs', json={'text': '你好', 'retry_of': job['id']},
            headers={'X-Star-CSRF': stranger_csrf}).status_code, 400)
        self.assertFalse(owner.get('/shared/jobs').json['jobs'])
        with owner.get('/text-translation.js') as response: self.assertEqual(response.status_code, 200)


if __name__ == '__main__': unittest.main()
