"""Versioned, attributable corrections without replacing unrelated team edits."""
import copy
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'glossary' / 'audit-20260929.json'


def manifest():
    return json.loads(PATH.read_text(encoding='utf-8'))


def merge(entries):
    review = manifest()
    entries = copy.deepcopy(entries)
    changes, conflicts = [], []
    for patch in review['patches']:
        old = {tuple(pair) for pair in patch['old']}
        indices = [i for i, e in enumerate(entries)
                   if (e['zh'], e['en']) in old or
                   (e['zh'] == patch['zh'] and e['en'].casefold() == patch['en'].casefold())]
        related = {patch['zh'], *(pair[0] for pair in old)}
        custom = [e for i, e in enumerate(entries) if e['zh'] in related and i not in indices]
        if custom:
            conflicts.append({'zh': patch['zh'], 'current': [e['en'] for e in custom], 'suggested': patch['en']})
        if not indices and custom:
            continue
        matching = [entries[i] for i in indices]
        original = copy.deepcopy(matching)
        item = copy.deepcopy(matching[0]) if matching else {
            'zh': patch['zh'], 'en': patch['en'], 'variants': [], 'machine_variants': [],
            'wrong_variants': [], 'priority': 1, 'note': '', 'source': ''}
        item.update(zh=patch['zh'], en=patch['en'], priority=1)
        invalid = {s.casefold() for s in patch['invalid_forms']}
        invalid.update(s.casefold() for s in patch['wrong_variants'])
        # Retain custom aliases and annotations, but do not retain a known bad form as accepted.
        for field in ('variants', 'machine_variants', 'wrong_variants'):
            values = [v for e in matching for v in e.get(field, [])] + patch.get(field, [])
            seen = set()
            item[field] = []
            for v in values:
                key = v.casefold()
                if key == item['en'].casefold() or key in seen or (field == 'variants' and key in invalid):
                    continue
                seen.add(key); item[field].append(v)
        accepted = {v.casefold() for v in [item['en'], *item['variants']]}
        item['wrong_variants'] = [v for v in item['wrong_variants'] if v.casefold() not in accepted]
        for field in ('note', 'source'):
            parts = list(dict.fromkeys(e.get(field, '') for e in matching if e.get(field)))
            addition = ('2026-09-29 校订：' + patch['note']) if field == 'note' else (
                '2026-09-29 核对依据：' + ', '.join(patch['refs']))
            if addition not in '\n'.join(parts):
                parts.append(addition)
            item[field] = '\n'.join(parts)
        if matching:
            entries[indices[0]] = item
            for i in reversed(indices[1:]):
                del entries[i]
        else:
            entries.append(item)
        if original != [item]:
            changes.append({'zh':item['zh'], 'old':[e['en'] for e in original], 'new':item['en']})
    pending_originals = {tuple(pair) for pair in review['pending_originals']}
    for e in entries:
        if (e['zh'], e['en']) in pending_originals:
            note = '待专业确认（2026-09-29）：' + review['pending'][e['zh']]
            if note not in e.get('note', ''):
                e['note'] = (e.get('note', '') + '\n' + note).strip()
            e['priority'] = 3
    from .formats import merge as merge_formats
    entries, format_changes = merge_formats(entries)
    changes.extend(format_changes)
    from .corrections import merge as merge_corrections
    entries, corrected = merge_corrections(entries)
    changes.extend(corrected)
    from .bit_depth import merge as merge_bit_depth
    entries, depth_changes = merge_bit_depth(entries)
    changes.extend(depth_changes)
    return entries, {'id':review['id'], 'changes':changes, 'conflicts':conflicts,
                     'pending':review['pending']}


def upgrade_local(path):
    from . import store
    version = manifest()['id']
    receipt = path.parent / ('lexicon-audit-' + version + '.json')
    if receipt.exists():
        return
    with store.edit_lock(path):
        raw = path.read_bytes()
        entries, report = merge(store.validate(json.loads(raw.decode('utf-8-sig'))))
        backup = Path(str(path) + '.before-' + version + '.bak')
        if not backup.exists():
            backup.write_bytes(raw)
        store.atomic_json(path, store.validate(entries))
        report['backup'] = str(backup)
        store.atomic_json(receipt, report)
