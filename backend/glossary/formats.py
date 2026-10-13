"""Split reviewed acronym expansions without replacing team-specific wording."""
import copy
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'glossary' / 'format-20261008.json'


def manifest():
    return json.loads(PATH.read_text(encoding='utf-8'))


def merge(entries):
    entries = copy.deepcopy(entries)
    patches = {(p['zh'], p['old']): p for p in manifest()['patches']}
    changes = []
    for entry in entries:
        patch = patches.get((entry['zh'], entry['en']))
        if not patch:
            continue
        old = entry['en']
        entry['en'] = patch['en']
        values = [*entry.get('variants', []), *patch['variants']]
        seen = {entry['en'].casefold()}
        entry['variants'] = []
        for value in values:
            key = value.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                entry['variants'].append(value.strip())
        # A newly accepted expansion must never remain a confirmed wrong form.
        entry['wrong_variants'] = [v for v in entry.get('wrong_variants', [])
                                   if v.strip().casefold() not in seen]
        changes.append({'zh': entry['zh'], 'old': [old], 'new': entry['en']})
    return entries, changes


def upgrade_local(path):
    """Apply once to the local library; shared files require an explicit merge."""
    from . import store
    version = manifest()['id']
    receipt = path.parent / ('lexicon-format-' + version + '.json')
    if receipt.exists():
        return
    with store.edit_lock(path):
        raw = path.read_bytes()
        entries, changes = merge(store.validate(json.loads(raw.decode('utf-8-sig'))))
        report = {'id': version, 'changes': changes}
        if changes:
            backup = Path(str(path) + '.before-' + version + '.bak')
            if not backup.exists():
                backup.write_bytes(raw)
            store.atomic_json(path, store.validate(entries))
            report['backup'] = str(backup)
        store.atomic_json(receipt, report)
