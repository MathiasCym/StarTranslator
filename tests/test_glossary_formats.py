import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.glossary import audit, formats, store
from backend.models import GlossaryEntry, Segment
from backend.matcher.rules import check_rules
from backend.glossary.loader import Glossary
from backend.server import app


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'NOVATERM_DATA_DIR': str(self.folder)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_seed_has_short_standards_and_expanded_aliases(self):
        entries = store.seed_entries()
        by_zh = {e['zh']: e for e in entries}
        self.assertGreaterEqual(len(entries),625)
        self.assertEqual(len(entries),len({(e['zh'],e['en']) for e in entries}))
        for patch_ in formats.manifest()['patches']:
            entry = by_zh[patch_['zh']]
            self.assertEqual(entry['en'], patch_['en'])
            for alias in patch_['variants']:
                self.assertIn(alias, entry['variants'])
                glossary = Glossary([GlossaryEntry(**entry)])
                self.assertEqual(glossary.lookup_exact(alias)[0].en, patch_['en'])
                segment = Segment(id='1', file='test.docx', text=alias, locator='body/0')
                self.assertEqual(check_rules([segment], glossary), [])
        self.assertEqual(by_zh['线路板/电路板']['en'], 'PCB')
        self.assertIn('Printed Circuit Board', by_zh['线路板/电路板']['variants'])
        self.assertEqual(by_zh['AI高精度定位技术']['en'], 'AI high-precision positioning technology')
        self.assertEqual(audit.merge(entries)[0], entries)

    def test_migration_preserves_metadata_and_team_overrides(self):
        patch_ = formats.manifest()['patches'][0]
        old = GlossaryEntry(patch_['zh'], patch_['old'], variants=['Team alias'],
                            machine_variants=['retrieval form'], wrong_variants=[patch_['variants'][0], 'bad form'],
                            priority=3, note='Team note', source='Team source').to_dict()
        custom = GlossaryEntry(patch_['zh'], 'Team-specific translation', note='Keep').to_dict()
        local = self.folder / 'lexicon.json'
        raw = json.dumps([old, custom], ensure_ascii=False).encode('utf-8')
        local.write_bytes(raw)
        # Simulate a library that already received the earlier cinema update.
        store.atomic_json(self.folder / ('lexicon-audit-' + audit.manifest()['id'] + '.json'), {})
        result = store.read()
        self.assertEqual(len(result['entries']),len({(e['zh'],e['en']) for e in result['entries']}))
        changed = result['entries'][0]
        self.assertEqual(changed['en'], patch_['en'])
        self.assertEqual(changed['variants'], ['Team alias', *patch_['variants']])
        for field in ('priority', 'note', 'source', 'machine_variants'):
            self.assertEqual(changed[field], old[field])
        self.assertEqual(changed['wrong_variants'], ['bad form'])
        self.assertEqual(result['entries'][1], custom)
        self.assertEqual(next(self.folder.glob('*.bak')).read_bytes(), raw)
        # Deliberate later edits/deletions are not undone on every launch.
        saved = store.save([custom], result['fingerprint'])
        self.assertEqual(store.read()['entries'], [custom])
        self.assertEqual(len(list(self.folder.glob('*.bak'))), 2)

    def test_shared_file_requires_explicit_merge_and_current_fingerprint(self):
        patch_ = formats.manifest()['patches'][0]
        shared = self.folder / 'shared.json'
        old = GlossaryEntry(patch_['zh'], patch_['old'], note='Shared note').to_dict()
        store.atomic_json(shared, [old])
        current = store.select(shared)
        self.assertEqual(store.read()['entries'], [old])
        client = app.test_client()
        before = shared.read_bytes()
        response = client.post('/api/lexicon/reviewed', json={'fingerprint': 'stale'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(shared.read_bytes(), before)
        response = client.post('/api/lexicon/reviewed', json={'fingerprint': current['fingerprint']})
        self.assertEqual(response.status_code, 200)
        changed = next(e for e in response.json['entries'] if e['zh'] == patch_['zh'])
        self.assertEqual(changed['en'], patch_['en'])
        self.assertIn(patch_['variants'][0], changed['variants'])
        self.assertEqual(changed['note'], 'Shared note')


if __name__ == '__main__':
    unittest.main()
