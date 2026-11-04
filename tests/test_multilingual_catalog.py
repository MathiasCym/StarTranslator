"""Multilingual reference must not change the bilingual translation glossary."""
import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.glossary import catalog,store
from backend.glossary.loader import DEFAULT_PATH
from backend.server import app

class MultilingualCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':self.tmp.name});env.start();self.addCleanup(env.stop)

    def test_latest_sixteen_languages_match_source_without_inventing_blank_cells(self):
        data=catalog.read()
        self.assertTrue(data['readOnly'])
        self.assertEqual(data['sourceRows'],1902)
        self.assertEqual(len(data['entries']),1902)
        self.assertEqual(len({row['id'] for row in data['entries']}),1902)
        counts={'zh-CN':1902,'en-US':1902,'es-ES':1871,'fr-FR':1871,'ja-JP':1871,'ko':1870,'pt':1871,'ru-RU':1871,
            'ar-SA':1898,'de-DE':1898,'id-ID':1898,'it-IT':1898,'th-TH':1898,'tr-TR':1898,'vi-VN':1898,'zh-Hant-TW':1899}
        self.assertEqual({lang['code']:lang['count'] for lang in data['languages']},counts)
        for code,count in counts.items():
            self.assertEqual(sum(bool(row['terms'].get(code)) for row in data['entries']),count)
        self.assertEqual(data['sourceSha256'],'c7ef5c90044eb09fc0293703f1279acc5f9502246dbcf59865ff3e6f105cb277')
        self.assertEqual(data['sourceLanguageCodes']['ko'],'ko-KR')
        self.assertEqual(data['sourceLanguageCodes']['zh-Hant-TW'],'zh-Hant-TW')

    def test_read_does_not_seed_modify_or_expand_active_translation_glossary(self):
        before=store.read();raw=Path(before['path']).read_bytes()
        rows=[entry.to_dict() for entry in store.load_glossary().entries]
        for _ in range(2):catalog.read()
        self.assertEqual(Path(before['path']).read_bytes(),raw)
        self.assertEqual([entry.to_dict() for entry in store.load_glossary().entries],rows)
        self.assertEqual(len(rows),2456)
        self.assertFalse((Path(self.tmp.name)/'multilingual.json').exists())

    def test_api_is_read_only(self):
        client=app.test_client()
        response=client.get('/api/lexicon/catalog')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['languages']),16)
        self.assertEqual(client.post('/api/lexicon/catalog',json={'entries':[]}).status_code,405)
        self.assertEqual(client.delete('/api/lexicon/catalog').status_code,405)

    def test_unavailable_catalog_does_not_break_bilingual_glossary(self):
        with patch.object(catalog,'DEFAULT_PATH',str(Path(self.tmp.name)/'missing/terms.json')):
            with self.assertRaisesRegex(ValueError,'中英词库仍可正常使用'):catalog.read()
        self.assertEqual(len(store.read()['entries']),2456)

    def test_stale_user_catalog_cannot_shadow_the_shipped_latest_catalog(self):
        stale=Path(self.tmp.name)/'multilingual.json';stale.write_text('{"entries":[],"languages":[]}',encoding='utf-8')
        data=catalog.read();self.assertEqual(len(data['languages']),16)
        self.assertEqual(len(data['entries']),1902)
        self.assertEqual(stale.read_text('utf-8'),'{"entries":[],"languages":[]}')

if __name__=='__main__':unittest.main()
