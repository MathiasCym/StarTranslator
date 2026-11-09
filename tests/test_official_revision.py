"""Official revisions upgrade exact baselines without reintroducing old standards."""
import copy,hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.glossary import bundled,store
from backend.glossary.bundled_revision import revise


def entry(zh,en,**fields):return store.validate([dict(zh=zh,en=en,priority=1,source='公司官方术语库（英语）',**fields)])[0]
def groups(entries):
    result={}
    for e in entries:result.setdefault(bundled.key(e['zh']),[]).append(e)
    return result


class OfficialRevisionTests(unittest.TestCase):
    def test_exact_old_standard_updates_once_and_keeps_personal_fields(self):
        old=entry('防松螺母','anti-loosing nut');new=entry('防松螺母','anti-loosening nut')
        personal={**old,'note':'保留个人备注','variants':['fastener'],'category':'person'}
        result,report=revise([personal],groups([old]),groups([new]))
        self.assertEqual(len(result),1);self.assertEqual(result[0]['en'],new['en'])
        for field in ('note','variants','category'):self.assertEqual(result[0][field],personal[field])
        self.assertEqual(report['updated'],1);self.assertEqual(report['conflicts'],[])
    def test_personal_translation_is_not_overwritten_or_duplicated(self):
        old=entry('术语','old');new=entry('术语','new');custom={**old,'en':'personal'}
        result,report=revise([custom],groups([old]),groups([new]))
        self.assertEqual(result,[custom]);self.assertEqual(len(report['conflicts']),1)
    def test_unchanged_official_value_does_not_revive_historical_disagreements(self):
        old=entry('对比度','contrast');custom={**old,'en':'contrast ratio'}
        result,report=revise([custom],groups([old]),groups([old]))
        self.assertEqual(result,[custom]);self.assertEqual(report['conflicts'],[])
    def test_removed_official_terms_are_retired_only_if_untouched(self):
        old=entry('旧词','old term');other=entry('自定义旧词','personal',note='personal note')
        result,report=revise([old,other],groups([old,other]),{})
        self.assertEqual(result,[other]);self.assertEqual(report['removed'],1)
    def test_deleted_terms_stay_deleted_but_previously_unshipped_ambiguity_is_added(self):
        old=entry('用户删除','deleted');a=entry('回显','input view');b=entry('回显','screen monitoring')
        result,report=revise([],groups([old,a,b]),groups([old,a,b]),preserve_missing={bundled.key(old['zh'])})
        self.assertEqual(result,[a,b]);self.assertEqual(report['preserved_deletions'],1)
    def test_new_official_word_can_update_an_untouched_older_bundled_default(self):
        old=entry('新增官方词','curated old');new=entry('新增官方词','official new')
        result,report=revise([old],{},groups([new]),previous_defaults=groups([old]))
        self.assertEqual(result[0]['en'],'official new');self.assertEqual(report['conflicts'],[])
    def test_converging_official_standard_merges_without_losing_personal_metadata(self):
        old={**entry('同词','old',note='first personal note',variants=['first alias']),'source':'personal provenance A'}
        existing={**entry('同词','new',note='second personal note',variants=['second alias']),'source':'personal provenance B'}
        result,report=revise([old,existing],groups([old,existing]),groups([entry('同词','new')]))
        self.assertEqual(len(result),1);self.assertEqual(report['merged'],1)
        for original in (old,existing):
            self.assertIn(original['note'],result[0]['note']);self.assertIn(original['source'],result[0]['source'])
            self.assertTrue(set(original['variants'])<=set(result[0]['variants']))
    def test_completed_latest_revision_does_not_reapply_an_older_missing_receipt(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'NOVATERM_DATA_DIR':directory}):
            file=Path(directory)/'lexicon.json';store.atomic_json(file,json.loads((bundled.ROOT/'team.json').read_text('utf-8')))
            bundled.upgrade_local(file);before=file.read_bytes()
            bundled.receipt(file,bundled.manifest()[0]['id']).unlink()
            bundled.upgrade_local(file);self.assertEqual(file.read_bytes(),before)
            self.assertEqual(bundled.status(file)['conflicts'],[])
    def test_real_old_2515_snapshot_upgrades_without_adding_competing_old_translations(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'NOVATERM_DATA_DIR':directory}):
            file=Path(directory)/'lexicon.json';old=json.loads((bundled.ROOT/'bundled-english-20261026.json').read_text('utf-8'))
            store.atomic_json(file,old);bundled.upgrade_local(file)
            data=json.loads(file.read_text('utf-8'));self.assertEqual(len(data),2456)
            revision=next(batch for batch in bundled.manifest() if batch.get('mode')=='revision')
            self.assertEqual(bundled.read_receipt(file,revision['id'])['updated'],9)
            self.assertEqual(bundled.status(file)['removed'],60)
            self.assertEqual(bundled.status(file)['conflicts'],[])
            changed=[e for e in data if e['zh']=='防松螺母'];self.assertEqual([e['en'] for e in changed],['anti-loosening nut'])
            before=file.read_bytes();bundled.upgrade_local(file);self.assertEqual(file.read_bytes(),before)
    def test_restored_pre_import_snapshot_is_not_kept_small_by_its_old_receipt(self):
        old_batch=bundled.manifest()[0]
        old=json.loads((bundled.ROOT/old_batch['catalog']).read_text('utf-8'))
        keys={bundled.key(v) for v in old_batch['terms']};base=[e for e in old if bundled.key(e['zh']) not in keys]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'NOVATERM_DATA_DIR':directory}):
            file=Path(directory)/'lexicon.json';store.atomic_json(file,base);raw=file.read_bytes()
            store.atomic_json(bundled.receipt(file,old_batch['id']),{'schema':1,'id':old_batch['id'],'completed':True,
                'added':1880,'conflicts':[],'backup':'','before_hash':hashlib.sha256(raw).hexdigest()})
            bundled.upgrade_local(file);self.assertEqual(len(json.loads(file.read_text('utf-8'))),2456)

    def test_revision_write_failure_keeps_original_and_recovers_without_duplicate_standards(self):
        latest=next(batch for batch in reversed(bundled.manifest()) if batch.get('mode')=='revision');older=bundled.manifest()[0]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'NOVATERM_DATA_DIR':directory}):
            file=Path(directory)/'lexicon.json';store.atomic_json(file,json.loads((bundled.ROOT/older['catalog']).read_text('utf-8')))
            store.atomic_json(bundled.receipt(file,older['id']),{'schema':1,'id':older['id'],'completed':True,'added':1880,'conflicts':[],'backup':''})
            before=file.read_bytes();write=store.atomic_json
            def fail(path,data):
                if Path(path)==file:raise PermissionError('fixture lock')
                return write(path,data)
            with patch.object(store,'atomic_json',side_effect=fail):bundled.upgrade_local(file)
            self.assertEqual(file.read_bytes(),before);self.assertIn('error',bundled.status(file))
            self.assertFalse(bundled.read_receipt(file,latest['id'])['completed'])
            bundled.upgrade_local(file);self.assertEqual(len(json.loads(file.read_text('utf-8'))),2456)
            self.assertTrue(bundled.read_receipt(file,latest['id'])['completed']);self.assertNotIn('error',bundled.status(file))


if __name__=='__main__':unittest.main()
