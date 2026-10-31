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

    def test_eight_languages_are_complete_and_blank_cells_not_invented(self):
        data=catalog.read()
        self.assertTrue(data['readOnly'])
        self.assertEqual(data['sourceRows'],1965)
        self.assertEqual(len(data['entries']),1965)
        self.assertEqual(len({row['id'] for row in data['entries']}),1965)
        counts={'zh-CN':1965,'en-US':1965,'es-ES':1883,'fr-FR':1883,'ja-JP':1883,'ko':1882,'pt':1883,'ru-RU':1883}
        self.assertEqual({lang['code']:lang['count'] for lang in data['languages']},counts)
        for code,count in counts.items():
            self.assertEqual(sum(bool(row['terms'].get(code)) for row in data['entries']),count)
        self.assertEqual(data['sourceSha256'],'1bb865cedb5dd3b8829fd6d92f6d6b091d3886ee76466655d8ddcc8a85ae6ea3')

    def test_read_does_not_seed_modify_or_expand_active_translation_glossary(self):
        before=store.read();raw=Path(before['path']).read_bytes()
        rows=[entry.to_dict() for entry in store.load_glossary().entries]
        for _ in range(2):catalog.read()
        self.assertEqual(Path(before['path']).read_bytes(),raw)
        self.assertEqual([entry.to_dict() for entry in store.load_glossary().entries],rows)
        self.assertEqual(len(rows),2515)
        self.assertFalse((Path(self.tmp.name)/'multilingual.json').exists())

    def test_api_is_read_only(self):
        client=app.test_client()
        response=client.get('/api/lexicon/catalog')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['languages']),8)
        self.assertEqual(client.post('/api/lexicon/catalog',json={'entries':[]}).status_code,405)
        self.assertEqual(client.delete('/api/lexicon/catalog').status_code,405)

    def test_unavailable_catalog_does_not_break_bilingual_glossary(self):
        with patch.object(catalog,'DEFAULT_PATH',str(Path(self.tmp.name)/'missing/terms.json')):
            with self.assertRaisesRegex(ValueError,'中英词库仍可正常使用'):catalog.read()
        self.assertEqual(len(store.read()['entries']),2515)

if __name__=='__main__':unittest.main()
