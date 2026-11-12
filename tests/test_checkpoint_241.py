"""Exact shipped-policy compatibility cannot cross task or content boundaries."""
import os,sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend.checkpoints import Checkpoint,SHIPPED_241,SHIPPED_244
from backend.task_resume import activate
import test_document_languages as fixtures

class ScopeTests(unittest.TestCase):
    def test_shipped_scopes_require_original_task_model_and_language_and_do_not_write_in_read_only_mode(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NOVATERM_DATA_DIR':folder}):
            identity={'source':'fixture.docx','fingerprint':'original','direction':'zh-CN>ko','model':{'model':'original'}}
            for stage,old_policy in [*SHIPPED_241.items(), *SHIPPED_244.items()]:
                with self.subTest(stage=stage),activate('original-task'):
                    with patch('backend.checkpoints.policy',return_value=old_policy):Checkpoint(stage,identity).put('one',{'translation':'valid cached text'})
                    data=Checkpoint(stage,identity,read_only=True)
                    self.assertEqual(data.get('one'),{'translation':'valid cached text'})
                    self.assertIsNone(Checkpoint(stage,{**identity,'direction':'zh-CN>ja-JP'},read_only=True).get('one'))
                    self.assertIsNone(Checkpoint(stage,{**identity,'model':{'model':'different'}},read_only=True).get('one'))
                    self.assertIsNone(Checkpoint(stage,{**identity,'fingerprint':'changed'},read_only=True).get('one'))
                with activate('new-task'):self.assertIsNone(Checkpoint(stage,identity,read_only=True).get('one'))

class WorkflowTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    source=fixtures.DocumentLanguageTests.source
    job=fixtures.DocumentLanguageTests.job
    options=fixtures.DocumentLanguageTests.options
    def test_old_whole_paragraph_with_invalid_spacer_style_remaps_without_retranslation(self):
        from docx import Document
        from docx.shared import RGBColor
        from backend import multilingual_documents as documents
        path=self.root/'spacer.docx';doc=Document();p=doc.add_paragraph()
        for value,color in [('网口','FFFFFF'),(' ','000000'),('带载','FFFF00')]:
            r=p.add_run(value);r.font.color.rgb=RGBColor.from_string(color)
        doc.save(path)
        target='포트 부하'
        class Cache:
            resumed=0;available=True;warning=''
            def get(self,key):
                return None if key[0]=='verified-content' else {'translation':target,
                    'runs':[{'id':0,'text':'포트 '},{'id':1,'text':'부하'},{'id':2,'text':''}]}
            def used(self):self.resumed+=1
            def put(self,key,value):pass
        class Model(fixtures.Model):
            def chat_json(inner,prompt,**options):
                payload=json.loads(prompt)
                self.assertNotIn('待译原文',payload,'Verified text must not be translated again')
                if '译文样式片段' in payload:return {'ok':True,'issues':[]}
                self.assertEqual(payload['已复核的完整译文'],target)
                return {'runs':[{'id':0,'text':'포트 '},{'id':1,'text':''},{'id':2,'text':'부하'}]}
        cache=Cache()
        with patch('backend.multilingual_documents.open_checkpoint',return_value=cache):
            result=documents.translate_file(str(path),fixtures.Glossary([]),None,client=Model(target),direction='zh-CN>ko')
        self.assertTrue(result['translation_complete'],result.get('review_items'))
        output=Document(result['path']).paragraphs[0]
        self.assertEqual(output.text,target);self.assertEqual(result['resumed_segments'],1)
        self.assertTrue(all(r.font.color.rgb!=RGBColor.from_string('000000') for r in output.runs if r.text.strip()))

    def test_explicit_241_korean_resume_reuses_validated_segment_but_fresh_task_does_not(self):
        from docx import Document
        path=self.source('.docx',fixtures.SAMPLES['zh-CN']);doc=Document(path);doc.add_paragraph(fixtures.SAMPLES['zh-CN']+' A9');doc.save(path)
        class Model(fixtures.Model):
            def chat_json(self,prompt,**options):
                value=super().chat_json(prompt,**options);payload=json.JSONDecoder().raw_decode(prompt)[0]
                if isinstance(value,dict) and 'translation' in value and 'A9' in payload.get('待译原文',''):value={**value,'translation':value['translation']+' A9'}
                return value
        data=self.options(path,'zh-CN','ko',kind='translate')
        with patch('backend.checkpoints.policy',side_effect=lambda stage:SHIPPED_241[stage]):first=self.job(data,Model(fixtures.SAMPLES['ko'],cancel_after=1))
        self.assertEqual(first['status'],'cancelled')
        resumed_model=Model(fixtures.SAMPLES['ko']);resumed=self.job({'resume_from':first['id']},resumed_model)
        self.assertEqual(resumed['status'],'complete',resumed.get('result'));self.assertEqual(resumed_model.translations,1)
        self.assertGreaterEqual(resumed['result']['outputs'][0]['resumed_segments'],1)
        fresh_model=Model(fixtures.SAMPLES['ko']);fresh=self.job(data,fresh_model)
        self.assertEqual(fresh['status'],'complete');self.assertEqual(fresh_model.translations,2)
        self.assertEqual(fresh['result']['outputs'][0]['resumed_segments'],0)

if __name__=='__main__':unittest.main()
