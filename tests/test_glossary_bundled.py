"""Default-library upgrades preserve edits, deletions and valid-file operation."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.glossary import store,bundled
from backend.server import app


def term(zh,en,**fields):
    return store.validate([dict(zh=zh,en=en,**fields)])[0]


class BundledGlossaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'lexicon.json'
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root)});env.start();self.addCleanup(env.stop)
        self.batch={'id':'test-official-v1','terms':['新增术语','示例姓名']}
        self.incoming=[term('新增术语','new term',priority=1),term('示例姓名','Example Name',category='person')]
        self.current=[term('已有术语','existing',variants=['retained alias'],note='personal note',source='my source')]
        store.atomic_json(self.path,self.current)
        for name,value in [('manifest',[self.batch]),('catalog',{bundled.key(e['zh']):[e] for e in self.incoming})]:
            stub=patch.object(bundled,name,return_value=value);stub.start();self.addCleanup(stub.stop)
    def read(self):return json.loads(self.path.read_text('utf-8-sig'))
    def run_upgrade(self):bundled.upgrade_local(self.path);return bundled.status(self.path)

    def test_missing_terms_are_added_with_exact_existing_fields_and_backup(self):
        before=self.path.read_bytes();report=self.run_upgrade()
        self.assertEqual(self.read(),self.current+self.incoming)
        self.assertEqual(report['added'],2)
        self.assertEqual(Path(report['backups'][0]).read_bytes(),before)
        self.assertFalse(self.path.with_suffix('.json.lock').exists())
    def test_repeat_start_does_not_write_again_or_restore_user_deletions(self):
        self.run_upgrade();self.path.write_text(json.dumps(self.current),'utf-8')
        before=self.path.read_bytes()
        with patch.object(store,'atomic_json',side_effect=AssertionError('Unexpected repeat write')):
            self.run_upgrade()
        self.assertEqual(self.path.read_bytes(),before)
    def test_custom_translation_category_aliases_and_notes_are_never_overwritten(self):
        personal=term('示例姓名','Personal Name',category='person',variants=['P. Name'],wrong_variants=['Wrong'],note='custom')
        store.atomic_json(self.path,self.current+[personal]);report=self.run_upgrade()
        self.assertEqual(self.read(),self.current+[personal,self.incoming[0]])
        self.assertEqual(report['added'],1);self.assertEqual(report['conflicts'][0]['zh'],'示例姓名')
    def test_normalized_chinese_and_accepted_english_aliases_do_not_duplicate(self):
        entry=term(' 新增术语 ','CUSTOM',variants=['new term'])
        store.atomic_json(self.path,self.current+[entry]);report=self.run_upgrade()
        self.assertEqual(report['added'],1);self.assertEqual(report['conflicts'],[])
        self.assertEqual(self.read()[1],entry)
    def test_external_json_and_shared_tables_are_not_modified(self):
        for name in ['shared.json','shared.xlsx']:
            path=self.root/name;path.write_bytes(b'external file');before=path.read_bytes()
            bundled.upgrade_local(path);self.assertIsNone(bundled.status(path));self.assertEqual(path.read_bytes(),before)
    def test_backup_failure_retains_usable_library_and_retries(self):
        before=self.path.read_bytes()
        with patch.object(bundled,'backup',side_effect=PermissionError('backup denied')):
            report=self.run_upgrade()
        self.assertIn('error',report);self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(bundled.receipt(self.path,self.batch['id']).exists())
        self.assertNotIn('error',self.run_upgrade());self.assertEqual(len(self.read()),3)
    def test_write_failure_keeps_original_and_pending_journal_can_resume(self):
        before=self.path.read_bytes();write=store.atomic_json
        def fail(path,value):
            if Path(path)==self.path:raise PermissionError('temporary file lock')
            return write(path,value)
        with patch.object(store,'atomic_json',side_effect=fail):self.assertIn('error',self.run_upgrade())
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.run_upgrade()['added'],2);self.assertEqual(len(self.read()),3)
    def test_crash_after_glossary_write_finalizes_journal_without_reimport(self):
        write=store.atomic_json
        def crash(path,value):
            if Path(path)==bundled.receipt(self.path,self.batch['id']) and value.get('completed'):raise OSError('receipt interrupted')
            return write(path,value)
        with patch.object(store,'atomic_json',side_effect=crash):self.assertIn('error',self.run_upgrade())
        before=self.path.read_bytes();self.assertEqual(len(self.read()),3)
        report=self.run_upgrade();self.assertEqual(report['added'],2);self.assertEqual(self.path.read_bytes(),before)
    def test_concurrent_edit_is_not_overwritten(self):
        original=bundled.backup
        def edit(path,raw,ident):
            result=original(path,raw,ident);store.atomic_json(path,self.current+[term('同时新增','concurrent')]);return result
        with patch.object(bundled,'backup',side_effect=edit):self.assertIn('error',self.run_upgrade())
        self.assertEqual(self.read()[-1]['zh'],'同时新增')
        self.assertEqual(self.run_upgrade()['added'],2);self.assertEqual(len(self.read()),4)
    def test_lock_contention_keeps_current_file_and_retries(self):
        lock=Path(str(self.path)+'.lock');lock.write_text('owned')
        before=self.path.read_bytes();self.assertIn('error',self.run_upgrade());self.assertEqual(self.path.read_bytes(),before)
        lock.unlink();self.assertEqual(self.run_upgrade()['added'],2)
    def test_invalid_bundled_term_does_not_mark_migration_complete(self):
        before=self.path.read_bytes()
        with patch.object(bundled,'catalog',return_value={}):self.assertIn('error',self.run_upgrade())
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(bundled.receipt(self.path,self.batch['id']).exists())
    def test_startup_api_applies_to_default_even_if_explicitly_selected(self):
        # Historical migrations are tested separately; emulate an existing profile.
        with patch('backend.glossary.audit.upgrade_local',side_effect=AssertionError('Unrelated historical migration')),patch('backend.glossary.formats.upgrade_local',side_effect=AssertionError('Unrelated historical migration')),patch('backend.glossary.corrections.upgrade_local'),patch('backend.glossary.bit_depth.upgrade_local'):
            store.atomic_json(self.root/'lexicon-settings.json',{'path':str(self.path)})
            client=app.test_client();response=client.get('/api/lexicon')
            self.assertEqual(response.status_code,200);self.assertEqual(len(response.json['entries']),3)
            self.assertEqual(response.json['bundled_update']['added'],2)
            self.assertEqual(len(client.get('/api/lexicon').json['entries']),3)
    def test_only_new_manifest_batch_runs_after_a_later_upgrade(self):
        self.run_upgrade();self.path.write_text(json.dumps(self.current),'utf-8')
        later={'id':'test-later-v2','terms':['后续新增']};entry=term('后续新增','later')
        with patch.object(bundled,'manifest',return_value=[self.batch,later]),patch.object(bundled,'catalog',return_value={bundled.key(entry['zh']):[entry]}):
            self.run_upgrade()
        self.assertEqual(self.read(),self.current+[entry])


class ReleasedLibraryUpgradeTests(unittest.TestCase):
    def test_real_635_entry_library_reaches_2515_without_changing_existing_entries(self):
        terms={bundled.key(t) for batch in bundled.manifest() for t in batch['terms']}
        incoming=store.validate(json.loads((bundled.ROOT/'team.json').read_text('utf-8-sig')))
        previous=[e for e in incoming if bundled.key(e['zh']) not in terms]
        self.assertEqual(len(previous),635);self.assertEqual(len(terms),1880)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'NOVATERM_DATA_DIR':directory}):
            path=Path(directory)/'lexicon.json';store.atomic_json(path,previous);before=path.read_bytes()
            bundled.upgrade_local(path);result=store.read(path)
            self.assertEqual(len(result['entries']),2515);self.assertEqual(result['entries'][:635],previous)
            self.assertEqual(Path(result['bundled_update']['backups'][0]).read_bytes(),before)
            self.assertEqual(result['bundled_update']['added'],1880)
            saved=path.read_bytes();bundled.upgrade_local(path);self.assertEqual(path.read_bytes(),saved)


if __name__=='__main__':unittest.main()
