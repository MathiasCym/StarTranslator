"""Maintained language standards must never overwrite the bilingual glossary."""
import copy,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.glossary import language_pairs as pairs,catalog,store
from backend.glossary.loader import Glossary
from backend import terminology_review as review,text_languages
from backend.models import Segment
from backend.server import app

TABLE={'schema':1,'readOnly':True,'entries':[
 {'id':'a','terms':{'zh-CN':'刷新率','en-US':'refresh rate','ja-JP':'リフレッシュレート','ko':'재생률','zh-Hant-TW':'刷新率','fr-FR':'fréquence'}},
 {'id':'b','terms':{'zh-CN':'缺项','en-US':'missing'}},
 {'id':'c','terms':{'zh-CN':'刷新率','en-US':'financial rate','ja-JP':'別の意味'}}]}

class LanguagePairsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':self.tmp.name});env.start();self.addCleanup(env.stop)
        self.english=store.read();self.before=Path(self.english['path']).read_bytes()
        self.reference=copy.deepcopy(TABLE)
        mock=patch.object(catalog,'read',side_effect=lambda:copy.deepcopy(self.reference));mock.start();self.addCleanup(mock.stop)
    def edit(self,language='ja-JP',**values):
        table=pairs.table(language);row=next(r for r in table['rows'] if r[pairs.FIELDS.index('_english')]=='refresh rate')
        for field,value in values.items():row[pairs.FIELDS.index(field)]=value
        pairs.save(language,table['rows'],table['columns'],table['fingerprint'])
        return next(dict(zip(pairs.FIELDS,r)) for r in pairs.table(language)['rows'] if r[pairs.FIELDS.index('_english')]=='refresh rate')
    def test_view_has_actual_targets_missing_cells_and_distinct_senses(self):
        table=pairs.table('ja-JP');rows=[dict(zip(pairs.FIELDS,r)) for r in table['rows']]
        self.assertEqual(next(r['en'] for r in rows if r['_english']=='missing'),'')
        self.assertEqual({r['en'] for r in rows if r['zh']=='刷新率'},{'リフレッシュレート','別の意味'})
        self.assertFalse(pairs.path().exists());self.assertEqual(Path(self.english['path']).read_bytes(),self.before)
    def test_all_supported_targets_edit_reload_without_touching_other_languages(self):
        for code,value in [('ja-JP','新しいレート'),('ko','새 재생률'),('zh-Hant-TW','重新整理率')]:
            row=self.edit(code,en=value,variants='別名',wrong_variants='誤訳',priority='1',note='团队确认')
            self.assertEqual((row['en'],row['priority'],row['variants'],row['wrong_variants']),(value,'1','別名','誤訳'))
            self.assertEqual(row['source'],'本机维护')
        self.assertEqual(Path(self.english['path']).read_bytes(),self.before)
        effective=catalog.effective();self.assertEqual(effective['entries'][0]['terms']['fr-FR'],'fréquence')
        self.assertEqual(self.reference,TABLE);self.assertEqual(effective['entries'][0]['terms']['en-US'],'refresh rate')
    def test_official_update_preserves_local_work_and_reports_conflict(self):
        self.edit(en='新しいレート',priority='1')
        self.reference['entries'][0]['terms']['ja-JP']='更新された公式'
        table=pairs.table('ja-JP');row=next(dict(zip(pairs.FIELDS,r)) for r in table['rows'] if r[pairs.FIELDS.index('_english')]=='refresh rate')
        self.assertEqual(row['en'],'新しいレート');self.assertIn('已变化',row['_conflict'])
    def test_duplicate_official_anchor_is_not_arbitrarily_selected_and_override_covers_all(self):
        self.reference['entries'].append({'id':'another','terms':{**TABLE['entries'][0]['terms'],'ja-JP':'別の公式'}})
        rows=pairs.table('ja-JP')['rows'];row=next(dict(zip(pairs.FIELDS,r)) for r in rows if r[pairs.FIELDS.index('_english')]=='refresh rate')
        self.assertEqual(row['en'],'');self.assertIn('多个',row['_conflict'])
        self.edit(en='確定したレート',priority='1')
        self.assertEqual([r['terms']['ja-JP'] for r in catalog.effective()['entries'] if r['terms']['en-US']=='refresh rate'],['確定したレート']*2)
    def test_stale_fingerprint_rejects_instead_of_overwriting(self):
        stale=pairs.table('ja-JP');self.edit(en='保存済み')
        before=pairs.path().read_bytes()
        with self.assertRaises(store.FileChanged):pairs.save('ja-JP',stale['rows'],stale['columns'],stale['fingerprint'])
        self.assertEqual(pairs.path().read_bytes(),before)
    def test_english_or_official_change_also_invalidates_open_table(self):
        stale=pairs.table('ko');self.reference['entries'][0]['terms']['ko']='새 공식'
        with self.assertRaises(store.FileChanged):pairs.save('ko',stale['rows'],stale['columns'],stale['fingerprint'])
        self.assertFalse(pairs.path().exists())
    def test_corrupt_file_is_reported_without_overwrite(self):
        pairs.path().write_text('{broken','utf-8')
        with self.assertRaisesRegex(ValueError,'原文件未改动'):pairs.table('ja-JP')
        self.assertEqual(pairs.path().read_text('utf-8'),'{broken')
    def test_add_delete_and_backup_are_language_scoped(self):
        table=pairs.table('ko');row=['']*len(pairs.FIELDS)
        for key,value in {'zh':'新词','en':'새 단어','priority':'1','category':'term'}.items():row[pairs.FIELDS.index(key)]=value
        table['rows'].append(row);pairs.save('ko',table['rows'],table['columns'],table['fingerprint'])
        self.assertTrue(any(r[0]=='新词' for r in pairs.table('ko')['rows']))
        self.assertFalse(any(r[0]=='新词' for r in pairs.table('ja-JP')['rows']))
        table=pairs.table('ko');table['rows']=[r for r in table['rows'] if r[0]!='新词']
        pairs.save('ko',table['rows'],table['columns'],table['fingerprint'])
        self.assertTrue(Path(str(pairs.path())+'.bak').exists())
        self.assertFalse(any(r[0]=='新词' for r in pairs.table('ko')['rows']))
    def test_existing_anchor_cannot_be_accidentally_written_as_another_concept(self):
        table=pairs.table('ja-JP');table['rows'][0][0]='不同中文'
        with self.assertRaisesRegex(ValueError,'不可'):pairs.save('ja-JP',table['rows'],table['columns'],table['fingerprint'])
        self.assertFalse(pairs.path().exists())
    def test_api_supported_language_save_and_stale_conflict(self):
        client=app.test_client();response=client.get('/api/glossary/language?language=ja-JP');self.assertEqual(response.status_code,200)
        table=response.json;table['language']='ja-JP'
        self.assertEqual(client.post('/api/glossary/language',json=table).status_code,200)
        self.assertEqual(client.post('/api/glossary/language',json=table).status_code,409)
        self.assertEqual(client.get('/api/glossary/language?language=fr-FR').status_code,400)
    def test_confirmed_standard_aliases_and_wrong_forms_drive_proofreading(self):
        self.reference['entries']=self.reference['entries'][:2]
        self.edit(en='確定レート',variants='許可レート',wrong_variants='誤レート',priority='1',note='显示参数')
        ref=catalog.effective();glossary=Glossary([])
        self.assertEqual(review.requirements('刷新率','許可レート',glossary,ref,'zh-CN','ja-JP'),[])
        rows=review.requirements('刷新率','確定レートと誤レート',glossary,ref,'zh-CN','ja-JP')
        self.assertEqual(rows[0]['targets'],['確定レート']);self.assertEqual(rows[0]['wrong_variants'],['誤レート'])
        self.assertEqual(rows[0]['note'],'显示参数')
        self.edit(priority='2')
        self.assertFalse(any('確定レート' in r['targets'] for r in review.requirements('刷新率','誤レート',glossary,catalog.effective(),'zh-CN','ja-JP')))
    def test_free_text_context_has_maintained_alias_error_and_truthful_provenance(self):
        self.edit(en='確定レート',variants='許可レート',wrong_variants='誤レート',priority='1')
        forward=text_languages.glossary_context('刷新率',catalog.effective(),'zh-CN','ja-JP')
        self.assertEqual(forward[0]['目标译法'],'確定レート');self.assertEqual(forward[0]['来源'],'本机维护')
        self.assertEqual(forward[0]['正确别名'],['許可レート'])
        reverse=text_languages.glossary_context('許可レート',catalog.effective(),'ja-JP','ko')
        self.assertEqual(reverse[0]['目标译法'],'재생률')
    def test_actual_review_calls_model_with_local_confirmed_standard(self):
        self.reference['entries']=self.reference['entries'][:2]
        self.edit(en='確定レート',priority='1')
        class Model:
            requests=[]
            def chat_json(inner,prompt,**kwargs):
                data=json.loads(prompt);inner.requests.append(data)
                return {'reviewed':True,'decisions':[{'id':r['id'],'status':'replace','original':'誤レート','replacement':'確定レート','reason':'已确认显示参数标准'} for r in data['术语待核对']]}
        model=Model();segment=Segment(id='p',file='qa.docx',file_path=str(Path(self.tmp.name)/'qa.docx'),text='誤レート',locator='p')
        with patch.object(review,'open_checkpoint',return_value=None):
            findings,stats=review.augment([segment],Glossary([]),[],{'errors':0,'unreviewed':0,'warnings':[]},source_language='zh-CN',target_language='ja-JP',aligned_sources={'p':'刷新率'},client=model,workers=1,cancel=threading.Event())
        self.assertEqual(len(model.requests),1);self.assertEqual(findings[0].suggested,'確定レート');self.assertTrue(findings[0].terminology_standard)

if __name__=='__main__':unittest.main()
