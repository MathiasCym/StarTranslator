"""Shared coverage, real transport recovery semantics and language adapters."""
import http.client,json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend.document_translation_core import ensure_coverage,transport_epoch,repaired_pages,interruption_summary,publish_new_file
from backend.llm.transport_recovery import RecoveryGate,TransportStopped
from backend.llm.client import LLMClient,LLMRequestFailed
import test_document_languages as fixtures


class GateTests(unittest.TestCase):
    def test_shared_publish_retries_locks_without_replacing_an_unexpected_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);temporary=root/'pending.docx';target=root/'saved.docx';temporary.write_bytes(b'verified')
            real=os.replace;attempts=[];guards=[]
            def commit(a,b):
                attempts.append(1)
                if len(attempts)==1:
                    error=PermissionError('transient lock');error.winerror=5;raise error
                real(a,b)
            with patch('backend.atomic_file.os.replace',side_effect=commit),patch('backend.atomic_file.time.sleep'):
                publish_new_file(temporary,target,lambda:guards.append(1))
            self.assertEqual(target.read_bytes(),b'verified');self.assertEqual(len(guards),2)
            temporary.write_bytes(b'other')
            with self.assertRaisesRegex(ValueError,'未覆盖'):publish_new_file(temporary,target,lambda:None)
            self.assertEqual(target.read_bytes(),b'verified')

    def test_shared_publish_rechecks_source_and_destination_after_wait(self):
        for external_target in (False,True):
            with self.subTest(external_target=external_target),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original';source.write_bytes(b'original')
                temporary=root/'pending';temporary.write_bytes(b'verified');target=root/'saved'
                def guard():
                    if source.read_bytes()!=b'original':raise ValueError('source changed')
                def edited(_):(target if external_target else source).write_bytes(b'user edit')
                error=PermissionError('transient lock');error.winerror=5
                with patch('backend.atomic_file.os.replace',side_effect=error),patch('backend.atomic_file.time.sleep',side_effect=edited):
                    with self.assertRaises(ValueError):publish_new_file(temporary,target,guard)
                self.assertEqual((target if external_target else source).read_bytes(),b'user edit')
                self.assertEqual(temporary.read_bytes(),b'verified')
    def test_cooldown_waits_and_allows_one_recovery_owner_without_request_flood(self):
        gate=RecoveryGate(.04);gate.failure();entered=[];waiting=[]
        def work(index):
            gate.before(notify=lambda _:waiting.append(index));entered.append(index)
            if len(entered)==1:time.sleep(.04);gate.success()
        threads=[threading.Thread(target=work,args=(i,)) for i in range(3)]
        start=time.monotonic()
        for thread in threads:thread.start()
        for thread in threads:thread.join(2);self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(time.monotonic()-start,.07);self.assertEqual(len(entered),3);self.assertTrue(waiting)
        self.assertTrue(gate.recovered(0))

    def test_persistent_failure_stops_probe_but_cancel_interrupts_wait(self):
        gate=RecoveryGate(0);epoch=gate.failure();gate.before();gate.failure()
        self.assertFalse(gate.may_recover(epoch))
        with self.assertRaises(TransportStopped):gate.before()
        gate=RecoveryGate(15);gate.failure();cancel=threading.Event();cancel.set()
        with self.assertRaises(TransportStopped) as caught:gate.before(cancel)
        self.assertTrue(caught.exception.cancelled)

    def test_transport_budget_then_later_request_recovers_without_skipping_next_request(self):
        import io
        client=LLMClient(provider='compatible',base_url='http://127.0.0.1:1/v1',model='fixture',api_key='',retries=0)
        client._transport.cooldown=0
        body=json.dumps({'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]}).encode()
        with patch('backend.llm.client._urlopen',side_effect=[http.client.IncompleteRead(b''),io.BytesIO(body),io.BytesIO(body)]) as send:
            with self.assertRaises(LLMRequestFailed) as caught:client.chat_json('first')
            self.assertEqual(send.call_count,1);stamp=transport_epoch(caught.exception)
            self.assertTrue(client.can_recover_transport(stamp));self.assertFalse(client.transport_recovered(stamp))
            self.assertEqual(client.chat_json('next'),{'ok':True});self.assertTrue(client.transport_recovered(stamp))
            self.assertEqual(client.chat_json('last'),{'ok':True});self.assertEqual(send.call_count,3)

    def test_coverage_catches_a_never_submitted_paragraph_without_changing_its_text(self):
        items=[SimpleNamespace(locator=str(i),slide=1,para=i+1,text='source '+str(i)) for i in range(3)]
        paragraphs={s.locator:SimpleNamespace(text=s.text) for s in items}
        pending=[{'locator':'1','retained_source':True,'reason':'known failure'}]
        result=ensure_coverage(items,['0'],pending,paragraphs)
        self.assertEqual([r['locator'] for r in result],['1','2']);self.assertEqual(len(pending),1)
        self.assertEqual(result[1]['translation'],'source 2');self.assertIn('不能视为翻译完成',result[1]['reason'])
        summary=interruption_summary([{'source':'a','review_items':[{'locator':'1','service_unavailable':True},{'locator':'2','service_unavailable':True}]},
            {'source':'b','review_items':[{'locator':'1','reason':'content validation'}]}])
        self.assertEqual(summary['pending'],2);self.assertIn('尚未进入正常校对',summary['message'])


class SharedAdapterTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    source=fixtures.DocumentLanguageTests.source
    job=fixtures.DocumentLanguageTests.job
    options=fixtures.DocumentLanguageTests.options

    def test_persistent_network_outage_has_one_common_interruption_summary(self):
        class Offline(fixtures.Model):
            def chat_json(self,*args,**kwargs):
                error=LLMRequestFailed('offline gateway');error.transport_epoch=0;raise error
            def can_recover_transport(self,epoch):return False
        for dst in ('zh-Hant-TW','ja-JP','ko'):
            with self.subTest(dst=dst):
                path=self.source('.docx',fixtures.SAMPLES['zh-CN'],dst+'-offline');before=path.read_bytes()
                job=self.job(self.options(path,'zh-CN',dst),Offline(fixtures.SAMPLES[dst]))
                self.assertEqual(job['status'],'partial')
                self.assertTrue(job['result']['connection_interrupted'])
                self.assertEqual(job['result']['outputs'],[])
                self.assertNotIn('report',job['result'])
                self.assertIn('模型连接中断',job['message']);self.assertEqual(path.read_bytes(),before)

    def test_every_document_target_uses_bounded_transport_recovery_before_proofreading(self):
        # This suite injects transport faults; native/PDF image fidelity has its
        # own suites and must not invoke an inherited real network method.
        self.stubs.enter_context(patch('backend.pdf_quality.audit',return_value={'status':'complete','issues':[]}))
        class Model(fixtures.Model):
            def __init__(self,target):super().__init__(target);self.gate=RecoveryGate(0);self.failed=False
            def can_recover_transport(self,epoch):return self.gate.may_recover(epoch)
            def transport_recovered(self,epoch):return self.gate.recovered(epoch)
            def chat_json_recoverable(self,*args,**kwargs):return [],False
            def chat_json(self,*args,**kwargs):
                prompt=args[0]
                if '【待译原文】' in prompt:result={'translation':self.target}
                elif not prompt.startswith('{'):result=[]
                elif '中文译文' in json.JSONDecoder().raw_decode(prompt)[0]:result={'reviewed':True,'suggestions':[]}
                elif '候选及英文原文语境' in json.JSONDecoder().raw_decode(prompt)[0]:result={'people':[]}
                else:result=super().chat_json(*args,**kwargs)
                if isinstance(result,dict) and 'translation' in result and not self.failed:
                    self.failed=True;error=LLMRequestFailed('synthetic exhausted connection');error.transport_epoch=self.gate.failure();raise error
                self.gate.success();return result
        for dst in ('en-US','zh-CN','zh-Hant-TW','ja-JP','ko'):
            src='en-US' if dst=='zh-CN' else 'zh-CN'
            for suffix in ('.docx','.pptx','.pdf'):
                with self.subTest(target=dst,format=suffix):
                    path=self.source(suffix,fixtures.SAMPLES[src],dst+suffix);before=path.read_bytes()
                    model=Model(fixtures.SAMPLES[dst]);job=self.job(self.options(path,src,dst),model)
                    self.assertTrue(model.failed);self.assertEqual(job['status'],'complete',job.get('result'))
                    output=job['result']['outputs'][0]
                    self.assertTrue(output['translation_complete']);self.assertEqual(output['untranslated'],0)
                    self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
