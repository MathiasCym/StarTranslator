"""English-to-Chinese format writers and English-only policy isolation."""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor
from pptx import Presentation
from pptx.util import Inches, Pt
from openpyxl import Workbook, load_workbook
from backend import workflow, task_queue, comparison
from backend.translation import translate_file
from backend.reverse_translation import audit_saved
from backend.extract import extract
from backend.extract.office import open_office
from backend.glossary.loader import Glossary
from backend.glossary import store
from backend.llm.client import LLMClient

SOURCE = 'The pixel pitch is 2.5 mm.'
TARGET = '点间距为 2.5 mm。'


class Model(LLMClient):
    def __init__(self, suggestions=False):
        self.provider='compatible';self.base_url='http://127.0.0.1:1/v1';self.model='reverse-fixture';self.api_format='openai'
        self.calls=[];self.suggestions=suggestions
    def chat_json(self, prompt, system='', **options):
        self.calls.append((prompt,system))
        data=json.loads(prompt)
        if '复核' in system and '"ok"' in system:return {'ok':True,'issues':[]}
        if '审校员' in system:
            return {'reviewed':True,'suggestions':[{'original':data['中文译文'],'replacement':'像素间距为 2.5 mm。','reason':'统一中文术语'}] if self.suggestions and data['中文译文']==TARGET else []}
        source=data['待译原文']
        target=TARGET if source==SOURCE else '屏幕支持 60 Hz。' if source=='The display supports 60 Hz.' else source
        result={'translation':target}
        if data.get('原文样式片段'):
            groups=data['原文样式片段']
            if len(groups)==2 and groups[0]['text']=='The pixel pitch':
                result['runs']=[{'id':groups[0]['id'],'text':'点间距'},{'id':groups[1]['id'],'text':'为 2.5 mm。'}]
            else:result['runs']=[{'id':g['id'],'text':target if i==0 else ''} for i,g in enumerate(groups)]
        return result


class ReverseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'profile')});env.start();self.addCleanup(env.stop)
        self.glossary=Glossary([])
        stub=patch('backend.workflow.store.load_glossary',return_value=self.glossary);stub.start();self.addCleanup(stub.stop)
        self.previous=dict(workflow.JOBS);self.reports=dict(workflow.REPORTS)
        workflow.JOBS.clear();workflow.REPORTS.clear();self.addCleanup(self.restore)
    def restore(self):
        workflow.JOBS.clear();workflow.JOBS.update(self.previous);workflow.REPORTS.clear();workflow.REPORTS.update(self.reports)
    def doc(self):
        file=self.root/'source.docx';doc=Document();p=doc.add_paragraph()
        run=p.add_run('The pixel pitch');run.bold=True;run.font.color.rgb=RGBColor(255,0,0)
        p.add_run(' is 2.5 mm.')
        table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='The display supports 60 Hz.'
        h=doc.add_paragraph();link=OxmlElement('w:hyperlink');link.set(qn('w:anchor'),'keep')
        r=OxmlElement('w:r');t=OxmlElement('w:t');t.text='https://example.com/中文';r.append(t);link.append(r);h._p.append(link)
        doc.save(file);return file
    def test_word_styles_tables_links_and_direction_specific_cache(self):
        source=self.doc();before=store.fingerprint(source);model=Model()
        result=translate_file(source,self.glossary,None,client=model,direction='en-zh')
        self.assertTrue(result['translation_complete']);self.assertEqual(result['output_audit']['status'],'complete')
        doc=Document(result['path']);self.assertEqual(doc.paragraphs[0].text,TARGET)
        self.assertTrue(doc.paragraphs[0].runs[0].bold);self.assertEqual(str(doc.paragraphs[0].runs[0].font.color.rgb),'FF0000')
        self.assertEqual(doc.tables[0].cell(0,0).text,'屏幕支持 60 Hz。')
        self.assertEqual(store.fingerprint(source),before)
        record=comparison.read(result['comparison_id']);self.assertEqual(record['direction'],'en-zh')
        second=Model();again=translate_file(source,self.glossary,None,client=second,direction='en-zh')
        self.assertEqual(again['resumed_segments'],2);self.assertEqual(second.calls,[])
        with patch('backend.translation.mapped_translation',side_effect=AssertionError('English policy must not run')):
            translate_file(source,self.glossary,None,client=Model(),direction='en-zh')
    def test_ppt_preserves_color_bold_and_passes_chinese_target_to_visual_review(self):
        source=self.root/'source.pptx';deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        shape=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(6),Inches(2));p=shape.text_frame.paragraphs[0]
        a=p.add_run();a.text='The pixel pitch';a.font.bold=True;a.font.size=Pt(24)
        b=p.add_run();b.text=' is 2.5 mm.';b.font.size=Pt(24);deck.save(source)
        with (patch('backend.pptx_visual_review.review_pptx',return_value=([],[])) as visual,
                patch('backend.officecli_bridge.inspect',return_value={}),patch('backend.officecli_bridge.compare',return_value=[])):
            result=translate_file(source,self.glossary,None,client=Model(),direction='en-zh')
        self.assertEqual(visual.call_args.kwargs['target_language'],'zh')
        output=Presentation(result['path']);self.assertEqual(output.slides[0].shapes[0].text,TARGET)
        self.assertTrue(output.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.bold)
    def test_all_editable_text_containers(self):
        fixtures={'.txt':SOURCE+'\r\n', '.md':'# '+SOURCE+'\n\n[Link](https://example.com/中文)',
            '.html':'<p>'+SOURCE+'</p><a href="https://example.com/中文">NOVA</a>',
            '.json':json.dumps({'keep-key':SOURCE,'url':'https://example.com/中文'}),
            '.srt':'1\n00:00:01,000 --> 00:00:03,000\n'+SOURCE+'\n',
            '.ass':'[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,'+SOURCE+'\n'}
        for extension,content in fixtures.items():
            with self.subTest(extension=extension):
                source=self.root/('source'+extension);source.write_text(content,encoding='utf-8')
                result=translate_file(source,self.glossary,None,client=Model(),direction='en-zh')
                self.assertIn(TARGET,'\n'.join(s.text for s in extract(result['path'])))
                self.assertTrue(result['translation_complete'])
                self.assertEqual(result['output_audit']['status'],'complete')
                if extension in ('.md','.html'):self.assertIn('https://example.com/中文',Path(result['path']).read_text(encoding='utf-8'))
                if extension=='.json':self.assertEqual(json.loads(Path(result['path']).read_text(encoding='utf-8'))['url'],'https://example.com/中文')
        source=self.root/'source.xlsx';book=Workbook();book.active['A1']=SOURCE;book.active['B1']='=1+2';book.save(source)
        result=translate_file(source,self.glossary,None,client=Model(),direction='en-zh')
        out=load_workbook(result['path']);self.assertEqual(out.active['A1'].value,TARGET);self.assertEqual(out.active['B1'].value,'=1+2');out.close()
        source=self.root/'source.epub'
        with ZipFile(source,'w') as package:
            package.writestr('mimetype','application/epub+zip')
            package.writestr('META-INF/container.xml','<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>')
            package.writestr('OPS/content.opf','<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="page" href="page.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="page"/></spine></package>')
            package.writestr('OPS/page.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><body><p>'+SOURCE+'</p></body></html>')
        result=translate_file(source,self.glossary,None,client=Model(),direction='en-zh')
        self.assertIn(TARGET,'\n'.join(s.text for s in extract(result['path'])))
    def test_pdf_text_layer_uses_chinese_output_without_english_residual_audit(self):
        from test_file_formats import pdf_fixture
        source=self.root/'source.pdf';pdf_fixture(source,SOURCE)
        with patch('backend.pdf_quality.audit',side_effect=AssertionError('English-only PDF audit must not run')):
            result=translate_file(source,self.glossary,None,client=Model(),direction='en-zh')
        self.assertEqual(Path(result['path']).suffix,'.docx')
        self.assertIn(TARGET,'\n'.join(s.text for s in extract(result['path'])))
        self.assertTrue(any('图片内英文' in w['reason'] for w in result['warnings']))
    def test_combined_review_save_unchanged_and_apply_chinese_suggestion(self):
        source=self.doc();model=Model(suggestions=True)
        with patch('backend.workflow.LLMClient',return_value=model),patch('backend.translation.LLMClient',return_value=model):
            job=workflow.start({'kind':'translate_review','direction':'en-zh','paths':[str(source)],'combined_output':'final'})
            final=asyncio.run(task_queue.wait(job['id'],.005))
        self.assertEqual(final['status'],'complete',final.get('error'))
        report=final['result']['report'];self.assertTrue(report['findings'])
        path=report['files'][0]['path'];data={'report_id':job['id'],'path':path,'save_unchanged':True}
        with patch('backend.translation_audit.saved_residuals',side_effect=AssertionError('Chinese is intended')):
            saved=workflow.apply_report(data)
        self.assertIn('Chinese_checked',saved['output']);self.assertEqual(saved['untranslated'],0)
        applied=workflow.apply_report({**data,'edits':[{'index':0,'text':'像素间距为 2.5 mm。'}]})
        self.assertEqual(Document(applied['output']).paragraphs[0].text,'像素间距为 2.5 mm。')
        self.assertEqual(comparison.read(applied['comparison_id'])['output_path'],applied['output'])
        options=__import__('backend.history',fromlist=['resume_options']).resume_options(job['id'])
        self.assertEqual(options['direction'],'en-zh')
    def test_chinese_proofreading_does_not_route_back_to_english(self):
        source=self.root/'chinese.docx';doc=Document();doc.add_paragraph(TARGET);doc.save(source)
        with (patch('backend.workflow.LLMClient',return_value=Model()),
              patch('backend.workflow.predominantly_chinese',side_effect=AssertionError('Do not translate intended Chinese back to English'))):
            job=workflow.start({'kind':'check','direction':'en-zh','paths':[str(source)],'use_llm':True})
            result=asyncio.run(task_queue.wait(job['id'],.005))
        self.assertEqual(result['status'],'complete');self.assertEqual(result['kind'],'check')
        self.assertEqual(result['result']['stats']['target_language'],'zh')
        self.assertEqual(Document(source).paragraphs[0].text,TARGET)


if __name__=='__main__':unittest.main()
