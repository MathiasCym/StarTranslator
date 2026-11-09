"""Usage supplements reach UI and prompts without replacing personal work."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.glossary import bundled,catalog,store,language_pairs as pairs,technical_usage
from backend import text_languages,terminology_review,text_translation
from backend.glossary.loader import Glossary
from backend.models import GlossaryEntry

class TechnicalUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':self.tmp.name});env.start();self.addCleanup(env.stop)
    def test_official_cells_counts_and_missing_languages_remain_truthful(self):
        original=catalog.read();before=copy.deepcopy(original);effective=catalog.effective()
        self.assertEqual(original,before);self.assertEqual(catalog.read(),before)
        self.assertEqual(len(original['entries']),1902)
        self.assertEqual(effective['languages'],before['languages'])
        extra=[r for r in effective['entries'] if r.get('id','').startswith('curated-bit')]
        self.assertEqual(len(extra),9)
        self.assertTrue(all('维护补充' in r['source'] and 'fr-FR' not in r['terms'] for r in extra))
        annotations=technical_usage.read()['annotations']
        english=json.loads((bundled.ROOT/'technical-usage-english.json').read_text('utf-8-sig'))
        self.assertEqual(english,annotations)
    def test_main_table_has_parameters_and_term_names_for_each_supported_language(self):
        for language,depth in [('ja-JP','ビット深度'),('ko','비트 깊이'),('zh-Hant-TW','位元深度')]:
            rows=[dict(zip(pairs.FIELDS,r)) for r in pairs.table(language)['rows']]
            self.assertEqual(next(r['en'] for r in rows if r['zh']=='位深' and r['_english']=='bit depth'),depth)
            row=next(r for r in rows if r['zh']=='8bit' and r['_english']=='8-bit')
            self.assertEqual(row['en'],'8bit');self.assertIn('单位记法',row['note']);self.assertIn('维护补充',row['source'])
            self.assertEqual(row['_official'],'')
    def test_default_save_does_not_turn_curated_rows_into_personal_overrides(self):
        table=pairs.table('ja-JP');pairs.save('ja-JP',table['rows'],table['columns'],table['fingerprint'])
        saved=pairs.read_data()['sources'][pairs.scope()]['ja-JP']
        self.assertNotIn(pairs.identity('8bit','8-bit'),saved)
    def test_personal_target_note_alias_error_and_deletion_survive_supplement(self):
        table=pairs.table('ja-JP');idx={k:pairs.FIELDS.index(k) for k in pairs.FIELDS}
        row=next(r for r in table['rows'] if r[idx['zh']]=='8bit' and r[idx['_english']]=='8-bit')
        for name,value in [('en','8 bit'),('note','团队专用说明'),('variants','8-bit'),('wrong_variants','8ビット')]:row[idx[name]]=value
        pairs.save('ja-JP',table['rows'],table['columns'],table['fingerprint'])
        before=pairs.path().read_bytes();effective=catalog.effective()
        row=next(r for r in effective['entries'] if r.get('id')=='curated-bit-parameter-8')
        self.assertEqual(row['terms']['ja-JP'],'8 bit');self.assertEqual(row['maintenance']['ja-JP']['note'],'团队专用说明')
        self.assertIn('单位记法',row['guidance']['note']);self.assertEqual(pairs.path().read_bytes(),before)
        table=pairs.table('ja-JP');table['rows']=[r for r in table['rows'] if r[idx['zh']]!='8bit']
        pairs.save('ja-JP',table['rows'],table['columns'],table['fingerprint'])
        self.assertFalse(any('ja-JP' in r['terms'] for r in catalog.effective()['entries'] if r.get('id')=='curated-bit-parameter-8'))
    def test_english_annotation_upgrade_keeps_standards_and_personal_fields_and_backup(self):
        path=Path(self.tmp.name)/'lexicon.json'
        personal=store.validate([{'zh':'8bit','en':'8-bit','note':'personal','variants':['Eight-bit'],'wrong_variants':['Eight bytes'],'priority':3},
            {'zh':'网口','en':'custom interface','note':'custom translation'}])
        store.atomic_json(path,personal);before=path.read_bytes()
        batch=next(b for b in bundled.manifest() if b['id']=='technical-usage-20261106')
        with patch.object(bundled,'manifest',return_value=[batch]):
            bundled.upgrade_local(path);result=store.read(path)
            self.assertEqual(len(result['entries']),2);first=result['entries'][0]
            self.assertEqual((first['en'],first['variants'],first['wrong_variants'],first['priority']),('8-bit',['Eight-bit'],['Eight bytes'],3))
            self.assertTrue(first['note'].startswith('personal\n'));self.assertIn('单位记法',first['note'])
            self.assertEqual(result['entries'][1],personal[1])
            self.assertEqual(Path(result['bundled_update']['backups'][0]).read_bytes(),before)
            written=path.read_bytes();bundled.upgrade_local(path);self.assertEqual(path.read_bytes(),written)
    def test_text_and_proofreading_payloads_receive_actual_usage_notes(self):
        reference=catalog.effective()
        ctx=text_languages.glossary_context('色深 8bit',reference,'zh-CN','ja-JP')
        self.assertTrue(any('单位记法' in r.get('技术使用说明',{}).get('note','') for r in ctx))
        rows=terminology_review.requirements('8bit','8ビット',Glossary([]),reference,'zh-CN','ja-JP')
        self.assertTrue(any(r['targets']==['8bit'] and '单位记法' in r['note'] for r in rows))
        glossary=Glossary([GlossaryEntry('8bit','8-bit',priority=1,note='parameter guidance')])
        self.assertEqual(text_translation.glossary_context('8bit',glossary,'zh-en')[0]['备注'],'parameter guidance')

    def test_parameter_fields_reject_partial_unit_localization_without_blocking_prose(self):
        from backend.parameter_notation import validate
        source='8bit / 10bit / 12bit'
        for accepted in ('8bit / 10bit / 12bit','8-bit / 10-bit / 12-bit','8 bit / 10 bit / 12 bit'):
            validate(source,accepted)
        for invalid in ('8ビット / 10bit / 12bit','8비트 / 10bit / 12bit','8位元 / 10bit / 12bit',
                        '8byte / 10bit / 12bit','9bit / 10bit / 12bit'):
            with self.assertRaises(ValueError):validate(source,invalid)
        validate('Each pixel contains 8 bits.','各画素は8ビットで構成されます。')

if __name__=='__main__':unittest.main()
