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
    def test_ordinal_ranks_are_equivalent_but_changed_rank_is_rejected(self):
        for src,dst,source,target in [
            ('zh-CN','ko','中国银幕数量位居世界第一','중국 스크린 수는 세계 1위입니다'),
            ('zh-CN','ja-JP','位居世界第一','世界一です'),
            ('zh-CN','zh-Hant-TW','世界第一','世界第一'),
            ('zh-CN','en-US','世界第一','first in the world'),
            ('en-US','ko','the third display','세 번째 디스플레이'),
        ]:
            with self.subTest(src=src,dst=dst):validate(source,target,src,dst,allow_identical=True)
        for target in ('세계 2위입니다','second in the world','世界第二'):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):validate('世界第一',target,'zh-CN','ko')
        validate('首先检查连接','First check the connection','zh-CN','en-US')
        validate('世界一流技术','world-class technology','zh-CN','en-US')

    def test_korean_document_titles_are_translated_and_original_name_glosses_allowed(self):
        source='2021年《“十四五”规划》'
        validate(source,'2021년 제14차 5개년 계획','zh-CN','ko')
        with self.assertRaisesRegex(ValueError,'未译汉字'):
            validate(source,'2021년 《“十四五”规划》','zh-CN','ko')
        with self.assertRaises(ValueError):
            validate(source,'2021년 제15차 5개년 계획','zh-CN','ko')
        validate('中影完成制版','중국영화(中影)가 마스터링을 완료했다','zh-CN','ko')
        with self.assertRaisesRegex(ValueError,'未译汉字'):
            validate('中影完成制版','中影가 마스터링을 완료했다','zh-CN','ko')

    def test_exact_scaled_quantities_grouping_counters_and_dimensions(self):
        validate('21.4万块，市场体量庞大','21만 4천 개, 시장 규모가 방대하다','zh-CN','ko')
        validate('亮度≥300尼特，支持4K 120Hz','밝기 ≥ 300니트, 4K 120Hz 지원','zh-CN','ko')
        validate('2024 六部委方案','2024 6개 부처 방안','zh-CN','ko')
        with self.assertRaises(ValueError):validate('2024 六部委方案','2024 5개 부처 방안','zh-CN','ko')
        validate('保证每一块LED屏幕显示准确','모든 LED 화면의 정확한 표시를 보장합니다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('保证每两块LED屏幕显示准确','모든 LED 화면의 정확한 표시를 보장합니다','zh-CN','ko')
        validate('基于一个基础假设','기본 가정에 근거합니다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('基于两个基础假设','기본 가정에 근거합니다','zh-CN','ko')
        validate('实现从零到一的突破','0에서 1로의 돌파구를 마련했다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('实现从零到一的突破','0에서 2로의 돌파구를 마련했다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('亮度≥300尼特','밝기 ≥ 300밀리미터','zh-CN','ko')
        with self.assertRaises(ValueError):validate('21.4万块','21만 5천 개','zh-CN','ko')
        with self.assertRaises(ValueError):validate('21.4万块','21만, 4천 개','zh-CN','ko')
        validate('为影院打造的一套LED控制系统','영화관용 LED 제어 시스템','zh-CN','ko')
        with self.assertRaises(ValueError):validate('为影院打造的两套LED控制系统','영화관용 LED 제어 시스템','zh-CN','ko')
        with self.assertRaises(ValueError):validate('为影院打造的一套LED控制系统','영화관용 여러 LED 시스템들','zh-CN','ko')
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

    def test_combined_review_arbitrates_an_invented_unit_without_weakening_validation(self):
        from unittest.mock import patch
        from backend import document_translation_policy as policy
        source='设备支持多种场景，最大处理量为360万，可满足'
        target='장비는 다양한 환경을 지원하며 최대 처리량은 360만으로, 충족할 수 있는 범위는'
        class Model:
            def __init__(self,accept):
                self.accept=accept;self.calls=[]
            def chat_json(self,prompt,**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                self.calls.append(payload)
                if '待译原文' in payload:return {'translation':target}
                if '待独立裁定的复核意见' in payload and self.accept:return {'ok':True,'issues':[]}
                return {'ok':False,'issues':['要求补写像素单位'],
                        'corrected_translation':target.replace('360만','360만 화소')}
        with policy.combined_processing(True),patch.object(policy,'reference',return_value={}):
            accepted=Model(True)
            self.assertEqual(translate_piece(accepted,source,None,'zh-CN','ko',threading.Event()),target)
            self.assertEqual(len(accepted.calls),3)
            self.assertEqual(accepted.calls[-1]['译文'],target)
            self.assertIn('待独立裁定的复核意见',accepted.calls[-1])
            with self.assertRaisesRegex(ValueError,'增加了数值单位'):
                translate_piece(Model(False),source,None,'zh-CN','ko',threading.Event())

if __name__=='__main__':unittest.main()
