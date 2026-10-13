"""Team-approved additions from the 2026-10-10 internal trial."""
import copy
import json
from . import store

VERSION = '20261010'
TERMS = {'缩放显示': 'Scaling display', '认证机构': 'Certification Institution'}


def merge(entries):
    entries = copy.deepcopy(entries); changes = []
    for zh, en in TERMS.items():
        matches = [entry for entry in entries if entry['zh'] == zh]
        if not matches:
            entries.append({'zh': zh, 'en': en, 'priority': 1, 'variants': [], 'machine_variants': [], 'wrong_variants': [],
                'note': '部门内部测试确认的标准译法。', 'source': 'MathiasCym / 2026-10-10'})
            changes.append({'zh': zh, 'old': [], 'new': en})
        for entry in matches:
            if entry['en'] != en: changes.append({'zh': zh, 'old': [entry['en']], 'new': en})
            entry['en'] = en; entry['priority'] = 1
            entry['variants'] = [v for v in entry.get('variants', []) if v.casefold() != en.casefold()]
            entry['wrong_variants'] = [v for v in entry.get('wrong_variants', []) if v.casefold() != en.casefold()]
    return entries, changes


def upgrade_local(path):
    receipt = path.parent / ('lexicon-corrections-' + VERSION + '.json')
    if receipt.exists(): return
    with store.edit_lock(path):
        entries, changes = merge(store.validate(json.loads(path.read_text(encoding='utf-8-sig'))))
        if changes: store.atomic_json(path, store.validate(entries))
        store.atomic_json(receipt, {'id': VERSION, 'changes': changes})
