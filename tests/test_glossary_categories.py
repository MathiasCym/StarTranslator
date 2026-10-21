"""Person metadata survives exchange, sync and prompt construction."""
import copy,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.models import GlossaryEntry
from backend.glossary import store,writer,exchange
from backend.glossary.loader import Glossary
from backend import team_sync
from backend.matcher.judge import _build_glossary_text
from backend.checkpoints import context_identity,digest

class PersonCategoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'profile')})
        env.start();self.addCleanup(env.stop)
        self.path=self.root/'terms.json'
        self.person=store.validate([dict(zh='示例姓名',en='Example Name',category='person',priority=1,variants=['Name, Example'])])[0]
        store.atomic_json(self.path,[self.person]);store.atomic_json(store.data_dir()/'lexicon-settings.json',{'path':str(self.path)})

    def test_legacy_terms_keep_public_and_checkpoint_identity(self):
        old=dict(zh='术语',en='term',variants=[],priority=2,note='',source='',machine_variants=[],wrong_variants=[])
        self.assertEqual(store.validate([old]),[old])
        class Client:pass
        identity=context_identity(Glossary([GlossaryEntry(**old)]),None,Client())
        self.assertEqual(identity['glossary'],digest([old]))
        self.assertNotEqual(identity['glossary'],context_identity(Glossary([GlossaryEntry(**self.person)]),None,Client())['glossary'])

    def test_person_roundtrips_json_excel_csv_and_chinese_headers(self):
        self.assertEqual(Glossary.load(str(self.path)).entries[0].category,'person')
        for suffix in ['json','xlsx']:
            target=self.root/('export.'+suffix);exchange.export_file(str(target),'')
            self.assertEqual(exchange.load_import(target),[self.person])
        csv=self.root/'names.csv';csv.write_text('中文,英文,分类\n示例姓名,Example Name,人名\n',encoding='utf-8-sig')
        self.assertEqual(exchange.load_import(csv)[0]['category'],'person')
        self.assertEqual(exchange.entries_from_rows(store.table_rows(store.read()),store.table_columns(store.read())),[self.person])

    def test_team_sync_extends_legacy_table_and_keeps_custom_cells(self):
        csv=self.root/'legacy.csv';csv.write_text('中文,英文,部门\n示例姓名,Example Name,测试组\n',encoding='utf-8-sig')
        team_sync.save_local(csv,[self.person],store.read(csv)['fingerprint'])
        self.assertEqual(writer.load_table(str(csv))['rows'][0][2],'测试组')
        self.assertEqual(store.read(csv)['entries'][0]['category'],'person')
        reset=copy.deepcopy(self.person);reset.pop('category')
        team_sync.save_local(csv,[reset],store.read(csv)['fingerprint'])
        self.assertNotIn('category',store.read(csv)['entries'][0])

    def test_three_way_merge_preserves_classification_and_independent_edits(self):
        old=copy.deepcopy(self.person);old.pop('category')
        remote=copy.deepcopy(old);remote['note']='Team note'
        merged,conflicts=team_sync.merge([old],[self.person],[remote]);self.assertFalse(conflicts)
        value=store.validate(team_sync.flatten(merged))[0]
        self.assertEqual(value['category'],'person');self.assertEqual(value['note'],'Team note')
        remote=copy.deepcopy(self.person);remote['note']='Later note'
        merged,conflicts=team_sync.merge([self.person],[old],[remote]);self.assertFalse(conflicts)
        self.assertNotIn('category',store.validate(team_sync.flatten(merged))[0])

    def test_old_import_cannot_erase_person_and_person_prompt_keeps_name_order(self):
        old=copy.deepcopy(self.person);old.pop('category')
        merged,_=exchange.merge_entries([self.person],[old]);self.assertEqual(merged,[self.person])
        merged,_=exchange.merge_entries([old],[self.person]);self.assertEqual(merged,[self.person])
        prompt=_build_glossary_text([GlossaryEntry(**self.person)])
        self.assertIn('人名',prompt);self.assertIn('Example Name',prompt);self.assertIn('姓名拼写与顺序',prompt)

    def test_invalid_category_never_overwrites_glossary(self):
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'分类'):store.save([{**self.person,'category':'arbitrary'}],store.read()['fingerprint'])
        self.assertEqual(before,self.path.read_bytes())
        columns=store.table_columns(store.read());rows=store.table_rows(store.read());rows[0][columns.index('category')]='invalid'
        with self.assertRaisesRegex(ValueError,'分类'):store.edit_table(self.path,rows,columns,store.read()['fingerprint'])
        self.assertEqual(before,self.path.read_bytes())

if __name__=='__main__':unittest.main()
