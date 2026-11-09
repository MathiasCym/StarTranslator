"""Cross-language regressions for fixes first found in Japanese documents."""
import json
import threading
import unittest
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend import text_languages as text,workflow
from backend.multilingual_quality import LanguageReview
from backend.extract import extract
import test_document_languages as fixtures

SOURCE='Connect to one output port. Frequency: 60 Hz.'
TARGETS={
    'zh-CN':'连接一个输出端口。频率：60 Hz。',
    'zh-Hant-TW':'連接一個輸出連接埠。頻率：60 Hz。',
    'ja-JP':'一つの出力ポートに接続します。周波数：60 Hz。',
    'ko':'출력 포트 한 개에 연결하세요. 주파수: 60 Hz.'}


class Model(fixtures.Model):
    def chat_json(self,prompt,system='',**options):
        data=json.JSONDecoder().raw_decode(prompt)[0];self.requests.append((prompt,system))
        if '待译原文' in data:
            self.translations+=1;return {'translation':self.target}
        if '译文' in data:return {'ok':True,'issues':[]}
        if '本段待校对文字' in data or '中文译文' in data:
            current=data.get('本段待校对文字',data.get('中文译文'))
            return {'reviewed':True,'suggestions':[{'original':'TEST TEST','replacement':'TEST','reason':'Remove duplicate label.'}] if 'TEST TEST' in current else []}
        raise AssertionError('Unexpected model request: '+prompt[:120])


class CrossLanguageTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    source=fixtures.DocumentLanguageTests.source
    job=fixtures.DocumentLanguageTests.job
    options=fixtures.DocumentLanguageTests.options

    def test_written_quantities_and_wrong_counts_in_every_document_target(self):
        for dst,target in TARGETS.items():
            with self.subTest(target=dst):
                text.validate(SOURCE,target,'en-US',dst)
                text.validate(SOURCE,target.replace('60','60'),'zh-CN',dst)
                with self.assertRaises(ValueError):text.validate(SOURCE,target.replace('60','61'),'en-US',dst)
                with self.assertRaises(ValueError):text.validate(SOURCE,target+' 1','en-US',dst)
        for source,target in [('Connect to one output port.','출력 포트 한 개에 연결하세요.'),
                ('Connect to one output port.','출력 포트 하나에 연결하세요.'),
                ('Connect to one output port.','하나의 출력 포트에 연결하세요.'),
                ('Connect to twenty-four controllers.','컨트롤러 스물네 대에 연결하세요.'),
                ('Use one bit.','한 비트를 사용하세요.'),
                ('連接一個輸出連接埠。','Connect to an output port.'),
                ('Connect to a controller.','컨트롤러 한 대에 연결하세요.')]:
            text.validate(source,target,'en-US','ko')
        text.validate("Hana's controller.",'하나의 컨트롤러.','en-US','ko')
        for bad in ('출력 포트 두 개에 연결하세요.','출력 포트에 연결하세요.','출력 포트 한 개와 컨트롤러 한 대에 연결하세요.'):
            with self.assertRaises(ValueError):text.validate('Connect to one output port.',bad,'en-US','ko')
        self.assertEqual(text.written_counts('대한 개발 한편 Hana 하나'),'대한 개발 한편 Hana 하나')

    def test_every_target_six_formats_translate_review_apply_and_save(self):
        for dst,target in TARGETS.items():
            for suffix in ('.docx','.pptx','.pdf','.xlsx','.txt','.md'):
                with self.subTest(target=dst,format=suffix):
                    path=self.source(suffix,SOURCE,dst+suffix);before=path.read_bytes();model=Model(target)
                    job=self.job(self.options(path,'en-US',dst),model)
                    self.assertEqual(job['status'],'complete',job.get('error') or job.get('result'))
                    result=job['result'];output=result['outputs'][0]
                    self.assertEqual(output['resumed_segments'],0);self.assertTrue(output['translation_complete'])
                    self.assertEqual(output['review_status'],'complete')
                    self.assertTrue(output['auto_exported']);self.assertNotIn('report',result)
                    self.assertFalse(output['unapplied_changes']);self.assertEqual(output['output_audit']['status'],'complete')
                    self.assertIn(target,'\n'.join(s.text for s in extract(output['path']) if s.editable))
                    self.assertEqual(path.read_bytes(),before)

    def test_semantic_review_context_and_disputed_wording_are_shared(self):
        for dst,target in TARGETS.items():
            with self.subTest(target=dst):
                class Disputed(Model):
                    def chat_json(inner,prompt,system='',**options):
                        data=json.JSONDecoder().raw_decode(prompt)[0]
                        if '译文' in data:
                            inner.requests.append((prompt,system));self.assertEqual(data['相邻原文（仅供理解）'],'same page context')
                            if '待独立裁定的复核意见' not in data:
                                return {'ok':False,'issues':['Prefer a different industry wording.'],'corrected_translation':target+' '}
                            return {'ok':True,'issues':[]}
                        return super().chat_json(prompt,system,**options)
                model=Disputed(target)
                value=text.translate_piece(model,SOURCE,None,'en-US',dst,threading.Event(),context='same page context',terminology=False,quality=LanguageReview('en-US',dst))
                self.assertEqual(value,target);self.assertEqual(model.translations,1)
                for prompt,_ in model.requests:self.assertNotIn('相关术语',prompt)

    def test_ppt_suggestion_soft_break_saves_natively_for_every_target(self):
        for dst,target in TARGETS.items():
            with self.subTest(target=dst):
                path=self.source('.pptx',target+' TEST TEST',dst);model=Model(target)
                job=self.job(self.options(path,'en-US',dst,'check'),model);report=job['result']
                self.assertEqual(len(report['findings']),1)
                saved=workflow.apply_report({'report_id':report['report_id'],'path':str(path),'edits':[{'index':0,'text':'TEST\vTEST'}]},client=model)
                self.assertFalse(saved.get('failed'));self.assertIn('TEST\vTEST',''.join(s.text for s in extract(saved['output'])))


if __name__=='__main__':unittest.main()
