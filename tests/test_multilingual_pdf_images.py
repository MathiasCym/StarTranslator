"""Offline figure contracts, pixel boundaries, safe fallback and saved media."""
import io,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from PIL import Image
from docx import Document
from backend import multilingual_pdf_images as images,multilingual_documents as documents
from backend.pdf_images import append_images
from backend.glossary.loader import Glossary
from backend.llm.client import LLMClient,LLMUnavailable
from backend.translation import Cancelled
import test_pdf_image_text as legacy

WORDS={'zh-CN':'刷新率为 60 Hz。','zh-Hant-TW':'更新率為 60 Hz。','en-US':'The refresh rate is 60 Hz.',
       'ja-JP':'リフレッシュレートは 60 Hz です。','ko':'재생률은 60 Hz입니다.'}


class Model(LLMClient):
 def __init__(self,src='en-US',dst='ja-JP',*,reject=False):
  self.provider='compatible';self.base_url='http://127.0.0.1:1/v1';self.model='figure-contract';self.api_format='openai'
  self.src=src;self.dst=dst;self.calls=[];self.reject=reject
 def chat_images_json(self,prompt,images,**options):
  self.calls.append(('image',prompt))
  if len(images)==1:return {'reviewed':True,'lines':[{'id':0,'text':WORDS[self.src]}],'untouched_ids':[],'unlocated_source':[]}
  return {'reviewed':True,'remaining_source':[],'meaning_preserved':not self.reject,'other_content_preserved':True,'readable':True}
 def chat_json(self,prompt,**options):
  self.calls.append(('text',prompt));data=json.JSONDecoder().raw_decode(prompt)[0]
  if '本段待校对文字' in data:return {'reviewed':True,'suggestions':[]}
  return {'translation':WORDS[self.dst]} if '待译原文' in data else {'ok':True,'issues':[]}


class MultilingualImageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'profile')});env.start();self.addCleanup(env.stop)
  self.source=self.root/'source.pdf';self.source.write_bytes(b'isolated fixture')
 def document(self):
  word=Document();append_images(word,SimpleNamespace(images=[SimpleNamespace(data=legacy.picture())]),1)
  return SimpleNamespace(document=word)
 def blob(self,document):
  shape=document.document.inline_shapes[0];rid=shape._inline.graphic.graphicData.pic.blipFill.blip.embed
  return document.document.part.related_parts[rid].blob
 def review(self,document,model,**options):
  ocr={'width':600,'height':100,'angle':0,'lines':[{'id':0,'text':WORDS[model.src],'box':[12,10,580,90]}]}
  with patch.object(images,'view_image',side_effect=lambda raw:(raw,1)),patch.object(images,'recognize',return_value=ocr):
   return images.review_images(document,self.source,model,Glossary([]),[],model.src,model.dst,**options)

 def test_twenty_image_language_pairs_keep_other_pixels_and_saved_media(self):
  for src in WORDS:
   for dst in WORDS:
    if src==dst:continue
    with self.subTest(src=src,dst=dst):
     document=self.document();before=self.blob(document);model=Model(src,dst)
     result=self.review(document,model);self.assertEqual(result['status'],'complete',result)
     self.assertEqual(result['translated_lines'],1)
     after=self.blob(document);self.assertNotEqual(before,after)
     with Image.open(io.BytesIO(before)) as a,Image.open(io.BytesIO(after)) as b:
      self.assertTrue(images.outside_unchanged(a,b,[(10,8,582,92)]))
     path=self.root/'saved.docx';document.document.save(path)
     self.assertEqual(images.audit_saved(path,result),[])

 def test_target_script_and_source_language_bind_the_cache_and_verify_bytes(self):
  first=Model();self.assertEqual(self.review(self.document(),first)['translated_images'],1)
  second=Model();result=self.review(self.document(),second)
  self.assertEqual(result['resumed'],1);self.assertEqual(second.calls,[])
  different=Model(dst='ko');result=self.review(self.document(),different)
  self.assertEqual(result['resumed'],0);self.assertTrue(different.calls)

 def test_unavailable_ocr_and_vision_keep_original_not_fake_complete(self):
  document=self.document();before=self.blob(document);model=Model()
  with patch.object(images,'recognize',side_effect=ValueError('required OCR language unavailable')):
   result=images.review_images(document,self.source,model,Glossary([]),[],'en-US','ja-JP')
  self.assertEqual(result['status'],'partial');self.assertEqual(model.calls,[]);self.assertEqual(before,self.blob(document))
  class NoVision(Model):
   def chat_images_json(self,*a,**kw):raise LLMUnavailable('offline')
  result=self.review(document,NoVision());self.assertEqual(result['status'],'partial');self.assertEqual(before,self.blob(document))

 def test_failed_independent_verification_does_not_apply_half_edited_picture(self):
  document=self.document();before=self.blob(document);result=self.review(document,Model(reject=True))
  self.assertEqual(result['status'],'partial');self.assertEqual(result['translated_images'],0);self.assertEqual(before,self.blob(document))

 def test_no_omitted_or_unlocated_ocr_rows_can_be_accepted(self):
  ocr={'lines':[{'id':0,'text':WORDS['en-US'],'box':[0,0,500,80]}]}
  for answer in [dict(reviewed=True,lines=[],untouched_ids=[],unlocated_source=[]),
       dict(reviewed=True,lines=[],untouched_ids=[0],unlocated_source=['extra label']),
       dict(reviewed=True,lines=[{'id':0,'text':WORDS['en-US']}],untouched_ids=[0],unlocated_source=[])]:
   with self.assertRaises(ValueError):images.scan(answer,ocr,'en-US','ja-JP')
  self.assertEqual(images.scan(dict(reviewed=True,lines=[],untouched_ids=[0],unlocated_source=[]),ocr,'en-US','ja-JP'),[])

 def test_ocr_cannot_change_numbers_urls_or_model_codes(self):
  ocr={'lines':[{'id':0,'text':'The A8 rate is 60 Hz. https://example.com/a','box':[0,0,500,80]}]}
  for source in ['The A9 rate is 60 Hz. https://example.com/a','The A8 rate is 61 Hz. https://example.com/a','The A8 rate is 60 Hz. https://example.com/b']:
   with self.assertRaises(ValueError):images.scan(dict(reviewed=True,lines=[{'id':0,'text':source}],untouched_ids=[],unlocated_source=[]),ocr,'en-US','ja-JP')

 def test_saved_file_cannot_drop_a_previously_verified_picture(self):
  document=self.document();review=self.review(document,Model());path=self.root/'saved.docx';document.document.save(path)
  broken=self.root/'broken.docx'
  with ZipFile(path) as original,ZipFile(broken,'w') as output:
   for info in original.infolist():output.writestr(info,b'wrong' if info.filename in review['expected_media'] else original.read(info.filename))
  result=images.audit_saved(broken,review);self.assertTrue(result);self.assertEqual(result[0]['kind'],'image')

 def test_cancellation_does_not_publish_or_cache_an_unverified_image(self):
  document=self.document();before=self.blob(document);cancel=threading.Event();cancel.set()
  with self.assertRaises(Cancelled):self.review(document,Model(),cancel=cancel)
  self.assertEqual(before,self.blob(document))

 def test_incomplete_picture_survives_text_audit_as_explicit_retryable_issue(self):
  document=self.document();review=self.review(document,Model(reject=True));path=self.root/'saved.docx';document.document.save(path)
  result=documents.audit_saved(path,{},target_language='ja-JP',image_review=review)
  self.assertEqual(result['status'],'partial');self.assertTrue(any(i['kind']=='image' and i['retryable'] for i in result['issues']))

 def test_normal_image_only_pdf_workflow_review_and_final_save(self):
  from backend import workflow
  from backend.references import ReferenceIndex
  legacy.PdfImageTextTests.pdf_with_image(self,'')
  model=Model();ocr={'width':600,'height':100,'angle':0,'lines':[{'id':0,'text':WORDS['en-US'],'box':[12,10,580,90]}]}
  data={'kind':'translate_review','paths':[str(self.source)],'direction':'en-US>ja-JP','workers':1,
        'output_dir':str(self.root/'output'),'combined_output':'final','_client':model}
  job={'id':'image-only-contract','kind':'translate_review','status':'running','percent':0,'error':'','cancel':threading.Event()}
  with patch('backend.workflow.store.load_glossary',return_value=Glossary([])),patch.object(images,'view_image',side_effect=lambda raw:(raw,1)),patch.object(images,'recognize',return_value=ocr):
   workflow.run(job,data)
  self.assertEqual(job['status'],'complete',job.get('error') or job['result'])
  output=job['result']['outputs'][0];self.assertEqual(output['translated'],0);self.assertEqual(output['image_review']['translated_lines'],1)
  self.assertEqual(output['output_audit']['status'],'complete')
  saved=workflow.apply_report({'report_id':job['result']['report']['report_id'],'path':output['path'],'save_unchanged':True},client=model)
  self.assertEqual(saved['output_audit']['status'],'complete');self.assertEqual(images.audit_saved(saved['output'],output['image_review']),[])


if __name__=='__main__':unittest.main()
