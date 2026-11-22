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
    def test_legacy_translation_drops_neighboring_text_from_the_retry_request(self):
        from backend.glossary.loader import Glossary
        from backend.text_translation import translate_piece
        from backend.translation import mapped_translation

        for source, target in (
            ('控制器连接状态', 'Controller connection status'),
            ('Overview of the automatic controller connection status', '控制器自动连接状态概览'),
        ):
            with self.subTest(source=source):
                requests = []

                def chat(prompt, **kwargs):
                    requests.append(prompt)
                    return {'translation': target if len(requests) == 2 else target + '\nADJACENT TEXT'}

                model = SimpleNamespace(chat_json=chat)
                groups = [{'id': 0, 'text': source}]
                if source.startswith('控'):
                    runs, _ = mapped_translation(model, 'ADJACENT TEXT\n【待译原文】\n'+source,
                                                 source, groups, threading.Event())
                    actual = runs[0]['text']
                else:
                    actual = translate_piece(model, source, Glossary([]), 'en-zh', threading.Event(),
                                             context='ADJACENT TEXT', groups=groups)

                self.assertEqual(actual, target)
                self.assertEqual(len(requests), 2)
                self.assertIn('ADJACENT TEXT', requests[0])
                self.assertNotIn('ADJACENT TEXT', requests[1])

    def test_review_ignores_prose_suggestions_outside_format_and_terminology(self):
        from backend.matcher.judge import validated_hits
        hits = validated_hits([
            {'kind':'grammar','found':'60 Hz','suggested':'50 Hz'},
            {'kind':'term','found':'dot spacing','suggested':'pixel pitch'},
            {'kind':'format','found':'TEST TEST','suggested':'TEST'},
        ], 'dot spacing · 60 Hz · TEST TEST')
        self.assertEqual([item['suggested'] for item in hits], ['pixel pitch','TEST'])

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

    def test_word_retries_only_the_title_when_translation_includes_neighboring_lines(self):
        from docx import Document
        from backend import document_languages, workflow
        from backend.extract import extract

        lines = ['连接状态', '控制器已连接。', '请检查信号。']
        path = self.root / 'headings.docx'
        document = Document()
        document.add_heading(lines[0], level=1)
        document.add_paragraph('\n'.join(lines[1:]))
        document.save(path)
        before = path.read_bytes()
        translations = {
            'zh-Hant-TW': ['連線狀態', '控制器已連線。', '請檢查訊號。'],
            'ja-JP': ['接続状態', 'コントローラーは接続済みです。', '信号を確認してください。'],
            'ko': ['연결 상태', '컨트롤러가 연결되었습니다.', '신호를 확인하세요.'],
        }

        class BoundaryModel(fixtures.Model):
            def __init__(self, values):
                super().__init__(None)
                self.values = dict(zip(lines, values))
                self.translation_inputs = []

            def chat_json(self, prompt, system='', **options):
                payload = json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' not in payload:
                    return super().chat_json(prompt, system, **options)
                source = payload['待译原文']
                self.translation_inputs.append(payload)
                if source == lines[0] and payload['相邻原文（仅供理解）']:
                    return {'translation': '\n'.join(self.values.values())}
                return {'translation': self.values[source]}

        for dst, values in translations.items():
            for kind in ('translate', 'translate_review'):
                with self.subTest(target=dst, kind=kind):
                    model = BoundaryModel(values)
                    options = document_languages.normalize(self.options(path, 'zh-CN', dst, kind))
                    job = {'id': f'{dst}-{kind}', 'status': 'running', 'cancel': threading.Event()}
                    workflow.run(job, {**options, '_client': model})
                    self.assertEqual(job['status'], 'complete', job.get('error') or job.get('result'))
                    output, = job['result']['outputs']
                    saved = Document(output['path'])
                    self.assertEqual([p.text for p in saved.paragraphs], [values[0], '\n'.join(values[1:])])
                    self.assertEqual(saved.paragraphs[0].style.name, 'Heading 1')
                    self.assertEqual([s.text for s in extract(output['path']) if s.editable], [values[0], '\n'.join(values[1:])])
                    requests = [item for item in model.translation_inputs if item['待译原文'] == lines[0]]
                    self.assertEqual(len(requests), 2)
                    self.assertIn(lines[1], requests[0]['相邻原文（仅供理解）'])
                    self.assertNotIn(lines[0], requests[0]['相邻原文（仅供理解）'])
                    self.assertEqual(requests[1]['相邻原文（仅供理解）'], '')
                    self.assertNotIn('上次译文（以此为底稿）', requests[1])
                    self.assertEqual(len(model.translation_inputs), 4)
                    self.assertEqual(path.read_bytes(), before)

    def test_document_body_connects_both_writing_skills_without_a_factual_review(self):
        from backend import document_languages, workflow
        from backend.extract import extract
        self.stubs.enter_context(patch('backend.pdf_quality.audit',return_value={'status':'complete','issues':[]}))

        class Model(fixtures.Model):
            def chat_json(self,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '原文' in payload and '译文' in payload:
                    raise AssertionError('Unexpected extra review of ordinary translation content.')
                if '待译原文' in payload:
                    self.writing_prompt=system
                return super().chat_json(prompt,system,**options)

        source='团队正在寻找一套创新方案，并探索一种新型场馆。'
        targets={'ko':'팀은 혁신적인 방안을 찾고 새로운 형태의 시설을 모색하고 있다.',
                 'ja-JP':'チームは革新的な方策を探し、新形式の施設を模索している。',
                 'zh-Hant-TW':'團隊正在尋找一套創新方案，也在探索新式場館。'}
        for suffix in ('.docx','.pdf','.pptx'):
            for dst,target in targets.items():
                for kind in ('translate','translate_review'):
                    with self.subTest(suffix=suffix,target=dst,kind=kind):
                        identity=f'{suffix[1:]}-{dst}-{kind}'
                        path=self.source(suffix,source,identity)
                        before=path.read_bytes()
                        model=Model(target)
                        job={'id':identity,'status':'running','cancel':threading.Event()}
                        options=document_languages.normalize(self.options(path,'zh-CN',dst,kind))
                        workflow.run(job,{**options,'_client':model})
                        self.assertEqual(job['status'],'complete',job.get('error') or job.get('result'))
                        output,=job['result']['outputs']
                        self.assertEqual(output['untranslated'],0)
                        self.assertEqual([s.text for s in extract(output['path']) if s.editable],[target])
                        self.assertEqual(model.translations,1)
                        self.assertIn('de-AI-writing',model.writing_prompt)
                        self.assertIn('Humanizer',model.writing_prompt)
                        self.assertEqual(path.read_bytes(),before)

    def test_english_document_with_chinese_source_selection_suggests_english(self):
        from backend.translation import translate_file
        path=self.source('.docx','The controller supports a refresh rate of 60 Hz.','english-source')
        with self.assertRaisesRegex(ValueError,'把源语言改为英语'):
            translate_file(str(path),None,None,direction='zh-en')

    def test_word_translation_recovers_a_fragment_before_either_export_path(self):
        from backend.extract import extract
        class Model(fixtures.Model):
            def chat_json(self,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' in payload and not system.startswith('补译一段'):
                    return {'translation':payload['待译原文']}
                return super().chat_json(prompt,system,**options)
        for kind in ('translate','translate_review'):
            with self.subTest(kind=kind):
                source='。8月22日票价为41美元'
                target='。8월 22일 요금은 41달러'
                path=self.source('.docx',source,kind)
                before=path.read_bytes()
                model=Model(target)
                job=self.job(self.options(path,'zh-CN','ko',kind),model)
                self.assertEqual(job['status'],'complete',job['result'])
                output=job['result']['outputs'][0]
                self.assertFalse(output['staged'] and not output.get('auto_exported'))
                self.assertEqual(output['untranslated'],0)
                self.assertIn(target,[s.text for s in extract(output['path']) if s.editable])
                self.assertTrue(any(system.startswith('补译一段') for _,system in model.requests))
                self.assertEqual(path.read_bytes(),before)

    def test_word_recovery_retries_malformed_translation_response(self):
        from backend.multilingual_documents import recover_paragraph
        from backend.llm.client import LLMResponseInvalid
        class Recovery(fixtures.Model):
            def __init__(self, first):
                super().__init__('관람 구역을 확인하세요.')
                self.first=first
            def chat_json(self,prompt,system='',**options):
                payload=json.loads(prompt)
                if '待译原文' in payload:
                    self.translations+=1
                    if self.translations==1 and isinstance(self.first,Exception):
                        raise self.first
                    if self.translations==2:
                        self.requests.append(payload['上次检查'])
                    return {'translation':self.target if self.translations>1 else '작동 상태를 확인하세요.'}
                if self.translations==1:
                    return {'ok':False,'issues':[self.first]}
                return {'ok':True,'issues':[]}
        for issue in (LLMResponseInvalid('响应不是 JSON'),):
            model=Recovery(issue)
            self.assertEqual(recover_paragraph(model,'检查观看区。','zh-CN','ko',threading.Event()),model.target)
            self.assertEqual(model.requests,[str(issue)])

    def test_multilingual_recovery_retries_failed_long_paragraph_by_sentence(self):
        from backend.extract import extract
        first='请确认观看区域。'
        second='刷新率为60 Hz。'
        first_target='관람 구역을 확인하세요.'
        second_target='주사율은 60 Hz입니다.'
        class SplitModel(fixtures.Model):
            def chat_json(self,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' in payload:
                    piece=payload['待译原文']
                    self.requests.append(piece)
                    return {'translation':{first:first_target,second:second_target}.get(piece,piece)}
                return {'ok':True,'issues':[]}
        model=SplitModel('')
        source=first+second
        path=self.source('.docx',source)
        job=self.job(self.options(path,'zh-CN','ko','translate'),model)
        output,=job['result']['outputs']
        self.assertTrue(output['translation_complete'])
        self.assertEqual(extract(output['path'])[0].text,first_target+' '+second_target)
        self.assertGreaterEqual(model.requests.count(source),2)
        self.assertIn(first,model.requests)
        self.assertIn(second,model.requests)

    def test_untranslated_slide_does_not_block_other_slides_from_export(self):
        from backend.extract import extract
        from pptx import Presentation
        from pptx.util import Inches
        class Partial(fixtures.Model):
            def chat_json(self,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' in payload and '亮度' in payload['待译原文']:
                    return {'translation':''}
                if payload.get('本段待校对文字')=='관람 구역을 확인하세요.':
                    return {'reviewed':True,'suggestions':[{'kind':'format','original':'확인하세요',
                        'replacement':'확인하십시오','reason':'同一文档使用一致的敬语。'}]}
                return super().chat_json(prompt,system,**options)
        class Complete(Partial):
            def chat_json(self,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '亮度' in payload.get('待译原文',''):
                    return {'translation':'밝기는 500 nits입니다.'}
                return super().chat_json(prompt,system,**options)
        path=self.root/'partial.pptx'
        deck=Presentation()
        for value in ('检查观看区。','亮度为500尼特。'):
            slide=deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_textbox(Inches(1),Inches(1),Inches(7),Inches(1)).text=value
        deck.save(path)
        before=path.read_bytes()
        target='관람 구역을 확인하세요.'
        for kind in ('translate','translate_review'):
            with self.subTest(kind=kind):
                job=self.job(self.options(path,'zh-CN','ko',kind),Partial(target))
                self.assertEqual(job['status'],'partial',job.get('result'))
                self.assertTrue(job['can_resume'])
                output,=job['result']['outputs']
                self.assertTrue(output['draft_pending']);self.assertEqual(output['untranslated'],1)
                self.assertFalse(output.get('auto_exported'))
                expected='관람 구역을 확인하십시오.' if kind=='translate_review' else target
                self.assertEqual([s.text for s in extract(output['path']) if s.editable],[expected,'亮度为500尼特。'])
                draft=Path(output['path']);saved_bytes=draft.read_bytes()
                resumed=self.job({'resume_from':job['id']},Complete(target))
                self.assertEqual(resumed['status'],'complete',resumed.get('result'))
                final,=resumed['result']['outputs']
                self.assertEqual(final['resumed_segments'],1)
                self.assertEqual(final['untranslated'],0);self.assertFalse(final.get('draft_pending'))
                self.assertEqual([s.text for s in extract(final['path']) if s.editable],[expected,'밝기는 500 nits입니다.'])
                self.assertEqual(draft.read_bytes(),saved_bytes)
                self.assertEqual(path.read_bytes(),before)

    def test_automatic_review_cannot_reintroduce_source_clause_via_multiple_edits(self):
        from backend.extract import extract
        class Review(fixtures.Model):
            def chat_json(self,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '本段待校对文字' in payload:
                    return {'reviewed':True,'suggestions':[
                        {'original':'표시 가능한','replacement':'there are','reason':'first part'},
                        {'original':'항목을 확인하세요','replacement':'three available options','reason':'second part'},
                    ]}
                return super().chat_json(prompt,system,**options)
        target='표시 가능한 항목을 확인하세요.'
        path=self.source('.docx','请检查可以显示的项目。')
        job=self.job(self.options(path,'zh-CN','ko','translate_review'),Review(target))
        output=job['result']['outputs'][0]
        self.assertEqual(output['untranslated'],0)
        self.assertEqual(output['corrected'],0)
        self.assertIn(target,[s.text for s in extract(output['path']) if s.editable])


    def test_invalid_proofreading_response_retries_without_retranslating(self):
        from backend.llm.client import LLMResponseInvalid
        class Review(fixtures.Model):
            reviews=0
            def chat_json(self,prompt,system='',**options):
                if '本段待校对文字' in json.JSONDecoder().raw_decode(prompt)[0]:
                    self.reviews+=1
                    if self.reviews==1:raise LLMResponseInvalid('response lacks JSON')
                return super().chat_json(prompt,system,**options)
        path=self.source('.docx','检查观看区。')
        model=Review('관람 구역을 확인하세요.')
        job=self.job(self.options(path,'zh-CN','ko'),model)
        self.assertEqual(job['status'],'complete',job['result'])
        self.assertEqual(model.reviews,2)
        self.assertEqual(model.translations,1)

    def test_numeric_year_labels_export_in_word_and_grouped_ppt(self):
        from backend import document_languages, workflow
        from backend.document_translation_core import verify_translation_delivery
        from backend.extract.office import open_office
        from docx import Document
        from pptx import Presentation
        from pptx.util import Inches

        class YearModel(fixtures.Model):
            def chat_json(self, prompt, system='', **options):
                if not prompt.lstrip().startswith('{'):
                    return {'translation': self.target}
                return super().chat_json(prompt, system, **options)

        for suffix in ('.docx', '.pptx'):
            with self.subTest(format=suffix):
                source = self.root / ('year-source' + suffix)
                if suffix == '.docx':
                    package = Document()
                    label = package.add_paragraph()
                else:
                    package = Presentation()
                    group = package.slides.add_slide(package.slide_layouts[6]).shapes.add_group_shape()
                    label = group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text_frame.paragraphs[0]
                label.add_run().text = '2025年'
                package.save(source)

                for kind in ('translate', 'translate_review'):
                    with self.subTest(workflow=kind):
                        job = {'id': suffix[1:] + '-' + kind, 'status': 'running', 'cancel': threading.Event()}
                        options = document_languages.normalize(self.options(source, 'zh-CN', 'en-US', kind))
                        workflow.run(job, {**options, '_client': YearModel('2025')})
                        self.assertEqual(job['status'], 'complete', job.get('result'))
                        output, = job['result']['outputs']
                        _, paragraphs, _ = open_office(output['path'])
                        self.assertIn('2025', [paragraph.text for _, paragraph, _, _, _ in paragraphs])
                        verify_translation_delivery(output['path'], 'zh-en', source=source)


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
