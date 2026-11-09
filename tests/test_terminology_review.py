"""Document translation is glossary-free; review must catch missed standards."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend import terminology_review as terms,workflow,text_languages
from backend.models import GlossaryEntry,Segment
from backend.glossary.loader import Glossary
from backend.extract import extract
import test_document_languages as fixtures

TABLE={'entries':[{'terms':{'zh-CN':'刷新率','en-US':'Refresh rate','ja-JP':'リフレッシュレート','ko':'재생률'}}]}


class TermModel(fixtures.Model):
    def __init__(self,target='レートは 60 Hz です。',decisions=None):
        super().__init__(target);self.term_calls=0;self.term_answer=decisions
    def chat_json(self,prompt,system='',**options):
        data=json.JSONDecoder().raw_decode(prompt)[0]
        if '术语待核对' in data:
            self.requests.append((prompt,system));self.term_calls+=1
            return self.term_answer if self.term_answer is not None else {'reviewed':True,'decisions':[
                {'id':row['id'],'status':'replace','original':'レート','replacement':row['targets'][0],
                 'reason':'The original names the refresh-rate parameter; use its confirmed Japanese standard.'}
                for row in data['术语待核对']]}
        return super().chat_json(prompt,system,**options)


class TerminologyTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    source=fixtures.DocumentLanguageTests.source
    job=fixtures.DocumentLanguageTests.job
    options=fixtures.DocumentLanguageTests.options

    def audit(self,model,*,source='刷新率为 60 Hz。',current='レートは 60 Hz です。',
              glossary=None,src='zh-CN',dst='ja-JP'):
        segment=Segment(id='p0',file='qa.docx',file_path=str(self.root/'qa.docx'),text=current,locator='p0')
        stats={'model_status':'complete','judged':1,'errors':0,'unreviewed':0,'warnings':[],
               'completed_files':[segment.file_path]}
        with patch('backend.terminology_review.catalog.read',return_value=TABLE):
            return terms.augment([segment],glossary or Glossary([]),[],stats,aligned_sources={'p0':source},
                source_language=src,target_language=dst,client=model,cancel=threading.Event(),workers=1)

    def test_term_missing_from_current_translation_is_checked_against_original(self):
        model=TermModel();findings,stats=self.audit(model)
        self.assertEqual(model.term_calls,1);self.assertEqual(stats['terminology_status'],'complete')
        self.assertEqual([(f.found_text,f.suggested,f.kind) for f in findings],[('レート','リフレッシュレート','term')])

    def test_english_notes_in_chinese_selected_document_are_not_exempt_from_terms(self):
        rows=terms.requirements('The refresh rate is 60 Hz.','レートは60 Hzです。',Glossary([]),TABLE,'zh-CN','ja-JP')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source'],'Refresh rate')

    def test_separate_review_resolves_explicit_original_pair_for_semantic_check(self):
        from backend.multilingual_documents import check_segments
        from backend.references import ReferenceIndex
        source=self.source('.txt','刷新率为 60 Hz。')
        target=self.root/'target.txt';target.write_text('リフレッシュレートは 60 Hz です。','utf-8')
        segments=extract(target);glossary=Glossary([])
        refs=ReferenceIndex([str(source)],glossary,{str(target):str(source)})
        model=TermModel()
        with patch('backend.terminology_review.catalog.read',return_value=TABLE):
            _,stats=check_segments(segments,glossary,client=model,references=refs,source_language='zh-CN',target_language='ja-JP',workers=1)
        payloads=[json.JSONDecoder().raw_decode(p)[0] for p,_ in model.requests]
        self.assertEqual(next(p['对应原文'] for p in payloads if '本段待校对文字' in p),'刷新率为 60 Hz。')
        self.assertEqual(stats['model_status'],'complete')

    def test_empty_model_result_cannot_silently_skip_required_terminology(self):
        model=TermModel(decisions={'reviewed':True,'decisions':[]});findings,stats=self.audit(model)
        self.assertFalse(findings);self.assertEqual(model.term_calls,2)
        self.assertEqual(stats['model_status'],'partial');self.assertEqual(stats['judged'],0)
        self.assertEqual(stats['unreviewed'],1);self.assertEqual(stats['completed_files'],[])
        self.assertTrue(any('漏掉' in warning for warning in stats['warnings']))

    def test_valid_standard_and_confirmed_alias_need_no_additional_model_call(self):
        model=TermModel();findings,stats=self.audit(model,current='リフレッシュレートは 60 Hz です。')
        self.assertFalse(findings);self.assertEqual(model.term_calls,0)
        g=Glossary([GlossaryEntry('刷新率','Refresh rate',variants=['refresh frequency'],priority=1)])
        self.assertFalse(terms.requirements('刷新率','refresh frequency',g,TABLE,'zh-CN','en-US'))

    def test_wrong_domain_can_be_explicitly_rejected_without_forced_replacement(self):
        g=Glossary([GlossaryEntry('工程裕量','margin',priority=1)])
        answer={'reviewed':True,'decisions':[{'id':'0','status':'not_applicable','reason':'This is gross margin in finance, not engineering margin.'}]}
        model=TermModel(decisions=answer)
        findings,stats=self.audit(model,source='The gross margin is 12%.',current='毛利率为 12%。',glossary=g,src='en-US',dst='zh-CN')
        self.assertFalse(findings);self.assertEqual(stats['model_status'],'complete');self.assertEqual(model.term_calls,1)

    def test_numeric_change_in_term_suggestion_is_rejected_and_not_cached(self):
        answer={'reviewed':True,'decisions':[{'id':'0','status':'replace','original':'レートは 60 Hz',
            'replacement':'リフレッシュレートは 61 Hz','reason':'Use the standard.'}]}
        model=TermModel(decisions=answer);findings,stats=self.audit(model)
        self.assertFalse(findings);self.assertEqual(model.term_calls,2);self.assertEqual(stats['model_status'],'partial')

    def test_missing_catalog_preserves_existing_results_and_reports_incomplete_check(self):
        row=Segment(id='p0',file='qa.docx',file_path=str(self.root/'qa.docx'),text='レートは 60 Hz です。',locator='p0')
        stats={'judged':1,'completed_files':[row.file_path]}
        with patch('backend.terminology_review.catalog.read',side_effect=ValueError('missing catalog')):
            findings,stats=terms.augment([row],Glossary([]),[],stats,client=TermModel(),target_language='ja-JP')
        self.assertFalse(findings);self.assertEqual(stats['terminology_status'],'partial')
        self.assertEqual(stats['judged'],0);self.assertEqual(stats['unreviewed'],1)
        self.assertTrue(any('missing catalog' in warning for warning in stats['warnings']))

    def test_one_correct_occurrence_cannot_hide_another_wrong_occurrence(self):
        rows=terms.requirements('刷新率、刷新率','リフレッシュレート、レート',Glossary([]),TABLE,'zh-CN','ja-JP')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source_occurrences'],2)
        self.assertEqual(rows[0]['standard_or_alias_occurrences'],1)

    def test_personal_english_standard_supersedes_official_english_for_other_source_languages(self):
        g=Glossary([GlossaryEntry('刷新率','Refresh frequency',variants=['Display refresh frequency'],priority=1)])
        rows=terms.requirements('リフレッシュレート','rate',g,TABLE,'ja-JP','en-US')
        self.assertEqual(rows[0]['targets'],['Refresh frequency'])
        self.assertFalse(terms.requirements('リフレッシュレート','Display refresh frequency',g,TABLE,'ja-JP','en-US'))

    def test_standalone_generation_has_no_glossary_and_combined_uses_and_applies_it(self):
        path=self.source('.docx','刷新率为 60 Hz。');glossary=Glossary([GlossaryEntry('刷新率','SENTINEL_GLOSSARY_ONLY',priority=1)])
        first=TermModel()
        with patch('backend.workflow.store.load_glossary',return_value=glossary),patch('backend.terminology_review.catalog.read',return_value=TABLE):
            translated=self.job(self.options(path,'zh-CN','ja-JP','translate'),first)
        self.assertEqual(translated['status'],'complete',translated)
        self.assertEqual(first.term_calls,0)
        for prompt,_ in first.requests:
            data=json.JSONDecoder().raw_decode(prompt)[0]
            self.assertNotIn('相关术语（仅作参考）',data);self.assertNotIn('相关术语',data)
            self.assertNotIn('SENTINEL_GLOSSARY_ONLY',prompt)
        self.assertIn('レートは 60 Hz',''.join(s.text for s in extract(translated['result']['outputs'][0]['path'])))
        second=TermModel()
        with patch('backend.workflow.store.load_glossary',return_value=glossary),patch('backend.terminology_review.catalog.read',return_value=TABLE):
            combined=self.job(self.options(path,'zh-CN','ja-JP'),second)
        self.assertEqual(combined['status'],'complete',combined)
        result=combined['result'];self.assertNotIn('report',result)
        output=result['outputs'][0];self.assertTrue(output['auto_exported']);self.assertFalse(output['unapplied_changes'])
        self.assertGreater(second.term_calls,0)
        self.assertTrue(any('相关术语（仅作参考）' in prompt and 'リフレッシュレート' in prompt for prompt,_ in second.requests))
        self.assertIn('リフレッシュレート',''.join(s.text for s in extract(output['path'])))

    def test_repeated_target_term_is_repaired_with_a_unique_full_paragraph(self):
        class Repeat(TermModel):
            def chat_json(inner,prompt,system='',**options):
                data=json.JSONDecoder().raw_decode(prompt)[0]
                if '术语待核对' not in data:return super().chat_json(prompt,system,**options)
                inner.term_calls+=1
                old='レート' if '定位修复' not in data else data['当前译文']
                new='リフレッシュレート' if '定位修复' not in data else 'リフレッシュレートとリフレッシュレートは60 Hzです。'
                return {'reviewed':True,'decisions':[{'id':'0','status':'replace','original':old,'replacement':new,'reason':'Use the confirmed parameter name at both occurrences.'}]}
        model=Repeat();findings,stats=self.audit(model,source='刷新率、刷新率均为60 Hz。',current='レートとレートは60 Hzです。')
        self.assertEqual(model.term_calls,2);self.assertEqual(stats['model_status'],'complete')
        self.assertEqual(len(findings),1);self.assertEqual(findings[0].found_text,'レートとレートは60 Hzです。')

    def test_free_text_still_receives_terms_in_generation_and_independent_review(self):
        model=TermModel('リフレッシュレート')
        result=text_languages.translate_piece(model,'刷新率',TABLE,'zh-CN','ja-JP',threading.Event())
        self.assertEqual(result,'リフレッシュレート')
        payloads=[json.JSONDecoder().raw_decode(p)[0] for p,_ in model.requests]
        self.assertEqual(payloads[0]['相关术语（仅作参考）'][0]['目标译法'],'リフレッシュレート')
        self.assertEqual(payloads[1]['相关术语'][0]['目标译法'],'リフレッシュレート')


if __name__=='__main__':unittest.main()
