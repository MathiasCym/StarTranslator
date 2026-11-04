"""Offline workflow contracts, not a substitute for native/model quality QA."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from zipfile import ZipFile,ZIP_STORED
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from backend import document_languages as languages, workflow, task_queue, history, comparison
from backend import multilingual_documents as documents
from backend.glossary.loader import Glossary
from backend.extract import extract
from backend.llm.client import LLMClient,LLMUnavailable
import test_checkpoint_process

SAMPLES={
 'zh-CN':'请勿关闭 A8 控制器。频率为 60 Hz。参见 https://example.com/中文',
 'zh-Hant-TW':'請勿關閉 A8 控制器。頻率為 60 Hz。參見 https://example.com/中文',
 'en-US':'Do not turn off the A8 controller. The frequency is 60 Hz. See https://example.com/中文',
 'ja-JP':'A8 コントローラーの電源を切らないでください。周波数は 60 Hz です。https://example.com/中文 を参照。',
 'ko':'A8 컨트롤러를 끄지 마세요. 주파수는 60 Hz입니다. https://example.com/中文 참조.'}


class Model(LLMClient):
 def __init__(self,target,cancel_after=None):
  self.provider='compatible';self.base_url='http://127.0.0.1:1/v1';self.model='multilingual-contract-fixture';self.api_format='openai'
  self.target=target;self.requests=[];self.translations=0;self.cancel_after=cancel_after
 def chat_json(self,prompt,system='',**options):
  self.requests.append((prompt,system));payload=json.JSONDecoder().raw_decode(prompt)[0]
  if '本段待校对文字' in payload:
   return {'reviewed':True,'suggestions':[{'original':'TEST TEST','replacement':'TEST','reason':'删除重复单词'}] if 'TEST TEST' in payload['本段待校对文字'] else []}
  if '待译原文' in payload:
   if self.cancel_after is not None and self.translations>=self.cancel_after:
    self.cancel.set();raise workflow.Cancelled('offline fixture interruption')
   self.translations+=1;return {'translation':self.target}
  if '译文' in payload:return {'ok':True,'issues':[]}
  raise AssertionError('Unexpected model contract: '+prompt[:100])


class DocumentLanguageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'profile')});env.start();self.addCleanup(env.stop)
  self.jobs=dict(workflow.JOBS);self.reports=dict(workflow.REPORTS);workflow.JOBS.clear();workflow.REPORTS.clear()
  self.addCleanup(self.restore)
  self.stubs=ExitStack();self.addCleanup(self.stubs.close)
  for name,value in [('backend.workflow.store.load_glossary',Glossary([])),('backend.officecli_bridge.inspect',{}),
      ('backend.officecli_bridge.compare',[]),('backend.pptx_visual_review.review_pptx',([],[])),
      ('backend.workflow.review_pptx',([],[]))]:self.stubs.enter_context(patch(name,return_value=value))
 def restore(self):
  workflow.JOBS.clear();workflow.JOBS.update(self.jobs);workflow.REPORTS.clear();workflow.REPORTS.update(self.reports)
 def source(self,suffix,source,sub=''):
  folder=self.root/sub;folder.mkdir(parents=True,exist_ok=True)
  return test_checkpoint_process.CheckpointProcessTests.source(self,folder,suffix,[source])
 def job(self,data,client):
  with patch('backend.workflow.LLMClient',return_value=client):
   job=workflow.start(data);return asyncio.run(task_queue.wait(job['id'],.005))
 def options(self,path,src,dst,kind='translate_review'):
  return {'kind':kind,'paths':[str(path)],'source_language':src,'target_language':dst,'workers':1,
      'combined_output':'final','output_dir':str(self.root/'output')}

 def test_five_languages_twenty_pairs_and_independent_targets_are_canonical(self):
  seen=set()
  for src in languages.LANGUAGES:
   for dst in languages.LANGUAGES:
    if src==dst:continue
    value=languages.normalize({'kind':'translate','source_language':src,'target_language':dst})
    self.assertEqual(languages.pair(value['direction']),(src,dst));seen.add(value['direction'])
  self.assertEqual(len(seen),20)
  for dst in languages.LANGUAGES:
   self.assertEqual(languages.pair(languages.normalize({'kind':'check','target_language':dst})['direction'])[1],dst)
  self.assertEqual(languages.pair('en-US>zh-TW'),('en-US','zh-Hant-TW'))
  for value in (None,{},'x','en-US>en-US','en-US>fr-FR'):
   with self.assertRaises(ValueError):languages.pair(value)

 def test_extended_eighteen_pairs_six_formats_combined_review_final_save(self):
  for src,source in SAMPLES.items():
   for dst,target in SAMPLES.items():
    if src==dst or languages.direction(src,dst) in languages.LEGACY:continue
    for suffix in ('.docx','.pptx','.pdf','.xlsx','.txt','.md'):
     with self.subTest(src=src,dst=dst,format=suffix):
      # Markdown autolinks are immutable syntax and intentionally absent from
      # editable segments. Their inline mapping has a separate link test.
      local_source=source.replace('https://example.com/中文','') if suffix=='.md' else source
      local_target=target.replace('https://example.com/中文','').strip() if suffix=='.md' else target
      path=self.source(suffix,local_source,f'{src}-{dst}-{suffix[1:]}');before=path.read_bytes();model=Model(local_target)
      job=self.job(self.options(path,src,dst),model)
      self.assertEqual(job['status'],'complete',job.get('error') or job.get('result'))
      output=job['result']['outputs'][0]
      self.assertTrue(output['translation_complete'],output['review_items'])
      self.assertEqual(output['target_language'],dst);self.assertEqual(output['resumed_segments'],0)
      self.assertEqual(output['review_status'],'complete');self.assertGreater(job['result']['stats']['judged'],0)
      self.assertEqual(output['output_audit']['status'],'complete')
      report_id=job['result']['report']['report_id']
      saved=workflow.apply_report({'report_id':report_id,'path':output['path'],'save_unchanged':True},client=model)
      self.assertEqual(saved['output_audit']['status'],'complete',saved)
      self.assertEqual(saved['remaining_chinese'],[])
      self.assertIn(local_target,'\n'.join(s.text for s in extract(saved['output'])))
      self.assertEqual(path.read_bytes(),before)
      self.assertEqual(comparison.read(output['comparison_id'])['direction'],languages.direction(src,dst))

 def test_independent_review_apply_and_save_all_three_new_languages(self):
  for dst in ('zh-Hant-TW','ja-JP','ko'):
   for suffix in ('.docx','.pptx','.pdf','.xlsx','.txt','.md'):
    with self.subTest(language=dst,format=suffix):
     path=self.source(suffix,SAMPLES[dst]+' TEST TEST',dst+suffix);model=Model(SAMPLES[dst])
     job=self.job({'kind':'check','paths':[str(path)],'target_language':dst,'workers':1},model)
     self.assertEqual(job['status'],'complete',job)
     result=job['result'];self.assertEqual(result['stats']['target_language'],dst)
     findings=result['findings'];self.assertEqual(len(findings),1,findings)
     saved=workflow.apply_report({'report_id':result['report_id'],'path':str(path),
      'edits':[{'index':0,'text':'TEST'}],'output_dir':str(self.root/'reviewed')},client=model)
     self.assertEqual(saved['applied_count'],1,saved);self.assertEqual(saved['output_audit']['status'],'complete')
     output='\n'.join(s.text for s in extract(saved['output']))
     self.assertNotIn('TEST TEST',output)
     self.assertIn(SAMPLES[dst],Path(saved['output']).read_text('utf-8') if suffix=='.md' else output)
     self.assertIn('TEST TEST','\n'.join(s.text for s in extract(path)))

 def test_pending_source_not_marked_complete_or_silently_repaired_by_english_policy(self):
  path=self.source('.docx',SAMPLES['en-US']);model=Model('incorrect 99 Hz')
  job=self.job(self.options(path,'en-US','ja-JP'),model)
  self.assertEqual(job['status'],'partial',job)
  output=job['result']['outputs'][0];self.assertEqual(output['untranslated'],1)
  self.assertIn(SAMPLES['en-US'],'\n'.join(s.text for s in extract(output['path'])))
  self.assertTrue(job['can_resume']);self.assertEqual(model.translations,2)
  saved=workflow.apply_report({'report_id':job['result']['report']['report_id'],'path':output['path'],'save_unchanged':True},client=model)
  self.assertEqual(saved['output_audit']['status'],'partial');self.assertEqual(saved['untranslated'],1)

 def test_new_language_resume_is_explicit_and_restores_original_language(self):
  from docx import Document
  path=self.root/'two.docx';doc=Document();doc.add_paragraph(SAMPLES['en-US']);doc.add_paragraph(SAMPLES['en-US']+' ');doc.save(path)
  data=self.options(path,'en-US','ko','translate');first=self.job(data,Model(SAMPLES['ko'],cancel_after=1))
  self.assertEqual(first['status'],'cancelled',first)
  fresh_model=Model(SAMPLES['ko']);fresh=self.job(data,fresh_model)
  self.assertEqual(fresh['status'],'complete');self.assertEqual(fresh_model.translations,2)
  self.assertEqual(fresh['result']['outputs'][0]['resumed_segments'],0)
  resumed_model=Model(SAMPLES['ko']);resumed=self.job({'resume_from':first['id']},resumed_model)
  self.assertEqual(resumed['status'],'complete',resumed)
  self.assertEqual(resumed_model.translations,1);self.assertEqual(resumed['result']['outputs'][0]['resumed_segments'],1)
  restored=history.resume_options(resumed['id']);self.assertEqual(restored['target_language'],'ko')

 def test_factual_and_script_guards_preserve_identifiers(self):
  for dst,target in SAMPLES.items():
   if dst=='en-US':continue
   documents.content_validate(SAMPLES['en-US'],target,'en-US',dst)
   for bad in (target.replace('60','61'),target.replace('Hz','mm'),target.replace('A8','A9'),target.replace('/中文','/changed')):
    with self.assertRaises(ValueError):documents.content_validate(SAMPLES['en-US'],bad,'en-US',dst)
  with self.assertRaises(ValueError):documents.content_validate(SAMPLES['ko'],SAMPLES['ja-JP'],'ko','en-US')

 def test_visual_policy_explicitly_preserves_each_target_language(self):
  from backend.pptx_visual_review import review_system,SYSTEM
  self.assertEqual(review_system('en'),SYSTEM)
  for dst in ('zh-Hant-TW','ja-JP','ko'):
   system=review_system(dst);self.assertIn(languages.LANGUAGES[dst],system);self.assertNotIn('中文原稿',system)
   self.assertIn('不得翻译或重写正文',system)

 def test_api_lists_complete_document_workflows(self):
  from backend.server import app
  metadata=app.test_client().get('/api/document/languages').get_json()
  self.assertEqual(len(metadata['languages']),5);self.assertIn('apply',metadata['workflows'])

 def test_new_languages_preserve_semantic_emphasis_links_media_and_bookmarks(self):
  from docx import Document
  from docx.oxml import OxmlElement
  from docx.oxml.ns import qn
  from docx.shared import Pt,RGBColor
  from pptx import Presentation
  from pptx.util import Inches
  from backend.multilingual_typography import font_for
  negative={'zh-Hant-TW':'請勿','ja-JP':'ないでください','ko':'지 마세요'}
  class StyledModel(Model):
   def chat_json(self,prompt,system='',**options):
    payload=json.JSONDecoder().raw_decode(prompt)[0]
    if '译文样式片段' in payload:return {'ok':True,'issues':[]}
    if '已复核的完整译文' in payload:
     first,last=self.target.split(self.negative)
     return {'runs':[{'id':1,'text':first},{'id':0,'text':self.negative},{'id':1,'text':last}]}
    return super().chat_json(prompt,system,**options)
  for dst in negative:
   for suffix in ('.docx','.pptx'):
    with self.subTest(language=dst,format=suffix):
     path=self.root/(dst+suffix);target=SAMPLES[dst]
     if suffix=='.docx':
      doc=Document();paragraph=doc.add_paragraph()
      mark=OxmlElement('w:bookmarkStart');mark.set(qn('w:id'),'7');mark.set(qn('w:name'),'Safety');paragraph._p.append(mark)
      red=paragraph.add_run('Do not');red.bold=True;red.font.color.rgb=RGBColor(255,0,0);red.font.size=Pt(18)
      rest=paragraph.add_run(SAMPLES['en-US'][6:]);rest.font.name='Arial';rest.font.size=Pt(18)
      end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),'7');paragraph._p.append(end)
      link=doc.add_paragraph();relationship=doc.part.relate_to('https://example.com/中文','http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',is_external=True)
      hyperlink=OxmlElement('w:hyperlink');hyperlink.set(qn('r:id'),relationship)
      run=OxmlElement('w:r');literal=OxmlElement('w:t');literal.text='https://example.com/中文';run.append(literal);hyperlink.append(run);link._p.append(hyperlink)
      table=doc.add_table(rows=1,cols=2);table.cell(0,0).text=SAMPLES['en-US'];table.cell(0,1).text='42'
      doc.add_picture(str(Path(__file__).resolve().parents[1]/'renderer/assets/normal.png'),width=Inches(.4));doc.save(path)
     else:
      doc=Presentation();slide=doc.slides.add_slide(doc.slide_layouts[6]);box=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(3))
      paragraph=box.text_frame.paragraphs[0];red=paragraph.add_run();red.text='Do not';red.font.bold=True
      from pptx.dml.color import RGBColor as PptColor
      red.font.color.rgb=PptColor(255,0,0);red.font.size=Pt(18)
      rest=paragraph.add_run();rest.text=SAMPLES['en-US'][6:];rest.font.name='Arial';rest.font.size=Pt(18)
      rest.hyperlink.address='https://example.com/中文'
      slide.shapes.add_picture(str(Path(__file__).resolve().parents[1]/'renderer/assets/normal.png'),Inches(9),Inches(1),height=Inches(.4));doc.save(path)
     model=StyledModel(target);model.negative=negative[dst]
     job=self.job(self.options(path,'en-US',dst,'translate'),model)
     self.assertEqual(job['status'],'complete',job)
     result=job['result']['outputs'][0];self.assertFalse(result['review_items']);self.assertFalse(result['layout_warnings'],result['layout_warnings'])
     output=Path(result['path'])
     with ZipFile(path) as before,ZipFile(output) as after:
      for name in before.namelist():
       if '/media/' in name or name.endswith('.rels'):self.assertEqual(before.read(name),after.read(name),name)
      main='word/document.xml' if suffix=='.docx' else 'ppt/slides/slide1.xml'
      from lxml import etree
      tree=etree.fromstring(after.read(main));runs=tree.xpath('//*[local-name()="r"]')
      emphasized=[r for r in runs if r.xpath('./*[local-name()="rPr"]/*[local-name()="b"]') or r.xpath('./*[local-name()="rPr"][@b="1"]')]
      self.assertEqual(''.join(''.join(r.itertext()) for r in emphasized),negative[dst])
      font=font_for(dst)
      if font:self.assertIn(font.encode(),after.read(main))
      if suffix=='.docx':
       self.assertEqual(len(tree.xpath('//*[local-name()="bookmarkStart"]')),1)
       self.assertEqual(len(tree.xpath('//*[local-name()="bookmarkEnd"]')),1)

 def test_other_existing_adapters_support_each_new_language_without_rebuilding_syntax(self):
  source=SAMPLES['en-US'].replace('https://example.com/中文','').strip()
  for dst in ('zh-Hant-TW','ja-JP','ko'):
   target=SAMPLES[dst].replace('https://example.com/中文','').strip()
   for suffix in ('.html','.json','.epub','.srt','.ass'):
    with self.subTest(language=dst,format=suffix):
     folder=self.root/(dst+suffix);folder.mkdir();path=folder/('source'+suffix)
     if suffix=='.html':path.write_text('<html><body><p>'+source+'</p><a href="https://example.com/中文">https://example.com/中文</a></body></html>','utf-8')
     elif suffix=='.json':path.write_text(json.dumps({'id':'A8','description':source,'count':60},ensure_ascii=False),'utf-8')
     elif suffix=='.epub':
      with ZipFile(path,'w') as archive:
       archive.writestr('mimetype','application/epub+zip',compress_type=ZIP_STORED)
       archive.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
       archive.writestr('OPS/book.opf','<package><manifest><item id="ch1" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="ch1"/></spine></package>')
       archive.writestr('OPS/chapter.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><body><p>'+source+'</p></body></html>')
     elif suffix=='.srt':path.write_text('1\n00:00:01,000 --> 00:00:04,000\n'+source+'\n','utf-8')
     else:path.write_text('[Script Info]\nTitle: fixture\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,'+source+'\n','utf-8')
     model=Model(target)
     # Immutable identifier strings do not require expansion into prose.
     original=model.chat_json
     def chat(prompt,system='',**options):
      data=json.JSONDecoder().raw_decode(prompt)[0]
      if data.get('待译原文')=='A8':return {'translation':'A8'}
      return original(prompt,system,**options)
     model.chat_json=chat
     job=self.job(self.options(path,'en-US',dst),model)
     self.assertEqual(job['status'],'complete',job.get('error') or job.get('result'))
     result=job['result']['outputs'][0];self.assertFalse(result['review_items'])
     saved=workflow.apply_report({'report_id':job['result']['report']['report_id'],'path':result['path'],'save_unchanged':True},client=model)
     self.assertIn(target,'\n'.join(s.text for s in extract(saved['output'])))
     if suffix=='.html':self.assertIn('href="https://example.com/中文"',Path(saved['output']).read_text('utf-8'))
     if suffix=='.srt':self.assertIn('00:00:01,000 --> 00:00:04,000',Path(saved['output']).read_text('utf-8'))
     if suffix=='.json':self.assertEqual(json.loads(Path(saved['output']).read_text('utf-8'))['id'],'A8')

 def test_failed_pdf_source_is_not_sent_to_target_proofreading(self):
  path=self.source('.pdf',SAMPLES['en-US']);model=Model('invalid 99 Hz')
  job=self.job(self.options(path,'en-US','ko'),model)
  self.assertEqual(job['status'],'partial');self.assertEqual(job['result']['stats']['judged'],0)
  self.assertFalse(any('本段待校对文字' in p for p,_ in model.requests))

 def emphasis_source(self,name):
  from docx import Document
  from docx.shared import RGBColor
  path=self.root/name;doc=Document();paragraph=doc.add_paragraph()
  red=paragraph.add_run('Do not');red.bold=True;red.font.color.rgb=RGBColor(255,0,0)
  paragraph.add_run(SAMPLES['en-US'][6:]);doc.save(path);return path

 def test_anchor_only_semantic_repair_recovers_japanese_red_negation(self):
  class Anchors(Model):
   def chat_json(self,prompt,system='',**options):
    data=json.JSONDecoder().raw_decode(prompt)[0]
    if '译文样式片段' in data:return {'ok':True,'issues':[]}
    if '已复核的完整译文' in data:
     if '"anchors"' in system:return {'anchors':[{'id':0,'text':'ないでください'}]}
     return {'runs':[{'id':1,'text':self.target}]}  # Invalid omission of emphasis.
    return super().chat_json(prompt,system,**options)
  path=self.emphasis_source('anchor.docx');model=Anchors(SAMPLES['ja-JP'])
  job=self.job(self.options(path,'en-US','ja-JP'),model)
  self.assertEqual(job['status'],'complete',job)
  output=job['result']['outputs'][0];self.assertFalse(output['style_warnings']);self.assertFalse(output['review_items'])
  from docx import Document
  red=[run.text for p in Document(output['path']).paragraphs for run in p.runs if run.font.color.rgb is not None]
  self.assertEqual(''.join(red),'ないでください')

 def test_unresolved_emphasis_warning_remains_visible_after_final_save(self):
  class InterruptedStyle(Model):
   def chat_json(self,prompt,system='',**options):
    data=json.JSONDecoder().raw_decode(prompt)[0]
    if '已复核的完整译文' in data:raise LLMUnavailable('fixture style mapping disconnect')
    return super().chat_json(prompt,system,**options)
  path=self.emphasis_source('style-disconnect.docx');model=InterruptedStyle(SAMPLES['ja-JP'])
  job=self.job(self.options(path,'en-US','ja-JP'),model)
  self.assertEqual(job['status'],'complete',job)
  output=job['result']['outputs'][0];self.assertFalse(output['review_items']);self.assertTrue(output['style_warnings'])
  saved=workflow.apply_report({'report_id':job['result']['report']['report_id'],'path':output['path'],'save_unchanged':True},client=model)
  self.assertTrue(any('局部强调' in warning['reason'] for warning in saved['layout_warnings']))
  self.assertIn(SAMPLES['ja-JP'],'\n'.join(s.text for s in extract(saved['output'])))


if __name__=='__main__':unittest.main()
