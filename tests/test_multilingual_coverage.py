"""Actual failure shapes: equivalent quantities, valid identity and failed-item repair."""
import json,sys,threading,unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend.text_languages import validate,translate_piece
from backend.multilingual_quality import LanguageReview,IncompleteLanguageReview,chinese_script
from backend.translation_retry import repaired_pages

class CoverageTests(unittest.TestCase):
    def test_exact_scaled_quantities_grouping_counters_and_dimensions(self):
        validate('130万像素','130만 화소','zh-CN','ko')
        validate('130만 화소','1,300,000 pixels','ko','en-US')
        with self.assertRaises(ValueError):validate('130万像素','13만 화소','zh-CN','ko')
        with self.assertRaises(ValueError):validate('130万像素','130만 밀리미터','zh-CN','ko')
        for source,target in [('带载\v130万像素','帶載\v130萬像素'),('130万像素','1,300,000畫素'),
                ('1.3 million pixels','130萬個像素'),('650,000 pixels','650000個像素'),
                ('500mm*500mm','500×500公厘'),('60 Hz','60赫茲')]:
            with self.subTest(source=source,target=target):validate(source,target,'en-US','zh-Hant-TW')
        for source,target in [('130万像素','13萬像素'),('650,000 pixels','650個像素'),
                ('500mm*500mm','500×500公分'),('130万像素','130萬公厘'),('60 Hz','60')]:
            with self.subTest(source=source,target=target):
                with self.assertRaises(ValueError):validate(source,target,'en-US','zh-Hant-TW')

    def test_correct_shared_formula_needs_explicit_target_language_certificate(self):
        source='1 Gbps(109) × 使用率';q=LanguageReview('zh-CN','zh-Hant-TW')
        class Model:
            def __init__(self,cert):self.cert=cert;self.calls=[]
            def chat_json(inner,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0];inner.calls.append((payload,system))
                if '待译原文' in payload:return {'translation':source}
                answer={'ok':True,'issues':[]}
                if inner.cert:answer['unchanged_source_spans']=[{'text':s,'target_language':'zh-Hant-TW','valid':True,'reason':'共用字形，公式與臺灣用語均正確。'} for s in q.candidates(source,source)]
                return answer
        model=Model(True);result=translate_piece(model,source,None,'zh-CN','zh-Hant-TW',threading.Event(),quality=q,terminology=False)
        self.assertEqual(result,source);self.assertEqual(len(model.calls),2)
        self.assertIn('台湾繁体中文',model.calls[1][1]);self.assertNotIn('正确的日语',model.calls[1][1])
        wide='1 Gbps（109） × 使用率'
        q=LanguageReview('zh-CN','zh-Hant-TW')
        self.assertTrue(q.review_identical_formula(source,wide));self.assertIn(wide,q.candidates(source,wide))
        q.validate_review(source,wide,{'ok':True,'issues':[],'unchanged_source_spans':[{'text':wide,'target_language':'zh-Hant-TW','valid':True,'reason':'公式同文；全形括號只屬排版差異。'}]})
        validate(source,wide,'zh-CN','zh-Hant-TW',allow_identical=bool(q.proof(source,wide)))
        with self.assertRaisesRegex(ValueError,'逐项确认'):
            translate_piece(Model(False),source,None,'zh-CN','zh-Hant-TW',threading.Event(),quality=LanguageReview('zh-CN','zh-Hant-TW'),terminology=False)

    def test_script_inventory_and_untranslated_clauses_keep_protected_literals(self):
        self.assertEqual(chinese_script('带载','zh-Hant-TW'),'帶載')
        q=LanguageReview('zh-CN','zh-Hant-TW')
        self.assertIn('带載',q.candidates('带载','带載'))
        with self.assertRaises(IncompleteLanguageReview):q.validate_review('带载','带載',{'ok':True,'issues':[]})
        for dst,target in [('zh-CN','正文。The display supports the controller.'),('zh-Hant-TW','正文。The display supports the controller.'),
                           ('ja-JP','本文です。The display supports the controller.'),('ko','본문입니다. The display supports the controller.')]:
            with self.subTest(dst=dst):
                with self.assertRaisesRegex(ValueError,'英文句子'):validate('The display supports the controller.',target,'en-US',dst)
        validate('`The display supports the controller.` 說明','`The display supports the controller.` 说明','zh-Hant-TW','zh-CN')

    def test_equivalent_formula_survives_document_style_mapping_after_certification(self):
        from backend.multilingual_documents import mapped
        source='1 Gbps(109) × 使用率';target='1 Gbps（109） × 使用率'
        groups=[{'id':0,'text':'1 Gbps(10','key':()}, {'id':1,'text':'9','key':()}, {'id':2,'text':') × 使用率','key':()}]
        runs=[{'id':0,'text':'1 Gbps（10'}, {'id':1,'text':'9'}, {'id':2,'text':'） × 使用率'}]
        q=LanguageReview('zh-CN','zh-Hant-TW')
        class Model:
            def chat_json(self,prompt,**options):
                payload=json.loads(prompt)
                if '待译原文' in payload:return {'translation':target}
                if '原文' in payload:return {'ok':True,'issues':[],'unchanged_source_spans':[
                    {'text':s,'target_language':'zh-Hant-TW','valid':True,'reason':'公式共用字，括號排版等價。'} for s in q.candidates(source,target)]}
                if '译文样式片段' in payload:return {'ok':True,'issues':[]}
                return {'runs':runs}
        result=mapped(Model(),source,groups,{},'zh-CN','zh-Hant-TW',threading.Event(),'','faithful',quality=q)
        self.assertEqual(result,runs);self.assertIsNotNone(q.proof(source,target))

    def test_repair_is_bounded_and_only_failed_content_is_repeated(self):
        calls=Counter();items=[SimpleNamespace(id=str(i),file_path='fixture.pptx',slide=i,locator=str(i)) for i in range(3)]
        retried=[]
        def compute(item,repair_error=None):
            calls[item.id]+=1
            error=ValueError('original failure evidence') if item.id=='2' or item.id=='1' and repair_error is None else None
            if repair_error is not None:self.assertEqual(repair_error,'original failure evidence')
            return item,[] if error is None else None,[],error
        results=list(repaired_pages(items,compute,3,threading.Event(),lambda item:item,on_retry=lambda item,error:retried.append(item.id)))
        self.assertEqual(calls,{'0':1,'1':2,'2':2});self.assertEqual(len(results),3)
        self.assertEqual(len([r for r in results if r[3] is not None]),1);self.assertCountEqual(retried,['1','2'])

    def test_incomplete_review_schema_rechecks_same_translation_without_retranslation(self):
        source='刷新率'
        class Model:
            def __init__(self,persistent=False):self.translations=0;self.reviews=0;self.persistent=persistent
            def chat_json(self,prompt,**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' in payload:self.translations+=1;return {'translation':source}
                self.reviews+=1
                result={'ok':True,'unchanged_source_spans':[{'text':source,'target_language':'zh-Hant-TW','valid':True,'reason':'臺灣中文的共用字形，無需轉換。'}]}
                if self.reviews>1 and not self.persistent:
                    self_test.assertIn('issues',payload['上次完整性检查']);result['issues']=[]
                return result
        self_test=self
        model=Model()
        result=translate_piece(model,source,None,'zh-CN','zh-Hant-TW',threading.Event(),quality=LanguageReview('zh-CN','zh-Hant-TW'),terminology=False)
        self.assertEqual(result,source);self.assertEqual(model.translations,1);self.assertEqual(model.reviews,2)
        broken=Model(True)
        with self.assertRaisesRegex(ValueError,'完整的译文复核'):
            translate_piece(broken,source,None,'zh-CN','zh-Hant-TW',threading.Event(),quality=LanguageReview('zh-CN','zh-Hant-TW'),terminology=False)
        self.assertEqual(broken.translations,2);self.assertEqual(broken.reviews,4)

if __name__=='__main__':unittest.main()
