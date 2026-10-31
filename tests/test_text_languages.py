"""Free-text languages/style isolation, real contracts and integrity regression."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from backend import text_languages as languages, text_translation as text, workflow, task_queue, lan_service
from backend.glossary.loader import Glossary
from backend.models import GlossaryEntry
from backend.llm.client import LLMUnavailable
from test_text_translation import Client, OK

SAMPLES={
 'zh-CN':'请勿关闭 A8 控制器。频率为 60 Hz。参见 https://example.com/中文。',
 'en-US':'Do not turn off the A8 controller. The frequency is 60 Hz. See https://example.com/中文。',
 'es-ES':'No apague el controlador A8. La frecuencia es de 60 Hz. Véase https://example.com/中文。',
 'fr-FR':'Ne désactivez pas le contrôleur A8. La fréquence est de 60 Hz. Voir https://example.com/中文。',
 'ja-JP':'A8 コントローラーの電源を切らないでください。周波数は 60 Hz です。https://example.com/中文 を参照。',
 'ko':'A8 컨트롤러를 끄지 마세요. 주파수는 60 Hz입니다. https://example.com/中文 참조.',
 'pt':'Não desligue o controlador A8. A frequência é de 60 Hz. Consulte https://example.com/中文。',
 'ru-RU':'Не выключайте контроллер A8. Частота составляет 60 Hz. См. https://example.com/中文。'}


class LanguageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':self.temp.name});env.start();self.addCleanup(env.stop)
  self.previous=dict(workflow.JOBS);workflow.JOBS.clear();self.addCleanup(self.restore)
  self.g=Glossary([GlossaryEntry('控制器','controller',priority=1)])
  glossary=patch('backend.text_translation.store.load_glossary',return_value=self.g);glossary.start();self.addCleanup(glossary.stop)
 def restore(self):
  workflow.JOBS.clear();workflow.JOBS.update(self.previous);task_queue.MAINTENANCE=False
 def run_job(self,source,src,dst,client,**options):
  with patch('backend.text_translation.LLMClient',return_value=client):
   job=workflow.start({'kind':'text','text':source,'source_language':src,'target_language':dst,**options})
   return asyncio.run(task_queue.wait(job['id'],.005))

 def test_all_56_pairs_use_the_job_contract_and_target_language(self):
  for src,source in SAMPLES.items():
   for dst,target in SAMPLES.items():
    if src==dst:continue
    with self.subTest(src=src,dst=dst):
     client=Client([{'translation':target},OK]);job=self.run_job(source,src,dst,client)
     self.assertTrue(job['result']['complete'],job)
     self.assertEqual(job['result']['translation'],target)
     self.assertEqual(job['source_language'],src);self.assertEqual(job['target_language'],dst)
     label='英文' if (src,dst)==('zh-CN','en-US') else languages.LANGUAGES[dst]
     self.assertIn(label,client.calls[0][1]['system'])

 def test_metadata_exposes_actual_eight_languages_without_mutating_resources(self):
  original=Path('glossary/multilingual.json').read_bytes()
  metadata=languages.metadata()
  self.assertEqual(len(metadata['languages']),8);self.assertEqual(metadata['warning'],'')
  self.assertEqual({row['code']:row['count'] for row in metadata['languages']}['ko'],1882)
  self.assertEqual(Path('glossary/multilingual.json').read_bytes(),original)

 def test_official_terms_only_use_a_real_source_target_pair(self):
  ref={'entries':[{'terms':{'zh-CN':'电流降亮','en-US':'current dimming','fr-FR':'variation de luminosité par courant'}},
                  {'terms':{'zh-CN':'缺译项','en-US':'missing entry'}}]}
  terms=languages.glossary_context('current dimming',ref,'en-US','fr-FR')
  self.assertEqual(terms[0]['目标译法'],'variation de luminosité par courant')
  self.assertFalse(languages.glossary_context('缺译项',ref,'zh-CN','fr-FR'))
  self.assertFalse(languages.glossary_context('micurrent dimmingfork',ref,'en-US','fr-FR'))

 def test_humanizer_is_automatic_for_prose_and_terms_keep_precise_wording(self):
  for src,dst in [('zh-CN','en-US'),('en-US','fr-FR')]:
   client=Client([{'translation':SAMPLES[dst]},OK]);job=self.run_job(SAMPLES[src],src,dst,client,humanize=False)
   self.assertTrue(job['result']['complete']);self.assertEqual(len(client.calls),2)
   self.assertIn('Humanizer',client.calls[0][1]['system']);self.assertTrue(job['humanize'])
  client=Client([{'translation':'pas de pixel'},OK]);job=self.run_job('pixel pitch','en-US','fr-FR',client)
  self.assertTrue(job['result']['complete']);self.assertFalse(job['humanize'])
  self.assertNotIn('Humanizer',client.calls[0][1]['system'])

 def test_code_blocks_and_inline_code_are_preserved_and_wrong_code_is_repaired(self):
  source='说明\n```python\nprint("中文")\n```\n结束'
  job=self.run_job(source,'zh-CN','en-US',Client([{'translation':'Description'},OK,{'translation':'End'},OK]),humanize=True)
  self.assertEqual(job['result']['translation'],'Description\n```python\nprint("中文")\n```\nEnd')
  source='说明\n ```python\nprint("中文")\n````\n结束'
  protected=[block['source'] for block in languages.blocks(source,text.pieces) if block.get('protected')]
  self.assertEqual(protected,[' ```python\nprint("中文")\n````'])
  self.assertEqual(list(languages.blocks('```python\nprint("中文")',text.pieces))[0]['translation'],'```python\nprint("中文")')
  self.assertEqual(list(languages.blocks('```python',text.pieces))[0]['translation'],'```python')
  long_code='`'+('变量=1; '*350)+'`'
  source='说明 '+long_code+' 结束'
  chunks=list(text.pieces(source))
  self.assertEqual(sum(len(list(languages.INLINE_CODE.finditer(block['source']))) for block in chunks),1)
  self.assertEqual(''.join(block.get('prefix','')+block['source']+block.get('suffix','') for block in chunks),source)
  self.assertTrue(list(text.pieces(long_code))[0]['protected'])
  client=Client([{'translation':'Run `wrong()` now.'},{'translation':'Run `start()` now.'},OK])
  result=self.run_job('现在执行 `start()`。','zh-CN','en-US',client,humanize=True)
  self.assertTrue(result['result']['complete']);self.assertIn('`start()`',result['result']['translation'])

 def test_new_language_facts_codes_units_and_japanese_han(self):
  languages.validate('The date is 9 May 2025. Pitch: 2.6 mm.','La date est le 9 mai 2025. Pas : 2,6 mm.','en-US','fr-FR')
  languages.validate('Power supply','電源','en-US','ja-JP')
  languages.validate('2位工程师负责2块屏。','2 ingénieurs sont responsables de 2 écrans.','zh-CN','fr-FR')
  languages.validate('灰阶精度为10位。','La précision des niveaux de gris est de 10 bits.','zh-CN','fr-FR')
  for target in ['Le pas est de 2,7 mm.','Le pas est de 2,6 cm.','Le pas est de 2,6.']:
   with self.subTest(target=target),self.assertRaises(ValueError):languages.validate('The pitch is 2.6 mm.',target,'en-US','fr-FR')
  for target in ['La température est 10.','La température est -11.']:
   with self.assertRaises(ValueError):languages.validate('The temperature is -10.',target,'en-US','fr-FR')
  with self.assertRaises(ValueError):languages.validate('A8 supports https://example.com/a','A9 prend en charge https://example.com/a','en-US','fr-FR')
  with self.assertRaises(ValueError):languages.validate('4K resolution','résolution 4Ko','en-US','fr-FR')
  with self.assertRaises(ValueError):languages.validate('See https://example.com/a','Voir https://example.com/b','en-US','fr-FR')

 def test_partial_retry_is_bound_to_languages(self):
  client=Client([{'translation':'Bonjour'},OK,LLMUnavailable('disconnect')])
  job=self.run_job('Hello\nWorld','en-US','fr-FR',client,humanize=True)
  self.assertEqual(job['status'],'failed');self.assertEqual(job['done'],1)
  with self.assertRaises(ValueError):self.run_job('Hello\nWorld','en-US','pt',Client([]),retry_of=job['id'])
  final=self.run_job('Hello\nWorld','en-US','fr-FR',Client([{'translation':'Monde'},OK]),humanize=True,retry_of=job['id'])
  self.assertEqual(final['result']['translation'],'Bonjour\nMonde')

 def test_locale_grouping_minus_and_percentage_do_not_change_values(self):
  languages.validate('The value is 1,234.5.','La valeur est 1\u202f234,5.','en-US','fr-FR')
  languages.validate('The value is 1,234.5.','El valor es 1.234,5.','en-US','es-ES')
  languages.validate('The value is -10.','La valeur est −10.','en-US','fr-FR')
  languages.validate('The value is 60%.','La valeur est 60 %.','en-US','fr-FR')
  with self.assertRaises(ValueError):languages.validate('The value is 60%.','La valeur est 60.','en-US','fr-FR')

 def test_only_unambiguous_added_sentence_punctuation_is_separated_from_addresses(self):
  source='See https://example.com/中文'
  target='См. https://example.com/中文.'
  fixed=languages.separate_link_punctuation(source,target)
  self.assertEqual(fixed,'См. https://example.com/中文 .')
  languages.validate(source,fixed,'en-US','ru-RU')
  self.assertEqual(languages.separate_link_punctuation(source,'Voir https://example.com/english.'),'Voir https://example.com/english.')
  with self.assertRaises(ValueError):languages.validate(source,'Voir https://example.com/english.','en-US','fr-FR')
  self.assertEqual(languages.separate_link_punctuation('https://example.com/a.','https://example.com/a.'),'https://example.com/a.')

 def test_unknown_or_identical_languages_are_rejected(self):
  for fields in [{'source_language':'fr-FR'}, {'source_language':[],'target_language':'en-US'},
   {'source_language':'xx','target_language':'en-US'}, {'source_language':'fr-FR','target_language':'fr-FR'},
   {'source_language':'fr-FR','target_language':[]}]:
   with self.subTest(fields=fields),self.assertRaises(ValueError):text.start({'text':'Hello',**fields})

 def test_lan_forwards_only_allowed_language_and_style_fields(self):
  app=lan_service.create_app(testing=True);owner=app.test_client();csrf=owner.get('/shared/session').json['csrf']
  self.assertEqual(len(owner.get('/shared/text/languages').json['languages']),8)
  with patch('backend.text_translation.LLMClient',return_value=Client([{'translation':SAMPLES['ja-JP']},OK])):
   response=owner.post('/shared/text/jobs',json={'text':SAMPLES['fr-FR'],'source_language':'fr-FR','target_language':'ja-JP',
      'humanize':True,'paths':['C:/secret'],'base_url':'http://evil'},headers={'X-Star-CSRF':csrf})
   self.assertEqual(response.status_code,200)
   job=asyncio.run(task_queue.wait(response.json['id'],.005))
   self.assertTrue(job['result']['complete']);self.assertTrue(job['humanize']);self.assertNotIn('paths',job)


if __name__=='__main__':unittest.main()
