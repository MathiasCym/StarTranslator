import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.glossary import audit, store, writer
from backend.glossary.loader import Glossary
from backend.models import GlossaryEntry, Segment
from backend.matcher.rules import check_rules
from backend.server import app


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'NOVATERM_DATA_DIR':str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def test_official_terms_aliases_and_units(self):
        entries = store.seed_entries()
        by = {e['zh']: e for e in entries}
        self.assertEqual(by['逐点校正']['en'], 'pixel-level calibration')
        self.assertEqual(by['逐点亮色度校正']['en'], 'Pixel Level Brightness and Chroma Calibration')
        self.assertIn('point-by-point calibration', by['逐点校正']['variants'])
        self.assertEqual(by['画质引擎']['en'], 'Image Booster')
        self.assertEqual(by['VMP']['en'], 'Vision Management Platform')
        self.assertEqual(by['照度']['en'], 'illuminance')
        self.assertNotIn('lux', [x.lower() for x in by['照度']['variants']])
        self.assertNotIn('nit', [x.lower() for x in by['亮度']['variants']])
        self.assertEqual(sum(e['zh']=='全灰阶校正' for e in entries), 1)
        self.assertEqual(audit.merge(entries)[0], entries)
        g = Glossary([GlossaryEntry(**e) for e in entries])
        seg = Segment(id='1',file='test.docx',para=1,locator={},text='300 nits, 30 lux, point-by-point calibration, per-pixel calibration.')
        self.assertEqual(check_rules([seg], g), [])

    def test_migration_keeps_team_content_and_backups_once(self):
        local = self.root/'lexicon.json'
        custom = GlossaryEntry('团队术语','Team-specific term',note='保留备注').to_dict()
        old = GlossaryEntry('逐点校正','point-by-point calibration',note='团队补充',variants=['team alias']).to_dict()
        raw = json.dumps([custom,old],ensure_ascii=False).encode('utf-8')
        local.write_bytes(raw)
        first = store.read()
        self.assertIn(custom,first['entries'])
        term = next(e for e in first['entries'] if e['zh']=='逐点校正')
        self.assertIn('团队补充',term['note']); self.assertIn('team alias',term['variants'])
        self.assertEqual(next(self.root.glob('*.bak')).read_bytes(),raw)
        saved = store.save([custom], first['fingerprint'])
        self.assertEqual(store.read()['entries'],[custom])  # don't resurrect deliberately deleted rows every launch

    def test_custom_translation_conflict_not_overwritten(self):
        custom = GlossaryEntry('逐点校正','Approved Company Wording',note='团队自定').to_dict()
        merged, report = audit.merge([custom])
        self.assertIn(custom, merged)
        self.assertIn('逐点校正',[c['zh'] for c in report['conflicts']])

    def test_edit_json_targets_opened_file_and_preserves_metadata(self):
        active = store.read(); before = Path(active['path']).read_bytes()
        other = self.root/'other.json'
        store.atomic_json(other,[GlossaryEntry('测试','test',priority=1,source='来源存档').to_dict()])
        current = store.read(other); rows = store.table_rows(current)
        rows[0][1] = 'edited'
        store.edit_table(str(other),rows,store.table_columns(current),current['fingerprint'])
        result = store.read(other)['entries'][0]
        self.assertEqual(result['source'],'来源存档'); self.assertEqual(result['priority'],1)
        self.assertEqual(result['en'],'edited')
        self.assertEqual(Path(active['path']).read_bytes(),before)

    def test_incomplete_grid_row_never_silently_drops(self):
        current = store.read(); before = Path(current['path']).read_bytes()
        rows = store.table_rows(current); rows[0][1] = ''
        with self.assertRaises(ValueError):
            store.edit_table(current['path'],rows,store.table_columns(current),current['fingerprint'])
        self.assertEqual(Path(current['path']).read_bytes(),before)

    def test_shared_not_implicitly_migrated_and_merge_checks_conflict(self):
        store.read()
        shared = self.root/'shared.json'
        old = GlossaryEntry('逐点校正','point-by-point calibration').to_dict()
        store.atomic_json(shared,[old]); current=store.select(shared)
        self.assertEqual(current['entries'],[old])
        client=app.test_client()
        response=client.post('/api/lexicon/reviewed',json={'fingerprint':'stale'})
        self.assertEqual(response.status_code,409)
        response=client.post('/api/lexicon/reviewed',json={'fingerprint':current['fingerprint']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['entries'][0]['en'],'pixel-level calibration')

    def test_unrecognized_spreadsheet_columns_survive_grid_roundtrip(self):
        path=self.root/'extra.csv'
        path.write_text('中文,英文,负责人,来源\n测试,test,Alice,原始依据\n',encoding='utf-8-sig')
        client=app.test_client()
        data=client.get('/api/glossary/table',query_string={'path':str(path)}).json
        self.assertEqual(data['rows'][0][2],'Alice')
        data['rows'][0][1]='edited'
        response=client.post('/api/glossary/table',json=data)
        self.assertEqual(response.status_code,200)
        self.assertIn('Alice',path.read_text(encoding='utf-8-sig'))


if __name__ == '__main__': unittest.main()
