"""Actual Office script evidence is shared, never guessed from plain text."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend.review_format import attach,hints,normalize_suggestion
from backend.extract import extract
from backend.text_languages import validate
import test_document_languages as fixtures


def deck(path,label):
    from pptx import Presentation
    from pptx.util import Inches
    d=Presentation();slide=d.slides.add_slide(d.slide_layouts[6])
    p=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(1)).text_frame.paragraphs[0]
    p.add_run().text='1 Gbps(10';r=p.add_run();r.text='9';r._r.get_or_add_rPr().set('baseline','30000');p.add_run().text=') × '+label
    slide.shapes.add_textbox(Inches(1),Inches(3),Inches(8),Inches(1)).text='TEST TEST'
    d.save(path)


class ScriptTests(unittest.TestCase):
    def test_missing_or_unreadable_optional_package_does_not_discard_supplied_text(self):
        from backend.models import Segment
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing.docx'
            segment=Segment('fixture',path.name,'Supplied review text','body/0',file_path=str(path))
            attach([segment]);self.assertEqual(hints(segment),{});self.assertEqual(segment.text,'Supplied review text')
            path.write_bytes(b'unreadable package');attach([segment])
            self.assertEqual(hints(segment),{});self.assertEqual(path.read_bytes(),b'unreadable package')
    def test_reads_real_ppt_metadata_and_discards_only_duplicate_script_representation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'formula.pptx';deck(path,'usage rate');before=path.read_bytes()
            segment=next(s for s in extract(path) if 'Gbps' in s.text);attach([segment])
            self.assertEqual(hints(segment)['当前文字真实上下标'],[{'start':9,'end':10,'text':'9','baseline':'30000'}])
            proposed=segment.text.replace('109','10⁹')
            self.assertEqual(normalize_suggestion(segment,segment.text,proposed),(segment.text,segment.text))
            mixed=proposed.replace('usage rate','utilization rate')
            self.assertEqual(normalize_suggestion(segment,segment.text,mixed)[1],mixed.replace('10⁹','109'))
            segment._script_positions=[]
            self.assertEqual(normalize_suggestion(segment,segment.text,proposed),(segment.text,proposed))
            self.assertEqual(path.read_bytes(),before)

    def test_word_subscript_and_same_language_revision_keep_factual_guards(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'formula.docx';doc=Document();p=doc.add_paragraph();p.add_run('H');r=p.add_run('2');r.font.subscript=True;p.add_run('O');doc.save(path)
            segment=next(s for s in extract(path) if s.text=='H2O');attach([segment])
            self.assertEqual(normalize_suggestion(segment,'H2O','H₂O'),('H2O','H2O'))
        validate('The brightness is 500 nits.','The Brightness is 500 nits.','en-US','en-US')
        with self.assertRaises(ValueError):validate('The brightness is 500 nits.','The brightness is 50 nits.','en-US','en-US')


class WorkflowTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    job=fixtures.DocumentLanguageTests.job

    def test_all_document_review_languages_receive_real_script_evidence_and_keep_real_advice(self):
        from backend import workflow
        labels={'en-US':'usage rate','zh-CN':'使用率','zh-Hant-TW':'使用率','ja-JP':'使用率','ko':'사용률'}
        class Model(fixtures.Model):
            def __init__(self):super().__init__('unused');self.script_requests=0
            def chat_json_recoverable(self,prompt,**options):
                current=prompt.split('【待审校段落】\n',1)[1].split('\n\n输出 JSON 数组。',1)[0]
                if 'Gbps' in current:
                    self.script_requests+=int('当前文字真实上下标' in prompt)
                    text='1 Gbps(109) × usage rate'
                    return [{'found':text,'suggested':text.replace('109','10⁹'),'reason':'incorrectly assume missing superscript','kind':'grammar'}],False
                return [{'found':'TEST TEST','suggested':'TEST','reason':'actual repeated word','kind':'grammar'}],False
            def chat_json(self,prompt,**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0];text=payload.get('本段待校对文字',payload.get('中文译文',''))
                if 'Gbps' in text:
                    self.script_requests+=int(bool(payload.get('当前文字真实上下标')))
                    return {'reviewed':True,'suggestions':[{'original':text,'replacement':text.replace('109','10⁹'),'reason':'incorrectly assume missing superscript'}]}
                return {'reviewed':True,'suggestions':[{'original':'TEST TEST','replacement':'TEST','reason':'actual repeated word'}]}
        for language,label in labels.items():
            with self.subTest(language=language):
                path=self.root/(language+'.pptx');deck(path,label);before=path.read_bytes();model=Model()
                job=self.job({'kind':'check','paths':[str(path)],'target_language':language,'workers':1},model)
                self.assertEqual(job['status'],'complete',job.get('result'));self.assertGreaterEqual(model.script_requests,1)
                report=job['result'];self.assertEqual(len(report['findings']),1,report['findings'])
                self.assertEqual(report['findings'][0]['found_text'],'TEST TEST')
                saved=workflow.apply_report({'report_id':report['report_id'],'path':str(path),'edits':[{'index':0,'text':'TEST'}]},client=model)
                self.assertEqual(saved['failed'],[]);self.assertEqual(path.read_bytes(),before)
                copied=next(s for s in extract(saved['output']) if 'Gbps' in s.text);attach([copied])
                self.assertEqual(hints(copied)['当前文字真实上下标'][0]['baseline'],'30000')
                self.assertIn('109',copied.text);self.assertNotIn('10⁹',copied.text)

if __name__=='__main__':unittest.main()
